"""Deterministic policy semantics, shared by the local reference and flow design."""
import hashlib
import json
from collections import Counter
from datetime import date

from .contracts import BoundaryError, EvaluationRequest

POLICY = "AMH-RAD-2026"
VERSION = "1.0"
REQUIRED = {f"{POLICY}-R0{i}" for i in range(1, 4)}
RULE_KINDS = {"conservative-duration", "conservative-modalities", "missing-evidence-review"}
ALLOWED_INDICATIONS = {"RadicularPain", "SpinalStenosis", "PersistentLowBackPain"}
ALLOWED_MEDICATIONS = {"NSAID", "MuscleRelaxant", "NeuropathicPainAgent"}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def select_rules(rules: list[dict], request: EvaluationRequest, as_of: date) -> list[dict]:
    applicable = [r for r in rules if r["active"] is True and
                  r["policyNumber"] == request.policyNumber and r["policyVersion"] == request.policyVersion and
                  r["cptCode"] == request.cptCode and date.fromisoformat(r["effectiveFrom"]) <= as_of and
                  (r["effectiveTo"] is None or as_of < date.fromisoformat(r["effectiveTo"]))]
    if {r["ruleId"] for r in applicable} != REQUIRED or len(applicable) != 3:
        raise BoundaryError("PolicyCoverageInvalid")
    if {r["kind"] for r in applicable} != RULE_KINDS:
        raise BoundaryError("UnsupportedRuleKind")
    by_kind = {r["kind"]: r for r in applicable}
    duration, modalities, escalation = [by_kind[k] for k in
        ("conservative-duration", "conservative-modalities", "missing-evidence-review")]
    if (duration["enforcement"] != "Strict_Block" or modalities["enforcement"] != "Strict_Block" or
            escalation["enforcement"] != "Medical_Director_Review"):
        raise BoundaryError("UnsupportedEnforcement")
    if (type(duration["minConservativeWeeks"]) is not int or duration["minConservativeWeeks"] < 6 or
            type(modalities["minPtSessionsPerWeek"]) is not int or modalities["minPtSessionsPerWeek"] < 2 or
            modalities["requiresPt"] is not True or modalities["requiresPharmacology"] is not True or
            duration["requiresFailedTreatment"] is not True):
        raise BoundaryError("PolicyThresholdInvalid")
    # Escalation rules have no treatment thresholds. Null is intentional.
    if (any(escalation[k] is not None for k in ("minConservativeWeeks", "minPtSessionsPerWeek")) or
            any(escalation[k] not in (None, False) for k in ("requiresPt", "requiresPharmacology", "requiresFailedTreatment"))):
        raise BoundaryError("EscalationRuleHasEligibilityDefaults")
    return sorted(applicable, key=lambda r: r["ruleId"])


def assess(request: EvaluationRequest, evidence: dict, rules: list[dict], source_receipts: dict) -> dict:
    reasons = []
    def result(status, codes):
        return {"status": status, "reasonCodes": codes, "verifiedFacts": verified,
                "authorizationGranted": False, "claimWriteCount": 0}

    verified = {"completedWeeks": None, "weeklyPtCounts": [], "pharmacologyVerified": None,
                "treatmentFailedOrWorsened": None, "redFlagsVerified": False}
    if any(evidence[k] != getattr(request, attr) for k, attr in
           [("claimId", "claimId"), ("memberId", "memberId"), ("cptCode", "cptCode"),
            ("policyNumber", "policyNumber"), ("policyVersion", "policyVersion")]):
        return result("InsufficientEvidence", ["ClaimEvidenceBindingMismatch"])
    if evidence.get("synthetic") is not True or not evidence.get("attestedBy") or not evidence.get("attestedAt"):
        return result("InsufficientEvidence", ["EvidenceNotAttested"])
    references = {r.documentId: r for r in request.evidenceReferences}
    if len(references) != len(request.evidenceReferences):
        return result("InsufficientEvidence", ["DuplicateEvidenceReference"])
    for document_id, ref in references.items():
        receipt = source_receipts.get(document_id)
        if receipt is None or ref.sha256 != receipt["sha256"] or ref.page > receipt["pages"]:
            return result("InsufficientEvidence", ["InvalidAgentEvidenceReference"])
    if evidence.get("contradictions"):
        return result("MedicalDirectorReviewRequired", ["ContradictoryEvidence"])
    verified["redFlagsVerified"] = evidence.get("redFlagsVerified") is True
    if verified["redFlagsVerified"]:
        required = {"clinical-note"}
        if not required <= set(source_receipts) or not required <= set(references):
            return result("InsufficientEvidence", ["RedFlagClinicalNoteMissing"])
        return result("MedicalDirectorReviewRequired", ["VerifiedRedFlagClinicalPath"])
    if evidence.get("redFlagsVerified") is None:
        return result("InsufficientEvidence", ["ClinicalPathUnknown"])
    required = {"pt-log", "clinical-note", "medication-log"}
    if not required <= set(source_receipts) or not required <= set(references):
        return result("InsufficientEvidence", ["RequiredClinicalRecordsMissing"])
    if evidence.get("indication") not in ALLOWED_INDICATIONS:
        return result("InsufficientEvidence", ["ClinicalIndicationNotVerified"])
    try:
        start = date.fromisoformat(evidence["therapyStart"])
        end = date.fromisoformat(evidence["therapyEndExclusive"])
        session_dates = [date.fromisoformat(s["date"]) for s in evidence["sessions"] if s["attended"] is True]
        if end <= start or len(session_dates) != len(set(session_dates)) or any(d < start or d >= end for d in session_dates):
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        return result("InsufficientEvidence", ["InvalidTreatmentLog"])
    weeks = (end - start).days // 7
    if weeks > 104:
        return result("InsufficientEvidence", ["InvalidTreatmentLog"])
    counts = Counter((d-start).days // 7 for d in session_dates)
    verified["completedWeeks"] = weeks
    verified["weeklyPtCounts"] = [counts[i] for i in range(weeks)]
    duration_rule = next(r for r in rules if r["kind"] == "conservative-duration")
    modalities = next(r for r in rules if r["kind"] == "conservative-modalities")
    if weeks < duration_rule["minConservativeWeeks"]:
        reasons.append("InsufficientConservativeDuration")
    # Each complete treatment week must meet the minimum. An average is unsafe.
    if weeks == 0 or any(n < modalities["minPtSessionsPerWeek"] for n in verified["weeklyPtCounts"]):
        reasons.append("PtFrequencyBelowMinimum")
    meds = evidence.get("medications")
    if not isinstance(meds, list):
        return result("InsufficientEvidence", ["PharmacologyUnknown"])
    try:
        covered = set()
        for medication in meds:
            if medication["category"] in ALLOWED_MEDICATIONS and medication["verified"] is True:
                ms, me = date.fromisoformat(medication["start"]), date.fromisoformat(medication["endExclusive"])
                if me <= ms:
                    raise ValueError()
                for i in range((end-start).days):
                    from datetime import timedelta
                    d = start + timedelta(days=i)
                    if ms <= d < me:
                        covered.add(d)
        verified["pharmacologyVerified"] = len(covered) == (end-start).days
    except (KeyError, TypeError, ValueError):
        return result("InsufficientEvidence", ["InvalidMedicationLog"])
    if not verified["pharmacologyVerified"]:
        reasons.append("PharmacologyNotDocumentedForRegimen")
    outcome = evidence.get("treatmentFailedOrWorsened")
    if outcome is None:
        return result("InsufficientEvidence", ["TreatmentOutcomeUnknown"])
    if type(outcome) is not bool:
        return result("InsufficientEvidence", ["TreatmentOutcomeInvalid"])
    verified["treatmentFailedOrWorsened"] = outcome
    if not outcome:
        reasons.append("FailedTreatmentNotEstablished")
    return result("PolicyCriteriaNotMet" if reasons else "EligibleForHumanReview", reasons or ["ConservativeCriteriaVerified"])

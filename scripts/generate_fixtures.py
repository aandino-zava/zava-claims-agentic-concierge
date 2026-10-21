"""Generate deterministic, fictitious records. No Azure documents are modified."""
import csv
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from claims_concierge.contracts import DecisionRequest, EvaluationRequest

REVIEWER = "00000000-0000-4000-8000-000000000001"
REQUESTER = "00000000-0000-4000-8000-000000000003"
UNAUTHORIZED = "00000000-0000-4000-8000-000000000002"
TENANT = "00000000-0000-4000-8000-000000000004"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+"\n", encoding="utf-8")


def generate(root=ROOT / "tests/fixtures"):
    root.mkdir(parents=True, exist_ok=True)
    common = {"policyNumber": "AMH-RAD-2026", "policyVersion": "1.0", "cptCode": "72148",
              "active": True, "effectiveFrom": "2026-01-01", "effectiveTo": None,
              "clinicalPath": "Conservative", "minConservativeWeeks": None, "minPtSessionsPerWeek": None,
              "requiresPt": None, "requiresPharmacology": None, "requiresFailedTreatment": None}
    rules = [
        {**common, "ruleId": "AMH-RAD-2026-R01", "kind": "conservative-duration", "enforcement": "Strict_Block",
         "minConservativeWeeks": 6, "requiresPt": True, "requiresPharmacology": True, "requiresFailedTreatment": True,
         "naturalLanguageRule": "Lumbar Spine MRI (CPT 72148) requires documented failure of a minimum 6-week conservative therapy regimen prior to advanced imaging authorization."},
        {**common, "ruleId": "AMH-RAD-2026-R02", "kind": "conservative-modalities", "enforcement": "Strict_Block",
         "minPtSessionsPerWeek": 2, "requiresPt": True, "requiresPharmacology": True,
         "naturalLanguageRule": "Conservative therapy documentation must substantiate active physical therapy (minimum 2 sessions/week) combined with documented pharmacologic intervention (NSAIDs, muscle relaxants, or neuropathic pain agents)."},
        {**common, "ruleId": "AMH-RAD-2026-R03", "kind": "missing-evidence-review", "clinicalPath": "Any",
         "enforcement": "Medical_Director_Review",
         "naturalLanguageRule": "Prior authorization appeals lacking explicit clinical duration logs or physical therapy notes must be halted from automated approval and routed to Medical Director Review."},
    ]
    evidence, claims, requests = [], [], []
    scenarios = [("complete", 6, 2), ("missing-attachments", 6, 2), ("short-duration", 5, 2),
                 ("low-frequency", 6, 1), ("missing-pharmacology", 6, 2), ("contradictory", 6, 2),
                 ("red-flag", 0, 0), ("symptoms-improved", 6, 2)]
    for i, (name, weeks, frequency) in enumerate(scenarios, 1):
        claim_id, member = f"SYN-CLM-{1000+i}", f"SYN-MEMBER-{1000+i}"
        start, end = date(2026, 8, 3), date(2026, 8, 3)+timedelta(weeks=weeks)
        sessions = [{"date": (start+timedelta(weeks=w, days=d)).isoformat(), "attended": True}
                    for w in range(weeks) for d in (1, 3)[:frequency]]
        item = {"claimId": claim_id, "memberId": member, "cptCode": "72148", "policyNumber": "AMH-RAD-2026",
                "policyVersion": "1.0", "synthetic": True, "fixtureName": name,
                "attestationMode": "SyntheticFixture", "attestedBy": REVIEWER,
                "attestedAt": "2026-10-01T12:00:00+00:00", "indication": "RadicularPain",
                "therapyStart": start.isoformat(), "therapyEndExclusive": end.isoformat(), "sessions": sessions,
                "medications": [{"category": "NSAID", "start": start.isoformat(), "endExclusive": end.isoformat(), "verified": True}],
                "treatmentFailedOrWorsened": name != "symptoms-improved", "redFlagsVerified": name == "red-flag",
                "contradictions": ["Illustrative clinical notes disagree about the course."] if name == "contradictory" else [], "sources": []}
        if name == "missing-pharmacology":
            item["medications"] = []
        sources = []
        folder = root / "sources" / name
        folder.mkdir(parents=True, exist_ok=True)
        if name == "missing-attachments":
            appeal = folder / "appeal.txt"
            appeal.write_text("SYNTHETIC POC FIXTURE. The appeal alleges eight weeks of twice-weekly PT and says logs are attached. No logs accompany this fixture. These assertions are unverified.\n", encoding="utf-8")
            sources.append(("appeal-letter", appeal))
        else:
            keys = ("claimId", "memberId", "cptCode", "indication", "treatmentFailedOrWorsened", "redFlagsVerified", "contradictions", "therapyStart", "therapyEndExclusive")
            note = {k: item[k] for k in keys}
            note["untrustedNarrative"] = "SYNTHETIC POC FIXTURE. These structured facts are generated test data, not a clinical attestation."
            write_json(folder / "clinical-note.json", note)
            sources.append(("clinical-note", folder / "clinical-note.json"))
            if name != "red-flag":
                with (folder / "pt-log.csv").open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["date", "attended"])
                    writer.writeheader()
                    writer.writerows({"date": s["date"], "attended": str(s["attended"]).lower()} for s in sessions)
                write_json(folder / "medication-log.json", item["medications"])
                sources += [("pt-log", folder / "pt-log.csv"), ("medication-log", folder / "medication-log.json")]
        item["sources"] = [{"documentId": doc, "path": path.relative_to(root).as_posix(), "pages": 1,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for doc, path in sources]
        evidence.append(item)
        claims.append({"claimId": claim_id, "memberId": member, "cptCode": "72148", "synthetic": True,
                       "version": 1, "status": "Under Review", "serviceDate": "2026-09-20"})
        requests.append({"schemaVersion": "1.0", "claimId": claim_id, "memberId": member, "cptCode": "72148",
                         "policyNumber": "AMH-RAD-2026", "policyVersion": "1.0", "claimVersion": 1,
                         "correlationId": str(uuid5(NAMESPACE_URL, "zava/correlation/"+name)),
                         "idempotencyKey": str(uuid5(NAMESPACE_URL, "zava/request/"+name)),
                         "evidenceReferences": [{"documentId": s["documentId"], "sha256": s["sha256"], "page": 1} for s in item["sources"]],
                         "proposedFacts": {"documentedTherapyWeeks": 8, "ptSessionsPerWeek": 2,
                                           "ptModalityPresent": True, "pharmaPresent": True, "treatmentFailedOrWorsened": True},
                         "clinicalSummary": "Illustrative model proposal. All operative facts require independent checks.",
                         "agentRecommendation": "RecommendHumanReview"})
    for name, content in [("policy-rules.json", rules), ("evidence.json", evidence), ("claims.json", claims), ("requests.json", requests)]:
        write_json(root / name, content)
    write_json(ROOT / "dataverse/policy-seed.json", rules)
    write_json(ROOT / "contracts/claim-evaluation.schema.json", EvaluationRequest.model_json_schema())
    write_json(ROOT / "contracts/reviewer-decision.schema.json", DecisionRequest.model_json_schema())
    write_json(ROOT / "config/simulation.example.json", {"tenantId": TENANT, "reviewerObjectIds": [REVIEWER],
               "requesterObjectIds": [REVIEWER, REQUESTER], "unauthorizedObjectId": UNAUTHORIZED, "mode": "Simulated"})


if __name__ == "__main__":
    generate()
    print("Generated 3 seed rules, 8 synthetic scenarios, source records, and strict contracts.")

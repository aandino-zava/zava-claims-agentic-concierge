import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from pydantic import ValidationError

from .contracts import BoundaryError, DecisionRequest, EvaluationRequest, TrustedContext
from .evaluation import assess, fingerprint, select_rules
from .repositories import EvaluationStore


class Gatekeeper:
    """Local reference for the approved Power Automate design; never a deployed API."""
    def __init__(self, tenant_id, reviewers, requesters, repository, store, claims, now=None):
        self.tenant_id = tenant_id
        self.reviewers, self.requesters = frozenset(reviewers), frozenset(requesters)
        self.repository, self.store, self.claims = repository, store, claims
        self.now = now or (lambda: datetime.now(timezone.utc))
        if claims.mode != "Simulated":
            raise BoundaryError("LiveClaimsWritesDisabled")

    def authorize(self, context: TrustedContext, capability, allowed):
        if not context.authenticated or context.tenant_id != self.tenant_id:
            raise BoundaryError("UnauthenticatedOrWrongTenant")
        if capability not in context.capabilities or context.object_id not in allowed:
            raise BoundaryError("UnauthorizedReviewer" if capability == "review" else "UnauthorizedCaller")

    def submit(self, payload_json: str, context: TrustedContext):
        self.authorize(context, "evaluate", self.requesters)
        try:
            request = EvaluationRequest.model_validate_json(payload_json)
        except ValidationError:
            raise BoundaryError("InvalidEvaluationPayload") from None
        payload = request.model_dump(mode="json")
        digest = fingerprint({"caller": context.object_id, "payload": payload})
        key = self.tenant_id + ":" + str(request.idempotencyKey)
        with self.store.connect() as c:
            row = c.execute("SELECT payload_hash,body FROM evaluations WHERE request_key=?", (key,)).fetchone()
        if row:
            if row[0] != digest:
                raise BoundaryError("IdempotencyConflict")
            return {**json.loads(row[1]), "duplicateSubmission": True}
        selected, evidence, receipts = [], {}, {}
        try:
            claim = self.claims.get(request.claimId)
            if claim["synthetic"] is not True:
                raise BoundaryError("RealClaimForbidden")
            if claim["version"] != request.claimVersion:
                raise BoundaryError("StaleClaim")
            if claim["memberId"] != request.memberId or claim["cptCode"] != request.cptCode:
                raise BoundaryError("ClaimIdentityMismatch")
            selected = select_rules(self.repository.policy(), request, date.fromisoformat(claim["serviceDate"]))
            evidence = self.repository.clinical(request.claimId)
            if evidence["attestedBy"] not in self.reviewers:
                raise BoundaryError("EvidenceAttestorNotAuthorized")
            attested_at = datetime.fromisoformat(evidence["attestedAt"])
            if attested_at.tzinfo is None or attested_at > self.now():
                raise BoundaryError("EvidenceAttestationInvalid")
            receipts = self.repository.sources(evidence)
            if evidence.get("redFlagsVerified") is not True:
                if date.fromisoformat(evidence["therapyEndExclusive"]) > min(self.now().date(), date.fromisoformat(claim["serviceDate"])):
                    raise BoundaryError("TreatmentAfterServiceOrFutureDate")
            report = assess(request, evidence, selected, receipts)
        except BoundaryError as exc:
            report = {"status": "EvaluationError", "reasonCodes": [exc.code], "verifiedFacts": {},
                      "authorizationGranted": False, "claimWriteCount": 0}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            report = {"status": "EvaluationError", "reasonCodes": ["InvalidAuthoritativeRecord"],
                      "verifiedFacts": {}, "authorizationGranted": False, "claimWriteCount": 0}
        item = {**report, "evaluationId": str(uuid4()), "evaluationVersion": 1,
                "approvalId": str(uuid4()), "assignedReviewerIds": sorted(self.reviewers),
                "correlationId": str(request.correlationId), "claimId": request.claimId,
                "claimVersion": request.claimVersion, "createdAt": self.now().isoformat(),
                "expiresAt": (self.now()+timedelta(hours=24)).isoformat(),
                "mode": "LocalSimulation", "cloudExecutionVerified": False,
                "state": "Rejected" if report["status"] == "EvaluationError" else "PendingReview",
                "request": payload, "policyFingerprint": fingerprint(selected),
                "evidenceFingerprint": fingerprint(evidence), "sourceFingerprint": fingerprint(receipts),
                "decision": None, "receipt": None, "duplicateSubmission": False,
                "audit": [{"event": "EvaluationRecorded", "actorObjectId": context.object_id,
                           "at": self.now().isoformat()}]}
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT payload_hash,body FROM evaluations WHERE request_key=?", (key,)).fetchone()
            if row:
                if row[0] != digest:
                    raise BoundaryError("IdempotencyConflict")
                return {**json.loads(row[1]), "duplicateSubmission": True}
            c.execute("INSERT INTO evaluations VALUES (?,?,?,?,?)",
                      (item["evaluationId"], key, context.object_id, digest, json.dumps(item)))
        return item

    def review(self, payload_json: str, context: TrustedContext):
        self.authorize(context, "review", self.reviewers)
        try:
            decision = DecisionRequest.model_validate_json(payload_json)
        except ValidationError:
            raise BoundaryError("InvalidDecisionPayload") from None
        decision_body = {**decision.model_dump(mode="json"), "verifiedReviewerObjectId": context.object_id}
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            item = EvaluationStore.read(c, str(decision.evaluationId))
            if context.object_id not in item["assignedReviewerIds"] or str(decision.approvalId) != item["approvalId"]:
                raise BoundaryError("ApprovalBindingMismatch")
            if item["decision"] is not None:
                if item["decision"] != decision_body:
                    raise BoundaryError("DecisionAlreadyRecorded")
                return {**item, "duplicateDecision": True}
            if item["state"] != "PendingReview":
                raise BoundaryError("EvaluationNotReviewable")
            if (decision.evaluationVersion != item["evaluationVersion"] or
                    decision.claimVersion != item["claimVersion"]):
                raise BoundaryError("StaleEvaluation")
            if self.now() >= datetime.fromisoformat(item["expiresAt"]):
                raise BoundaryError("ApprovalExpired")
            request = EvaluationRequest.model_validate_json(json.dumps(item["request"]))
            current_claim = self.claims.get(item["claimId"])
            current_rules = select_rules(self.repository.policy(), request, date.fromisoformat(current_claim["serviceDate"]))
            evidence = self.repository.clinical(item["claimId"])
            sources = self.repository.sources(evidence)
            if (fingerprint(current_rules) != item["policyFingerprint"] or
                    fingerprint(evidence) != item["evidenceFingerprint"] or fingerprint(sources) != item["sourceFingerprint"]):
                raise BoundaryError("PolicyOrEvidenceChanged")
            if current_claim["version"] != item["claimVersion"]:
                raise BoundaryError("StaleClaim")
            clinical_red_flag = item["reasonCodes"] == ["VerifiedRedFlagClinicalPath"]
            if decision.decision == "ApproveAuthorization" and item["status"] != "EligibleForHumanReview" and not clinical_red_flag:
                raise BoundaryError("ApprovalBlockedByEvidenceOrPolicy")
            item["decision"] = decision_body
            item["evaluationVersion"] += 1
            item["audit"].append({"event": "HumanDecisionRecorded", "actorObjectId": context.object_id,
                                  "decision": decision.decision, "at": self.now().isoformat()})
            if decision.decision in {"RequestAdditionalInformation", "Escalate"}:
                item["state"] = "AdditionalInformationRequested" if decision.decision == "RequestAdditionalInformation" else "Escalated"
                EvaluationStore.write(c, item)
                return item
            item["state"] = "Committing"
            EvaluationStore.write(c, item)
        # Separate databases intentionally model the non-transactional service boundary.
        try:
            self.claims.mutate(item["evaluationId"], item["claimId"], item["claimVersion"],
                               "Approved" if decision.decision == "ApproveAuthorization" else "Denied",
                               context.object_id, decision.reason)
            receipt = self.claims.receipt(item["evaluationId"])
            expected = "Approved" if decision.decision == "ApproveAuthorization" else "Denied"
            if not self._valid_receipt(item, receipt, expected):
                raise BoundaryError("WriteReceiptNotConfirmed")
            return self._finish(item["evaluationId"], "Completed", receipt=receipt)
        except BoundaryError as exc:
            uncertain = exc.code in {"ApiTimeout", "WriteReceiptNotConfirmed"}
            return self._finish(item["evaluationId"], "MutationUncertain" if uncertain else "ExecutionFailed", error=exc.code)

    def _finish(self, evaluation_id, state, receipt=None, error=None):
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            item = EvaluationStore.read(c, evaluation_id)
            item.update(state=state, receipt=receipt, executionError=error,
                        claimWriteCount=1 if receipt else 0,
                        authorizationGranted=False, # Simulated receipts never authorize real care.
                        simulatedAuthorizationConfirmed=bool(receipt and receipt["status"] == "Approved"))
            item["audit"].append({"event": state, "at": self.now().isoformat(), "mode": "Simulated"})
            EvaluationStore.write(c, item)
        return item

    @staticmethod
    def _valid_receipt(item, receipt, expected):
        return bool(receipt and receipt.get("mode") == "Simulated" and
                    receipt.get("operationId") == item["evaluationId"] and
                    receipt.get("claimId") == item["claimId"] and receipt.get("status") == expected and
                    receipt.get("version") == item["claimVersion"]+1 and
                    receipt.get("actorObjectId") == item["decision"]["verifiedReviewerObjectId"])

    def reconcile(self, evaluation_id, context):
        self.authorize(context, "review", self.reviewers)
        with self.store.connect() as c:
            item = EvaluationStore.read(c, evaluation_id)
        if item["state"] not in {"MutationUncertain", "Committing"}:
            return item
        receipt = self.claims.receipt(evaluation_id)
        expected = "Approved" if item["decision"]["decision"] == "ApproveAuthorization" else "Denied"
        if self._valid_receipt(item, receipt, expected):
            return self._finish(evaluation_id, "Completed", receipt=receipt)
        # Absence of a receipt is not proof of a failed remote operation. Do not retry.
        return item

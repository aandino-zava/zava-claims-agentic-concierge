import copy
import csv
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .contracts import BoundaryError


class FixtureRepository:
    """Read-only synthetic evidence provider. It is not a Dataverse connection."""
    def __init__(self, fixture_root: Path):
        self.root = fixture_root.resolve()
        self.rules = json.loads((self.root / "policy-rules.json").read_text())
        self.evidence = json.loads((self.root / "evidence.json").read_text())
        self.fail = None

    def policy(self):
        if self.fail == "DataverseUnavailable":
            raise BoundaryError(self.fail)
        return copy.deepcopy(self.rules)

    def clinical(self, claim_id):
        if self.fail == "DataverseUnavailable":
            raise BoundaryError(self.fail)
        for item in self.evidence:
            if item["claimId"] == claim_id:
                return copy.deepcopy(item)
        raise BoundaryError("ClaimEvidenceNotFound")

    def sources(self, evidence):
        if self.fail == "SearchUnavailable":
            raise BoundaryError(self.fail)
        receipts = {}
        for source in evidence["sources"]:
            path = (self.root / source["path"]).resolve()
            if not path.is_relative_to(self.root):
                raise BoundaryError("SourcePathNotAllowed")
            try:
                content = path.read_bytes()
            except OSError:
                raise BoundaryError("SourceUnavailable") from None
            digest = hashlib.sha256(content).hexdigest()
            if digest != source["sha256"]:
                raise BoundaryError("SourceIntegrityFailed")
            receipts[source["documentId"]] = {"sha256": digest, "pages": source["pages"]}
            if source["documentId"] == "pt-log":
                import io
                rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
                expected = [{"date": s["date"], "attended": str(s["attended"]).lower()} for s in evidence["sessions"]]
                if rows != expected:
                    raise BoundaryError("PtFactsDoNotMatchSource")
            if source["documentId"] == "medication-log":
                if json.loads(content) != evidence["medications"]:
                    raise BoundaryError("MedicationFactsDoNotMatchSource")
            if source["documentId"] == "clinical-note":
                note = json.loads(content)
                keys = ("claimId", "memberId", "cptCode", "indication", "treatmentFailedOrWorsened",
                        "redFlagsVerified", "contradictions", "therapyStart", "therapyEndExclusive")
                if any(note.get(k) != evidence.get(k) for k in keys):
                    raise BoundaryError("ClinicalFactsDoNotMatchSource")
        return receipts


class EvaluationStore:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, caller TEXT NOT NULL,
                payload_hash TEXT NOT NULL, body TEXT NOT NULL)""")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=20)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def read(c, evaluation_id):
        row = c.execute("SELECT body FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
        if row is None:
            raise BoundaryError("EvaluationNotFound")
        return json.loads(row[0])

    @staticmethod
    def write(c, item):
        c.execute("UPDATE evaluations SET body=? WHERE id=?", (json.dumps(item), item["evaluationId"]))


class SimulatedClaimsAdapter:
    """A separate durable database models a remote SOR and uncertain responses."""
    mode = "Simulated"

    def __init__(self, path: Path, claims: list[dict]):
        self.path, self.fault = path, None
        with self.connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS claims (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS receipts (operation TEXT PRIMARY KEY, body TEXT NOT NULL)")
            for claim in claims:
                c.execute("INSERT OR IGNORE INTO claims VALUES (?,?)", (claim["claimId"], json.dumps(claim)))

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=20)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, claim_id):
        with self.connect() as c:
            row = c.execute("SELECT body FROM claims WHERE id=?", (claim_id,)).fetchone()
        if row is None:
            raise BoundaryError("ClaimNotFound")
        return json.loads(row[0])

    def receipt(self, operation):
        with self.connect() as c:
            row = c.execute("SELECT body FROM receipts WHERE operation=?", (operation,)).fetchone()
        return json.loads(row[0]) if row else None

    def mutate(self, operation, claim_id, expected_version, status, actor, reason):
        if self.fault == "ApiAuthenticationFailed":
            raise BoundaryError(self.fault)
        if self.fault == "ApiTimeoutBeforeWrite":
            raise BoundaryError("ApiTimeout")
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            prior = c.execute("SELECT body FROM receipts WHERE operation=?", (operation,)).fetchone()
            if prior:
                return json.loads(prior[0])
            row = c.execute("SELECT body FROM claims WHERE id=?", (claim_id,)).fetchone()
            if row is None:
                raise BoundaryError("ClaimNotFound")
            claim = json.loads(row[0])
            if claim["synthetic"] is not True:
                raise BoundaryError("RealClaimForbidden")
            if claim["version"] != expected_version:
                raise BoundaryError("StaleClaim")
            if claim["status"] not in {"Submitted", "Under Review", "In Appeal", "Pending Info"}:
                raise BoundaryError("ClaimTransitionNotAllowed")
            claim.update(status=status, version=expected_version+1)
            receipt = {"mode": self.mode, "operationId": operation, "claimId": claim_id,
                       "status": status, "version": claim["version"], "actorObjectId": actor, "reason": reason}
            c.execute("UPDATE claims SET body=? WHERE id=?", (json.dumps(claim), claim_id))
            c.execute("INSERT INTO receipts VALUES (?,?)", (operation, json.dumps(receipt)))
        if self.fault == "ApiTimeoutAfterWrite":
            raise BoundaryError("ApiTimeout")
        return receipt


class LiveClaimsAdapter:
    """Deliberately unavailable until a separately approved API integration exists."""
    mode = "LiveDisabled"
    def __init__(self, *args, **kwargs):
        raise BoundaryError("LiveClaimsWritesDisabled")

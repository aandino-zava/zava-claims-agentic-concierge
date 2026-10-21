"""Run real local checks and write an explicitly simulated execution report."""
import argparse
import copy
import html
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from claims_concierge.contracts import BoundaryError, TrustedContext
from claims_concierge.repositories import EvaluationStore, FixtureRepository, SimulatedClaimsAdapter
from claims_concierge.service import Gatekeeper


class RecordingResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.records = []

    def startTest(self, test):
        super().startTest(test)
        self.started = time.monotonic()

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({"name": test.id(), "outcome": "Passed", "seconds": round(time.monotonic()-self.started, 4)})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({"name": test.id(), "outcome": "Failed", "detail": self._exc_info_to_string(err, test)})

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({"name": test.id(), "outcome": "Error", "detail": self._exc_info_to_string(err, test)})


STYLE = """body{margin:0;background:#eef3f5;color:#162d3b;font:16px/1.55 Segoe UI,system-ui,sans-serif}header{padding:30px 5%;background:#123d4c;color:white}h1{margin:8px 0;font-size:32px}.eyebrow{letter-spacing:.12em;font-size:13px;color:#a4e3df}main{max-width:1400px;margin:24px auto;padding:0 28px}a{color:#006c77}.notice{background:#fff2ce;border-left:5px solid #ca8d00;padding:14px 20px;margin:18px 0}.metrics{display:flex;gap:18px;flex-wrap:wrap}.metric{background:white;border:1px solid #d6e2e7;padding:18px 24px;min-width:190px;border-radius:10px}.metric strong{font-size:30px;display:block;color:#087b69}section{padding:20px 24px;background:white;border:1px solid #d6e2e7;border-radius:10px;margin:20px 0}h2{font-size:22px;margin:0 0 14px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:12px 14px;border-bottom:1px solid #e1e9ed;vertical-align:top}th{background:#f0f6f7;font-size:13px;color:#415b66}.tag{display:inline-block;border-radius:20px;background:#e1f2ed;color:#11674e;padding:4px 12px;font-weight:600}.muted{color:#526b77;font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.55 Consolas,monospace;background:#eff4f6;padding:18px;border-radius:8px}header a{color:#baf1ec}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}@media(max-width:900px){.grid{grid-template-columns:1fr}}"""


def page(title, content, subtitle="Local executable reference · synthetic claims only"):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>'+STYLE+'</style><header><div class="eyebrow">ZAVA MEDICAL CLAIMS CONCIERGE</div><h1>'+html.escape(title)+'</h1><div>'+html.escape(subtitle)+'</div></header><main><div class="notice"><strong>Local simulation.</strong> No native Copilot Studio agent or Power Automate run is represented here. Identity contexts are harness inputs, not real sign-ins. No Azure claims were changed.</div>'+content+'</main></html>'


def pretty(value):
    return '<pre>'+html.escape(json.dumps(value, indent=2))+'</pre>'


def run_scenarios(identity):
    tenant = identity["tenantId"]
    reviewers = identity.get("reviewerObjectIds") or [identity["medicalDirectorObjectId"]]
    reviewer = reviewers[0]
    unauthorized = identity.get("unauthorizedObjectId") or identity["unauthorizedTestObjectId"]
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    cases = []
    requests = json.loads((ROOT / "tests/fixtures/requests.json").read_text())
    claims = json.loads((ROOT / "tests/fixtures/claims.json").read_text())
    actions = ["ApproveAuthorization", "RequestAdditionalInformation", "DenyClaim", "Escalate",
               "RequestAdditionalInformation", "Escalate", "ApproveAuthorization", "Escalate"]
    expected = ["EligibleForHumanReview", "InsufficientEvidence", "PolicyCriteriaNotMet", "PolicyCriteriaNotMet",
                "PolicyCriteriaNotMet", "MedicalDirectorReviewRequired", "MedicalDirectorReviewRequired", "PolicyCriteriaNotMet"]
    for index, request in enumerate(requests):
        with tempfile.TemporaryDirectory(prefix="scenario-", dir=work) as temporary:
            directory = Path(temporary)
            assert directory.resolve().is_relative_to(work.resolve())
            repository = FixtureRepository(ROOT / "tests/fixtures")
            # This rebinds a labelled synthetic attestation, not a real clinician signature.
            for evidence in repository.evidence:
                evidence["attestedBy"] = reviewer
            store = EvaluationStore(directory / "evaluations.sqlite")
            adapter = SimulatedClaimsAdapter(directory / "claims.sqlite", claims)
            engine = Gatekeeper(tenant, reviewers, {reviewer}, repository, store, adapter)
            ctx = TrustedContext(tenant, reviewer, True, frozenset({"evaluate", "review"}))
            evaluation = engine.submit(json.dumps(request), ctx)
            if evaluation["status"] != expected[index]:
                raise RuntimeError("Unexpected scenario outcome: "+evaluation["status"])
            decision = {"schemaVersion": "1.0", "evaluationId": evaluation["evaluationId"], "evaluationVersion": 1,
                        "approvalId": evaluation["approvalId"], "claimVersion": 1, "decision": actions[index],
                        "reason": "Illustrative Medical Director decision in the local synthetic harness."}
            unauthorized_result = None
            if index == 0:
                other = TrustedContext(tenant, unauthorized, True, frozenset({"review"}))
                try:
                    engine.review(json.dumps(decision), other)
                    raise RuntimeError("Unauthorized decision unexpectedly passed")
                except BoundaryError as exc:
                    unauthorized_result = {"result": exc.code, "identityContext": "Simulated", "objectId": unauthorized,
                                           "claimVersionAfterAttempt": adapter.get(request["claimId"])["version"], "claimWrites": 0}
            completed = engine.review(json.dumps(decision), ctx)
            duplicate = engine.review(json.dumps(decision), ctx)
            cases.append({"name": repository.evidence[index]["fixtureName"], "claimId": request["claimId"],
                          "request": request, "evaluation": evaluation, "decisionResult": completed,
                          "duplicateDecision": duplicate.get("duplicateDecision", False),
                          "unauthorizedAttempt": unauthorized_result, "simulatedIdentityObjectId": reviewer})
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/local-verification")
    parser.add_argument("--identity-config")
    parser.add_argument("--pwsh")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    identity = json.loads(Path(args.identity_config or ROOT / "config/simulation.example.json").read_text(encoding="utf-8-sig"))
    if identity["mode"] != "Simulated":
        raise SystemExit("Only simulated identity contexts are supported")
    result = RecordingResult()
    unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py").run(result)
    pwsh = args.pwsh or shutil.which("pwsh")
    if not pwsh:
        raise SystemExit("PowerShell 7 is required to run the delivery safeguards")
    ps = subprocess.run([pwsh, "-NoProfile", "-File", str(ROOT / "tests/Test-Deployment.ps1")], cwd=ROOT,
                        capture_output=True, text=True, timeout=60)
    count = re.search(r"Passed (\d+) local", ps.stdout)
    checks = int(count.group(1)) if count else 0
    cases = run_scenarios(identity) if result.wasSuccessful() and ps.returncode == 0 else []
    report = {"validationLevel": "Local unit and simulated integration", "nativeCloudExecutionVerified": False,
              "pythonVersion": platform.python_version(), "recordedAtUtc": datetime.now(timezone.utc).isoformat(),
              "unitTests": result.records, "unitTestsRun": result.testsRun, "unitFailures": len(result.failures)+len(result.errors),
              "deploymentChecks": checks, "deploymentChecksExitCode": ps.returncode,
              "deploymentChecksOutput": ps.stdout+ps.stderr, "scenarios": cases,
              "claimsMode": "Simulated", "realClaimsWriteCount": 0}
    (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    rows = []
    for case in cases:
        ev, decision = case["evaluation"], case["decisionResult"]
        rows.append('<tr><td><a href="scenario-'+case["name"]+'.html">'+html.escape(case["name"])+'</a><br><span class="muted">'+case["claimId"]+'</span></td><td>'+ev["status"]+'</td><td>'+html.escape(', '.join(ev["reasonCodes"]))+'</td><td>'+decision["state"]+'</td><td>'+str(decision["claimWriteCount"])+' simulated</td></tr>')
        content = '<p><a href="index.html">← All local verification results</a></p><div class="metrics"><div class="metric">Evaluation<strong style="font-size:22px">'+ev["status"]+'</strong></div><div class="metric">Confirmed writes<strong>'+str(decision["claimWriteCount"])+' simulated</strong></div><div class="metric">Real claims writes<strong>0</strong></div></div>'
        content += '<section><h2>Verified facts from the protected fixture</h2>'+pretty(ev["verifiedFacts"])+ '<p>Reason: <strong>'+html.escape(', '.join(ev["reasonCodes"]))+'</strong></p></section>'
        content += '<div class="grid"><section><h2>Untrusted model proposal</h2>'+pretty(case["request"]["proposedFacts"])+ '</section><section><h2>Recorded human-decision simulation</h2>'+pretty({"decision": decision["decision"]["decision"], "state": decision["state"], "duplicateDecisionBlocked": case["duplicateDecision"], "realAuthorizationGranted": decision["authorizationGranted"]})+'</section></div>'
        if case["unauthorizedAttempt"]:
            content += '<section id="unauthorized"><h2>Unauthorized reviewer blocked</h2>'+pretty(case["unauthorizedAttempt"])+ '</section>'
        content += '<section><h2>Operation receipt and attribution</h2>'+pretty(decision["receipt"])+ '<p class="muted">Evaluation '+decision["evaluationId"]+' · Correlation '+decision["correlationId"]+'</p></section>'
        (output / ('scenario-'+case["name"]+'.html')).write_text(page(case["claimId"]+' · '+case["name"], content), encoding="utf-8")
    content = '<div class="metrics"><div class="metric">Policy and runtime checks<strong>'+str(result.testsRun)+'</strong></div><div class="metric">Deployment safeguards<strong>'+str(checks)+'</strong></div><div class="metric">Synthetic scenarios<strong>'+str(len(cases))+'</strong></div><div class="metric">Real claims writes<strong>0</strong></div></div>'
    content += '<section><h2>Executed synthetic scenarios</h2><table><thead><tr><th>SCENARIO</th><th>EVALUATION</th><th>REASON</th><th>REVIEW RESULT</th><th>OPERATIONS</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></section>'
    content += '<section><h2>Validation boundary</h2><p>The local checks exercise structured evidence, reviewer allowlists, duplicate decisions and confirmed/uncertain simulated writes. The target runtime is Power Automate. Native agent, flow, identity and Dataverse behavior still require approved Dev authoring and acceptance.</p><p><a href="verification.json">Inspect the complete test results and execution traces</a></p></section>'
    test_rows = ''.join('<tr><td>'+html.escape(t["name"].split('.')[-1])+'</td><td>'+t["outcome"]+'</td></tr>' for t in result.records)
    content += '<section><h2>Actual local test results</h2><table><tbody>'+test_rows+'</tbody></table></section>'
    (output / "index.html").write_text(page("Local verification results", content), encoding="utf-8")
    print(json.dumps({"pythonTests": result.testsRun, "pythonFailures": report["unitFailures"], "powerShellChecks": checks,
                      "powerShellExitCode": ps.returncode, "scenarios": len(cases), "cloudExecutionVerified": False,
                      "report": str(output / "index.html")}, indent=2))
    return 0 if result.wasSuccessful() and ps.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

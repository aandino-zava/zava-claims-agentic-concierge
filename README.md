# Zava Medical Claims Concierge

Zava Medical Claims Concierge helps an authorized reviewer evaluate a synthetic lumbar MRI claim against a versioned policy. Copilot Studio retrieves and interprets documents. Power Automate independently checks structured rules and evidence, then routes the case to a Medical Director. Only a recorded human decision can reach the controlled claims adapter.

**Current delivery:** deployed and published in the approved Dev environment. The native agent retrieves from the existing Azure AI Search index and calls the Power Automate Gatekeeper. Dataverse holds three audited claims tables, three active policy rules and eight synthetic evidence fixtures. A native Claims Review app and a claims-specific Medical Director read role are included.

The native demonstration reached `EligibleForHumanReview`, then recorded the authenticated Medical Director's **Escalate** decision and rationale. The synthetic claim stayed at version 1, `Under Review`; real and simulated claim writes were both zero for that decision. A separate ineligible approval response was blocked. The simulator commit branch is implemented and locally tested, but a native approved-write receipt was not exercised in this session.

An authentic unmanaged solution was exported, prepared with processing off, packed with PAC, and checked by Power Apps Checker with zero findings. See [native validation](docs/native-validation.json) and [package provenance](solution/provenance.json). Receiving-tenant import and GitHub workflow execution remain unverified.

All claims operations in this POC are simulated. `authorizationGranted` remains false even when a simulated approval completes. The existing Azure claims portal is never mutated by this build.

## Run locally

Use Python 3.11+ and PowerShell 7. The only local runtime dependency is Pydantic 2.

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
pwsh -NoProfile -File tests/Test-Deployment.ps1
python scripts/run_checks.py --output artifacts/local-verification
```

Open `artifacts/local-verification/index.html` to inspect actual local results and scenario receipts. The identity contexts in this harness are simulated; no real reviewer sign-in or native flow execution is implied.

## Why these boundaries exist

- **Copilot Studio** handles conversation, retrieval and a typed proposal. It cannot approve, deny, write policy/evidence, or update the claims portal.
- **Dataverse** stores three tables: versioned Medical Policy Rules, protected Claim Evidence Facts, and durable Claim Evaluations with decisions and receipts. Structured conditions drive enforcement; policy prose is explanatory.
- **Power Automate** implements the Gatekeeper and review worker. It re-reads authoritative rows, checks source/claim binding and stale state, and fails closed when a mandatory check cannot complete. Python is the local behavioral reference, not an added Azure service.
- **Native Approvals in Teams** provides the human response. The worker verifies the actual responder's object ID and approval assignment, rather than trusting a card click or model-supplied identity.
- **The claims adapter** is explicitly simulated. The observed portal contract is `PATCH /api/v1/claims/{claim_id}/status`; live integration remains disabled until its client authorization and human-decision enforcement are separately approved and verified.

See [architecture and sequence](docs/architecture.md), [security boundaries](docs/security.md), [deployment](docs/deployment.md), [test evidence and acceptance](docs/testing.md), and the [demonstration guide](docs/demo.md).

## Configure and prepare Dev

The guided and command-line paths use the same PowerShell module. Configuration is data; no PowerShell source edits are required.

```powershell
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Configure
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Validate -ConfigPath .local/target.json
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Plan -ConfigPath .local/target.json
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Validate -Online -ConfigPath .local/target.json
```

`Configure` lists available environments, asks for the target and identity/endpoints, and saves a nonsecret local JSON file. `Plan` performs no tenant mutation. `Bootstrap` and `Import` require the exact approved environment URL. Runtime connections must be authorized in the receiving tenant; connection IDs do not carry sign-ins.

Deployment must be to an approved Development environment. Packages ship processing off. Do not infer that importing an unmanaged solution disables an already-running installation; verify actual flow and configuration state afterward.

## Repository contents

| Path | Purpose |
|---|---|
| `src/claims_concierge/` | Tested local policy, identity-boundary, decision and receipt behavior |
| `contracts/` | Strict evaluation/reviewer schemas and the observed portal API contract |
| `dataverse/` | Approved policy seed specifications and table authoring plan |
| `agent/` | Agent instructions, native tool plan and knowledge constraints |
| `flows/` | Power Automate authoring sequence and supported expression inputs |
| `scripts/` | One guided/CLI deployment engine, schema/seed tooling and local verification |
| `tests/fixtures/` | Eight fictional cases, PT logs, medication records and clinical notes |
| `solution/src/` | Genuine portable native agent, flows, tables, forms, views, app and role |
| `solution/provenance.json` | Export, reviewed source digest, package checksum and receiving-validation state |

No credentials, connection instances, local identity settings or patient records belong in source control. Source generation and ordinary CI require no tenant access. A successful local test run is not a successful Power Platform deployment.

# Security and governance

The POC demonstrates enforcement boundaries with fictional data. It does not substantiate HIPAA compliance or production readiness.

The optional [portal connection](portal-connection.md) permits status changes only to explicitly allowlisted fictional portal claims. The portal's managed identity reads protected Dataverse evaluations, evidence, policy and actual native Approval responses, then records completion. It has no policy, evidence or Approval editing rights. The portal owns the version-checked status update and durable receipt; the agent receives no portal write tool. This does not enable real patient data or care authorization.

| Boundary | Control | Required native evidence |
|---|---|---|
| Agent entry | Microsoft authentication; private POC audience; anonymous channels disabled | Authorized sign-in and rejected unauthorized access |
| Agent tools | User-authenticated read tools; no policy/evidence or claims write tools | Tool credentials, sharing and effective role verification |
| Evaluation action | Strict JSON, private flow invocation, independent rule/evidence reads | Platform-trigger/access tests; no identity taken from JSON |
| Evidence | Protected source bodies, source version, hashes at ingestion, content/fact comparisons | Tampering and stale-source tests under actual Dataverse permissions |
| Policy | Structured rule kinds, effective versions, mandatory coverage and restricted writers | Three seeds, alternate keys, R03 null/false semantics and audit records |
| Medical review | Actual Approval responder object ID/tenant, configured MD allowlist, assignment, approval ID and expiry | Native authenticated escalation captured; full negative matrix remains local |
| Claims | Simulated adapter only; expected version; one-time operation and receipt readback | Confirmed simulator receipt and no Azure portal mutation |
| Delivery | Explicit Dev target, checksum, native provenance, processing off | Native export/pack/check and post-import state verification |

The deployed `Zava Claims Medical Director` role has native App Opener privileges and organization Read on the three claims tables. It grants no claims-specific create, write or delete privileges. It was assigned and read back for the designated owner. Agent read tools use the caller's connection and fixed table/filter/column projections; the submission tool invokes only the Gatekeeper.

The single-owner POC uses a trusted owner connection; that account retains its underlying administrator privileges. The worker independently checks the configured MD allowlist and actual Approval responder, but it does not perform a fresh Dataverse security-role lookup at decision time. A dedicated worker identity, evidence/policy administrator roles and independent reviewer authorization are production requirements, not implemented least-privilege claims. Unauthorized-account sign-in remains an acceptance check for each installation.

Organization and claims table/column auditing were enabled under the approved Dev plan. Audit retention is a tenant governance decision; do not silently change the existing retention setting. The synthetic build kept readable diagnostics for its screenshots. Before real clinical use, secure sensitive flow inputs/outputs and restrict run-history/transcript access. Do not treat application result rows as immutable audit storage when administrators can update them.

Teams notifications contain a synthetic claim alias, evaluation state and protected review link. Clinical evidence, medication details and member identity belong in the authorized review app. Approvals go only to the configured Medical Director; the separate access-test account receives no access or messages from setup.

A production system of record must enforce authorization, human-decision proof and reliable duplicate handling at its own write boundary. An automation account's access alone would not establish a human decision. The live claims adapter is disabled.

Production work must address evidence-source authority and clinical attestation, patient-level authorization, narrow runtime identities, independent reviewer access, clinical exceptions/overrides, reliable idempotency at the system of record, durable transaction reconciliation, privacy/retention requirements, monitoring and incident response, accessibility, recovery, and validated deployment into a separate controlled lifecycle. Do not reuse the private single-owner POC sharing model as a multi-user authorization design.

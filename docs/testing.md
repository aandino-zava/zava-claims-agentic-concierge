# Testing and verification

## What is checked automatically?

The Python tests execute the local behavioral reference against separate durable evaluation and claims databases. They verify clinical thresholds, weekly frequency, medication coverage, explicit unknowns, provenance, claim binding, missing/inactive rules, R03 behavior, unsupported recommendations, identity allowlists, stale policy/evidence/claim state, expiry, duplicate/concurrent decisions, dependency failures, injected document instructions, API authentication errors, and uncertain writes with receipt reconciliation.

PowerShell checks cover configuration restrictions, target/approval binding, separation of reviewer/test identities, credential fields, missing native exports and script syntax. They do not contact a tenant. `scripts/run_checks.py` records actual per-test outcomes, scenario traces and receipts in JSON/HTML.

`scripts/check_sdk_contract.py` constructs all three table payloads using the inspected official SDK while HTTP is blocked. It checks real method signatures, primary-name uniqueness and memo constraints. This is payload compatibility evidence, not successful Dataverse metadata creation.

The synthetic sources have no relationship to real portal claims. `TrustedContext` is an in-process harness input, not a token verifier. A local unauthorized-reviewer result proves the oracle's boundary behavior, not an Entra sign-in or a Power Automate run. The reference's SQLite serialization is not evidence that a Dataverse flow is atomic; that must be verified natively.

## What has been verified live?

The approved Dev deployment created the dedicated unmanaged solution, three audited tables/active alternate keys, three versioned policy rows, eight clearly synthetic evidence fixtures, configuration, connection references, a published authenticated agent, two active native flows, a Claims Review app with readable locked forms, and the Medical Director read role. The role assignment was queried after PAC reported success.

Search Index Data Reader was granted at the separately approved existing Search service scope. Entra document querying then returned HTTP 200, and native agent knowledge retrieval returned three indexed chunks with actual source URLs. Citation URL access as an arbitrary reviewer is not established by retrieval alone.

The final native agent read protected evidence and structured rules, retrieved Search context, and invoked the Gatekeeper. Its request copied the synthetic claim bindings, source hashes/pages and six-week facts. The 32-second native flow returned `EligibleForHumanReview`, `ConservativeCriteriaVerified`, six complete weeks, weekly PT counts `[2,2,2,2,2,2]`, verified pharmacology and a durable evaluation/correlation ID. It wrote zero claims.

Native Approvals delivered the request to the designated Medical Director. The actual authenticated response was **Escalate**, with rationale **Need more input**. The worker saved the responder object ID/tenant, approval ID and decision, then set the evaluation to `Escalated`. A separate protected read confirmed the synthetic claim remained version 1, `Under Review`, with zero real or simulated writes. No mutation receipt is expected for an escalation.

An earlier manual native diagnostic run created an ineligible evaluation because of a source-envelope mismatch in the flow. The user submitted an approval response and the worker correctly blocked it as `BlockedIneligibleApproval`. The source-binding defect was fixed before the successful final agent run. This diagnostic is not presented as a native missing-fixture scenario pass. A temporary agent Flow binding also failed and one preview answer fabricated an unconfirmed result; the binding was replaced natively and the instructions tightened before the verified run.

The genuine export was unpacked, reviewed with processing off, packed with PAC, and checked by Power Apps Checker: zero critical, high, medium, low or informational findings. Four GitHub workflows passed local actionlint. The last full local policy run had 58 tests and eight synthetic scenarios; the updated deployment scripts passed 24 local checks. These levels are separate in [native validation](native-validation.json).

## What remains unverified?

Native approved/denied synthetic mutation and receipt reconciliation; the complete native concurrency/staleness/fault matrix; real negative-account sign-in; receiving-environment import and first-run acceptance; GitHub workflow execution/federated trust; broad user sharing and production role enforcement. The operator requested light native testing and chose escalation. Local simulator tests cover approved-write receipts, but they do not prove that native commit branch.

## How should native acceptance be repeated?

1. Record target environment, solution version/export hash, connection identities and native component IDs.
2. Verify the three tables, three exact seed texts, structured path/version/effective fields and alternate keys. Confirm R03 has no operative treatment thresholds, including Dataverse Boolean defaults.
3. Verify the eight source fixtures, SyntheticFixture labels, source bodies/versions and restricted writers. Preserve actual clinician verification separately.
4. In the authenticated agent, retrieve the permitted guideline/appeal, open its actual citation, read rules/evidence, and submit a valid complete fixture. Capture the agent/tool result and native Gatekeeper run.
5. Confirm insufficient duration, missing PT logs, low weekly frequency, missing pharmacology and contradictory sources block approval and do not automatically deny.
6. Use the designated Medical Director's real Approval response; capture responder object ID, approval binding and the resulting durable decision. A mutation decision additionally requires a confirmed simulator receipt. Ensure no Azure claims record changes.
7. Attempt unauthorized entry with the selected lab account in that account's own session; no credential reset, access grant or message is implied. Separately test a wrong responder/approval ID and manipulated model payload through an authorized test harness.
8. Test duplicate and concurrent decisions, expired/stale approvals, changed policy/evidence/claim versions and uncertain simulator operations. Confirm exactly one operation or an explicit unresolved state.
9. Inject Search/Dataverse/API faults in the controlled Dev test branch and verify fail-closed outcomes. Never weaken production connections to induce faults.
10. Export authentic artifacts, review dependencies/values/processing state, run PAC solution check, then verify configuration/runtime state after a scoped import. Keep local, simulated and native evidence labelled separately.

Screenshots should show the actual configuration, input, failure/result and correlation ID. Do not capture credentials or identifiable patient information. Failed/loading screenshots are diagnostic evidence and must not be presented as successful execution.

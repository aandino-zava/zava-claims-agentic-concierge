# Validation and acceptance

## What is checked automatically

Repository checks cover policy thresholds, missing or contradictory evidence, source and claim binding, reviewer authorization, stale state, duplicate decisions, failures and simulated receipt reconciliation. PowerShell checks validate target configuration, package integrity and safe import conditions. An offline SDK check validates Dataverse payload construction without contacting a tenant.

These checks run on Windows and Linux in GitHub Actions. They exercise a local reference and deployment tools. They do not establish native flow atomicity, real sign-in, connector access or a successful tenant deployment. See [maintenance](maintenance.md#run-the-checks) to run them locally.

## What was verified natively

The published agent read structured policy and protected fictional evidence, retrieved Search context, and called the Gatekeeper. The completed example returned `EligibleForHumanReview` with `ConservativeCriteriaVerified`: six complete weeks, two attended PT sessions in each week, medication coverage and failed treatment.

The assigned Medical Director responded **Escalate** through native Approvals. The worker recorded the authenticated response and saved `Escalated`. Independent readback confirmed the claim remained `Under Review` at version 1, with zero real or simulated claim writes. An escalation has no mutation receipt.

The exported package was also checked by Power Apps Checker with zero findings. Each rebuilt ZIP has its own checksum and Checker status; see the build artifact's `solution/provenance.json`. An earlier package's result does not certify a later build.

## What remains unverified

- Native approved or denied simulator writes and receipt reconciliation.
- The full native concurrency, stale-state and dependency-failure cases.
- Actual unauthorized-account sign-in and broader multi-user authorization.
- Receiving-environment import and first-run acceptance, including GitHub federation.

Local simulations do not substitute for these checks. The solution remains a private, single-reviewer POC using fictional data.

## How to accept your installation

1. Record the source commit, package checksum, target, connection identities and published agent version. Verify both flows remain off until runtime setup is complete.
2. Verify the three policy rules and eight fictional evidence cases. Confirm effective dates, source versions, active keys, auditing and reviewer access.
3. Confirm the agent can retrieve context and open citations with the reviewer's permissions. Then [activate simulation](deployment.md#5-verify-settings-and-activate-simulation) and follow the [demonstration](demo.md).
4. Verify that missing PT records, short duration, low weekly frequency, missing medication and contradictory sources prevent approval eligibility. Missing evidence must not cause automatic final denial.
5. Capture a genuine Medical Director response. Check the responder, approval binding and durable decision. For a simulated write, require a matching receipt and readback of the resulting claim state.
6. Use the separate test account's own session to verify unauthorized entry is rejected. Also test a wrong reviewer or approval binding through an authorized test method; do not grant extra access to make a test pass.
7. Check duplicates, conflicting decisions, expired requests, changed policy/evidence/claim versions and uncertain operations. Expect one confirmed operation or an explicit unresolved state. Never retry an uncertain write blindly.
8. Exercise dependency failures only in controlled Dev. Confirm failures stop processing and do not report an invented successful result.

Retain the evaluation/correlation ID, flow runs, actual Approval response and independent state readback. Do not commit tenant settings, transcripts, raw exports or run histories to this repository.

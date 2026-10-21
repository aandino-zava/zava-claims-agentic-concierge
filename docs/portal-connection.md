# Connect fictional portal claims

The default solution keeps claim operations in its simulator. An optional connection can update explicitly allowed fictional records in the [Zava Health Claims Portal](https://github.com/aandino-zava/zava-health-claims-portal) after a verified Medical Director decision.

## The protected path

`Protected claim and evidence → deterministic Gatekeeper → native human Approval → durable decision queue → independent portal checks → fictional claim update → verified receipt`

The existing review worker sends only explicitly bound cases to `PortalUpdatePending`. The portal uses its existing managed identity to read that queue and the actual native Approval response. It verifies the assigned reviewer, approval/evaluation binding, eligibility for approval, current protected evidence and policy, and the exact portal claim snapshot.

The portal changes status and records a uniquely identified operation receipt in one version-checked database update. It then reads the result back and records `PortalConfirmed` in the evaluation. A duplicate decision uses the existing receipt; an unavailable service leaves the queue entry pending. A failed business check records `PortalUpdateBlocked`.

The agent never receives a portal write tool. Azure AI Search remains a source of document context. A patient's name, a similar narrative or a statement that attachments exist cannot bind evidence to a claim.

## What the receiving installation supplies

- The optional portal connection from the [portal setup guide](https://github.com/aandino-zava/zava-health-claims-portal/blob/main/docs/CLAIMS_CONCIERGE.md), using App Service with Always On.
- An application user for the existing portal managed identity, assigned the dedicated **Zava Claims Portal Worker** role. It can read the three claims tables and native Approval/response records, and update evaluation completion. It cannot change policy, evidence or Approval records.
- The configured Medical Director's Entra object ID and Dataverse user ID, and an explicit list of allowed fictional portal claim IDs.
- A protected `portalBinding` in the claim snapshot, containing the exact portal `claimId`, `memberId`, `cptCode`, `serviceDate`, `version`, `status` and `synthetic` flag. An authorized evidence maintainer creates this binding before evaluation.

Keep completed destination values out of public source. Business rows and managed-identity assignments do not travel with the solution package. The agent audience stays restricted, and unbound examples continue through the simulator.

After any portal status change, an authorized maintainer must refresh the protected binding before starting another evaluation. The original snapshot deliberately becomes stale; repeating an approval cannot silently apply it to a newer claim version.

## What approval means

The request explicitly tells the Medical Director when approval or denial can update a bound fictional portal record. Passing the Gatekeeper establishes eligibility for human review. Approval still requires that verified eligibility; a denial still requires a genuine human decision. Information requests and escalation do not update portal status through this connection.

The evaluation remains a fictional clinical simulation (`mode: Simulated`); the optional execution result separately records `executionMode: PortalSynthetic` and the portal receipt. This distinction does not permit real patient data, care authorization or production claims processing. Keep `allowLiveClaimsWrites` false and the reserved direct-API setting blank.

Check the portal status, timeline, version and receipt as well as the Dataverse completion. A successful review flow or `PortalUpdatePending` alone is not evidence that a portal update occurred. Snapshot checks across Dataverse and PostgreSQL do not create a shared transaction; see the portal guide for failure handling and production limitations.

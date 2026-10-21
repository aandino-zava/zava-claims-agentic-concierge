# Demonstration guide

Begin with the native agent, the protected Claims Review app, and the two native flows. The captured Dev demonstration evaluated SYN-CLM-1001, reached `EligibleForHumanReview`, and recorded the Medical Director's authenticated **Escalate / Need more input** response. Claim version/status stayed unchanged. Identify the POC and simulated mode explicitly.

Use this prompt for a fresh demonstration: “Evaluate synthetic claim SYN-CLM-1001. Retrieve its protected evidence and rules, submit it through SubmitClaimEvaluation, and report only the returned evaluation ID, status and mode.” A fresh request creates a new review case. Open the secure review record before choosing a decision in native Approvals. The agent cannot choose the decision.

The remaining table describes available fixture cases and expected/local-tested behavior. Those cases were not all rerun natively. A native approved-write receipt and a real negative-account sign-in have not been demonstrated.

| Scenario | Example | Expected behavior |
|---|---|---|
| Sufficient evidence | SYN-CLM-1001 | Six complete weeks, two attended sessions each week, documented medication and failed treatment reach human review. No automatic approval. |
| Missing attachments | SYN-CLM-1002 | An appeal asserts attachments that are absent. Approval is blocked; the reviewer can request information. No automatic denial. |
| Manipulated proposal | SYN-CLM-1003 | The model proposes eight weeks; the independently read log contains five. The proposal does not override the evidence. |
| Low PT frequency | SYN-CLM-1004 | One session per week fails the structured threshold. An average or mention of PT cannot pass. |
| Missing pharmacology | SYN-CLM-1005 | A clinical claim without documented pharmacology cannot be approved. |
| Contradictory evidence | SYN-CLM-1006 | Route to Medical Director review and require corrected evidence before approval. |
| Red-flag clinical path | SYN-CLM-1007 | Verified red-flag notes take the separate human pathway without imposing conservative treatment requirements. |
| Symptoms improved | SYN-CLM-1008 | Duration/modality alone does not establish failed therapy. |

For the captured review, show the assigned Approval, actual responder identity, recorded escalation rationale and durable Escalated result. Show a simulated mutation receipt only after an actual native mutation and readback have produced one. For the negative case, show the selected lab account outside the allowlist and rejected access. If no real sign-in was performed, label the local identity test as simulated.

Explain why each component exists: Copilot Studio interprets evidence; existing Search supplies context; Dataverse makes reviewed rules versionable; Power Automate independently enforces conditions; the clinician controls the consequential decision; the adapter and readback protect claims state; native export and shared configuration support repeatable deployment.

End with a trace from correlation ID to evaluation, source/policy snapshots, reviewer decision and receipt. Show an uncertain timeout separately: no success is reported until reconciliation confirms a matching receipt. The production discussion should cover evidence attestation, patient-level access, least privilege, system-of-record idempotency and clinical governance.

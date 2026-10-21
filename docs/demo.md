# Demonstrate the solution

Use the published agent, Claims Review app and two flows in the configured Dev environment. Keep the demonstration fictional and in Simulated mode.

1. Ask the agent: **“Evaluate synthetic claim SYN-CLM-1001. Retrieve its protected evidence and rules, submit it through SubmitClaimEvaluation, and report the returned evaluation ID, status and mode.”**
2. Confirm the actual Gatekeeper run and durable evaluation row. This complete-evidence example should reach `EligibleForHumanReview`; that outcome is not a claim authorization.
3. Open the protected evidence link from the assigned native Approval. The configured Medical Director supplies the decision; the agent cannot choose it.
4. For a demonstration with no claim change, choose **Escalate** and enter a reason. Confirm the evaluation becomes `Escalated`, the responder is recorded, and the claim remains unchanged.

A fresh submission can create a new review request and notification. Use one case at a time: the POC worker processes requests sequentially, including its Approval wait.

Other fictional cases are available for [acceptance testing](testing.md):

| Claim | Case | Expected behavior |
|---|---|---|
| SYN-CLM-1001 | Complete conservative treatment | Eligible for human review |
| SYN-CLM-1002 | Missing attachments | More evidence required |
| SYN-CLM-1003 | Short treatment duration | Conservative criteria not met |
| SYN-CLM-1004 | Low weekly PT frequency | Conservative criteria not met |
| SYN-CLM-1005 | Missing medication | No approval eligibility |
| SYN-CLM-1006 | Contradictory sources | Medical Director review required |
| SYN-CLM-1007 | Verified red flags | Separate human clinical review path |
| SYN-CLM-1008 | Symptoms improved | Conservative criteria not met |

These are sample cases and locally checked expectations, not a claim that every case passed natively in your environment. A simulated approval or denial additionally needs its own native receipt and state readback.

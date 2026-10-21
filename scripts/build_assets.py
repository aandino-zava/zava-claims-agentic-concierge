"""Build schema and authoring inputs; these are not a native solution export."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2)+"\n", encoding="utf-8")


def column(name, kind="string", **kwargs):
    label = name.replace('_',' ').title().replace(' Id',' ID').replace('Cpt','CPT').replace('Pt ','PT ').replace('Json','JSON')
    return {"name": "{prefix}_"+name, "type": kind, "displayName": label, **kwargs}


def build():
    provenance=ROOT/'solution/provenance.json'
    if provenance.exists() and json.loads(provenance.read_text(encoding='utf-8-sig')).get('nativeExportPresent'):
        raise SystemExit('Authentic native source already exists. Use the reviewed Dev export workflow; bootstrap generation cannot overwrite delivered configuration or provenance.')
    rule_fields = [column("rule_id"), column("policy_number"), column("cpt_code"),
        column("natural_language_rule", "memo", maxLength=4000), column("min_conservative_weeks", "int"),
        column("requires_pt", "bool"), column("requires_pharmacology", "bool"),
        column("enforcement_level", "choice", options={"Strict_Block": 100000000, "Medical_Director_Review": 100000001, "Audit_Only": 100000002}),
        column("is_active", "bool"), column("policy_version"), column("effective_from", "datetime"),
        column("effective_to", "datetime"), column("rule_kind"), column("clinical_path"),
        column("min_pt_sessions_week", "int"), column("requires_failed_treatment", "bool")]
    evidence_fields = [column("evidence_id"), column("claim_id"), column("member_id"), column("cpt_code"),
        column("policy_number"), column("policy_version"), column("source_version", "int"),
        column("verification_state", "choice", options={"Unverified": 100000000, "SyntheticFixture": 100000001, "ClinicianVerified": 100000002, "Retired": 100000003}),
        column("attestor_object_id"), column("attested_at", "datetime"), column("is_synthetic", "bool"),
        column("facts_json", "memo", maxLength=1000000), column("sources_json", "memo", maxLength=1000000),
        column("claim_snapshot_json", "memo", maxLength=1000000), column("review_summary", "memo", maxLength=4000)]
    evaluation_fields = [column("evaluation_id"), column("request_key"), column("claim_id"), column("member_id"),
        column("correlation_id"), column("caller_object_id"), column("policy_number"), column("policy_version"),
        column("claim_version", "int"), column("evaluation_version", "int"), column("state"), column("outcome"),
        column("approval_id"), column("assigned_reviewer_id"), column("reviewer_object_id"), column("expires_at", "datetime"),
        column("mode"), column("request_json", "memo", maxLength=1000000), column("result_json", "memo", maxLength=1000000),
        column("policy_snapshot_json", "memo", maxLength=1000000), column("evidence_snapshot_json", "memo", maxLength=1000000),
        column("decision_json", "memo", maxLength=1000000), column("receipt_json", "memo", maxLength=1000000)]
    evaluation_fields.append(column("review_summary", "memo", maxLength=4000))
    tables = []
    for name, display, primary, fields, keys in [
        ("medical_policy_rules", "Medical Policy Rules", "rule_id", rule_fields, [["rule_id", "policy_version"]]),
        ("claim_evidence", "Claim Evidence Facts", "evidence_id", evidence_fields, [["evidence_id"], ["claim_id", "policy_version"]]),
        ("claim_evaluation", "Claim Evaluations", "evaluation_id", evaluation_fields, [["evaluation_id"], ["request_key"]]),
    ]:
        tables.append({"name": "{prefix}_"+name, "displayName": display, "primaryName": "{prefix}_"+primary,
                       "platformGuid": True, "auditEnabled": True, "columns": fields,
                       "alternateKeys": [["{prefix}_"+k for k in key] for key in keys]})
    write("dataverse/schema.json", {"format": "authoring-plan-1.0", "nativeSolutionExport": False, "tables": tables})
    variables = [{"suffix": name, "type": kind, "defaultValue": default} for name, kind, default in [
        ("ClaimsMode", "String", "Simulated"), ("ProcessingEnabled", "Boolean", "no"),
        ("SearchEndpoint", "String", ""), ("SearchIndex", "String", ""), ("PolicyVersion", "String", "1.0"),
        ("MedicalDirectorObjectId", "String", ""), ("MedicalDirectorUPN", "String", ""),
        ("ClaimsApiBaseUrl", "String", ""), ("ApprovalLifetimeHours", "Decimal", "24"),
        ("TenantId", "String", ""), ("DataverseUrl", "String", "")]]
    write("config/environment-variables.json", variables)
    write("config/target.example.json", {"deploymentScope": "Development", "environmentDisplayName": "",
        "environmentId": "", "environmentUrl": "", "organizationId": "", "tenantId": "",
        "publisherUniqueName": "Zava", "publisherDisplayName": "Zava", "publisherPrefix": "cr",
        "solutionUniqueName": "ZavaMedicalClaimsConcierge", "solutionDisplayName": "Zava Medical Claims Concierge",
        "mode": "Simulated", "processingEnabled": False, "allowLiveClaimsWrites": False,
        "medicalDirectorObjectId": "", "medicalDirectorUpn": "", "unauthorizedTestObjectId": "",
        "searchEndpoint": "", "searchIndex": "", "searchSemanticConfiguration": "", "claimsApiBaseUrl": "",
        "connections": {"Dataverse": "", "AzureAISearch": "", "Approvals": "", "Teams": ""}})
    write("solution/provenance.json", {"state": "AwaitingApprovedDevAuthoring", "nativeExportPresent": False,
        "importableSolutionPresent": False, "processingEnabledInDistributable": False,
        "requiredSolution": "ZavaMedicalClaimsConcierge",
        "explanation": "Local schema, contracts and reference behavior exist. Genuine agent/flow/table artifacts must be authored in the approved Dev environment and exported with PAC before pack/import is enabled."})
    write("agent/tools.json", {"nativeBindingsVerified": False, "authentication": "MicrosoftEntraID",
        "pocAudience": "ConfiguredMedicalDirectorOnly", "tools": [
            {"name": "FetchPolicyRules", "mode": "ReadOnly", "target": "Dataverse Medical Policy Rules", "authentication": "User", "filters": ["policy number", "CPT", "active", "version", "service date"]},
            {"name": "FetchClaimEvidence", "mode": "ReadOnly", "target": "Dataverse Claim Evidence Facts", "authentication": "User", "filters": ["exact authorized synthetic claim", "policy version"]},
            {"name": "SubmitClaimEvaluation", "mode": "ControlledAction", "target": "EvaluateClaimWithRuleCheck", "input": "evaluationJson", "schema": "contracts/claim-evaluation.schema.json"}]})
    write("flows/authoring-plan.json", {"nativeFlowExport": False, "targetRuntime": "PowerAutomate", "flows": [
        {"name": "EvaluateClaimWithRuleCheck", "trigger": "When an agent calls the flow", "input": {"evaluationJson": "Text"},
         "response": {"resultJson": "Text"}, "steps": [
            "Restrict invocation to the private authenticated POC agent and its approved owner; do not accept caller identity from the payload.",
            "Parse the strict evaluation schema, reject unsupported properties and recommendations.",
            "Look up the idempotency key, compare the stored caller and canonical payload; return the existing evaluation or reject a conflict.",
            "Retrieve the protected synthetic claim snapshot and validate member, CPT, synthetic flag, version and service date.",
            "Retrieve all three active versioned policy rules effective on the service date. Reject missing, duplicate or unsupported kinds; R03 thresholds must be null.",
            "Retrieve protected evidence and source snapshots. Require SyntheticFixture or ClinicianVerified state as appropriate to Simulated mode. The agent has no write privileges on these rows.",
            "Decode the independently stored source bodies and compare parsed PT, medication and clinical facts with the attested snapshot; compare source version at review. Hashes are checked at ingestion; Power Automate does not have a general SHA-256 expression.",
            "Validate every source reference, document/claim binding, page and explicit unknown. Retrieve policy grounding using the approved Search connection. Failed mandatory retrieval returns EvaluationError.",
            "Route contradictions or verified red flags for Medical Director review. Require clinical notes for red flags; do not apply conservative thresholds to that path.",
            "Compute full seven-day therapy weeks, count attended PT sessions in each week, require at least two per week, medication coverage, valid indication, and failed/worsening outcome.",
            "Record outcome, source and policy snapshots, reason codes, expiry, claim/evaluation version and correlation ID. Use an alternate key to reject duplicate create races.",
            "Respond with the durable evaluation ID, outcome and mode. Never write a claim or automatically deny it."]},
        {"name": "ReviewAndCompleteClaimEvaluation", "trigger": "Dataverse row added to Claim Evaluations", "concurrency": 1,
         "steps": ["Check ProcessingEnabled, Simulated mode, PendingReview state and request expiry before dispatch. Expired queued cases produce no approval task.",
            "Create a native approval assigned only to configured MedicalDirectorUPN; persist its actual approval ID before waiting.",
            "Use four custom responses: Approve Authorization, Deny Claim, Request Additional Information, Escalate. Include claim alias, status and a secure evidence link only; keep clinical details out of notification text.",
            "Require a response within 24 hours. Use the response's authenticated object ID; compare tenant, actual approval ID, assigned reviewer and current reviewer authorization. Never trust a model-supplied reviewer field.",
            "Re-read claim, evidence and policy. Reject stale versions, changed snapshots, duplicate or conflicting decisions, failed reads and expired approvals.",
            "Allow approval only for verified conservative eligibility or the verified red-flag clinical path. Missing or contradictory evidence requires reevaluation before approval.",
            "Record the one-time decision under a serialized worker plus optimistic concurrency. Processing state is server-owned. Review/update bypass by other principals must fail.",
            "Request information or escalate without a claims operation. Explicit human approval/denial invokes only the Dataverse simulator branch.",
            "For the simulator, create a uniquely keyed operation receipt and update only the synthetic snapshot. This is not the Azure portal system of record. Track unfinished operations for reconciliation; do not report success prematurely.",
            "Read back the receipt and synthetic state, then mark Completed. Unknown results remain MutationUncertain and are not blindly retried.",
            "Return or expose the recorded outcome and correlation ID. Real API mutation remains disabled."]}]})
    write("flows/expression-catalog.json", {"runtimeVerified": False, "purpose": "Supported WDL expressions for native authoring; validate actual action names in Dev.", "expressions": {
        "completedWeeks": "div(sub(ticks(variables('TherapyEndExclusive')),ticks(variables('TherapyStart'))),6048000000000)",
        "weekIndex": "div(sub(ticks(item()?['date']),ticks(variables('TherapyStart'))),6048000000000)",
        "weekIndices": "range(0,variables('CompletedWeeks'))",
        "minimumPtMetForWeek": "greaterOrEquals(length(body('Filter_attended_sessions_in_week')),variables('MinimumPtSessionsPerWeek'))",
        "approvalExpired": "greaterOrEquals(ticks(utcNow()),ticks(variables('ExpiresAt')))",
        "reviewerMatches": "equals(toLower(variables('VerifiedResponderObjectId')),toLower(variables('AssignedReviewerObjectId')))",
        "sourceContent": "base64ToString(items('For_each_source')?['bodyBase64'])",
        "sameCanonicalPayload": "equals(variables('StoredCanonicalPayload'),variables('CurrentCanonicalPayload'))"}})


if __name__ == "__main__":
    build()
    print("Built portable schema, environment settings, agent tools, and flow authoring inputs.")

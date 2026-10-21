"""Approved Dev bootstrap using the official Dataverse SDK.

Table/column creation uses the inspected SDK 1.1 constraint types. Audit
metadata and PublishXml use the documented Web API escape hatch.
The schema and seeds were authored in the approved Dev environment. Receiving
installations still require their own exact target authorization.
"""
import argparse
import base64
import json
import re
import time
from enum import IntEnum
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]


def column_types(table, include_primary=True):
    columns = {}
    for field in table["columns"]:
        if not include_primary and field["name"] == table["primaryName"]:
            continue
        if field["type"] == "memo":
            columns[field["name"]] = {"type": "memo", "max_length": field["maxLength"], "display_name": field["displayName"]}
        else:
            columns[field["name"]] = IntEnum("Options", field["options"]) if field["type"] == "choice" else field["type"]
    return columns


def load(configuration_path):
    cfg = json.loads(Path(configuration_path).read_text(encoding="utf-8-sig"))
    if (cfg["deploymentScope"] != "Development" or cfg["mode"] != "Simulated" or
            cfg["allowLiveClaimsWrites"] is not False or cfg["processingEnabled"] is not False):
        raise ValueError("Only the approved Development simulation contract is supported")
    if not re.fullmatch(r"https://[a-z0-9-]+\.crm[0-9]*\.dynamics\.com/?", cfg["environmentUrl"]):
        raise ValueError("Invalid Dataverse target URL")
    for key in ("tenantId", "organizationId", "environmentId", "medicalDirectorObjectId", "unauthorizedTestObjectId"):
        if UUID(cfg[key]).int == 0:
            raise ValueError("Empty identity/target GUID")
    if cfg["medicalDirectorObjectId"].lower() == cfg["unauthorizedTestObjectId"].lower():
        raise ValueError("Reviewer and negative-test identities must differ")
    if not re.fullmatch(r"[a-z][a-z0-9]{1,7}", cfg["publisherPrefix"]):
        raise ValueError("Invalid publisher prefix")
    for key in ("publisherUniqueName", "solutionUniqueName"):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,79}", cfg[key]):
            raise ValueError("Invalid publisher/solution unique name")
    return cfg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--approved-environment")
    args = parser.parse_args()
    cfg = load(args.config)
    if not args.verify and (not args.execute or (args.approved_environment or "").rstrip("/") != cfg["environmentUrl"].rstrip("/")):
        raise SystemExit("No mutation performed. Supply --execute and the explicitly approved --approved-environment URL.")
    from auth import get_client
    client, credential, context = get_client(cfg, "dv-query" if args.verify else "dv-metadata")
    org = client.records.list("organization", select=["organizationid", "name"], top=1).first()
    if org is None or org["organizationid"].lower() != cfg["organizationId"].lower():
        raise SystemExit("Organization does not match the approved target")
    schema = json.loads((ROOT / "dataverse/schema.json").read_text().replace("{prefix}", cfg["publisherPrefix"]))
    if args.verify:
        for table in schema["tables"]:
            if not client.tables.get(table["name"]):
                raise SystemExit("Missing table: "+table["name"])
        rules = client.records.list(cfg["publisherPrefix"]+"_medical_policy_rules", select=[cfg["publisherPrefix"]+"_rule_id"], top=10)
        solution = client.records.list("solution", filter=f"uniquename eq '{cfg['solutionUniqueName']}'", select=["solutionid"], top=1).first()
        if not solution:
            raise SystemExit("Solution record missing")
        components = client.records.list("solutioncomponent", filter=f"_solutionid_value eq {solution['solutionid']}", select=["componenttype", "objectid"])
        print(json.dumps({"organizationAuditValidation": "Performed by the PAC setup wrapper", "rules": list(rules),
                          "components": list(components), "runtimeAcceptanceVerified": False}, default=str))
        return
    publisher = client.records.list("publisher", filter=f"customizationprefix eq '{cfg['publisherPrefix']}'", select=["publisherid", "uniquename"], top=2).first()
    if publisher and publisher["uniquename"] != cfg["publisherUniqueName"]:
        raise SystemExit("Publisher prefix is owned by a different publisher; no overwrite performed")
    publisher_id = publisher["publisherid"] if publisher else client.records.create("publisher", {
        "uniquename": cfg["publisherUniqueName"], "friendlyname": cfg["publisherDisplayName"], "customizationprefix": cfg["publisherPrefix"]})
    solution = client.records.list("solution", filter=f"uniquename eq '{cfg['solutionUniqueName']}'", select=["solutionid", "_publisherid_value"], top=1).first()
    if solution and solution["_publisherid_value"].lower() != str(publisher_id).lower():
        raise SystemExit("Existing solution uses another publisher; no overwrite performed")
    if not solution:
        client.records.create("solution", {"uniquename": cfg["solutionUniqueName"], "friendlyname": cfg["solutionDisplayName"],
            "version": "1.0.0.0", "publisherid@odata.bind": f"/publishers({publisher_id})"})
    import requests
    api = cfg["environmentUrl"].rstrip("/")+"/api/data/v9.2/"
    metadata_access_token = None
    def metadata_call(method, path, payload):
        nonlocal metadata_access_token
        # Used only for metadata gaps and the unbound PublishXml action.
        if metadata_access_token is None or metadata_access_token.expires_on < time.time()+120:
            metadata_access_token = credential.get_token(cfg["environmentUrl"].rstrip("/")+"/.default")
        token = metadata_access_token.token
        headers = {"Authorization": "Bearer "+token, "Content-Type": "application/json", "OData-Version": "4.0",
                   "User-Agent": f"zava-claims-delivery ({context})", "MSCRM.SolutionUniqueName": cfg["solutionUniqueName"],
                   "MSCRM.MergeLabels": "true", "Consistency": "Strong"}
        try:
            if method == "PATCH":
                # Metadata uses full-definition PUT, unlike business-row PATCH.
                current = requests.get(api+path, headers=headers, timeout=60)
                current.raise_for_status()
                definition = current.json()
                if "/Attributes(" in path:
                    metadata_type = definition["@odata.type"].removeprefix("#")
                    cast_path = path+"/"+metadata_type
                    current = requests.get(api+cast_path, headers=headers, timeout=60)
                    current.raise_for_status()
                    definition = current.json()
                    path = cast_path
                definition.pop("@odata.context", None)
                for key, value in payload.items():
                    if isinstance(value, dict) and isinstance(definition.get(key), dict):
                        definition[key].update(value)
                    else:
                        definition[key] = value
                payload, method = definition, "PUT"
            response = requests.request(method, api+path, headers=headers, json=payload, timeout=60)
            if not response.ok:
                # Avoid dumping raw service payloads into logs.
                raise RuntimeError(f"Scoped Dataverse metadata operation failed with HTTP {response.status_code}")
        finally:
            token = None
            headers.clear()
    from PowerPlatform.Dataverse.core.errors import MetadataError
    for table in schema["tables"]:
        columns = column_types(table)
        existing = client.tables.get(table["name"])
        if not existing:
            # The SDK adds the primary name column itself. Including it twice
            # produces duplicate metadata in the create request.
            create_columns = column_types(table, include_primary=False)
            client.tables.create(table["name"], create_columns, solution=cfg["solutionUniqueName"], primary_column=table["primaryName"], display_name=table["displayName"])
            print("Created table: "+table["name"], flush=True)
        # Phased add/check protects partially completed reruns; never overwrite a row.
        for attempt in range(12):
            try:
                present = {c["LogicalName"] for c in client.tables.list_columns(table["name"], select=["LogicalName", "AttributeType"])}
                break
            except MetadataError:
                if attempt == 11:
                    raise
                print("Waiting for new table metadata: "+table["name"], flush=True)
                time.sleep(10)
        missing = {k: v for k, v in columns.items() if k not in present}
        if missing:
            client.tables.add_columns(table["name"], missing)
        metadata_call("PATCH", f"EntityDefinitions(LogicalName='{table['name']}')", {"IsAuditEnabled": {"Value": True}})
        for field in table["columns"]:
            metadata_call("PATCH", f"EntityDefinitions(LogicalName='{table['name']}')/Attributes(LogicalName='{field['name']}')", {
                "IsAuditEnabled": {"Value": True}, "DisplayName": {"LocalizedLabels": [{"Label": field["displayName"], "LanguageCode": 1033}]}})
    time.sleep(15)
    for table in schema["tables"]:
        existing_keys = client.tables.get_alternate_keys(table["name"])
        existing_names = {k.schema_name for k in existing_keys}
        for index, key_columns in enumerate(table["alternateKeys"]):
            key_name = table["name"]+"_key"+str(index+1)
            if key_name not in existing_names:
                client.tables.create_alternate_key(table["name"], key_name, key_columns, display_name=key_name)
    for table in schema["tables"]:
        wanted = {table["name"]+"_key"+str(i+1) for i in range(len(table["alternateKeys"]))}
        for attempt in range(12):
            keys = {k.schema_name: k.status for k in client.tables.get_alternate_keys(table["name"])}
            if any(keys.get(k) == "Failed" for k in wanted):
                raise SystemExit("Alternate-key index build failed; inspect the scoped table before retry")
            if all(keys.get(k) == "Active" for k in wanted):
                break
            time.sleep(10)
        else:
            raise SystemExit("Alternate-key activation remains pending; do not proceed with duplicate-sensitive data operations")
    metadata_call("POST", "PublishXml", {"ParameterXml": "<importexportxml><entities>"+"".join("<entity>"+t["name"]+"</entity>" for t in schema["tables"])+"</entities></importexportxml>"})
    # The approved setup wrapper enables/reads organization auditing with PAC.
    # This metadata script only changes the three claims tables and columns.
    prefix = cfg["publisherPrefix"]+"_"
    fields = {"ruleId": "rule_id", "policyNumber": "policy_number", "policyVersion": "policy_version", "cptCode": "cpt_code",
        "naturalLanguageRule": "natural_language_rule", "minConservativeWeeks": "min_conservative_weeks",
        "requiresPt": "requires_pt", "requiresPharmacology": "requires_pharmacology", "active": "is_active",
        "kind": "rule_kind", "clinicalPath": "clinical_path", "minPtSessionsPerWeek": "min_pt_sessions_week", "requiresFailedTreatment": "requires_failed_treatment"}
    for rule in json.loads((ROOT / "dataverse/policy-seed.json").read_text()):
        row = {prefix+target: (False if rule[source] is None and source in {"requiresPt", "requiresPharmacology", "requiresFailedTreatment"} else rule[source]) for source, target in fields.items()}
        row[prefix+"enforcement_level"] = {"Strict_Block": 100000000, "Medical_Director_Review": 100000001, "Audit_Only": 100000002}[rule["enforcement"]]
        row[prefix+"effective_from"] = rule["effectiveFrom"]+"T00:00:00Z"
        old = client.records.list(prefix+"medical_policy_rules", filter=f"{prefix}rule_id eq '{rule['ruleId']}' and {prefix}policy_version eq '{rule['policyVersion']}'", select=list(row), top=1).first()
        if old:
            for key, value in row.items():
                if key.endswith("effective_from"):
                    continue
                if old.get(key) != value:
                    raise SystemExit("Existing policy differs from the seed; no overwrite performed")
        else:
            client.records.create(prefix+"medical_policy_rules", row)
    print("Created/verified claims tables and three seed rules. Native roles, connections, agent, flows, fixture import and acceptance remain required.")


if __name__ == "__main__":
    main()

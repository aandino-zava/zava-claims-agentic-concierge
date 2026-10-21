"""Offline SDK payload/signature probe. Authentication and HTTP are forbidden.

Private SDK builders are inspected only in this compatibility probe, never used
by the deployment runtime. Successful payload construction is not Dev acceptance.
"""
import argparse
import inspect
import json
import sys
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk-dir")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.sdk_dir:
        sys.path.insert(0, str(Path(args.sdk_dir).resolve()))
    from PowerPlatform.Dataverse.data._odata import _ODataClient
    from PowerPlatform.Dataverse.operations.tables import TableOperations
    from bootstrap_dataverse import column_types
    schema = json.loads((ROOT/"dataverse/schema.json").read_text().replace("{prefix}", "cr"))
    records = []
    with patch("requests.sessions.Session.request", side_effect=AssertionError("No network allowed in SDK contract probe")):
        sdk = _ODataClient(auth=None, base_url="https://orgpoc.crm.dynamics.com")
        try:
            sdk._get_entity_by_table_schema_name = lambda _: None
            for table in schema["tables"]:
                columns = column_types(table, include_primary=False)
                inspect.signature(TableOperations.create).bind(None, table["name"], columns, solution="ZavaMedicalClaimsConcierge",
                    primary_column=table["primaryName"], display_name=table["displayName"])
                inspect.signature(TableOperations.add_columns).bind(None, table["name"], columns)
                captured = {}
                def capture(**kwargs):
                    captured.update(kwargs)
                    return {"LogicalName": table["name"], "EntitySetName": table["name"]+"s", "MetadataId": "offline", "PrimaryNameAttribute": table["primaryName"]}
                sdk._create_entity = capture
                sdk._create_table(table["name"], columns, solution_unique_name="ZavaMedicalClaimsConcierge",
                                  primary_column_schema_name=table["primaryName"], display_name=table["displayName"])
                attributes = captured["attributes"]
                names = [a["SchemaName"] for a in attributes]
                assert len(names) == len(set(names)) == len(table["columns"]), "Duplicate or missing metadata attribute"
                assert sum(a.get("IsPrimaryName", False) for a in attributes) == 1
                for field in table["columns"]:
                    if field["type"] == "memo":
                        assert next(a for a in attributes if a["SchemaName"] == field["name"])["MaxLength"] == field["maxLength"]
                records.append({"table": table["name"], "attributes": len(names), "primaryName": table["primaryName"], "result": "ConstructedOffline"})
        finally:
            sdk.close()
    result = {"sdkVersion": version("PowerPlatform-Dataverse-Client"), "networkAllowed": False,
              "cloudAcceptanceVerified": False, "tablePayloads": records}
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

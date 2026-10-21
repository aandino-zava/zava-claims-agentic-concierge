"""Load only explicitly labelled synthetic fixtures after Dev approval."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from bootstrap_dataverse import load, ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-environment")
    args = parser.parse_args()
    cfg = load(args.config)
    if not args.execute or (args.approved_environment or "").rstrip("/") != cfg["environmentUrl"].rstrip("/"):
        raise SystemExit("Synthetic fixture import requires the explicitly approved Dev URL")
    from auth import get_client
    client, _, _ = get_client(cfg, "dv-data")
    org = client.records.list("organization", select=["organizationid"], top=1).first()
    if not org or org["organizationid"].lower() != cfg["organizationId"].lower():
        raise SystemExit("Wrong organization")
    fixtures = ROOT / "tests/fixtures"
    claims = {c["claimId"]: c for c in json.loads((fixtures / "claims.json").read_text())}
    prefix = cfg["publisherPrefix"]+"_"
    for evidence in json.loads((fixtures / "evidence.json").read_text()):
        if evidence["synthetic"] is not True or not evidence["claimId"].startswith("SYN-"):
            raise SystemExit("Non-synthetic data rejected")
        identifier = "SYN-EVIDENCE-"+evidence["claimId"].split("-")[-1]
        old = client.records.list(prefix+"claim_evidence", filter=f"{prefix}evidence_id eq '{identifier}'", select=[prefix+"evidence_id"], top=1).first()
        if old:
            # Never overwrite a changed verification state or clinical facts.
            print("Preserved existing fixture "+identifier)
            continue
        sources = []
        for source in evidence["sources"]:
            path = (fixtures/source["path"]).resolve()
            if not path.is_relative_to(fixtures.resolve()):
                raise SystemExit("Source path outside fixtures")
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != source["sha256"]:
                raise SystemExit("Fixture hash mismatch")
            sources.append({**source, "bodyBase64": base64.b64encode(body).decode("ascii")})
        facts = {k: v for k, v in evidence.items() if k not in {"sources", "attestedBy", "attestedAt"}}
        facts["attestationMode"] = "SyntheticFixture"
        row = {prefix+"evidence_id": identifier, prefix+"claim_id": evidence["claimId"], prefix+"member_id": evidence["memberId"],
               prefix+"cpt_code": evidence["cptCode"], prefix+"policy_number": evidence["policyNumber"], prefix+"policy_version": evidence["policyVersion"],
               prefix+"source_version": 1, prefix+"verification_state": 100000001, prefix+"is_synthetic": True,
               prefix+"facts_json": json.dumps(facts), prefix+"sources_json": json.dumps(sources),
               prefix+"claim_snapshot_json": json.dumps(claims[evidence["claimId"]]),
               prefix+"review_summary": f"SYNTHETIC POC: {evidence['fixtureName']}. {len(evidence['sessions'])} recorded PT sessions; {len(evidence['medications'])} medication record(s); {len(evidence['sources'])} source record(s). Red-flag fixture: {evidence['redFlagsVerified']}. These generated records are not a human clinical attestation."}
        client.records.create(prefix+"claim_evidence", row)
    print("Synthetic fixtures loaded. No human attestation or claims portal write was performed.")


if __name__ == "__main__":
    main()

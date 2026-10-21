"""Prepare an authentic unpacked claims export; never contacts a tenant.

Keep the raw export as a recoverable installation snapshot. This operation
changes only the unpacked local copy and rejects unfamiliar native structure.
"""
import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',default=str(ROOT/'solution/src'))
    parser.add_argument('--provenance',default=str(ROOT/'solution/provenance.json'))
    args=parser.parse_args()
    source=Path(args.source).resolve()
    provenance=Path(args.provenance)
    record=json.loads(provenance.read_text(encoding='utf-8-sig'))
    assert record.get('nativeExportPresent') is True, 'Authentic export provenance required'
    manifest=ET.parse(source/'Other/Solution.xml').getroot().find('SolutionManifest')
    assert manifest.findtext('UniqueName')=='ZavaMedicalClaimsConcierge'
    assert manifest.findtext('Managed')=='0'
    assert {p.name for p in (source/'Entities').iterdir() if p.is_dir()}=={'cr_claim_evidence','cr_claim_evaluation','cr_medical_policy_rules'}, 'Unrelated or missing table requires review'
    expected={'EvaluateClaimWithRuleCheck','ReviewAndCompleteClaimEvaluation'}
    flows=list((source/'Workflows').glob('*.json'))
    assert len(flows)==2 and {p.name.split('-')[0] for p in flows}==expected
    neutral={'ClaimsMode':'Simulated','ProcessingEnabled':'no','PolicyVersion':'1.0','ApprovalLifetimeHours':24}
    installation_values=set()
    for path in flows:
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        parameters=data['properties']['definition']['parameters']
        for name,value in parameters.items():
            if name.startswith('$'): continue
            assert value.get('metadata',{}).get('schemaName')=='cr_'+name, 'Unexpected parameter binding'
            prior=value.get('defaultValue')
            if name not in neutral and isinstance(prior,str) and prior:
                installation_values.add(prior.rstrip('/'))
            value['defaultValue']=neutral.get(name,'')
        path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
        metadata=path.with_suffix('.json.data.xml')
        tree=ET.parse(metadata); root=tree.getroot()
        assert root.find('StateCode') is not None and root.find('StatusCode') is not None
        root.find('StateCode').text='0'; root.find('StatusCode').text='1'
        tree.write(metadata,encoding='utf-8',xml_declaration=True)
    for path in (source/'environmentvariabledefinitions').glob('*/environmentvariablevalues.json'):
        suffix=path.parent.name.removeprefix('cr_')
        current=json.loads(path.read_text(encoding='utf-8-sig'))['environmentvariablevalues']['environmentvariablevalue']
        current=[current] if isinstance(current,dict) else current
        for item in current:
            value=item.get('value')
            if suffix not in neutral and isinstance(value,str) and value:
                installation_values.add(value.rstrip('/'))
        path.unlink()  # Current values belong to the receiving installation.
    for path in (source/'environmentvariabledefinitions').glob('*/environmentvariabledefinition.xml'):
        tree=ET.parse(path); root=tree.getroot(); suffix=root.attrib['schemaname'].removeprefix('cr_')
        default=root.find('defaultvalue')
        if default is not None: default.text=str(neutral.get(suffix,''))
        tree.write(path,encoding='utf-8',xml_declaration=True)
    knowledge=[]; retired=[]; enabled_flow_tools=[]
    for path in (source/'botcomponents').glob('*/data'):
        data=path.read_text(encoding='utf-8-sig')
        if 'RetiredPreviewBinding' in data:
            assert 'kind: InvokeFlowTaskAction' not in data, 'Do not remove a working flow binding'
            retired.append(path.parent)
        if 'kind: AzureAISearchSource' in data:
            knowledge.append(path)
            for field,placeholder in [('indexName','configure-search-index'),('semanticConfigurationName','configure-semantic-configuration')]:
                data,count=re.subn(r'(?m)^(  '+field+r':) .+$',lambda m:m[1]+' '+placeholder,data)
                assert count==1, 'Unfamiliar native knowledge configuration'
            path.write_text(data,encoding='utf-8')
        if 'kind: InvokeFlowTaskAction' in data:
            assert 'flowId: 4fcf9742-1ccd-f111-a05a-000d3a33def5' in data and 'mode: Invoker' in data
            enabled_flow_tools.append(path)
    assert len(knowledge)==1 and len(enabled_flow_tools)==1, 'Native Search and Gatekeeper binding must be present'
    for folder in retired:
        assert folder.parent==source/'botcomponents'
        assert {p.name for p in folder.iterdir()}=={'data','botcomponent.xml'}
        # Do not delete anything in Dev; omit only this disabled local duplicate.
        for path in folder.iterdir(): path.unlink()
        folder.rmdir()
    role=ET.parse(next((source/'Roles').glob('*.xml'))).getroot()
    claims_privileges={p.attrib['name']:p.attrib['level'] for p in role.findall('./RolePrivileges/RolePrivilege') if 'cr_claim_' in p.attrib['name'] or 'cr_medical_policy_' in p.attrib['name']}
    assert claims_privileges=={'prvReadcr_claim_evaluation':'Global','prvReadcr_claim_evidence':'Global','prvReadcr_medical_policy_rules':'Global'}, 'Claims-specific role must remain read only'
    # Reject rather than silently rewrite unknown credentials or lab identities.
    forbidden=sorted(installation_values)
    for path in source.rglob('*'):
        if not path.is_file(): continue
        try: data=path.read_text(encoding='utf-8-sig')
        except UnicodeError: continue
        assert not any(value.lower() in data.lower() for value in forbidden), 'Installation value requires review: '+str(path.relative_to(source))
        assert not re.search(r'Bearer\s+[A-Za-z0-9._-]{35,}|[?&]sig=[A-Za-z0-9_%+-]{20,}',data), 'Credential-like value requires review'
    record.update(state='PortableNativeSourcePrepared',portableReviewComplete=False,processingEnabledInDistributable=False,
                  nativeExportPresent=True,importableSolutionPresent=False,
                  nativeFlowCount=2,enabledAgentToolCount=3,claimsRoleCount=1,
                  receivingKnowledgeConfigurationRequired=True,
                  receivingImportVerified=False,
                  omittedDisabledPreviewBindings=len(retired),
                  dependencyReview='Standard AppModuleWebResources and PowerAppsAppFramework packages required in receiving Dev')
    for key in ['packageSha256','checkerStatus','checkerFindings','checkerReportSha256']:
        record.pop(key,None)  # A new export/package cannot inherit an old analysis.
    provenance.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'prepared':True,'flowCount':2,'processingEnabled':False,'nativeFlowBindingPreserved':True,'receivingImportVerified':False}))


if __name__=='__main__': main()

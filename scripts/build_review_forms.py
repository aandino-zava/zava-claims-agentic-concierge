"""Customize only the claims tables' generated native forms and views."""
import argparse
import copy
import json
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date
from pathlib import Path
from uuid import uuid4
from bootstrap_dataverse import load, ROOT
from auth import get_client


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True)
    parser.add_argument('--approved-environment',required=True); parser.add_argument('--evidence-dir',required=True)
    args=parser.parse_args(); cfg=load(args.config)
    if args.approved_environment.rstrip('/')!=cfg['environmentUrl'].rstrip('/'):
        raise SystemExit('Exact approved Dev target required')
    client,credential,context=get_client(cfg,'dv-metadata')
    org=client.records.list('organization',select=['organizationid'],top=1).first()
    if org['organizationid'].lower()!=cfg['organizationId'].lower(): raise SystemExit('Wrong target')
    import requests
    token=credential.get_token(cfg['environmentUrl'].rstrip('/')+'/.default')
    api=cfg['environmentUrl'].rstrip('/')+'/api/data/v9.2/'
    headers={'Authorization':'Bearer '+token.token,'Content-Type':'application/json','Consistency':'Strong',
             'MSCRM.MergeLabels':'true','MSCRM.SolutionUniqueName':cfg['solutionUniqueName'],'User-Agent':'zava-claims-delivery ('+context+')'}
    destination=Path(args.evidence_dir); destination.mkdir(parents=True,exist_ok=True)
    prefix=cfg['publisherPrefix']+'_'
    schema=json.loads((ROOT/'dataverse/schema.json').read_text().replace('{prefix}',cfg['publisherPrefix']))
    selected={
        'medical_policy_rules':['rule_id','policy_number','policy_version','cpt_code','rule_kind','enforcement_level','natural_language_rule','min_conservative_weeks','min_pt_sessions_week','requires_pt','requires_pharmacology','requires_failed_treatment','is_active'],
        'claim_evidence':['evidence_id','claim_id','member_id','cpt_code','verification_state','source_version','review_summary'],
        'claim_evaluation':['evaluation_id','claim_id','member_id','state','outcome','mode','review_summary','correlation_id','expires_at','approval_id']}
    classes={'string':'{4273EDBD-AC1D-40d3-9FB2-095C621B552D}','memo':'{E0DECE4B-6FC8-4a8f-A065-082708572369}',
        'int':'{C6D124CA-7EDA-4a60-AEA9-7FB8D318B68F}','datetime':'{5B773807-9FB2-42db-97C3-7A91EFF8ADFF}',
        'bool':'{67FAC785-CD58-4f9f-ABB3-4B7DDC6ED5ED}','choice':'{3EF39988-22BB-4f0b-BBBE-64B5A3748AEE}'}
    names={'medical_policy_rules':('Medical Policy Rule','Medical Policy Rules'),'claim_evidence':('Claim Evidence Facts','Claim Evidence Facts'),
           'claim_evaluation':('Claim Evaluation','Claim Evaluations')}
    report=[]
    for table in schema['tables']:
        logical=table['name']; suffix=logical[len(prefix):]
        metadata=requests.get(api+"EntityDefinitions(LogicalName='"+logical+"')",headers=headers,timeout=60); metadata.raise_for_status()
        full=metadata.json(); full.pop('@odata.context',None)
        singular,plural=names[suffix]
        for key,label in [('DisplayName',singular),('DisplayCollectionName',plural)]:
            full[key]['LocalizedLabels']=[{'Label':label,'LanguageCode':1033}]
        changed=requests.put(api+"EntityDefinitions(LogicalName='"+logical+"')",headers=headers,json=full,timeout=60); changed.raise_for_status()
        form=client.records.list('systemform',filter="objecttypecode eq '"+logical+"' and type eq 2",select=['formid','name','formxml'],top=1).first()
        if not form: raise RuntimeError('No generated Main form for '+logical)
        (destination/(logical+'-form-before.xml')).write_text(form['formxml'])
        root=ET.fromstring(form['formxml'])
        rows=root.find('.//tabs/tab/columns/column/sections/section/rows')
        if rows is None: raise RuntimeError('Generated form lacks expected rows container')
        # Generated forms already contain every custom field. Replace their
        # rows with the review projection; merely appending leaves raw JSON
        # and editable defaults visible.
        for row in list(rows): rows.remove(row)
        columns={column['name']:column for column in table['columns']}
        for field in selected[suffix]:
            name=prefix+field
            column=columns[name]
            row=ET.SubElement(rows,'row'); cell=ET.SubElement(row,'cell',{'id':'{'+str(uuid4()).upper()+'}','showlabel':'true',
                **({'rowspan':'18','auto':'false'} if column['type']=='memo' else {})})
            labels=ET.SubElement(cell,'labels'); ET.SubElement(labels,'label',{'description':column['displayName'],'languagecode':'1033'})
            ET.SubElement(cell,'control',{'id':name,'datafieldname':name,'classid':classes[column['type']],
                'disabled':'true','uniqueid':'{'+str(uuid4()).upper()+'}'})
        client.records.update('systemform',form['formid'],{'name':'Claims Review - '+singular,'formxml':ET.tostring(root,encoding='unicode')})
        view=client.records.list('savedquery',filter="returnedtypecode eq '"+logical+"' and querytype eq 0",select=['savedqueryid','name','fetchxml','layoutxml','isdefault'],top=10)
        candidates=list(view); target=next((x for x in candidates if x.get('isdefault')),candidates[0] if candidates else None)
        if target:
            (destination/(logical+'-view-before.json')).write_text(json.dumps(dict(target),indent=2))
            fetch=ET.fromstring(target['fetchxml']); entity=fetch.find('entity')
            layout=ET.fromstring(target['layoutxml']); layout_row=layout.find('row')
            wanted=[prefix+k for k in selected[suffix] if k not in {'natural_language_rule','review_summary','min_conservative_weeks','min_pt_sessions_week','requires_pt','requires_pharmacology','requires_failed_treatment','is_active','approval_id'}][:7]
            for attr in list(entity.findall('attribute')): entity.remove(attr)
            for cell in list(layout_row): layout_row.remove(cell)
            ET.SubElement(entity,'attribute',{'name':logical+'id'})
            for name in wanted:
                ET.SubElement(entity,'attribute',{'name':name}); ET.SubElement(layout_row,'cell',{'name':name,'width':'180'})
            client.records.update('savedquery',target['savedqueryid'],{'name':'Claims Review - '+plural,
                'fetchxml':ET.tostring(fetch,encoding='unicode'),'layoutxml':ET.tostring(layout,encoding='unicode')})
        report.append({'table':logical,'formId':form['formid'],'readOnlyReviewFields':selected[suffix]})
        print('Built native review form and view: '+logical,flush=True)
    for row in client.records.list(prefix+'claim_evidence',filter=prefix+'is_synthetic eq true',
             select=[prefix+'claim_evidenceid',prefix+'facts_json',prefix+'sources_json',prefix+'review_summary'],top=20):
        facts=json.loads(row[prefix+'facts_json']); sources=json.loads(row[prefix+'sources_json'])
        if not facts.get('claimId','').startswith('SYN-'): continue
        if not row.get(prefix+'review_summary','').startswith('SYNTHETIC POC:'): continue
        start=date.fromisoformat(facts['therapyStart']) if facts.get('therapyStart') else None
        end=date.fromisoformat(facts['therapyEndExclusive']) if facts.get('therapyEndExclusive') else None
        counts=Counter((date.fromisoformat(s['date'])-start).days//7 for s in facts.get('sessions',[]) if s['attended'] is True and start)
        weeks=(end-start).days//7 if start and end else 0
        lines=['SYNTHETIC POC: '+facts['fixtureName'],'Generated fixture; not a human clinical attestation.',
            'Claim: '+facts['claimId']+' | Member: '+facts['memberId']+' | CPT: '+facts['cptCode'],
            'Policy: '+facts['policyNumber']+' / '+facts['policyVersion'],'Indication: '+str(facts.get('indication')),
            'Therapy: '+str(facts.get('therapyStart'))+' through '+str(facts.get('therapyEndExclusive'))+' (end exclusive)',
            'Complete weeks: '+str(weeks)+' | attended PT counts by week: '+str([counts[i] for i in range(weeks)]),
            'Failed or worsened: '+str(facts.get('treatmentFailedOrWorsened'))+' | Verified red flags: '+str(facts.get('redFlagsVerified')),
            'Contradictions: '+('; '.join(facts.get('contradictions',[])) or 'None recorded'),'Medication documentation:']
        lines += [m['category']+' | '+m['start']+' through '+m['endExclusive']+' (end exclusive) | verified: '+str(m['verified']) for m in facts.get('medications',[])] or ['None attached']
        lines += ['Protected source records:']+[s['documentId']+' | '+str(s['pages'])+' page(s) | SHA-256 '+s['sha256'] for s in sources]
        client.records.update(prefix+'claim_evidence',row[prefix+'claim_evidenceid'],{prefix+'review_summary':'\n'.join(lines)[:4000]})
    response=requests.post(api+'PublishXml',headers=headers,json={'ParameterXml':'<importexportxml><entities>'+''.join('<entity>'+t['name']+'</entity>' for t in schema['tables'])+'</entities></importexportxml>'},timeout=90)
    response.raise_for_status()
    (destination/'native-review-forms.json').write_text(json.dumps(report,indent=2))
    print('Published only claims forms/views; synthetic facts and real claims unchanged.')


if __name__=='__main__': main()

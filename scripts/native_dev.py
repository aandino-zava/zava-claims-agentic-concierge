"""Scoped, approved Dev component authoring through the official SDK.

The Web API helper covers solution membership and publishing actions only.
Runtime claims remain simulated. No claims portal mutation is implemented.
"""
import argparse
import json
from pathlib import Path
from bootstrap_dataverse import load, ROOT
from auth import get_client


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--operation',choices=['inspect','configure','configure-runtime','read-flow','write-flow','off-flow','activate-flow','enable-processing'],required=True)
    parser.add_argument('--flow-name')
    parser.add_argument('--definition')
    parser.add_argument('--evidence-dir',required=True)
    parser.add_argument('--approved-environment')
    parser.add_argument('--search-connection')
    args=parser.parse_args()
    cfg=load(args.config)
    evidence=Path(args.evidence_dir)
    evidence.mkdir(parents=True,exist_ok=True)
    writing=args.operation not in {'inspect','read-flow'}
    if writing and (args.approved_environment or '').rstrip('/') != cfg['environmentUrl'].rstrip('/'):
        raise SystemExit('Exact approved Dev environment required')
    client,credential,context=get_client(cfg,'dv-solution' if writing else 'dv-query')
    org=client.records.list('organization',select=['organizationid','isauditenabled'],top=1).first()
    if not org or org['organizationid'].lower()!=cfg['organizationId'].lower():
        raise SystemExit('Wrong organization')
    solution=client.records.list('solution',filter="uniquename eq '"+cfg['solutionUniqueName']+"'",select=['solutionid'],top=1).first()
    if not solution:
        raise SystemExit('Approved solution missing')
    import requests
    token=None
    def action(name,payload):
        nonlocal token
        if token is None:
            token=credential.get_token(cfg['environmentUrl'].rstrip('/')+'/.default')
        response=requests.post(cfg['environmentUrl'].rstrip('/')+'/api/data/v9.2/'+name,
            headers={'Authorization':'Bearer '+token.token,'Content-Type':'application/json',
                     'User-Agent':'zava-claims-delivery ('+context+')','MSCRM.SolutionUniqueName':cfg['solutionUniqueName']},
            json=payload,timeout=90)
        if not response.ok:
            detail=response.json().get('error',{})
            raise RuntimeError(name+' HTTP '+str(response.status_code)+' '+str(detail.get('message',''))[:700])
        return response.json() if response.content else {}
    def add(identifier,kind):
        action('AddSolutionComponent',{'ComponentId':str(identifier),'ComponentType':kind,
            'SolutionUniqueName':cfg['solutionUniqueName'],'AddRequiredComponents':False})
    def connection_component_type():
        nonlocal token
        if args.search_connection:
            siblings=client.records.list('connectionreference',filter="connectionid eq '"+args.search_connection+"'",select=['connectionreferenceid'],top=10)
            for sibling in siblings:
                component=client.records.list('solutioncomponent',filter="objectid eq "+sibling['connectionreferenceid'],select=['componenttype'],top=1).first()
                if component:
                    return component['componenttype']
        if token is None:
            token=credential.get_token(cfg['environmentUrl'].rstrip('/')+'/.default')
        response=requests.get(cfg['environmentUrl'].rstrip('/')+"/api/data/v9.2/EntityDefinitions(LogicalName='solutioncomponent')/Attributes(LogicalName='componenttype')/Microsoft.Dynamics.CRM.PicklistAttributeMetadata",
            params={'$expand':'OptionSet'},headers={'Authorization':'Bearer '+token.token,'User-Agent':'zava-claims-delivery ('+context+')'},timeout=60)
        response.raise_for_status()
        matches=[option['Value'] for option in response.json()['OptionSet']['Options']
            if any(label['Label'].replace(' ','').lower()=='connectionreference' for label in option.get('Label',{}).get('LocalizedLabels',[]))]
        if len(matches)!=1:
            raise RuntimeError('Cannot resolve native connection-reference component type')
        return matches[0]
    if args.operation=='inspect':
        tables=client.tables.list(filter="LogicalName eq 'cr_medical_policy_rules' or LogicalName eq 'cr_claim_evidence' or LogicalName eq 'cr_claim_evaluation'",
             select=['LogicalName','MetadataId','EntitySetName','PrimaryIdAttribute','IsAuditEnabled'])
        result={'organization':dict(org),'solution':dict(solution),'tables':tables}
        (evidence/'live-components.json').write_text(json.dumps(result,indent=2,default=str))
        print(json.dumps(result,default=str))
    elif args.operation=='configure-runtime':
        # A solution import transports definitions; explicit target configuration
        # materializes environment parameters without enabling processing.
        import re
        from build_native_flows import environment_parameters
        semantic=cfg.get('searchSemanticConfiguration','')
        if cfg['publisherPrefix']!='cr' or not re.fullmatch(r'[a-z0-9][a-z0-9-]*',cfg['searchIndex']):
            raise ValueError('Expected the exported cr package and a valid receiving Search index name')
        if not re.fullmatch(r'[A-Za-z0-9_-]+',semantic):
            raise ValueError('Supply the actual receiving Search semantic configuration')
        results=[]
        for name in ['EvaluateClaimWithRuleCheck','ReviewAndCompleteClaimEvaluation']:
            rows=list(client.records.list('workflow',filter="name eq '"+name+"' and category eq 5",select=['workflowid','clientdata'],top=2))
            if len(rows)!=1: raise RuntimeError('Expected exactly one imported claims flow: '+name)
            flow=rows[0]
            (evidence/(name+'-before-target-configuration.json')).write_text(json.dumps(dict(flow),indent=2))
            data=json.loads(flow['clientdata'])
            data['properties']['definition']['parameters'].update(environment_parameters(cfg))
            client.records.update('workflow',flow['workflowid'],{'statecode':0,'statuscode':1})
            client.records.update('workflow',flow['workflowid'],{'clientdata':json.dumps(data)})
            check=client.records.retrieve('workflow',flow['workflowid'],select=['statecode','clientdata'])
            assert check['statecode']==0 and json.loads(check['clientdata'])['properties']['definition']['parameters']['ProcessingEnabled']['defaultValue']=='no'
            results.append({'name':name,'state':'Off','processingEnabled':False})
        bots=list(client.records.list('bot',filter="schemaname eq '"+cfg['publisherPrefix']+"_ZavaMedicalClaimsConcierge'",select=['botid'],top=2))
        if len(bots)!=1: raise RuntimeError('Expected one imported claims agent')
        components=list(client.records.list('botcomponent',filter='_parentbotid_value eq '+bots[0]['botid'],select=['botcomponentid','data','name'],top=100))
        knowledge=[r for r in components if 'kind: AzureAISearchSource' in (r.get('data') or '')]
        if len(knowledge)!=1: raise RuntimeError('Expected one native claims Search knowledge source')
        row=knowledge[0]; data=row['data']
        for field,value in [('indexName',cfg['searchIndex']),('semanticConfigurationName',semantic)]:
            data,count=re.subn(r'(?m)^(  '+field+r':) .+$',lambda m:m[1]+' '+value,data)
            if count!=1: raise RuntimeError('Unexpected native Search configuration shape: '+field)
        client.records.update('botcomponent',row['botcomponentid'],{'data':data})
        (evidence/'target-runtime-configuration.json').write_text(json.dumps({'flows':results,'nativeKnowledgeConfigured':True,'published':False},indent=2))
        print('Configured only imported claims flow parameters and native Search index. Both flows remain Off; publish the agent after receiving acceptance.')
    elif args.operation=='enable-processing':
        definition=client.records.list('environmentvariabledefinition',filter="schemaname eq 'cr_ProcessingEnabled'",select=['environmentvariabledefinitionid'],top=1).first()
        current=client.records.list('environmentvariablevalue',filter='_environmentvariabledefinitionid_value eq '+definition['environmentvariabledefinitionid'],select=['environmentvariablevalueid','value'],top=1).first()
        client.records.update('environmentvariablevalue',current['environmentvariablevalueid'],{'value':'yes'})
        # Environment-variable parameter values are materialized when a cloud
        # flow is saved. Refresh the two owned Dev definitions explicitly.
        for name in ['EvaluateClaimWithRuleCheck','ReviewAndCompleteClaimEvaluation']:
            flow=client.records.list('workflow',filter="name eq '"+name+"' and category eq 5",select=['workflowid','clientdata'],top=1).first()
            data=json.loads(flow['clientdata'])
            data['properties']['definition']['parameters']['ProcessingEnabled']['defaultValue']='yes'
            client.records.update('workflow',flow['workflowid'],{'statecode':0,'statuscode':1})
            client.records.update('workflow',flow['workflowid'],{'clientdata':json.dumps(data)})
            client.records.update('workflow',flow['workflowid'],{'statecode':1,'statuscode':2})
            print('Refreshed approved simulated Dev flow: '+name,flush=True)
        print('Enabled simulated processing in approved Dev only. Portable default remains off.')
    elif args.operation=='configure':
        mapping={'SearchEndpoint':'searchEndpoint','SearchIndex':'searchIndex','MedicalDirectorObjectId':'medicalDirectorObjectId',
                 'MedicalDirectorUPN':'medicalDirectorUpn','ClaimsApiBaseUrl':'claimsApiBaseUrl',
                 'TenantId':'tenantId','DataverseUrl':'environmentUrl'}
        results=[]
        for var in json.loads((ROOT/'config/environment-variables.json').read_text()):
            name=cfg['publisherPrefix']+'_'+var['suffix']
            old=client.records.list('environmentvariabledefinition',filter="schemaname eq '"+name+"'",select=['environmentvariabledefinitionid'],top=1).first()
            identifier=old['environmentvariabledefinitionid'] if old else client.records.create('environmentvariabledefinition',{
                'schemaname':name,'displayname':'Claims '+var['suffix'],'type':{'String':100000000,'Boolean':100000002,'Decimal':100000001}[var['type']],
                'defaultvalue':var['defaultValue'],'description':'Zava Medical Claims Concierge POC configuration.'})
            add(identifier,380)
            value=cfg[mapping[var['suffix']]] if var['suffix'] in mapping else var['defaultValue']
            current=client.records.list('environmentvariablevalue',filter='_environmentvariabledefinitionid_value eq '+str(identifier),
                select=['environmentvariablevalueid','value'],top=2).first()
            if not current:
                client.records.create('environmentvariablevalue',{'value':str(value),
                    'EnvironmentVariableDefinitionId@odata.bind':'/environmentvariabledefinitions('+str(identifier)+')'})
            elif current['value']!=str(value) and not (var['suffix']=='ProcessingEnabled' and current['value'] in {'yes','true'}):
                raise RuntimeError('Existing current value differs: '+name)
            results.append({'schemaName':name,'definitionId':str(identifier),'configured':True})
            print('Configured '+name,flush=True)
        # Reuse only the owner's verified Dev Dataverse connection; do not modify it.
        connection_id=cfg.get('connections',{}).get('Dataverse','')
        if not connection_id: raise ValueError('Supply an authorized Dataverse connection ID in target configuration')
        connection={'name':connection_id,'properties':{'apiId':'/providers/Microsoft.PowerApps/apis/shared_commondataserviceforapps'}}
        logical=cfg['publisherPrefix']+'_ClaimsDataverse'
        old=client.records.list('connectionreference',filter="connectionreferencelogicalname eq '"+logical+"'",
            select=['connectionreferenceid'],top=1).first()
        identifier=old['connectionreferenceid'] if old else client.records.create('connectionreference',{
            'connectionreferencelogicalname':logical,'connectionreferencedisplayname':'Claims Dataverse',
            'connectorid':connection['properties']['apiId'],'connectionid':connection['name']})
        connection_type=connection_component_type()
        add(identifier,connection_type)
        results.append({'connectionReference':logical,'id':str(identifier),'connectionId':connection['name']})
        if args.search_connection:
            logical=cfg['publisherPrefix']+'_ClaimsAzureAISearch'
            old=client.records.list('connectionreference',filter="connectionreferencelogicalname eq '"+logical+"'",select=['connectionreferenceid'],top=1).first()
            identifier=old['connectionreferenceid'] if old else client.records.create('connectionreference',{
                'connectionreferencelogicalname':logical,'connectionreferencedisplayname':'Claims Azure AI Search',
                'connectorid':'/providers/Microsoft.PowerApps/apis/shared_azureaisearch','connectionid':args.search_connection})
            add(identifier,connection_type)
            results.append({'connectionReference':logical,'id':str(identifier),'connectionId':args.search_connection})
        (evidence/'native-configuration.json').write_text(json.dumps(results,indent=2))
    else:
        if args.flow_name not in {'EvaluateClaimWithRuleCheck','ReviewAndCompleteClaimEvaluation'}:
            raise SystemExit('Only the two approved claims flows are supported')
        flow=client.records.list('workflow',filter="name eq '"+args.flow_name+"' and category eq 5",
            select=['workflowid','name','clientdata','statecode'],top=2).first()
        if args.operation in {'off-flow','activate-flow'}:
            if not flow: raise SystemExit('Flow missing')
            state=1 if args.operation=='activate-flow' else 0
            client.records.update('workflow',flow['workflowid'],{'statecode':state,'statuscode':2 if state else 1})
            print(json.dumps({'id':flow['workflowid'],'requestedState':state}))
        elif args.operation=='read-flow':
            if not flow:
                raise SystemExit('Flow does not exist yet')
            (evidence/(args.flow_name+'-current.json')).write_text(json.dumps(dict(flow),indent=2))
            print(json.dumps({'id':flow['workflowid'],'state':flow['statecode'],'clientdataSaved':True}))
        else:
            payload=json.loads(Path(args.definition).read_text())
            if flow:
                previous=json.loads(flow['clientdata'])
                setting=previous.get('properties',{}).get('definition',{}).get('parameters',{}).get('ProcessingEnabled')
                if setting:
                    payload['properties']['definition']['parameters']['ProcessingEnabled']['defaultValue']=setting['defaultValue']
                (evidence/(args.flow_name+'-before.json')).write_text(json.dumps(dict(flow),indent=2))
                client.records.update('workflow',flow['workflowid'],{'statecode':0,'statuscode':1})
                client.records.update('workflow',flow['workflowid'],{'clientdata':json.dumps(payload)})
                identifier=flow['workflowid']
            else:
                identifier=client.records.create('workflow',{'category':5,'name':args.flow_name,'type':1,'primaryentity':'none',
                    'description':'Zava Medical Claims Concierge. Simulated claims only; private owner POC.',
                    'clientdata':json.dumps(payload)})
            add(identifier,29)
            print(json.dumps({'id':str(identifier),'state':'Draft','nativeDefinitionSaved':True}))


if __name__=='__main__':
    main()

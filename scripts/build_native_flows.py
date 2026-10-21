"""Build native WDL authoring inputs for the approved simulation-only POC.

Publish through Dataverse, validate in the native designer, then export the
genuine solution. These inputs alone are not an importable solution.
"""
import argparse
import copy
import json
from pathlib import Path
from bootstrap_dataverse import load, ROOT


def expr(value): return '@'+value
def quoted(value): return "'"+value.replace("'","''")+"'"
def eq(a,b): return 'equals('+a+','+b+')'
def both(*parts): return 'and('+','.join(parts)+')'
def either(*parts): return 'or('+','.join(parts)+')'
def body(name): return "body('"+name+"')"
def out(name): return "outputs('"+name+"')"
def variable(name): return "variables('"+name+"')"
def odata(field,value):
    return "concat('"+field+" eq ',decodeUriComponent('%27'),replace("+value+",decodeUriComponent('%27'),decodeUriComponent('%27%27')),decodeUriComponent('%27'))"


class Chain:
    def __init__(self): self.actions={}; self.last=None
    def add(self,name,kind,**parts):
        item={'type':kind,'runAfter':{self.last:['Succeeded']} if self.last else {},**parts}
        self.actions[name]=item; self.last=name
        return item
    def compose(self,name,value): return self.add(name,'Compose',inputs=value)
    def set(self,name,key,value): return self.add(name,'SetVariable',inputs={'name':key,'value':value})
    def append(self,name,key,value): return self.add(name,'AppendToArrayVariable',inputs={'name':key,'value':value})
    def query(self,name,source,where): return self.add(name,'Query',inputs={'from':source,'where':expr(where)})
    def condition(self,name,condition,yes,no=None):
        # Designer-compatible WDL condition object; keep the boolean formula
        # in a visible expression token instead of an opaque string condition.
        return self.add(name,'If',expression={'and':[{'equals':[expr(condition),True]}]},actions=yes.actions,**({'else':{'actions':no.actions}} if no else {}))
    def each(self,name,source,actions):
        return self.add(name,'Foreach',foreach=source,actions=actions.actions,runtimeConfiguration={'concurrency':{'repetitions':1}})
    def api(self,name,connector,operation,parameters,webhook=False):
        return self.add(name,'OpenApiConnectionWebhook' if webhook else 'OpenApiConnection',inputs={
            'host':{'apiId':'/providers/Microsoft.PowerApps/apis/'+connector,'connectionName':connector,'operationId':operation},
            'parameters':parameters,'authentication':"@parameters('$authentication')"})
    def dv(self,name,operation,parameters): return self.api(name,'shared_commondataserviceforapps',operation,parameters)


def inline_schema(item,definitions):
    if isinstance(item,list): return [inline_schema(x,definitions) for x in item]
    if not isinstance(item,dict): return item
    if '$ref' in item: return inline_schema(copy.deepcopy(definitions[item['$ref'].split('/')[-1]]),definitions)
    result={k:inline_schema(v,definitions) for k,v in item.items() if k not in {'$defs','title','pattern'}}
    if item.get('pattern')=='^[A-Z0-9-]{3,80}$': result.update(minLength=3,maxLength=80)
    if item.get('pattern')=='^[0-9]{5}$': result.update(minLength=5,maxLength=5)
    if item.get('format')=='uuid': result.update(minLength=36,maxLength=36)
    if item.get('pattern')=='^[a-f0-9]{64}$': result.update(minLength=64,maxLength=64)
    if 'const' in result: result['enum']=[result.pop('const')]
    return result


def environment_parameters(cfg):
    names={'ClaimsMode':('String','Simulated'),'ProcessingEnabled':('String','no'),
           'SearchIndex':('String',cfg['searchIndex']),'PolicyVersion':('String','1.0'),
           'MedicalDirectorObjectId':('String',cfg['medicalDirectorObjectId']),
           'MedicalDirectorUPN':('String',cfg['medicalDirectorUpn']),'ApprovalLifetimeHours':('Int',24),
           'TenantId':('String',cfg['tenantId']),'DataverseUrl':('String',cfg['environmentUrl'])}
    return {suffix:{'type':kind,'defaultValue':value,'metadata':{'schemaName':cfg['publisherPrefix']+'_'+suffix}}
            for suffix,(kind,value) in names.items()}


def enabled_configuration():
    return both(eq("parameters('ClaimsMode')","'Simulated'"),
        "contains(createArray('yes','true'),toLower(string(parameters('ProcessingEnabled'))))")


def evidence_snapshot(value,prefix):
    # Compare business fields, independent of Get/List response annotations.
    fields=['claim_evidenceid','evidence_id','claim_id','member_id','cpt_code','policy_number','policy_version',
        'source_version','verification_state','is_synthetic','facts_json','sources_json','claim_snapshot_json']
    return {key:expr(value+"?['"+prefix+key+"']") for key in fields}


def skeleton(cfg,trigger,refs):
    parameters={'$authentication':{'type':'SecureObject','defaultValue':{}},'$connections':{'type':'Object','defaultValue':{}},**environment_parameters(cfg)}
    references={connector:{'runtimeSource':'embedded','connection':{'connectionReferenceLogicalName':logical},'api':{'name':connector}}
                for connector,logical in refs.items()}
    return {'properties':{'connectionReferences':references,'definition':{
        '$schema':'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#',
        'contentVersion':'1.0.0.0','parameters':parameters,'triggers':trigger,'actions':{}}},'schemaVersion':'1.0.0.0'}


def evaluation(cfg,seed):
    prefix=cfg['publisherPrefix']+'_'
    native=json.loads(seed['clientdata'])
    trigger=native['properties']['definition']['triggers']
    # Skills responses are synchronous; request-trigger concurrency is unsupported.
    # The durable request alternate key rejects simultaneous duplicate creates.
    trigger['manual'].pop('runtimeConfiguration',None)
    result=skeleton(cfg,trigger,{'shared_commondataserviceforapps':prefix+'ClaimsDataverse','shared_azureaisearch':prefix+'ClaimsAzureAISearch'})
    top=Chain()
    defaults={'Result':('Object',{'status':'EvaluationError','reasonCodes':['MandatoryReadOrValidationFailed'],'mode':'Simulated','authorizationGranted':False}),
              'EvaluationId':('String',expr('guid()')),'Outcome':('String','InsufficientEvidence'),'Reasons':('Array',[]),
              'SourcesValid':('Boolean',True),'ReferencesValid':('Boolean',True),'Clinical':('Object',{}),
              'WeeklyCounts':('Array',[]),'MedicationCovered':('Boolean',True),'SourcesSeen':('Array',[]),
              'CompletedWeeks':('Integer',0),'CanApprove':('Boolean',False)}
    for name,(kind,value) in defaults.items():
        top.add('Initialize_'+name,'InitializeVariable',inputs={'variables':[{'name':name,'type':kind.lower(),'value':value}]})
    scope=Chain()
    schema=json.loads((ROOT/'contracts/claim-evaluation.schema.json').read_text())
    scope.add('Parse_strict_evaluation','ParseJson',inputs={'content':"@triggerBody()?['text']",'schema':inline_schema(schema,schema.get('$defs',{}))})
    req=body('Parse_strict_evaluation')
    # Native Parse JSON rejects regex patterns with connector actions. Validate
    # the same identifier constraints with character queries and exact shapes.
    scope.compose('Identifier_characters',expr("concat("+req+"?['claimId'],"+req+"?['memberId'],"+req+"?['policyNumber'])"))
    scope.query('Invalid_identifier_characters',expr('range(0,length('+out('Identifier_characters')+'))'),
        "not(contains('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-',substring("+out('Identifier_characters')+",item(),1)))")
    scope.query('Invalid_CPT_characters',expr('range(0,length('+req+"?['cptCode']))"),
        "not(contains('0123456789',substring("+req+"?['cptCode'],item(),1)))")
    scope.compose('UUID_characters',expr("toLower(replace(concat("+req+"?['correlationId'],"+req+"?['idempotencyKey']),'-',''))"))
    scope.query('Invalid_UUID_characters',expr('range(0,length('+out('UUID_characters')+'))'),
        "not(contains('0123456789abcdef',substring("+out('UUID_characters')+",item(),1)))")
    uuid_checks=[]
    for field in ['correlationId','idempotencyKey']:
        value=req+"?['"+field+"']"
        uuid_checks += [eq('substring('+value+','+str(index)+",1)","'-'") for index in [8,13,18,23]]
        uuid_checks.append(eq("length(replace("+value+",'-',''))",'32'))
    scope.add('Validate_identifier_contract','ParseJson',inputs={'content':{'valid':expr(both(
        eq('length('+body('Invalid_identifier_characters')+')','0'),eq('length('+body('Invalid_CPT_characters')+')','0'),
        eq('length('+body('Invalid_UUID_characters')+')','0'),eq(req+"?['policyVersion']","parameters('PolicyVersion')"),*uuid_checks))},
        'schema':{'type':'object','properties':{'valid':{'type':'boolean','enum':[True]}},'required':['valid'],'additionalProperties':False}})
    scope.compose('Canonical_request',expr('string('+req+')'))
    scope.dv('Find_existing_request','ListRecords',{'entityName':prefix+'claim_evaluations','$filter':expr(odata(prefix+'request_key',req+"?['idempotencyKey']")),'$top':2})
    replay=Chain(); conflict=Chain()
    replay.set('Return_stored_result','Result',expr("json(first("+body('Find_existing_request')+"?['value'])?['"+prefix+"result_json'])"))
    conflict.set('Return_request_conflict','Result',{'status':'EvaluationError','reasonCodes':['IdempotencyConflict'],'mode':'Simulated','authorizationGranted':False})
    existing=Chain()
    existing.condition('Match_existing_request',both(
        eq("first("+body('Find_existing_request')+"?['value'])?['"+prefix+"request_json']",out('Canonical_request')),
        eq("first("+body('Find_existing_request')+"?['value'])?['"+prefix+"caller_object_id']","parameters('MedicalDirectorObjectId')")),replay,conflict)
    new=Chain()
    new.dv('Read_protected_evidence','ListRecords',{'entityName':prefix+'claim_evidences',
        '$filter':expr('concat('+odata(prefix+'claim_id',req+"?['claimId']")+",' and ',"+odata(prefix+'policy_version',req+"?['policyVersion']")+')'),'$top':2})
    new.dv('Read_active_policy_rules','ListRecords',{'entityName':prefix+'medical_policy_ruleses',
        '$filter':expr('concat('+odata(prefix+'policy_number',req+"?['policyNumber']")+",' and ',"+odata(prefix+'policy_version',req+"?['policyVersion']")+",' and cr_is_active eq true')"),'$orderby':prefix+'rule_id asc','$top':10})
    new.api('Retrieve_policy_grounding','shared_azureaisearch','IntegratedVectorSearch',{
        'indexName':"@parameters('SearchIndex')",'integratedVectorSearchRequest/searchText':'AMH RAD 2026 lumbar spine MRI conservative therapy six weeks physical therapy',
        'integratedVectorSearchRequest/vectorizedSearchFields':['snippet_vector'],'integratedVectorSearchRequest/selectFields':['uid','snippet','blob_url'],
        'integratedVectorSearchRequest/nearestNeighbors':3,'integratedVectorSearchRequest/top':3})
    good=Chain()
    good.compose('Evidence',expr('first('+body('Read_protected_evidence')+"?['value'])"))
    ev=out('Evidence')
    good.compose('Facts',expr('json('+ev+"?['"+prefix+"facts_json'])"))
    facts=out('Facts')
    good.compose('Sources',expr('json('+ev+"?['"+prefix+"sources_json'])"))
    sources=out('Sources')
    good.compose('Claim',expr('json('+ev+"?['"+prefix+"claim_snapshot_json'])"))
    claim=out('Claim')
    good.query('Duration_rule',expr(body('Read_active_policy_rules')+"?['value']"),eq("item()?['"+prefix+"rule_kind']","'conservative-duration'"))
    good.query('Modalities_rule',expr(body('Read_active_policy_rules')+"?['value']"),eq("item()?['"+prefix+"rule_kind']","'conservative-modalities'"))
    good.query('Missing_evidence_rule',expr(body('Read_active_policy_rules')+"?['value']"),eq("item()?['"+prefix+"rule_kind']","'missing-evidence-review'"))
    good.query('Invalid_policy_rows',expr(body('Read_active_policy_rules')+"?['value']"),either(
        "not(contains(createArray('AMH-RAD-2026-R01','AMH-RAD-2026-R02','AMH-RAD-2026-R03'),item()?['"+prefix+"rule_id']))",
        'not('+eq("item()?['"+prefix+"cpt_code']",req+"?['cptCode']")+')',
        'greater(ticks('+"item()?['"+prefix+"effective_from']),ticks("+claim+"?['serviceDate']))",
        'lessOrEquals(ticks(coalesce('+"item()?['"+prefix+"effective_to'],'9999-12-31T00:00:00Z')),ticks("+claim+"?['serviceDate']))"))
    valid=Chain()
    source_loop=Chain(); source="items('Validate_protected_sources')"
    source_loop.append('Remember_document_id','SourcesSeen',expr(source+"?['documentId']"))
    invalid_source=Chain(); invalid_source.set('Reject_source_binding','SourcesValid',False)
    # Sources are attached to the protected evidence row, whose claim/member/
    # CPT binding is already checked. The source envelope contains path/hash/
    # pages/body, not duplicate claim fields. Verify its fixture path and the
    # decoded clinical record instead of testing nonexistent envelope fields.
    expected_file="if(equals("+source+"?['documentId'],'pt-log'),'pt-log.csv',if(equals("+source+"?['documentId'],'clinical-note'),'clinical-note.json','medication-log.json'))"
    source_loop.condition('Check_source_binding',both(eq(ev+"?['"+prefix+"is_synthetic']",'true'),eq(facts+"?['synthetic']",'true'),
        "contains(createArray('clinical-note','pt-log','medication-log'),"+source+"?['documentId'])",
        eq(source+"?['path']","concat('sources/',"+facts+"?['fixtureName'],'/',"+expected_file+")"),
        'greaterOrEquals(int('+source+"?['pages']),1)",
        eq('length('+source+"?['sha256'])",'64')),Chain(),invalid_source)
    clinical=Chain()
    clinical.compose('Parse_clinical_source',expr('json(base64ToString('+source+"?['bodyBase64']))"))
    note=out('Parse_clinical_source')
    clinical.set('Use_clinical_source','Clinical',expr(note))
    invalid_clinical=Chain(); invalid_clinical.set('Reject_clinical_mismatch','SourcesValid',False)
    clinical.condition('Compare_clinical_source',both(*[eq('string('+note+"?['"+key+"'])",'string('+facts+"?['"+key+"'])")
        for key in ['claimId','memberId','cptCode','therapyStart','therapyEndExclusive','indication','treatmentFailedOrWorsened','redFlagsVerified','contradictions']]),Chain(),invalid_clinical)
    source_loop.condition('Clinical_note_source',eq(source+"?['documentId']","'clinical-note'"),clinical)
    pt=Chain()
    pt.compose('PT_source_text',expr("replace(base64ToString("+source+"?['bodyBase64']),decodeUriComponent('%0D'),'')"))
    pt.query('PT_source_rows',expr("skip(split("+out('PT_source_text')+",decodeUriComponent('%0A')),1)"),'not(empty(item()))')
    pt.add('Parse_PT_source','Select',inputs={'from':expr(body('PT_source_rows')),'select':{
        'date':"@first(split(item(),','))",'attended':"@equals(last(split(item(),',')),'true')"}})
    pt.query('Invalid_PT_tokens',expr(body('PT_source_rows')),"or(not(equals(length(split(item(),',')),2)),not(contains(createArray('true','false'),last(split(item(),',')))))")
    invalid_pt=Chain(); invalid_pt.set('Reject_PT_source_mismatch','SourcesValid',False)
    pt.condition('Compare_PT_source',both(eq("first(split("+out('PT_source_text')+",decodeUriComponent('%0A')))","'date,attended'"),
        eq('length('+body('Invalid_PT_tokens')+')','0'),eq('string('+body('Parse_PT_source')+')','string('+facts+"?['sessions'])")),Chain(),invalid_pt)
    source_loop.condition('PT_log_source',eq(source+"?['documentId']","'pt-log'"),pt)
    meds=Chain(); meds.compose('Parse_medication_source',expr('json(base64ToString('+source+"?['bodyBase64']))"))
    invalid_meds=Chain(); invalid_meds.set('Reject_medication_source_mismatch','SourcesValid',False)
    meds.condition('Compare_medication_source',eq('string('+out('Parse_medication_source')+')','string('+facts+"?['medications'])"),Chain(),invalid_meds)
    source_loop.condition('Medication_log_source',eq(source+"?['documentId']","'medication-log'"),meds)
    valid.each('Validate_protected_sources',expr(sources),source_loop)
    references=Chain(); ref="items('Validate_agent_references')"
    references.query('Match_reference',expr(sources),both(eq("item()?['documentId']",ref+"?['documentId']"),
        eq("item()?['sha256']",ref+"?['sha256']"),'greaterOrEquals(int('+"item()?['pages']),int("+ref+"?['page']))"))
    bad_ref=Chain(); bad_ref.set('Reject_reference','ReferencesValid',False)
    references.condition('Reference_exists_exactly_once',eq('length('+body('Match_reference')+')','1'),Chain(),bad_ref)
    valid.each('Validate_agent_references',expr(req+"?['evidenceReferences']"),references)
    valid.add('Reference_document_ids','Select',inputs={'from':expr(req+"?['evidenceReferences']"),'select':"@item()?['documentId']"})
    valid.compose('Required_source_ids',expr("if(equals("+facts+"?['redFlagsVerified'],true),createArray('clinical-note'),createArray('clinical-note','pt-log','medication-log'))"))
    verified=Chain()
    contradiction=Chain(); contradiction.set('Contradictions_need_MD','Outcome','MedicalDirectorReviewRequired'); contradiction.append('Contradiction_reason','Reasons','ContradictoryEvidence')
    not_contradictory=Chain()
    red=Chain(); red.set('Red_flags_need_MD','Outcome','MedicalDirectorReviewRequired'); red.set('Red_flag_path_verified','CanApprove',True); red.append('Red_flag_reason','Reasons','VerifiedRedFlagClinicalPath')
    conservative=Chain()
    conservative.compose('Therapy_days',expr("div(sub(ticks("+facts+"?['therapyEndExclusive']),ticks("+facts+"?['therapyStart'])),864000000000)"))
    conservative.set('Count_complete_weeks','CompletedWeeks',expr('div('+out('Therapy_days')+',7)'))
    conservative.query('Attended_PT',expr(facts+"?['sessions']"),eq("item()?['attended']",'true'))
    conservative.add('Attended_dates','Select',inputs={'from':expr(body('Attended_PT')),'select':"@item()?['date']"})
    conservative.query('Out_of_range_PT',expr(body('Attended_PT')),either('less(ticks(item()?[\'date\']),ticks('+facts+"?['therapyStart']))",
        'greaterOrEquals(ticks(item()?[\'date\']),ticks('+facts+"?['therapyEndExclusive']))"))
    calculate=Chain()
    weeks=Chain(); week="items('Check_each_complete_week')"
    weeks.query('Sessions_in_week',expr(body('Attended_PT')),both(
        'greaterOrEquals(ticks(item()?[\'date\']),ticks(addDays('+facts+"?['therapyStart'],mul("+week+',7))))',
        'less(ticks(item()?[\'date\']),ticks(addDays('+facts+"?['therapyStart'],mul(add("+week+',1),7))))'))
    weeks.append('Record_week_count','WeeklyCounts',expr('length('+body('Sessions_in_week')+')'))
    calculate.each('Check_each_complete_week',expr('range(0,'+variable('CompletedWeeks')+')'),weeks)
    calculate.query('Weeks_below_minimum',expr(variable('WeeklyCounts')),'less(item(),int(first('+body('Modalities_rule')+")?['"+prefix+"min_pt_sessions_week']))")
    days=Chain(); day="addDays("+facts+"?['therapyStart'],items('Check_medication_every_day'))"
    days.query('Medication_covering_day',expr(facts+"?['medications']"),both(eq("item()?['verified']",'true'),
        "contains(createArray('NSAID','MuscleRelaxant','NeuropathicPainAgent'),item()?['category'])",
        'lessOrEquals(ticks(item()?[\'start\']),ticks('+day+'))','greater(ticks(item()?[\'endExclusive\']),ticks('+day+'))'))
    uncovered=Chain(); uncovered.set('Medication_day_missing','MedicationCovered',False)
    days.condition('Medication_day_covered','greater(length('+body('Medication_covering_day')+'),0)',Chain(),uncovered)
    calculate.each('Check_medication_every_day',expr('range(0,'+out('Therapy_days')+')'),days)
    for name,condition,reason in [
        ('Duration_meets_policy','less('+variable('CompletedWeeks')+',int(first('+body('Duration_rule')+")?['"+prefix+"min_conservative_weeks']))",'InsufficientConservativeDuration'),
        ('Every_week_meets_policy','or(equals('+variable('CompletedWeeks')+',0),greater(length('+body('Weeks_below_minimum')+'),0))','PtFrequencyBelowMinimum'),
        ('Medication_meets_policy','not('+variable('MedicationCovered')+')','PharmacologyNotDocumentedForRegimen'),
        ('Treatment_failed_or_worsened','not(equals('+facts+"?['treatmentFailedOrWorsened'],true))",'FailedTreatmentNotEstablished')]:
        fail=Chain(); fail.append(name+'_reason','Reasons',reason); calculate.condition(name,condition,fail)
    eligible=Chain(); eligible.set('Conservative_eligible','Outcome','EligibleForHumanReview'); eligible.set('Conservative_path_verified','CanApprove',True); eligible.append('Conservative_reason','Reasons','ConservativeCriteriaVerified')
    unmet=Chain(); unmet.set('Conservative_unmet','Outcome','PolicyCriteriaNotMet')
    calculate.condition('All_conservative_checks_pass',eq('length('+variable('Reasons')+')','0'),eligible,unmet)
    invalid_treatment=Chain(); invalid_treatment.append('Treatment_invalid_reason','Reasons','InvalidOrUnknownTreatmentLog')
    conservative.condition('Treatment_log_valid',both('greater('+out('Therapy_days')+',0)','lessOrEquals('+out('Therapy_days')+',728)',
        eq('length('+body('Out_of_range_PT')+')','0'),eq('length('+body('Attended_dates')+')','length(union('+body('Attended_dates')+','+body('Attended_dates')+'))'),
        "contains(createArray('RadicularPain','SpinalStenosis','PersistentLowBackPain'),"+facts+"?['indication'])",
        'lessOrEquals(ticks('+facts+"?['therapyEndExclusive']),ticks("+claim+"?['serviceDate']))",
        either(eq(facts+"?['treatmentFailedOrWorsened']",'true'),eq(facts+"?['treatmentFailedOrWorsened']",'false'))),calculate,invalid_treatment)
    verified.condition('Check_contradictions','greater(length('+facts+"?['contradictions']),0)",contradiction)
    verified.condition('Verified_red_flag_path',both(eq('length('+facts+"?['contradictions'])",'0'),eq(facts+"?['redFlagsVerified']",'true')),red)
    verified.condition('Conservative_clinical_path',both(eq('length('+facts+"?['contradictions'])",'0'),eq(facts+"?['redFlagsVerified']",'false')),conservative)
    invalid_sources=Chain(); invalid_sources.append('Missing_or_invalid_source_reason','Reasons','RequiredClinicalRecordsMissingOrMismatched')
    valid.condition('Source_and_reference_checks_pass',both(variable('SourcesValid'),variable('ReferencesValid'),
        eq('length('+variable('SourcesSeen')+')','length(union('+variable('SourcesSeen')+','+variable('SourcesSeen')+'))'),
        eq('length('+body('Reference_document_ids')+')','length(union('+body('Reference_document_ids')+','+body('Reference_document_ids')+'))'),
        eq('length(intersection('+out('Required_source_ids')+','+variable('SourcesSeen')+'))','length('+out('Required_source_ids')+')'),
        eq('length(intersection('+out('Required_source_ids')+','+body('Reference_document_ids')+'))','length('+out('Required_source_ids')+')'),
        'not(equals('+facts+"?['redFlagsVerified'],null))"),verified,invalid_sources)
    valid.compose('Evaluation_result',{'evaluationId':expr(variable('EvaluationId')),'correlationId':expr(req+"?['correlationId']"),
        'status':expr(variable('Outcome')),'reasonCodes':expr(variable('Reasons')),'mode':'Simulated','authorizationGranted':False,
        'eligibleForHumanApproval':expr(variable('CanApprove')),'completedWeeks':expr(variable('CompletedWeeks')),
        'weeklyPtCounts':expr(variable('WeeklyCounts')),'pharmacologyVerified':expr(variable('MedicationCovered')),
        'claimWriteCount':0,'expiresAt':"@addHours(utcNow(),parameters('ApprovalLifetimeHours'))"})
    fields={'evaluation_id':expr(variable('EvaluationId')),'request_key':expr(req+"?['idempotencyKey']"),'claim_id':expr(req+"?['claimId']"),
        'member_id':expr(req+"?['memberId']"),'correlation_id':expr(req+"?['correlationId']"),'caller_object_id':"@parameters('MedicalDirectorObjectId')",
        'policy_number':expr(req+"?['policyNumber']"),'policy_version':expr(req+"?['policyVersion']"),'claim_version':expr(req+"?['claimVersion']"),
        'evaluation_version':1,'state':'PendingReview','outcome':expr(variable('Outcome')),'assigned_reviewer_id':"@parameters('MedicalDirectorObjectId')",
        'expires_at':"@addHours(utcNow(),parameters('ApprovalLifetimeHours'))",'mode':'Simulated','request_json':expr(out('Canonical_request')),
        'result_json':expr('string('+out('Evaluation_result')+')'),'policy_snapshot_json':expr('string('+body('Read_active_policy_rules')+"?['value'])"),
        'evidence_snapshot_json':expr('string('+out('Stable_evidence_snapshot')+')'),
        'review_summary':"@concat('SYNTHETIC POC / Simulated. Claim ',body('Parse_strict_evaluation')?['claimId'],'. Outcome: ',variables('Outcome'),'. Reasons: ',join(variables('Reasons'),', '),'. No real claim has been changed.',decodeUriComponent('%0A%0A'),outputs('Evidence')?['cr_review_summary'])"}
    valid.compose('Stable_evidence_snapshot',evidence_snapshot(ev,prefix))
    valid.dv('Create_durable_evaluation','CreateRecord',{'entityName':prefix+'claim_evaluations',**{'item/'+prefix+k:v for k,v in fields.items()}})
    valid.set('Return_durable_result','Result',expr(out('Evaluation_result')))
    bad_binding=Chain(); bad_binding.set('Return_binding_or_policy_error','Result',{'status':'EvaluationError','reasonCodes':['ClaimBindingOrPolicyCoverageInvalid'],'mode':'Simulated','authorizationGranted':False})
    threshold=both(eq('length('+body('Duration_rule')+')','1'),eq('length('+body('Modalities_rule')+')','1'),eq('length('+body('Missing_evidence_rule')+')','1'),
        eq('length('+body('Invalid_policy_rows')+')','0'),
        eq("first("+body('Duration_rule')+")?['"+prefix+"enforcement_level']",'100000000'),
        eq("first("+body('Modalities_rule')+")?['"+prefix+"enforcement_level']",'100000000'),
        eq("first("+body('Missing_evidence_rule')+")?['"+prefix+"enforcement_level']",'100000001'),
        'greaterOrEquals(int(first('+body('Duration_rule')+")?['"+prefix+"min_conservative_weeks']),6)",
        'greaterOrEquals(int(first('+body('Modalities_rule')+")?['"+prefix+"min_pt_sessions_week']),2)",
        eq("first("+body('Modalities_rule')+")?['"+prefix+"requires_pt']",'true'),eq("first("+body('Modalities_rule')+")?['"+prefix+"requires_pharmacology']",'true'),
        eq("first("+body('Duration_rule')+")?['"+prefix+"requires_failed_treatment']",'true'),
        eq("first("+body('Missing_evidence_rule')+")?['"+prefix+"min_conservative_weeks']",'null'),eq("first("+body('Missing_evidence_rule')+")?['"+prefix+"min_pt_sessions_week']",'null'),
        *['not(equals(first('+body('Missing_evidence_rule')+")?['"+prefix+field+"'],true))" for field in ['requires_pt','requires_pharmacology','requires_failed_treatment']])
    good.condition('Enforce_claim_and_policy_contract',both(threshold,
        eq('length('+body('Read_protected_evidence')+"?['value'])",'1'),eq('length('+body('Read_active_policy_rules')+"?['value'])",'3'),
        'not(empty('+body('Retrieve_policy_grounding')+'))',eq(ev+"?['"+prefix+"is_synthetic']",'true'),
        eq(ev+"?['"+prefix+"verification_state']",'100000001'),eq(claim+"?['synthetic']",'true'),
        *[eq(facts+"?['"+k+"']",req+"?['"+k+"']") for k in ['claimId','memberId','cptCode','policyNumber','policyVersion']],
        *[eq(claim+"?['"+k+"']",req+"?['"+k+"']") for k in ['claimId','memberId','cptCode']],
        eq(claim+"?['version']",req+"?['claimVersion']")),valid,bad_binding)
    bad_reads=Chain(); bad_reads.set('Return_missing_or_ambiguous_data','Result',{'status':'EvaluationError','reasonCodes':['MandatoryPolicyEvidenceOrGroundingMissing'],'mode':'Simulated','authorizationGranted':False})
    first_good=next(iter(good.actions.values()))
    first_good['runAfter']={new.last:['Succeeded']}
    new.actions.update(good.actions); new.last=good.last
    scope.condition('Idempotency_key_already_used','greater(length('+body('Find_existing_request')+"?['value']),0)",existing,new)
    enabled=scope
    disabled=Chain(); disabled.set('Processing_is_disabled','Result',{'status':'ProcessingDisabled','mode':'Simulated','authorizationGranted':False})
    top.condition('Require_simulated_enabled_configuration',enabled_configuration(),enabled,disabled)
    response=copy.deepcopy(native['properties']['definition']['actions']['Respond_to_Copilot'])
    response['runAfter']={top.last:['Succeeded','Failed','TimedOut','Skipped']}
    response['inputs']['body']={'resultjson':expr('string('+variable('Result')+')')}
    top.actions['Respond_to_Copilot']=response
    result['properties']['definition']['actions']=top.actions
    return result


def review(cfg,seed):
    prefix=cfg['publisherPrefix']+'_'
    native=json.loads(seed['clientdata'])
    triggers=copy.deepcopy(native['properties']['definition']['triggers'])
    trigger=next(iter(triggers.values()))
    trigger['inputs']['parameters']['subscriptionRequest/filterexpression']="cr_state eq 'PendingReview' and cr_mode eq 'Simulated'"
    trigger['runtimeConfiguration']={'concurrency':{'runs':1}}
    refs={connector:entry['connection']['connectionReferenceLogicalName'] for connector,entry in native['properties']['connectionReferences'].items()}
    result=skeleton(cfg,triggers,refs)
    rowid="triggerBody()?['"+prefix+"claim_evaluationid']"
    top=Chain()
    top.add('Initialize_completion_status','InitializeVariable',inputs={'variables':[{'name':'CompletionStatus','type':'string','value':'MutationUncertain'}]})
    enabled=Chain()
    enabled.dv('Read_pending_evaluation','GetItem',{'entityName':prefix+'claim_evaluations','recordId':expr(rowid)})
    pending=body('Read_pending_evaluation')
    def update(chain,name,read,fields):
        terminal=fields.get('state')
        if terminal in {'BlockedIneligibleApproval','StaleEvaluation','RejectedApprovalResponse','ApprovalExpired'}:
            fields={**fields,'result_json':expr("string(setProperty(setProperty(json("+read+"?['"+prefix+"result_json']),'status','"+terminal+"'),'authorizationGranted',false))"),
                'review_summary':expr("concat('SYNTHETIC POC / Simulated. Current state: "+terminal+". No real claim has been changed.',decodeUriComponent('%0A%0A'),"+read+"?['"+prefix+"review_summary'])")}
        action=chain.dv(name,'UpdateOnlyRecord',{'entityName':prefix+'claim_evaluations','recordId':expr(rowid),
            'If-Match':expr(read+"?['@odata.etag']"),**{'item/'+prefix+k:v for k,v in fields.items()}})
        action['inputs']['retryPolicy']={'type':'none'}
        return action
    dispatch=Chain()
    update(dispatch,'Reserve_approval_dispatch',pending,{'state':'ApprovalCreating','evaluation_version':2})
    dispatch.compose('Protected_review_link',expr("concat('https://',uriHost(parameters('DataverseUrl')),'/main.aspx?appid=34e1f7d9-1ccd-f111-a05c-000d3a3122f1&pagetype=entityrecord&etn="+prefix+"claim_evaluation&id=',"+rowid+")"))
    create=copy.deepcopy(native['properties']['definition']['actions']['Create_an_approval'])
    create['runAfter']={dispatch.last:['Succeeded']}
    create['inputs']['retryPolicy']={'type':'none'}
    create['inputs']['parameters'].update({
        'ApprovalCreationInput/title':expr("concat('SYNTHETIC POC / Simulated — ',"+pending+"?['"+prefix+"claim_id'])"),
        'ApprovalCreationInput/assignedTo':"@parameters('MedicalDirectorUPN')",
        'ApprovalCreationInput/details':'Review the protected evaluation and evidence in Claims Review. All claims and decisions are synthetic POC records. No real claim will be changed. Missing documentation supports RequestAdditionalInformation, not automatic denial.',
        'ApprovalCreationInput/itemLink':expr(out('Protected_review_link')),
        'ApprovalCreationInput/itemLinkDescription':'Open protected Claims Review',
        'ApprovalCreationInput/enableNotifications':True,'ApprovalCreationInput/enableReassignment':False})
    dispatch.actions['Create_native_approval']=create; dispatch.last='Create_native_approval'
    dispatch.dv('Read_dispatch_reservation','GetItem',{'entityName':prefix+'claim_evaluations','recordId':expr(rowid)})
    update(dispatch,'Persist_platform_approval_id',body('Read_dispatch_reservation'),{'state':'AwaitingMedicalDirector',
        'approval_id':expr(body('Create_native_approval')+"?['name']"),'evaluation_version':3})
    wait=dispatch.api('Wait_for_Medical_Director','shared_approvals','WaitForAnApproval',{
        'approvalName':expr(body('Create_native_approval')+"?['name']")},webhook=True)
    wait['limit']={'timeout':'PT24H'}
    responded=Chain()
    responded.dv('Read_current_evaluation','GetItem',{'entityName':prefix+'claim_evaluations','recordId':expr(rowid)})
    current=body('Read_current_evaluation')
    responded.compose('Authenticated_response',expr("first("+body('Wait_for_Medical_Director')+"?['responses'])"))
    response=out('Authenticated_response')
    responded.compose('Decision',expr(response+"?['approverResponse']"))
    decision=out('Decision')
    authorized=Chain()
    authorized.dv('Read_current_evidence','ListRecords',{'entityName':prefix+'claim_evidences',
        '$filter':expr('concat('+odata(prefix+'claim_id',current+"?['"+prefix+"claim_id']")+",' and ',"+odata(prefix+'policy_version',current+"?['"+prefix+"policy_version']")+')'),'$top':2})
    authorized.dv('Read_current_policy','ListRecords',{'entityName':prefix+'medical_policy_ruleses',
        '$filter':expr('concat('+odata(prefix+'policy_number',current+"?['"+prefix+"policy_number']")+",' and ',"+odata(prefix+'policy_version',current+"?['"+prefix+"policy_version']")+",' and cr_is_active eq true')"),'$orderby':prefix+'rule_id asc','$top':10})
    ev="first("+body('Read_current_evidence')+"?['value'])"
    authorized.compose('Current_stable_evidence',evidence_snapshot(ev,prefix))
    authorized.compose('Authoritative_simulated_claim',expr('json('+ev+"?['"+prefix+"claim_snapshot_json'])"))
    claim=out('Authoritative_simulated_claim')
    verified=Chain()
    verified.compose('Auditable_human_decision',{'approvalId':expr(current+"?['"+prefix+"approval_id']"),
        'reviewerObjectId':expr(response+"?['responder']?['id']"),'reviewerTenantId':expr(response+"?['responder']?['tenantId']"),
        'decision':expr(decision),'comments':expr(response+"?['comments']"),'respondedAt':expr(response+"?['responseDate']"),'mode':'Simulated'})
    write=Chain()
    # Reserve the decision once, then use evidence ETag to atomically reject
    # concurrent claim/evidence edits. No automated retry can repeat a mutation.
    update(write,'Reserve_decision_once',current,{'state':'Processing','evaluation_version':4,
        'reviewer_object_id':expr(response+"?['responder']?['id']"),'decision_json':expr('string('+out('Auditable_human_decision')+')')})
    write.compose('Expected_simulated_claim',expr("setProperty(setProperty(setProperty("+claim+",'status',if(equals("+decision+",'ApproveAuthorization'),'Authorized','Denied')),'version',add(int("+claim+"?['version']),1)),'operationId',"+current+"?['"+prefix+"evaluation_id'])"))
    mutation=write.dv('Commit_simulated_claim_with_ETag','UpdateOnlyRecord',{'entityName':prefix+'claim_evidences',
        'recordId':expr(ev+"?['"+prefix+"claim_evidenceid']"),'If-Match':expr(ev+"?['@odata.etag']"),
        'item/'+prefix+'claim_snapshot_json':expr('string('+out('Expected_simulated_claim')+')')})
    mutation['inputs']['retryPolicy']={'type':'none'}
    write.dv('Read_back_simulated_claim','GetItem',{'entityName':prefix+'claim_evidences','recordId':expr(ev+"?['"+prefix+"claim_evidenceid']")})
    write.actions[write.last]['runAfter']={'Commit_simulated_claim_with_ETag':['Succeeded','Failed','TimedOut']}
    write.compose('Committed_claim',expr('json('+body('Read_back_simulated_claim')+"?['"+prefix+"claim_snapshot_json'])"))
    receipt=Chain(); receipt.set('Mark_confirmed_simulation','CompletionStatus','SimulatedConfirmed')
    write.condition('Verify_persisted_simulated_receipt',both(eq(out('Committed_claim'),out('Expected_simulated_claim')),
        eq(out('Committed_claim')+"?['synthetic']",'true'),eq(out('Committed_claim')+"?['operationId']",current+"?['"+prefix+"evaluation_id']")),receipt)
    write.compose('Durable_mutation_receipt',{'status':expr(variable('CompletionStatus')),'mode':'Simulated','authorizationGranted':False,
        'operationId':expr(current+"?['"+prefix+"evaluation_id']"),'claimId':expr(current+"?['"+prefix+"claim_id']"),
        'expectedVersion':expr(current+"?['"+prefix+"claim_version']"),'persistedClaim':expr(out('Committed_claim')),
        'reviewerObjectId':expr(response+"?['responder']?['id']"),'approvalId':expr(current+"?['"+prefix+"approval_id']"),
        'realClaimWriteCount':0,'simulatedClaimWriteCount':expr("if(equals(variables('CompletionStatus'),'SimulatedConfirmed'),1,0)")})
    write.dv('Read_completion_reservation','GetItem',{'entityName':prefix+'claim_evaluations','recordId':expr(rowid)})
    update(write,'Record_verified_completion',body('Read_completion_reservation'),{'state':expr(variable('CompletionStatus')),
        'receipt_json':expr('string('+out('Durable_mutation_receipt')+')'),
        'result_json':expr('string('+out('Durable_mutation_receipt')+')'),'evaluation_version':5,
        'review_summary':expr("concat('SYNTHETIC POC / Simulated. Human decision: ',"+decision+" ,'. Completion: ',variables('CompletionStatus'),'. Real claim writes: 0.')")})
    no_write=Chain()
    no_write.compose('Non_mutating_result',{'status':expr("if(equals("+decision+",'RequestAdditionalInformation'),'AdditionalInformationRequested','Escalated')"),
        'evaluationId':expr(current+"?['"+prefix+"evaluation_id']"),'mode':'Simulated','authorizationGranted':False,'realClaimWriteCount':0,'simulatedClaimWriteCount':0})
    update(no_write,'Record_non_mutating_human_decision',current,{'state':expr(out('Non_mutating_result')+"?['status']"),
        'decision_json':expr('string('+out('Auditable_human_decision')+')'),'reviewer_object_id':expr(response+"?['responder']?['id']"),
        'result_json':expr('string('+out('Non_mutating_result')+')'),'evaluation_version':4})
    blocked=Chain(); update(blocked,'Record_ineligible_approval',current,{'state':'BlockedIneligibleApproval',
        'decision_json':expr('string('+out('Auditable_human_decision')+')'),'reviewer_object_id':expr(response+"?['responder']?['id']"),'evaluation_version':4})
    mutation_choice=Chain()
    mutation_choice.condition('Human_approval_requires_verified_eligibility',either(eq(decision,"'DenyClaim'"),
        both(eq(decision,"'ApproveAuthorization'"),eq("json("+current+"?['"+prefix+"result_json'])?['eligibleForHumanApproval']",'true'))),write,blocked)
    verified.condition('Human_decision_requests_claim_change',"contains(createArray('ApproveAuthorization','DenyClaim'),"+decision+')',mutation_choice,no_write)
    stale=Chain(); update(stale,'Reject_stale_evaluation',current,{'state':'StaleEvaluation','evaluation_version':4})
    authorized.condition('Evidence_policy_and_claim_still_current',both(eq('length('+body('Read_current_evidence')+"?['value'])",'1'),
        eq('length('+body('Read_current_policy')+"?['value'])",'3'),
        eq(out('Current_stable_evidence'),'json('+current+"?['"+prefix+"evidence_snapshot_json'])"),
        eq(body('Read_current_policy')+"?['value']",'json('+current+"?['"+prefix+"policy_snapshot_json'])"),
        eq(claim+"?['synthetic']",'true'),eq(claim+"?['version']",current+"?['"+prefix+"claim_version']")),verified,stale)
    reject=Chain(); update(reject,'Reject_unbound_unauthorized_or_expired_response',current,{'state':'RejectedApprovalResponse','evaluation_version':4})
    responded.condition('Require_authenticated_assigned_reviewer_and_current_approval',both(enabled_configuration(),
        eq('length('+body('Wait_for_Medical_Director')+"?['responses'])",'1'),
        eq('toLower('+response+"?['responder']?['id'])","toLower(parameters('MedicalDirectorObjectId'))"),
        eq('toLower('+response+"?['responder']?['tenantId'])","toLower(parameters('TenantId'))"),
        eq(current+"?['"+prefix+"assigned_reviewer_id']","parameters('MedicalDirectorObjectId')"),
        eq(current+"?['"+prefix+"approval_id']",body('Create_native_approval')+"?['name']"),
        eq(current+"?['"+prefix+"state']","'AwaitingMedicalDirector'"),eq(current+"?['"+prefix+"mode']","'Simulated'"),
        eq(current+"?['"+prefix+"evaluation_version']",'3'),
        'greater(ticks('+current+"?['"+prefix+"expires_at']),ticks(utcNow()))",
        "contains(createArray('ApproveAuthorization','DenyClaim','RequestAdditionalInformation','Escalate'),"+decision+')'),authorized,reject)
    responded.actions[next(iter(responded.actions))]['runAfter']={'Wait_for_Medical_Director':['Succeeded']}
    dispatch.actions.update(responded.actions)
    timeout=Chain(); timeout.dv('Read_timed_out_evaluation','GetItem',{'entityName':prefix+'claim_evaluations','recordId':expr(rowid)})
    update(timeout,'Record_expired_approval',body('Read_timed_out_evaluation'),{'state':'ApprovalExpired','evaluation_version':4})
    timeout.actions[next(iter(timeout.actions))]['runAfter']={'Wait_for_Medical_Director':['TimedOut','Failed']}
    dispatch.actions.update(timeout.actions)
    enabled.condition('Require_pending_unexpired_unassigned_evaluation',both(eq(pending+"?['"+prefix+"state']","'PendingReview'"),
        eq(pending+"?['"+prefix+"mode']","'Simulated'"),eq(pending+"?['"+prefix+"assigned_reviewer_id']","parameters('MedicalDirectorObjectId')"),
        'empty('+pending+"?['"+prefix+"approval_id'])",'greater(ticks('+pending+"?['"+prefix+"expires_at']),ticks(utcNow()))"),dispatch)
    top.condition('Require_simulated_enabled_configuration',enabled_configuration(),enabled)
    result['properties']['definition']['actions']=top.actions
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True); parser.add_argument('--seed-flow',required=True); parser.add_argument('--output',required=True)
    parser.add_argument('--kind',choices=['evaluation','review'],default='evaluation')
    args=parser.parse_args(); cfg=load(args.config)
    result=(evaluation if args.kind=='evaluation' else review)(cfg,json.loads(Path(args.seed_flow).read_text()))
    Path(args.output).write_text(json.dumps(result,indent=2))
    print('Built native evaluation flow input; platform validation and native export remain required.')


if __name__=='__main__': main()

"""Apply target values to imported flows while keeping processing disabled."""

def environment_parameters(cfg):
    names={'ClaimsMode':('String','Simulated'),'ProcessingEnabled':('String','no'),
           'SearchIndex':('String',cfg['searchIndex']),'PolicyVersion':('String','1.0'),
           'MedicalDirectorObjectId':('String',cfg['medicalDirectorObjectId']),
           'MedicalDirectorUPN':('String',cfg['medicalDirectorUpn']),'ApprovalLifetimeHours':('Int',24),
           'TenantId':('String',cfg['tenantId']),'DataverseUrl':('String',cfg['environmentUrl'])}
    return {suffix:{'type':kind,'defaultValue':value,'metadata':{'schemaName':cfg['publisherPrefix']+'_'+suffix}}
            for suffix,(kind,value) in names.items()}

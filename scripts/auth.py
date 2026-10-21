"""Portable subset of the existing Dataverse skill's Azure CLI credential path.

Uses official Azure Identity and SDK authentication; no tokens are persisted or
printed, and no custom MSAL flow or raw cache access is implemented.
"""
def get_client(configuration, skill):
    if skill not in {"dv-solution", "dv-metadata", "dv-data", "dv-query"}:
        raise ValueError("Unsupported Dataverse skill attribution")
    from azure.identity import AzureCliCredential
    from PowerPlatform.Dataverse.client import DataverseClient
    from PowerPlatform.Dataverse.core.config import OperationContext
    credential = AzureCliCredential(tenant_id=configuration["tenantId"])
    context_string = f"app=dataverse-skills/1.16.0;skill={skill};agent=codex"
    client = DataverseClient(base_url=configuration["environmentUrl"], credential=credential,
                             context=OperationContext(user_agent_context=context_string))
    return client, credential, context_string

# Deploy the claims concierge

Use an authorized **Development** environment. This package supports simulated claims only. The receiving tenant's administrator must authorize deployment, create the runtime connections and supply the target settings.

## 1 Prepare the environment

You need Dataverse, Copilot Studio, Power Automate and the required connector permissions and licensing. The target must include the standard AppModule Web Resources and PowerAppsAppFramework dependencies declared in `solution/src/Other/Solution.xml`.

Create and authorize these connections in the target:

| Connection | Used by |
|---|---|
| Microsoft Dataverse | Agent read tools and both flows |
| Azure AI Search | Agent knowledge and policy grounding |
| Approvals | Assigned review and Teams notifications |

The package contains five connection references because the agent and flows use separate references to these connectors. Setup maps each to the supplied authorized connection. A connection ID does not transfer credentials or grant access.

Use an existing Search index with `uid`, `snippet`, `blob_url`, `snippet_parent_id`, `image_snippet_parent_id` and `snippet_vector`, integrated vectorization, and a semantic configuration. A different index schema requires a reviewed mapping change. Setup does not create Azure resources or indexes. The querying identity needs the intended Search service's data-read access, such as Search Index Data Reader.

## 2 Create target settings

Clone your copy of the repository. For local setup, install PowerShell 7, Python 3.11 or later, Azure CLI and Microsoft's Power Platform CLI (`pac`). Sign in to the intended tenant with Azure CLI and PAC, then run:

```powershell
python -m pip install -r scripts/requirements-deployment.txt
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Configure
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Plan -ConfigPath .local/target.json
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Validate -Online -ConfigPath .local/target.json
```

`Configure` lists environments and writes `.local/target.json` from [the template](../config/target.example.json). Supply:

| Settings | What to enter |
|---|---|
| Environment | Display name, environment ID, organization ID, HTTPS Dataverse URL and tenant ID |
| Reviewer | Medical Director UPN and Entra object ID |
| Access check | A different account's object ID for unauthorized-access acceptance; setup does not grant it access |
| Search | Service endpoint, index name and semantic configuration |
| Connections | Authorized Dataverse, Azure AI Search and Approvals connection IDs |

Keep `mode` as `Simulated`, `processingEnabled` as `false`, and `allowLiveClaimsWrites` as `false`. Leave the reserved `claimsApiBaseUrl` blank. Preserve the package's `cr` publisher prefix and `ZavaMedicalClaimsConcierge` solution name. Changing native identities is a separate source migration.

`Plan` makes no changes. Online validation checks that the signed-in tenant and environment match the settings. Keep the completed file out of Git and shared logs.

## 3 Build and deploy with GitHub Actions

In your repository, create a GitHub environment named `claims-dev`. Protect it with authorized reviewers and permitted deployment branches. The receiving administrator must configure an Entra deployment application, its Dataverse application user and access, and a federated credential for this exact GitHub repository and environment.

Set these values on `claims-dev`:

| Name | GitHub setting |
|---|---|
| `AZURE_CLIENT_ID` | Environment variable for the deployment application |
| `AZURE_TENANT_ID` | Environment variable for the receiving tenant |
| `PP_TARGET_JSON` | Environment secret containing the completed target JSON |

In **Actions**, select **Build native solution**. Use a successful run for the exact commit you intend to deploy. The build packs reviewed native source and produces `checked-native-solution`, containing the ZIP, checksum and build record. It requires no tenant access.

Next, run **Deploy checked artifact to approved Dev** from that same commit and enter the successful build's run ID. The workflow verifies the commit and checksum, runs Power Apps Checker, imports that downloaded ZIP, configures the target, enables auditing and verifies components. It keeps processing off and does not publish the agent.

A green package build proves packaging. The separate deployment job and runtime acceptance establish what happened in the target. Federation and receiving-tenant deployment must be validated in your installation.

### Manual ZIP alternative

Download the same build artifact and extract it so the ZIP and `.sha256` file are together. Replace the example organization URL with the exact URL already reviewed in `.local/target.json`.

```powershell
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Check -ConfigPath .local/target.json `
  -PackagePath artifacts/ZavaMedicalClaimsConcierge.zip
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Import -ConfigPath .local/target.json `
  -PackagePath artifacts/ZavaMedicalClaimsConcierge.zip `
  -ApprovedEnvironmentUrl 'https://YOUR-ORG.crm.dynamics.com'
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Verify -ConfigPath .local/target.json
```

Both routes use the same import logic. An unmanaged import may preserve an existing enabled state, so explicit post-import configuration and readback are required. If setup fails after import, investigate the partial installation before retrying.

## 4 Add sample data and reviewer access

Solution import carries definitions, not policy or evidence rows. On the intended new Dev installation, run:

```powershell
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Bootstrap -ConfigPath .local/target.json `
  -ApprovedEnvironmentUrl 'https://YOUR-ORG.crm.dynamics.com'
```

Bootstrap adds missing policy and fictional evidence without overwriting existing changes. The imported solution already contains the app, forms, flows and agent definitions; you do not need to recreate them.

Assign **Zava Claims Medical Director** to the configured reviewer using `pac admin assign-user` or environment administration, and verify the assignment. This role provides App Opener and organization Read on the three claims tables. It grants no claims-specific create, write or delete privileges. Configure the private agent audience and verify that the reviewer can open Claims Review and its evidence links.

## 5 Verify settings and activate simulation

In Copilot Studio, verify Microsoft authentication, private reviewer access, the two user-authenticated read tools, and the native **SubmitClaimEvaluation** Flow binding. Confirm the Search knowledge source is Ready and open actual citations as the reviewer.

Verify the intended agent settings after import: public web search, ungrounded responses, connected agents, uploads, code interpreter and tenant graph grounding off. An export does not establish that every agent setting transfers to another environment.

Follow the [acceptance guide](testing.md). When ready to start controlled Dev acceptance, enable simulated processing:

```powershell
python scripts/native_dev.py --config .local/target.json --operation enable-processing `
  --approved-environment 'https://YOUR-ORG.crm.dynamics.com' --evidence-dir work/activation
```

This updates the materialized flow parameters and turns on only the two claims flows. Publish the agent in Copilot Studio and complete the native example. Keep claims simulated throughout acceptance.

For later changes, use the [maintenance guide](maintenance.md). To roll back, disable claims processing, preserve evidence and decisions, and restore an approved component version.

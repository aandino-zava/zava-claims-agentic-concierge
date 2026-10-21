# Setup and deployment

The approved installation is running in Zava PP Lab Dev. This repository includes the genuine unmanaged solution source and a checked package. Import into another environment has not been exercised. A package import transports definitions; it does not transport business records, runtime sign-ins, role assignments, sharing, publication or every agent setting.

## Receiving Dev prerequisites

Use PowerShell 7, Python 3.11+, the official PAC CLI and the dependencies in `scripts/requirements-deployment.txt`. Reuse valid authentication. The receiving tenant administrator must authorize the deployment identity, create its Dataverse application user when using a service principal, create/authorize the runtime Dataverse, Azure AI Search and Approvals connections, and supply the target settings. A connection ID grants no access by itself.

The receiving environment must include the standard AppModule Web Resources and PowerAppsAppFramework packages identified in `solution/src/Other/Solution.xml`. Do not remove those dependency declarations to force an import. The native Search contract uses `uid`, `snippet`, `blob_url`, `snippet_parent_id`, `image_snippet_parent_id` and `snippet_vector`, with integrated vectorization and a semantic configuration. An index with a different schema needs a reviewed mapping change; the deployment does not create or alter Azure indexes.

## Guided configuration

```powershell
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Configure
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Plan -ConfigPath .local/target.json
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Validate -Online -ConfigPath .local/target.json
```

The wizard asks for environment/organization/tenant IDs, the Medical Director and separate negative-test identity, Search endpoint/index/semantic configuration, the unused live-API base URL, and authorized connection IDs. These are configuration data; no PowerShell source edits are needed. Keep completed `.local/target.json` out of Git and logs. Runtime connections must point to the receiving environment and configured Search service. The negative-test account is never granted access by setup.

The publisher prefix and native component identities in this exported package are `cr` and `ZavaMedicalClaimsConcierge`. Preserve them for this package family. Changing those identifiers is a separate source migration, not ordinary target configuration.

## Import the same checked package

Download `ZavaMedicalClaimsConcierge.zip` and its `.sha256` from the checked native build. Install deployment dependencies, then run:

```powershell
python -m pip install -r scripts/requirements-deployment.txt
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Import -ConfigPath .local/target.json `
  -PackagePath artifacts/ZavaMedicalClaimsConcierge.zip `
  -ApprovedEnvironmentUrl 'https://YOUR-ORG.crm.dynamics.com'
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Verify -ConfigPath .local/target.json
```

Import checks the checksum, unmanaged solution identity, target and recognized settings. It generates PAC deployment settings, binds references by verified connector ID, imports the same ZIP, then enables and reads back organization auditing with PAC without changing retention. It configures the imported claims flow parameters and native Search index/semantic configuration through the official SDK. Both flows are read back **Off**, and their materialized `ProcessingEnabled` parameter stays `no`. Temporary deployment settings are removed. A failure after import is reported as a partial installation; do not assume it was rolled back.

Native export does not carry seed/business rows. For a confirmed new Dev installation, use the policy/fixture scripts after reviewing the exact target. Bootstrap is idempotent and preserves existing policy/evidence changes rather than overwriting them:

```powershell
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Bootstrap -ConfigPath .local/target.json `
  -ApprovedEnvironmentUrl 'https://YOUR-ORG.crm.dynamics.com'
```

Assign `Zava Claims Medical Director` to the approved reviewer with `pac admin assign-user` against that exact environment and verify the assignment. This role supplies App Opener privileges plus organization Read on only the three claims tables; it supplies no claims-specific create/write/delete privileges. Configure the private agent audience, caller connections and protected review link. The review app ID is preserved by the native package; verify the link in the receiving tenant.

Before enabling processing, verify Microsoft authentication, private owner access, user-authenticated read tools, the real native Flow tool binding, and the Search knowledge source. Reapply and verify the agent settings: public web search, ungrounded responses, connected agents, uploads, code interpreter and tenant graph grounding off. Native export is not proof that every installation setting follows the package. Open actual citations as the reviewer; returned private blob URLs are not proof of access.

Enable only the approved Dev simulation after acceptance. `native_dev.py --operation enable-processing` requires the exact approved environment and refreshes materialized flow parameters as well as the environment variable. It turns on only the two claims flows. Publish the agent through Copilot Studio after validating its topics/tools. The installed PAC version's copilot publication command failed in this session; native UI publication succeeded. Do not use a successful import as evidence of publication or end-to-end operation.

## Build and pull saved Dev changes

The native source under `solution/src` is authoritative for packaging. The temporary `agent/native` authoring workspace is ignored: an observed PAC copilot push normalized a Flow action into an incomplete binding. The repaired native binding was created in the designer and preserved by genuine solution export, including its workflow dependency. Use the solution lifecycle for delivery.

`Export` writes an ignored raw installation snapshot and refuses to overwrite nonempty source. `scripts/Export-ClaimsDevForReview.ps1` exports only the named solution into staging, prepares a portable copy, preserves the previous source in ignored work, and rebuilds only when portable definitions changed. It never imports over Dev, toggles the running Dev flows or synchronizes business records.

`prepare_native_package.py` rejects unfamiliar structure, clears installation current values and flow defaults, preserves the native Flow binding and dependencies, sets both packaged flows Off, and omits one disabled historical preview binding from the portable copy. Native Search uses explicit configuration placeholders until receiving setup applies the supplied index and semantic configuration. `Confirm-NativePortability.ps1` records the reviewed tree digest. `Pack` refuses missing review or a changed tree. The digest is SHA-256 of PowerShell-sorted `relative/path:sha256(file)` lines joined with LF and no trailing LF.

```powershell
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Pack -ConfigPath .local/target.json
pwsh scripts/Invoke-ClaimsSetup.ps1 -Operation Check -ConfigPath .local/target.json `
  -PackagePath artifacts/ZavaMedicalClaimsConcierge.zip
```

The approved package was packed with PAC 2.13.1 and Power Apps Checker returned zero findings. This does not establish receiving-tenant acceptance. An unmanaged import into an already-running installation may preserve existing state; the explicit post-import configuration and readback are required.

## GitHub delivery

The source and four workflows are published in the private repository. [Ordinary validation](https://github.com/aandino-zava/zava-claims-agentic-concierge/actions/workflows/validate.yml) runs on Windows and Linux without tenant access; [native package build results](https://github.com/aandino-zava/zava-claims-agentic-concierge/actions/workflows/build-native.yml) are recorded separately. Microsoft's installation action explicitly adds PAC to PATH for the following script steps. `Build native solution` packs the reviewed source and publishes one ZIP/checksum artifact. `Deploy checked artifact to approved Dev` is manual, requires a successful native build for the exact same commit, verifies the downloaded checksum, runs Power Apps Checker with no findings permitted, and targets the protected `claims-dev` GitHub environment. It never rebuilds a different solution inside deployment, enables processing or publishes the agent.

The tenant administrator must first configure a federated deployment application, Dataverse application user/access, and the exact repository/environment trust. Protect `claims-dev` with authorized reviewers and allowed deployment branches. Set environment variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and environment secret `PP_TARGET_JSON`. No trust, application, role or GitHub environment has been created by this build. Federation uses the supported [PAC GitHub federation option](https://learn.microsoft.com/power-platform/developer/cli/reference/auth#--githubfederated--ghf).

`Propose saved Dev changes` is also manual. It exports saved components, prepares/repacks processing off, runs local checks, and opens a scoped review PR only when portable source changed. A bot-created PR may not trigger ordinary PR CI; run the native build explicitly where needed. Review/merge changes repository source only. CI cleans its temporary settings and ephemeral authentication; do not run CI authentication cleanup against your desktop profiles.

Rollback starts by disabling claims processing, preserving evaluations/decisions/evidence, and restoring an approved native component version. Do not delete unrelated solutions or business rows.

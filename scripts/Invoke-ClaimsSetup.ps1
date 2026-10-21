#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('Configure','Validate','Plan','Bootstrap','Export','Pack','Check','Import','Verify')][string]$Operation = 'Plan',
    [string]$ConfigPath = '.local/target.json', [string]$PacPath, [string]$PythonPath = 'python',
    [string]$ApprovedEnvironmentUrl, [string]$PackagePath, [switch]$Online
)
Import-Module (Join-Path $PSScriptRoot 'ClaimsDeployment.psm1') -Force
$ErrorActionPreference = 'Stop'
$repository = Split-Path $PSScriptRoot -Parent
if ($Operation -eq 'Configure') {
    $config = Get-Content -LiteralPath (Join-Path $repository 'config/target.example.json') -Raw | ConvertFrom-Json -AsHashtable
    $pacExecutable = Resolve-ClaimsPac $PacPath
    Invoke-ClaimsPac $pacExecutable @('env','list') | Write-Host
    foreach ($key in @('environmentDisplayName','environmentId','environmentUrl','organizationId','tenantId',
        'medicalDirectorObjectId','medicalDirectorUpn','unauthorizedTestObjectId','searchEndpoint','searchIndex','searchSemanticConfiguration')) {
        $config[$key] = Read-Host $key
    }
    foreach ($connector in @('Dataverse','AzureAISearch','Approvals')) {
        $config.connections[$connector] = Read-Host ("Authorized connection ID for " + $connector)
    }
    $resolved = [System.IO.Path]::GetFullPath($ConfigPath)
    New-Item -ItemType Directory -Path (Split-Path $resolved -Parent) -Force | Out-Null
    $config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $resolved -Encoding utf8
    Read-ClaimsConfiguration $resolved | Out-Null
    Write-Host "Saved configuration: $resolved"
    $Operation = 'Plan'
}
$cfg = Read-ClaimsConfiguration $ConfigPath
if ($Operation -eq 'Validate' -and -not $Online) { Write-Host 'Configuration valid; no tenant access performed.'; return }
if ($Operation -eq 'Plan') { New-ClaimsDeploymentPlan $cfg | ConvertTo-Json -Depth 20; return }
if ($Operation -eq 'Import' -and (-not $cfg.ContainsKey('searchSemanticConfiguration') -or [string]::IsNullOrWhiteSpace($cfg.searchSemanticConfiguration))) {
    throw 'Supply the receiving Search semantic configuration in target JSON before import.'
}
$pacExecutable = Resolve-ClaimsPac $PacPath
if ($Online -or $Operation -in @('Bootstrap','Export','Import','Verify')) { Test-ClaimsOnlineTarget $cfg $pacExecutable | Out-Null }
if ($Operation -eq 'Validate') { Write-Host 'Configured tenant and Dataverse target match the live read.'; return }
if ($Operation -eq 'Bootstrap' -or $Operation -eq 'Import') { Assert-ClaimsExecutionApproval $cfg $ApprovedEnvironmentUrl }
switch ($Operation) {
    'Bootstrap' {
        Invoke-ClaimsPac $pacExecutable @('org','update-settings','--environment',$cfg.environmentUrl,'--name','isauditenabled','--value','true') | Out-Null
        Assert-ClaimsAuditEnabled $cfg $pacExecutable
        & $PythonPath (Join-Path $PSScriptRoot 'bootstrap_dataverse.py') --config $ConfigPath --execute --approved-environment $ApprovedEnvironmentUrl
        if ($LASTEXITCODE -ne 0) { throw 'Dataverse bootstrap failed; inspect scoped partial state before retry.' }
        & $PythonPath (Join-Path $PSScriptRoot 'seed_fixtures.py') --config $ConfigPath --execute --approved-environment $ApprovedEnvironmentUrl
        if ($LASTEXITCODE -ne 0) { throw 'Synthetic fixture import failed; existing rows were preserved.' }
        Write-Host 'Policy and fictional sample data are ready. Verify reviewer access and the imported components before activation.'
    }
    'Export' { Export-ClaimsNativeSolution $cfg $pacExecutable }
    'Pack' { New-ClaimsNativePackage $cfg $pacExecutable }
    'Check' {
        if (-not $PackagePath) { throw 'Supply a native -PackagePath.' }
        Test-ClaimsPackageWithChecker $cfg $pacExecutable $PackagePath
    }
    'Import' {
        Import-ClaimsNativeSolution $cfg $pacExecutable $PackagePath
        Invoke-ClaimsPac $pacExecutable @('org','update-settings','--environment',$cfg.environmentUrl,'--name','isauditenabled','--value','true') | Out-Null
        Assert-ClaimsAuditEnabled $cfg $pacExecutable
        & $PythonPath (Join-Path $PSScriptRoot 'native_dev.py') --config $ConfigPath --operation configure-runtime `
            --approved-environment $ApprovedEnvironmentUrl --evidence-dir (Join-Path $repository 'work/post-import')
        if ($LASTEXITCODE -ne 0) { throw 'Import completed, but receiving runtime configuration failed. Processing must stay off.' }
        Write-Host 'Import and receiving configuration finished with processing off. Runtime acceptance and agent publication remain separate.'
    }
    'Verify' {
        Assert-ClaimsAuditEnabled $cfg $pacExecutable
        & $PythonPath (Join-Path $PSScriptRoot 'bootstrap_dataverse.py') --config $ConfigPath --verify
        if ($LASTEXITCODE -ne 0) { throw 'Post-deployment component verification failed.' }
        Write-Host 'Table/rule/component reads completed. Run the native acceptance checklist before claiming end-to-end readiness.'
    }
}

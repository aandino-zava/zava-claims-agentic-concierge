#Requires -Version 7.0
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath,[string]$PacPath,[string]$PythonPath='python')
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ClaimsDeployment.psm1') -Force
$repository=Split-Path $PSScriptRoot -Parent
$cfg=Read-ClaimsConfiguration $ConfigPath
$pacExecutable=Resolve-ClaimsPac $PacPath
Test-ClaimsOnlineTarget $cfg $pacExecutable | Out-Null
$staging=Join-Path $repository ('work/dev-export-'+[guid]::NewGuid())
New-Item -ItemType Directory -Path $staging -Force | Out-Null
$raw=Join-Path $staging 'raw.zip'
$prepared=Join-Path $staging 'prepared'
Invoke-ClaimsPac $pacExecutable @('solution','export','--environment',$cfg.environmentUrl,'--name',$cfg.solutionUniqueName,'--path',$raw,'--managed','false','--overwrite') | Out-Null
Invoke-ClaimsPac $pacExecutable @('solution','unpack','--zipfile',$raw,'--folder',$prepared,'--packagetype','Unmanaged') | Out-Null
$provenancePath=Join-Path $repository 'solution/provenance.json'
$oldProvenance=Get-Content -LiteralPath $provenancePath -Raw
$provenance=$oldProvenance | ConvertFrom-Json -AsHashtable
$oldTree=$provenance.portableTreeSha256
$provenance.nativeExportPresent=$true
$provenance.rawExportSha256=(Get-FileHash -LiteralPath $raw -Algorithm SHA256).Hash.ToLowerInvariant()
$stagedProvenance=Join-Path $staging 'provenance.json'
$provenance | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $stagedProvenance -Encoding utf8
& $PythonPath (Join-Path $PSScriptRoot 'prepare_native_package.py') --source $prepared --provenance $stagedProvenance
if ($LASTEXITCODE -ne 0) { throw 'Portable export preparation failed; existing repository source was preserved.' }
$source=[IO.Path]::GetFullPath((Join-Path $repository 'solution/src'))
$backup=[IO.Path]::GetFullPath((Join-Path $staging 'before'))
$rootPrefix=[IO.Path]::GetFullPath($repository)+[IO.Path]::DirectorySeparatorChar
foreach ($target in @($source,$backup,[IO.Path]::GetFullPath($prepared))) {
    if (-not $target.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Move target outside repository' }
}
Move-Item -LiteralPath $source -Destination $backup
Move-Item -LiteralPath $prepared -Destination $source
Copy-Item -LiteralPath $stagedProvenance -Destination $provenancePath
& (Join-Path $PSScriptRoot 'Confirm-NativePortability.ps1') -RepositoryRoot $repository
$current=Get-Content -LiteralPath $provenancePath -Raw | ConvertFrom-Json -AsHashtable
if ($current.portableTreeSha256 -eq $oldTree) {
    $oldProvenance | Set-Content -LiteralPath $provenancePath -Encoding utf8
    Write-Host 'Saved Dev export has no portable source changes. No PR is needed.'
    return
}
New-ClaimsNativePackage $cfg $pacExecutable | Write-Host
Write-Host 'Portable saved Dev changes are ready for review. Dev runtime was not changed; raw export remains ignored.'

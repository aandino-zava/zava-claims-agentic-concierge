#Requires -Version 7.0
[CmdletBinding()]
param([string]$RepositoryRoot = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference='Stop'
$source=Join-Path $RepositoryRoot 'solution/src'
$provenancePath=Join-Path $RepositoryRoot 'solution/provenance.json'
$provenance=Get-Content -LiteralPath $provenancePath -Raw | ConvertFrom-Json -AsHashtable
if ($provenance.state -ne 'PortableNativeSourcePrepared' -or $provenance.processingEnabledInDistributable) {
    throw 'Prepare and inspect the authentic export before confirming its portable digest.'
}
$tree=@(Get-ChildItem -LiteralPath $source -File -Recurse | Sort-Object FullName | ForEach-Object {
    [IO.Path]::GetRelativePath($source,$_.FullName).Replace('\','/')+':'+(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}) -join "`n"
$provenance.portableTreeSha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($tree))).ToLowerInvariant()
$provenance.portableReviewComplete=$true
$provenance.state='PortableNativeSourceReviewed'
$provenance | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $provenancePath -Encoding utf8
Write-Host 'Reviewed portable native tree digest saved. Runtime Dev state was not changed.'

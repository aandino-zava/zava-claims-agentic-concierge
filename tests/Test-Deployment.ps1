#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
$claimsModule=Import-Module (Join-Path $PSScriptRoot '../scripts/ClaimsDeployment.psm1') -Force -PassThru
$repo = Split-Path $PSScriptRoot -Parent
$work = Join-Path $repo 'work'
New-Item -ItemType Directory -Path $work -Force | Out-Null
$testFile = Join-Path $work ('deployment-test-' + [guid]::NewGuid().ToString() + '.json')
$testPackage = Join-Path $work ('invalid-package-' + [guid]::NewGuid().ToString() + '.zip')
$packageFixture=Join-Path $work ('package-fixture-'+[guid]::NewGuid())
$fixtureSolution=Join-Path $packageFixture 'solution'
$fixtureOther=Join-Path $fixtureSolution 'src/Other'
New-Item -ItemType Directory -Path $fixtureOther -Force | Out-Null
$fixtureProvenance=Join-Path $fixtureSolution 'provenance.json'
$fixtureManifest=Join-Path $fixtureOther 'Solution.xml'
function Invoke-FixturePack {
    & $claimsModule { param($root,$cfg)
        $previous=$script:RepositoryRoot
        try { $script:RepositoryRoot=$root; New-ClaimsNativePackage $cfg 'must-not-be-invoked' }
        finally { $script:RepositoryRoot=$previous }
    } $packageFixture $configuration
}
$configuration = Get-Content -LiteralPath (Join-Path $repo 'config/target.example.json') -Raw | ConvertFrom-Json -AsHashtable
foreach ($key in @('environmentId','organizationId','tenantId','medicalDirectorObjectId','unauthorizedTestObjectId')) { $configuration[$key] = [guid]::NewGuid().ToString() }
$configuration.environmentDisplayName='Example Dev'; $configuration.environmentUrl='https://orgpoc.crm.dynamics.com'
$configuration.searchEndpoint='https://search-poc.search.windows.net'; $configuration.searchIndex='claims-poc-index'
$configuration.claimsApiBaseUrl='https://claims-poc.azurewebsites.net'; $configuration.medicalDirectorUpn='reviewer@example.test'
$script:passed = 0
function Assert-True([bool]$Condition,[string]$Label) { if (-not $Condition) { throw "Failed: $Label" }; $script:passed++ }
function Assert-Throws([scriptblock]$Action,[string]$Label) { $thrown=$false; try { & $Action | Out-Null } catch { $thrown=$true }; Assert-True $thrown $Label }
function Assert-ThrowsLike([scriptblock]$Action,[string]$Pattern,[string]$Label) { $message=''; try { & $Action | Out-Null } catch { $message=$_.Exception.Message }; Assert-True ($message -match $Pattern) $Label }
function Write-TestConfig($Value) { $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $testFile -Encoding utf8 }
try {
    Write-TestConfig $configuration
    $valid = Read-ClaimsConfiguration $testFile
    Assert-True ($valid.mode -eq 'Simulated') 'Valid config'
    $copy=$configuration.Clone(); $copy.claimsApiBaseUrl=''; Write-TestConfig $copy
    Assert-True ((Read-ClaimsConfiguration $testFile).claimsApiBaseUrl -eq '') 'No live API required for simulation'
    $plan = New-ClaimsDeploymentPlan $valid
    Assert-True ($plan.environmentUrl -eq $valid.environmentUrl -and $plan.operations.Count -eq 10) 'Plan target and operations'
    foreach ($change in @(@('deploymentScope','Production'),@('mode','Live'),@('allowLiveClaimsWrites',$true),@('processingEnabled',$true),
        @('environmentUrl','http://orgpoc.crm.dynamics.com'),@('searchEndpoint','https://search-poc.search.windows.net.attacker.test'),
        @('claimsApiBaseUrl','http://claims-poc.azurewebsites.net'),@('tenantId','not-a-guid'),@('publisherPrefix','x'),@('medicalDirectorUpn','invalid'))) {
        $copy = $configuration.Clone(); $copy[$change[0]]=$change[1]; Write-TestConfig $copy
        Assert-Throws { Read-ClaimsConfiguration $testFile } ('Reject '+$change[0])
    }
    $copy=$configuration.Clone(); $copy.unauthorizedTestObjectId=$copy.medicalDirectorObjectId; Write-TestConfig $copy
    Assert-Throws { Read-ClaimsConfiguration $testFile } 'Separate negative-test identity'
    $copy=$configuration.Clone(); $copy['clientSecret']='forbidden'; Write-TestConfig $copy
    Assert-Throws { Read-ClaimsConfiguration $testFile } 'No credentials in configuration'
    Assert-Throws { Assert-ClaimsExecutionApproval $configuration 'https://wrong.crm.dynamics.com' } 'Wrong approval target'
    Assert-Throws { Assert-ClaimsExecutionApproval $configuration '' } 'Missing deployment approval'
    '{"nativeExportPresent":false}' | Set-Content -LiteralPath $fixtureProvenance
    Assert-ThrowsLike { Invoke-FixturePack } 'No authentic native export' 'Reject missing native export'
    '<ImportExportXml />' | Set-Content -LiteralPath $fixtureManifest
    '{"nativeExportPresent":true,"portableReviewComplete":false}' | Set-Content -LiteralPath $fixtureProvenance
    Assert-ThrowsLike { Invoke-FixturePack } 'still needs portability' 'Reject unreviewed native source'
    @{nativeExportPresent=$true;portableReviewComplete=$true;processingEnabledInDistributable=$false;portableTreeSha256=('0'*64)} | ConvertTo-Json | Set-Content -LiteralPath $fixtureProvenance
    Assert-ThrowsLike { Invoke-FixturePack } 'source changed since portability review' 'Reject changed reviewed native source'
    $zip = [IO.Compression.ZipFile]::Open($testPackage,[IO.Compression.ZipArchiveMode]::Create)
    try {
        $entry=$zip.CreateEntry('solution.xml'); $writer=[IO.StreamWriter]::new($entry.Open())
        try { $writer.Write('<ImportExportXml><SolutionManifest><UniqueName>UnrelatedSolution</UniqueName><Managed>0</Managed></SolutionManifest></ImportExportXml>') } finally { $writer.Dispose() }
    } finally { $zip.Dispose() }
    '0'*64 | Set-Content -LiteralPath ($testPackage+'.sha256') -Encoding ascii
    Assert-ThrowsLike { Import-ClaimsNativeSolution $configuration 'not-invoked' $testPackage } 'checksum mismatch' 'Reject changed package before tenant access'
    (Get-FileHash -LiteralPath $testPackage -Algorithm SHA256).Hash | Set-Content -LiteralPath ($testPackage+'.sha256') -Encoding ascii
    Assert-ThrowsLike { Import-ClaimsNativeSolution $configuration 'not-invoked' $testPackage } 'configured unmanaged claims solution' 'Reject unrelated solution before tenant access'
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $repo 'scripts') -File | Where-Object Extension -in @('.ps1','.psm1')) {
        $tokens=$null; $parseErrors=$null
        [System.Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$parseErrors) | Out-Null
        Assert-True ($parseErrors.Count -eq 0) ('PowerShell syntax: '+$file.Name)
    }
    Write-Host "Passed $script:passed local deployment/configuration checks. No tenant mutations performed."
} finally {
    foreach ($path in @($testFile,$testPackage,($testPackage+'.sha256'),$fixtureManifest,$fixtureProvenance)) { if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force } }
    # Remove only known empty fixture folders, never recursively delete a computed path.
    foreach ($path in @($fixtureOther,(Join-Path $fixtureSolution 'src'),$fixtureSolution,$packageFixture)) { if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path } }
}

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:RepositoryRoot = Split-Path $PSScriptRoot -Parent

function Read-ClaimsConfiguration {
    param([Parameter(Mandatory)][string]$Path)
    $cfg = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable
    $allowed = @('deploymentScope','environmentDisplayName','environmentId','environmentUrl','organizationId','tenantId',
        'publisherUniqueName','publisherDisplayName','publisherPrefix','solutionUniqueName','solutionDisplayName',
        'mode','processingEnabled','allowLiveClaimsWrites','medicalDirectorObjectId','medicalDirectorUpn',
        'unauthorizedTestObjectId','searchEndpoint','searchIndex','claimsApiBaseUrl','connections')
    foreach ($key in $cfg.Keys) { if ($key -notin ($allowed + @('searchSemanticConfiguration'))) { throw "Unexpected configuration field: $key" } }
    foreach ($key in $allowed) { if (-not $cfg.ContainsKey($key)) { throw "Missing configuration field: $key" } }
    if ($cfg.deploymentScope -ne 'Development' -or $cfg.mode -ne 'Simulated' -or
        $cfg.allowLiveClaimsWrites -isnot [bool] -or $cfg.allowLiveClaimsWrites -or
        $cfg.processingEnabled -isnot [bool] -or $cfg.processingEnabled) {
        throw 'This delivery supports Development, Simulated mode, live writes disabled, and packaged processing off.'
    }
    foreach ($key in @('environmentId','organizationId','tenantId','medicalDirectorObjectId','unauthorizedTestObjectId')) {
        $parsedGuid = [guid]::Empty
        if (-not [guid]::TryParse([string]$cfg[$key], [ref]$parsedGuid) -or $parsedGuid -eq [guid]::Empty) { throw "Invalid GUID: $key" }
    }
    if ($cfg.medicalDirectorObjectId -eq $cfg.unauthorizedTestObjectId) { throw 'The negative-test identity must differ from the reviewer.' }
    if ($cfg.environmentUrl -notmatch '^https://[a-z0-9-]+\.crm[0-9]*\.dynamics\.com/?$') { throw 'Expected a Dataverse HTTPS organization URL.' }
    if ($cfg.searchEndpoint -notmatch '^https://[a-z0-9-]+\.search\.windows\.net/?$') { throw 'Expected an Azure AI Search HTTPS endpoint.' }
    if ($cfg.claimsApiBaseUrl -and $cfg.claimsApiBaseUrl -notmatch '^https://[a-z0-9-]+\.azurewebsites\.net/?$') { throw 'Expected an App Service HTTPS API base URL.' }
    if ($cfg.medicalDirectorUpn -notmatch '^[^\s@]+@[^\s@]+$') { throw 'Invalid reviewer UPN.' }
    if ($cfg.publisherPrefix -notmatch '^[a-z][a-z0-9]{1,7}$') { throw 'Publisher prefix must contain 2-8 lowercase letters/digits.' }
    foreach ($key in @('publisherUniqueName','solutionUniqueName')) {
        if ($cfg[$key] -notmatch '^[A-Za-z][A-Za-z0-9_]{1,79}$') { throw "Invalid unique name: $key" }
    }
    if ([string]::IsNullOrWhiteSpace($cfg.searchIndex) -or $cfg.searchIndex -notmatch '^[a-z0-9][a-z0-9-]*$') { throw 'Invalid Search index name.' }
    if ($cfg.connections -isnot [System.Collections.IDictionary]) { throw 'Connections must be an object.' }
    return $cfg
}

function Resolve-ClaimsPac {
    param([string]$PacPath)
    if ($PacPath) { if (-not (Test-Path -LiteralPath $PacPath -PathType Leaf)) { throw 'PAC executable not found.' }; return $PacPath }
    $command = Get-Command pac -ErrorAction SilentlyContinue
    if (-not $command) { throw 'PAC CLI is required. Supply -PacPath or install the official Microsoft Power Platform CLI.' }
    return $command.Source
}

function Invoke-ClaimsPac {
    param([string]$PacPath, [string[]]$Arguments)
    $result = & $PacPath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "PAC command failed: $($Arguments[0..([Math]::Min(1,$Arguments.Count-1))] -join ' ')" }
    return ($result -join "`n")
}

function Test-ClaimsOnlineTarget {
    param([hashtable]$Configuration, [string]$PacPath)
    $text = Invoke-ClaimsPac $PacPath @('env','who','--environment',$Configuration.environmentUrl,'--json')
    $who = $text | ConvertFrom-Json -AsHashtable
    if ($who.EnvironmentId -ne $Configuration.environmentId -or $who.OrgId -ne $Configuration.organizationId -or
        $who.OrgUrl.TrimEnd('/') -ne $Configuration.environmentUrl.TrimEnd('/') -or
        $who.FriendlyName -ne $Configuration.environmentDisplayName) { throw 'Live Dataverse target does not match the configuration.' }
    # Verify the currently selected Azure tenant without changing it.
    $account = & az account show --query '{tenant:tenantId}' -o json | ConvertFrom-Json -AsHashtable
    if ($LASTEXITCODE -ne 0 -or $account.tenant -ne $Configuration.tenantId) { throw 'Cached Azure tenant does not match the target.' }
    return $who
}

function Assert-ClaimsAuditEnabled {
    param([hashtable]$Configuration,[string]$PacPath)
    $result=Invoke-ClaimsPac $PacPath @('org','list-settings','--filter','isauditenabled','--environment',$Configuration.environmentUrl)
    if ($result -notmatch '(?im)^isauditenabled\s+(Yes|True)\s*$') { throw 'Organization auditing was not confirmed enabled by PAC.' }
    Write-Host 'Organization auditing confirmed enabled.'
}

function New-ClaimsDeploymentPlan {
    param([hashtable]$Configuration)
    return [ordered]@{
        kind = 'SolutionDeployment'; environment = $Configuration.environmentDisplayName
        environmentUrl = $Configuration.environmentUrl; environmentId = $Configuration.environmentId
        organizationId = $Configuration.organizationId; tenantId = $Configuration.tenantId
        solution = $Configuration.solutionUniqueName; publisherPrefix = $Configuration.publisherPrefix
        medicalDirector = $Configuration.medicalDirectorUpn; medicalDirectorObjectId = $Configuration.medicalDirectorObjectId
        unauthorizedTestObjectId = $Configuration.unauthorizedTestObjectId; claimsMode = 'Simulated'
        operations = @(
            'Validate the exact Development target and authorized connections.'
            'Build or download the reviewed unmanaged solution and verify its checksum.'
            'Run Power Apps Checker on the package selected for import.'
            'Import that package and bind its connection references.'
            'Configure target flow parameters and Search mapping with processing off.'
            'Enable and verify organization auditing without changing retention.'
            'Add missing policy and fictional evidence rows without overwriting changes.'
            'Assign and verify the Medical Director role and private agent audience.'
            'Verify native tools, protected review links and Search access.'
            'Enable simulation and publish the agent for controlled native acceptance.'
        )
        excluded = @('Azure resources/role assignments/app registrations','real claims writes','UAT/Test/Production deployment','GitHub publication','messages to other lab users')
        permissionStatus = 'Import and Bootstrap require a matching ApprovedEnvironmentUrl'
    }
}

function Assert-ClaimsExecutionApproval {
    param([hashtable]$Configuration, [string]$ApprovedEnvironmentUrl)
    if (-not $ApprovedEnvironmentUrl -or $ApprovedEnvironmentUrl.TrimEnd('/') -ne $Configuration.environmentUrl.TrimEnd('/')) {
        throw 'Execution requires -ApprovedEnvironmentUrl matching the reviewed Dev target.'
    }
}

function Read-ClaimsCheckerResults {
    param([Parameter(Mandatory)][string]$Directory)
    $archives=@(Get-ChildItem -LiteralPath $Directory -File -Filter '*.zip')
    if ($archives.Count -ne 1) { throw 'Expected one downloaded Power Apps Checker report.' }
    $archive=[IO.Compression.ZipFile]::OpenRead($archives[0].FullName)
    try {
        $reports=@($archive.Entries | Where-Object FullName -like '*.sarif')
        if ($reports.Count -ne 1) { throw 'Expected one SARIF report.' }
        $reader=[IO.StreamReader]::new($reports[0].Open())
        try { $report=$reader.ReadToEnd() | ConvertFrom-Json -AsHashtable } finally { $reader.Dispose() }
        if (-not $report.ContainsKey('runs')) { throw 'Checker report has no completed analysis runs.' }
        $findings=0
        foreach ($run in $report.runs) { if ($run.ContainsKey('results')) { $findings+=@($run.results).Count } }
        if ($findings -gt 0) { throw "Power Apps Checker returned $findings finding(s); review before deployment." }
        return @{status='Finished';findings=$findings;reportSha256=(Get-FileHash -LiteralPath $archives[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    } finally { $archive.Dispose() }
}

function Test-ClaimsPackageWithChecker {
    param([hashtable]$Configuration,[string]$PacPath,[string]$PackagePath)
    if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw 'Native package not found.' }
    $directory=Join-Path $script:RepositoryRoot ('work/checker-'+[guid]::NewGuid())
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    # PAC prints a temporary signed report URL. Capture it and expose only the
    # parsed report summary, never its signed download URL in normal CI logs.
    Invoke-ClaimsPac $PacPath @('solution','check','--environment',$Configuration.environmentUrl,'--path',$PackagePath,'--outputDirectory',$directory) | Out-Null
    $result=Read-ClaimsCheckerResults $directory
    $result.packageSha256=(Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $result | ConvertTo-Json
}

function Export-ClaimsNativeSolution {
    param([hashtable]$Configuration, [string]$PacPath)
    $nativeRoot = Join-Path $script:RepositoryRoot 'solution'
    $source = Join-Path $nativeRoot 'src'
    if ((Test-Path -LiteralPath $source) -and @(Get-ChildItem -LiteralPath $source -Force).Count -gt 0) {
        throw 'Existing native source must be reviewed before replacement. Export into a clean checkout to preserve Dev edits.'
    }
    $raw = Join-Path $nativeRoot 'raw'
    New-Item -ItemType Directory -Path $raw -Force | Out-Null
    $zip = Join-Path $raw ($Configuration.solutionUniqueName + '.zip')
    Invoke-ClaimsPac $PacPath @('solution','export','--environment',$Configuration.environmentUrl,'--name',$Configuration.solutionUniqueName,'--path',$zip,'--managed','false','--overwrite') | Out-Null
    Invoke-ClaimsPac $PacPath @('solution','unpack','--zipfile',$zip,'--folder',$source,'--packagetype','Unmanaged') | Out-Null
    $provenance = @{state='NativeExportNeedsPortabilityReview';nativeExportPresent=$true;importableSolutionPresent=$false;
        portableReviewComplete=$false;processingEnabledInDistributable=$false;requiredSolution=$Configuration.solutionUniqueName;
        rawExportSha256=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()}
    $provenance | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $nativeRoot 'provenance.json') -Encoding utf8
    return $zip
}

function New-ClaimsNativePackage {
    param([hashtable]$Configuration, [string]$PacPath)
    $native = Join-Path $script:RepositoryRoot 'solution'
    $provenance = Get-Content -LiteralPath (Join-Path $native 'provenance.json') -Raw | ConvertFrom-Json -AsHashtable
    $source = Join-Path $native 'src'
    if (-not $provenance.nativeExportPresent -or -not (Test-Path -LiteralPath (Join-Path $source 'Other/Solution.xml'))) {
        throw 'No authentic native export exists. Complete approved Dev authoring and export first.'
    }
    if (-not $provenance.ContainsKey('portableReviewComplete') -or -not $provenance.portableReviewComplete) {
        throw 'The native export still needs portability, dependency, binding and processing-state review.'
    }
    if ($provenance.processingEnabledInDistributable) { throw 'Distributable processing must be off.' }
    if (-not $provenance.ContainsKey('portableTreeSha256')) { throw 'Reviewed native source digest is missing.' }
    $tree = @(Get-ChildItem -LiteralPath $source -File -Recurse | Sort-Object FullName | ForEach-Object {
        [IO.Path]::GetRelativePath($source,$_.FullName).Replace('\','/') + ':' + (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }) -join "`n"
    $treeHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($tree))).ToLowerInvariant()
    if ($treeHash -ne $provenance.portableTreeSha256) { throw 'Native source changed since portability review.' }
    $artifactRoot = Join-Path $script:RepositoryRoot 'artifacts'
    New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null
    $zip = Join-Path $artifactRoot 'ZavaMedicalClaimsConcierge.zip'
    Invoke-ClaimsPac $PacPath @('solution','pack','--zipfile',$zip,'--folder',$source,'--packagetype','Unmanaged') | Out-Null
    $packageHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    $packageHash | Set-Content -LiteralPath ($zip + '.sha256') -Encoding ascii
    if (-not $provenance.ContainsKey('packageSha256') -or $provenance.packageSha256 -ne $packageHash) {
        $provenance.checkerStatus='NotRunForThisPackage'
        $provenance.checkerFindings=$null
    }
    $provenance.packageSha256 = $packageHash
    $provenance.importableSolutionPresent = $true
    $provenance.state = 'NativePackageBuilt'
    $provenance | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $native 'provenance.json') -Encoding utf8
    return $zip
}

function Import-ClaimsNativeSolution {
    param([hashtable]$Configuration, [string]$PacPath, [string]$PackagePath)
    if ($Configuration.publisherPrefix -ne 'cr' -or $Configuration.solutionUniqueName -ne 'ZavaMedicalClaimsConcierge') {
        throw 'This native package preserves the cr publisher prefix and ZavaMedicalClaimsConcierge identity.'
    }
    if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw 'Native package not found.' }
    $expectedHash = (Get-Content -LiteralPath ($PackagePath + '.sha256') -Raw).Trim()
    if ((Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Package checksum mismatch.' }
    $archive = [IO.Compression.ZipFile]::OpenRead([IO.Path]::GetFullPath($PackagePath))
    try {
        $entry = $archive.GetEntry('solution.xml')
        if (-not $entry) { throw 'The ZIP has no native solution manifest.' }
        $reader = [IO.StreamReader]::new($entry.Open())
        try { [xml]$manifest = $reader.ReadToEnd() } finally { $reader.Dispose() }
        $uniqueName = $manifest.SelectSingleNode("//*[local-name()='SolutionManifest']/*[local-name()='UniqueName']")
        $managed = $manifest.SelectSingleNode("//*[local-name()='SolutionManifest']/*[local-name()='Managed']")
        if (-not $uniqueName -or $uniqueName.InnerText -ne $Configuration.solutionUniqueName -or -not $managed -or $managed.InnerText -ne '0') {
            throw 'Package is not the configured unmanaged claims solution.'
        }
    } finally { $archive.Dispose() }
    $work = Join-Path $script:RepositoryRoot 'work'
    New-Item -ItemType Directory -Path $work -Force | Out-Null
    $settingsPath = Join-Path $work ('settings-' + [guid]::NewGuid().ToString() + '.json')
    try {
        Invoke-ClaimsPac $PacPath @('solution','create-settings','--solution-zip',$PackagePath,'--settings-file',$settingsPath) | Out-Null
        $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json -AsHashtable
        $values = @{'ClaimsMode'='Simulated';'ProcessingEnabled'='no';'SearchEndpoint'=$Configuration.searchEndpoint;
            'SearchIndex'=$Configuration.searchIndex;'PolicyVersion'='1.0';'MedicalDirectorObjectId'=$Configuration.medicalDirectorObjectId;
            'MedicalDirectorUPN'=$Configuration.medicalDirectorUpn;'ClaimsApiBaseUrl'=$Configuration.claimsApiBaseUrl;'ApprovalLifetimeHours'='24';
            'TenantId'=$Configuration.tenantId;'DataverseUrl'=$Configuration.environmentUrl}
        foreach ($variable in $settings.EnvironmentVariables) {
            $suffix = $variable.SchemaName -replace ('^'+[regex]::Escape($Configuration.publisherPrefix)+'_'), ''
            if (-not $values.ContainsKey($suffix)) { throw "Unrecognized packaged variable: $($variable.SchemaName)" }
            $variable.Value = $values[$suffix]
        }
        foreach ($reference in $settings.ConnectionReferences) {
            # Native agent authoring creates additional references with generated
            # logical names. Bind by the verified connector, not a name guess.
            $suffix = switch -Regex ($reference.ConnectorId) {
                '/shared_commondataserviceforapps$' { 'Dataverse'; break }
                '/shared_azureaisearch$' { 'AzureAISearch'; break }
                '/shared_approvals$' { 'Approvals'; break }
                '/shared_teams$' { 'Teams'; break }
                default { throw "Unsupported packaged connector: $($reference.ConnectorId)" }
            }
            if (-not $Configuration.connections.ContainsKey($suffix) -or [string]::IsNullOrWhiteSpace($Configuration.connections[$suffix])) {
                throw "Supply the authorized connection for $suffix through configuration."
            }
            $reference.ConnectionId = $Configuration.connections[$suffix]
        }
        $settings | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $settingsPath -Encoding utf8
        Invoke-ClaimsPac $PacPath @('solution','import','--environment',$Configuration.environmentUrl,'--path',$PackagePath,
            '--settings-file',$settingsPath,'--publish-changes') | Out-Null
    } finally {
        if (Test-Path -LiteralPath $settingsPath) { Remove-Item -LiteralPath $settingsPath -Force }
    }
}

Export-ModuleMember -Function Read-ClaimsConfiguration,Resolve-ClaimsPac,Invoke-ClaimsPac,Test-ClaimsOnlineTarget,Assert-ClaimsAuditEnabled,New-ClaimsDeploymentPlan,Assert-ClaimsExecutionApproval,Read-ClaimsCheckerResults,Test-ClaimsPackageWithChecker,Export-ClaimsNativeSolution,New-ClaimsNativePackage,Import-ClaimsNativeSolution

param(
    [switch]$SkipInstaller,
    [string]$BuildId = "",
    [string]$WebView2BootstrapperPath = "",
    [string]$InstallerExtractorPath = ""
)

function Resolve-SingleInstaller {
    param(
        [Parameter(Mandatory = $true)]
        [string]$OutputDirectory
    )

    $Candidates = @(Get-ChildItem -LiteralPath $OutputDirectory -Filter "*.exe" -File)
    if ($Candidates.Count -eq 0) {
        throw "Installer build produced no Setup executable in: $OutputDirectory"
    }
    if ($Candidates.Count -gt 1) {
        throw "Installer build produced multiple Setup executables in: $OutputDirectory"
    }
    return $Candidates[0]
}

# R1 shipped msvcp140/vcruntime140 14.26 from a driver folder that sat before System32 on PATH;
# PyInstaller resolves these DLLs through PATH. For the PyInstaller run, put System32 first and
# drop every other folder that carries its own copy.
function Get-PackagingPath {
    $System32 = [Environment]::GetFolderPath("System").TrimEnd('\')
    $Entries = @($System32)
    foreach ($Entry in ($env:PATH -split ';')) {
        $Trimmed = $Entry.Trim().Trim('"').TrimEnd('\')
        if (-not $Trimmed -or $Trimmed -ieq $System32) { continue }
        $CarriesVcRuntime = $false
        foreach ($Name in @("msvcp140.dll", "vcruntime140.dll")) {
            try {
                if (Test-Path -LiteralPath (Join-Path $Trimmed $Name) -PathType Leaf) { $CarriesVcRuntime = $true }
            }
            catch { }
        }
        if ($CarriesVcRuntime) {
            Write-Host "PACKAGING_PATH_DROPPED=$Trimmed"
            continue
        }
        $Entries += $Trimmed
    }
    return ($Entries -join ';')
}

# onnxruntime needs VC runtime 14.40 or newer; an older bundled copy fails at import on the user's machine.
function Assert-VcRuntimeVersion {
    param(
        [Parameter(Mandatory = $true)][string]$AppTree,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $Minimum = [Version]"14.40.0.0"
    # Windows PowerShell 5.1 ignores -Include together with -LiteralPath, so filter by name explicitly.
    $Dlls = @(Get-ChildItem -LiteralPath $AppTree -Recurse -File | Where-Object { $_.Name -match '^(msvcp140|vcruntime140|concrt140).*\.dll$' })
    if ($Dlls.Count -eq 0) {
        throw "VC_RUNTIME_GATE=FAIL ($Label): no VC runtime DLL found under $AppTree"
    }
    foreach ($Dll in $Dlls) {
        $DllVersion = $Dll.VersionInfo.FileVersionRaw
        $Relative = $Dll.FullName.Substring($AppTree.Length).TrimStart('\')
        if ($null -eq $DllVersion -or $DllVersion -lt $Minimum) {
            throw "VC_RUNTIME_GATE=FAIL ($Label): $Relative is $DllVersion, needs >= $Minimum"
        }
        Write-Output "VC_RUNTIME=$DllVersion $Relative"
    }
    Write-Output "VC_RUNTIME_GATE=PASS ($Label) files=$($Dlls.Count)"
}

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$VersionPath = Join-Path $ProjectRoot "product_version.json"
$SpecPath = Join-Path $PSScriptRoot "HDDE.spec"
$InstallerScript = Join-Path $PSScriptRoot "HDDE.iss"
$PackageDataGate = Join-Path $PSScriptRoot "package_data_gate.py"
$InstallerDataGate = Join-Path $PSScriptRoot "installer_data_gate.py"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Project Python runtime is missing: $Python"
}

$Version = Get-Content -Raw -Encoding UTF8 -LiteralPath $VersionPath | ConvertFrom-Json
$VersionMatch = [regex]::Match([string]$Version.version, '^(\d+)\.(\d+)\.(\d+)')
if (-not $VersionMatch.Success) {
    throw "product_version.json has an invalid version."
}
$InstallerVersion = "$($VersionMatch.Groups[1].Value).$($VersionMatch.Groups[2].Value).$($VersionMatch.Groups[3].Value).0"
$PublicVersion = "V$($VersionMatch.Groups[1].Value).$($VersionMatch.Groups[2].Value).$($VersionMatch.Groups[3].Value)"
if (-not $BuildId) {
    $BuildId = "W60-03-" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ") + "-" + $PID
}
if ($BuildId -notmatch '^[A-Za-z0-9_.-]+$') {
    throw "BuildId may contain only letters, digits, dot, underscore and hyphen."
}
$PackageBaseName = "HDDE_V$($Version.version)_${BuildId}_Setup"
$ReleaseRoot = Join-Path $ProjectRoot "build\w60_03\$($Version.version)\$BuildId"
$FrontendDist = Join-Path $ReleaseRoot "dist"
$AppDist = Join-Path $ReleaseRoot "app"
$PyInstallerWork = Join-Path $ReleaseRoot "pyinstaller"
$InstallerOutput = Join-Path $ProjectRoot "packaging\windows\release\$PublicVersion\installer"
$ProvenanceManifest = Join-Path $ReleaseRoot "package-provenance-manifest.json"
$ExtractedInstallerRoot = Join-Path $ReleaseRoot "installer-extracted"
$ExtractedProvenanceManifest = Join-Path $ReleaseRoot "installer-extracted-app-provenance-manifest.json"
$InstallerContentManifest = Join-Path $ReleaseRoot "installer-content-manifest.json"
# ISCC writes the Setup file incrementally; an interrupted compile leaves a truncated exe.
# Compile into the build tree and move into the release folder only after every gate passes.
$InstallerStaging = Join-Path $ReleaseRoot "installer-staging"

foreach ($OutputPath in @($FrontendDist, $AppDist, $PyInstallerWork, $ProvenanceManifest, $ExtractedInstallerRoot, $ExtractedProvenanceManifest, $InstallerContentManifest, $InstallerStaging)) {
    if (Test-Path -LiteralPath $OutputPath) {
        throw "Isolated W60-03 output already exists and will not be deleted: $OutputPath"
    }
}
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null

Push-Location $ProjectRoot
$PreviousFrontendDist = $env:HDDE_PACKAGING_FRONTEND_DIR
try {
    $env:HDDE_PACKAGING_FRONTEND_DIR = $FrontendDist
    & npm.cmd run build -- --outDir $FrontendDist --manifest
    if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed with exit code $LASTEXITCODE." }

    & $Python -c "import os; from pathlib import Path; from runtime.production_frontend import validate_production_frontend; validate_production_frontend(Path(os.environ['HDDE_PACKAGING_FRONTEND_DIR'])); print('PRODUCTION_FRONTEND=PASS')"
    if ($LASTEXITCODE -ne 0) { throw "Frontend artifact validation failed with exit code $LASTEXITCODE." }

    $PreviousPath = $env:PATH
    try {
        $env:PATH = Get-PackagingPath
        & $Python -m PyInstaller --noconfirm --distpath $AppDist --workpath $PyInstallerWork $SpecPath
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed with exit code $LASTEXITCODE." }
    }
    finally {
        $env:PATH = $PreviousPath
    }

    $PackagedAppTree = Join-Path $AppDist "HDDE"
    $PackagedExe = Join-Path $PackagedAppTree "HDDE.exe"
    if (-not (Test-Path -LiteralPath $PackagedExe -PathType Leaf)) {
        throw "Frozen runtime output is missing: $PackagedExe"
    }
    Assert-VcRuntimeVersion -AppTree $PackagedAppTree -Label "app"
    # HDDE.exe is a windowed app: pipe through Out-String so PowerShell waits and captures the self-test line.
    $SelfTestOutput = (& $PackagedExe --self-test | Out-String).Trim()
    $SelfTestExit = $LASTEXITCODE
    Write-Output $SelfTestOutput
    if ($SelfTestExit -ne 0 -or $SelfTestOutput -notmatch 'HDDE_PACKAGED_SELF_TEST=PASS') {
        throw "Frozen runtime self-test failed with exit code ${SelfTestExit}: $SelfTestOutput"
    }

    & $Python $PackageDataGate --app-tree $PackagedAppTree --project-root $ProjectRoot --manifest $ProvenanceManifest --pyinstaller-work (Join-Path $PyInstallerWork "HDDE")
    if ($LASTEXITCODE -ne 0) { throw "PACKAGE_DATA_LEAK_GATE failed with exit code $LASTEXITCODE." }

    $PackagedExeHash = Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $PackagedExe -Algorithm SHA256
    $ProvenanceManifestHash = Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $ProvenanceManifest -Algorithm SHA256
    Write-Output "APP_EXE_PATH=$PackagedExe"
    Write-Output "APP_EXE_SHA256=$($PackagedExeHash.Hash.ToLowerInvariant())"
    Write-Output "PROVENANCE_MANIFEST=$ProvenanceManifest"
    Write-Output "PROVENANCE_MANIFEST_SHA256=$($ProvenanceManifestHash.Hash.ToLowerInvariant())"

    if ($SkipInstaller) {
        Write-Output "INSTALLER_BUILD=SKIPPED"
        Write-Output "PACKAGED_APP_PATH=$PackagedExe"
        exit 0
    }

    if (-not $WebView2BootstrapperPath) {
        $WebView2BootstrapperPath = Join-Path $ReleaseRoot "tools\MicrosoftEdgeWebView2Setup.exe"
    }
    if (-not (Test-Path -LiteralPath $WebView2BootstrapperPath -PathType Leaf)) {
        throw "Microsoft WebView2 Evergreen Bootstrapper is missing: $WebView2BootstrapperPath"
    }
    $BootstrapperSignature = Get-AuthenticodeSignature -LiteralPath $WebView2BootstrapperPath
    if ($BootstrapperSignature.Status -ne "Valid" -or $BootstrapperSignature.SignerCertificate.Subject -notmatch "Microsoft Corporation") {
        throw "Microsoft WebView2 Evergreen Bootstrapper signature validation failed."
    }

    if (-not $InstallerExtractorPath) {
        $InstallerExtractorPath = Join-Path $ReleaseRoot "tools\innoextract670\innoextract.exe"
    }
    if (-not (Test-Path -LiteralPath $InstallerExtractorPath -PathType Leaf)) {
        throw "Inno Setup extractor is missing: $InstallerExtractorPath"
    }

    $InnoCandidates = @(
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1

    if (-not $InnoCandidates) {
        Write-Output "INNO_SETUP_AVAILABLE=NO"
        Write-Output "INSTALLER_SCRIPT_READY=YES"
        Write-Output "REQUIRED_TOOL=Inno Setup 6"
        Write-Output "PACKAGED_APP_PATH=$PackagedExe"
        exit 2
    }

    $ExpectedInstaller = Join-Path $InstallerOutput "$PackageBaseName.exe"
    if (Test-Path -LiteralPath $ExpectedInstaller) {
        throw "Final installer already exists and will not be overwritten: $ExpectedInstaller"
    }
    New-Item -ItemType Directory -Path $InstallerStaging | Out-Null
    $StagedInstaller = Join-Path $InstallerStaging "$PackageBaseName.exe"
    & $InnoCandidates "/DSourceDir=$PackagedAppTree" "/DOutputDir=$InstallerStaging" "/DProductVersion=$($Version.version)" "/DInstallerVersion=$InstallerVersion" "/DDisplayVersion=$($Version.display_version)" "/DPackageBaseName=$PackageBaseName" "/DWebView2Bootstrapper=$WebView2BootstrapperPath" $InstallerScript
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed with exit code $LASTEXITCODE. Staged output left at: $InstallerStaging" }

    if (-not (Test-Path -LiteralPath $StagedInstaller -PathType Leaf)) {
        throw "Installer build produced no expected Setup executable: $StagedInstaller"
    }
    $Installer = Get-Item -LiteralPath $StagedInstaller
    & $InstallerExtractorPath --extract --silent --output-dir $ExtractedInstallerRoot $Installer.FullName
    if ($LASTEXITCODE -ne 0) { throw "Installer content extraction failed with exit code $LASTEXITCODE." }

    $ExtractedAppTree = Join-Path $ExtractedInstallerRoot "app"
    & $Python $PackageDataGate --app-tree $ExtractedAppTree --project-root $ProjectRoot --manifest $ExtractedProvenanceManifest --pyinstaller-work (Join-Path $PyInstallerWork "HDDE")
    if ($LASTEXITCODE -ne 0) { throw "Extracted installer app tree PACKAGE_DATA_LEAK_GATE failed with exit code $LASTEXITCODE." }
    Assert-VcRuntimeVersion -AppTree $ExtractedAppTree -Label "installer"

    & $Python $InstallerDataGate --installer $Installer.FullName --extracted-root $ExtractedInstallerRoot --source-app-tree $PackagedAppTree --webview2-bootstrapper $WebView2BootstrapperPath --app-provenance $ProvenanceManifest --extracted-app-provenance $ExtractedProvenanceManifest --manifest $InstallerContentManifest
    if ($LASTEXITCODE -ne 0) { throw "Installer content data gate failed with exit code $LASTEXITCODE." }
    $SystemUtilityModule = Join-Path $PSHOME "Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1"
    Import-Module -Name $SystemUtilityModule -Force -ErrorAction Stop
    $Hash = Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $Installer.FullName -Algorithm SHA256

    # Publish: same-volume rename, so the release folder only ever sees a complete, gated file.
    New-Item -ItemType Directory -Force -Path $InstallerOutput | Out-Null
    if (Test-Path -LiteralPath $ExpectedInstaller) {
        throw "Final installer appeared during the build and will not be overwritten: $ExpectedInstaller"
    }
    Move-Item -LiteralPath $Installer.FullName -Destination $ExpectedInstaller
    $Installer = Get-Item -LiteralPath $ExpectedInstaller
    $PublishedHash = Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $Installer.FullName -Algorithm SHA256
    if ($PublishedHash.Hash -ne $Hash.Hash) {
        throw "Published installer hash differs from the gated staged file: $ExpectedInstaller"
    }
    Write-Output "INSTALLER_BUILD=PASS"
    Write-Output "PACKAGE_PATH=$($Installer.FullName)"
    Write-Output "PACKAGE_SIZE=$($Installer.Length)"
    Write-Output "PACKAGE_SHA256=$($Hash.Hash.ToLowerInvariant())"
    Write-Output "INSTALLER_CONTENT_MANIFEST=$InstallerContentManifest"
    Write-Output "INSTALLER_CONTENT_MANIFEST_SHA256=$((Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $InstallerContentManifest -Algorithm SHA256).Hash.ToLowerInvariant())"
    Write-Output "WEBVIEW2_BOOTSTRAPPER_SHA256=$((Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $WebView2BootstrapperPath -Algorithm SHA256).Hash.ToLowerInvariant())"
    Write-Output "WEBVIEW2_BUNDLED=YES"
}
finally {
    $env:HDDE_PACKAGING_FRONTEND_DIR = $PreviousFrontendDist
    Pop-Location
}

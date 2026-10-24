[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $InstallerPath,
    [Parameter(Mandatory = $true)][string] $UnpackedPath,
    [Parameter(Mandatory = $true)][string] $EvidenceDirectory,
    [switch] $AllowUnsignedTest
)
if (-not $AllowUnsignedTest) { throw 'Explicit unsigned preflight opt-in required; this is not the signed release gate.' }
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Windows required.' }
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$version = (Get-Content -LiteralPath (Join-Path $project 'VERSION') -Raw).Trim()
$evidence = [IO.Path]::GetFullPath($EvidenceDirectory)
if (Test-Path -LiteralPath $evidence) { throw 'A fresh evidence directory is required.' }
[IO.Directory]::CreateDirectory($evidence) | Out-Null
$installerSource = (Get-Item -LiteralPath $InstallerPath).FullName
$unpacked = (Get-Item -LiteralPath $UnpackedPath).FullName
$installer = Join-Path $evidence ('Nerkhbaan-' + $version + '-win-x64-UNSIGNED.exe')
if ((Get-Item -LiteralPath $installerSource).VersionInfo.ProductVersion -ne $version) { throw 'Candidate product version does not match source version.' }
$rootTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$ownerId = [Guid]::NewGuid().ToString('N')
$ownedRoot = Join-Path $rootTemp ('nerkhbaan-installed-acceptance-' + $ownerId)
$installPath = Join-Path $ownedRoot 'app'
$marker = Join-Path $ownedRoot 'acceptance-owner.json'
$receiptPath = Join-Path $evidence 'unsigned-installer-acceptance.json'
$registryRoots = @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')
function Get-ProductInstallations {
    $result = @()
    foreach ($registryRoot in $registryRoots) {
        foreach ($key in Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue) {
            $value = Get-ItemProperty -LiteralPath $key.PSPath
            if ($value.DisplayName -match '^Nerkhbaan') {
                $location = $value.InstallLocation
                if ([string]::IsNullOrWhiteSpace($location) -and $value.UninstallString -match '^"([^"]+)"') {
                    $location = [IO.Path]::GetDirectoryName($Matches[1])
                }
                $result += [pscustomobject]@{ key = $key.PSPath; key_name = $key.PSChildName; install_location = $location; display_version = $value.DisplayVersion }
            }
        }
    }
    return $result
}
function Assert-OwnedPath([string] $target) {
    $resolved = [IO.Path]::GetFullPath($target)
    $base = [IO.Path]::GetFullPath($ownedRoot)
    if (-not $base.StartsWith($rootTemp, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($base) -ne ('nerkhbaan-installed-acceptance-' + $ownerId)) { throw 'Owned test root escaped temporary directory.' }
    if ($resolved -ne $base -and -not $resolved.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Target escaped owned test root.' }
    if (-not (Test-Path -LiteralPath $marker)) { throw 'Test ownership marker missing.' }
    $owner = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($owner.id -ne $ownerId -or $owner.root -ne $ownedRoot) { throw 'Test ownership marker mismatch.' }
    if ((Get-Item -LiteralPath $ownedRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Owned root must not be a reparse point.' }
}
$before = @(Get-ProductInstallations)
$defaultProfile = Join-Path $env:APPDATA 'Nerkhbaan'
function Get-ProfileFingerprint {
    if (-not (Test-Path -LiteralPath $defaultProfile)) { return 'absent' }
    $records = @(Get-ChildItem -LiteralPath $defaultProfile -File -Recurse | Sort-Object FullName | ForEach-Object {
        if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Profile contains a reparse point; preserve and stop.' }
        $_.FullName.Substring($defaultProfile.Length) + ':' + (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    })
    $bytes = [Text.Encoding]::UTF8.GetBytes(($records -join "`n"))
    return [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes))
}
$defaultProfileBefore = Test-Path -LiteralPath $defaultProfile
$profileFingerprintBefore = Get-ProfileFingerprint
if (Test-Path -LiteralPath $receiptPath) { throw 'Receipt already exists; no repeated installation.' }
$receiptStream = [IO.File]::Open($receiptPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
$initialReceipt = [Text.UTF8Encoding]::new($false).GetBytes('{"accepted_unsigned_install":false,"state":"started"}')
$receiptStream.Write($initialReceipt, 0, $initialReceipt.Length)
$receiptStream.Flush()
if ($before.Count -ne 0 -or @(Get-Process -Name Nerkhbaan -ErrorAction SilentlyContinue).Count -ne 0) { throw 'Existing installation or running product must be preserved; isolated machine required.' }
if (Test-Path -LiteralPath $ownedRoot) { throw 'Owned test root already exists.' }
Copy-Item -LiteralPath $installerSource -Destination $installer
[IO.Directory]::CreateDirectory($ownedRoot) | Out-Null
@{ id = $ownerId; root = $ownedRoot } | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding utf8
$receipt = [ordered]@{ schema = 1; version = $version; started_at_utc = [DateTime]::UtcNow.ToString('o'); scope = 'Actual unsigned Windows x64 NSIS per-user install/runtime/uninstall, own temporary install and profile; no trusted publisher signature'; source_commit = (& git -C $project rev-parse HEAD).Trim(); source_worktree_modified = [bool]((& git -C $project status --porcelain --untracked-files=no) -join ''); owner_id = $ownerId; installer = [IO.Path]::GetFileName($installer); installer_sha256 = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant(); existing_installations_before = $before.Count; default_profile_existed_before = $defaultProfileBefore; signed_acceptance = $false; runtime_passed = $false; install_passed = $false; uninstall_passed = $false; cleanup_passed = $false }
$uninstaller = Join-Path $installPath 'Uninstall Nerkhbaan.exe'
try {
    Assert-OwnedPath $installPath
    $process = Start-Process -FilePath $installer -ArgumentList @('/S', '/currentuser', ('/D=' + $installPath)) -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) { throw 'Owned installer did not finish within sixty seconds.' }
    if ($process.ExitCode -ne 0) { throw 'Owned installer returned failure.' }
    $executable = Join-Path $installPath 'Nerkhbaan.exe'
    if (-not (Test-Path -LiteralPath $executable) -or -not (Test-Path -LiteralPath $uninstaller)) { throw 'Installed program or uninstaller missing.' }
    $installed = @(Get-ProductInstallations)
    if ($installed.Count -ne 1 -or [IO.Path]::GetFullPath($installed[0].install_location).TrimEnd('\') -ne $installPath.TrimEnd('\') -or $installed[0].display_version -ne $version) { throw 'Installed registry does not match owned test.' }
    $receipt.registry_key = $installed[0].key_name
    $receipt.install_passed = $true
    $receipt.installer_exit_code = $process.ExitCode
    $receipt.artifacts = @()
    foreach ($file in @($installer, $executable, $uninstaller)) {
        $info = Get-Item -LiteralPath $file
        $signature = Get-AuthenticodeSignature -LiteralPath $info.FullName
        $receipt.artifacts += @{ file = $info.Name; bytes = $info.Length; sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant(); signature_status = $signature.Status.ToString(); product_version = $info.VersionInfo.ProductVersion; company_name = $info.VersionInfo.CompanyName; timestamp_present = $null -ne $signature.TimeStamperCertificate }
    }
    $receipt.installed_executable_matches_candidate = (Get-FileHash -LiteralPath $executable).Hash -eq (Get-FileHash -LiteralPath (Join-Path $unpacked 'Nerkhbaan.exe')).Hash
    if (-not $receipt.installed_executable_matches_candidate) { throw 'Installed executable differs from candidate.' }
    $receipt.installed_archive_matches_candidate = (Get-FileHash -LiteralPath (Join-Path $installPath 'resources\app.asar')).Hash -eq (Get-FileHash -LiteralPath (Join-Path $unpacked 'resources\app.asar')).Hash
    if (-not $receipt.installed_archive_matches_candidate) { throw 'Installed archive differs from candidate.' }
    $env:NERKHBAAN_DESKTOP_EXECUTABLE = $executable
    $env:NERKHBAAN_DESKTOP_SMOKE_RECEIPT = Join-Path $evidence 'unsigned-installed-runtime.json'
    $node = (Get-Command node.exe).Source
    $runtimeInfo = [Diagnostics.ProcessStartInfo]::new($node, 'scripts/desktop-smoke.mjs')
    $runtimeInfo.WorkingDirectory = $project
    $runtimeInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $runtimeInfo.CreateNoWindow = $true
    $runtimeInfo.UseShellExecute = $false
    $runtimeInfo.RedirectStandardOutput = $true
    $runtimeInfo.RedirectStandardError = $true
    $runtime = [Diagnostics.Process]::new()
    $runtime.StartInfo = $runtimeInfo
    $runtime.Start() | Out-Null
    $runtimeOut = $runtime.StandardOutput.ReadToEndAsync()
    $runtimeError = $runtime.StandardError.ReadToEndAsync()
    if (-not $runtime.WaitForExit(120000)) { throw 'Owned runtime acceptance did not finish within sixty seconds.' }
    [IO.File]::WriteAllText((Join-Path $evidence 'unsigned-installed-runtime.log'), $runtimeOut.GetAwaiter().GetResult())
    [IO.File]::WriteAllText((Join-Path $evidence 'unsigned-installed-runtime.stderr.log'), $runtimeError.GetAwaiter().GetResult())
    $receipt.runtime_exit_code = $runtime.ExitCode
    if ($runtime.ExitCode -ne 0) { throw 'Owned installed runtime acceptance failed.' }
    $runtimeRecord = Get-Content -LiteralPath $env:NERKHBAAN_DESKTOP_SMOKE_RECEIPT -Raw | ConvertFrom-Json
    if (-not $runtimeRecord.passed -or -not $runtimeRecord.isolated_profile_removed) { throw 'Installed runtime or profile cleanup did not pass.' }
    $receipt.runtime_passed = $true
} catch {
    $receipt.failure = $_.Exception.Message
} finally {
    Remove-Item Env:\NERKHBAAN_DESKTOP_EXECUTABLE -ErrorAction SilentlyContinue
    Remove-Item Env:\NERKHBAAN_DESKTOP_SMOKE_RECEIPT -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $uninstaller) {
        Assert-OwnedPath $uninstaller
        $removeProcess = Start-Process -FilePath $uninstaller -ArgumentList @('/S', '/currentuser') -WindowStyle Hidden -PassThru
        $uninstallerExited = $removeProcess.WaitForExit(60000)
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        while (((Test-Path -LiteralPath $installPath) -or @(Get-ProductInstallations).Count -gt 0) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 100 }
        $receipt.uninstaller_exit_code = if ($uninstallerExited) { $removeProcess.ExitCode } else { $null }
        $receipt.install_directory_removed = -not (Test-Path -LiteralPath $installPath)
        $receipt.existing_installations_after = @(Get-ProductInstallations).Count
        $receipt.application_registry_key_removed = -not (Test-Path -LiteralPath ('HKCU:\Software\' + $receipt.registry_key))
        $receipt.uninstall_passed = $uninstallerExited -and $removeProcess.ExitCode -eq 0 -and $receipt.install_directory_removed -and $receipt.existing_installations_after -eq 0 -and $receipt.application_registry_key_removed
    }
    $receipt.default_profile_preserved = ((Test-Path -LiteralPath $defaultProfile) -eq $defaultProfileBefore) -and ((Get-ProfileFingerprint) -eq $profileFingerprintBefore)
    if ($receipt.uninstall_passed) {
        Assert-OwnedPath $ownedRoot
        Remove-Item -LiteralPath $ownedRoot -Recurse -Force
        $receipt.owned_root_removed = -not (Test-Path -LiteralPath $ownedRoot)
        $receipt.cleanup_passed = $receipt.owned_root_removed -and $receipt.default_profile_preserved
    }
    $receipt.completed_at_utc = [DateTime]::UtcNow.ToString('o')
    $receipt.accepted_unsigned_install = $receipt.install_passed -and $receipt.runtime_passed -and $receipt.uninstall_passed -and $receipt.cleanup_passed
    $receipt.installer_unchanged = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -eq $receipt.installer_sha256
    $receipt.accepted_unsigned_install = $receipt.accepted_unsigned_install -and $receipt.installer_unchanged
    $receiptBytes = [Text.UTF8Encoding]::new($false).GetBytes(($receipt | ConvertTo-Json -Depth 6))
    $receiptStream.Position = 0
    $receiptStream.SetLength(0)
    $receiptStream.Write($receiptBytes, 0, $receiptBytes.Length)
    $receiptStream.Flush()
    $receiptStream.Dispose()
    [pscustomobject]@{ accepted_unsigned_install = $receipt.accepted_unsigned_install; install_passed = $receipt.install_passed; runtime_passed = $receipt.runtime_passed; uninstall_passed = $receipt.uninstall_passed; cleanup_passed = $receipt.cleanup_passed; signed_acceptance = $false; receipt = $receiptPath } | ConvertTo-Json
}
if (-not $receipt.accepted_unsigned_install) { exit 1 }
exit 0

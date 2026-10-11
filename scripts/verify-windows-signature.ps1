[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string[]] $ArtifactPath,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $ExpectedPublisher,
    [ValidatePattern('^([A-Fa-f0-9]{40})?$')]
    [string] $ExpectedSignerThumbprint = '',
    [string] $ReceiptPath = ''
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Windows signature verification requires Windows.'
}

$records = @()
foreach ($artifact in $ArtifactPath) {
    $file = Get-Item -LiteralPath $artifact
    if ($file.PSIsContainer) { throw 'Each artifact must be a file.' }
    $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
    $certificate = $signature.SignerCertificate
    $timestamp = $signature.TimeStamperCertificate
    $hasSigningEku = $false
    if ($null -ne $certificate) {
        foreach ($extension in $certificate.Extensions) {
            if ($extension.Oid.Value -eq '2.5.29.37') {
                $hasSigningEku = @($extension.EnhancedKeyUsages | Where-Object { $_.Value -eq '1.3.6.1.5.5.7.3.3' }).Count -gt 0
            }
        }
    }
    $publisherMatches = $null -ne $certificate -and [string]::Equals(
        $certificate.Subject, $ExpectedPublisher, [StringComparison]::OrdinalIgnoreCase)
    $thumbprintMatches = [string]::IsNullOrWhiteSpace($ExpectedSignerThumbprint) -or (
        $null -ne $certificate -and [string]::Equals(
            $certificate.Thumbprint, $ExpectedSignerThumbprint, [StringComparison]::OrdinalIgnoreCase))
    $selfSignedLeaf = $null -ne $certificate -and $certificate.Subject -eq $certificate.Issuer
    $accepted = $signature.Status -eq 'Valid' -and $signature.SignatureType -eq 'Authenticode' -and (
        $publisherMatches -and $thumbprintMatches -and $hasSigningEku -and $null -ne $timestamp -and -not $selfSignedLeaf)
    $records += [pscustomobject]@{
        file = $file.Name
        bytes = $file.Length
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        signature_status = $signature.Status.ToString()
        signature_type = $signature.SignatureType.ToString()
        signer_subject = if ($certificate) { $certificate.Subject } else { $null }
        signer_issuer = if ($certificate) { $certificate.Issuer } else { $null }
        signer_thumbprint = if ($certificate) { $certificate.Thumbprint } else { $null }
        timestamp_present = $null -ne $timestamp
        timestamp_subject = if ($timestamp) { $timestamp.Subject } else { $null }
        publisher_matches = $publisherMatches
        thumbprint_matches = $thumbprintMatches
        code_signing_eku = $hasSigningEku
        self_signed_leaf = $selfSignedLeaf
        accepted = $accepted
    }
}

$receipt = [pscustomobject]@{
    schema = 1
    checked_at_utc = [DateTime]::UtcNow.ToString('o')
    scope = 'Windows Authenticode trust on this verification host; no claim about every host or SmartScreen reputation'
    expected_publisher = $ExpectedPublisher
    expected_signer_thumbprint = $ExpectedSignerThumbprint
    artifacts = $records
    accepted = @($records | Where-Object { -not $_.accepted }).Count -eq 0
}
$json = $receipt | ConvertTo-Json -Depth 6
if (-not [string]::IsNullOrWhiteSpace($ReceiptPath)) {
    $resolvedReceipt = [IO.Path]::GetFullPath($ReceiptPath)
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($resolvedReceipt)) | Out-Null
    [IO.File]::WriteAllText($resolvedReceipt, $json, [Text.UTF8Encoding]::new($false))
}
Write-Output $json
if (-not $receipt.accepted) { exit 1 }

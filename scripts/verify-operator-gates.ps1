param(
    [Parameter(Mandatory = $true)]
    [string]$EvidencePath
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $EvidencePath -PathType Leaf)) {
    throw "Evidence file not found: $EvidencePath"
}

$raw = Get-Content -LiteralPath $EvidencePath -Raw
$evidence = $raw | ConvertFrom-Json
$rules = [ordered]@{
    provider_rights_signoff      = @{ MaxAgeDays = 365; AllowNotApplicable = $false }
    provider_live_canary_schedule = @{ MaxAgeDays = 7; AllowNotApplicable = $false }
    secret_manager_activation    = @{ MaxAgeDays = 90; AllowNotApplicable = $false }
    navasan_transport_signoff    = @{ MaxAgeDays = 90; AllowNotApplicable = $true }
    brsapi_tsetmc_future_domain  = @{ MaxAgeDays = 365; AllowNotApplicable = $true }
    production_restore_proof     = @{ MaxAgeDays = 90; AllowNotApplicable = $false }
    production_deployment_proof  = @{ MaxAgeDays = 7; AllowNotApplicable = $false }
    browser_smoke_proof          = @{ MaxAgeDays = 7; AllowNotApplicable = $false }
}

$errors = @()
if ($evidence.schema_version -ne 1) {
    $errors += "schema_version: must be 1"
}
if ($evidence.environment -ne "production") {
    $errors += "environment: must be production"
}

$now = [DateTimeOffset]::UtcNow
foreach ($name in $rules.Keys) {
    $rule = $rules[$name]
    $gate = $evidence.$name
    if ($null -eq $gate) {
        $errors += "${name}: missing"
        continue
    }
    if ($gate.status -ne "passed" -and $gate.status -ne "not_applicable") {
        $errors += "${name}: status must be passed or not_applicable"
    }
    if ($gate.status -eq "not_applicable" -and -not $rule.AllowNotApplicable) {
        $errors += "${name}: this production gate cannot be not_applicable"
    }
    if ($gate.status -eq "not_applicable" -and [string]::IsNullOrWhiteSpace($gate.reason)) {
        $errors += "${name}: not_applicable needs reason"
    }
    if ([string]::IsNullOrWhiteSpace($gate.owner) -or $gate.owner -match '^(owner|team|example|unknown|tbd)$') {
        $errors += "${name}: real owner missing"
    }
    if ([string]::IsNullOrWhiteSpace($gate.evidence_ref) -or $gate.evidence_ref -notmatch '^[a-z][a-z0-9+.-]*://[^\s]+$') {
        $errors += "${name}: evidence_ref must be one typed URI with no spaces"
    }
    try {
        $checkedAt = [DateTimeOffset]::Parse(
            [string]$gate.checked_at,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::AssumeUniversal
        ).ToUniversalTime()
        if ($checkedAt -gt $now.AddMinutes(5)) {
            $errors += "${name}: checked_at is in the future"
        }
        if ($checkedAt -lt $now.AddDays(-[int]$rule.MaxAgeDays)) {
            $errors += "${name}: evidence is too old"
        }
    }
    catch {
        $errors += "${name}: checked_at must be a valid UTC timestamp"
    }
}

$serialized = $evidence | ConvertTo-Json -Depth 8 -Compress
$secretPatterns = @(
    "sk-[A-Za-z0-9]",
    "Bearer\s+[A-Za-z0-9]{16,}",
    "api[_-]?key[=:]\s*[A-Za-z0-9]{8,}",
    "password[=:]\s*[^,\s`"]{8,}",
    "BEGIN (RSA|OPENSSH|PRIVATE KEY)"
)
foreach ($pattern in $secretPatterns) {
    if ($serialized -match $pattern) {
        $errors += "evidence contains secret-like value"
        break
    }
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { [Console]::Error.WriteLine($_) }
    exit 1
}

Write-Output "operator gates evidence valid"

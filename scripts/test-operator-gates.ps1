$ErrorActionPreference = "Stop"

$checkedAt = [DateTimeOffset]::UtcNow.ToString("o")
$gate = {
    param([string]$Owner, [string]$Reference)
    return [ordered]@{
        status = "passed"
        owner = $Owner
        checked_at = $checkedAt
        evidence_ref = $Reference
    }
}
$evidence = [ordered]@{
    schema_version = 1
    environment = "production"
    provider_rights_signoff = & $gate "pricing-ops" "ticket://pricing-rights/123"
    provider_live_canary_schedule = & $gate "pricing-ops" "monitor://provider-canary/123"
    secret_manager_activation = & $gate "platform-ops" "vault-policy://nerkhbaan/prod"
    navasan_transport_signoff = & $gate "pricing-ops" "config://navasan/https-proxy"
    brsapi_tsetmc_future_domain = & $gate "product-ops" "backlog://market-domain/123"
    production_restore_proof = & $gate "platform-ops" "drill://database-restore/123"
    production_deployment_proof = & $gate "platform-ops" "deploy://nerkhbaan/123"
    browser_smoke_proof = & $gate "qa-ops" "smoke://browser/123"
}

$testPath = Join-Path ([IO.Path]::GetTempPath()) "nerkhbaan-operator-gates-$([Guid]::NewGuid().ToString('N')).json"
try {
    $evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $testPath -Encoding UTF8
    & "$PSScriptRoot\verify-operator-gates.ps1" -EvidencePath $testPath
}
finally {
    Remove-Item -LiteralPath $testPath -Force -ErrorAction SilentlyContinue
}

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'cloudflare-demo-common.ps1')
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location -LiteralPath $projectRoot
try {
    # Stop only the tunnel; never use compose down or remove any data volumes.
    Invoke-DemoCompose -ComposeArgs @('--profile', 'cloudflare-demo', 'stop', 'cloudflared')
    Assert-DemoRestartSafe
    Invoke-DemoCompose -ComposeArgs @('-f', 'docker-compose.yml', 'up', '-d', '--no-deps', '--wait', '--wait-timeout', '45', 'backend')
    Write-Host 'Tunnel stopped. Backend restored to root .env settings; all database data is retained.'
    Write-Host 'Open http://localhost:5173. Replace demo-origin invitation links before reuse locally.'
} finally {
    Pop-Location
}

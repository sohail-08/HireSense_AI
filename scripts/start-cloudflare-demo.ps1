[CmdletBinding()]
param([switch]$UrlOnly)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'cloudflare-demo-common.ps1')
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location -LiteralPath $projectRoot
try {
    $health = Invoke-WebRequest -Uri 'http://localhost:5173/api/health' -TimeoutSec 5 -UseBasicParsing
    if ($health.StatusCode -ne 200) { throw 'Start the local application before opening a demo tunnel.' }
    if (-not $UrlOnly) { Assert-DemoRestartSafe }
    Write-Host 'Starting a temporary public website tunnel. Use synthetic demo data; media remains self-hosted.'
    Invoke-DemoCompose -ComposeArgs @('--profile', 'cloudflare-demo', 'up', '-d', '--no-deps', 'cloudflared')
    $origin = Wait-DemoTunnel -ControlAddress (Get-DemoControlAddress)
    if (-not $UrlOnly) {
        Enable-DemoOrigin -PublicUrl $origin
        Write-Host 'Public origin and secure candidate cookies configured. Root .env was not changed.'
    } else {
        Write-Host 'URL discovery only; backend public-origin configuration has not been applied.'
    }
    Write-Host 'Keep Docker and the laptop running. Quick Tunnel URLs change when recreated.'
    Write-Host 'Existing localhost invitations need Replace link before sharing. No emails are sent automatically.'
    Write-Warning 'Website-only demo: Cloudflare does not expose LiveKit audio/video. Remote media needs separate networking.'
    Write-Output ([PSCustomObject]@{ PublicUrl = $origin; BackendConfigured = (-not $UrlOnly); RemoteMediaReady = $false })
} finally {
    Pop-Location
}

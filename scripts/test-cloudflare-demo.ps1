$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'cloudflare-demo-common.ps1')

function Assert-DemoTest {
    param([bool]$Condition, [string]$Description)
    if (-not $Condition) { throw ('Test failed: ' + $Description) }
}

Assert-DemoTest ((Get-ValidatedDemoOrigin 'demo-name.trycloudflare.com') -eq 'https://demo-name.trycloudflare.com') 'hostname normalized'
Assert-DemoTest ((Get-ValidatedDemoOrigin 'https://demo-name.trycloudflare.com/') -eq 'https://demo-name.trycloudflare.com') 'HTTPS origin normalized'
foreach ($inputValue in @('http://demo.trycloudflare.com', 'https://evil.example',
    'https://demo.trycloudflare.com/path', 'https://demo.trycloudflare.com?token=fake',
    'https://user:fake@demo.trycloudflare.com', 'https://demo.trycloudflare.com:8443')) {
    $rejected = $false
    try { $null = Get-ValidatedDemoOrigin $inputValue } catch { $rejected = $true }
    Assert-DemoTest $rejected 'unexpected origins rejected'
}

# Mock Docker: this script never creates a tunnel, restarts a service or reads secrets.
$script:demoCalls = @()
$script:demoFail = $false
$script:safetyStatus = [PSCustomObject]@{ active_rooms = 0; pending_email = 0 }
function Get-DemoSafetyStatus { return $script:safetyStatus }
function Invoke-DemoCompose {
    param([string[]]$ComposeArgs)
    $script:demoCalls += [PSCustomObject]@{ Arguments = $ComposeArgs; Origin = $env:DEMO_PUBLIC_URL }
    if ($script:demoFail) { throw 'Synthetic Docker failure' }
}
$before = [Environment]::GetEnvironmentVariable('DEMO_PUBLIC_URL', 'Process')
try {
    [Environment]::SetEnvironmentVariable('DEMO_PUBLIC_URL', 'original-test-value', 'Process')
    Enable-DemoOrigin 'https://demo-name.trycloudflare.com'
    Assert-DemoTest ($script:demoCalls[0].Origin -eq 'https://demo-name.trycloudflare.com') 'origin scoped to Compose'
    Assert-DemoTest ($script:demoCalls[0].Arguments -contains 'docker-compose.cloudflare.yml') 'demo overlay selected'
    Assert-DemoTest ($script:demoCalls[0].Arguments -contains '--no-deps') 'no unrelated service restart'
    Assert-DemoTest ($env:DEMO_PUBLIC_URL -eq 'original-test-value') 'process override restored'
    $script:demoFail = $true
    $failed = $false
    try { Enable-DemoOrigin 'demo-name.trycloudflare.com' } catch { $failed = $true }
    Assert-DemoTest $failed 'failure surfaced'
    Assert-DemoTest ($env:DEMO_PUBLIC_URL -eq 'original-test-value') 'override restored after failure'
    $script:demoFail = $false
    $script:safetyStatus.active_rooms = 1
    $blocked = $false
    try { Enable-DemoOrigin 'demo-name.trycloudflare.com' } catch { $blocked = $true }
    Assert-DemoTest $blocked 'active interviews prevent restart'
    $script:safetyStatus.active_rooms = 0; $script:safetyStatus.pending_email = 1
    $blocked = $false
    try { Enable-DemoOrigin 'demo-name.trycloudflare.com' } catch { $blocked = $true }
    Assert-DemoTest $blocked 'pending email prevents restart'
} finally {
    [Environment]::SetEnvironmentVariable('DEMO_PUBLIC_URL', $before, 'Process')
}
Write-Output 'Cloudflare helper checks passed (origin validation, scoped configuration, rollback, and restart safeguards).'

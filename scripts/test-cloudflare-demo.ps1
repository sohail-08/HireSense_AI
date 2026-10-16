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
$script:demoFailFrontend = $false
$script:demoHealthChecks = 0
$script:safetyStatus = [PSCustomObject]@{ active_rooms = 0; pending_email = 0 }
function Get-DemoSafetyStatus { return $script:safetyStatus }
function Invoke-DemoCompose {
    param([string[]]$ComposeArgs)
    $script:demoCalls += [PSCustomObject]@{ Arguments = $ComposeArgs; Origin = $env:DEMO_PUBLIC_URL }
    if ($script:demoFail) { throw 'Synthetic Docker failure' }
    if ($script:demoFailFrontend -and $ComposeArgs[-1] -eq 'frontend') { throw 'Synthetic frontend failure' }
}
function Wait-DemoWebsite { $script:demoHealthChecks += 1 }
$before = [Environment]::GetEnvironmentVariable('DEMO_PUBLIC_URL', 'Process')
try {
    [Environment]::SetEnvironmentVariable('DEMO_PUBLIC_URL', 'original-test-value', 'Process')
    Enable-DemoOrigin 'https://demo-name.trycloudflare.com'
    Assert-DemoTest ($script:demoCalls[0].Origin -eq 'https://demo-name.trycloudflare.com') 'origin scoped to Compose'
    Assert-DemoTest ($script:demoCalls[0].Arguments -contains 'docker-compose.cloudflare.yml') 'demo overlay selected'
    Assert-DemoTest ($script:demoCalls[0].Arguments -contains '--no-deps') 'no unrelated service restart'
    Assert-DemoTest ($script:demoCalls[0].Arguments[-1] -eq 'backend') 'backend restarted first'
    Assert-DemoTest ($script:demoCalls[1].Arguments[-1] -eq 'frontend') 'frontend refreshed after backend'
    Assert-DemoTest ($script:demoCalls[1].Arguments -contains '--force-recreate') 'frontend assets and proxy refreshed'
    Assert-DemoTest ($script:demoCalls[1].Arguments -contains 'docker-compose.cloudflare.yml') 'frontend refresh preserves public overlay'
    Assert-DemoTest ($script:demoHealthChecks -eq 1) 'website API health verified'
    Assert-DemoTest ($env:DEMO_PUBLIC_URL -eq 'original-test-value') 'process override restored'
    $script:demoFail = $true
    $failed = $false
    try { Enable-DemoOrigin 'demo-name.trycloudflare.com' } catch { $failed = $true }
    Assert-DemoTest $failed 'failure surfaced'
    Assert-DemoTest ($env:DEMO_PUBLIC_URL -eq 'original-test-value') 'override restored after failure'
    $script:demoFail = $false
    $script:demoFailFrontend = $true
    $failed = $false
    try { Enable-DemoOrigin 'demo-name.trycloudflare.com' } catch { $failed = $true }
    Assert-DemoTest $failed 'frontend failure surfaced'
    Assert-DemoTest ($env:DEMO_PUBLIC_URL -eq 'original-test-value') 'override restored after frontend failure'
    Assert-DemoTest ($script:demoHealthChecks -eq 1) 'failed frontend cannot be reported healthy'
    $script:demoFailFrontend = $false
    $script:demoCalls = @()
    Restore-DemoLocalOrigin
    Assert-DemoTest ($script:demoCalls.Count -eq 2) 'localhost restore refreshes both web services'
    Assert-DemoTest ($script:demoCalls[0].Arguments -notcontains 'docker-compose.cloudflare.yml') 'localhost restore removes overlay'
    Assert-DemoTest ($script:demoCalls[1].Arguments[-1] -eq 'frontend') 'localhost proxy refreshed'
    Assert-DemoTest ($script:demoHealthChecks -eq 2) 'localhost restore checks website health'
    $script:demoCalls = @()
    $script:safetyStatus.active_rooms = 1
    $blocked = $false
    try { Enable-DemoOrigin 'demo-name.trycloudflare.com' } catch { $blocked = $true }
    Assert-DemoTest $blocked 'active interviews prevent restart'
    Assert-DemoTest ($script:demoCalls.Count -eq 0) 'active-room block prevents all web restarts'
    $script:safetyStatus.active_rooms = 0; $script:safetyStatus.pending_email = 1
    $blocked = $false
    try { Enable-DemoOrigin 'demo-name.trycloudflare.com' } catch { $blocked = $true }
    Assert-DemoTest $blocked 'pending email prevents restart'
    $blocked = $false
    try { Restore-DemoLocalOrigin } catch { $blocked = $true }
    Assert-DemoTest $blocked 'localhost restore also guards pending email'
} finally {
    [Environment]::SetEnvironmentVariable('DEMO_PUBLIC_URL', $before, 'Process')
}
Write-Output 'Cloudflare helper checks passed (origin validation, scoped configuration, rollback, and restart safeguards).'

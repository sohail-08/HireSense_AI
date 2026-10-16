Set-StrictMode -Version Latest

function Invoke-DemoCompose {
    param([string[]]$ComposeArgs)
    & docker compose @ComposeArgs
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose failed. Check Docker Desktop and service health.' }
}

function Get-ValidatedDemoOrigin {
    param([Parameter(Mandatory)][string]$Hostname)
    $value = $Hostname.Trim()
    if ($value -notmatch '^https://') { $value = 'https://' + $value }
    $uri = $null
    if (-not [Uri]::TryCreate($value, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -ne 'https' -or -not $uri.IsDefaultPort -or
        $uri.Host -notmatch '^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.trycloudflare\.com$' -or
        $uri.AbsolutePath -ne '/' -or $uri.Query -or $uri.Fragment -or $uri.UserInfo) {
        throw 'The local tunnel returned an unexpected public hostname.'
    }
    return $uri.GetLeftPart([UriPartial]::Authority)
}

function Get-DemoControlAddress {
    $address = (& docker compose port cloudflared 2000 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $address -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw 'Cloudflare local control port is unavailable. Check the demo service.'
    }
    return 'http://' + $address
}

function Wait-DemoTunnel {
    param([Parameter(Mandatory)][string]$ControlAddress)
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $ready = Invoke-WebRequest -Uri ($ControlAddress + '/ready') -TimeoutSec 3 -UseBasicParsing
            $metadata = Invoke-RestMethod -Uri ($ControlAddress + '/quicktunnel') -TimeoutSec 3
            if ($ready.StatusCode -eq 200 -and $metadata.hostname) {
                return Get-ValidatedDemoOrigin -Hostname $metadata.hostname
            }
        } catch {
            # Retry startup without logging request diagnostics or invitation URLs.
        }
        Start-Sleep -Seconds 1
    }
    throw 'Tunnel not ready. Verify outbound TCP port 7844 and DNS connectivity, then retry.'
}

function Enable-DemoOrigin {
    param([Parameter(Mandatory)][string]$PublicUrl)
    $origin = Get-ValidatedDemoOrigin -Hostname $PublicUrl
    Assert-DemoRestartSafe
    $previous = [Environment]::GetEnvironmentVariable('DEMO_PUBLIC_URL', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('DEMO_PUBLIC_URL', $origin, 'Process')
        Restart-DemoWebApp -ComposeFiles @('docker-compose.yml', 'docker-compose.cloudflare.yml')
    } finally {
        [Environment]::SetEnvironmentVariable('DEMO_PUBLIC_URL', $previous, 'Process')
    }
}

function Wait-DemoWebsite {
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-WebRequest -Uri 'http://localhost:5173/api/health' -TimeoutSec 3 -UseBasicParsing
            if ($health.StatusCode -eq 200) { return }
        } catch {
            # Bound retries while Nginx/Docker DNS settle; never log private URLs.
        }
        Start-Sleep -Seconds 1
    }
    throw 'Website API health check failed after restart. Check frontend/backend service health.'
}

function Restart-DemoWebApp {
    param([string[]]$ComposeFiles = @('docker-compose.yml'))
    Assert-DemoRestartSafe
    $arguments = @()
    foreach ($file in $ComposeFiles) { $arguments += @('-f', $file) }
    Invoke-DemoCompose -ComposeArgs ($arguments + @('up', '-d', '--no-deps', '--wait', '--wait-timeout', '45', 'backend'))
    # Refresh built assets and Nginx after replacing the backend. Database/MCP
    # services are untouched; dynamic Docker DNS also handles later IP changes.
    Invoke-DemoCompose -ComposeArgs ($arguments + @('up', '-d', '--no-deps', '--force-recreate', 'frontend'))
    Wait-DemoWebsite
}

function Restore-DemoLocalOrigin {
    Restart-DemoWebApp
}

function Get-DemoSafetyStatus {
    $code = "import json; from app.database import SessionLocal; from app.models.interview import InterviewSchedule,InterviewDelivery; from sqlalchemy import select,func; db=SessionLocal(); room_busy=InterviewSchedule.room_status.in_(['ready','active','ending']) | (InterviewSchedule.interviewer_joined_at.is_not(None) & InterviewSchedule.room_status.not_in(['ended','cancelled']) & InterviewSchedule.status.in_(['scheduled','rescheduled'])); print(json.dumps({'active_rooms':db.scalar(select(func.count()).select_from(InterviewSchedule).where(room_busy)),'pending_email':db.scalar(select(func.count()).select_from(InterviewDelivery).where((InterviewDelivery.status=='pending') | InterviewDelivery.in_flight))})); db.close()"
    $result = (& docker compose exec -T backend python -c $code | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Unable to check whether the backend can be safely restarted.' }
    return $result | ConvertFrom-Json
}

function Assert-DemoRestartSafe {
    $status = Get-DemoSafetyStatus
    if ($status.active_rooms -gt 0 -or $status.pending_email -gt 0) {
        throw 'Finish/end joined or active interviews and resolve pending email deliveries before changing demo mode.'
    }
}

function Get-DemoMediaStatus {
    $result = (& docker compose exec -T backend python -m app.check_livekit --check-api | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Unable to check LiveKit configuration. Check backend service health.' }
    return $result | ConvertFrom-Json
}

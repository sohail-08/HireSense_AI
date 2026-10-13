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
        Invoke-DemoCompose -ComposeArgs @('-f', 'docker-compose.yml', '-f', 'docker-compose.cloudflare.yml',
            'up', '-d', '--no-deps', '--wait', '--wait-timeout', '45', 'backend')
    } finally {
        [Environment]::SetEnvironmentVariable('DEMO_PUBLIC_URL', $previous, 'Process')
    }
}

function Get-DemoSafetyStatus {
    $code = "import json; from app.database import SessionLocal; from app.models.interview import InterviewSchedule,InterviewDelivery; from sqlalchemy import select,func; db=SessionLocal(); print(json.dumps({'active_rooms':db.scalar(select(func.count()).select_from(InterviewSchedule).where(InterviewSchedule.room_status.in_(['ready','active','ending']))),'pending_email':db.scalar(select(func.count()).select_from(InterviewDelivery).where((InterviewDelivery.status=='pending') | InterviewDelivery.in_flight))})); db.close()"
    $result = (& docker compose exec -T backend python -c $code | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Unable to check whether the backend can be safely restarted.' }
    return $result | ConvertFrom-Json
}

function Assert-DemoRestartSafe {
    $status = Get-DemoSafetyStatus
    if ($status.active_rooms -gt 0 -or $status.pending_email -gt 0) {
        throw 'Finish/end active interviews and resolve pending email deliveries before changing demo mode.'
    }
}

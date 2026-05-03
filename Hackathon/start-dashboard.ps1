# start-dashboard.ps1
# Starts Python HTTP server + ngrok, then shows the public URL.
# Usage: .\start-dashboard.ps1  (run from repo root)

$dashboardDir = Join-Path $PSScriptRoot "hackerson\smartevac-dashboard"
$ngrokExe     = "$env:TEMP\ngrok-v3\ngrok.exe"

# ── Check ngrok ───────────────────────────────────────────────────────────
if (-not (Test-Path $ngrokExe)) {
    Write-Host "[ERROR] ngrok not found at $ngrokExe"
    Write-Host "Download from https://ngrok.com/download and extract to $env:TEMP\ngrok-v3\"
    exit 1
}

# ── Kill existing processes on port 8080 ─────────────────────────────────
$existing = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Stopping existing process on port 8080..."
    $existing | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}

# Kill existing ngrok
Get-Process ngrok -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# ── Start Python HTTP server ──────────────────────────────────────────────
Write-Host "Starting Python HTTP server on port 8080..."
$pythonProc = Start-Process -FilePath "python" `
    -ArgumentList "-m", "http.server", "8080" `
    -WorkingDirectory $dashboardDir `
    -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2

if ($pythonProc.HasExited) {
    Write-Host "[ERROR] Python server failed to start"
    exit 1
}
Write-Host "[OK] Python server started (PID $($pythonProc.Id))"

# ── Start ngrok ───────────────────────────────────────────────────────────
Write-Host "Starting ngrok..."
$ngrokProc = Start-Process -FilePath $ngrokExe `
    -ArgumentList "http", "8080" `
    -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 4

# ── Get public URL ────────────────────────────────────────────────────────
$url = ""
for ($i = 0; $i -lt 5; $i++) {
    try {
        $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -ErrorAction Stop
        $url = $tunnels.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -ExpandProperty public_url -First 1
        if ($url) { break }
    } catch {
        Start-Sleep -Seconds 2
    }
}

Write-Host ""
if ($url) {
    Write-Host "============================================"
    Write-Host "  Dashboard URL:"
    Write-Host "  $url"
    Write-Host "============================================"
    Write-Host ""
    Write-Host "Share this URL with all 3 computers."
    Write-Host "Each person opens the URL and selects their role."
    Write-Host ""
    Write-Host "Press Ctrl+C to stop."

    # Keep running until Ctrl+C
    try {
        while ($true) { Start-Sleep -Seconds 10 }
    } finally {
        Write-Host "Stopping..."
        Stop-Process -Id $pythonProc.Id -Force -ErrorAction SilentlyContinue
        Stop-Process -Id $ngrokProc.Id  -Force -ErrorAction SilentlyContinue
        Write-Host "Done."
    }
} else {
    Write-Host "[ERROR] Could not get ngrok URL. Check http://localhost:4040 manually."
    Write-Host "Python server PID: $($pythonProc.Id)"
    Write-Host "ngrok PID: $($ngrokProc.Id)"
}

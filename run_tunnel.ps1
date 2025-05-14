# run_tunnel.ps1
param(
    [int]$Port = 5000
)

# Navigate to the script's directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Set the YouTube Data API key for this session
$env:YOUTUBE_API_KEY = "AIzaSyBBkzfnLHrCwS6LNOTWRTpaMdYvIdyJudE"

# Ensure yt-dlp is installed
Write-Host "Installing yt-dlp..."
pip install yt-dlp | Out-Null

# Start the Flask application in a new PowerShell window
Write-Host "Starting Flask application..."
Start-Process powershell -ArgumentList "-NoExit -Command cd '$scriptDir'; python app.py" -WindowStyle Normal

# Wait for Flask to initialize
Start-Sleep -Seconds 3

# Start Cloudflare Tunnel in this window
Write-Host "Starting Cloudflare Tunnel on port $Port..."
$cfPath = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
& $cfPath tunnel --url http://localhost:$Port 
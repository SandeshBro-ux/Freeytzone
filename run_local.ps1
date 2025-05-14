# run_local.ps1
param(
    [int]$Port = 5000
)

# Navigate to the script's directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Set the YouTube Data API key for this session
$env:YOUTUBE_API_KEY = "AIzaSyBBkzfnLHrCwS6LNOTWRTpaMdYvIdyJudE"

# Create a function to check if a command exists
function Test-CommandExists {
    param ($command)
    $exists = $null -ne (Get-Command $command -ErrorAction SilentlyContinue)
    return $exists
}

# Ensure yt-dlp is installed
Write-Host "Installing yt-dlp..."
pip install yt-dlp | Out-Null

# Check for ffmpeg
if (-not (Test-CommandExists "ffmpeg")) {
    Write-Host "ffmpeg not found. Attempting to install via scoop..."
    
    # Check if scoop is installed
    if (-not (Test-CommandExists "scoop")) {
        Write-Host "Installing scoop package manager..."
        try {
            # Set execution policy and install scoop
            Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
            Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression
        } catch {
            Write-Host "Failed to install scoop. Please install ffmpeg manually and add it to your PATH."
            Write-Host "Download from: https://ffmpeg.org/download.html"
        }
    }
    
    # Install ffmpeg using scoop
    if (Test-CommandExists "scoop") {
        Write-Host "Installing ffmpeg via scoop..."
        scoop install ffmpeg
    }
}

# Set PATH to include common ffmpeg locations
$ffmpegPaths = @(
    "$HOME\scoop\shims",
    "C:\ffmpeg\bin",
    "$scriptDir\ffmpeg\bin"
)

foreach ($path in $ffmpegPaths) {
    if (Test-Path $path) {
        $env:PATH = "$path;$env:PATH"
    }
}

# Fix any corrupted app.py file with our fixed version
if (Test-Path "$scriptDir\app_fixed.py") {
    Write-Host "Using fixed version of app.py..."
    if (Test-Path "$scriptDir\app.py.original") {
        Write-Host "Original backup already exists."
    } else {
        Copy-Item "$scriptDir\app.py" "$scriptDir\app.py.original" -Force
        Write-Host "Created backup of original app.py"
    }
    Copy-Item "$scriptDir\app_fixed.py" "$scriptDir\app.py" -Force
    Write-Host "Applied fixed version of app.py"
}

# Start the Flask application directly in this window (no tunnel)
Write-Host "Starting Flask application on http://localhost:$Port..."
Write-Host "You can access your downloader directly at: http://localhost:$Port/direct"
python app.py

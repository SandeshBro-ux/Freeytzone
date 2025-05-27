# YouTube Downloader

A powerful YouTube downloader web application with 2K video quality support, MP3 extraction, thumbnail downloads, and real-time progress tracking. Now with browser emulation to bypass YouTube's bot verification!

## Features

- **High-Quality Video**: Download videos in resolutions up to 2K (1440p)
- **MP3 Extraction**: Extract audio from videos in MP3 format
- **Thumbnail Downloads**: Save video thumbnails in original quality
- **Progress Tracking**: Real-time download progress with speed and ETA
- **Download Management**: Cancel ongoing downloads or start new ones
- **User-Friendly Interface**: Clean, responsive design with Bootstrap
- **Bot Verification Bypass**: Uses browser emulation to appear as a real human user

## How to Use

1. Enter a YouTube URL in the input field
2. Click "Fetch Info" to retrieve video details
3. Select your desired format:
   - **Video with Audio**: Download the complete video
   - **Audio Only (MP3)**: Extract just the audio track
   - **Original Thumbnail**: Download the video thumbnail image
4. For videos, select your preferred quality
5. Click "Download" to start the process
6. Monitor the download progress in real-time
7. When complete, click "Save File" to download to your device

## Technical Details

- Built with Flask (Python web framework)
- Uses yt-dlp for YouTube video extraction
- Selenium and headless Chrome for browser emulation
- Bootstrap for responsive UI
- AJAX for seamless background operations
- Downloads persist in a dedicated directory

## Requirements

- Python 3.11+
- Flask
- flask-cors
- yt-dlp
- requests
- selenium
- webdriver-manager
- ChromeDriver and headless Chrome (auto-installed by build script)

## Deployment on Render

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Configure the service with:
   - **Build Command**: `chmod +x build.sh && ./build.sh`
   - **Start Command**: `gunicorn app:app`
   - **Environment Variables**:
     - `FFMPEG_PATH`: `/usr/bin/ffmpeg` (optional)
     - `YOUTUBE_API_KEY`: Your YouTube API key (optional, for fallback)
     - `YTDLP_PROXY_URL`: Your proxy URL (optional, for additional layer of protection)

### How the Render Deployment Works

This application uses a custom approach to run headless Chrome in Render's environment:

1. The `build.sh` script automatically downloads:
   - A portable version of Chromium specifically designed for serverless environments
   - A compatible version of ChromeDriver
   
2. Both binaries are installed in the user's home directory (`$HOME/chrome-bin`)

3. The application detects these binaries and uses them for browser emulation, which enables:
   - YouTube bot verification bypass without requiring system-level Chrome installation
   - Reliable operation in Render's read-only file system environment

## Usage Notes

This application is for personal use only. Please respect copyright laws and YouTube's Terms of Service when downloading content.
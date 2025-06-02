# FreeYTZone - YouTube Video Downloader

A web application for downloading YouTube videos with support for various quality options and automatic IP rotation to bypass rate limits.

## Features

- Clean, modern web interface
- Support for downloading videos in multiple quality levels (up to 2K/4K)
- MP3 audio extraction
- VPNBook proxy integration for bypassing YouTube's rate limits (HTTP Error 429)
- Proper cookie support for downloading age-restricted or private videos
- Automatic retry with proxy rotation when encountering rate limits

## Environment Variables

Configure the application with the following environment variables:

- `YOUTUBE_API_KEY` - YouTube Data API key for fetching video metadata
- `YTDLP_PROXY_URL` - Custom proxy URL (overrides VPNBook if set)
- `USE_VPNBOOK` - Enable/disable VPNBook proxy integration (default: "True")
- `VPNBOOK_COUNTRY` - Country for VPNBook proxy (default: random, options: US, CA, DE, FR, UK, PL)
- `VPNBOOK_PROTOCOL` - Protocol for VPNBook proxy (default: "http", options: "http", "socks")

## Installation

### Requirements
- Python 3.8 or higher
- FFmpeg (for video format conversion and audio extraction)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/SandeshBro-ux/Freeytzone.git
cd Freeytzone
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your YouTube API key:
```
YOUTUBE_API_KEY=your_youtube_api_key
USE_VPNBOOK=True
```

4. Run the application:
```bash
python app.py
```

## Deployment on Render

This application is configured for easy deployment on Render.

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Configure environment variables in the Render dashboard
4. Deploy!

## VPNBook Proxy Integration

The application integrates with VPNBook's free proxies to bypass YouTube's rate limits:

- Automatically fetches the current VPNBook password
- Rotates proxies when encountering rate limits
- Tracks failed proxies to avoid using them again
- Supports multiple countries (US, Canada, Germany, France, UK, Poland)

## Usage

1. Enter a YouTube video URL
2. (Optional) Paste your YouTube cookies for age-restricted or private videos
3. Click "Fetch Video Info" to analyze the video
4. Select your desired quality
5. Click "Download" to save the video

## Handling Rate Limits

YouTube imposes rate limits (HTTP 429 errors) on frequent requests. This application:

1. Automatically retries with different VPNBook proxies
2. Provides clear error messages when rate limits are encountered
3. Allows using cookies to authenticate with YouTube and reduce rate limiting

## License

MIT License

## Project Structure

```
/
|-- app.py                  # Main Flask application
|-- requirements.txt        # Python dependencies
|-- .env                    # Environment variables (for API key)
|-- templates/
|   |-- index.html          # Frontend HTML template
|-- cookies/                # Temporary storage for uploaded cookie files (created automatically)
|-- downloads/              # Temporary storage for downloaded videos (created automatically)
|-- README.md               # This file
```

## Notes

-   The `cookies` and `downloads` directories are created automatically by the application if they don't exist. Cookie files are temporarily stored per video ID and then deleted after a successful download. Downloaded files are served from the `downloads` directory.
-   This application is for personal and educational purposes only. Always respect copyright laws and YouTube's Terms of Service when downloading content. 
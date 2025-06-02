# Freeytzone - YouTube Video Downloader

A web application that allows users to download YouTube videos in various qualities, extract MP3 audio, and download thumbnails or channel logos.

## Recent Enhancements for Cookie Handling

The application has been updated to improve cookie handling, specifically to address issues with YouTube bot detection when deployed on platforms like Render. The key changes include:

### 1. Enhanced Cookie Handling
- Added a new `create_cookie_file()` function that uses temporary files for better security
- Improved process_cookie_string() with better detection and formatting of Netscape cookie format
- Better cleanup of temporary cookie files

### 2. Improved Error Handling for Rate Limits
- Added specific detection and handling for HTTP 429 (Too Many Requests) errors
- Clear error messages that guide users to provide cookies when needed

### 3. Browser-like Request Headers
- Updated HTTP headers to make requests appear more like a standard browser
- Added Accept, Accept-Language, and other headers that help avoid detection

### 4. Better File Finding Logic
- Improved logic for finding downloaded files in case of unexpected naming issues

## Usage

To use cookies with the application:

1. Export cookies from a browser extension like "EditThisCookie" or "Cookie-Editor"
2. Copy the Netscape format cookies into the cookies input field
3. This helps bypass YouTube's bot detection when fetching video information and downloading videos

## Setup and Running

1. Install dependencies: `pip install -r requirements.txt`
2. Run the application: `python app.py`
3. Access the application at `http://localhost:5000`

## Features

- Fetch and display YouTube video information
- Download videos in various qualities (up to 2K)
- Extract MP3 audio from videos
- Download video thumbnails and channel logos
- Support for cookies to handle age-restricted and private videos

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
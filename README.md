# YouTube Downloader

A powerful YouTube downloader web application with 2K video quality support, MP3 extraction, thumbnail downloads, and real-time progress tracking.

## Features

- **High-Quality Video**: Download videos in resolutions up to 2K (1440p)
- **MP3 Extraction**: Extract audio from videos in MP3 format
- **Thumbnail Downloads**: Save video thumbnails in original quality
- **Progress Tracking**: Real-time download progress with speed and ETA
- **Download Management**: Cancel ongoing downloads or start new ones
- **User-Friendly Interface**: Clean, responsive design with Bootstrap

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
- Bootstrap for responsive UI
- AJAX for seamless background operations
- Downloads persist in a dedicated directory

## Requirements

- Python 3.11+
- Flask
- flask-cors
- yt-dlp
- requests

## Usage Notes

This application is for personal use only. Please respect copyright laws and YouTube's Terms of Service when downloading content.
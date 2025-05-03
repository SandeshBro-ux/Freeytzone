import os
import logging
from flask import Flask, render_template, request, jsonify, send_file, abort
from flask_cors import CORS
import tempfile
import shutil
from utils.youtube_downloader_new import YouTubeDownloader

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "youtube_downloader_secret")
CORS(app)

# Create download directory that persists between sessions
def create_downloads_directory():
    # First try to use the workspace directory if available (for Replit)
    workspace_dir = os.environ.get('HOME', '')
    if workspace_dir and os.path.exists(workspace_dir):
        downloads_dir = os.path.join(workspace_dir, 'downloads')
    else:
        # Fallback to local directory
        downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
    
    # Create the directory if it doesn't exist
    os.makedirs(downloads_dir, exist_ok=True)
    logger.debug(f"Download directory created at: {downloads_dir}")
    return downloads_dir

# Create persistent download directory
TEMP_DIR = create_downloads_directory()

# Create a global downloader instance
downloader = YouTubeDownloader(TEMP_DIR)

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/api/video-info', methods=['POST'])
def get_video_info():
    """Get information about a YouTube video"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        info = downloader.get_video_info(url)
        
        return jsonify(info)
    except Exception as e:
        logger.error(f"Error getting video info: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    """Download YouTube content based on parameters"""
    try:
        data = request.get_json()
        url = data.get('url')
        format_type = data.get('format')  # 'video', 'audio', 'thumbnail'
        quality = data.get('quality', 'best')
        
        if not url or not format_type:
            return jsonify({'error': 'URL and format type are required'}), 400
        
        # Generate a download ID for progress tracking
        download_id = downloader.start_download(url, format_type, quality)
        logger.debug(f"Started download with ID: {download_id}")
        
        return jsonify({'download_id': download_id})
    except Exception as e:
        logger.error(f"Error starting download: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/progress/<download_id>', methods=['GET'])
def get_progress(download_id):
    """Get the progress of a download"""
    try:
        logger.debug(f"Getting progress for download ID: {download_id}")
        progress = downloader.get_progress(download_id)
        
        return jsonify(progress)
    except Exception as e:
        logger.error(f"Error getting progress: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download-file/<download_id>', methods=['GET'])
def get_download_file(download_id):
    """Get the downloaded file"""
    try:
        file_path, filename, mime_type = downloader.get_download_file(download_id)
        
        if not file_path:
            return jsonify({'error': 'Download not found or not completed'}), 404
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype=mime_type
        )
    except Exception as e:
        logger.error(f"Error sending file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/cancel/<download_id>', methods=['POST'])
def cancel_download(download_id):
    """Cancel an ongoing download"""
    try:
        result = downloader.cancel_download(download_id)
        
        return jsonify({'success': result})
    except Exception as e:
        logger.error(f"Error canceling download: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Cleanup old downloads (files older than 1 hour)
@app.before_request
def cleanup_old_downloads():
    """Clean up old downloads before processing each request"""
    try:
        downloader.cleanup_old_downloads(3600)  # 1 hour in seconds
    except Exception as e:
        logger.error(f"Error cleaning up old downloads: {str(e)}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

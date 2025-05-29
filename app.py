import os
import logging
from flask import Flask, render_template, request, jsonify, send_file, abort
from flask_cors import CORS
import tempfile
import shutil
import time
from utils.youtube_downloader_new import YouTubeDownloader
from threading import Thread

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create Flask app
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'), template_folder=os.path.join(BASE_DIR, 'templates'))
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
downloader = YouTubeDownloader(temp_dir=TEMP_DIR)

# Start background thread to auto-clean empty download subdirectories
def auto_clean_empty_dirs():
    import os, shutil, time
    while True:
        try:
            for name in os.listdir(TEMP_DIR):
                dir_path = os.path.join(TEMP_DIR, name)
                if os.path.isdir(dir_path) and not os.listdir(dir_path):
                    shutil.rmtree(dir_path)
                    logger.debug(f"Auto-deleted empty download directory: {dir_path}")
        except Exception as e:
            logger.error(f"Error auto-cleaning empty directories: {e}")
        time.sleep(5)
Thread(target=auto_clean_empty_dirs, daemon=True).start()

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/api/video-info', methods=['POST'])
def get_video_info_route():
    """Get information about a YouTube video"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Get YouTube API Key from environment
        youtube_api_key = os.environ.get('YOUTUBE_API_KEY')
        if not youtube_api_key:
            logger.warning("YOUTUBE_API_KEY environment variable not set. API v3 features will be limited.")
            # Optionally, you could choose to proceed without it or return an error/warning to frontend

        # Call the modified get_video_info method, passing the API key
        # The use_api_v3 flag can be controlled here if needed, defaults to True in downloader method
        info = downloader.get_video_info(url, api_key=youtube_api_key)
        
        if info.get('error'):
            # Check if it's a yt-dlp specific error that API v3 might have mitigated
            if info.get('yt_dlp_error') and info.get('info_source', '').startswith('api_v3'):
                logger.warning(f"yt-dlp failed but API v3 provided some data: {info['yt_dlp_error']}")
                # Return the partial data from API v3, but flag that formats might be missing
                return jsonify(info) # Frontend should handle this (e.g. show metadata but no download options)
            return jsonify({'error': info['error']}), 500 # Or a more appropriate status code
        
        return jsonify(info)
    except Exception as e:
        logger.error(f"Error in /api/video-info route: {str(e)}", exc_info=True)
        return jsonify({'error': f"An unexpected server error occurred: {str(e)}"}), 500

@app.route('/api/download', methods=['POST'])
def download_video_route():
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
        logger.error(f"Error starting download: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/progress/<download_id>', methods=['GET'])
def get_progress_route(download_id):
    """Get the progress of a download"""
    try:
        logger.debug(f"Getting progress for download ID: {download_id}")
        progress = downloader.get_progress(download_id)
        
        return jsonify(progress)
    except Exception as e:
        logger.error(f"Error getting progress for {download_id}: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/download-file/<download_id>', methods=['GET'])
def get_download_file_route(download_id):
    """Get the downloaded file and schedule its deletion after 5 seconds"""
    try:
        file_path, filename, mime_type = downloader.get_download_file(download_id)
        
        if not file_path or not filename:
            return jsonify({'error': 'File not found or download not complete'}), 404
        
        # Send the file and schedule deletion of its directory after the response is closed
        response = send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype=mime_type
        )
        
        # Schedule cleanup of the specific download's temporary directory
        task_temp_dir = None
        with downloader.progress_lock: # Access task info safely
            task = downloader.download_tasks.get(download_id)
            if task and task.get('temp_dir_path'):
                task_temp_dir = task['temp_dir_path']
        
        if task_temp_dir:
            def delete_task_dir():
                try:
                    time.sleep(5) # Wait a bit for download to complete
                    if os.path.exists(task_temp_dir):
                        shutil.rmtree(task_temp_dir)
                        logger.info(f"Successfully deleted temp download directory: {task_temp_dir}")
                except Exception as e_clean:
                    logger.error(f"Error deleting temp download directory {task_temp_dir}: {e_clean}")
            response.call_on_close(delete_task_dir) # Flask specific: call after response is sent
        else:
            logger.warning(f"No temp_dir_path found for download_id {download_id} to schedule deletion.")
        
        return response
    except Exception as e:
        logger.error(f"Error sending file for {download_id}: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/cancel/<download_id>', methods=['POST'])
def cancel_download_route(download_id):
    """Cancel an ongoing download"""
    try:
        result = downloader.cancel_download(download_id)
        
        return jsonify({'success': result})
    except Exception as e:
        logger.error(f"Error canceling download {download_id}: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# Cleanup old downloads (files older than 1 hour)
@app.before_request
def cleanup_old_general_downloads():
    """Clean up old downloads before processing each request"""
    try:
        # This should ideally scan TEMP_DIR for any old directories not tied to active tasks
        # The current YouTubeDownloader.cleanup_old_downloads is a placeholder
        # downloader.cleanup_old_downloads(3600) # 1 hour
        pass # For now, rely on individual download cleanup or a more robust general scanner
    except Exception as e:
        logger.error(f"Error in before_request cleanup: {str(e)}", exc_info=True)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True) # Added debug=True for development

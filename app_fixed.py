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
downloader = YouTubeDownloader(TEMP_DIR)

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

@app.route('/direct')
def direct_page():
    """Render the direct download page"""
    return render_template('direct.html')

# Simple direct download method
@app.route('/direct-download/<download_id>', methods=['GET'])
def direct_download(download_id):
    try:
        logger.info(f"Direct download requested for ID: {download_id}")
        file_path, filename, mime_type = downloader.get_download_file(download_id)
        
        if not file_path:
            return jsonify({'error': 'Download not found or not completed'}), 404
        
        if not os.path.exists(file_path):
            logger.error(f"File does not exist: {file_path}")
            return jsonify({'error': 'File does not exist'}), 404
        
        # Send the file directly
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype=mime_type
        )
    except Exception as e:
        logger.error(f"Error in direct download: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
        # Detailed logging for debugging
        logger.debug("=== Download request received ===")
        data = request.get_json()
        logger.debug(f"Download data: {data}")
        url = data.get('url')
        format_type = data.get('format')  # 'video', 'audio', 'thumbnail'
        quality = data.get('quality', 'best')
        
        if not url or not format_type:
            logger.error("URL or format type missing")
            return jsonify({'error': 'URL and format type are required'}), 400
        
        # Log environment variables for ffmpeg
        logger.debug(f"PATH: {os.environ.get('PATH')}")
        
        # Check ffmpeg version
        try:
            import subprocess
            ffmpeg_result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
            if ffmpeg_result.returncode == 0:
                logger.debug(f"ffmpeg version: {ffmpeg_result.stdout.splitlines()[0]}")
            else:
                logger.error(f"ffmpeg check failed: {ffmpeg_result.stderr}")
        except Exception as e:
            logger.error(f"Error checking ffmpeg: {e}")
        
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
    """Get the downloaded file and schedule its deletion after 5 seconds"""
    try:
        # DIRECT_DOWNLOAD_WORKAROUND - Modified to handle Cloudflare tunnel better
        file_path, filename, mime_type = downloader.get_download_file(download_id)
        
        if not file_path:
            return jsonify({'error': 'Download not found or not completed'}), 404
        
        # Read file and encode as base64 for direct browser download
        import base64
        try:
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            # Get file size
            file_size = os.path.getsize(file_path)
            logger.debug(f"File size: {file_size} bytes")
            
            # Generate download info
            download_info = {
                'filename': filename,
                'mime_type': mime_type,
                'file_size': file_size,
                'download_id': download_id
            }
            
            # Create response to return download info
            return jsonify({
                'status': 'success',
                'download_info': download_info
            })
        except Exception as e:
            logger.error(f"Error preparing file: {str(e)}")
            return jsonify({'error': f'Error preparing file: {str(e)}'}), 500

@app.route('/api/direct-file/<download_id>', methods=['GET'])
def get_direct_file(download_id):
    """Direct file download endpoint that sends chunks to avoid Cloudflare timeouts"""
    try:
        logger.debug(f"Direct file download requested for ID: {download_id}")
        file_path, filename, mime_type = downloader.get_download_file(download_id)
        
        if not file_path:
            logger.error(f"Download not found or not completed for ID: {download_id}")
            return jsonify({'error': 'Download not found or not completed'}), 404
        
        # Verify file exists and is readable
        if not os.path.exists(file_path):
            logger.error(f"File does not exist: {file_path}")
            return jsonify({'error': 'File does not exist'}), 404
            
        file_size = os.path.getsize(file_path)
        logger.debug(f"File found: {file_path}, size: {file_size} bytes")
        
        if file_size == 0:
            logger.error(f"File exists but has zero size: {file_path}")
            return jsonify({'error': 'File is empty'}), 500
        
        # Test file can be opened before returning response
        try:
            with open(file_path, 'rb') as test:
                test.read(1)  # Just read 1 byte to make sure it works
            logger.debug(f"File opened successfully: {file_path}")
        except Exception as e:
            logger.error(f"Cannot open file {file_path}: {str(e)}")
            return jsonify({'error': f'Cannot open file: {str(e)}'}), 500
            
        # Stream the file in chunks to avoid Cloudflare timeouts
        def generate():
            logger.debug(f"Starting file streaming for {file_path}")
            chunk_size = 4096  # 4KB chunks
            sent_bytes = 0
            try:
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        sent_bytes += len(chunk)
                        yield chunk
                logger.debug(f"File streaming complete. Sent {sent_bytes} of {file_size} bytes")
            except Exception as e:
                logger.error(f"Error during file streaming: {str(e)}")
                # Can't return HTTP error from generator, but log it
        
        # Schedule deletion after sending
        dir_path = os.path.dirname(file_path)
        def delayed_delete():
            time.sleep(5)
            logger.debug(f"Attempting to delete download directory: {dir_path}")
            try:
                if os.path.exists(dir_path):
                    shutil.rmtree(dir_path)
                    logger.debug(f"Successfully deleted download directory: {dir_path}")
                else:
                    logger.debug(f"Download directory not found (already deleted?): {dir_path}")
            except Exception as e:
                logger.error(f"Error deleting download directory {dir_path}: {e}")
        
        Thread(target=delayed_delete, daemon=True).start()
        
        logger.debug(f"Preparing response with mime_type: {mime_type}, filename: {filename}")
        response = app.response_class(
            generate(),
            mimetype=mime_type,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(file_size)
            }
        )
        return response
    except Exception as e:
        logger.error(f"Error in direct download: {str(e)}")
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
    # Run without debug reloader to prevent mid-run restarts
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

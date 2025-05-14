import os
import shutil
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='fix_cloudflare.log',
    filemode='w'
)
logger = logging.getLogger()
logger.addHandler(logging.StreamHandler())

def fix_ffmpeg_path():
    """Add ffmpeg to PATH if not already there"""
    logger.info("Checking for ffmpeg in PATH...")
    
    # Check if ffmpeg is in PATH
    ffmpeg_in_path = False
    for path in os.environ.get('PATH', '').split(os.pathsep):
        if os.path.exists(os.path.join(path, 'ffmpeg.exe')):
            ffmpeg_in_path = True
            logger.info(f"ffmpeg found in PATH at: {os.path.join(path, 'ffmpeg.exe')}")
            break
    
    # Check common ffmpeg locations
    ffmpeg_locations = [
        r"C:\Users\baral\scoop\shims\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        os.path.expanduser(r"~\scoop\shims\ffmpeg.exe"),
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe"
    ]
    
    found_ffmpeg = None
    for location in ffmpeg_locations:
        if os.path.exists(location):
            found_ffmpeg = location
            logger.info(f"ffmpeg found at: {location}")
            break
    
    # Add ffmpeg to PATH if found but not in PATH
    if not ffmpeg_in_path and found_ffmpeg:
        ffmpeg_path = os.path.dirname(found_ffmpeg)
        logger.info(f"Adding {ffmpeg_path} to PATH...")
        os.environ['PATH'] = ffmpeg_path + os.pathsep + os.environ.get('PATH', '')
        logger.info("ffmpeg added to PATH")
        return True
    elif ffmpeg_in_path:
        logger.info("ffmpeg already in PATH")
        return True
    else:
        logger.error("ffmpeg not found. Please install it.")
        return False

def update_app_code():
    """Update app.py to use direct downloads instead of streaming through Cloudflare"""
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
    backup_path = app_path + '.backup'
    
    logger.info(f"Backing up app.py to {backup_path}")
    shutil.copy2(app_path, backup_path)
    
    # Read the file
    with open(app_path, 'r') as f:
        content = f.read()
    
    # Find the @app.route('/api/download-file/<download_id>') function
    if '@app.route(\'/api/download-file/<download_id>\'' in content:
        logger.info("Found download-file route, updating...")
        
        # Check if it's already been modified
        if 'DIRECT_DOWNLOAD_WORKAROUND' in content:
            logger.info("App already has the direct download workaround.")
            return True
        
        # Define the old route
        old_route = '''@app.route('/api/download-file/<download_id>', methods=['GET'])
def get_download_file(download_id):
    """Get the downloaded file and schedule its deletion after 5 seconds"""
    try:
        file_path, filename, mime_type = downloader.get_download_file(download_id)
        
        if not file_path:
            return jsonify({'error': 'Download not found or not completed'}), 404
        
        # Send the file and schedule deletion of its directory after the response is closed
        response = send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype=mime_type
        )
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
        def schedule_delete():
            Thread(target=delayed_delete, daemon=True).start()
        response.call_on_close(schedule_delete)
        return response'''
        
        # Define the new route
        new_route = '''@app.route('/api/download-file/<download_id>', methods=['GET'])
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
'''
        
        # Replace the route
        updated_content = content.replace(old_route, new_route)
        
        # Add the direct download route
        direct_download_route = '''
@app.route('/api/direct-file/<download_id>', methods=['GET'])
def get_direct_file(download_id):
    """Direct file download endpoint that sends chunks to avoid Cloudflare timeouts"""
    try:
        file_path, filename, mime_type = downloader.get_download_file(download_id)
        
        if not file_path:
            return jsonify({'error': 'Download not found or not completed'}), 404
        
        # Stream the file in chunks to avoid Cloudflare timeouts
        def generate():
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(4096)  # 4KB chunks
                    if not chunk:
                        break
                    yield chunk
        
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
        
        response = app.response_class(
            generate(),
            mimetype=mime_type,
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )
        return response
    except Exception as e:
        logger.error(f"Error in direct download: {str(e)}")
        return jsonify({'error': str(e)}), 500
'''
        
        # Add the direct download route after @app.route('/api/cancel/<download_id>'
        if '@app.route(\'/api/cancel/<download_id>\'' in updated_content:
            updated_content = updated_content.replace('@app.route(\'/api/cancel/<download_id>\'', 
                                                   direct_download_route + '\n@app.route(\'/api/cancel/<download_id>\'')
        
        # Update the templates/index.html file to use the direct download
        try:
            index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'index.html')
            index_backup = index_path + '.backup'
            
            # Backup index.html
            logger.info(f"Backing up index.html to {index_backup}")
            shutil.copy2(index_path, index_backup)
            
            # Read index.html
            with open(index_path, 'r') as f:
                index_content = f.read()
            
            # Check if already modified
            if 'handleDirectDownload' in index_content:
                logger.info("Index.html already modified.")
            else:
                # Find the downloadLink handler in JavaScript
                if 'downloadLink.addEventListener(\'click\'' in index_content:
                    logger.info("Found downloadLink event listener, updating...")
                    
                    download_js_old = '''downloadLink.addEventListener('click', async function(e) {
            e.preventDefault();
            if (!currentDownloadId) return;

            window.location.href = `/api/download-file/${currentDownloadId}`;
        });'''
                    
                    download_js_new = '''downloadLink.addEventListener('click', async function(e) {
            e.preventDefault();
            if (!currentDownloadId) return;

            // Use the updated direct download approach
            handleDirectDownload(currentDownloadId);
        });
        
        // Direct download handler to avoid Cloudflare timeout issues
        async function handleDirectDownload(downloadId) {
            try {
                // First get the download info
                const response = await fetch(`/api/download-file/${downloadId}`);
                const data = await response.json();
                
                if (data.status === 'success') {
                    // Create a direct download link
                    const downloadInfo = data.download_info;
                    console.log("Download info:", downloadInfo);
                    
                    // Direct the browser to the streaming endpoint
                    window.location.href = `/api/direct-file/${downloadId}`;
                } else {
                    showError("Download Error", data.error || "Failed to prepare download");
                }
            } catch (error) {
                console.error("Download error:", error);
                showError("Download Error", "Failed to download file. Please try again.");
            }
        }'''
                    
                    # Replace the JavaScript
                    updated_index = index_content.replace(download_js_old, download_js_new)
                    
                    # Write the updated index.html
                    with open(index_path, 'w') as f:
                        f.write(updated_index)
                    
                    logger.info("Updated index.html with direct download handler")
        except Exception as e:
            logger.error(f"Error updating index.html: {str(e)}")
        
        # Write the updated app.py
        with open(app_path, 'w') as f:
            f.write(updated_content)
        
        logger.info("Updated app.py with direct download workaround")
        return True
    else:
        logger.error("Could not find the download-file route in app.py")
        return False

if __name__ == "__main__":
    logger.info("Starting Cloudflare download fix")
    fix_ffmpeg_path()
    update_app_code()
    logger.info("Fix complete. Please restart your application.")

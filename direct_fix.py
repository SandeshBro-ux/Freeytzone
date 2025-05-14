import os
import sys
import shutil
import logging
import re

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("direct_fix.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def implement_direct_approach():
    """Implement a more direct, simplified approach for downloading"""
    # Path to app.py
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
    
    # Back up the file
    backup_path = app_path + '.direct_fix.bak'
    logger.info(f"Backing up app.py to {backup_path}")
    shutil.copy2(app_path, backup_path)
    
    # Read the file
    with open(app_path, 'r') as f:
        content = f.read()
    
    # Add a simple, direct download method that bypasses the Cloudflare tunnel for downloads
    direct_method = """
# Direct download method that doesn't use streaming
@app.route('/api/simple-download/<download_id>', methods=['GET'])
def simple_download(download_id):
    try:
        logger.info(f"Simple download requested for ID: {download_id}")
        file_path, filename, mime_type = downloader.get_download_file(download_id)
        
        if not file_path:
            logger.error(f"File not found for download ID: {download_id}")
            return jsonify({'error': 'Download not found or not completed'}), 404
        
        if not os.path.exists(file_path):
            logger.error(f"File path doesn't exist: {file_path}")
            return jsonify({'error': 'File not found on server'}), 404
        
        file_size = os.path.getsize(file_path)
        logger.info(f"Sending file: {file_path}, size: {file_size} bytes")
        
        try:
            # Use Flask's send_file with conditional to suppress warnings
            response = send_file(
                file_path, 
                as_attachment=True,
                download_name=filename,
                mimetype=mime_type
            )
            
            # Delete the file after a delay
            dir_path = os.path.dirname(file_path)
            def delayed_delete():
                import time
                time.sleep(5)
                logger.info(f"Deleting download directory: {dir_path}")
                try:
                    if os.path.exists(dir_path):
                        shutil.rmtree(dir_path)
                except Exception as e:
                    logger.error(f"Error deleting directory: {e}")
            
            from threading import Thread
            Thread(target=delayed_delete, daemon=True).start()
            
            return response
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            return jsonify({'error': f'Error sending file: {str(e)}'}), 500
            
    except Exception as e:
        logger.error(f"Error in simple download: {e}")
        return jsonify({'error': str(e)}), 500
"""
    
    # Find where to insert the new method
    cleanup_pattern = r"# Cleanup old downloads"
    match = re.search(cleanup_pattern, content)
    
    if match:
        # Insert before cleanup
        insert_pos = match.start()
        new_content = content[:insert_pos] + direct_method + "\n\n" + content[insert_pos:]
        
        # Write the updated file
        with open(app_path, 'w') as f:
            f.write(new_content)
        
        logger.info("Added simple direct download method to app.py")
    else:
        logger.error("Could not find insertion point in app.py")
        return False
    
    # Now update the index.html to use this new method
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    index_path = os.path.join(templates_dir, 'index.html')
    
    # Back up index.html
    index_backup = index_path + '.direct_fix.bak'
    logger.info(f"Backing up index.html to {index_backup}")
    shutil.copy2(index_path, index_backup)
    
    # Read index.html
    with open(index_path, 'r') as f:
        index_content = f.read()
    
    # Find the download button handler
    download_button_pattern = r"downloadLink\.addEventListener\('click', [^{]*{[^}]*}\);"
    match = re.search(download_button_pattern, index_content)
    
    if match:
        # Replace with direct approach
        old_handler = match.group(0)
        new_handler = """downloadLink.addEventListener('click', function(e) {
            e.preventDefault();
            if (!currentDownloadId) return;
            
            // Use simple direct download that doesn't use streaming
            window.location.href = `/api/simple-download/${currentDownloadId}`;
        });"""
        
        new_index_content = index_content.replace(old_handler, new_handler)
        
        # Write updated index.html
        with open(index_path, 'w') as f:
            f.write(new_index_content)
        
        logger.info("Updated download button handler in index.html")
        return True
    else:
        logger.error("Could not find download button handler in index.html")
        return False

def clear_downloads():
    """Clear the downloads directory and state file"""
    downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
    state_file = os.path.join(downloads_dir, 'downloads_state.json')
    
    logger.info(f"Clearing downloads directory: {downloads_dir}")
    
    # Clear state file
    if os.path.exists(state_file):
        try:
            # Create empty state file
            with open(state_file, 'w') as f:
                f.write('{}')
            logger.info("Reset downloads state file")
        except Exception as e:
            logger.error(f"Error clearing state file: {e}")
    
    # Clear download directories
    try:
        subdirs = [d for d in os.listdir(downloads_dir) 
                 if os.path.isdir(os.path.join(downloads_dir, d))]
        
        for subdir in subdirs:
            subdir_path = os.path.join(downloads_dir, subdir)
            try:
                shutil.rmtree(subdir_path)
                logger.info(f"Deleted download directory: {subdir}")
            except Exception as e:
                logger.error(f"Error deleting directory {subdir}: {e}")
    except Exception as e:
        logger.error(f"Error listing downloads directory: {e}")

if __name__ == "__main__":
    logger.info("Starting direct download fix...")
    clear_downloads()
    implement_direct_approach()
    logger.info("Direct download fix complete. Please restart your application.")

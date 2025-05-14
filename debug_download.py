import os
import sys
import logging
import json
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("debug_download.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def check_downloads_directory():
    """Check the downloads directory structure and permissions"""
    downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
    logger.info(f"Checking downloads directory: {downloads_dir}")
    
    if not os.path.exists(downloads_dir):
        logger.error(f"Downloads directory does not exist: {downloads_dir}")
        os.makedirs(downloads_dir, exist_ok=True)
        logger.info(f"Created downloads directory: {downloads_dir}")
    
    # Check permissions
    try:
        permissions = oct(os.stat(downloads_dir).st_mode)[-3:]
        logger.info(f"Downloads directory permissions: {permissions}")
        
        # Test write access
        test_file = os.path.join(downloads_dir, 'test_write.txt')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        logger.info("Write test to downloads directory succeeded")
    except Exception as e:
        logger.error(f"Error checking downloads directory: {str(e)}")
    
    # List subdirectories
    subdirs = [d for d in os.listdir(downloads_dir) if os.path.isdir(os.path.join(downloads_dir, d))]
    logger.info(f"Found {len(subdirs)} subdirectories in downloads directory")
    
    # Check the content of each subdirectory
    for subdir in subdirs:
        subdir_path = os.path.join(downloads_dir, subdir)
        files = list(Path(subdir_path).glob('*'))
        logger.info(f"Subdirectory {subdir} contains {len(files)} files:")
        
        for file_path in files:
            try:
                size = os.path.getsize(file_path)
                logger.info(f"  - {file_path.name}: {size} bytes")
                
                # Check if file is complete
                if size > 0:
                    logger.info(f"File seems complete based on size")
                else:
                    logger.warning(f"File has zero size, might be incomplete")
            except Exception as e:
                logger.error(f"Error checking file {file_path}: {str(e)}")

def check_download_state():
    """Check the download state file"""
    state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads', 'downloads_state.json')
    logger.info(f"Checking downloads state file: {state_file}")
    
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                downloads = json.load(f)
                logger.info(f"Found {len(downloads)} downloads in state file")
                
                # Analyze each download
                for download_id, download_info in downloads.items():
                    logger.info(f"Download ID: {download_id}")
                    logger.info(f"  Status: {download_info.get('status', 'unknown')}")
                    logger.info(f"  Format type: {download_info.get('format_type', 'unknown')}")
                    logger.info(f"  Progress: {download_info.get('progress', 0)}%")
                    logger.info(f"  Output file: {download_info.get('output_file', 'N/A')}")
                    
                    # Check if the output file exists and is accessible
                    output_file = download_info.get('output_file')
                    if output_file and os.path.exists(output_file):
                        size = os.path.getsize(output_file)
                        logger.info(f"  Output file exists: {size} bytes")
                        
                        # Try to open the file
                        try:
                            with open(output_file, 'rb') as test_f:
                                test_f.read(1024)  # Try to read a small chunk
                            logger.info("  File can be read successfully")
                        except Exception as e:
                            logger.error(f"  ERROR: Cannot read file: {str(e)}")
                    elif output_file:
                        logger.error(f"  ERROR: Output file does not exist: {output_file}")
                    else:
                        logger.warning("  No output file specified")
        except Exception as e:
            logger.error(f"Error reading downloads state file: {str(e)}")
    else:
        logger.warning(f"Downloads state file does not exist: {state_file}")

def fix_direct_file_endpoint():
    """Fix the direct file endpoint in app.py"""
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
    logger.info(f"Updating app.py to fix direct file endpoint: {app_path}")
    
    with open(app_path, 'r') as f:
        content = f.read()
    
    if '@app.route(\'/api/direct-file/<download_id>\'' in content:
        logger.info("Found direct-file endpoint, updating with better error handling...")
        
        # Find the start of the route function
        start_idx = content.find('@app.route(\'/api/direct-file/<download_id>\'')
        if start_idx == -1:
            logger.error("Could not find direct-file endpoint")
            return False
        
        # Find the beginning of the try block
        try_idx = content.find('try:', start_idx)
        if try_idx == -1:
            logger.error("Could not find try block in direct-file endpoint")
            return False
        
        # Find where to insert our additional logging
        generate_idx = content.find('def generate():', try_idx)
        if generate_idx == -1:
            logger.error("Could not find generate function in direct-file endpoint")
            return False
        
        # Create the improved function with thorough error checking
        improved_function = '''@app.route('/api/direct-file/<download_id>', methods=['GET'])
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
        return jsonify({'error': str(e)}), 500'''
        
        # Replace the existing function
        function_end_idx = content.find('@app.route', try_idx)
        if function_end_idx == -1:
            function_end_idx = content.find('# Cleanup old downloads', try_idx)
        
        if function_end_idx > 0:
            before = content[:start_idx]
            after = content[function_end_idx:]
            new_content = before + improved_function + '\n\n' + after
            
            with open(app_path, 'w') as f:
                f.write(new_content)
            
            logger.info("Updated direct-file endpoint with improved error handling")
            return True
        else:
            logger.error("Could not determine end of direct-file function")
            return False
    else:
        logger.error("Direct-file endpoint not found in app.py")
        return False

if __name__ == "__main__":
    logger.info("Starting download debugging...")
    check_downloads_directory()
    check_download_state()
    fix_direct_file_endpoint()
    logger.info("Debug complete. Please check the logs and restart your application.")

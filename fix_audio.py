import os
import logging
import sys
import shutil
import re

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='fix_audio.log',
    filemode='w'
)
logger = logging.getLogger()
logger.addHandler(logging.StreamHandler())

def update_youtube_downloader():
    """Update the YouTube downloader to ensure audio is converted to MP3"""
    downloader_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'utils', 'youtube_downloader_new.py')
    backup_path = downloader_path + '.backup'
    
    # Create backup
    logger.info(f"Backing up youtube_downloader_new.py to {backup_path}")
    shutil.copy2(downloader_path, backup_path)
    
    # Read the file
    with open(downloader_path, 'r') as f:
        content = f.read()
    
    # Look for the audio download section
    if "format_type == 'audio'" in content:
        logger.info("Found audio download section, updating...")
        
        # Find the current audio download command
        audio_command_pattern = r"""local_command = \[\s*sys\.executable, '-m', 'yt_dlp',\s*'-f', 'bestaudio',\s*'-x', '--audio-format', 'mp3',\s*'--audio-quality', '0',\s*# Use a more compatible audio codec\s*'--postprocessor-args', ".*?",\s*'-o', output_file,\s*'--newline',\s*url\s*\]"""
        
        # New improved audio download command
        new_audio_command = """local_command = [
                    sys.executable, '-m', 'yt_dlp',
                    '-f', 'bestaudio',
                    '-x', '--audio-format', 'mp3',
                    '--audio-quality', '0',
                    # Force to use ffmpeg for extraction and make sure we get mp3
                    '--extract-audio',
                    '--postprocessor-args', "-codec:a libmp3lame -q:a 2 -ac 2 -ar 44100",
                    '--force-overwrites',
                    '-o', output_file,
                    '--newline',
                    url
                ]"""
        
        # Use regex to replace the command with more flexible matching
        updated_content = re.sub(audio_command_pattern, new_audio_command, content, flags=re.DOTALL)
        
        # Write the updated file
        with open(downloader_path, 'w') as f:
            f.write(updated_content)
        
        logger.info("Updated audio download command in youtube_downloader_new.py")
        return True
    else:
        logger.error("Could not find audio download section in youtube_downloader_new.py")
        return False

def update_app_logging():
    """Update app.py to add more logging for debugging"""
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
    
    # Read the file
    with open(app_path, 'r') as f:
        content = f.read()
    
    # Add more detailed logging to the download route
    if "@app.route('/api/download'" in content:
        logger.info("Found download API route, adding more logging...")
        
        download_route_pattern = r"""@app.route\('/api/download', methods=\['POST'\]\)\s*def download_video\(\):\s*"""
        
        # Find the existing function start
        match = re.search(download_route_pattern, content)
        if match:
            # Find where the try block starts
            try_start = content.find("try:", match.end())
            if try_start > 0:
                # Add detailed logging after the try statement
                improved_logging = """try:
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
        """
                
                # Replace the original try block
                original_try = content[try_start:try_start+3]
                updated_content = content.replace(content[try_start:try_start+3], improved_logging, 1)
                
                # Write the updated file
                with open(app_path, 'w') as f:
                    f.write(updated_content)
                
                logger.info("Added detailed logging to app.py")
                return True
    
    logger.error("Could not find download API route in app.py")
    return False

if __name__ == "__main__":
    logger.info("Starting audio format fix")
    update_youtube_downloader()
    update_app_logging()
    logger.info("Audio format fix complete. Please restart your application.")

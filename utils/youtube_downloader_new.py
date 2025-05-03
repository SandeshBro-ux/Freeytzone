import os
import uuid
import json
import logging
import subprocess
import threading
import time
import datetime
import shutil
from urllib.parse import urlparse, parse_qs
import requests
from pathlib import Path

# Configure logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)  # Set to DEBUG for detailed logs

class YouTubeDownloader:
    def __init__(self, temp_dir):
        """Initialize YouTubeDownloader with a temporary directory"""
        self.temp_dir = temp_dir
        self.downloads = {}  # Store active downloads
        
        # Create temp dir if it doesn't exist
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Check if yt-dlp is installed
        try:
            subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True, check=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.error("yt-dlp is not installed or not in PATH. Please install it.")
            
        # Create downloads state file path
        self.downloads_state_file = os.path.join(self.temp_dir, 'downloads_state.json')
        
        # Load existing downloads if any (for persistence between restarts)
        self._load_downloads()
        
    def _load_downloads(self):
        """Load existing downloads from state file"""
        try:
            if os.path.exists(self.downloads_state_file):
                with open(self.downloads_state_file, 'r') as f:
                    self.downloads = json.load(f)
                    logger.debug(f"Loaded {len(self.downloads)} downloads from state file")
        except Exception as e:
            logger.error(f"Error loading downloads state: {str(e)}")
            self.downloads = {}
            
    def _save_downloads(self):
        """Save downloads state to file"""
        try:
            # Create a copy of downloads without process objects (not serializable)
            downloads_copy = {}
            for download_id, download_info in self.downloads.items():
                download_copy = download_info.copy()
                if 'process' in download_copy:
                    del download_copy['process']
                downloads_copy[download_id] = download_copy
                
            with open(self.downloads_state_file, 'w') as f:
                json.dump(downloads_copy, f)
        except Exception as e:
            logger.error(f"Error saving downloads state: {str(e)}")
            
    def cleanup_old_downloads(self, max_age_seconds=3600):
        """Clean up old download directories and entries"""
        try:
            current_time = time.time()
            expired_ids = []
            
            # Identify expired downloads
            for download_id, download_info in self.downloads.items():
                start_time = download_info.get('start_time', 0)
                age = current_time - start_time
                
                if age > max_age_seconds:
                    expired_ids.append(download_id)
            
            # Remove expired downloads
            for download_id in expired_ids:
                download_path = os.path.join(self.temp_dir, download_id)
                try:
                    if os.path.exists(download_path):
                        if os.path.isdir(download_path):
                            # Use os.rmdir for directories or manually remove files as fallback
                            try:
                                for root, dirs, files in os.walk(download_path, topdown=False):
                                    for file in files:
                                        os.remove(os.path.join(root, file))
                                    for dir in dirs:
                                        os.rmdir(os.path.join(root, dir))
                                os.rmdir(download_path)
                            except Exception as e:
                                logger.error(f"Error recursively removing directory: {str(e)}")
                        else:
                            os.remove(download_path)
                    del self.downloads[download_id]
                    logger.debug(f"Cleaned up expired download: {download_id}")
                except Exception as e:
                    logger.error(f"Error cleaning up download {download_id}: {str(e)}")
            
            # Save updated state
            if expired_ids:
                self._save_downloads()
                
            return len(expired_ids)
        except Exception as e:
            logger.error(f"Error in cleanup_old_downloads: {str(e)}")
            return 0
            
    def _is_valid_youtube_url(self, url):
        """Validate if the URL is a valid YouTube URL"""
        try:
            parsed_url = urlparse(url)
            
            # Check if domain is youtube.com or youtu.be
            if parsed_url.netloc not in ['www.youtube.com', 'youtube.com', 'youtu.be']:
                return False
                
            # Check if the URL has a video ID
            if parsed_url.netloc in ['www.youtube.com', 'youtube.com']:
                query = parse_qs(parsed_url.query)
                return 'v' in query
            elif parsed_url.netloc == 'youtu.be':
                return len(parsed_url.path) > 1
                
            return False
        except Exception as e:
            logger.error(f"Error validating URL: {str(e)}")
            return False
    
    def get_video_info(self, url):
        """Get information about a YouTube video"""
        try:
            if not self._is_valid_youtube_url(url):
                raise ValueError("Invalid YouTube URL")
                
            command = [
                'yt-dlp',
                '--dump-json',
                '--no-playlist',
                url
            ]
            
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            
            # Extract relevant information
            formats = []
            # Group formats with same resolution
            resolution_formats = {}
            
            # Add a default best quality option
            resolution_formats['best'] = {
                'format_id': 'best',
                'resolution': 'Best quality (auto)',
                'fps': None,
                'filesize': None
            }
            
            # Extract format information
            has_high_quality = False
            
            # Add audio-only format first
            for fmt in info.get('formats', []):
                if fmt and fmt.get('vcodec') == 'none' and fmt.get('acodec') != 'none':
                    # Audio only format - get the best one
                    if 'audio_only' not in resolution_formats:
                        resolution_formats['audio_only'] = {
                            'format_id': fmt.get('format_id', 'bestaudio'),
                            'resolution': 'audio_only',
                            'fps': None,
                            'filesize': fmt.get('filesize', 0)
                        }
                    break
                
            # Get available video formats
            for fmt in info.get('formats', []):
                if not fmt:
                    continue
                    
                # Extract video formats - we'll merge with audio during download
                if fmt.get('vcodec') != 'none':
                    height = fmt.get('height')
                    if height and height >= 720:  # Only include HD formats and above
                        width = fmt.get('width', 0) or 0  # Handle None value
                        resolution = f"{width}x{height}"
                        if resolution not in resolution_formats:
                            resolution_formats[resolution] = {
                                'format_id': fmt.get('format_id', ''),
                                'resolution': resolution,
                                'fps': fmt.get('fps'),
                                'filesize': fmt.get('filesize', 0)
                            }
                        if height >= 1440:  # 2K or better
                            has_high_quality = True
            
            # If no 2K quality found, update the "best" option description
            if not has_high_quality:
                max_height = 0
                for fmt_key in resolution_formats:
                    if 'x' in fmt_key:
                        try:
                            height = int(fmt_key.split('x')[1])
                            max_height = max(max_height, height)
                        except (ValueError, IndexError):
                            pass
                
                if max_height > 0:
                    max_resolution = "1080p" if max_height == 1080 else f"{max_height}p"
                    resolution_formats['best']['resolution'] = f"Best quality (up to {max_resolution})"
            else:
                resolution_formats['best']['resolution'] = f"Best quality (up to 2K)"
            
            # Convert to list and sort by resolution
            formats = list(resolution_formats.values())
            
            # Sort formats by resolution (highest first, with "best" at the top)
            def format_sort_key(fmt):
                res = fmt.get('resolution', '')
                if not res:
                    return 0
                
                # Put "best" at the top
                if res.startswith('Best'):
                    return 10000
                
                # Put audio at the bottom
                if res == 'audio_only':
                    return -1
                
                # Sort video formats by height
                if 'x' in res:
                    try:
                        height = int(res.split('x')[1])
                        return height
                    except (ValueError, IndexError):
                        pass
                
                return 0
            
            formats.sort(key=format_sort_key, reverse=True)
            
            # Extract thumbnail info
            thumbnails = []
            for thumb in info.get('thumbnails', []):
                if not thumb:
                    continue
                
                url = thumb.get('url')
                if url:
                    width = thumb.get('width', 0) or 0  # Default to 0 if None
                    height = thumb.get('height', 0) or 0  # Default to 0 if None
                    thumbnails.append({
                        'url': url,
                        'width': width,
                        'height': height
                    })
            
            # Sort thumbnails by resolution (highest first)
            thumbnails.sort(key=lambda x: (x.get('width', 0) or 0) * (x.get('height', 0) or 0), reverse=True)
            
            return {
                'title': info.get('title', 'Unknown Title'),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown Uploader'),
                'view_count': info.get('view_count', 0),
                'formats': formats,
                'thumbnails': thumbnails,
                'video_id': info.get('id', '')
            }
            
        except subprocess.SubprocessError as e:
            logger.error(f"Error getting video info: {str(e)}")
            error_msg = str(e)
            raise ValueError(f"Error getting video info: {error_msg}")
        except json.JSONDecodeError:
            logger.error("Could not parse video information")
            raise ValueError("Could not parse video information")
        except Exception as e:
            logger.error(f"Unexpected error getting video info: {str(e)}")
            raise ValueError(f"Unexpected error: {str(e)}")
    
    def _download_thread(self, download_id, url, format_type, quality):
        """Download thread function for background download processing"""
        try:
            if download_id not in self.downloads:
                logger.error(f"Download ID not found: {download_id}")
                return
                
            download_info = self.downloads[download_id]
            download_info['status'] = 'downloading'
            
            output_path = os.path.join(self.temp_dir, download_id)
            os.makedirs(output_path, exist_ok=True)
            
            local_command = None  # Initialize command variable
            
            if format_type == 'video':
                if quality == 'best':
                    # Specifically target 2K (1440p) or better quality with both video and audio
                    # Filter to avoid problematic Opus audio formats
                    format_str = 'bestvideo[height>=1440]+bestaudio[acodec!=opus]/bestvideo[height>=1080]+bestaudio[acodec!=opus]/best'
                else:
                    # Extract height from quality string (e.g., 1920x1080 -> 1080)
                    height = quality.split('x')[1] if 'x' in quality else quality
                    format_str = f'bestvideo[height<={height}]+bestaudio[acodec!=opus]/best[height<={height}]'
                
                logger.debug(f"Using format string: {format_str}")
                
                output_file = os.path.join(output_path, '%(title)s.%(ext)s')
                local_command = [
                    'yt-dlp',
                    '-f', format_str,
                    '--merge-output-format', 'mp4',  # Force output to be mp4
                    '--verbose',  # Add verbose output for debugging
                    # Force audio to be converted to AAC for better browser compatibility
                    '--postprocessor-args', "-c:a aac -b:a 192k", 
                    '-o', output_file,
                    '--newline',
                    url
                ]
                
                # Log the command for debugging
                logger.debug(f"Video download command: {' '.join(local_command)}")
                
                download_info['expected_extension'] = 'mp4'
                download_info['mime_type'] = 'video/mp4'
                
            elif format_type == 'audio':
                output_file = os.path.join(output_path, '%(title)s.%(ext)s')
                local_command = [
                    'yt-dlp',
                    '-f', 'bestaudio',
                    '-x', '--audio-format', 'mp3',
                    '--audio-quality', '0',
                    # Use a more compatible audio codec
                    '--postprocessor-args', "-codec:a libmp3lame -q:a 0",
                    '-o', output_file,
                    '--newline',
                    url
                ]
                
                logger.debug(f"Audio download command: {' '.join(local_command)}")
                
                download_info['expected_extension'] = 'mp3'
                download_info['mime_type'] = 'audio/mpeg'
                
            elif format_type == 'thumbnail':
                # Get video info to get the best thumbnail
                video_info = self.get_video_info(url)
                
                if not video_info.get('thumbnails'):
                    raise ValueError("No thumbnails found for this video")
                
                # Get the best quality thumbnail
                best_thumbnail = video_info['thumbnails'][0]
                thumbnail_url = best_thumbnail['url']
                
                # Download the thumbnail
                response = requests.get(thumbnail_url, stream=True)
                if response.status_code != 200:
                    raise ValueError(f"Failed to download thumbnail: HTTP {response.status_code}")
                
                # Generate a safe filename
                title = video_info.get('title', 'thumbnail')
                filename = f"{title}_thumbnail.jpg"
                # Remove invalid characters from filename
                filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
                file_path = os.path.join(output_path, filename)
                
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                download_info['output_file'] = file_path
                download_info['filename'] = filename
                download_info['mime_type'] = 'image/jpeg'
                download_info['status'] = 'completed'
                download_info['progress'] = 100
                return
            
            # If we get here, we should have a command for video or audio download
            if not local_command:
                raise ValueError("No download command generated")
                
            process = subprocess.Popen(
                local_command,
                stderr=subprocess.STDOUT,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            download_info['process'] = process
            
            # Process output if stdout is available
            if process and process.stdout:
                for line in iter(process.stdout.readline, ''):
                    if download_info.get('status') == 'canceled':
                        process.terminate()
                        break
                        
                    if '[download]' in line and '%' in line:
                        try:
                            progress_part = line.split('[download]')[1].strip()
                            percentage = float(progress_part.split('%')[0].strip())
                            download_info['progress'] = percentage
                            
                            # Extract speed and ETA if available
                            if 'ETA' in line:
                                speed_part = line.split('at')[1].split('ETA')[0].strip()
                                eta_part = line.split('ETA')[1].strip()
                                download_info['speed'] = speed_part
                                download_info['eta'] = eta_part
                        except (ValueError, IndexError) as e:
                            logger.debug(f"Error parsing progress: {str(e)}")
                            pass
                    elif 'Destination:' in line:
                        try:
                            destination = line.split('Destination:')[1].strip()
                            download_info['output_file'] = destination
                            filename = os.path.basename(destination)
                            download_info['filename'] = filename
                        except (ValueError, IndexError) as e:
                            logger.debug(f"Error parsing destination: {str(e)}")
                            pass
            
            # Wait for process to complete
            return_code = process.wait()
            logger.debug(f"Download process returned code: {return_code}")
            
            if return_code == 0 and download_info.get('status') != 'canceled':
                download_info['status'] = 'completed'
                download_info['progress'] = 100
                
                # If we didn't get the output file from stdout, try to find it
                if 'output_file' not in download_info:
                    files = list(Path(output_path).glob('*'))
                    logger.debug(f"Files in output directory: {[str(f) for f in files]}")
                    
                    if files:
                        download_info['output_file'] = str(files[0])
                        download_info['filename'] = files[0].name
                        logger.debug(f"Found output file: {download_info['output_file']}")
                else:
                    logger.debug(f"Output file from stdout: {download_info.get('output_file')}")
                
                # Check for the file with alternate extensions
                file_found = False
                if 'output_file' in download_info:
                    # Try the extracted filename first
                    if os.path.exists(download_info['output_file']):
                        file_found = True
                        logger.debug(f"Verified output file exists: {download_info['output_file']}")
                        file_size = os.path.getsize(download_info['output_file'])
                        logger.debug(f"File size: {file_size} bytes")
                    else:
                        # Try to locate the file with different extension
                        base_path = os.path.splitext(download_info['output_file'])[0]
                        for ext in ['.mp4', '.webm', '.mkv']:
                            test_path = f"{base_path}{ext}"
                            if os.path.exists(test_path):
                                download_info['output_file'] = test_path
                                download_info['filename'] = os.path.basename(test_path)
                                file_found = True
                                logger.debug(f"Found file with different extension: {test_path}")
                                file_size = os.path.getsize(test_path)
                                logger.debug(f"File size: {file_size} bytes")
                                break
                
                # If we couldn't find the file in the output directory, try to find any video file
                if not file_found:
                    files = list(Path(output_path).glob('*.*'))
                    video_files = [f for f in files if f.suffix.lower() in ['.mp4', '.webm', '.mkv']]
                    logger.debug(f"Looking for video files. Found: {[str(f) for f in video_files]}")
                    
                    if video_files:
                        download_info['output_file'] = str(video_files[0])
                        download_info['filename'] = video_files[0].name
                        file_found = True
                        logger.debug(f"Found video file: {download_info['output_file']}")
                
                if not file_found:
                    logger.error("Output file doesn't exist or wasn't found")
                    download_info['status'] = 'failed'
                    download_info['error'] = "Download completed but file not found"
                
                self._save_downloads()
            else:
                download_info['status'] = 'failed'
                error_msg = f"Download process exited with code {return_code}"
                logger.error(error_msg)
                download_info['error'] = error_msg
                
        except Exception as e:
            logger.error(f"Error in download thread: {str(e)}")
            if download_id in self.downloads:
                self.downloads[download_id]['status'] = 'failed'
                self.downloads[download_id]['error'] = str(e)
                self._save_downloads()
    
    def start_download(self, url, format_type, quality='best'):
        """Start a download process and return the download ID"""
        if not self._is_valid_youtube_url(url):
            raise ValueError("Invalid YouTube URL")
            
        if format_type not in ['video', 'audio', 'thumbnail']:
            raise ValueError("Invalid format type. Must be 'video', 'audio', or 'thumbnail'")
            
        download_id = str(uuid.uuid4())
        
        self.downloads[download_id] = {
            'url': url,
            'format_type': format_type,
            'quality': quality,
            'status': 'starting',
            'progress': 0,
            'speed': 'N/A',
            'eta': 'N/A',
            'start_time': time.time()
        }
        
        # Save downloads state for persistence
        self._save_downloads()
        
        # Start download in background thread
        thread = threading.Thread(
            target=self._download_thread,
            args=(download_id, url, format_type, quality)
        )
        thread.daemon = True
        thread.start()
        
        return download_id
    
    def get_progress(self, download_id):
        """Get the progress of a download"""
        if download_id not in self.downloads:
            raise ValueError("Download ID not found")
            
        download_info = self.downloads[download_id]
        return {
            'status': download_info.get('status', 'unknown'),
            'progress': download_info.get('progress', 0),
            'speed': download_info.get('speed', 'N/A'),
            'eta': download_info.get('eta', 'N/A'),
            'format_type': download_info.get('format_type', ''),
            'elapsed': int(time.time() - download_info.get('start_time', time.time()))
        }
    
    def get_download_file(self, download_id):
        """Get the path to the downloaded file"""
        if download_id not in self.downloads:
            return None, None, None
            
        download_info = self.downloads[download_id]
        
        if download_info.get('status') != 'completed':
            return None, None, None
            
        return (
            download_info.get('output_file', None),
            download_info.get('filename', None),
            download_info.get('mime_type', None)
        )
    
    def cancel_download(self, download_id):
        """Cancel an ongoing download"""
        if download_id not in self.downloads:
            return False
            
        download_info = self.downloads[download_id]
        
        if download_info.get('status') in ['completed', 'failed', 'canceled']:
            return True
            
        download_info['status'] = 'canceled'
        
        # Terminate the process if it exists
        process = download_info.get('process')
        if process:
            try:
                process.terminate()
            except Exception as e:
                logger.error(f"Error terminating process: {str(e)}")
                
        # Save the updated state
        self._save_downloads()
                
        return True
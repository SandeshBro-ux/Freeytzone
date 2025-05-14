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
import sys

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
            subprocess.run([sys.executable, '-m', 'yt_dlp', '--version'], capture_output=True, text=True, check=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.error("yt-dlp is not installed or not in PATH. Please install it.")
        # Check if ffmpeg is installed (required for merging audio and video)
        self.ffmpeg_available = True
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, check=True)
            logger.debug("ffmpeg is available")
        except (subprocess.SubprocessError, FileNotFoundError):
            self.ffmpeg_available = False
            logger.error("ffmpeg is not installed or not in PATH. Please install ffmpeg to enable merging of video and audio streams.")
            
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
        # Validate URL
        if not self._is_valid_youtube_url(url):
            raise ValueError("Invalid YouTube URL")
        # Use Python yt_dlp binding
        try:
            import yt_dlp
        except ImportError:
            raise ValueError("yt-dlp Python module not installed. Please install with 'python -m pip install yt-dlp'.")
        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        # Build formats list grouped by resolution
        resolution_formats = {'best': {'format_id': 'best', 'resolution': 'Best quality (auto)', 'fps': None, 'filesize': None}}
        has_high_quality = False
        # Audio-only format
        for fmt in info.get('formats', []):
            if fmt.get('vcodec') == 'none' and fmt.get('acodec') != 'none':
                resolution_formats['audio_only'] = {
                    'format_id': fmt.get('format_id'),
                    'resolution': 'audio_only',
                    'fps': None,
                    'filesize': fmt.get('filesize', 0)
                }
                break
        # Video formats (HD and above)
        for fmt in info.get('formats', []):
            if fmt.get('vcodec') != 'none':
                height = fmt.get('height') or 0
                if height >= 720:
                    width = fmt.get('width') or 0
                    res = f"{width}x{height}"
                    resolution_formats[res] = {
                        'format_id': fmt.get('format_id'),
                        'resolution': res,
                        'fps': fmt.get('fps'),
                        'filesize': fmt.get('filesize', 0)
                    }
                    if height >= 1440:
                        has_high_quality = True
        # Update "best" description
        if not has_high_quality:
            max_h = max((int(k.split('x')[1]) for k in resolution_formats if 'x' in k), default=0)
            if max_h > 0:
                pr = "1080p" if max_h == 1080 else f"{max_h}p"
                resolution_formats['best']['resolution'] = f"Best quality (up to {pr})"
        else:
            resolution_formats['best']['resolution'] = 'Best quality (up to 2K)'
        # Convert to list and sort
        formats = list(resolution_formats.values())
        def fskey(f):
            r = f.get('resolution', '')
            if r.startswith('Best'): return 10000
            if r == 'audio_only': return -1
            if 'x' in r:
                try:
                    return int(r.split('x')[1])
                except:
                    return 0
            return 0
        formats.sort(key=fskey, reverse=True)
        # Thumbnails
        thumbnails = []
        for thumb in info.get('thumbnails', []):
            url = thumb.get('url')
            if url:
                w = thumb.get('width') or 0
                h = thumb.get('height') or 0
                thumbnails.append({'url': url, 'width': w, 'height': h})
        thumbnails.sort(key=lambda t: t['width'] * t['height'], reverse=True)
        # Return info
        result = {
            'title': info.get('title', 'Unknown Title'),
            'duration': info.get('duration', 0),
            'uploader': info.get('uploader', 'Unknown Uploader'),
            'view_count': info.get('view_count', 0),
            'like_count': info.get('like_count', 0),
            'dislike_count': info.get('dislike_count', 0),
            'formats': formats,
            'thumbnails': thumbnails,
            'video_id': info.get('id', '')
        }
        # Fetch channel logo via YouTube Data API if channel_id and API key are available
        channel_id = info.get('channel_id') or info.get('uploader_id')
        api_key = os.getenv('YOUTUBE_API_KEY')
        result['subscriber_count'] = 'N/A'  # Default if we can't retrieve it
        if channel_id and api_key:
            try:
                api_url = 'https://www.googleapis.com/youtube/v3/channels'
                params = {'part': 'snippet,statistics', 'id': channel_id, 'key': api_key}
                resp = requests.get(api_url, params=params, timeout=5)
                resp.raise_for_status()
                items = resp.json().get('items', [])
                if items:
                    thumb_obj = items[0]['snippet']['thumbnails'].get('default') or {}
                    logo_url = thumb_obj.get('url')
                    if logo_url:
                        result['channel_logo'] = logo_url
                    # Try to get subscriber count
                    if 'statistics' in items[0]:
                        sub_count = items[0]['statistics'].get('subscriberCount')
                        if sub_count:
                            result['subscriber_count'] = int(sub_count)
            except Exception as e:
                logger.debug(f"Could not fetch channel logo: {e}")
        return result
    
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
                # Ensure ffmpeg is available for merging streams
                if not getattr(self, 'ffmpeg_available', False):
                    logger.error("ffmpeg is not available; cannot merge video and audio.")
                    download_info['status'] = 'failed'
                    download_info['error'] = 'ffmpeg not found in PATH'
                    self._save_downloads()
                    return
                if quality == 'best':
                    # Select best video and best audio streams; yt-dlp will recode to mp4 (AAC) below
                    format_str = 'bestvideo[height>=1440]+bestaudio/best'
                else:
                    # Extract height from quality string (e.g., 1920x1080 -> 1080)
                    height = quality.split('x')[1] if 'x' in quality else quality
                    # Select video at the requested resolution plus best audio stream
                    format_str = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]'
                
                logger.debug(f"Using format string: {format_str}")
                
                output_file = os.path.join(output_path, '%(title)s.%(ext)s')
                # Build yt-dlp command for video download, support custom ffmpeg location
                ffmpeg_loc = os.getenv('FFMPEG_PATH')
                base_cmd = [sys.executable, '-m', 'yt_dlp']
                if ffmpeg_loc:
                    base_cmd.extend(['--ffmpeg-location', ffmpeg_loc])
                # Use yt-dlp's recode-video to produce an MP4 (with AAC audio)
                local_command = base_cmd + [
                    '-f', format_str,
                    '--recode-video', 'mp4',
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
                    sys.executable, '-m', 'yt_dlp',
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
                # Use template with dynamic extension from yt-dlp conversion
                thumbnail_output_template = os.path.join(output_path, '%(title)s_thumbnail.%(ext)s')
                
                local_command = [
                    sys.executable, '-m', 'yt_dlp',
                    '--write-thumbnail',  # Tell yt-dlp to download the thumbnail
                    '--convert-thumbnails', 'png', # Convert thumbnail to PNG
                    '--skip-download',    # Don't download video/audio
                    '-o', thumbnail_output_template,
                    '--newline',
                    url
                ]
                logger.debug(f"Thumbnail download command: {' '.join(local_command)}")
                
                # Mime type will be determined after download, default or use common
                download_info['expected_extension'] = 'png' 
                download_info['mime_type'] = 'image/png'
            
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
                download_info['eta'] = 'Done'  # Finalize ETA
                download_info['speed'] = 'Complete' # Finalize Speed
                
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
                        # For thumbnails, primary extension is png. For videos, mp4, webm, mkv.
                        possible_extensions = ['.png'] if format_type == 'thumbnail' else ['.mp4', '.webm', '.mkv']
                        for ext in possible_extensions:
                            test_path = f"{os.path.splitext(download_info['output_file'])[0]}{ext}"
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
                    # Adjust search for thumbnail or video files
                    if format_type == 'thumbnail':
                        target_files = [f for f in files if f.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp']]
                        logger.debug(f"Looking for thumbnail files. Found: {[str(f) for f in target_files]}")
                    else:
                        target_files = [f for f in files if f.suffix.lower() in ['.mp4', '.webm', '.mkv']]
                        logger.debug(f"Looking for video files. Found: {[str(f) for f in target_files]}")
                    
                    if target_files:
                        download_info['output_file'] = str(target_files[0])
                        download_info['filename'] = target_files[0].name
                        file_found = True
                        logger.debug(f"Found target file: {download_info['output_file']}")
                
                if not file_found:
                    logger.error("Output file doesn't exist or wasn't found")
                    download_info['status'] = 'failed'
                    download_info['error'] = "Download completed but file not found"
                elif format_type == 'thumbnail' and file_found:
                    # For thumbnails, update mime_type based on actual extension
                    actual_ext = Path(download_info['output_file']).suffix.lower()
                    if actual_ext == '.jpg' or actual_ext == '.jpeg':
                        download_info['mime_type'] = 'image/jpeg'
                    elif actual_ext == '.png':
                        download_info['mime_type'] = 'image/png'
                        # Fix double .png.png extension issue
                        orig_path = download_info['output_file']
                        if '.png.png' in orig_path:
                            fixed_path = orig_path.replace('.png.png', '.png')
                                try:
                                    os.rename(orig_path, fixed_path)
                                download_info['output_file'] = fixed_path
                                download_info['filename'] = os.path.basename(fixed_path)
                                logger.debug(f"Fixed double .png extension by renaming to {fixed_path}")
                            except Exception as e:
                                logger.error(f"Failed to rename double .png extension: {e}")
                    elif actual_ext == '.webp':
                        download_info['mime_type'] = 'image/webp'
                    else:
                        download_info['mime_type'] = 'application/octet-stream' # fallback
                    logger.debug(f"Thumbnail downloaded with extension {actual_ext}, mime_type set to {download_info['mime_type']}")
                    # If thumbnail is not PNG, convert it to PNG via ffmpeg
                    if actual_ext != '.png' and getattr(self, 'ffmpeg_available', False):
                        orig_thumb = download_info['output_file']
                        # Remove any .png or .webp or .jpg extension before appending .png
                        base_thumb = os.path.splitext(orig_thumb)[0]
                        # If base_thumb already endswith .png, strip it
                        if base_thumb.endswith('.png'):
                            base_thumb = base_thumb[:-4]
                        png_thumb = base_thumb + '.png'
                        ffmpeg_cmd = ['ffmpeg', '-i', orig_thumb, '-y', png_thumb]
                        logger.debug(f"Converting thumbnail to PNG: {' '.join(ffmpeg_cmd)}")
                        try:
                            subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=True)
                            os.remove(orig_thumb)
                            download_info['output_file'] = png_thumb
                            download_info['filename'] = os.path.basename(png_thumb)
                            download_info['mime_type'] = 'image/png'
                            logger.debug("Thumbnail conversion to PNG completed")
                        except subprocess.SubprocessError as e:
                            logger.error(f"Thumbnail conversion to PNG failed: {e}")
                
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
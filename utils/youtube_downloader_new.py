import os
import uuid
import json
import logging
import subprocess
import threading
import time
import random
import shutil
from urllib.parse import urlparse, parse_qs
import requests
from pathlib import Path
import sys
import re
from dotenv import load_dotenv
import yt_dlp
import tempfile # For temporary cookie file
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Load environment variables from .env file
load_dotenv()

# Configure logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG if os.environ.get('DEBUG') else logging.INFO)  # Set to DEBUG for detailed logs

# Helper function to get Chrome path on Render
def get_chrome_path():
    """Get Chrome path on Render - prioritizing headless-chromium binary"""
    # First check for headless-chromium from Sparticuz in the home directory
    home_chrome_headless = os.path.join(os.path.expanduser('~'), 'chrome-bin', 'headless-chromium')
    if os.path.exists(home_chrome_headless):
        logger.info(f"Using Headless Chromium binary at: {home_chrome_headless}")
        return home_chrome_headless
    
    # Next check for standard Chrome in the home directory
    home_chrome = os.path.join(os.path.expanduser('~'), 'chrome-bin', 'chrome')
    if os.path.exists(home_chrome):
        logger.info(f"Using Chrome binary at: {home_chrome}")
        return home_chrome
    
    # Fallback to system Chrome
    logger.warning("No custom Chrome binary found, will attempt to use system Chrome (may fail on Render)")
    return None

# Helper function to get ChromeDriver path on Render
def get_chromedriver_path():
    home_chromedriver = os.path.join(os.path.expanduser('~'), 'chrome-bin', 'chromedriver')
    if os.path.exists(home_chromedriver):
        logger.info(f"Using ChromeDriver binary at: {home_chromedriver}")
        return home_chromedriver
    # Fallback to system ChromeDriver
    return None

# Setup Selenium WebDriver with appropriate options for the environment
def setup_chrome_driver():
    """Setup Chrome with extreme memory optimization for limited environments like Render"""
    chrome_options = Options()
    
    # Essential headless mode settings
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Critical memory optimization settings
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--single-process")  # Important for memory usage
    chrome_options.add_argument("--disable-setuid-sandbox")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--remote-debugging-port=9222")
    
    # Extreme memory optimization
    chrome_options.add_argument("--js-flags=--expose-gc")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--disable-features=site-per-process")
    chrome_options.add_argument("--disable-dev-tools")
    chrome_options.add_argument("--disable-browser-side-navigation")
    chrome_options.add_argument("--disable-default-apps")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-component-update")
    
    # Force low memory settings
    chrome_options.add_argument("--js-flags=--memory-reducer")
    chrome_options.add_argument("--aggressive-cache-discard")
    
    # Process optimization
    chrome_options.add_argument("--renderer-process-limit=1")
    
    # Limit JavaScript memory
    chrome_options.add_argument("--js-flags=--max-old-space-size=128")
    
    # Set small window size
    chrome_options.add_argument("--window-size=800,600")
    
    # Set custom binary path if available (for Render)
    chrome_binary = get_chrome_path()
    if chrome_binary:
        chrome_options.binary_location = chrome_binary
        logger.info(f"Set Chrome binary location to: {chrome_binary}")
    
    # Mimic a minimal browser with reduced fingerprint
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/114.0.0.0 Safari/537.36")
    
    # Add fingerprint randomization to avoid detection
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    # Add proxy if available
    proxy_url = os.getenv('YTDLP_PROXY_URL')
    if proxy_url:
        chrome_options.add_argument(f'--proxy-server={proxy_url}')
        logger.info(f"Using proxy for browser emulation: {proxy_url}")
    else:
        logger.info("No YTDLP_PROXY_URL. Proceeding without proxy.")
    
    # Create a clean temporary directory for Chrome
    chrome_tmp_dir = tempfile.mkdtemp()
    chrome_options.add_argument(f"--user-data-dir={chrome_tmp_dir}")
    logger.info(f"Created temporary Chrome profile at: {chrome_tmp_dir}")
    
    try:
        # First try to use the custom ChromeDriver path (for Render)
        chromedriver_path = get_chromedriver_path()
        if chromedriver_path:
            service = Service(executable_path=chromedriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info("Successfully initialized Chrome with custom ChromeDriver path")
            return driver, chrome_tmp_dir
        
        # If no custom ChromeDriver, try webdriver_manager (for local development)
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info("Successfully initialized Chrome with ChromeDriverManager")
            return driver, chrome_tmp_dir
        except Exception as e:
            logger.warning(f"Failed to use ChromeDriverManager: {e}. Trying default Chrome setup.")
            
        # Fall back to default Chrome setup
        driver = webdriver.Chrome(options=chrome_options)
        logger.info("Successfully initialized Chrome with default setup")
        return driver, chrome_tmp_dir
    except Exception as e:
        logger.error(f"All Chrome initialization methods failed: {e}")
        # Clean up temp directory if driver initialization failed
        try:
            shutil.rmtree(chrome_tmp_dir)
            logger.info(f"Cleaned up Chrome temporary directory after initialization failure")
        except Exception as cleanup_error:
            logger.warning(f"Failed to clean up Chrome temporary directory: {cleanup_error}")
        raise e

# Utility to convert human-readable sizes (e.g., '1.23MiB') to bytes
def parse_size(value_str, unit):
    """Convert human-readable sizes to bytes"""
    v = float(value_str)
    unit = unit.lower()
    if unit == 'kib': 
        return v * 1024
    if unit == 'mib': 
        return v * 1024**2
    if unit == 'gib': 
        return v * 1024**3
    return v

class YouTubeDownloader:
    def __init__(self, temp_dir):
        """Initialize YouTubeDownloader with a temporary directory"""
        self.temp_dir = temp_dir
        self.downloads = {}  # Store active downloads
        
        # Add thread lock for safe dictionary updates
        self.lock = threading.Lock()
        
        # Create temp dir if it doesn't exist
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Check if yt-dlp is installed (still needed for downloading)
        try:
            subprocess.run([sys.executable, '-m', 'yt_dlp', '--version'], capture_output=True, text=True, check=True)
            logger.debug("yt-dlp is available for downloading.")
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.error("yt-dlp is not installed or not in PATH. Downloading will fail. Please install it.")
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
                return 'v' in query and len(query['v'][0]) == 11
            elif parsed_url.netloc == 'youtu.be':
                return len(parsed_url.path) > 1 and len(parsed_url.path[1:]) == 11
                
            return False
        except Exception as e:
            logger.error(f"Error validating URL: {str(e)}")
            return False
    
    def _extract_video_id(self, url):
        """Extract video ID from YouTube URL"""
        parsed_url = urlparse(url)
        if parsed_url.netloc in ['www.youtube.com', 'youtube.com']:
            query = parse_qs(parsed_url.query)
            if 'v' in query and query['v'][0]:
                return query['v'][0]
        elif parsed_url.netloc == 'youtu.be':
            if parsed_url.path and len(parsed_url.path) > 1:
                return parsed_url.path[1:]
        return None
    
    def get_video_info(self, url):
        """Get information about a YouTube video using browser emulation to avoid bot detection"""
        if not self._is_valid_youtube_url(url):
            raise ValueError("Invalid YouTube URL")
        
        video_id = self._extract_video_id(url)
        if not video_id:
            raise ValueError("Could not extract video ID from URL")
        
        api_key = os.getenv('YOUTUBE_API_KEY')
        if not api_key:
            logger.warning("YOUTUBE_API_KEY not found. Channel info will be unavailable.")

        video_info = {}
        channel_info = {}
        detailed_formats_available = False
        info_source = 'api'
        temp_cookie_file_path = None
        
        # Check if browser emulation is disabled via environment variable
        browser_disabled = os.environ.get('DISABLE_BROWSER', '').lower() in ('true', '1', 'yes')
        if browser_disabled:
            logger.info("Browser emulation disabled by DISABLE_BROWSER environment variable")
        
        # Only try browser emulation if it's not disabled
        if not browser_disabled:
            driver, chrome_tmp_dir = None, None
            try:
                logger.debug(f"Attempting to fetch info with browser emulation for {url}")
                
                # Use our centralized Chrome setup function
                try:
                    driver, chrome_tmp_dir = setup_chrome_driver()
                    
                    # First visit YouTube homepage to establish a normal session
                    driver.get("https://www.youtube.com/")
                    time.sleep(random.uniform(1, 2))  # Shorter random delay to save memory
                    
                    # Perform some random scrolling to appear human-like
                    driver.execute_script(f"window.scrollTo(0, {random.randint(100, 200)});")
                    time.sleep(random.uniform(0.5, 1))  # Shorter delay
                    
                    # Now navigate to the actual video
                    driver.get(url)
                    
                    # Wait for video to load with a longer timeout for slower environments
                    try:
                        WebDriverWait(driver, 20).until(
                            EC.presence_of_element_located((By.ID, "movie_player"))
                        )
                        logger.info("Video player loaded successfully")
                    except Exception as e:
                        logger.warning(f"Waiting for video player timed out: {e}. Continuing anyway.")
                    
                    # Add more realistic interactions
                    time.sleep(random.uniform(1, 2))  # Shorter delay
                    
                    # Get cookies from browser session
                    cookies = driver.get_cookies()
                    logger.info(f"Retrieved {len(cookies)} cookies from browser session")
                    
                    # Create a temporary cookie file for yt-dlp
                    try:
                        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_cookie_file:
                            # Format cookies for yt-dlp
                            for cookie in cookies:
                                domain = cookie.get('domain', '')
                                if domain.startswith('.'):
                                    domain = domain[1:]
                                expires = cookie.get('expiry', 0)
                                secure = cookie.get('secure', False)
                                httpOnly = cookie.get('httpOnly', False)
                                tmp_cookie_file.write(f"{domain}\tTRUE\t{cookie.get('path', '/')}\t{str(secure).upper()}\t{expires}\t{cookie.get('name', '')}\t{cookie.get('value', '')}\n")
                            
                            temp_cookie_file_path = tmp_cookie_file.name
                            logger.info(f"Created cookie file from browser session: {temp_cookie_file_path}")
                    except Exception as cookie_error:
                        logger.error(f"Error creating cookie file: {cookie_error}")
                        temp_cookie_file_path = None
                    
                    # Force garbage collection to free memory
                    driver.execute_script("window.gc();")
                    
                    # Now use yt-dlp with the browser session cookies
                    ydl_opts = {
                        'quiet': True, 
                        'no_warnings': True, 
                        'skip_download': True,
                        'forceid': True, 
                        'extract_flat': 'discard_in_playlist',
                    }
                    
                    if temp_cookie_file_path:
                        ydl_opts['cookiefile'] = temp_cookie_file_path
                    
                    # Add proxy if available
                    proxy_url = os.getenv('YTDLP_PROXY_URL')
                    if proxy_url:
                        ydl_opts['proxy'] = proxy_url
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        raw_info = ydl.extract_info(url, download=False)
                    
                    if raw_info:
                        # Process video info
                        video_info['title'] = raw_info.get('title', 'Unknown Title')
                        video_info['uploader'] = raw_info.get('uploader', 'Unknown Uploader')
                        video_info['duration'] = raw_info.get('duration', 0)
                        video_info['view_count'] = raw_info.get('view_count', 0)
                        video_info['like_count'] = raw_info.get('like_count', 0)
                        video_info['video_id'] = raw_info.get('id', video_id)
                        video_info['channel_id'] = raw_info.get('channel_id')
                        
                        # Process formats
                        raw_formats = raw_info.get('formats', [])
                        processed_formats = []
                        
                        # Process audio formats
                        audio_formats_yt_dlp = [f for f in raw_formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
                        if audio_formats_yt_dlp:
                            best_audio = max(audio_formats_yt_dlp, key=lambda f: f.get('tbr', 0) or f.get('abr', 0), default=None)
                            if best_audio:
                                processed_formats.append({
                                    'format_id': best_audio.get('format_id'), 'resolution': 'Audio Only', 'fps': None, 
                                    'filesize': best_audio.get('filesize') or best_audio.get('filesize_approx'),
                                    'ext': best_audio.get('ext'), 'note': best_audio.get('format_note', 'Best Audio')
                                })
                        
                        # Process video formats with improved resolution detection
                        video_only_formats = []
                        merged_formats = []
                        
                        # First pass to identify all available formats
                        for f_item in raw_formats:
                            if f_item.get('vcodec') != 'none':
                                # Get resolution in consistent format
                                width = f_item.get('width')
                                height = f_item.get('height')
                                
                                if not width or not height:
                                    # Try to extract from resolution string
                                    resolution_str = f_item.get('resolution')
                                    if resolution_str and 'x' in resolution_str:
                                        try:
                                            width_str, height_str = resolution_str.split('x')
                                            width = int(width_str)
                                            height = int(height_str)
                                        except (ValueError, TypeError):
                                            continue
                                    else:
                                        continue
                                
                                # Format resolution consistently
                                res = f"{width}x{height}"
                                
                                # Create format entry
                                fmt_entry = {
                                    'format_id': f_item.get('format_id'), 
                                    'resolution': res,
                                    'fps': f_item.get('fps'), 
                                    'filesize': f_item.get('filesize') or f_item.get('filesize_approx'), 
                                    'ext': f_item.get('ext'),
                                    'note': f_item.get('format_note', f"{height}p"),
                                    'width': width,
                                    'height': height
                                }
                                
                                # Categorize as video-only or merged format
                                if f_item.get('acodec') != 'none': 
                                    merged_formats.append(fmt_entry)
                                else: 
                                    video_only_formats.append(fmt_entry)
                        
                        # Create categorized formats list with proper quality labeling
                        processed_video_formats = []
                        
                        # Add merged formats first (these have audio built-in)
                        if merged_formats:
                            # Sort by height and fps
                            sorted_merged = sorted(merged_formats, 
                                key=lambda x: (x.get('height', 0), x.get('fps', 0)), 
                                reverse=True)
                            processed_video_formats.extend(sorted_merged)
                        
                        # Add video-only formats 
                        if video_only_formats:
                            # Sort by height and fps
                            sorted_video_only = sorted(video_only_formats, 
                                key=lambda x: (x.get('height', 0), x.get('fps', 0)), 
                                reverse=True)
                            processed_video_formats.extend(sorted_video_only)
                        
                        # Extend the main formats list
                        processed_formats.extend(processed_video_formats)
                        
                        if processed_formats:
                            video_info['formats'] = processed_formats
                            detailed_formats_available = True
                            info_source = 'browser+yt-dlp'
                            logger.info(f"Successfully fetched detailed info with browser emulation for {url}")
                        else:
                            logger.warning(f"Browser+yt-dlp provided info but no usable formats for {url}. Falling back to API.")
                except Exception as browser_error:
                    logger.error(f"Error during browser setup or navigation: {browser_error}")
                finally:
                    # Close the browser
                    if driver:
                        driver.quit()
                        logger.info("Browser session closed")
                    
                    # Clean up temporary directory
                    if chrome_tmp_dir and os.path.exists(chrome_tmp_dir):
                        try:
                            shutil.rmtree(chrome_tmp_dir)
                            logger.info(f"Removed Chrome temporary directory: {chrome_tmp_dir}")
                        except Exception as tmp_dir_error:
                            logger.error(f"Error removing Chrome temporary directory: {tmp_dir_error}")
                    
                    # Clean up temporary cookie file
                    if temp_cookie_file_path and os.path.exists(temp_cookie_file_path):
                        try:
                            os.remove(temp_cookie_file_path)
                            logger.info(f"Removed temporary cookie file: {temp_cookie_file_path}")
                        except Exception as cookie_error:
                            logger.error(f"Error removing temporary cookie file: {cookie_error}")
            except Exception as e:
                logger.error(f"Browser emulation failed for {url}: {e}. Falling back to regular yt-dlp.")
        else:
            logger.info("Skipping browser emulation as it's disabled, using yt-dlp directly")
            
        # At this point, either browser emulation has failed or was skipped
        # Fall back to regular yt-dlp method
        temp_cookie_file_path = None
        proxy_url = os.getenv('YTDLP_PROXY_URL')
        
        try:
            logger.debug(f"Attempting fallback to direct yt-dlp for {url}")
            ydl_opts = {
                'quiet': True, 'no_warnings': True, 'skip_download': True,
                'forceid': True, 'extract_flat': 'discard_in_playlist',
            }
            cookies_content = os.getenv('YTDLP_COOKIES_CONTENT')
            if cookies_content:
                try:
                    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_cookie_file:
                        tmp_cookie_file.write(cookies_content)
                        temp_cookie_file_path = tmp_cookie_file.name
                    ydl_opts['cookiefile'] = temp_cookie_file_path
                    logger.info(f"Using temporary cookie file for yt-dlp fallback: {temp_cookie_file_path}")
                except Exception as e:
                    logger.error(f"Error creating or writing temporary cookie file: {e}")
            else:
                logger.info("No YTDLP_COOKIES_CONTENT. Proceeding without cookie file for yt-dlp fallback.")
            
            if proxy_url:
                ydl_opts['proxy'] = proxy_url
                logger.info(f"Using proxy for yt-dlp fallback: {proxy_url}")
            else:
                logger.info("No YTDLP_PROXY_URL. Proceeding without proxy for yt-dlp fallback.")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                raw_info = ydl.extract_info(url, download=False)
            
            # Process raw_info the same as in the browser approach
            if raw_info:
                # Process video info (same as browser approach)
                video_info['title'] = raw_info.get('title', 'Unknown Title')
                video_info['uploader'] = raw_info.get('uploader', 'Unknown Uploader')
                video_info['duration'] = raw_info.get('duration', 0)
                video_info['view_count'] = raw_info.get('view_count', 0)
                video_info['like_count'] = raw_info.get('like_count', 0)
                video_info['video_id'] = raw_info.get('id', video_id)
                video_info['channel_id'] = raw_info.get('channel_id')
                raw_thumbnails = raw_info.get('thumbnails', [])
                thumbnails = []
                for thumb in raw_thumbnails:
                    thumbnails.append({'url': thumb.get('url'), 'width': thumb.get('width',0), 'height': thumb.get('height',0)})
                video_info['thumbnails'] = sorted(thumbnails, key=lambda t: t.get('width',0) * t.get('height',0), reverse=True)
                
                raw_formats = raw_info.get('formats', [])
                processed_formats = []
                audio_formats_yt_dlp = [f for f in raw_formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
                if audio_formats_yt_dlp:
                    best_audio = max(audio_formats_yt_dlp, key=lambda f: f.get('tbr', 0) or f.get('abr', 0), default=None)
                    if best_audio:
                        processed_formats.append({
                            'format_id': best_audio.get('format_id'), 'resolution': 'Audio Only', 'fps': None, 
                            'filesize': best_audio.get('filesize') or best_audio.get('filesize_approx'),
                            'ext': best_audio.get('ext'), 'note': best_audio.get('format_note', 'Best Audio')
                        })
                
                # Process video formats with improved resolution detection
                video_only_formats = []
                merged_formats = []
                
                # First pass to identify all available formats
                for f_item in raw_formats:
                    if f_item.get('vcodec') != 'none':
                        # Get resolution in consistent format
                        width = f_item.get('width')
                        height = f_item.get('height')
                        
                        if not width or not height:
                            # Try to extract from resolution string
                            resolution_str = f_item.get('resolution')
                            if resolution_str and 'x' in resolution_str:
                                try:
                                    width_str, height_str = resolution_str.split('x')
                                    width = int(width_str)
                                    height = int(height_str)
                                except (ValueError, TypeError):
                                    continue
                            else:
                                continue
                        
                        # Format resolution consistently
                        res = f"{width}x{height}"
                        
                        # Create format entry
                        fmt_entry = {
                            'format_id': f_item.get('format_id'), 
                            'resolution': res, 
                            'fps': f_item.get('fps'), 
                            'filesize': f_item.get('filesize') or f_item.get('filesize_approx'), 
                            'ext': f_item.get('ext'),
                            'note': f_item.get('format_note', f"{height}p"),
                            'width': width,
                            'height': height
                        }
                        
                        # Categorize as video-only or merged format
                        if f_item.get('acodec') != 'none': 
                            merged_formats.append(fmt_entry)
                        else: 
                            video_only_formats.append(fmt_entry)
                
                # Create categorized formats list with proper quality labeling
                processed_video_formats = []
                
                # Add merged formats first (these have audio built-in)
                if merged_formats:
                    # Sort by height and fps
                    sorted_merged = sorted(merged_formats, 
                        key=lambda x: (x.get('height', 0), x.get('fps', 0)), 
                        reverse=True)
                    processed_video_formats.extend(sorted_merged)
                
                # Add video-only formats 
                if video_only_formats:
                    # Sort by height and fps
                    sorted_video_only = sorted(video_only_formats, 
                        key=lambda x: (x.get('height', 0), x.get('fps', 0)), 
                        reverse=True)
                    processed_video_formats.extend(sorted_video_only)
                
                # Extend the main formats list
                processed_formats.extend(processed_video_formats)
                
                if processed_formats:
                    video_info['formats'] = processed_formats
                    detailed_formats_available = True
                    info_source = 'yt-dlp'
                    logger.info(f"Successfully fetched detailed info with direct yt-dlp for {url}")
                else:
                    logger.warning(f"yt-dlp provided info but no usable formats for {url}. Falling back to API.")
        except yt_dlp.utils.DownloadError as e:
            logger.warning(f"yt-dlp DownloadError for {url} (Proxy: {proxy_url if proxy_url else 'N/A'}): {e}. Falling back to API.")
        except Exception as e:
            logger.error(f"Unexpected error during yt-dlp for {url} (Proxy: {proxy_url if proxy_url else 'N/A'}): {e}. Falling back to API.")
        finally:
            if temp_cookie_file_path and os.path.exists(temp_cookie_file_path):
                try:
                    os.remove(temp_cookie_file_path)
                    logger.info(f"Removed temporary cookie file: {temp_cookie_file_path}")
                except Exception as e:
                    logger.error(f"Error removing temporary cookie file {temp_cookie_file_path}: {e}")
        
        # API Fallback for both browser and direct yt-dlp approaches
        if not detailed_formats_available:
            logger.debug(f"Fetching base video info via YouTube API for {video_id}")
            if not api_key:
                raise ValueError("YOUTUBE_API_KEY not found, and both browser and yt-dlp approaches failed to provide info.")
            try:
                video_api_url = 'https://www.googleapis.com/youtube/v3/videos'
                video_params = {'part': 'snippet,contentDetails,statistics', 'id': video_id, 'key': api_key}
                resp = requests.get(video_api_url, params=video_params, timeout=10)
                resp.raise_for_status()
                video_data = resp.json()
                if not video_data.get('items'):
                    raise ValueError(f"Video not found via API: {video_data.get('error', {}).get('message', 'Unknown API error')}")
                item = video_data['items'][0]
                video_info.setdefault('title', item['snippet'].get('title', 'Unknown Title'))
                video_info.setdefault('uploader', item['snippet'].get('channelTitle', 'Unknown Uploader'))
                video_info.setdefault('channel_id', item['snippet'].get('channelId'))
                duration_iso = item['contentDetails'].get('duration', 'PT0S')
                duration_seconds = 0
                if duration_iso.startswith('PT'):
                    temp_duration_api = duration_iso[2:]
                    if 'H' in temp_duration_api: parts = temp_duration_api.split('H'); duration_seconds += int(parts[0]) * 3600; temp_duration_api = parts[1] if len(parts) > 1 else ''
                    if 'M' in temp_duration_api: parts = temp_duration_api.split('M'); duration_seconds += int(parts[0]) * 60; temp_duration_api = parts[1] if len(parts) > 1 else ''
                    if 'S' in temp_duration_api: duration_seconds += int(temp_duration_api.replace('S', ''))
                video_info.setdefault('duration', duration_seconds)
                video_info.setdefault('view_count', int(item['statistics'].get('viewCount', 0)))
                video_info.setdefault('like_count', int(item['statistics'].get('likeCount', 0)))
                
                # Get thumbnails for both quality detection and thumbnails list
                thumbnails_data = item['snippet'].get('thumbnails', {})
                
                # Process thumbnails if needed
                if not video_info.get('thumbnails'): 
                    api_thumbnails = []
                    for quality_key in ['maxres', 'standard', 'high', 'medium', 'default']:
                        if quality_key in thumbnails_data:
                            thumb = thumbnails_data[quality_key]
                            api_thumbnails.append({'url': thumb['url'], 'width': thumb.get('width',0), 'height': thumb.get('height',0)})
                    video_info['thumbnails'] = sorted(api_thumbnails, key=lambda t: t.get('width',0) * t.get('height',0), reverse=True)
                
                video_info.setdefault('video_id', video_id)
                
                # Detect highest quality based on available thumbnails and definition field
                max_quality = "SD"
                quality_height = 480
                
                # Check for maxres thumbnail - YouTube provides these only for videos with 1080p or higher resolution
                if 'maxres' in thumbnails_data:
                    max_quality = "FULLHD"
                    quality_height = 1080
                
                # Check definition from contentDetails for better resolution info
                definition = item['contentDetails'].get('definition', 'sd')
                if definition == 'hd':
                    if max_quality == "SD":
                        max_quality = "HD"
                        quality_height = 720
                
                # Check for higher definition based on maxres thumbnail dimensions
                if 'maxres' in thumbnails_data:
                    maxres_thumb = thumbnails_data['maxres']
                    maxres_height = maxres_thumb.get('height', 0)
                    if maxres_height >= 2160:
                        max_quality = "4K"
                        quality_height = 2160
                    elif maxres_height >= 1440:
                        max_quality = "2K"
                        quality_height = 1440
                
                # Create API formats with detailed quality information
                api_formats = [
                    {
                        'format_id': 'best_video_api', 
                        'resolution': f'Best Video Available ({max_quality})', 
                        'note': f'Best Video ({max_quality}) (API Fallback)', 
                        'ext': 'mp4',
                        'height': quality_height
                    },
                    {
                        'format_id': 'best_audio_api', 
                        'resolution': 'Audio Only', 
                        'note': 'Audio (API Fallback)', 
                        'ext': 'm4a'
                    }
                ]
                
                video_info['formats'] = api_formats
                info_source = 'api'
                logger.info(f"Fetched basic info via YouTube API for {video_id} (browser and yt-dlp fallback). Quality detected: {max_quality}")
            except requests.exceptions.RequestException as e:
                logger.error(f"API request error (browser and yt-dlp also failed): {e}")
                raise ValueError(f"Could not fetch video from YouTube API (browser and yt-dlp also failed): {e}")
            except (KeyError, IndexError, ValueError) as e:
                logger.error(f"API parsing error (browser and yt-dlp also failed): {e}")
                raise ValueError(f"Error processing API data (browser and yt-dlp also failed): {e}")
        
        # Channel info fetching - same as before
        current_channel_id = video_info.get('channel_id')
        if current_channel_id and api_key:
            try:
                channel_api_url = 'https://www.googleapis.com/youtube/v3/channels'
                channel_params = {'part': 'snippet,statistics', 'id': current_channel_id, 'key': api_key}
                resp = requests.get(channel_api_url, params=channel_params, timeout=10)
                resp.raise_for_status()
                channel_data = resp.json()
                if channel_data.get('items'):
                    ch_item = channel_data['items'][0]
                    sub_count_raw = ch_item['statistics'].get('subscriberCount')
                    if ch_item['statistics'].get('hiddenSubscriberCount') is False and sub_count_raw is not None:
                        channel_info['subscriber_count'] = int(sub_count_raw)
                    elif ch_item['statistics'].get('hiddenSubscriberCount') is True: channel_info['subscriber_count'] = 'Hidden'
                    else: channel_info['subscriber_count'] = 'N/A'
                    ch_thumbnails_data = ch_item['snippet'].get('thumbnails', {})
                    if 'default' in ch_thumbnails_data: channel_info['channel_logo'] = ch_thumbnails_data['default']['url']
                else: channel_info['subscriber_count'] = 'N/A'
            except requests.exceptions.RequestException as e:
                logger.warning(f"API request error for channel details: {e}.")
                channel_info.setdefault('subscriber_count', 'N/A')
            except (KeyError, IndexError, ValueError) as e:
                logger.warning(f"Error parsing channel API response: {e}.")
                channel_info.setdefault('subscriber_count', 'N/A')
        else:
            channel_info.setdefault('subscriber_count', 'N/A')
            if not api_key and current_channel_id: logger.warning("Cannot fetch channel: YOUTUBE_API_KEY missing.")
            elif not current_channel_id: logger.warning("Cannot fetch channel: channel_id missing.")

        result = {**video_info, **channel_info, 'info_source': info_source}
        logger.debug(f"Final video info for '{result.get('title')}': Source: {info_source}, Formats: {len(result.get('formats', []))}")
        return result
    
    def _download_thread(self, download_id, url, format_type, quality):
        """Download thread function for background download processing"""
        try:
            if download_id not in self.downloads:
                logger.error(f"Download ID not found: {download_id}")
                return
                
            download_info = self.downloads[download_id]
            with self.lock:
                download_info['status'] = 'downloading'
            
            output_path = os.path.join(self.temp_dir, download_id)
            os.makedirs(output_path, exist_ok=True)
            
            # Check if browser emulation is disabled via environment variable
            browser_disabled = os.environ.get('DISABLE_BROWSER', '').lower() in ('true', '1', 'yes')
            if browser_disabled:
                logger.info("Browser emulation disabled by DISABLE_BROWSER environment variable for download")
                temp_cookie_file_path = None
            else:
                # First try to get cookies from a browser session to avoid bot verification
                temp_cookie_file_path = None
                try:
                    # Use our centralized Chrome setup function
                    driver, chrome_tmp_dir = None, None
                    try:
                        driver, chrome_tmp_dir = setup_chrome_driver()
                        
                        # First visit YouTube homepage to establish a normal session
                        driver.get("https://www.youtube.com/")
                        time.sleep(random.uniform(1, 2))  # Shorter random delay
                        
                        # Perform some random scrolling to appear human-like
                        driver.execute_script(f"window.scrollTo(0, {random.randint(100, 200)});")
                        time.sleep(random.uniform(0.5, 1))  # Shorter delay
                        
                        # Now navigate to the actual video
                        driver.get(url)
                        
                        # Wait for video to load with a reasonable timeout
                        try:
                            WebDriverWait(driver, 20).until(
                                EC.presence_of_element_located((By.ID, "movie_player"))
                            )
                            logger.info("Video player loaded successfully for download")
                        except Exception as e:
                            logger.warning(f"Waiting for video player timed out in download: {e}. Continuing anyway.")
                        
                        # Add minimal interactions
                        time.sleep(random.uniform(1, 2))  # Shorter delay
                        
                        # Force garbage collection to free memory
                        driver.execute_script("window.gc();")
                        
                        # Get cookies from browser session
                        cookies = driver.get_cookies()
                        logger.info(f"Retrieved {len(cookies)} cookies from browser session for download")
                        
                        # Create a temporary cookie file for yt-dlp
                        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_cookie_file:
                            # Format cookies for yt-dlp
                            for cookie in cookies:
                                domain = cookie.get('domain', '')
                                if domain.startswith('.'):
                                    domain = domain[1:]
                                expires = cookie.get('expiry', 0)
                                secure = cookie.get('secure', False)
                                httpOnly = cookie.get('httpOnly', False)
                                tmp_cookie_file.write(f"{domain}\tTRUE\t{cookie.get('path', '/')}\t{str(secure).upper()}\t{expires}\t{cookie.get('name', '')}\t{cookie.get('value', '')}\n")
                            
                            temp_cookie_file_path = tmp_cookie_file.name
                            logger.info(f"Created cookie file from browser session for download: {temp_cookie_file_path}")
                    except Exception as browser_error:
                        logger.error(f"Browser setup or navigation error in download: {browser_error}")
                    finally:
                        # Close the browser
                        if driver:
                            driver.quit()
                            logger.info("Browser session closed for download")
                        
                        # Clean up temporary directory
                        if chrome_tmp_dir and os.path.exists(chrome_tmp_dir):
                            try:
                                shutil.rmtree(chrome_tmp_dir)
                                logger.info(f"Removed Chrome temporary directory for download: {chrome_tmp_dir}")
                            except Exception as tmp_dir_error:
                                logger.error(f"Error removing Chrome temporary directory for download: {tmp_dir_error}")
                except Exception as e:
                    logger.error(f"Browser emulation failed for download {download_id}: {e}. Will try without browser cookies.")
                    temp_cookie_file_path = None
            
            local_command = None
            
            if format_type == 'video':
                # Ensure ffmpeg is available for merging streams
                if not getattr(self, 'ffmpeg_available', False):
                    logger.error("ffmpeg is not available; cannot merge video and audio.")
                    download_info['status'] = 'failed'
                    download_info['error'] = 'ffmpeg not found in PATH'
                    self._save_downloads()
                    return
                if quality == 'best':
                    # Select best video up to 1440p and best audio.
                    # Fallback to best overall format up to 1440p if specific combo fails.
                    format_str = 'bestvideo[height<=1440]+bestaudio/best[height<=1440]'
                else:
                    # Extract height from quality string (e.g., 1920x1080 -> 1080 or a format_id)
                    # If quality is a format_id, this height extraction won't apply directly,
                    # yt-dlp will use the format_id directly if it's a valid one.
                    # For resolution-based like '1080p', extract height.
                    height_str_match = re.search(r'(\d+)p', str(quality))
                    if 'x' in str(quality): # e.g. 1920x1080
                        height = quality.split('x')[1]
                    elif height_str_match: # e.g. 1080p
                        height = height_str_match.group(1)
                    else: # Assuming it might be a direct format ID or a generic 'best'/'worst'
                        height = quality # Pass it as is, or handle as format ID if specific
                    
                    # If a specific format ID was passed (not 'best', 'worst', or resoltion string)
                    if not str(height).isnumeric() and quality not in ['best', 'worst']:
                        format_str = quality # Use the format ID directly
                    else:
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
                ]
                
                # Add cookie file if we have it
                if temp_cookie_file_path:
                    local_command.extend(['--cookies', temp_cookie_file_path])
                
                # Add proxy if available
                proxy_url = os.getenv('YTDLP_PROXY_URL')
                if proxy_url:
                    local_command.extend(['--proxy', proxy_url])
                
                # Add URL as the last parameter
                local_command.append(url)
                
                # Log the command for debugging
                logger.debug(f"Video download command: {' '.join(local_command)}")
                
                download_info['expected_extension'] = 'mp4'
                download_info['mime_type'] = 'video/mp4'
                
            elif format_type == 'audio':
                # Ensure ffmpeg is available for audio conversion
                if not getattr(self, 'ffmpeg_available', False):
                    download_info['status'] = 'failed'
                    download_info['error'] = 'ffmpeg is required for audio conversion; please install ffmpeg and ensure it is in your PATH'
                    self._save_downloads()
                    return
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
                ]
                
                # Add cookie file if we have it
                if temp_cookie_file_path:
                    local_command.extend(['--cookies', temp_cookie_file_path])
                
                # Add proxy if available
                proxy_url = os.getenv('YTDLP_PROXY_URL')
                if proxy_url:
                    local_command.extend(['--proxy', proxy_url])
                
                # Add URL as the last parameter
                local_command.append(url)
                
                logger.debug(f"Audio download command: {' '.join(local_command)}")
                
                download_info['expected_extension'] = 'mp3'
                download_info['mime_type'] = 'audio/mpeg'
                
            elif format_type == 'thumbnail':
                # Get video info to get the best thumbnail
                video_info = self.get_video_info(url)
                
                if not video_info['thumbnails']:
                    raise ValueError("No thumbnails found for this video")
                
                # Get the best quality thumbnail
                best_thumbnail = video_info['thumbnails'][0]
                thumbnail_url = best_thumbnail['url']
                
                # Download the thumbnail
                response = requests.get(thumbnail_url, stream=True)
                if response.status_code != 200:
                    raise ValueError(f"Failed to download thumbnail: HTTP {response.status_code}")
                
                filename = f"{video_info['title']}_thumbnail.jpg"
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
                self._save_downloads()
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
                    logger.debug(f"yt-dlp raw_line: {line.strip()}")
                    if download_info.get('status') == 'canceled':
                        process.terminate()
                        break
                        
                    if '[Merger]' in line or '[VideoConvertor]' in line:
                        with self.lock:
                            # Switch to processing status, cap progress at 90%
                            download_info['status'] = 'processing'
                            if download_info.get('progress', 0) > 90:
                                download_info['progress'] = 90
                            download_info['eta'] = 'Processing...'
                            download_info['processing_stage'] = line.strip()
                            # Record when processing started to calculate progress during this phase
                            if 'processing_start_time' not in download_info:
                                download_info['processing_start_time'] = time.time()
                            logger.debug(f"Download {download_id}: Entered processing phase: {line.strip()}")
                            
                    if '[download]' in line and '%' in line:
                        # Store the raw progress line for direct access by get_progress
                        with self.lock:
                            download_info['last_progress_line'] = line.strip()
                        
                        try:
                            # Default values for this line's parsing attempt
                            current_line_eta = None
                            # Preserve previous speed/ETA info if current line doesn't update it
                            current_line_speed_str = download_info.get('speed', 'N/A')
                            current_line_speed_bytes = download_info.get('speed_bytes')

                            # Special case for the very first progress line
                            # Directly extract ETA from line using a more aggressive approach
                            # Example line: [download]   0.0% of   50.62MiB at  499.80KiB/s ETA 01:43
                            if "ETA" in line:
                                eta_part = line.split("ETA")[-1].strip()
                                if eta_part and eta_part != "Unknown ETA" and not eta_part.startswith("Unknown"):
                                    # Directly use the ETA value from yt-dlp output
                                    current_line_eta = eta_part
                                    logger.debug(f"Direct ETA extraction: '{eta_part}' from line: '{line.strip()}'")
                            
                            # Also extract speed more aggressively
                            if "at" in line and "/s" in line:
                                speed_part = line.split("at")[-1].split("ETA")[0].strip()
                                if speed_part and "/s" in speed_part:
                                    current_line_speed_str = speed_part
                                    logger.debug(f"Direct speed extraction: '{speed_part}' from line: '{line.strip()}'")

                            # 1. Try to parse ETA directly from yt-dlp output with regex as fallback
                            m_eta_direct = re.search(r'ETA\\s+((?:\\d{2}:)?\\d{2}:\\d{2})', line)
                            if m_eta_direct:
                                current_line_eta = m_eta_direct.group(1)
                            elif "ETA Unknown ETA" in line: # yt-dlp explicitly states Unknown ETA
                                current_line_eta = 'Unknown'

                            # 2. Parse downloaded bytes and total bytes for progress
                            # Preserve previous byte info if current line doesn't update it
                            downloaded_bytes = download_info.get('downloaded_bytes')
                            total_bytes = download_info.get('total_bytes')
                            
                            m_sizes = re.search(r'(\\d+(?:\\.\\d+)?)([KMG]iB) of (\\d+(?:\\.\\d+)?)([KMG]iB)', line)
                            if m_sizes:
                                down_val, down_unit, total_val, total_unit = m_sizes.groups()
                                downloaded_bytes = parse_size(down_val, down_unit)
                                total_bytes = parse_size(total_val, total_unit)
                                download_info['downloaded_bytes'] = downloaded_bytes
                                download_info['total_bytes'] = total_bytes
                                if total_bytes is not None and total_bytes > 0:
                                    download_info['progress'] = (downloaded_bytes / total_bytes) * 100
                                elif download_info.get('progress', 0) < 100 : # Only update if not already 100 and no total_bytes
                                    # Fallback to CLI percentage for progress if byte info is incomplete for calculation
                                    m_pct = re.search(r'(\\d+(?:\\.\\d+)?)%', line)
                                    if m_pct:
                                        download_info['progress'] = float(m_pct.group(1))
                            else:
                                # Fallback to CLI percentage if full byte string not found
                                m_pct = re.search(r'(\\d+(?:\\.\\d+)?)%', line)
                                if m_pct:
                                    download_info['progress'] = float(m_pct.group(1))

                            # 3. Parse speed
                            m_speed = re.search(r'at\\s+(\\d+(?:\\.\\d+)?)([KMG]iB)/s', line)
                            if m_speed:
                                speed_val, speed_unit = m_speed.groups()
                                current_line_speed_bytes = parse_size(speed_val, speed_unit)
                                current_line_speed_str = f"{speed_val}{speed_unit}/s"
                            
                            # Log parsed values before committing to download_info
                            logger.debug(f"Download {download_id}: Parsed line. Current Speed: '{current_line_speed_str}', Current ETA: '{current_line_eta}', Progress: {download_info.get('progress')}")

                            # 4. If ETA was not directly parsed from yt-dlp, try to calculate it
                            if current_line_eta is None: # Not 'Unknown', and not found in HH:MM:SS format
                                if current_line_speed_bytes and current_line_speed_bytes > 0 and \
                                   downloaded_bytes is not None and total_bytes is not None and \
                                   downloaded_bytes < total_bytes:
                                    
                                    remaining_bytes = total_bytes - downloaded_bytes
                                    eta_seconds = int(remaining_bytes / current_line_speed_bytes)
                                    
                                    h, rem = divmod(eta_seconds, 3600)
                                    m, s_rem = divmod(rem, 60)
                                    if h > 0:
                                        current_line_eta = f"{h}:{m:02d}:{s_rem:02d}"
                                    else:
                                        current_line_eta = f"{m:02d}:{s_rem:02d}"
                                else:
                                    # Not enough info for calculation, or speed is zero/unavailable
                                    # Preserve existing ETA or set to 'Calculating...' if none exists
                                    current_line_eta = download_info.get('eta', 'Calculating...')

                            # 5. Update download_info with the determined ETA for the current line
                            if current_line_eta is not None:
                                download_info['eta'] = current_line_eta
                            
                            # Log just before final assignment for this line
                            logger.debug(f"Download {download_id}: Finalizing line. Speed to store: '{current_line_speed_str}', ETA to store: '{current_line_eta}'")
                            
                            # Update download_info with thread safety
                            with self.lock:
                                # Update progress calculation if we have byte information
                                if 'downloaded_bytes' in locals() and 'total_bytes' in locals():
                                    if total_bytes is not None and total_bytes > 0:
                                        download_info['progress'] = (downloaded_bytes / total_bytes) * 100
                                
                                # Update progress from percentage if we parsed it
                                m_pct = re.search(r'(\d+(?:\.\d+)?)%', line)
                                if m_pct:
                                    download_info['progress'] = float(m_pct.group(1))
                                    
                                # Set speed and ETA
                                if current_line_eta is not None:
                                    download_info['eta'] = current_line_eta
                                if current_line_speed_str != 'N/A':
                                    download_info['speed'] = current_line_speed_str
                                if current_line_speed_bytes is not None:
                                    download_info['speed_bytes'] = current_line_speed_bytes

                        except Exception as e:
                            logger.debug(f"Error parsing progress line: '{line.strip()}'. Error: {str(e)}")
                            # Preserve existing info or set defaults on error
                            download_info['progress'] = download_info.get('progress', 0)
                            download_info['speed'] = download_info.get('speed', 'N/A')
                            download_info['eta'] = download_info.get('eta', 'N/A')
                            
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
                # yt-dlp finished, but post-processing may still be running
                download_info['status'] = 'processing'
                download_info['progress'] = 99
                download_info['eta'] = 'Processing...'
                download_info['speed'] = 'N/A'
                self._save_downloads()
                
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
                
                # When everything is truly done:
                download_info['status'] = 'completed'
                download_info['progress'] = 100
                download_info['eta'] = 'Done'
                download_info['speed'] = 'Complete'
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
            'speed': 'Calculating...',
            'eta': 'Calculating...',
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
            
        # Safely get a copy of the current download_info
        with self.lock:
            download_info = self.downloads[download_id].copy()
        
        # VERBOSE LOGGING: Log exactly what's in the download_info dictionary
        logger.debug(f"PROGRESS DEBUG - Download {download_id} raw info: {str(download_info)}")
        
        # Copy values to prevent modifying the original dictionary
        status = download_info.get('status', 'unknown')
        progress = download_info.get('progress', 0)
        speed = download_info.get('speed', 'Calculating...')
        eta = download_info.get('eta', 'Calculating...')
        format_type = download_info.get('format_type', '')
        elapsed = int(time.time() - download_info.get('start_time', time.time()))
        
        # If there's a raw_line key in download_info that contains progress information,
        # parse it directly here to ensure accuracy
        raw_line = download_info.get('last_progress_line', '')
        if raw_line and '[download]' in raw_line and '%' in raw_line:
            try:
                # Extract percentage directly from the line
                pct_match = re.search(r'(\d+(?:\.\d+)?)%', raw_line)
                if pct_match:
                    # Cap download progress at 90% maximum to reserve 10% for processing
                    parsed_pct = float(pct_match.group(1))
                    if status != 'processing' and parsed_pct > 90:
                        progress = 90
                    else:
                        progress = min(90, parsed_pct)
                
                # Direct extraction of ETA
                if 'ETA' in raw_line:
                    eta_part = raw_line.split('ETA')[-1].strip()
                    if eta_part and not eta_part.startswith('Unknown'):
                        eta = eta_part
                
                # Direct extraction of speed
                if 'at' in raw_line and '/s' in raw_line:
                    try:
                        speed_part = raw_line.split('at')[-1].split('ETA')[0].strip()
                        if '/s' in speed_part:
                            speed = speed_part
                    except Exception as speed_parse_error:
                        logger.debug(f"Error parsing speed: {speed_parse_error}")
                        pass  # Keep current speed if parsing fails
                        
                logger.debug(f"Direct parsing from raw line: progress={progress}, speed={speed}, eta={eta}")
            except Exception as e:
                logger.error(f"Error parsing raw progress line: {str(e)}")
                
        # ENSURE PROGRESS IS VISIBLE: Force progress to be above 0 if downloading
        if status == 'downloading' and progress < 0.1:
            progress = 0.1
        
        # If we're in processing stage (after download, during conversion), 
        # set progress between 90% and 99% based on elapsed time
        if status == 'processing':
            # Calculate processing progress based on time elapsed since entering processing
            # Most conversions take ~5-15 seconds, so we'll estimate progress
            processing_start = download_info.get('processing_start_time', download_info.get('start_time', time.time()))
            processing_elapsed = time.time() - processing_start
            
            # Map processing time to progress range 90-99%
            # Assume typical processing takes ~10 seconds
            processing_progress = min(9, processing_elapsed / 10 * 9)
            progress = 90 + processing_progress
            speed = "Processing..."
            
            # Show processing stage if available
            processing_stage = download_info.get('processing_stage', '')
            if 'Merger' in processing_stage:
                eta = "Merging streams..."
            elif 'VideoConvertor' in processing_stage:
                eta = "Preparing for download in your device..."
            else:
                eta = "Processing..."
                
            logger.debug(f"Processing progress calculation: elapsed={processing_elapsed}s, progress={progress}%")
        
        # ENSURE STATUS NAMES MATCH FRONTEND EXPECTATIONS
        # Convert backend status names to what frontend expects if needed
        status_mapping = {
            'starting': 'starting',
            'downloading': 'downloading',
            'processing': 'processing',
            'completed': 'completed',
            'failed': 'failed',
            'canceled': 'canceled'
        }
        status = status_mapping.get(status, status)
        
        # Create result dictionary
        result = {
            'status': status,
            'progress': progress,
            'speed': speed,
            'eta': eta,
            'format_type': format_type,
            'elapsed': elapsed
        }
        
        # Log what we're about to return to the frontend
        logger.debug(f"PROGRESS RESPONSE - Download {download_id}: {str(result)}")
        
        return result
    
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

    def auto_clean_empty_directories(self):
        """Auto-clean empty directories"""
        try:
            # Find all empty directories in the temp_dir
            empty_dirs = []
            for root, _, files in os.walk(self.temp_dir):
                if not files:
                    empty_dirs.append(root)
            
            # Remove empty directories
            for empty_dir in empty_dirs:
                try:
                    os.rmdir(empty_dir)
                    logger.debug(f"Removed empty directory: {empty_dir}")
                except Exception as e:
                    logger.error(f"Error removing empty directory: {str(e)}")
            
            return len(empty_dirs)
        except Exception as e:
            logger.error(f"Error auto-cleaning empty directories: {str(e)}")
            return 0
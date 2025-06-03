import os
import re
import json
import requests
import yt_dlp
import tempfile
import platform
import time
from http.cookiejar import MozillaCookieJar
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
from googleapiclient.discovery import build
from dotenv import load_dotenv
from io import BytesIO
from PIL import Image, ImageDraw
import urllib.request
import traceback
import logging # Added for more detailed logging

# Import our VPNBook proxy manager - will be used conditionally
from vpn_handler import get_ytdlp_proxy_url, mark_proxy_failed

load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'cookies'
app.config['DOWNLOAD_FOLDER'] = 'downloads'
app.secret_key = os.urandom(24)

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
# Suppress overly verbose logs from libraries if needed
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

API_KEY = os.getenv("YOUTUBE_API_KEY")

# Get the proxy URL from environment variable
YTDLP_PROXY_URL_ENV = os.getenv("YTDLP_PROXY_URL")

# VPNBook settings
# USE_VPNBOOK will only be True if YTDLP_PROXY_URL_ENV is not set AND USE_VPNBOOK is explicitly "true"
USE_VPNBOOK_ENV_RAW = os.getenv("USE_VPNBOOK", "False").lower()
SHOULD_USE_VPNBOOK = not YTDLP_PROXY_URL_ENV and USE_VPNBOOK_ENV_RAW == "true"

VPNBOOK_COUNTRY = os.getenv("VPNBOOK_COUNTRY", None)
VPNBOOK_PROTOCOL = os.getenv("VPNBOOK_PROTOCOL", "http")

if not API_KEY:
    app.logger.warning("YOUTUBE_API_KEY environment variable is not set. API dependent features may fail.")

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
if not os.path.exists(app.config['DOWNLOAD_FOLDER']):
    os.makedirs(app.config['DOWNLOAD_FOLDER'])

# Determine the effective YTDLP_PROXY_URL
EFFECTIVE_YTDLP_PROXY_URL = None

# If an explicit proxy URL was provided in environment, use that
if YTDLP_PROXY_URL_ENV:
    EFFECTIVE_YTDLP_PROXY_URL = YTDLP_PROXY_URL_ENV
    app.logger.info(f"Using proxy URL from environment variable: {YTDLP_PROXY_URL_ENV}")
# Otherwise, if USE_VPNBOOK is True, fetch a proxy URL from VPNBook
elif SHOULD_USE_VPNBOOK:
    try:
        EFFECTIVE_YTDLP_PROXY_URL = get_ytdlp_proxy_url(VPNBOOK_COUNTRY, VPNBOOK_PROTOCOL)
        app.logger.info(f"Using VPNBook proxy: {EFFECTIVE_YTDLP_PROXY_URL}")
    except Exception as e:
        app.logger.error(f"Failed to initialize VPNBook proxy: {str(e)}")
        app.logger.warning("VPNBook proxy initialization failed. Continuing without proxy.")

# Function to determine browser type based on OS and User-Agent
def detect_browser_from_user_agent(user_agent_string):
    """
    Detect browser name from User-Agent string for cookiesfrombrowser
    """
    if not user_agent_string:
        return "chrome"  # Default to chrome
        
    ua_lower = user_agent_string.lower()
    
    if "edg" in ua_lower:
        return "edge"
    elif "chrome" in ua_lower:
        return "chrome"
    elif "firefox" in ua_lower:
        return "firefox"
    elif "safari" in ua_lower and "chrome" not in ua_lower:
        return "safari"
    elif "opera" in ua_lower:
        return "opera"
    else:
        return "chrome"  # Default to chrome

# Function to get a YouTube API service
def get_youtube_service():
    if not API_KEY:
        raise ValueError("YouTube API key is required but not set")
    return build('youtube', 'v3', developerKey=API_KEY, cache_discovery=False)

# Format numbers for display (e.g., 1000 -> 1K, 1000000 -> 1M)
def format_count(count_str):
    try:
        count = int(count_str)
        if count >= 1000000:
            return f"{count/1000000:.1f}M"
        elif count >= 1000:
            return f"{count/1000:.1f}K"
        else:
            return str(count)
    except (ValueError, TypeError):
        return "0"

def extract_video_id(url):
    """Extract the video ID from a YouTube URL"""
    video_id = None
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',          # Standard youtube.com URLs
        r'(?:embed\/)([0-9A-Za-z_-]{11}).*',        # Embed URLs
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11}).*',    # youtu.be short URLs
        r'(?:shorts\/)([0-9A-Za-z_-]{11}).*'        # YouTube shorts URLs
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            break
    
    return video_id

def process_cookie_string(cookies_content_str):
    """
    Process cookie string to ensure it's properly formatted for Netscape format.
    This is critical for bypassing YouTube's bot detection when deployed.
    """
    if not cookies_content_str or not cookies_content_str.strip():
        return "" # Return empty string for empty/whitespace-only input

    normalized_content = cookies_content_str.replace('\r\n', '\n').replace('\r', '\n')
    lines = normalized_content.split('\n')
    
    output_lines = []
    header_written = False

    first_content_line_processed = False
    temp_buffer = [] # To hold lines before deciding if header needs to be prefixed

    for line_text in lines:
        stripped_line = line_text.strip()
        
        if not stripped_line:
            if first_content_line_processed: # Preserve empty lines after first content if any
                 temp_buffer.append("") 
            continue # Skip leading empty lines or multiple empty lines

        if not first_content_line_processed and stripped_line.startswith("# Netscape HTTP Cookie File"):
            output_lines.append(stripped_line) # Add header first
            header_written = True
            first_content_line_processed = True
        elif stripped_line.startswith("#"):
            # Avoid adding default header again if another comment is the first content
            if not header_written and not first_content_line_processed:
                 output_lines.append("# Netscape HTTP Cookie File")
                 header_written = True
            first_content_line_processed = True
            if not (header_written and stripped_line == "# Netscape HTTP Cookie File"):
                 temp_buffer.append(stripped_line) # Store other comments
        else: # Assumed to be a cookie data line
            if not header_written and not first_content_line_processed:
                 output_lines.append("# Netscape HTTP Cookie File")
                 header_written = True
            first_content_line_processed = True
            parts = re.split(r'\s+', stripped_line) # Split by one or more whitespace characters
            if len(parts) == 7 or len(parts) == 6: # Typical number of fields
                temp_buffer.append("\t".join(parts)) # Re-join with TABS
            else:
                temp_buffer.append(stripped_line) # Append as is if not standard structure
    
    output_lines.extend(temp_buffer)
    
    # Final check if header was missed (e.g. if input was only cookie data lines)
    if not header_written and any(line.strip() for line in output_lines):
        output_lines.insert(0, "# Netscape HTTP Cookie File")
    elif not output_lines:
        return ""

    final_str = "\n".join(output_lines)
    if final_str and not final_str.endswith('\n'): # Ensure trailing newline if there's content
      final_str += '\n'
      
    return final_str

def create_cookie_file(cookies_content, identifier="default"):
    """
    Create and return the path to a cookie file from cookie content.
    Uses a more secure temporary file approach that works better in deployed environments.
    """
    if not cookies_content or not cookies_content.strip():
        return None
        
    processed_cookies = process_cookie_string(cookies_content)
    if not processed_cookies.strip() or processed_cookies.strip() == "# Netscape HTTP Cookie File":
        return None
        
    # Create a temporary file that will be automatically cleaned up when closed
    cookie_file = tempfile.NamedTemporaryFile(
        prefix=f"ytdl_cookies_{identifier}_", 
        suffix=".txt",
        dir=app.config['UPLOAD_FOLDER'],
        delete=False  # We'll handle deletion in finally blocks
    )
    
    try:
        with open(cookie_file.name, 'w', encoding='utf-8', newline='\n') as f:
            f.write(processed_cookies)
        return cookie_file.name
    except Exception as e:
        print(f"Error creating cookie file: {e}")
        try:
            os.remove(cookie_file.name)
        except:
            pass
        return None

def sanitize_filename(filename):
    """Sanitize a filename by removing invalid characters"""
    # Replace invalid characters with underscores
    invalid_chars = r'[\\/:"*?<>|]'
    sanitized = re.sub(invalid_chars, '_', filename)
    # Limit the length to avoid file system issues
    return sanitized[:100]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/fetch_info', methods=['POST'])
def fetch_info():
    data = request.get_json()
    url = data.get('url')
    cookies_content = data.get('cookies_content')
    user_agent_from_client = data.get('user_agent')

    app.logger.info(f"Received /fetch_info request for URL: {url}")
    if cookies_content:
        app.logger.debug(f"Cookies received (first 100 chars): {cookies_content[:100] if len(cookies_content) > 100 else cookies_content}")
    if user_agent_from_client:
        app.logger.debug(f"User-Agent received: {user_agent_from_client}")

    if not url:
        app.logger.error("URL is required for /fetch_info")
        return jsonify({'error': 'URL is required'}), 400

    video_id = extract_video_id(url)
    if not video_id:
        app.logger.error(f"Invalid YouTube URL: {url}")
        return jsonify({'error': 'Invalid YouTube URL'}), 400

    cookies_file_path = None
    info_dict = None
    encountered_429 = False

    try:
        # Set up base options for yt-dlp
        base_ydl_opts = {
            'noplaylist': True,
            'quiet': False, 
            'no_warnings': True,
            'skip_download': True,
            'forcejson': True,
            'noprogress': True,
            'no_color': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'logtostderr': False,
            'socket_timeout': 30,  # Increased timeout
            'retries': 10,        # Increased retries
            'fragment_retries': 10,
            'extractor_retries': 5,
        }

        # Use client User-Agent if provided
        if user_agent_from_client:
            app.logger.info(f"Using client User-Agent: {user_agent_from_client}")
            base_ydl_opts['user_agent'] = user_agent_from_client
            base_ydl_opts['http_headers'] = {'User-Agent': user_agent_from_client}
        else:
            default_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            app.logger.info(f"Using default User-Agent for yt-dlp: {default_ua}")
            base_ydl_opts['user_agent'] = default_ua
            base_ydl_opts['http_headers'] = {'User-Agent': default_ua}

        # Set up cookies from browser
        if cookies_content:
            # First attempt: Use cookiesfrombrowser feature if client User-Agent is provided
            browser_type = detect_browser_from_user_agent(user_agent_from_client)
            
            # Unfortunately cookiesfrombrowser can't be used with cookie content from API
            # We still need to create a cookie file, but later we'll implement a better solution
            cookies_file_path = create_cookie_file(cookies_content, f"fetch_{video_id}")
            if cookies_file_path:
                app.logger.info(f"Created cookie file: {cookies_file_path}")
                base_ydl_opts['cookiefile'] = cookies_file_path
            else:
                app.logger.warning("Failed to create cookie file from content")
        
        # Use our configured proxy if available
        current_proxy_url_to_use = EFFECTIVE_YTDLP_PROXY_URL
        if current_proxy_url_to_use:
            # Hide username/password when logging
            logged_proxy = current_proxy_url_to_use.split('@')[1] if '@' in current_proxy_url_to_use else current_proxy_url_to_use
            app.logger.info(f"Using proxy for this fetch attempt: {logged_proxy}")
            base_ydl_opts['proxy'] = current_proxy_url_to_use

        # Attempt with cookies first
        if cookies_file_path:
            app.logger.info(f"Attempting to fetch info for {url} WITH cookies: {cookies_file_path}")
            try:
                with yt_dlp.YoutubeDL(base_ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
                if info_dict:
                    app.logger.info(f"Successfully fetched info with cookies for {url}")
            except yt_dlp.utils.DownloadError as e:
                error_str = str(e)
                app.logger.error(f"yt-dlp DownloadError WITH cookies for {url}: {error_str}")
                app._last_yt_dlp_error = error_str  # Store for later reference
                
                # Check for specific error types
                if "429" in error_str or "too many requests" in error_str.lower():
                    encountered_429 = True
                    app.logger.error("Encountered HTTP 429 rate limiting error")
                
                # Retry logic would be here for specific error types
                
                # If cookies don't work or get an error, try without cookies
                app.logger.info(f"Attempting to fetch info for {url} WITHOUT cookies.")
                try:
                    no_cookie_opts = base_ydl_opts.copy()
                    if 'cookiefile' in no_cookie_opts:
                        del no_cookie_opts['cookiefile']
                    
                    with yt_dlp.YoutubeDL(no_cookie_opts) as ydl:
                        info_dict = ydl.extract_info(url, download=False)
                    if info_dict:
                        app.logger.info(f"Successfully fetched info WITHOUT cookies for {url}")
                except yt_dlp.utils.DownloadError as e_no_cookie:
                    error_str_no_cookie = str(e_no_cookie)
                    app.logger.error(f"yt-dlp DownloadError WITHOUT cookies for {url}: {error_str_no_cookie}")
                    app._last_yt_dlp_error = error_str_no_cookie
                    
                    # VPNBook proxy rotation logic
                    if SHOULD_USE_VPNBOOK and ("429" in error_str_no_cookie or "too many requests" in error_str_no_cookie.lower()):
                        app.logger.info("Attempting VPNBook proxy rotation due to 429 error")
                        try:
                            # Mark current proxy as failed
                            if current_proxy_url_to_use:
                                mark_proxy_failed(current_proxy_url_to_use)
                                
                            # Get a new proxy URL
                            new_proxy_url = get_ytdlp_proxy_url(VPNBOOK_COUNTRY, VPNBOOK_PROTOCOL, renew=True)
                            app.logger.info(f"Rotated to new VPNBook proxy: {new_proxy_url.split('@')[1] if '@' in new_proxy_url else new_proxy_url}")
                            
                            # Try with new proxy
                            vpnbook_retry_opts = no_cookie_opts.copy()
                            vpnbook_retry_opts['proxy'] = new_proxy_url
                            
                            # Add a short delay to avoid immediate retry
                            time.sleep(2)
                            
                            with yt_dlp.YoutubeDL(vpnbook_retry_opts) as ydl:
                                info_dict = ydl.extract_info(url, download=False)
                            if info_dict:
                                app.logger.info(f"Successfully fetched info with rotated VPNBook proxy for {url}")
                        except Exception as e_proxy_rotate:
                            app.logger.error(f"Error rotating VPNBook proxy: {e_proxy_rotate}")
        else:
            # No cookies provided, try direct fetch
            app.logger.info(f"Attempting to fetch info for {url} without cookies (none provided).")
            try:
                with yt_dlp.YoutubeDL(base_ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
                if info_dict:
                    app.logger.info(f"Successfully fetched info without cookies for {url}")
            except yt_dlp.utils.DownloadError as e_direct:
                error_str_direct = str(e_direct)
                app.logger.error(f"yt-dlp DownloadError for direct fetch of {url}: {error_str_direct}")
                app._last_yt_dlp_error = error_str_direct
                
                # Check for rate limiting
                if "429" in error_str_direct or "too many requests" in error_str_direct.lower():
                    encountered_429 = True
                    app.logger.error("Encountered HTTP 429 rate limiting error")
                    
                    # VPNBook proxy rotation logic (similar to above)
                    if SHOULD_USE_VPNBOOK:
                        # Similar rotation logic as above
                        pass  # Simplified for brevity

        # Check if we got a valid info_dict
        if not info_dict:
            app.logger.error(f"Failed to fetch video info from yt-dlp after all attempts for {url}. Encountered 429: {encountered_429}")
            
            # Capture last error message for more specific feedback
            last_error_msg = "The content may be unavailable, private, or an unknown yt-dlp error occurred."
            
            # Check if the error contains "Video unavailable" which is a specific YouTube error
            # This typically means the video is genuinely unavailable rather than an access issue
            error_status_code = 500  # Default to server error
            if hasattr(app, '_last_yt_dlp_error') and app._last_yt_dlp_error:
                if "video unavailable" in app._last_yt_dlp_error.lower():
                    last_error_msg = "This video is not available. It may be private, deleted, age-restricted, or region-blocked in our server's location."
                    app.logger.warning(f"YouTube reports video {video_id} is unavailable. This is likely a genuine content restriction, not an error in our code.")
                    error_status_code = 404  # Not found is more appropriate for unavailable content
                elif "http error 429" in app._last_yt_dlp_error.lower() or "too many requests" in app._last_yt_dlp_error.lower():
                    encountered_429 = True
                    error_status_code = 429
            
            if encountered_429:
                return jsonify({
                    'error': 'YouTube is rate-limiting requests from this server. Please provide fresh cookies or try again much later. Using a different User-Agent might also help.'
                }), 429
            else:
                return jsonify({
                    'error': f'Failed to fetch video info from yt-dlp: {last_error_msg}',
                    'video_id': video_id,
                    'is_unavailable': "video unavailable" in app._last_yt_dlp_error.lower() if hasattr(app, '_last_yt_dlp_error') else False
                }), error_status_code

        app.logger.info(f"Successfully fetched info_dict for {url}. Title: {info_dict.get('title')}")
        
        formats = info_dict.get('formats', [])
        
        ydl_max_height = 0  # Renamed from actual_max_height
        video_formats = []
        for f in formats:
            if f.get('height') and f.get('vcodec') and f.get('vcodec') != 'none':
                video_formats.append({
                    'format_id': f.get('format_id', 'N/A'),
                    'ext': f.get('ext', 'N/A'),
                    'resolution': f"{f.get('width', 0)}x{f.get('height', 0)}",
                    'height': f.get('height', 0),
                    'fps': f.get('fps', 0),
                    'vcodec': f.get('vcodec', 'N/A')
                })
                if f['height'] > ydl_max_height:
                    ydl_max_height = f['height']
        
        # Fallback if formats list is empty or unhelpful, check top-level height
        if ydl_max_height == 0 and info_dict.get('height'):
            if info_dict.get('vcodec') and info_dict.get('vcodec') != 'none':
                ydl_max_height = info_dict.get('height', 0)

        print(f"Max height identified by yt-dlp: {ydl_max_height}p")
        
        # Manual fallback: parse the YouTube watch page HTML to get streamingData for all formats
        # THIS HTML PARSING IS VERY LIKELY TO BE BLOCKED IF YT-DLP IS BLOCKED BY 429
        # Consider removing or heavily conditionalizing this if 429s are persistent
        # For now, let's keep it but be aware.
        try:
            session = requests.Session()
            if cookies_file_path and os.path.exists(cookies_file_path): # check existence again, might have been cleaned
                jar = MozillaCookieJar()
                jar.load(cookies_file_path, ignore_discard=True, ignore_expires=True)
                session.cookies = jar
            
            # Use the same User-Agent as yt-dlp
            headers = {'User-Agent': base_ydl_opts['user_agent']}
            resp = session.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                html_text = resp.text
                # Use DOTALL to capture multi-line JSON blob
                pattern = r'ytInitialPlayerResponse\s*=\s*({.+?})\s*;'
                m = re.search(pattern, html_text, flags=re.DOTALL)
                if m:
                    player_response = json.loads(m.group(1))
                    sd = player_response.get('streamingData', {})
                    stream_list = sd.get('formats', []) + sd.get('adaptiveFormats', [])
                    html_heights = [f.get('height') for f in stream_list if isinstance(f.get('height'), int)]
                    if html_heights:
                        html_max = max(html_heights)
                        if html_max > ydl_max_height:
                            ydl_max_height = html_max
                            print(f"Overrode max height via HTML parse: {ydl_max_height}p")
            else:
                print(f"Failed to fetch HTML: HTTP {resp.status_code}")
        except Exception as e:
            print(f"Manual HTML fallback error: {e}")
        
        video_title_ytdlp = info_dict.get('title', 'N/A')
        duration_from_ydlp = info_dict.get('duration_string', 'N/A')
        
        # Initialize max_quality_str based on ydl_max_height
        if ydl_max_height >= 2160:
            max_quality_str = "4K (2160p)"
        elif ydl_max_height >= 1440:
            max_quality_str = "2K (1440p)"
        elif ydl_max_height >= 1080:
            max_quality_str = "1080p (Full HD)"
        elif ydl_max_height >= 720:
            max_quality_str = "720p (HD)"
        elif ydl_max_height >= 480:
            max_quality_str = "480p (SD)"
        elif ydl_max_height > 0:
            max_quality_str = f"{ydl_max_height}p"
        else:
            max_quality_str = "N/A"

        # Continue with YouTube API call
        try:
            youtube = get_youtube_service()
            video_response = youtube.videos().list(
                part="snippet,statistics,contentDetails", id=video_id).execute()
            
            if not video_response['items']:
                return jsonify({'error': 'Video not found via API'}), 404
            
            item = video_response['items'][0]
            snippet = item['snippet']
            statistics = item.get('statistics', {})
            
            # Get channel info
            channel_id = snippet.get('channelId')
            channel_response = youtube.channels().list(
                part="snippet,statistics", id=channel_id).execute()
            channel_item = channel_response['items'][0]
            channel_snippet = channel_item['snippet']
            channel_statistics = channel_item.get('statistics', {})
            
            # Prepare API info
            api_info = {
                'title': snippet['title'],
                'description': snippet.get('description', 'No description available'),
                'views': format_count(statistics.get('viewCount', '0')),
                'likes': format_count(statistics.get('likeCount', '0')),
                'comments': format_count(statistics.get('commentCount', '0')),
                'thumbnail': snippet['thumbnails']['high']['url'],
                'channel_name': snippet['channelTitle'],
                'channel_logo': channel_snippet['thumbnails']['default']['url'],
                'subscribers': format_count(channel_statistics.get('subscriberCount', '0')),
                'max_quality': max_quality_str,
                'duration': duration_from_ydlp,
                'channel_id': channel_id
            }
            return jsonify(api_info)
        except Exception as e:
            return jsonify({'error': f'Error fetching API info: {str(e)}'}), 500
    except Exception as e:
        print(f"Unexpected error in fetch_info: {e}")
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500
    finally:
        if cookies_file_path and os.path.exists(cookies_file_path):
            try:
                os.remove(cookies_file_path)
                print(f"Cleaned up cookie file in finally: {cookies_file_path}")
            except Exception as e:
                print(f"Failed to clean up cookie file in finally: {e}")

@app.route('/download', methods=['POST'])
def download_video():
    data = request.get_json()
    url = data.get('url')
    quality = data.get('quality', 'best')
    cookies_content = data.get('cookies_content')
    user_agent_from_client = data.get('user_agent')
    
    app.logger.info(f"Received /download request for URL: {url}, Quality: {quality}")
    if cookies_content:
        app.logger.debug(f"Cookies received for download (first 100 chars): {cookies_content[:100] if len(cookies_content) > 100 else cookies_content}")
    if user_agent_from_client:
        app.logger.debug(f"User-Agent received for download: {user_agent_from_client}")
        
    if not url:
        app.logger.error("URL is required for /download")
        return jsonify({'error': 'URL is required'}), 400
        
    video_id = extract_video_id(url)
    if not video_id:
        app.logger.error(f"Invalid YouTube URL for download: {url}")
        return jsonify({'error': 'Invalid YouTube URL'}), 400
        
    download_path = app.config['DOWNLOAD_FOLDER']
    if not os.path.exists(download_path):
        os.makedirs(download_path)
        
    cookies_file_path = None
    video_files = []
    actual_downloaded_filename = None # For tracking the final filename
    
    try:
        # Create a better cookie file if content provided
        if cookies_content and cookies_content.strip():
            cookies_file_path = create_cookie_file(cookies_content, f"download_{video_id}")
            app.logger.info(f"Created cookie file for download: {cookies_file_path}")
            
        # Setup base yt-dlp options with better error handling
        base_ydl_opts = {
            'noplaylist': True,
            'quiet': False, 
            'no_warnings': True,
            'noprogress': True,
            'no_color': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'logtostderr': False,
            'socket_timeout': 30,  # Increased timeout
            'retries': 10,         # Increased retries
            'fragment_retries': 10,
            'extractor_retries': 5,
        }
        
        # Set User-Agent for download
        if user_agent_from_client and user_agent_from_client.strip():
            app.logger.info(f"Using client User-Agent for download: {user_agent_from_client}")
            base_ydl_opts['user_agent'] = user_agent_from_client
            base_ydl_opts['http_headers'] = {'User-Agent': user_agent_from_client}
        else:
            default_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            app.logger.info(f"Using default User-Agent for download: {default_ua}")
            base_ydl_opts['user_agent'] = default_ua
            base_ydl_opts['http_headers'] = {'User-Agent': default_ua}

        # Add cookies file if created
        if cookies_file_path:
            base_ydl_opts['cookiefile'] = cookies_file_path
            app.logger.info(f"Using cookies file for download: {cookies_file_path}")

        # Use the effective proxy URL determined at startup
        current_proxy_url_to_use = EFFECTIVE_YTDLP_PROXY_URL
        if current_proxy_url_to_use:
            logged_proxy = current_proxy_url_to_use.split('@')[1] if '@' in current_proxy_url_to_use else current_proxy_url_to_use
            app.logger.info(f"Using proxy for this download attempt: {logged_proxy}")
            base_ydl_opts['proxy'] = current_proxy_url_to_use
        
        # Initial info fetch for filename (always try, but handle failure)
        info_dict_for_filename = None
        try:
            temp_ydl_opts_for_info = base_ydl_opts.copy()
            temp_ydl_opts_for_info['skip_download'] = True
            temp_ydl_opts_for_info['forcejson'] = True
            
            app.logger.info(f"Fetching video info for filename determination...")
            
            with yt_dlp.YoutubeDL(temp_ydl_opts_for_info) as ydl_info_fetch:
                info_dict_for_filename = ydl_info_fetch.extract_info(url, download=False)
                
            if info_dict_for_filename:
                app.logger.info(f"Successfully fetched info for filename. Title: {info_dict_for_filename.get('title')}")
            else:
                app.logger.warning("No info dictionary returned for filename determination.")
                
        except yt_dlp.utils.DownloadError as e_info_dl_err:
            error_str = str(e_info_dl_err)
            app.logger.error(f"DownloadError during initial info fetch for filename: {error_str}")
            
            # Check for 429 rate limiting
            if "http error 429" in error_str.lower() or "too many requests" in error_str.lower():
                if SHOULD_USE_VPNBOOK and not YTDLP_PROXY_URL_ENV:
                    app.logger.warning("Encountered 429 during info fetch. Attempting to rotate VPNBook proxy.")
                    try:
                        if current_proxy_url_to_use:
                            mark_proxy_failed(current_proxy_url_to_use)
                            
                        new_proxy_url = get_ytdlp_proxy_url(VPNBOOK_COUNTRY, VPNBOOK_PROTOCOL, renew=True)
                        if new_proxy_url:
                            logged_new_proxy = new_proxy_url.split('@')[1] if '@' in new_proxy_url else new_proxy_url
                            app.logger.info(f"Rotated to new proxy: {logged_new_proxy}")
                            
                            # Try again with new proxy
                            retry_opts = temp_ydl_opts_for_info.copy()
                            retry_opts['proxy'] = new_proxy_url
                            
                            with yt_dlp.YoutubeDL(retry_opts) as ydl_retry:
                                info_dict_for_filename = ydl_retry.extract_info(url, download=False)
                                
                            if info_dict_for_filename:
                                app.logger.info("Successfully fetched info with new proxy.")
                    except Exception as e_proxy_rotate:
                        app.logger.error(f"Error rotating proxy during info fetch: {str(e_proxy_rotate)}")
                else:
                    return jsonify({
                        'error': 'YouTube is rate-limiting requests from this server. Please provide fresh cookies or try again later.'
                    }), 429
        except Exception as e_generic_info:
            app.logger.error(f"Generic error during initial info fetch for filename: {e_generic_info}", exc_info=True)
            app.logger.warning("Proceeding with default filename due to generic error in info fetch.")

        # Set output template based on whether title was fetched
        if info_dict_for_filename and info_dict_for_filename.get('title'):
            final_filename_stem = sanitize_filename(info_dict_for_filename.get('title', video_id)) # Fallback to video_id
            base_ydl_opts['outtmpl'] = os.path.join(download_path, f'{final_filename_stem}.%(ext)s')
        else:
            # Fallback filename if title couldn't be fetched
            base_ydl_opts['outtmpl'] = os.path.join(download_path, f'{video_id}_%(height)sp.%(ext)s')
        app.logger.info(f"Final output template for download: {base_ydl_opts['outtmpl']}")

        # Copy base options and customize for quality
        final_download_opts = base_ydl_opts.copy()

        # Handle MP3 downloads
        if quality == 'mp3':
            format_selector = 'bestaudio/best'
            # Use a temporary name for the initial download before conversion
            temp_audio_filename_stem = sanitize_filename(info_dict_for_filename.get('title', video_id)) + "_temp_audio"
            output_template_for_ydl = os.path.join(download_path, f'{temp_audio_filename_stem}.%(ext)s')
            
            # The final MP3 will be renamed
            final_mp3_filename_stem = sanitize_filename(info_dict_for_filename.get('title', video_id))
            final_mp3_path_on_server = os.path.join(download_path, f"{final_mp3_filename_stem}.mp3")

            final_download_opts.update({
                'format': format_selector,
                'outtmpl': output_template_for_ydl, 
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'ffmpeg_location': os.getenv('FFMPEG_PATH')
            })
            
            app.logger.info("Starting MP3 download and conversion...")
            download_info_dict = None
            
            # First attempt with cookies
            try:
                with yt_dlp.YoutubeDL(final_download_opts) as ydl:
                    download_info_dict = ydl.extract_info(url, download=True)
                app.logger.info(f"MP3 download successful with cookies: {url}")
                
            except yt_dlp.utils.DownloadError as e_mp3_dl:
                mp3_error = str(e_mp3_dl)
                app.logger.error(f"MP3 download error with cookies: {mp3_error}")
                
                if "http error 429" in mp3_error.lower() or "too many requests" in mp3_error.lower():
                    # Try VPNBook proxy rotation if applicable
                    if SHOULD_USE_VPNBOOK and not YTDLP_PROXY_URL_ENV:
                        try:
                            if current_proxy_url_to_use:
                                mark_proxy_failed(current_proxy_url_to_use)
                                
                            new_proxy_url = get_ytdlp_proxy_url(VPNBOOK_COUNTRY, VPNBOOK_PROTOCOL, renew=True)
                            if new_proxy_url:
                                app.logger.info(f"Retrying MP3 download with new proxy")
                                
                                retry_opts = final_download_opts.copy()
                                retry_opts['proxy'] = new_proxy_url
                                
                                with yt_dlp.YoutubeDL(retry_opts) as ydl_retry:
                                    download_info_dict = ydl_retry.extract_info(url, download=True)
                                app.logger.info(f"MP3 download successful with new proxy: {url}")
                        except Exception as e_retry:
                            app.logger.error(f"MP3 download failed with new proxy: {str(e_retry)}")
                    else:
                        return jsonify({
                            'error': 'YouTube is rate-limiting MP3 download requests. Try again later or provide fresh cookies.'
                        }), 429
                else:
                    # If this is a non-429 error, check if the video is unavailable
                    if "video unavailable" in mp3_error.lower():
                        return jsonify({
                            'error': 'This video is unavailable. It may be private, deleted, or region-restricted.'
                        }), 404
            
            # If we got a download_info_dict, try to determine the final path
            if download_info_dict:
                try:
                    # Check if the MP3 file was successfully created
                    if os.path.exists(final_mp3_path_on_server):
                        actual_downloaded_filename = os.path.basename(final_mp3_path_on_server)
                    # Use the info_dict to determine the name otherwise
                    else:
                        temp_ydl = yt_dlp.YoutubeDL(final_download_opts)
                        processed_path = temp_ydl.prepare_filename(download_info_dict)
                        if processed_path.endswith('.mp3'):
                            actual_downloaded_filename = os.path.basename(processed_path)
                        else:
                            # If the path doesn't end with .mp3, we need to convert it
                            actual_downloaded_filename = os.path.basename(processed_path).rsplit('.', 1)[0] + '.mp3'
                except Exception as e_path_mp3:
                    app.logger.error(f"Error determining MP3 path: {str(e_path_mp3)}")
                    
            # Fallback filename determination for MP3
            if not actual_downloaded_filename:
                actual_downloaded_filename = f"{final_mp3_filename_stem}.mp3"
                
        else:
            # Handle video downloads (non-MP3)
            if quality == 'best':
                format_selector = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            elif quality == '4k':
                format_selector = 'bestvideo[height>=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height>=2160]+bestaudio/best[height>=2160]/best'
            elif quality == '2k':
                format_selector = 'bestvideo[height>=1440][height<2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height>=1440][height<2160]+bestaudio/best[height>=1440][height<2160]/best'
            elif quality == '1080p':
                format_selector = 'bestvideo[height>=1080][height<1440][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height>=1080][height<1440]+bestaudio/best[height>=1080][height<1440]/best'
            elif quality == '720p':
                format_selector = 'bestvideo[height>=720][height<1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height>=720][height<1080]+bestaudio/best[height>=720][height<1080]/best'
            else:
                format_selector = 'bestvideo[height>=480][height<720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height>=480][height<720]+bestaudio/best[height>=480][height<720]/best'
            
            final_download_opts.update({
                'format': format_selector,
                'merge_output_format': 'mp4',
                'format_sort': ['+res', '+fps', '+vcodec:h264', '+acodec:aac', 'ext:mp4'],
                'postprocessors': [
                    {'key': 'FFmpegMetadata'},
                    {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
                ],
                'ffmpeg_location': os.getenv('FFMPEG_PATH')
            })
            
            app.logger.info(f"Starting video download for quality: {quality}")
            downloaded_video_info = None
            
            # First attempt with cookies and other options
            try:
                with yt_dlp.YoutubeDL(final_download_opts) as ydl:
                    downloaded_video_info = ydl.extract_info(url, download=True)
                app.logger.info(f"Video download successful with cookies: {url}")
                
            except yt_dlp.utils.DownloadError as e_video_dl:
                video_error = str(e_video_dl)
                app.logger.error(f"Video download error with cookies: {video_error}")
                
                if "http error 429" in video_error.lower() or "too many requests" in video_error.lower():
                    # Try VPNBook proxy rotation if applicable
                    if SHOULD_USE_VPNBOOK and not YTDLP_PROXY_URL_ENV:
                        try:
                            if current_proxy_url_to_use:
                                mark_proxy_failed(current_proxy_url_to_use)
                                
                            new_proxy_url = get_ytdlp_proxy_url(VPNBOOK_COUNTRY, VPNBOOK_PROTOCOL, renew=True)
                            if new_proxy_url:
                                app.logger.info(f"Retrying video download with new proxy")
                                
                                retry_opts = final_download_opts.copy()
                                retry_opts['proxy'] = new_proxy_url
                                
                                with yt_dlp.YoutubeDL(retry_opts) as ydl_retry:
                                    downloaded_video_info = ydl_retry.extract_info(url, download=True)
                                app.logger.info(f"Video download successful with new proxy: {url}")
                        except Exception as e_retry:
                            app.logger.error(f"Video download failed with new proxy: {str(e_retry)}")
                    else:
                        return jsonify({
                            'error': 'YouTube is rate-limiting video download requests. Try again later or provide fresh cookies.'
                        }), 429
                else:
                    # If this is a non-429 error, check if the video is unavailable
                    if "video unavailable" in video_error.lower():
                        return jsonify({
                            'error': 'This video is unavailable. It may be private, deleted, or region-restricted.'
                        }), 404
                    
            # Determine the final downloaded filename
            actual_downloaded_filename = None
            
            if downloaded_video_info:
                # Create a temporary ydl instance just to call prepare_filename
                try:
                    temp_ydl_for_path = yt_dlp.YoutubeDL(final_download_opts)
                    actual_downloaded_filename = os.path.basename(temp_ydl_for_path.prepare_filename(downloaded_video_info))
                    app.logger.info(f"yt-dlp prepared filename: {actual_downloaded_filename}")
                except Exception as e_path:
                    app.logger.error(f"Could not determine exact downloaded filename: {str(e_path)}")
            
            # Fallback if prepare_filename failed
            if not actual_downloaded_filename:
                expected_stem = sanitize_filename(info_dict_for_filename.get('title', video_id))
                actual_downloaded_filename = f"{expected_stem}.mp4"
                app.logger.warning(f"Falling back to constructed filename: {actual_downloaded_filename}")

        # Check if the file was actually downloaded
        full_file_path = os.path.join(download_path, actual_downloaded_filename)
        app.logger.info(f"Checking for downloaded file at: {full_file_path}")
        
        if os.path.exists(full_file_path):
            app.logger.info(f"Download successful: {actual_downloaded_filename}")
            
            # Get file size for display
            file_size = os.path.getsize(full_file_path)
            file_size_mb = file_size / (1024 * 1024)  # Convert to MB
            
            return jsonify({
                'success': True,
                'message': 'Video downloaded successfully',
                'filename': actual_downloaded_filename,
                'file_size': f"{file_size_mb:.2f} MB",
                'download_url': f"/download/{actual_downloaded_filename}"
            })
        else:
            app.logger.error(f"File not found after download: {full_file_path}")
            return jsonify({
                'error': 'Download failed: File not created',
                'file_path': full_file_path
            }), 500
            
    except Exception as e:
        app.logger.error(f"Unexpected error in download_video: {str(e)}", exc_info=True)
        return jsonify({'error': f'Server error: {str(e)}'}), 500
    finally:
        # Clean up temporary cookie files
        if cookies_file_path and os.path.exists(cookies_file_path):
            try:
                os.remove(cookies_file_path)
                app.logger.info(f"Cleaned up cookie file: {cookies_file_path}")
            except Exception as e_clean:
                app.logger.error(f"Failed to clean up cookie file: {str(e_clean)}")

@app.route('/downloads/<filename>')
def serve_downloaded_file(filename):
    return send_from_directory(app.config['DOWNLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/download_thumbnail/<video_id>')
def download_thumbnail(video_id):
    try:
        # Get video info from YouTube API to find the highest quality thumbnail
        youtube = get_youtube_service()
        video_response = youtube.videos().list(
            part="snippet", id=video_id).execute()
        
        if not video_response['items']:
            return jsonify({'error': 'Video not found'}), 404
        
        # Get the highest quality thumbnail available
        thumbnails = video_response['items'][0]['snippet']['thumbnails']
        if 'maxres' in thumbnails:
            thumbnail_url = thumbnails['maxres']['url']
        elif 'high' in thumbnails:
            thumbnail_url = thumbnails['high']['url']
        else:
            # Fall back to standard or whatever is available
            thumbnail_url = thumbnails[list(thumbnails.keys())[0]]['url']
        
        # Get the video title for the filename - not used in new fixed name
        # video_title = video_response['items'][0]['snippet']['title']
        # safe_title = re.sub(r'[^a-zA-Z0-9]', '_', video_title)
        
        # Download the thumbnail
        response = requests.get(thumbnail_url, stream=True)
        if response.status_code == 200:
            # Convert to PNG for consistent naming
            img = Image.open(BytesIO(response.content))
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            
            return send_file(
                img_byte_arr,
                mimetype='image/png', # Changed to PNG
                as_attachment=True,
                download_name="Freeytzone(Thumbnail).png" # New fixed filename
            )
        else:
            return jsonify({'error': 'Could not download thumbnail'}), 500
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/download_channel_logo/<channel_id>')
def download_channel_logo(channel_id):
    try:
        # Get channel info from YouTube API
        youtube = get_youtube_service()
        channel_response = youtube.channels().list(
            part="snippet", id=channel_id).execute()
        
        if not channel_response['items']:
            return jsonify({'error': 'Channel not found'}), 404
        
        thumbnails = channel_response['items'][0]['snippet']['thumbnails']
        if 'high' in thumbnails:
            logo_url = thumbnails['high']['url']
        elif 'medium' in thumbnails:
            logo_url = thumbnails['medium']['url']
        elif 'default' in thumbnails:
            logo_url = thumbnails['default']['url']
        else:
            return jsonify({'error': 'Channel logo thumbnails not found'}), 404
        
        response = requests.get(logo_url, stream=True)
        if response.status_code == 200:
            # Open the downloaded image and ensure it's RGBA for alpha channel manipulation
            img = Image.open(BytesIO(response.content)).convert("RGBA")
            width, height = img.size

            # Create an anti-aliased circular mask
            # Supersample the mask drawing (draw on a larger canvas and then shrink)
            supersample_factor = 4 # Higher factor means smoother edges but more processing
            mask_supersampled_size = (width * supersample_factor, height * supersample_factor)
            
            mask_supersampled = Image.new('L', mask_supersampled_size, 0) # 'L' mode for grayscale mask
            draw = ImageDraw.Draw(mask_supersampled)
            # Draw a white ellipse on the black background of the supersampled mask
            draw.ellipse((0, 0) + mask_supersampled_size, fill=255)
            
            # Downscale the supersampled mask to the original image size using Lanczos resampling for anti-aliasing
            mask_antialiased = mask_supersampled.resize((width, height), Image.Resampling.LANCZOS)

            # Apply the anti-aliased mask to the alpha channel of the image
            img.putalpha(mask_antialiased)
            
            # Save the processed image (with circular transparency) to a BytesIO object as PNG
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            
            return send_file(
                img_byte_arr,
                mimetype='image/png',
                as_attachment=True,
                download_name="Freeytzone(Logo).png" # Fixed filename
            )
        else:
            return jsonify({'error': 'Could not download channel logo'}), 500
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

if __name__ == '__main__':
    # When running locally, Flask's dev server is fine.
    # For Render, gunicorn will be used via Procfile or start command.
    # Render sets the PORT environment variable.
    port = int(os.environ.get("PORT", 5000)) # Default to 5000 if not on Render
    # Running with debug=True is not recommended for production like Render
    # It's better to rely on gunicorn's workers and manage logging.
    # For Render, gunicorn should bind to 0.0.0.0 and the $PORT.
    # The 'gunicorn app:app' command will handle this.
    # If running this script directly (e.g. python app.py), it will use Flask's dev server.
    
    # Check if running in a gunicorn environment by checking for gunicorn-specific env vars
    # This is just for conditional logic if needed, gunicorn usually takes over the launch.
    is_gunicorn_env = "GUNICORN_PID" in os.environ 
    
    if not is_gunicorn_env: # Only run app.run if not in gunicorn (i.e. local dev)
        app.logger.info(f"Starting Flask development server on http://0.0.0.0:{port}")
        app.run(host='0.0.0.0', port=port, debug=True) # debug=True for local dev
    else:
        # If Gunicorn is running it, this part of the script won't typically be reached
        # as Gunicorn imports `app` and runs it.
        # We can add a log here for sanity check if it were to be reached.
        app.logger.info("Detected Gunicorn environment. Gunicorn is managing the WSGI server.") 
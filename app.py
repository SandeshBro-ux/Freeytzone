import os
import re
import json
import requests
import yt_dlp
import tempfile
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
if YTDLP_PROXY_URL_ENV:
    EFFECTIVE_YTDLP_PROXY_URL = YTDLP_PROXY_URL_ENV
    app.logger.info(f"Using configured yt-dlp proxy from YTDLP_PROXY_URL: {EFFECTIVE_YTDLP_PROXY_URL}")
elif SHOULD_USE_VPNBOOK:
    app.logger.info(f"YTDLP_PROXY_URL not set, and USE_VPNBOOK is True. Attempting to use VPNBook.")
    try:
        vpnbook_proxy = get_ytdlp_proxy_url(VPNBOOK_COUNTRY, VPNBOOK_PROTOCOL)
        if vpnbook_proxy:
            EFFECTIVE_YTDLP_PROXY_URL = vpnbook_proxy
            app.logger.info(f"Using VPNBook proxy: {'*****'.join(EFFECTIVE_YTDLP_PROXY_URL.split('@')[0].split(':'))}@{EFFECTIVE_YTDLP_PROXY_URL.split('@')[1] if '@' in EFFECTIVE_YTDLP_PROXY_URL else EFFECTIVE_YTDLP_PROXY_URL}")
        else:
            app.logger.warning("Failed to get VPNBook proxy URL. Continuing without proxy.")
    except Exception as e:
        app.logger.error(f"Failed to initialize VPNBook proxy: {e}")
else:
    app.logger.info("No proxy configured. YTDLP_PROXY_URL is not set and USE_VPNBOOK is False or overridden.")

def get_youtube_service():
    return build('youtube', 'v3', developerKey=API_KEY)

def extract_video_id(url):
    video_id_match = re.search(r'(?:v=|[\/])([0-9A-Za-z_-]{11}).*', url)
    return video_id_match.group(1) if video_id_match else None

def format_count(count_str):
    try:
        count = int(count_str)
        if count >= 1000000:
            return f"{count/1000000:.1f}M"
        elif count >= 1000:
            return f"{count/1000:.1f}K"
        else:
            return str(count)
    except:
        return count_str

def sanitize_filename(filename):
    """
    Sanitizes a string to be used as a filename.
    Removes or replaces characters that are invalid in filenames on most OS.
    """
    if not filename:
        return "untitled"
    # Remove characters that are definitely problematic
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    # Replace other common problematic characters with an underscore
    filename = re.sub(r'[\s#%&{}$!@`+=]', "_", filename)
    # Truncate to a reasonable length (e.g., 200 characters) to avoid issues with max path lengths
    filename = filename[:200]
    # Remove leading/trailing underscores and dots that can be problematic
    filename = filename.strip('._')
    if not filename: # If all characters were problematic and removed
        return "sanitized_filename"
    return filename

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
        app.logger.debug(f"Cookies received (first 100 chars): {cookies_content[:100]}")
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
        cookies_file_path = create_cookie_file(cookies_content, f"fetch_{video_id}")
        if cookies_file_path:
            app.logger.info(f"Created temporary cookie file: {cookies_file_path}")
        else:
            app.logger.info("No valid cookies content provided or failed to create cookie file.")
        
        base_ydl_opts = {
            'noplaylist': True,
            'quiet': False, 
            'no_warnings': True, # To reduce log noise, errors will still be caught
            'skip_download': True,
            'forcejson': True,
            'youtube_skip_dash_manifest': True,
            'noprogress': True,
            'no_color': True,
            'nocheckcertificate': True,
            'logtostderr': False, # Don't want yt-dlp to print to stderr directly
            'verbose': False, # Will enable for specific error cases if needed
            # 'dump_single_json': True, # Alternative to forcejson for some cases
        }
        
        if user_agent_from_client and user_agent_from_client.strip():
            app.logger.info(f"Using client-provided User-Agent for yt-dlp: {user_agent_from_client}")
            base_ydl_opts['user_agent'] = user_agent_from_client
        else:
            default_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            app.logger.info(f"Using default User-Agent for yt-dlp: {default_ua}")
            base_ydl_opts['user_agent'] = default_ua
        
        # Use the effective proxy URL determined at startup
        current_proxy_url_to_use = EFFECTIVE_YTDLP_PROXY_URL
        
        # If VPNBook is specifically enabled for this attempt (e.g. after a failure)
        # This logic might be more complex if we allow per-request proxy choices.
        # For now, relying on EFFECTIVE_YTDLP_PROXY_URL logic at startup.

        if current_proxy_url_to_use:
            app.logger.info(f"Using proxy for this yt-dlp attempt: {current_proxy_url_to_use.split('@')[1] if '@' in current_proxy_url_to_use else current_proxy_url_to_use}")
            base_ydl_opts['proxy'] = current_proxy_url_to_use

        # Attempt 1: With cookies (if provided)
        if cookies_file_path:
            app.logger.info(f"Attempting to fetch info for {url} WITH cookies: {cookies_file_path}")
            ydl_opts_with_cookies = base_ydl_opts.copy()
            ydl_opts_with_cookies['cookiefile'] = cookies_file_path
            app.logger.debug(f"yt-dlp options (with cookies): {json.dumps(ydl_opts_with_cookies, indent=2)}")
            try:
                with yt_dlp.YoutubeDL(ydl_opts_with_cookies) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
                app.logger.info(f"yt-dlp fetch WITH cookies successful for {url}")
            except yt_dlp.utils.DownloadError as err:
                error_str = str(err) # Keep original case for detailed logging
                app.logger.error(f"yt-dlp DownloadError WITH cookies for {url}: {error_str}")
                if "http error 429" in error_str.lower() or "too many requests" in error_str.lower():
                    encountered_429 = True
                    # VPNBook rotation logic (only if SHOULD_USE_VPNBOOK and no YTDLP_PROXY_URL_ENV was set)
                    if SHOULD_USE_VPNBOOK and not YTDLP_PROXY_URL_ENV:
                        app.logger.warning(f"Encountered 429 WITH cookies. VPNBook is active. Attempting to rotate proxy.")
                        mark_proxy_failed() # Mark the current one (if it was from VPNBook)
                        try:
                            new_proxy_url = get_ytdlp_proxy_url(VPNBOOK_COUNTRY, VPNBOOK_PROTOCOL, renew=True)
                            if new_proxy_url:
                                app.logger.info(f"Rotated VPNBook proxy after 429 to: {'*****'.join(new_proxy_url.split('@')[0].split(':'))}@{new_proxy_url.split('@')[1] if '@' in new_proxy_url else new_proxy_url}")
                                ydl_opts_with_cookies_retry = ydl_opts_with_cookies.copy()
                                ydl_opts_with_cookies_retry['proxy'] = new_proxy_url
                                app.logger.debug(f"Retrying yt-dlp options (with cookies, new proxy): {json.dumps(ydl_opts_with_cookies_retry, indent=2)}")
                                with yt_dlp.YoutubeDL(ydl_opts_with_cookies_retry) as ydl_retry:
                                    info_dict = ydl_retry.extract_info(url, download=False)
                                app.logger.info(f"yt-dlp fetch WITH cookies and new proxy successful for {url}")
                                encountered_429 = False # Reset flag as it worked
                            else:
                                app.logger.warning("Failed to get a new VPNBook proxy after 429.")
                        except Exception as e_proxy_rotate:
                            app.logger.error(f"Error rotating VPNBook proxy: {e_proxy_rotate}")
                # If still no info_dict after potential retry, it remains None
                if not info_dict: info_dict = None 
            except Exception as e_generic:
                app.logger.error(f"Generic yt-dlp error WITH cookies for {url}: {e_generic}", exc_info=True)
                info_dict = None

        # Attempt 2: Without cookies (if no cookies used OR first attempt failed and info_dict is still None)
        if not info_dict:
            app.logger.info(f"Attempting to fetch info for {url} WITHOUT cookies.")
            ydl_opts_no_cookies = base_ydl_opts.copy()
            ydl_opts_no_cookies['cookiefile'] = None # Explicitly ensure no cookie file
            app.logger.debug(f"yt-dlp options (no cookies): {json.dumps(ydl_opts_no_cookies, indent=2)}")
            try:
                with yt_dlp.YoutubeDL(ydl_opts_no_cookies) as ydl2:
                    info_dict = ydl2.extract_info(url, download=False)
                app.logger.info(f"yt-dlp fetch WITHOUT cookies successful for {url}")
            except yt_dlp.utils.DownloadError as err_no_cookies:
                error_str = str(err_no_cookies) # Keep original case
                app.logger.error(f"yt-dlp DownloadError WITHOUT cookies for {url}: {error_str}")
                if "http error 429" in error_str.lower() or "too many requests" in error_str.lower():
                    encountered_429 = True
                    # VPNBook rotation logic (only if SHOULD_USE_VPNBOOK and no YTDLP_PROXY_URL_ENV was set)
                    if SHOULD_USE_VPNBOOK and not YTDLP_PROXY_URL_ENV:
                        app.logger.warning(f"Encountered 429 WITHOUT cookies. VPNBook is active. Attempting to rotate proxy.")
                        mark_proxy_failed()
                        try:
                            new_proxy_url = get_ytdlp_proxy_url(VPNBOOK_COUNTRY, VPNBOOK_PROTOCOL, renew=True)
                            if new_proxy_url:
                                app.logger.info(f"Rotated VPNBook proxy after 429 to: {'*****'.join(new_proxy_url.split('@')[0].split(':'))}@{new_proxy_url.split('@')[1] if '@' in new_proxy_url else new_proxy_url}")
                                ydl_opts_no_cookies_retry = ydl_opts_no_cookies.copy()
                                ydl_opts_no_cookies_retry['proxy'] = new_proxy_url
                                app.logger.debug(f"Retrying yt-dlp options (no cookies, new proxy): {json.dumps(ydl_opts_no_cookies_retry, indent=2)}")
                                with yt_dlp.YoutubeDL(ydl_opts_no_cookies_retry) as ydl_retry:
                                    info_dict = ydl_retry.extract_info(url, download=False)
                                app.logger.info(f"yt-dlp fetch WITHOUT cookies and new proxy successful for {url}")
                                encountered_429 = False # Reset flag
                            else:
                                app.logger.warning("Failed to get a new VPNBook proxy after 429 (no cookies attempt).")
                        except Exception as e_proxy_rotate_no_cookie:
                            app.logger.error(f"Error rotating VPNBook proxy (no cookies attempt): {e_proxy_rotate_no_cookie}")
                # If this fails, this is our final yt-dlp error for info
            except Exception as e_generic_no_cookies:
                app.logger.error(f"Generic yt-dlp error WITHOUT cookies for {url}: {e_generic_no_cookies}", exc_info=True)
        
        if not info_dict:
            app.logger.error(f"Failed to fetch video info from yt-dlp after all attempts for {url}. Encountered 429: {encountered_429}")
            if encountered_429:
                return jsonify({'error': 'YouTube is rate-limiting requests from this server. Please provide fresh cookies or try again much later. Using a different User-Agent might also help.'}), 429
            else:
                # Try to get the original error message from yt-dlp if available
                # This part is tricky as the error is caught and logged above.
                # We can pass a generic message or try to capture the last error.
                # For now, a generic message.
                last_error_msg = "The content may be unavailable, private, or an unknown yt-dlp error occurred."
                # A more robust way would be to store the last exception string.
                return jsonify({'error': f'Failed to fetch video info from yt-dlp. {last_error_msg}'}), 500

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
        app.logger.debug(f"Cookies received for download (first 100 chars): {cookies_content[:100]}")
    if user_agent_from_client:
        app.logger.debug(f"User-Agent received for download: {user_agent_from_client}")

    if not url or not quality:
        app.logger.error("URL and quality are required for /download")
        return jsonify({'error': 'URL and quality are required'}), 400

    video_id = extract_video_id(url) or "unknown_id"
    cookies_file_path = None
    info_dict_for_filename = {} 
    
    try:
        cookies_file_path = create_cookie_file(cookies_content, f"dl_{video_id}")
        if cookies_file_path:
            app.logger.info(f"Created temporary cookie file for download: {cookies_file_path}")
        else:
            app.logger.info("No valid cookies content for download or failed to create cookie file.")

        download_path = app.config['DOWNLOAD_FOLDER']
        
        base_ydl_opts = {
            'noplaylist': True,
            # outtmpl will be set after fetching title or using fallback
            'noprogress': True,
            'verbose': False, # Keep this false for downloads unless debugging specific issues
            'quiet': False,   # To see some output from yt-dlp during download
            'nopart': True,
            'continuedl': False, # Changed to False to avoid issues with partial files
            'no_color': True,
            'nocheckcertificate': True,
            'youtube_skip_dash_manifest': True,
            'logtostderr': False,
        }

        current_user_agent = None
        if user_agent_from_client and user_agent_from_client.strip():
            app.logger.info(f"Using client-provided User-Agent for download: {user_agent_from_client}")
            current_user_agent = user_agent_from_client
        else:
            default_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            app.logger.info(f"Using default User-Agent for download: {default_ua}")
            current_user_agent = default_ua
        
        base_ydl_opts['user_agent'] = current_user_agent
        base_ydl_opts['http_headers'] = {
            'User-Agent': current_user_agent, # Crucial for consistency
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
        }

        if cookies_file_path:
            base_ydl_opts['cookiefile'] = cookies_file_path
            app.logger.info(f"Using cookies file for download: {cookies_file_path}")

        # Use the effective proxy URL determined at startup for downloads as well
        current_proxy_url_to_use = EFFECTIVE_YTDLP_PROXY_URL
        # VPNBook rotation logic for downloads is similar to fetch_info if needed,
        # but for now, we'll rely on the initial EFFECTIVE_YTDLP_PROXY_URL.
        # A 429 during download is less common for the actual file chunks if metadata was fetched.

        if current_proxy_url_to_use:
            app.logger.info(f"Using proxy for this download attempt: {current_proxy_url_to_use.split('@')[1] if '@' in current_proxy_url_to_use else current_proxy_url_to_use}")
            base_ydl_opts['proxy'] = current_proxy_url_to_use
        
        # Initial info fetch for filename (always try, but handle failure)
        # This part is crucial to get the title for the filename
        temp_ydl_opts_for_info = {
            'noplaylist': True, 'quiet': True, 'no_warnings': True, 
            'skip_download': True, 'forcejson': True, 
            'user_agent': base_ydl_opts['user_agent'], # Use consistent UA
            'cookiefile': cookies_file_path, # Use cookies if available
            'proxy': base_ydl_opts.get('proxy'), # Use proxy if available
            'nocheckcertificate': True,
        }
        app.logger.debug(f"yt-dlp options (for filename info fetch): {json.dumps(temp_ydl_opts_for_info, indent=2)}")
        
        try:
            with yt_dlp.YoutubeDL(temp_ydl_opts_for_info) as ydl_info_fetch:
                info_dict_for_filename = ydl_info_fetch.extract_info(url, download=False)
            app.logger.info(f"Successfully fetched info for filename. Title: {info_dict_for_filename.get('title')}")
        except yt_dlp.utils.DownloadError as e_info_dl_err:
            error_str = str(e_info_dl_err)
            app.logger.error(f"DownloadError during initial info fetch for filename (download route): {error_str}")
            # Specific handling for 429 during this critical step
            if "http error 429" in error_str.lower() or "too many requests" in error_str.lower():
                # Attempt VPNBook proxy rotation if applicable
                if SHOULD_USE_VPNBOOK and not YTDLP_PROXY_URL_ENV:
                    app.logger.warning("Encountered 429 during filename info fetch. VPNBook active. Rotating proxy.")
                    mark_proxy_failed()
                    try:
                        new_proxy_url = get_ytdlp_proxy_url(VPNBOOK_COUNTRY, VPNBOOK_PROTOCOL, renew=True)
                        if new_proxy_url:
                            app.logger.info(f"Rotated VPNBook proxy for filename info fetch to: {'*****'.join(new_proxy_url.split('@')[0].split(':'))}@{new_proxy_url.split('@')[1] if '@' in new_proxy_url else new_proxy_url}")
                            temp_ydl_opts_for_info['proxy'] = new_proxy_url
                            # Retry fetching info with new proxy
                            with yt_dlp.YoutubeDL(temp_ydl_opts_for_info) as ydl_info_retry:
                                info_dict_for_filename = ydl_info_retry.extract_info(url, download=False)
                            app.logger.info(f"Successfully fetched info for filename after proxy rotation. Title: {info_dict_for_filename.get('title')}")
                        else:
                            app.logger.warning("Failed to get a new VPNBook proxy for filename info fetch.")
                    except Exception as e_proxy_info_rotate:
                        app.logger.error(f"Error rotating VPNBook proxy for filename info fetch: {e_proxy_info_rotate}")
                
                # If still no info_dict_for_filename after potential retry, or if not using VPNBook for rotation
                if not info_dict_for_filename.get('title'):
                    app.logger.error("Could not resolve 429 error to fetch filename info. Aborting download.")
                    return jsonify({'error': 'YouTube is rate-limiting requests, cannot fetch video title for download. Please use fresh cookies or try again later.'}), 429
            # For other errors, we might proceed with a default filename.
            app.logger.warning(f"Proceeding with default filename as info fetch failed: {error_str}")
        except Exception as e_generic_info:
            app.logger.error(f"Generic error during initial info fetch for filename (download route): {e_generic_info}", exc_info=True)
            app.logger.warning("Proceeding with default filename due to generic error in info fetch.")

        # Set output template based on whether title was fetched
        if info_dict_for_filename.get('title'):
            final_filename_stem = sanitize_filename(info_dict_for_filename.get('title', video_id)) # Fallback to video_id
            base_ydl_opts['outtmpl'] = os.path.join(download_path, f'{final_filename_stem}.%(ext)s')
        else:
            # Fallback filename if title couldn't be fetched
            base_ydl_opts['outtmpl'] = os.path.join(download_path, f'{video_id}_%(height)sp.%(ext)s') # Default uses video_id and height
        app.logger.info(f"Final output template for download: {base_ydl_opts['outtmpl']}")

        final_download_opts = base_ydl_opts.copy() # Start with the base options

        if quality == 'mp3':
            format_selector = 'bestaudio/best'
            # Use a temporary name for the initial download before conversion
            # The final name will be based on the title or video_id
            temp_audio_filename_stem = sanitize_filename(info_dict_for_filename.get('title', video_id)) + "_temp_audio"
            output_template_for_ydl = os.path.join(download_path, f'{temp_audio_filename_stem}.%(ext)s')
            
            # The final MP3 will be renamed to <title_or_id>.mp3
            final_mp3_filename_stem = sanitize_filename(info_dict_for_filename.get('title', video_id))
            final_mp3_path_on_server = os.path.join(download_path, f"{final_mp3_filename_stem}.mp3")

            final_download_opts.update({
                'format': format_selector,
                'outtmpl': output_template_for_ydl, 
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192', # Standard MP3 quality
                }],
                'ffmpeg_location': os.getenv('FFMPEG_PATH') # Ensure FFmpeg is found
            })
            app.logger.debug(f"yt-dlp options (MP3 download): {json.dumps(final_download_opts, indent=2)}")
            download_info_dict = None
            try:
                with yt_dlp.YoutubeDL(final_download_opts) as ydl:
                    download_info_dict = ydl.extract_info(url, download=True) # This triggers download and postprocessing
                app.logger.info(f"MP3 download and conversion initiated for {url}")
            except yt_dlp.utils.DownloadError as e_mp3_dl:
                error_str = str(e_mp3_dl)
                app.logger.error(f"DownloadError during MP3 processing for {url}: {error_str}")
                # Simplified 429 handling for download part, as info fetch is primary concern
                if "http error 429" in error_str.lower() or "too many requests" in error_str.lower():
                     return jsonify({'error': 'YouTube rate-limited during MP3 download. Try again with fresh cookies.'}), 429
                return jsonify({'error': f'Failed to download/convert to MP3: {error_str}'}), 500
            except Exception as e_mp3_generic:
                app.logger.error(f"Generic error during MP3 processing for {url}: {e_mp3_generic}", exc_info=True)
                return jsonify({'error': f'Server error during MP3 processing: {e_mp3_generic}'}), 500

            # Find the generated MP3 file. yt-dlp appends .mp3 after conversion.
            # The original extension in output_template_for_ydl might be .webm, .m4a etc.
            expected_temp_mp3_file = os.path.join(download_path, f"{temp_audio_filename_stem}.mp3")
            
            if os.path.exists(final_mp3_path_on_server): # Clean up if exists from previous attempt
                try: os.remove(final_mp3_path_on_server)
                except: pass

            if os.path.exists(expected_temp_mp3_file):
                os.rename(expected_temp_mp3_file, final_mp3_path_on_server)
                app.logger.info(f"Successfully converted and renamed MP3 to: {final_mp3_path_on_server}")
            else:
                # Fallback: check if yt-dlp used a different naming convention (e.g. if title had issues)
                # This part needs to be robust. yt-dlp's `prepare_filename` on `download_info_dict` (if it ran)
                # might give the actual name before postprocessing.
                # For simplicity now, we'll assume `temp_audio_filename_stem.mp3` is the target.
                app.logger.error(f"Converted MP3 file not found at expected path: {expected_temp_mp3_file}")
                # Try to list files in download_path that might be it
                possible_files = [f for f in os.listdir(download_path) if temp_audio_filename_stem in f and f.endswith('.mp3')]
                if possible_files:
                    app.logger.warning(f"Found possible MP3 matches: {possible_files}. Using the first one: {possible_files[0]}")
                    os.rename(os.path.join(download_path, possible_files[0]), final_mp3_path_on_server)
                else:
                    return jsonify({'error': 'MP3 conversion failed. Output file not found after processing.'}), 500

            if os.path.exists(final_mp3_path_on_server):
                return jsonify({
                    'download_url': f'/downloads/{os.path.basename(final_mp3_path_on_server)}',
                    'filename': os.path.basename(final_mp3_path_on_server)
                })
            else: # Should not happen if rename was successful
                return jsonify({'error': 'MP3 finalization failed unexpectedly.'}), 500

        # Video download part
        else: # Not MP3, so it's a video format
            if quality == '2K': format_selector = 'bestvideo[height<=?1440]+bestaudio/best[height<=?1440]'
            elif quality == '1080p': format_selector = 'bestvideo[height<=?1080]+bestaudio/best[height<=?1080]'
            elif quality == '720p': format_selector = 'bestvideo[height<=?720]+bestaudio/best[height<=?720]'
            elif quality == 'best': format_selector = 'bestvideo+bestaudio/best'
            elif 'p' in quality:
                height = quality[:-1]
                format_selector = f'bestvideo[height<=?{height}]+bestaudio/best[height<=?{height}]'
            else: # Default to 1080p if unrecognized
                format_selector = 'bestvideo[height<=?1080]+bestaudio/best[height<=?1080]'
            
            final_download_opts.update({
                'format': format_selector,
                'merge_output_format': 'mp4', # Standard MP4 output
                 # Prefer h264/aac if available for wider compatibility, sort by resolution
                'format_sort': ['+res', '+fps', '+vcodec:h264', '+acodec:aac', 'ext:mp4'],
                # FFmpeg postprocessor for metadata and ensuring audio codec (e.g. AAC for mp4)
                'postprocessors': [
                    {'key': 'FFmpegMetadata'},
                    {
                        'key': 'FFmpegVideoConvertor', # Ensures video is in a compatible format if needed, e.g. h264
                        'preferedformat': 'mp4',
                    },
                    # Ensure audio is AAC for MP4 compatibility, if not already.
                    # This can be part of merge_output_format or a specific audio conversion.
                    # yt-dlp often handles this well with 'merge_output_format': 'mp4'.
                    # Adding an explicit audio conversion can sometimes cause issues or be redundant.
                    # Let's rely on merge_output_format for now.
                ],
                'ffmpeg_location': os.getenv('FFMPEG_PATH')
            })
            app.logger.debug(f"yt-dlp options (video download - {quality}): {json.dumps(final_download_opts, indent=2)}")
            downloaded_video_info = None
            try:
                with yt_dlp.YoutubeDL(final_download_opts) as ydl:
                    downloaded_video_info = ydl.extract_info(url, download=True)
                app.logger.info(f"Video download successful for {url} ({quality})")
            except yt_dlp.utils.DownloadError as e_video_dl:
                error_str = str(e_video_dl)
                app.logger.error(f"DownloadError during video download ({quality}) for {url}: {error_str}")
                if "http error 429" in error_str.lower() or "too many requests" in error_str.lower():
                    return jsonify({'error': 'YouTube rate-limited during video download. Try again with fresh cookies.'}), 429
                return jsonify({'error': f'Failed to download video ({quality}): {error_str}'}), 500
            except Exception as e_video_generic:
                app.logger.error(f"Generic error during video download ({quality}) for {url}: {e_video_generic}", exc_info=True)
                return jsonify({'error': f'Server error during video download: {e_video_generic}'}), 500

            # Determine the actual filename yt-dlp used
            # yt-dlp.prepare_filename(info_dict) is the most reliable way
            # We need info_dict from the download step, not just the filename info fetch
            actual_downloaded_filename = None
            if downloaded_video_info:
                # Create a temporary ydl instance just to call prepare_filename
                # This is a bit of a workaround, ideally, yt-dlp would return the final path more directly
                # or the hook system would be used.
                try:
                    temp_ydl_for_path = yt_dlp.YoutubeDL(final_download_opts) # Use same opts for path generation
                    actual_downloaded_filename = os.path.basename(temp_ydl_for_path.prepare_filename(downloaded_video_info))
                    app.logger.info(f"yt-dlp prepared filename: {actual_downloaded_filename}")
                except Exception as e_path:
                    app.logger.error(f"Could not determine exact downloaded filename using prepare_filename: {e_path}")
            
            # Fallback if prepare_filename failed or info wasn't rich enough
            if not actual_downloaded_filename:
                # Construct expected filename based on outtmpl and fetched info
                # This is less reliable than prepare_filename
                expected_stem = sanitize_filename(info_dict_for_filename.get('title', video_id))
                # The extension would be .mp4 due to merge_output_format
                actual_downloaded_filename = f"{expected_stem}.mp4" 
                app.logger.warning(f"Falling back to constructed filename: {actual_downloaded_filename}")


            full_file_path = os.path.join(download_path, actual_downloaded_filename)
            app.logger.info(f"Checking for downloaded file at: {full_file_path}")

            if os.path.exists(full_file_path):
                return jsonify({
                    'download_url': f'/downloads/{actual_downloaded_filename}',
                    'filename': actual_downloaded_filename
                })
            else:
                # If the primary expected file isn't there, list dir and try to find a match
                # This can happen if sanitize_filename or yt-dlp's naming differs slightly
                app.logger.error(f"Video file not found at expected path: {full_file_path}. Listing download directory...")
                try:
                    files_in_download_dir = os.listdir(download_path)
                    app.logger.debug(f"Files in download_path ('{download_path}'): {files_in_download_dir}")
                    # Try a more generic match based on video_id or title parts
                    possible_match = None
                    title_part = sanitize_filename(info_dict_for_filename.get('title','')).lower() if info_dict_for_filename.get('title') else video_id.lower()
                    for f_name in files_in_download_dir:
                        if f_name.endswith('.mp4') and (video_id.lower() in f_name.lower() or (title_part and title_part in f_name.lower())):
                            possible_match = f_name
                            app.logger.warning(f"Found a possible match: {possible_match}. Using this file.")
                            break
                    if possible_match:
                         return jsonify({
                            'download_url': f'/downloads/{possible_match}',
                            'filename': possible_match
                        })
                    else:
                        app.logger.error("No suitable MP4 file found in download directory after exhaustive check.")
                        return jsonify({'error': 'Video download completed, but the final file could not be located on the server.'}), 500
                except Exception as list_err:
                    app.logger.error(f"Error listing download directory: {list_err}")
                    return jsonify({'error': 'Video download might have completed, but an error occurred verifying the file.'}), 500
    
    except yt_dlp.utils.MaxDownloadsReached:
        app.logger.error("Max downloads reached error from yt-dlp.")
        return jsonify({'error': 'Max downloads reached. This is unexpected.'}), 500
    except Exception as e:
        app.logger.error(f"Unexpected error in download_video: {e}", exc_info=True)
        return jsonify({'error': f'Server error during download: {str(e)}'}), 500
    finally:
        if cookies_file_path and os.path.exists(cookies_file_path):
            try:
                os.remove(cookies_file_path)
                app.logger.info(f"Cleaned up cookie file in download finally: {cookies_file_path}")
            except Exception as e_cleanup:
                app.logger.error(f"Failed to clean up cookie file in download finally: {e_cleanup}")

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
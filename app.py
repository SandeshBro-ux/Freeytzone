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

load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'cookies'
app.config['DOWNLOAD_FOLDER'] = 'downloads'
app.secret_key = os.urandom(24)

API_KEY = os.getenv("YOUTUBE_API_KEY")
YTDLP_PROXY_URL = os.getenv("YTDLP_PROXY_URL")

if not API_KEY:
    print("WARNING: YOUTUBE_API_KEY environment variable is not set. API dependent features may fail.")

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
if not os.path.exists(app.config['DOWNLOAD_FOLDER']):
    os.makedirs(app.config['DOWNLOAD_FOLDER'])

if YTDLP_PROXY_URL:
    print(f"INFO: Using yt-dlp proxy: {YTDLP_PROXY_URL}")

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
    user_agent_from_client = data.get('user_agent') # Get User-Agent from client

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'error': 'Invalid YouTube URL'}), 400

    cookies_file_path = None
    info_dict = None
    encountered_429 = False # Flag to track if a 429 was seen

    try:
        cookies_file_path = create_cookie_file(cookies_content, f"fetch_{video_id}")
        
        # It's good practice to set common ydl_opts once
        base_ydl_opts = {
            'noplaylist': True,
            'quiet': False, 
            'no_warnings': False,
            'skip_download': True,
            'forcejson': True,
            'youtube_skip_dash_manifest': True,
            # Default User-Agent, will be overridden if client provides one
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        if user_agent_from_client and user_agent_from_client.strip():
            base_ydl_opts['user_agent'] = user_agent_from_client.strip()
            print(f"INFO: Using client-provided User-Agent for yt-dlp: {base_ydl_opts['user_agent']}")
        elif YTDLP_PROXY_URL: # Keep this condition if you want to show proxy usage regardless of UA
             print(f"INFO: Using default User-Agent for yt-dlp with proxy: {base_ydl_opts['user_agent']}")

        if YTDLP_PROXY_URL:
            base_ydl_opts['proxy'] = YTDLP_PROXY_URL

        # Attempt 1: With cookies (if provided)
        if cookies_file_path:
            print(f"Attempting to fetch info for {url} WITH cookies: {cookies_file_path}")
            ydl_opts_with_cookies = base_ydl_opts.copy()
            ydl_opts_with_cookies['cookiefile'] = cookies_file_path
            try:
                with yt_dlp.YoutubeDL(ydl_opts_with_cookies) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as err:
                error_str = str(err).lower()
                print(f"yt-dlp DownloadError WITH cookies: {error_str}")
                if "http error 429" in error_str or "too many requests" in error_str:
                    encountered_429 = True
                info_dict = None 
            except Exception as e_generic:
                print(f"Generic yt-dlp error WITH cookies: {e_generic}")
                info_dict = None

        # Attempt 2: Without cookies (if no cookies used OR first attempt failed)
        if not info_dict:
            print(f"Attempting to fetch info for {url} WITHOUT cookies.")
            ydl_opts_no_cookies = base_ydl_opts.copy()
            ydl_opts_no_cookies['cookiefile'] = None # Explicitly ensure no cookie file
            try:
                with yt_dlp.YoutubeDL(ydl_opts_no_cookies) as ydl2:
                    info_dict = ydl2.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as err_no_cookies:
                error_str = str(err_no_cookies).lower()
                print(f"yt-dlp DownloadError WITHOUT cookies: {error_str}")
                if "http error 429" in error_str or "too many requests" in error_str:
                    encountered_429 = True
                # If this fails, this is our final yt-dlp error for info
                # The jsonify below will handle the encountered_429 flag
            except Exception as e_generic_no_cookies:
                print(f"Generic yt-dlp error WITHOUT cookies: {e_generic_no_cookies}")
                # Let the generic error handling catch this if info_dict is still None
        
        # Check results after all attempts
        if not info_dict:
            # If a 429 error was encountered at any point, prioritize that message
            if encountered_429:
                return jsonify({'error': 'YouTube is rate-limiting requests from this server. Please provide cookies or try again much later.'}), 429
            else:
                # If no 429, but still no info_dict, return a generic yt-dlp failure
                return jsonify({'error': 'Failed to fetch video info from yt-dlp after all attempts. The content may be unavailable or private.'}), 500

        # --- If we got here, info_dict should be populated --- 
        
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
            
            # Use a browser-like user agent to help avoid detection
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
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
    user_agent_from_client = data.get('user_agent') # Get User-Agent from client

    if not url or not quality:
        return jsonify({'error': 'URL and quality are required'}), 400

    video_id = extract_video_id(url) or "unknown"
    cookies_file_path = None
    info_dict_for_filename = {} # For storing info used for filename generation
    
    try:
        cookies_file_path = create_cookie_file(cookies_content, f"dl_{video_id}")
        download_path = app.config['DOWNLOAD_FOLDER']
        
        base_ydl_opts = {
            'cookiefile': cookies_file_path,
            'noplaylist': True,
            'outtmpl': os.path.join(download_path, '%(title)s.%(ext)s'),
            'noprogress': True,
            'verbose': False, 
            'quiet': True,
            'nopart': True,
            'continuedl': False,
            'http_headers': { # These are for direct HTTP requests if yt-dlp makes them, distinct from UA for yt-dlp itself
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'DNT': '1',
                'Connection': 'keep-alive',
            },
            'youtube_skip_dash_manifest': True,
            # Default User-Agent for yt-dlp internal operations, will be overridden
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        if user_agent_from_client and user_agent_from_client.strip():
            base_ydl_opts['user_agent'] = user_agent_from_client.strip()
            # Also update http_headers User-Agent if client provides one, for consistency
            base_ydl_opts['http_headers']['User-Agent'] = user_agent_from_client.strip()
            print(f"INFO: Using client-provided User-Agent for yt-dlp download: {base_ydl_opts['user_agent']}")
        elif YTDLP_PROXY_URL:
             print(f"INFO: Using default User-Agent for yt-dlp download with proxy: {base_ydl_opts['user_agent']}")

        if YTDLP_PROXY_URL:
            base_ydl_opts['proxy'] = YTDLP_PROXY_URL

        # Initial info fetch for filename (always try, but handle failure)
        temp_ydl_opts_for_info = base_ydl_opts.copy()
        temp_ydl_opts_for_info.pop('format', None)
        temp_ydl_opts_for_info.pop('postprocessors', None)
        temp_ydl_opts_for_info.pop('postprocessor_args', None)
        temp_ydl_opts_for_info['outtmpl'] = os.path.join(download_path, '%(id)s_temp_info.%(ext)s')
        temp_ydl_opts_for_info['skip_download'] = True
        temp_ydl_opts_for_info['quiet'] = False # Let's see output for this specific step
        temp_ydl_opts_for_info['forcejson'] = True

        print("Attempting initial info fetch for filename (download route)...")
        try:
            with yt_dlp.YoutubeDL(temp_ydl_opts_for_info) as ydl_info_fetch:
                info_dict_for_filename = ydl_info_fetch.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e_info_dl_err:
            error_str = str(e_info_dl_err).lower()
            print(f"DownloadError during initial info fetch for filename: {error_str}")
            if "http error 429" in error_str or "too many requests" in error_str:
                if cookies_file_path and os.path.exists(cookies_file_path):
                    try: os.remove(cookies_file_path)
                    except Exception as e_rm: print(f"Error removing cookie file early: {e_rm}")
                return jsonify({
                    'error': 'YouTube is rate-limiting requests. Cannot fetch video title for download. Please use cookies or try again later.'
                }), 429
            # For other errors, we might proceed with a default filename, so don't return error yet.
            # info_dict_for_filename will remain empty {} as initialized.
        except Exception as e_generic_info:
            print(f"Generic error during initial info fetch for filename: {e_generic_info}")
            # info_dict_for_filename will remain empty {}.

        if info_dict_for_filename.get('title'):
            final_filename_stem = sanitize_filename(info_dict_for_filename.get('title', 'video'))
            base_ydl_opts['outtmpl'] = os.path.join(download_path, f'{final_filename_stem}.%(ext)s')
        else:
            base_ydl_opts['outtmpl'] = os.path.join(download_path, f'{video_id}_%(height)sp.%(ext)s')

        # --- Actual download process starts here ---
        # Add 'format' and other download-specific options back to base_ydl_opts
        # (This part of your existing logic seems okay, but it will also be subject to 429s)

        if quality == 'mp3':
            format_selector = 'bestaudio/best'
            output_template_for_ydl = os.path.join(download_path, '%(id)s_temp_audio.%(ext)s')
            fixed_mp3_filename = "freeytzone(audio).mp3" 
            final_mp3_path_on_server = os.path.join(download_path, fixed_mp3_filename)

            # Update base_ydl_opts specifically for MP3 download
            mp3_ydl_opts = base_ydl_opts.copy()
            mp3_ydl_opts.update({
                'format': format_selector,
                'outtmpl': output_template_for_ydl, 
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True, 
                'ffmpeg_location': os.getenv('FFMPEG_PATH')
            })

            try:
                with yt_dlp.YoutubeDL(mp3_ydl_opts) as ydl:
                    download_info_dict = ydl.extract_info(url, download=True)
            except yt_dlp.utils.DownloadError as e_mp3_dl:
                error_str = str(e_mp3_dl).lower()
                print(f"DownloadError during MP3 download: {error_str}")
                if "http error 429" in error_str or "too many requests" in error_str:
                    if cookies_file_path and os.path.exists(cookies_file_path):
                        try: os.remove(cookies_file_path)
                        except Exception as e_rm: print(f"Error removing cookie file early: {e_rm}")
                    return jsonify({'error': 'YouTube is rate-limiting downloads. Please try again later or use cookies.'}), 429
                if cookies_file_path and os.path.exists(cookies_file_path):
                    try: os.remove(cookies_file_path)
                    except Exception as e_rm: print(f"Error removing cookie file early: {e_rm}")
                return jsonify({'error': f'Failed to download MP3: {error_str}'}), 500

            temp_audio_id = download_info_dict.get('id', 'temp_audio')
            temp_audio_base = os.path.join(download_path, f"{temp_audio_id}_temp_audio.mp3")

            if os.path.exists(final_mp3_path_on_server):
                os.remove(final_mp3_path_on_server)
            
            if os.path.exists(temp_audio_base):
                os.rename(temp_audio_base, final_mp3_path_on_server)
            else:
                print(f"MP3 file not found at expected path: {temp_audio_base}")
                # Search for any MP3 file with the temp ID in the name
                mp3_files = [f for f in os.listdir(download_path) if temp_audio_id in f and f.endswith('.mp3')]
                if mp3_files:
                    print(f"Found alternative MP3 file: {mp3_files[0]}")
                    os.rename(os.path.join(download_path, mp3_files[0]), final_mp3_path_on_server)
                else:
                    return jsonify({'error': 'MP3 conversion failed. Output file not found.'}), 500

            if os.path.exists(final_mp3_path_on_server):
                return jsonify({
                    'download_url': f'/downloads/{fixed_mp3_filename}',
                    'filename': fixed_mp3_filename
                })
            else:
                return jsonify({'error': 'MP3 finalization failed.'}), 500

        elif quality == '2K':
            format_selector = 'bestvideo[height<=?2160]+bestaudio/best[height<=?2160]'
        elif quality == '1080p':
            format_selector = 'bestvideo[height<=?1080]+bestaudio/best[height<=?1080]'
        elif quality == '720p':
            format_selector = 'bestvideo[height<=?720]+bestaudio/best[height<=?720]'
        elif quality == 'best':
            format_selector = 'bestvideo+bestaudio/best'
        elif 'p' in quality:
            height = quality[:-1]
            format_selector = f'bestvideo[height<=?{height}]+bestaudio/best[height<=?{height}]'
        else:
            format_selector = 'bestvideo[height<=?1080]+bestaudio/best[height<=?1080]'

        # Configure video download options
        base_ydl_opts.update({
            'format': format_selector,
            'merge_output_format': 'mp4',
            'format_sort': ['acodec:aac', 'res', 'fps', 'vcodec:vp9.2', 'vcodec:vp9', 'vcodec:avc1'],
            'postprocessors': [{
                'key': 'FFmpegMetadata',
            }],
            'ffmpeg_location': os.getenv('FFMPEG_PATH'),
            # Add postprocessor args to force AAC audio in output MP4
            'postprocessor_args': {
                'merge': ['-c:a', 'aac', '-b:a', '192k']
            }
        })

        print(f"Final ydl_opts for video quality {quality}: {base_ydl_opts}")
        try:
            with yt_dlp.YoutubeDL(base_ydl_opts) as ydl:
                downloaded_video_info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e_video_dl:
            error_str = str(e_video_dl).lower()
            print(f"DownloadError during video download ({quality}): {error_str}")
            if "http error 429" in error_str or "too many requests" in error_str:
                if cookies_file_path and os.path.exists(cookies_file_path):
                    try: os.remove(cookies_file_path)
                    except Exception as e_rm: print(f"Error removing cookie file early: {e_rm}")
                return jsonify({'error': 'YouTube is rate-limiting video downloads. Please try again later or use cookies.'}), 429
            if cookies_file_path and os.path.exists(cookies_file_path):
                try: os.remove(cookies_file_path)
                except Exception as e_rm: print(f"Error removing cookie file early: {e_rm}")
            return jsonify({'error': f'Failed to download video ({quality}): {error_str}'}), 500

        list_of_files = os.listdir(download_path)
        info_for_filename_check = info_dict_for_filename if info_dict_for_filename.get('title') else downloaded_video_info
        expected_title_stem = sanitize_filename(info_for_filename_check.get('title', 'video'))
        
        if not info_dict_for_filename.get('title'):
            height_str = str(downloaded_video_info.get('height', '')) + "p" if downloaded_video_info.get('height') else "res"
            expected_title_stem = sanitize_filename(video_id + "_" + height_str)

        downloaded_filename = None
        possible_exts = [info_for_filename_check.get('ext')] 
        if quality == '1080p' or quality == '720p' or quality == '2K': possible_exts.append('mp4')
        if quality == 'mp3': possible_exts.append('mp3')
        possible_exts = list(set(filter(None, possible_exts)))

        for f_name in sorted(list_of_files, key=lambda x: os.path.getmtime(os.path.join(download_path, x)), reverse=True):
            if f_name.startswith(expected_title_stem):
                file_ext_lower = f_name.split('.')[-1].lower() if '.' in f_name else ''
                for p_ext in possible_exts:
                    if file_ext_lower == p_ext.lower():
                         downloaded_filename = f_name
                         break
                if downloaded_filename:
                    break
        
        if not downloaded_filename:
            if list_of_files:
                latest_file = max([os.path.join(download_path, f) for f in list_of_files if f.lower().endswith(tuple(possible_exts) + ('.mkv', '.webm'))], 
                                   key=os.path.getctime, default=None)
                if latest_file:
                    downloaded_filename = os.path.basename(latest_file)
                    print(f"Fallback: Guessed downloaded filename as: {downloaded_filename}")

        if not downloaded_filename:
             print(f"Could not determine downloaded filename for title: {expected_title_stem} and exts: {possible_exts}")
             return jsonify({'error': 'Could not determine downloaded filename after download.'}), 500

        download_url = f'/downloads/{downloaded_filename}'
        return jsonify({
            'message': 'Download successful', 
            'filename': downloaded_filename,
            'download_url': download_url
        })
    except yt_dlp.utils.DownloadError as e:
        error_message = str(e).lower()
        print(f"Outer DownloadError catch in /download: {error_message}")
        if "http error 429" in error_message or "too many requests" in error_message:
            return jsonify({'error': 'YouTube is rate-limiting requests. Please use cookies or try again later.'}), 429
        if "is age restricted" in error_message:
            return jsonify({'error': 'This video is age-restricted and requires cookies to download.'}), 403
        if "Private video" in error_message:
            return jsonify({'error': 'This is a private video. Cookies might be required if you have access.'}), 403
        if "Video unavailable" in error_message:
            return jsonify({'error': 'This video is unavailable.'}), 404
        return jsonify({'error': f'Download failed: {error_message}'}), 500
    finally:
        if cookies_file_path and os.path.exists(cookies_file_path):
            try:
                os.remove(cookies_file_path)
                print(f"Cleaned up temporary cookie file in finally /download: {cookies_file_path}")
            except Exception as e:
                print(f"Error cleaning up cookie file in finally /download {cookies_file_path}: {e}")

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
    app.run(debug=True, host='0.0.0.0') 
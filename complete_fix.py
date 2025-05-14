import os
import sys
import shutil
import logging
import subprocess
import time

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("complete_fix.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def modify_app_for_direct_download():
    """Add a simple direct download method to app.py"""
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
    
    # Create backup
    backup_path = app_path + '.final.bak'
    logger.info(f"Backing up app.py to {backup_path}")
    shutil.copy2(app_path, backup_path)
    
    # Create the new simplified download method
    new_route = """
# Simple direct download method
@app.route('/direct-download/<download_id>', methods=['GET'])
def direct_download(download_id):
    try:
        logger.info(f"Direct download requested for ID: {download_id}")
        file_path, filename, mime_type = downloader.get_download_file(download_id)
        
        if not file_path:
            return jsonify({'error': 'Download not found or not completed'}), 404
        
        if not os.path.exists(file_path):
            logger.error(f"File does not exist: {file_path}")
            return jsonify({'error': 'File does not exist'}), 404
        
        # Send the file directly
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype=mime_type
        )
    except Exception as e:
        logger.error(f"Error in direct download: {str(e)}")
        return jsonify({'error': str(e)}), 500
"""
    
    # Read the file
    with open(app_path, 'r') as f:
        content = f.readlines()
    
    # Find a good insertion point right before @app.before_request
    for i, line in enumerate(content):
        if "@app.before_request" in line:
            logger.info(f"Found insertion point at line {i}")
            content.insert(i, new_route)
            break
    
    # Write the updated file
    with open(app_path, 'w') as f:
        f.writelines(content)
    
    logger.info("Added direct download route to app.py")

def create_new_download_html():
    """Create a simple HTML download page"""
    download_html = """<!DOCTYPE html>
<html>
<head>
    <title>Direct YouTube Downloader</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .form-group {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }
        input[type="text"], select {
            width: 100%;
            padding: 8px;
            box-sizing: border-box;
        }
        button {
            background-color: #4CAF50;
            color: white;
            padding: 10px 15px;
            border: none;
            cursor: pointer;
        }
        button:hover {
            background-color: #45a049;
        }
        .result {
            margin-top: 20px;
            padding: 15px;
            background-color: #fff;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .progress {
            height: 20px;
            margin-top: 10px;
            background-color: #f0f0f0;
            border-radius: 10px;
            overflow: hidden;
        }
        .progress-bar {
            height: 100%;
            background-color: #4CAF50;
            width: 0%;
            transition: width 0.3s;
        }
        .error {
            color: red;
            font-weight: bold;
        }
        .success {
            color: green;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <h1>Direct YouTube Downloader</h1>
    <div class="form-group">
        <label for="url">YouTube URL:</label>
        <input type="text" id="url" placeholder="Enter YouTube URL">
    </div>
    <div class="form-group">
        <label for="format">Format:</label>
        <select id="format">
            <option value="video">Video (MP4)</option>
            <option value="audio">Audio (MP3)</option>
        </select>
    </div>
    <button id="download-btn">Start Download</button>
    
    <div id="result" class="result" style="display: none;">
        <h3 id="status-text">Downloading...</h3>
        <div class="progress">
            <div id="progress-bar" class="progress-bar"></div>
        </div>
        <p id="progress-text">0%</p>
        <p id="speed-text"></p>
        <p id="eta-text"></p>
        <button id="download-link" style="display: none;">Download File</button>
    </div>

    <script>
        const urlInput = document.getElementById('url');
        const formatSelect = document.getElementById('format');
        const downloadBtn = document.getElementById('download-btn');
        const result = document.getElementById('result');
        const statusText = document.getElementById('status-text');
        const progressBar = document.getElementById('progress-bar');
        const progressText = document.getElementById('progress-text');
        const speedText = document.getElementById('speed-text');
        const etaText = document.getElementById('eta-text');
        const downloadLink = document.getElementById('download-link');
        
        let currentDownloadId = null;
        let progressInterval = null;
        
        downloadBtn.addEventListener('click', async function() {
            const url = urlInput.value.trim();
            if (!url) {
                alert('Please enter a YouTube URL');
                return;
            }
            
            // Reset UI
            result.style.display = 'block';
            statusText.textContent = 'Starting download...';
            statusText.className = '';
            progressBar.style.width = '0%';
            progressText.textContent = '0%';
            speedText.textContent = '';
            etaText.textContent = '';
            downloadLink.style.display = 'none';
            
            try {
                // Start download
                const response = await fetch('/api/download', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        url: url,
                        format: formatSelect.value,
                        quality: 'best'
                    }),
                });
                
                const data = await response.json();
                
                if (data.error) {
                    showError(data.error);
                    return;
                }
                
                currentDownloadId = data.download_id;
                
                // Start checking progress
                if (progressInterval) {
                    clearInterval(progressInterval);
                }
                
                progressInterval = setInterval(checkProgress, 1000);
                
            } catch (error) {
                showError('Failed to start download: ' + error.message);
            }
        });
        
        downloadLink.addEventListener('click', function(e) {
            e.preventDefault();
            if (!currentDownloadId) return;
            
            // Simple direct download
            window.location.href = `/direct-download/${currentDownloadId}`;
        });
        
        async function checkProgress() {
            if (!currentDownloadId) return;
            
            try {
                const response = await fetch(`/api/progress/${currentDownloadId}`);
                const data = await response.json();
                
                if (data.error) {
                    clearInterval(progressInterval);
                    showError(data.error);
                    return;
                }
                
                // Update progress
                progressBar.style.width = `${data.progress}%`;
                progressText.textContent = `${Math.round(data.progress)}%`;
                
                if (data.speed !== 'N/A') {
                    speedText.textContent = `Speed: ${data.speed}`;
                }
                
                if (data.eta !== 'N/A') {
                    etaText.textContent = `ETA: ${data.eta}`;
                }
                
                // Check if download is complete
                if (data.status === 'completed') {
                    clearInterval(progressInterval);
                    statusText.textContent = 'Download complete!';
                    statusText.className = 'success';
                    downloadLink.style.display = 'inline-block';
                }
                
                // Check if download failed
                if (data.status === 'failed') {
                    clearInterval(progressInterval);
                    showError('Download failed');
                }
                
                // Check if download was canceled
                if (data.status === 'canceled') {
                    clearInterval(progressInterval);
                    statusText.textContent = 'Download canceled';
                    statusText.className = 'error';
                }
                
            } catch (error) {
                console.error('Error checking progress:', error);
            }
        }
        
        function showError(message) {
            statusText.textContent = message;
            statusText.className = 'error';
        }
    </script>
</body>
</html>
"""
    
    # Create the file
    direct_html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'direct.html')
    logger.info(f"Creating direct.html at {direct_html_path}")
    
    with open(direct_html_path, 'w') as f:
        f.write(download_html)
    
    # Add route to app.py for the direct page
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
    
    with open(app_path, 'r') as f:
        content = f.readlines()
    
    # Find the route for the main page
    for i, line in enumerate(content):
        if "@app.route('/')" in line:
            # Add our direct route after the main route
            direct_route = """
@app.route('/direct')
def direct_page():
    \"\"\"Render the direct download page\"\"\"
    return render_template('direct.html')
"""
            # Find the end of the main route function
            for j in range(i+1, len(content)):
                if "def " in content[j] or "@app" in content[j]:
                    content.insert(j, direct_route)
                    break
            break
    
    # Write the updated file
    with open(app_path, 'w') as f:
        f.writelines(content)
    
    logger.info("Added direct page route to app.py")

def check_ffmpeg():
    """Verify ffmpeg is properly installed and in PATH"""
    logger.info("Checking ffmpeg installation...")
    
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info(f"ffmpeg is properly installed: {result.stdout.splitlines()[0]}")
            return True
        else:
            logger.error(f"ffmpeg check failed: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error checking ffmpeg: {str(e)}")
        return False

def clear_downloads():
    """Clear the downloads directory"""
    downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
    logger.info(f"Clearing downloads directory: {downloads_dir}")
    
    # Remove all subdirectories in downloads
    for item in os.listdir(downloads_dir):
        item_path = os.path.join(downloads_dir, item)
        if os.path.isdir(item_path):
            try:
                shutil.rmtree(item_path)
                logger.info(f"Removed directory: {item_path}")
            except Exception as e:
                logger.error(f"Error removing directory {item_path}: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting complete fix...")
    
    # Check ffmpeg
    if not check_ffmpeg():
        logger.warning("ffmpeg may not be properly installed. Downloads might fail.")
    
    # Clear downloads
    clear_downloads()
    
    # Modify app.py for direct download
    modify_app_for_direct_download()
    
    # Create new direct download HTML page
    create_new_download_html()
    
    logger.info("Complete fix applied. Please restart your application and visit /direct for a simpler download experience.")

import os
import logging
import sys
import subprocess
import platform

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tunnel_debug.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def check_environment():
    """Check if all required dependencies are installed"""
    logger.info("Checking environment...")
    
    # Check Python version
    logger.info(f"Python version: {sys.version}")
    
    # Check OS details
    logger.info(f"Platform: {platform.platform()}")
    
    # Check yt-dlp
    logger.info("Checking yt-dlp installation...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            logger.info(f"yt-dlp version: {result.stdout.strip()}")
        else:
            logger.error(f"yt-dlp check failed: {result.stderr}")
    except Exception as e:
        logger.error(f"Error checking yt-dlp: {str(e)}")
    
    # Check ffmpeg
    logger.info("Checking ffmpeg installation...")
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            logger.info(f"ffmpeg found: {result.stdout.split('\\n')[0]}")
        else:
            logger.error(f"ffmpeg check failed: {result.stderr}")
    except Exception as e:
        logger.error(f"Error checking ffmpeg: {str(e)}")
    
    # Check download directory
    downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
    logger.info(f"Download directory: {downloads_dir}")
    if os.path.exists(downloads_dir):
        logger.info(f"Download directory exists with permissions: {oct(os.stat(downloads_dir).st_mode)[-3:]}")
        try:
            test_file = os.path.join(downloads_dir, 'test_write.txt')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            logger.info("Write test to download directory succeeded")
        except Exception as e:
            logger.error(f"Write test to download directory failed: {str(e)}")
    else:
        logger.error("Download directory does not exist")

if __name__ == "__main__":
    logger.info("Starting environment check...")
    check_environment()
    logger.info("Environment check complete")

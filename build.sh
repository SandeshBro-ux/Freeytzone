#!/bin/bash
# Script to download Chrome binary and ChromeDriver for Render

# Enable detailed debugging
set -x

# Don't exit on error immediately
set +e

echo "============================================================"
echo "DETAILED BUILD DEBUGGING"
echo "============================================================"
echo "Current directory: $(pwd)"
echo "Home directory: $HOME"
echo "Environment: $(env | sort)"
echo "============================================================"

# Create directories for binaries
mkdir -p $HOME/chrome-bin
echo "Created chrome-bin directory at $HOME/chrome-bin"
ls -la $HOME/chrome-bin

# Download ChromeDriver directly
echo "Downloading ChromeDriver..."
CHROMEDRIVER_VERSION="114.0.5735.90"  # Use a stable version
wget -q "https://chromedriver.storage.googleapis.com/$CHROMEDRIVER_VERSION/chromedriver_linux64.zip" || { 
    echo "ERROR: ChromeDriver download failed!"
    exit 1
}
echo "ChromeDriver download successful, unzipping..."
unzip -q chromedriver_linux64.zip || {
    echo "ERROR: Failed to unzip ChromeDriver!"
    exit 1
}
chmod +x chromedriver
mv chromedriver $HOME/chrome-bin/ || {
    echo "ERROR: Failed to move ChromeDriver to chrome-bin directory!"
    exit 1
}
rm -f chromedriver_linux64.zip
echo "ChromeDriver installed at $HOME/chrome-bin/chromedriver"
ls -la $HOME/chrome-bin

# Create a debug directory to examine download files
echo "Creating debug directory..."
mkdir -p $HOME/debug
cd $HOME/debug
echo "Current directory: $(pwd)"

# Use a more direct approach for headless Chrome - use the prebuilt binary
echo "Downloading headless Chrome binary directly..."
# Try a different source - Puppeteer's Chrome binary
CHROME_BINARY_URL="https://github.com/Sparticuz/chromium/releases/download/v114.0.0/chromium-v114.0.0-linux.zip"
echo "Downloading from: $CHROME_BINARY_URL"
wget -v "$CHROME_BINARY_URL" || {
    echo "ERROR: Failed to download Chrome binary!"
    exit 1
}

echo "Download completed. Listing files in current directory:"
ls -la

echo "Extracting Chrome binary..."
unzip -v chromium-v114.0.0-linux.zip || {
    echo "ERROR: Failed to unzip Chrome binary!"
    echo "Details of the zip file:"
    file chromium-v114.0.0-linux.zip
    exit 1
}

# Check what files were extracted (for debugging)
echo "Extracted files in current directory:"
ls -la

# Print detailed info about the extracted files
echo "Detailed file info:"
file *

# Try a different approach if headless-chromium isn't found
if [ ! -f "headless-chromium" ]; then
    echo "WARNING: headless-chromium not found in current directory!"
    echo "Trying alternative extraction approach..."
    
    # Download directly from official source
    echo "Downloading Chrome from official source..."
    wget -v "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb" || {
        echo "ERROR: Failed to download Chrome from official source!"
        exit 1
    }
    
    echo "Extracting Chrome binary from deb package..."
    mkdir -p chrome-extract
    dpkg -x google-chrome-stable_current_amd64.deb chrome-extract || {
        echo "ERROR: Failed to extract Chrome deb package!"
        exit 1
    }
    
    echo "Files extracted from deb package:"
    ls -la chrome-extract
    
    # Find Chrome binary in extracted files
    CHROME_BIN=$(find chrome-extract -name "chrome" -type f | head -n 1)
    if [ -n "$CHROME_BIN" ]; then
        echo "Found Chrome binary at: $CHROME_BIN"
        cp "$CHROME_BIN" $HOME/chrome-bin/chrome || {
            echo "ERROR: Failed to copy Chrome binary!"
            exit 1
        }
        chmod +x $HOME/chrome-bin/chrome
    else
        echo "ERROR: Chrome binary not found in extracted package!"
        exit 1
    fi
else
    # The main binary should be called "headless-chromium"
    echo "Found headless-chromium binary"
    chmod +x headless-chromium || {
        echo "ERROR: Failed to make headless-chromium executable!"
        exit 1
    }
    
    cp headless-chromium $HOME/chrome-bin/ || {
        echo "ERROR: Failed to copy headless-chromium to chrome-bin directory!"
        exit 1
    }
    
    # Create a symlink named 'chrome' for compatibility
    ln -sf $HOME/chrome-bin/headless-chromium $HOME/chrome-bin/chrome || {
        echo "ERROR: Failed to create symlink!"
        exit 1
    }
fi

# Clean up
cd -
echo "Final chrome-bin directory contents:"
ls -la $HOME/chrome-bin

# Verify installation
echo "Chrome binary path: $(find $HOME/chrome-bin -type f -executable | grep -E 'chrome|headless')"
echo "ChromeDriver path: $HOME/chrome-bin/chromedriver"
echo "ChromeDriver version: $($HOME/chrome-bin/chromedriver --version || echo 'Failed to get ChromeDriver version')"

# Add the directory to PATH
export PATH="$HOME/chrome-bin:$PATH"
echo 'export PATH="$HOME/chrome-bin:$PATH"' >> ~/.bashrc

echo "Chrome and ChromeDriver setup complete!"

# Install Python packages
echo "Installing Python packages..."
pip install -r requirements.txt || {
    echo "ERROR: Failed to install Python packages!"
    exit 1
}

echo "Build script completed successfully!" 
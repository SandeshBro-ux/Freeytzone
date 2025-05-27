#!/bin/bash
# Script to download Chrome and ChromeDriver binaries for Render

# Exit on any error
set -e

echo "Setting up Chrome and ChromeDriver for Render deployment..."

# Create a directory for the binaries
mkdir -p $HOME/chrome-bin

# Download Chrome
echo "Downloading Chrome..."
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
ar x google-chrome-stable_current_amd64.deb data.tar.xz
tar -xf data.tar.xz ./opt/google/chrome/chrome --strip-components=3
mv chrome $HOME/chrome-bin/
rm -f google-chrome-stable_current_amd64.deb data.tar.xz

# Get the Chrome version
CHROME_VERSION=$($HOME/chrome-bin/chrome --version | awk '{print $3}' | cut -d. -f1)
echo "Detected Chrome version: $CHROME_VERSION"

# Download matching ChromeDriver
echo "Downloading ChromeDriver..."
CHROMEDRIVER_VERSION=$(wget -qO- "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_$CHROME_VERSION")
wget -q "https://chromedriver.storage.googleapis.com/$CHROMEDRIVER_VERSION/chromedriver_linux64.zip"
unzip -q chromedriver_linux64.zip
mv chromedriver $HOME/chrome-bin/
rm -f chromedriver_linux64.zip

# Make the binaries executable
chmod +x $HOME/chrome-bin/chrome $HOME/chrome-bin/chromedriver

# Create symbolic links
mkdir -p $HOME/bin
ln -sf $HOME/chrome-bin/chrome $HOME/bin/chrome
ln -sf $HOME/chrome-bin/chromedriver $HOME/bin/chromedriver

# Add to PATH
export PATH="$HOME/bin:$PATH"

# Verify installation
echo "Chrome path: $HOME/chrome-bin/chrome"
echo "ChromeDriver path: $HOME/chrome-bin/chromedriver"
echo "Chrome version: $($HOME/chrome-bin/chrome --version)"
echo "ChromeDriver version: $($HOME/chrome-bin/chromedriver --version)"

echo "Chrome and ChromeDriver setup complete!"

# Install Python packages
pip install -r requirements.txt 
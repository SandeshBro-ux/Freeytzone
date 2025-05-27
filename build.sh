#!/bin/bash
# Script to download Chrome binary and ChromeDriver for Render

# Exit on any error
set -e

echo "Setting up Chrome and ChromeDriver for Render deployment..."

# Create directories for binaries
mkdir -p $HOME/chrome-bin

# Download ChromeDriver directly
echo "Downloading ChromeDriver..."
CHROMEDRIVER_VERSION="114.0.5735.90"  # Use a stable version
wget -q "https://chromedriver.storage.googleapis.com/$CHROMEDRIVER_VERSION/chromedriver_linux64.zip"
unzip -q chromedriver_linux64.zip
chmod +x chromedriver
mv chromedriver $HOME/chrome-bin/
rm -f chromedriver_linux64.zip

# Use direct download for a headless Chrome binary (ChromeDP)
echo "Downloading headless Chrome..."
mkdir -p $HOME/tmp
cd $HOME/tmp
wget -q https://github.com/Sparticuz/chromium/releases/download/v114.0.0/chromium-v114.0.0-pack.tar
tar -xf chromium-v114.0.0-pack.tar
cp -r chrome-linux/* $HOME/chrome-bin/
rm -rf chrome-linux chromium-v114.0.0-pack.tar
cd -

# Verify installation
echo "Chrome binary path: $HOME/chrome-bin/chrome"
echo "ChromeDriver path: $HOME/chrome-bin/chromedriver"
echo "ChromeDriver version: $($HOME/chrome-bin/chromedriver --version)"

# Add the directory to PATH
export PATH="$HOME/chrome-bin:$PATH"
echo 'export PATH="$HOME/chrome-bin:$PATH"' >> ~/.bashrc

echo "Chrome and ChromeDriver setup complete!"

# Install Python packages
pip install -r requirements.txt 
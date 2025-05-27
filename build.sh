#!/bin/bash
# Simple script to download Chrome and ChromeDriver for Render

# Create binary directory
mkdir -p $HOME/chrome-bin

# Download and install ChromeDriver
echo "Setting up ChromeDriver..."
wget -q "https://chromedriver.storage.googleapis.com/114.0.5735.90/chromedriver_linux64.zip"
unzip -q chromedriver_linux64.zip
chmod +x chromedriver
mv chromedriver $HOME/chrome-bin/
rm chromedriver_linux64.zip

# Download and install headless Chrome
echo "Setting up headless Chrome..."
cd /tmp
wget -q "https://github.com/Sparticuz/chromium/releases/download/v114.0.0/chromium-v114.0.0-linux.zip"
unzip -q chromium-v114.0.0-linux.zip
chmod +x headless-chromium
mv headless-chromium $HOME/chrome-bin/
cd -

# Add to PATH
export PATH="$HOME/chrome-bin:$PATH"
echo 'export PATH="$HOME/chrome-bin:$PATH"' >> ~/.bashrc

# Install Python packages
pip install -r requirements.txt 
#!/bin/bash
# Script to install Chrome and ChromeDriver on Render during build

# Exit on any error
set -e

echo "Setting up Chrome and ChromeDriver for Render deployment..."

# Install dependencies
apt-get update
apt-get install -y wget gnupg unzip

# Install Chrome
echo "Installing Google Chrome..."
wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list
apt-get update
apt-get install -y google-chrome-stable

# Get the Chrome version
CHROME_VERSION=$(google-chrome --version | awk '{ print $3 }' | cut -d '.' -f 1)

# Download matching ChromeDriver
echo "Installing ChromeDriver..."
CHROMEDRIVER_VERSION=$(wget -qO- "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_$CHROME_VERSION")
wget -q "https://chromedriver.storage.googleapis.com/$CHROMEDRIVER_VERSION/chromedriver_linux64.zip"
unzip chromedriver_linux64.zip
mv chromedriver /usr/local/bin/
chmod +x /usr/local/bin/chromedriver

# Verify installation
echo "Chrome version: $(google-chrome --version)"
echo "ChromeDriver version: $(chromedriver --version)"

echo "Chrome and ChromeDriver setup complete!" 
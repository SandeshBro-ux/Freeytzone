const fs = require('fs-extra');
const path = require('path');
const { spawn } = require('cross-spawn');
const { execSync } = require('child_process');

// Check if cloudflared is installed
function checkCloudflared() {
  console.log('Checking if cloudflared is installed...');
  
  try {
    let cloudflaredPath = '';
    
    if (process.platform === 'win32') {
      cloudflaredPath = 'C:\\Program Files (x86)\\cloudflared\\cloudflared.exe';
      if (!fs.existsSync(cloudflaredPath)) {
        console.log('Cloudflared not found at the expected location.');
        console.log('Please install cloudflared using: winget install --id Cloudflare.cloudflared');
        process.exit(1);
      }
    } else {
      // For Mac/Linux, check if it's in the PATH
      try {
        execSync('cloudflared --version', { stdio: 'ignore' });
        cloudflaredPath = 'cloudflared';
      } catch (err) {
        console.log('Cloudflared not found in PATH. Please install cloudflared.');
        if (process.platform === 'darwin') {
          console.log('On Mac, you can install it with: brew install cloudflared');
        } else {
          console.log('Visit: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/');
        }
        process.exit(1);
      }
    }
    
    return cloudflaredPath;
  } catch (err) {
    console.error('Error checking for cloudflared:', err);
    process.exit(1);
  }
}

// Check if Python Flask app exists
function checkFlaskApp() {
  if (!fs.existsSync('app.py')) {
    console.error('Error: app.py not found. Make sure you\'re in the YoutubeMediaGrabber directory.');
    process.exit(1);
  }
}

// Start the Flask server
function startFlaskServer(port = 5000) {
  console.log(`Starting Flask server on port ${port}...`);
  
  // Update port in app.py if necessary
  let appContent = fs.readFileSync('app.py', 'utf8');
  if (appContent.includes('port=5000') && port !== 5000) {
    appContent = appContent.replace('port=5000', `port=${port}`);
    fs.writeFileSync('app.py', appContent);
  }
  
  // Start the Flask server
  const flaskProcess = spawn('python', ['app.py'], { stdio: 'inherit' });
  
  flaskProcess.on('error', (err) => {
    console.error('Failed to start Flask server:', err);
    process.exit(1);
  });
  
  console.log(`Flask server started on port ${port}`);
  return flaskProcess;
}

// Start the Cloudflare tunnel
function startCloudflaredTunnel(cloudflaredPath, port = 5000) {
  console.log('Starting Cloudflare tunnel...');
  
  const tunnelProcess = spawn(
    cloudflaredPath, 
    ['tunnel', '--url', `http://localhost:${port}`], 
    { stdio: 'inherit' }
  );
  
  tunnelProcess.on('error', (err) => {
    console.error('Failed to start Cloudflare tunnel:', err);
    process.exit(1);
  });
  
  console.log(`Cloudflare tunnel started pointing to http://localhost:${port}`);
  console.log('Look for a URL like: https://looking-salad-arm-affects.trycloudflare.com/');
  console.log('Press Ctrl+C to stop the server and tunnel');
  
  return tunnelProcess;
}

// Main function
function main() {
  const port = 5000; // Default Flask port
  
  // Check prerequisites
  checkFlaskApp();
  const cloudflaredPath = checkCloudflared();
  
  // Start Flask server
  const serverProcess = startFlaskServer(port);
  
  // Wait a bit for the server to start
  console.log('Waiting for Flask server to start...');
  setTimeout(() => {
    // Start Cloudflare tunnel
    const tunnelProcess = startCloudflaredTunnel(cloudflaredPath, port);
    
    // Handle process termination
    process.on('SIGINT', () => {
      console.log('\nShutting down...');
      tunnelProcess.kill();
      serverProcess.kill();
      console.log('Server and tunnel stopped.');
      process.exit(0);
    });
  }, 2000);
}

// Run the main function
main(); 
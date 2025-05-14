import os
import sys
import subprocess
import time
import platform

def start_local_server(port=80):
    """Start the Flask application"""
    print(f"Starting Flask server on port {port}...")
    
    # Check if we're in the correct directory
    if not os.path.exists("app.py"):
        print("Error: app.py not found. Make sure you're in the YoutubeMediaGrabber directory.")
        sys.exit(1)
    
    # Modify the port in app.py if necessary
    with open("app.py", "r") as f:
        content = f.read()
    
    if "port=5000" in content and port != 5000:
        content = content.replace("port=5000", f"port={port}")
        with open("app.py", "w") as f:
            f.write(content)
    
    # Start the Flask server in a subprocess
    cmd = [sys.executable, "app.py"]
    try:
        flask_process = subprocess.Popen(cmd)
        print(f"Flask server is running on port {port}")
        return flask_process
    except Exception as e:
        print(f"Error starting Flask server: {e}")
        sys.exit(1)

def start_cloudflare_tunnel(local_port=80):
    """Start a Cloudflare tunnel to expose the local server"""
    print("Starting Cloudflare tunnel...")
    
    # Check if cloudflared is installed
    cloudflared_path = ""
    if platform.system() == "Windows":
        cloudflared_path = "C:\\Program Files (x86)\\cloudflared\\cloudflared.exe"
        if not os.path.exists(cloudflared_path):
            print("Cloudflared not found at the expected location.")
            print("Please install cloudflared using: winget install --id Cloudflare.cloudflared")
            sys.exit(1)
    else:
        # On Linux/Mac, check if cloudflared is in PATH
        try:
            subprocess.run(["cloudflared", "--version"], capture_output=True, check=True)
            cloudflared_path = "cloudflared"
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("Cloudflared not found in PATH. Please install cloudflared.")
            sys.exit(1)
    
    # Start the cloudflared tunnel
    tunnel_cmd = [cloudflared_path, "tunnel", "--url", f"http://localhost:{local_port}"]
    try:
        print(f"Creating tunnel to http://localhost:{local_port}")
        tunnel_process = subprocess.Popen(tunnel_cmd)
        print("Cloudflare tunnel started. Look for a URL like: https://looking-salad-arm-affects.trycloudflare.com/")
        print("Press Ctrl+C to stop the server and tunnel")
        return tunnel_process
    except Exception as e:
        print(f"Error starting Cloudflare tunnel: {e}")
        sys.exit(1)

def main():
    port = 80
    
    # Start the Flask server
    server_process = start_local_server(port)
    
    # Give the server time to start
    time.sleep(2)
    
    # Start the Cloudflare tunnel
    tunnel_process = start_cloudflare_tunnel(port)
    
    try:
        # Keep the script running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        # Terminate the processes
        tunnel_process.terminate()
        server_process.terminate()
        print("Server and tunnel stopped.")

if __name__ == "__main__":
    main() 
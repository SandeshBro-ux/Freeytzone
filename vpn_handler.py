import os
import re
import time
import requests
import random
import logging
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('vpn_handler')

class VPNBookProxyManager:
    """Handles VPNBook free proxies for use with yt-dlp"""
    
    VPNBOOK_URL = "https://www.vpnbook.com/freevpn"
    
    # Free proxy servers from VPNBook (from their website)
    PROXY_SERVERS = {
        'US': [
            'US16.vpnbook.com',
            'US178.vpnbook.com'
        ],
        'CA': [
            'CA149.vpnbook.com',
            'CA196.vpnbook.com'
        ],
        'DE': [
            'DE20.vpnbook.com',
            'DE220.vpnbook.com'
        ],
        'FR': [
            'FR200.vpnbook.com',
            'FR231.vpnbook.com'
        ],
        'UK': [
            'UK205.vpnbook.com',
            'UK68.vpnbook.com'
        ],
        'PL': [
            'PL134.vpnbook.com',
            'PL140.vpnbook.com'
        ]
    }
    
    def __init__(self):
        self.password = None
        self.last_password_fetch = 0
        self.password_cache_duration = 3600  # 1 hour
        self.username = "vpnbook"  # VPNBook default username
        self.current_proxy = None
        self.failed_proxies = set()

    def get_current_password(self, force_refresh=False):
        """Fetch the current VPNBook password from their website"""
        current_time = time.time()
        
        if (self.password is None or 
            force_refresh or 
            current_time - self.last_password_fetch > self.password_cache_duration):
            
            try:
                logger.info("Fetching current VPNBook password...")
                response = requests.get(self.VPNBOOK_URL, timeout=10)
                if response.status_code != 200:
                    logger.warning(f"Failed to fetch VPNBook password, status code: {response.status_code}")
                    if self.password:  # Return cached password if available
                        return self.password
                    return None
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find the password - it's usually in a specific format 
                # near text that says "Password:" on their website
                # This pattern might need adjustment if their site changes
                password_elements = soup.find_all('strong')
                for element in password_elements:
                    text = element.text.strip()
                    # VPNBook passwords are typically alphanumeric and 8+ characters
                    if re.match(r'^[a-zA-Z0-9]{8,}$', text):
                        self.password = text
                        self.last_password_fetch = current_time
                        logger.info(f"Found VPNBook password (updated)")
                        break
                
                if not self.password:
                    logger.warning("Could not find password on VPNBook website")
                    
            except Exception as e:
                logger.error(f"Error fetching VPNBook password: {str(e)}")
                
        return self.password

    def get_proxy_url(self, country=None, protocol="http"):
        """
        Get a proxy URL from VPNBook, with authentication
        
        Args:
            country (str): Two-letter country code (US, CA, DE, FR, UK, PL)
            protocol (str): Protocol to use (http, socks)
            
        Returns:
            str: Proxy URL in format protocol://user:pass@host:port
        """
        # Ensure we have the current password
        password = self.get_current_password()
        if not password:
            logger.warning("No VPNBook password available - proxy won't authenticate")
            return None
        
        # Select country or random if not specified
        available_countries = list(self.PROXY_SERVERS.keys())
        if not country or country not in available_countries:
            country = random.choice(available_countries)
            
        # Get servers for selected country
        servers = self.PROXY_SERVERS.get(country, [])
        if not servers:
            logger.warning(f"No servers available for country: {country}")
            return None
            
        # Select a server that hasn't failed recently
        available_servers = [s for s in servers if s not in self.failed_proxies]
        if not available_servers:
            # Reset failed proxies if all have failed
            self.failed_proxies = set()
            available_servers = servers
            
        server = random.choice(available_servers)
        
        # Determine port based on protocol
        if protocol.lower() == "http":
            port = 80  # VPNBook HTTP proxy port
        elif protocol.lower() == "socks":
            port = 1080  # VPNBook SOCKS proxy port
        else:
            port = 80  # Default to HTTP
        
        proxy_url = f"{protocol}://{self.username}:{password}@{server}:{port}"
        self.current_proxy = {'url': proxy_url, 'server': server, 'country': country}
        
        logger.info(f"Generated {protocol.upper()} proxy URL for {country} ({server})")
        return proxy_url

    def mark_current_proxy_failed(self):
        """Mark the current proxy as failed to avoid using it in subsequent requests"""
        if self.current_proxy and 'server' in self.current_proxy:
            failed_server = self.current_proxy['server']
            self.failed_proxies.add(failed_server)
            logger.warning(f"Marked proxy {failed_server} as failed")
            
    def rotate_proxy(self, country=None, protocol="http"):
        """Force rotation to a new proxy"""
        if self.current_proxy and 'server' in self.current_proxy:
            previous = self.current_proxy['server']
        else:
            previous = None
            
        # Try to get a different server than the current one
        for _ in range(5):  # Try 5 times to get a different server
            new_proxy = self.get_proxy_url(country, protocol)
            if not previous or self.current_proxy['server'] != previous:
                break
                
        return self.current_proxy

# Create a singleton instance
proxy_manager = VPNBookProxyManager()

def get_ytdlp_proxy_url(country=None, protocol="http", renew=False):
    """
    Get a proxy URL suitable for yt-dlp
    
    Args:
        country (str): Two-letter country code (US, CA, DE, FR, UK, PL)
        protocol (str): Protocol to use (http, socks)
        renew (bool): Force refresh of proxy
        
    Returns:
        str: Proxy URL
    """
    if renew:
        return proxy_manager.rotate_proxy(country, protocol)['url']
    else:
        return proxy_manager.get_proxy_url(country, protocol)
        
def mark_proxy_failed():
    """Mark the current proxy as failed"""
    proxy_manager.mark_current_proxy_failed()
    
if __name__ == "__main__":
    # Test code
    print("Testing VPNBook proxy manager...")
    password = proxy_manager.get_current_password(force_refresh=True)
    print(f"Current password: {password}")
    
    proxy_url = get_ytdlp_proxy_url("US")
    print(f"Proxy URL: {proxy_url}") 
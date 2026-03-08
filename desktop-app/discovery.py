import zeroconf
import socket
import threading
import time

class NomadDiscovery:
    def __init__(self, callback):
        self.callback = callback
        self.zeroconf = zeroconf.Zeroconf()
        self.browser = None
        self.servers = {}
        self.running = False
        
    def start(self):
        self.running = True
        self.browser = zeroconf.ServiceBrowser(self.zeroconf, "_http._tcp.local.", handlers=[self.on_service_state_change])
        
    def stop(self):
        self.running = False
        if self.browser:
            self.browser.cancel()
        self.zeroconf.close()
        
    def on_service_state_change(self, zeroconf_obj, service_type, name, state_change):
        if not self.running: return
        
        info = zeroconf_obj.get_service_info(service_type, name)
        if info:
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
            port = info.port
            server_name = name.split('.')[0]
            
            # Simple heuristic to identify Nomad Pi
            # In a real scenario, we might check TXT records or specific paths
            is_nomad = "nomad" in server_name.lower() or "raspberry" in server_name.lower()
            
            if is_nomad:
                url = f"http://{addresses[0]}:{port}"
                self.callback(server_name, addresses[0], url)

if __name__ == "__main__":
    def print_found(name, ip, url):
        print(f"Found: {name} at {url}")
        
    d = NomadDiscovery(print_found)
    d.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        d.stop()

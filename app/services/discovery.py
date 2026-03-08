import socket
import time
import threading
import json
import logging

logger = logging.getLogger("nomad")

class DiscoveryService:
    def __init__(self, port=8000):
        self.port = port
        self.running = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self.thread.start()
        logger.info("UDP Discovery Service started on port 8001")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)

    def _broadcast_loop(self):
        while self.running:
            try:
                # Prepare message
                msg = {
                    "service": "nomad-media",
                    "port": self.port,
                    "type": "discovery"
                }
                data = json.dumps(msg).encode('utf-8')
                
                # Broadcast to 255.255.255.255 on port 8001 (Firmware listens here)
                self.sock.sendto(data, ('<broadcast>', 8001))
            except Exception as e:
                # Don't spam logs if network is down
                pass
            
            time.sleep(5)

service = DiscoveryService()

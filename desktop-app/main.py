import sys
import os
import socket
import zeroconf
import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QListWidget, 
                             QListWidgetItem, QStackedWidget, QMessageBox,
                             QProgressBar, QFileDialog, QInputDialog, QGridLayout, QScrollArea)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QSize
from PyQt6.QtGui import QIcon, QFont, QPixmap, QAction
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
import requests

# --- Styles ---
DARK_THEME = """
QMainWindow {
    background-color: #1e1e1e;
    color: #ffffff;
}
QWidget {
    background-color: #1e1e1e;
    color: #ffffff;
}
QListWidget {
    background-color: #252526;
    border: 1px solid #3e3e42;
    border-radius: 5px;
    padding: 5px;
    color: #ffffff;
}
QListWidget::item {
    padding: 10px;
    border-bottom: 1px solid #3e3e42;
}
QListWidget::item:selected {
    background-color: #37373d;
}
QPushButton {
    background-color: #007acc;
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 4px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #0098ff;
}
QPushButton:disabled {
    background-color: #3e3e42;
    color: #888888;
}
QLabel {
    color: #cccccc;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollArea > QWidget > QWidget {
    background-color: transparent;
}
"""

class MediaCard(QWidget):
    clicked = pyqtSignal(str)  # Emits file path

    def __init__(self, title, path, type="video"):
        super().__init__()
        self.path = path
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(160)
        self.setFixedHeight(200)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Placeholder Icon/Thumbnail
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("background-color: #2d2d30; border-radius: 8px;")
        self.icon_label.setFixedHeight(140)
        self.icon_label.setText("🎬" if type == "video" else "🎵")
        self.icon_label.setFont(QFont("Segoe UI Emoji", 48))
        layout.addWidget(self.icon_label)
        
        # Title
        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(self.title_label)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.path)

class NativeDashboard(QWidget):
    def __init__(self, api_url, parent=None):
        super().__init__(parent)
        self.api_url = api_url
        self.layout = QVBoxLayout(self)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("Library")
        title.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        header.addWidget(title)
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_library)
        header.addWidget(refresh_btn)
        
        header.addStretch()
        self.layout.addLayout(header)
        
        # Scroll Area for Grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(20)
        scroll.setWidget(self.grid_container)
        self.layout.addWidget(scroll)
        
        self.load_library()
        
    def load_library(self):
        # Clear existing
        for i in range(self.grid_layout.count()):
            item = self.grid_layout.itemAt(i)
            if item.widget():
                item.widget().deleteLater()
                
        # Fetch from API
        try:
            # We'll fetch from the /api/media/list endpoint (assuming it exists or similar)
            # For now, we might need to list directories or use a search endpoint
            # Fallback to listing root data directory
            resp = requests.get(f"{self.api_url}/api/media/list?path=")
            if resp.status_code == 200:
                files = resp.json().get("files", [])
                row = 0
                col = 0
                max_cols = 5
                
                for f in files:
                    if f['type'] == 'directory': continue
                    
                    card = MediaCard(f['name'], f['path'], "video")
                    card.clicked.connect(self.parent().parent().play_media)
                    self.grid_layout.addWidget(card, row, col)
                    
                    col += 1
                    if col >= max_cols:
                        col = 0
                        row += 1
            else:
                # If endpoint fails, show dummy data for testing UI structure
                pass
        except Exception as e:
            print(f"Failed to load library: {e}")

class NomadApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nomad Pi Player")
        self.resize(1024, 768)
        self.setStyleSheet(DARK_THEME)
        
        self.central_widget = QStackedWidget()
        self.setCentralWidget(self.central_widget)
        
        self.init_discovery_page()
        # No init_browser_page anymore - purely native pages
        
        self.servers = {}
        self.current_api_url = None
        self.discovery_thread = DiscoveryThread()
        self.discovery_thread.found_server.connect(self.add_server)
        self.discovery_thread.start()

    def init_discovery_page(self):
        # ... (keep existing discovery page code) ...
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("Nomad Pi Discovery")
        title.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        subtitle = QLabel("Scanning network for Nomad Pi devices...")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        
        self.server_list = QListWidget()
        self.server_list.setFixedWidth(400)
        self.server_list.setFixedHeight(300)
        self.server_list.itemDoubleClicked.connect(self.connect_to_server)
        layout.addWidget(self.server_list, 0, Qt.AlignmentFlag.AlignCenter)
        
        manual_btn = QPushButton("Connect Manually")
        manual_btn.setFixedWidth(200)
        manual_btn.clicked.connect(self.manual_connect)
        layout.addWidget(manual_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        self.central_widget.addWidget(page)

    def init_dashboard_page(self, url):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Native Toolbar
        toolbar = QWidget()
        toolbar.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3e3e42;")
        tb_layout = QHBoxLayout(toolbar)
        
        home_btn = QPushButton("Disconnect")
        home_btn.clicked.connect(lambda: self.central_widget.setCurrentIndex(0))
        tb_layout.addWidget(home_btn)
        
        self.status_label = QLabel(f"Connected to {url}")
        tb_layout.addWidget(self.status_label)
        
        tb_layout.addStretch()
        layout.addWidget(toolbar)
        
        # Native Content Area
        self.dashboard = NativeDashboard(url, self)
        layout.addWidget(self.dashboard)
        
        self.central_widget.addWidget(page)
        self.central_widget.setCurrentWidget(page)

    # ... (rest of methods) ...

    def connect_to_server(self, item):
        url = item.data(Qt.ItemDataRole.UserRole)
        self.load_url(url)

    def load_url(self, url):
        self.current_api_url = url
        self.init_dashboard_page(url)

    def play_media(self, path):
        # Convert path to stream URL
        # Assuming path starts with /data/
        # API needs stream endpoint
        stream_url = f"{self.current_api_url}/api/stream?path={path}"
        from player import VideoPlayer
        self.player_window = VideoPlayer()
        self.player_window.load_media(stream_url)
        self.player_window.show()

class DiscoveryThread(QThread):
    found_server = pyqtSignal(str, str, str)

    def run(self):
        zc = zeroconf.Zeroconf()
        # Browse multiple common service types
        services = ["_http._tcp.local.", "_workstation._tcp.local.", "_nomad._tcp.local."]
        browsers = []
        for service in services:
            browsers.append(zeroconf.ServiceBrowser(zc, service, handlers=[self.on_service_state_change]))
            
        # Keep browsing
        while not self.isInterruptionRequested():
            self.msleep(500)
        zc.close()

    def on_service_state_change(self, zeroconf_obj, service_type, name, state_change):
        if state_change is zeroconf.ServiceStateChange.Added:
            try:
                # Resolve with a longer timeout to ensure we get the address
                info = zeroconf_obj.get_service_info(service_type, name, timeout=3000)
                if info and info.addresses:
                    # Handle multiple addresses (IPv4 preference)
                    address = None
                    for addr in info.addresses:
                        try:
                            ip = socket.inet_ntoa(addr)
                            if not ip.startswith("169.254"): # Skip link-local
                                address = ip
                                break
                        except: pass
                    
                    if not address:
                        address = socket.inet_ntoa(info.addresses[0])

                    port = info.port
                    server_name = name.split('.')[0]
                    
                    # Try to validate if it's really a Nomad Pi instance
                    is_likely_target = any(k in server_name.lower() for k in ["nomad", "pi", "raspberry", "media"])
                    if is_likely_target or "_nomad" in service_type:
                        url = f"http://{address}:{port}"
                        self.found_server.emit(server_name, address, url)
            except Exception as e:
                print(f"Error resolving service {name}: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NomadApp()
    window.show()
    sys.exit(app.exec())

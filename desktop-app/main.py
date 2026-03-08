import sys
import os
import socket
import zeroconf
import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QListWidget, 
                             QListWidgetItem, QStackedWidget, QMessageBox,
                             QProgressBar, QFileDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtGui import QIcon, QFont

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
"""

class DiscoveryThread(QThread):
    found_server = pyqtSignal(str, str, str)  # name, ip, url

    def run(self):
        zc = zeroconf.Zeroconf()
        browser = zeroconf.ServiceBrowser(zc, "_http._tcp.local.", handlers=[self.on_service_state_change])
        # Keep browsing
        while not self.isInterruptionRequested():
            self.msleep(500)
        zc.close()

    def on_service_state_change(self, zeroconf_obj, service_type, name, state_change):
        if state_change is zeroconf.ServiceStateChange.Added:
            info = zeroconf_obj.get_service_info(service_type, name)
            if info:
                address = socket.inet_ntoa(info.addresses[0])
                port = info.port
                server_name = name.split('.')[0]
                url = f"http://{address}:{port}"
                # Filter for Nomad Pi instances if possible, or just list all HTTP services
                # For now, we assume any HTTP service might be it, but we can filter by name
                if "nomad" in server_name.lower():
                    self.found_server.emit(server_name, address, url)

class NomadApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nomad Pi Player")
        self.resize(1024, 768)
        self.setStyleSheet(DARK_THEME)
        
        self.central_widget = QStackedWidget()
        self.setCentralWidget(self.central_widget)
        
        self.init_discovery_page()
        self.init_browser_page()
        
        self.servers = {}
        self.discovery_thread = DiscoveryThread()
        self.discovery_thread.found_server.connect(self.add_server)
        self.discovery_thread.start()

    def init_discovery_page(self):
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

    def init_browser_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar
        toolbar = QWidget()
        toolbar.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3e3e42;")
        tb_layout = QHBoxLayout(toolbar)
        
        home_btn = QPushButton("Home")
        home_btn.clicked.connect(lambda: self.central_widget.setCurrentIndex(0))
        tb_layout.addWidget(home_btn)
        
        self.status_label = QLabel("Connected")
        tb_layout.addWidget(self.status_label)
        
        tb_layout.addStretch()
        
        layout.addWidget(toolbar)
        
        # Web View
        self.web_view = QWebEngineView()
        self.web_view.setStyleSheet("background-color: #1e1e1e;")
        layout.addWidget(self.web_view)
        
        self.central_widget.addWidget(page)

    def add_server(self, name, ip, url):
        if url not in self.servers:
            self.servers[url] = name
            item = QListWidgetItem(f"{name} ({ip})")
            item.setData(Qt.ItemDataRole.UserRole, url)
            self.server_list.addItem(item)

    def connect_to_server(self, item):
        url = item.data(Qt.ItemDataRole.UserRole)
        self.load_url(url)

    def manual_connect(self):
        # Placeholder for manual IP entry
        pass

    def load_url(self, url):
        self.status_label.setText(f"Connected to: {url}")
        self.web_view.setUrl(QUrl(url))
        self.central_widget.setCurrentIndex(1)

    def closeEvent(self, event):
        self.discovery_thread.requestInterruption()
        self.discovery_thread.quit()
        self.discovery_thread.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NomadApp()
    window.show()
    sys.exit(app.exec())

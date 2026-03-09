import sys
import socket
import zeroconf
import requests
from urllib.parse import quote
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QMessageBox,
    QInputDialog,
    QGridLayout,
    QScrollArea,
    QLineEdit,
    QComboBox,
    QFileDialog,
    QSplitter,
    QTextEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap

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

    def __init__(self, title, path, api_url, token, media_type="video", poster=None):
        super().__init__()
        self.path = path
        self.api_url = api_url
        self.token = token
        self.poster = poster
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
        self.icon_label.setText("🎬" if media_type == "video" else "🎵")
        self.icon_label.setFont(QFont("Segoe UI Emoji", 48))
        self._try_load_poster()
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

    def _try_load_poster(self):
        if not self.poster:
            return

        try:
            if isinstance(self.poster, str) and self.poster.startswith("/"):
                poster_url = f"{self.api_url}{self.poster}"
            else:
                poster_url = str(self.poster)

            response = requests.get(poster_url, timeout=4)
            if response.status_code == 200 and response.content:
                pix = QPixmap()
                if pix.loadFromData(response.content):
                    self.icon_label.setPixmap(
                        pix.scaled(
                            self.icon_label.width(),
                            self.icon_label.height(),
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    self.icon_label.setText("")
        except Exception:
            pass

class NativeDashboard(QWidget):
    def __init__(self, api_url, token, parent=None):
        super().__init__(parent)
        self.api_url = api_url
        self.token = token
        self.current_category = "movies"
        self.layout = QVBoxLayout(self)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("Library")
        title.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        header.addWidget(title)

        self.category_buttons = {}
        for category in ["movies", "shows", "music", "books", "gallery", "files"]:
            btn = QPushButton(category.title())
            btn.clicked.connect(lambda _, c=category: self.set_category(c))
            self.category_buttons[category] = btn
            header.addWidget(btn)
        
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
        self.empty_label = QLabel("")
        self.layout.addWidget(self.empty_label)
        
        self.set_category("movies")

    def set_category(self, category):
        self.current_category = category
        self.load_library()
        
    def load_library(self):
        while self.grid_layout.count():
            item = self.grid_layout.itemAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = requests.get(
                f"{self.api_url}/api/media/library/{self.current_category}?limit=200",
                headers=headers,
                timeout=8,
            )
            if resp.status_code == 200:
                payload = resp.json() or {}
                items = payload.get("items", [])
                row = 0
                col = 0
                max_cols = 5

                for item in items:
                    path = item.get("path")
                    if not path:
                        continue
                    name = item.get("title") or item.get("name") or "Unknown"
                    media_type = "music" if self.current_category == "music" else "video"
                    card = MediaCard(
                        title=name,
                        path=path,
                        api_url=self.api_url,
                        token=self.token,
                        media_type=media_type,
                        poster=item.get("poster"),
                    )
                    card.clicked.connect(self.parent().play_media)
                    self.grid_layout.addWidget(card, row, col)

                    col += 1
                    if col >= max_cols:
                        col = 0
                        row += 1
                self.empty_label.setText(
                    "" if items else f"No items in {self.current_category.title()} library"
                )
            else:
                QMessageBox.warning(
                    self,
                    "Library Error",
                    f"Failed to load {self.current_category} library\nHTTP {resp.status_code}: {resp.text[:180]}",
                )
                self.empty_label.setText("Failed to load library")
        except Exception as e:
            QMessageBox.warning(self, "Library Error", f"Failed to load library: {e}")
            self.empty_label.setText("Failed to load library")


class UploadPanel(QWidget):
    def __init__(self, api_url, token, parent=None):
        super().__init__(parent)
        self.api_url = api_url
        self.token = token
        self.files = []

        layout = QVBoxLayout(self)
        title = QLabel("Upload Files")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        row = QHBoxLayout()
        self.category = QComboBox()
        self.category.addItems(["movies", "shows", "music", "books", "gallery", "files"])
        row.addWidget(self.category)

        choose_btn = QPushButton("Choose Files")
        choose_btn.clicked.connect(self.choose_files)
        row.addWidget(choose_btn)

        upload_btn = QPushButton("Upload")
        upload_btn.clicked.connect(self.upload_files)
        row.addWidget(upload_btn)

        layout.addLayout(row)
        self.file_list = QListWidget()
        layout.addWidget(self.file_list)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(120)
        layout.addWidget(self.log)

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files to Upload")
        if not files:
            return
        self.files = files
        self.file_list.clear()
        for f in files:
            self.file_list.addItem(f)

    def upload_files(self):
        if not self.files:
            self.log.append("No files selected.")
            return

        category = self.category.currentText()
        headers = {"Authorization": f"Bearer {self.token}"}
        self.log.append(f"Uploading {len(self.files)} file(s) to {category}...")
        for file_path in self.files:
            try:
                with open(file_path, "rb") as fh:
                    files = {"files": (file_path.split("\\")[-1], fh)}
                    resp = requests.post(
                        f"{self.api_url}/api/media/upload/{category}",
                        headers=headers,
                        files=files,
                        timeout=120,
                    )
                if resp.status_code == 200:
                    self.log.append(f"✓ {file_path}")
                else:
                    self.log.append(f"✗ {file_path} -> HTTP {resp.status_code}: {resp.text[:120]}")
            except Exception as e:
                self.log.append(f"✗ {file_path} -> {e}")


class SettingsPanel(QWidget):
    def __init__(self, api_url, token, parent=None):
        super().__init__(parent)
        self.api_url = api_url
        self.token = token

        layout = QVBoxLayout(self)
        title = QLabel("Settings")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        omdb_row = QHBoxLayout()
        omdb_row.addWidget(QLabel("OMDb API Key:"))
        self.omdb_input = QLineEdit()
        self.omdb_input.setPlaceholderText("Enter OMDb key")
        omdb_row.addWidget(self.omdb_input)
        save_btn = QPushButton("Save OMDb")
        save_btn.clicked.connect(self.save_omdb)
        omdb_row.addWidget(save_btn)
        layout.addLayout(omdb_row)

        actions = QHBoxLayout()
        update_btn = QPushButton("Run Update")
        update_btn.clicked.connect(lambda: self.control("update"))
        actions.addWidget(update_btn)
        restart_btn = QPushButton("Restart App")
        restart_btn.clicked.connect(lambda: self.control("restart"))
        actions.addWidget(restart_btn)
        actions.addStretch()
        layout.addLayout(actions)

        self.status = QTextEdit()
        self.status.setReadOnly(True)
        self.status.setMinimumHeight(140)
        layout.addWidget(self.status)

        self.load_omdb()

    def load_omdb(self):
        try:
            resp = requests.get(f"{self.api_url}/api/system/settings/omdb", timeout=6)
            if resp.status_code == 200:
                self.omdb_input.setText((resp.json() or {}).get("key", ""))
        except Exception:
            pass

    def save_omdb(self):
        try:
            resp = requests.post(
                f"{self.api_url}/api/system/settings/omdb",
                json={"key": self.omdb_input.text().strip()},
                timeout=8,
            )
            if resp.status_code == 200:
                self.status.append("OMDb key saved.")
            else:
                self.status.append(f"Failed to save OMDb key: {resp.status_code}")
        except Exception as e:
            self.status.append(f"Failed to save OMDb key: {e}")

    def control(self, action):
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            resp = requests.post(
                f"{self.api_url}/api/system/control/{action}",
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 200:
                self.status.append(f"{action.title()} requested successfully.")
            else:
                self.status.append(f"{action.title()} failed: {resp.status_code} {resp.text[:120]}")
        except Exception as e:
            self.status.append(f"{action.title()} failed: {e}")

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
        
        self.servers = set()
        self.current_api_url = None
        self.current_token = None
        self.dashboard_page = None
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

    def init_dashboard_page(self, url):
        if self.dashboard_page is not None:
            self.central_widget.removeWidget(self.dashboard_page)
            self.dashboard_page.deleteLater()

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Native Toolbar
        toolbar = QWidget()
        toolbar.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3e3e42;")
        tb_layout = QHBoxLayout(toolbar)
        
        home_btn = QPushButton("Disconnect")
        home_btn.clicked.connect(self.disconnect)
        tb_layout.addWidget(home_btn)
        
        self.status_label = QLabel(f"Connected to {url}")
        tb_layout.addWidget(self.status_label)
        
        tb_layout.addStretch()
        layout.addWidget(toolbar)
        
        nav_row = QHBoxLayout()
        library_btn = QPushButton("Library")
        upload_btn = QPushButton("Upload")
        settings_btn = QPushButton("Settings")
        nav_row.addWidget(library_btn)
        nav_row.addWidget(upload_btn)
        nav_row.addWidget(settings_btn)
        nav_row.addStretch()
        layout.addLayout(nav_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.page_stack = QStackedWidget()
        self.dashboard = NativeDashboard(url, self.current_token, self)
        self.upload_panel = UploadPanel(url, self.current_token, self)
        self.settings_panel = SettingsPanel(url, self.current_token, self)
        self.page_stack.addWidget(self.dashboard)
        self.page_stack.addWidget(self.upload_panel)
        self.page_stack.addWidget(self.settings_panel)
        splitter.addWidget(self.page_stack)

        from player import VideoPlayer
        self.embedded_player = VideoPlayer(self, embedded=True)
        splitter.addWidget(self.embedded_player)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

        library_btn.clicked.connect(lambda: self.page_stack.setCurrentWidget(self.dashboard))
        upload_btn.clicked.connect(lambda: self.page_stack.setCurrentWidget(self.upload_panel))
        settings_btn.clicked.connect(lambda: self.page_stack.setCurrentWidget(self.settings_panel))

        self.dashboard_page = page
        self.central_widget.addWidget(page)
        self.central_widget.setCurrentWidget(page)

    def disconnect(self):
        self.current_api_url = None
        self.current_token = None
        self.central_widget.setCurrentIndex(0)

    def add_server(self, name, ip, url):
        if url in self.servers:
            return
        self.servers.add(url)
        item = QListWidgetItem(f"{name} ({ip})")
        item.setData(Qt.ItemDataRole.UserRole, url)
        self.server_list.addItem(item)

    def connect_to_server(self, item):
        url = item.data(Qt.ItemDataRole.UserRole)
        self.load_url(url)

    def manual_connect(self):
        value, ok = QInputDialog.getText(
            self,
            "Connect Manually",
            "Enter Nomad Pi host, IP, or URL:",
            text="nomadpi.local:8000",
        )
        if not ok or not value.strip():
            return

        value = value.strip()
        if not value.startswith("http://") and not value.startswith("https://"):
            value = f"http://{value}"
        self.load_url(value)

    def prompt_login(self):
        username, ok = QInputDialog.getText(
            self, "Nomad Login", "Username:", text="admin"
        )
        if not ok or not username.strip():
            return None
        password, ok = QInputDialog.getText(
            self,
            "Nomad Login",
            "Password:",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return None
        return username.strip(), password

    def authenticate(self, url):
        creds = self.prompt_login()
        if not creds:
            return None
        username, password = creds
        try:
            resp = requests.post(
                f"{url}/api/auth/login",
                json={"username": username, "password": password},
                timeout=8,
            )
            if resp.status_code != 200:
                QMessageBox.warning(
                    self,
                    "Login Failed",
                    f"Could not log in to {url}\nHTTP {resp.status_code}: {resp.text[:180]}",
                )
                return None
            payload = resp.json() or {}
            token = payload.get("token")
            if not token:
                QMessageBox.warning(self, "Login Failed", "No token returned by server.")
                return None
            return token
        except Exception as e:
            QMessageBox.warning(self, "Connection Failed", f"Unable to connect to {url}\n{e}")
            return None

    def load_url(self, url):
        token = self.authenticate(url)
        if not token:
            return
        self.current_api_url = url.rstrip("/")
        self.current_token = token
        self.init_dashboard_page(self.current_api_url)

    def play_media(self, path):
        encoded_path = quote(path, safe="/")
        stream_url = f"{self.current_api_url}/api/media/stream?path={encoded_path}&token={self.current_token}"
        self.embedded_player.load_media(stream_url)

    def closeEvent(self, event):
        if self.discovery_thread.isRunning():
            self.discovery_thread.requestInterruption()
            self.discovery_thread.quit()
            self.discovery_thread.wait(2000)
        event.accept()

class DiscoveryThread(QThread):
    found_server = pyqtSignal(str, str, str)

    def run(self):
        zc = zeroconf.Zeroconf()
        services = ["_http._tcp.local.", "_workstation._tcp.local.", "_nomad._tcp.local."]
        browsers = []
        for service in services:
            browsers.append(
                zeroconf.ServiceBrowser(zc, service, handlers=[self.on_service_state_change])
            )

        self.try_common_hosts()
        tick = 0

        while not self.isInterruptionRequested():
            tick += 1
            if tick % 20 == 0:
                self.try_common_hosts()
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

    def try_common_hosts(self):
        for host in ["nomadpi.local", "raspberrypi.local", "radxa.local"]:
            try:
                ip = socket.gethostbyname(host)
                url = f"http://{ip}:8000"
                r = requests.get(f"{url}/api/system/status", timeout=2)
                if r.status_code == 200:
                    self.found_server.emit(host, ip, url)
            except Exception:
                continue

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NomadApp()
    window.show()
    sys.exit(app.exec())

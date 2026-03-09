from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider, QStyle
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, QUrl

class VideoPlayer(QWidget):
    def __init__(self, parent=None, embedded=False):
        super().__init__(parent)
        self.embedded = embedded
        if not embedded:
            self.setWindowTitle("Nomad Player")
            self.resize(900, 620)
        
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(0.85)
        self.media_player.setAudioOutput(self.audio_output)
        
        self.video_widget = QVideoWidget()
        self.media_player.setVideoOutput(self.video_widget)
        
        # Controls
        self.play_btn = QPushButton()
        self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.play_video)
        
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.set_position)
        
        self.label = QLabel("00:00 / 00:00")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(85)
        self.volume.setFixedWidth(120)
        self.volume.valueChanged.connect(self.on_volume_changed)
        
        # Layout
        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.addWidget(self.play_btn)
        control_layout.addWidget(self.slider)
        control_layout.addWidget(self.label)
        control_layout.addWidget(self.volume)
        
        layout = QVBoxLayout()
        layout.addWidget(self.video_widget)
        layout.addLayout(control_layout)
        
        self.setLayout(layout)
        self.setStyleSheet(
            "QWidget { background: #121212; color: #e0e0e0; }"
            "QLabel { color: #d0d0d0; min-width: 110px; }"
            "QSlider::groove:horizontal { height: 6px; background: #2f2f2f; border-radius: 3px; }"
            "QSlider::handle:horizontal { background: #00a8ff; width: 14px; margin: -4px 0; border-radius: 7px; }"
            "QPushButton { background: #1f1f1f; border: 1px solid #3a3a3a; padding: 6px; border-radius: 6px; }"
        )
        
        self.media_player.positionChanged.connect(self.position_changed)
        self.media_player.durationChanged.connect(self.duration_changed)
        self.media_player.playbackStateChanged.connect(self.on_playback_state_changed)
        
    def load_media(self, url):
        self.media_player.stop()
        self.media_player.setSource(QUrl.fromEncoded(url.encode("utf-8")))
        self.play_btn.setEnabled(True)
        self.media_player.play()
        
    def play_video(self):
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        else:
            self.media_player.play()
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            
    def position_changed(self, position):
        self.slider.setValue(position)
        duration = self.media_player.duration()
        self.label.setText(f"{self.format_time(position)} / {self.format_time(duration)}")
        
    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.label.setText(f"{self.format_time(self.media_player.position())} / {self.format_time(duration)}")
        
    def set_position(self, position):
        self.media_player.setPosition(position)

    def on_volume_changed(self, value):
        self.audio_output.setVolume(max(0.0, min(1.0, value / 100.0)))

    def on_playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        else:
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        
    def format_time(self, ms):
        seconds = (ms // 1000) % 60
        minutes = (ms // 60000) % 60
        hours = (ms // 3600000)
        
        if hours > 0:
            return f"{hours:02}:{minutes:02}:{seconds:02}"
        return f"{minutes:02}:{seconds:02}"

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    player = VideoPlayer()
    player.resize(640, 480)
    player.show()
    # Example usage: player.load_media("http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4")
    sys.exit(app.exec())

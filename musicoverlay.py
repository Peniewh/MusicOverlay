# musicoverlay.py
import sys, os, json, ctypes, random

# Безопасная инициализация faulthandler — не падает в windowed-сборке
import faulthandler
try:
    if sys.stderr is not None:
        faulthandler.enable()
    else:
        _log_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "crash.log")
        faulthandler.enable(open(_log_path, "w", encoding="utf-8"))
except Exception:
    pass

sys.coinit_flags = 2
try:
    ctypes.windll.ole32.CoInitializeEx(None, 0x2)
except Exception:
    pass

from pathlib import Path
from dataclasses import dataclass

# ---------------------------------------------------------------- VLC path
def _resolve_vlc():
    here = Path(__file__).resolve().parent
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    for c in (here / "vlc", (exe_dir / "vlc") if exe_dir else None):
        if c and c.exists() and (c / "libvlc.dll").exists():
            return c
    for p in (r"C:\Program Files\VideoLAN\VLC", r"C:\Program Files (x86)\VideoLAN\VLC"):
        if os.path.isdir(p):
            return Path(p)
    return None

VLC_DIR = _resolve_vlc()
if VLC_DIR:
    try:
        os.add_dll_directory(str(VLC_DIR))
        os.environ["PATH"] = str(VLC_DIR) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass

import vlc
import keyboard
import yt_dlp
from mutagen import File as MutagenFile

try:
    from vkpymusic import Service as VkService, TokenReceiver as VkTokenReceiver
    HAS_VKPYMUSIC = True
except Exception as _e:
    HAS_VKPYMUSIC = False

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QHBoxLayout, QVBoxLayout, QPushButton,
    QSlider, QMenu, QFileDialog, QInputDialog, QSizePolicy, QSystemTrayIcon,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QListWidget,
    QListWidgetItem, QCheckBox, QProgressDialog, QMessageBox, QFrame, QComboBox
)
from PySide6.QtCore import (
    Qt, QTimer, QPoint, QRect, QObject, Signal, QSize,
    QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
)
from PySide6.QtGui import (
    QPixmap, QColor, QPainter, QAction, QIcon, QPainterPath, QFontMetrics, QPen
)

# ---------------------------------------------------------------- paths
def _resolve_paths():
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        bundle_dir = Path(getattr(sys, "_MEIPASS", exe_dir))
        assets_ext = exe_dir / "assets"
        assets_bundle = bundle_dir / "assets"
        assets = assets_ext if assets_ext.exists() else assets_bundle
        return exe_dir, assets
    base = Path(__file__).resolve().parent
    return base, base / "assets"

BASE_DIR, ASSETS_DIR = _resolve_paths()
CONFIG_PATH = BASE_DIR / "config.json"
CACHE_DIR = BASE_DIR / "cache"
DOWNLOADS_DIR = BASE_DIR / "downloads"

for d in (CACHE_DIR, ASSETS_DIR, DOWNLOADS_DIR):
    try:
        d.mkdir(exist_ok=True)
    except Exception:
        pass

# ---------------------------------------------------------------- click-through
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
user32 = ctypes.windll.user32

def set_click_through(hwnd: int, enabled: bool):
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enabled:
        ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    else:
        ex &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
        ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)

# ---------------------------------------------------------------- autostart
import winreg

def get_autostart_path() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    return f'"{pythonw}" "{Path(__file__).resolve()}"'

def is_autostart_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, "MusicOverlay")
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False

def set_autostart(enabled: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        try:
            if enabled:
                winreg.SetValueEx(key, "MusicOverlay", 0, winreg.REG_SZ, get_autostart_path())
            else:
                try:
                    winreg.DeleteValue(key, "MusicOverlay")
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception as e:
        try:
            print("autostart err:", e)
        except Exception:
            pass
        return False

# ---------------------------------------------------------------- config
DEFAULT_CONFIG = {
    "toggle_overlay": "ctrl+shift+m",
    "toggle_click_through": "ctrl+shift+c",
    "prev_track": "ctrl+shift+left",
    "next_track": "ctrl+shift+right",
    "next_track_in_order": "ctrl+alt+right",
    "play_pause": "ctrl+shift+space",
    "volume_up": "ctrl+shift+up",
    "volume_down": "ctrl+shift+down",
    "quit_app": "ctrl+shift+q",
    "volume": 70,
    "opacity": 0.96,
    "tracks": [],
    "window_x": 60,
    "window_y": 60,
    "repeat_mode": "off",
    "shuffle": False,
    "show_notification": True,
    "media_keys_enabled": True,
    "browser_for_cookies": "auto",
    "vk_token": "",
    "vk_user_agent": "",
}

def load_config():
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        try:
            print("save_config err:", e)
        except Exception:
            pass

# ---------------------------------------------------------------- metadata
@dataclass
class Track:
    path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    cover_path: str = ""

def extract_cover(path: str) -> str:
    try:
        audio = MutagenFile(path)
        if audio is None or not getattr(audio, "tags", None):
            return ""
        data = None
        tags = audio.tags
        if hasattr(tags, "getall"):
            frames = tags.getall("APIC")
            if frames:
                data = frames[0].data
        if data is None and hasattr(audio, "pictures") and audio.pictures:
            data = audio.pictures[0].data
        if data is None and "covr" in tags:
            data = bytes(tags["covr"][0])
        if data:
            out = CACHE_DIR / (Path(path).stem + ".jpg")
            out.write_bytes(data)
            return str(out)
    except Exception as e:
        try:
            print("cover err:", e)
        except Exception:
            pass
    return ""

def read_track(path: str) -> Track:
    t = Track(path=path, title=Path(path).stem)
    try:
        audio = MutagenFile(path, easy=True)
        if audio and audio.tags:
            t.title = (audio.tags.get("title") or [t.title])[0]
            t.artist = (audio.tags.get("artist") or [""])[0]
            t.album = (audio.tags.get("album") or [""])[0]
    except Exception:
        pass
    t.cover_path = extract_cover(path)
    return t

# ---------------------------------------------------------------- player
class MusicPlayer(QObject):
    track_changed = Signal(object)
    state_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.instance = vlc.Instance("--no-video", "--quiet")
        self.player = self.instance.media_player_new()
        self.playlist: list[Track] = []
        self.index = -1
        self.repeat_mode = "off"
        self.shuffle = False

    def set_playlist(self, paths):
        self.playlist = [read_track(p) for p in paths if Path(p).exists()]

    def play_index(self, i):
        if not self.playlist:
            return
        self.index = i % len(self.playlist)
        t = self.playlist[self.index]
        media = self.instance.media_new(t.path)
        self.player.set_media(media)
        self.player.play()
        self.track_changed.emit(t)

    def play_pause(self):
        if not self.playlist:
            return
        if self.index == -1:
            self.play_index(0)
            return
        if self.player.is_playing():
            self.player.pause()
        else:
            self.player.play()
        self.state_changed.emit(self.player.is_playing())

    def advance(self, auto: bool = False):
        if not self.playlist:
            return
        if auto and self.repeat_mode == "one":
            self.play_index(self.index)
            return
        if self.shuffle and len(self.playlist) > 1:
            idx = self.index
            while idx == self.index:
                idx = random.randrange(len(self.playlist))
            self.play_index(idx)
            return
        nxt = self.index + 1
        if nxt >= len(self.playlist):
            if auto and self.repeat_mode == "off":
                self.player.stop()
                self.state_changed.emit(False)
                return
            nxt = 0
        self.play_index(nxt)

    def next(self):
        self.advance(auto=False)

    def next_in_order(self):
        if not self.playlist:
            return
        if self.repeat_mode == "one":
            self.play_index(self.index)
            return
        nxt = self.index + 1
        if nxt >= len(self.playlist):
            nxt = 0
        self.play_index(nxt)

    def prev(self):
        if not self.playlist:
            return
        if self.shuffle and len(self.playlist) > 1:
            idx = self.index
            while idx == self.index:
                idx = random.randrange(len(self.playlist))
            self.play_index(idx)
            return
        self.play_index(self.index - 1)

    def set_volume(self, v):
        self.player.audio_set_volume(int(v))

    def time(self):
        return self.player.get_time()

    def length(self):
        return self.player.get_length()

    def seek(self, ms):
        self.player.set_time(int(ms))

    def is_playing(self):
        return bool(self.player.is_playing())

    def tick(self):
        if self.playlist and self.player.get_state() == vlc.State.Ended:
            self.advance(auto=True)

# ---------------------------------------------------------------- notification
class TrackNotification(QWidget):
    def __init__(self):
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(340, 96)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self.cover = QLabel()
        self.cover.setFixedSize(72, 72)
        self.cover.setStyleSheet("background: rgba(255,255,255,0.10); border-radius: 8px;")
        self.cover.setScaledContents(False)
        layout.addWidget(self.cover)

        right = QVBoxLayout()
        right.setSpacing(2)
        right.setAlignment(Qt.AlignVCenter)
        layout.addLayout(right, 1)

        self.title_lbl = QLabel("")
        self.title_lbl.setStyleSheet(
            "color:#fff; font-size:13px; font-weight:700; background:transparent;"
        )
        right.addWidget(self.title_lbl)

        self.artist_lbl = QLabel("")
        self.artist_lbl.setStyleSheet(
            "color:rgba(255,255,255,0.7); font-size:11px; background:transparent;"
        )
        right.addWidget(self.artist_lbl)

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.animate_hide)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().toRectF(), 12, 12)
        p.fillPath(path, QColor(18, 18, 22, 240))
        p.setPen(QColor(255, 255, 255, 32))
        p.drawPath(path)

    def show_track(self, track: Track, duration_ms: int = 3200):
        title = track.title or Path(track.path).stem
        artist = track.artist or ""

        fm = QFontMetrics(self.title_lbl.font())
        self.title_lbl.setText(fm.elidedText(title, Qt.ElideRight, 240))
        self.artist_lbl.setText(artist[:40])

        if track.cover_path and Path(track.cover_path).exists():
            px = QPixmap(track.cover_path).scaled(
                72, 72, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            self.cover.setPixmap(px)
        else:
            self.cover.clear()

        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() - 20
        y = screen.bottom() - self.height() - 20
        self.move(x, y)

        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(260)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_in = anim
        anim.start()

        self.hide_timer.start(duration_ms)

    def animate_hide(self):
        if not self.isVisible():
            return
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(260)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self.hide)
        self._anim_out = anim
        anim.start()

# ---------------------------------------------------------------- playlist popup
class PlaylistPopup(QWidget):
    track_activated = Signal(int)
    track_removed = Signal(int)
    clear_requested = Signal()

    def __init__(self):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(340, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        t = QLabel("Плейлист")
        t.setStyleSheet("color:#fff; font-weight:700; font-size:13px; background:transparent;")
        head.addWidget(t)
        head.addStretch(1)
        clear_btn = QPushButton("Очистить")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet(
            "QPushButton { color:#fff; background:#333; border:none; "
            "padding:3px 8px; border-radius:6px; font-size:11px; }"
            "QPushButton:hover { background:#444; }"
        )
        clear_btn.clicked.connect(self.clear_requested.emit)
        head.addWidget(clear_btn)
        layout.addLayout(head)

        self.list = QListWidget()
        self.list.setStyleSheet("""
            QListWidget { background: rgba(255,255,255,0.05); color:#fff;
                         border:none; border-radius:8px; padding:4px;
                         font-size:12px; }
            QListWidget::item { padding:6px 8px; border-radius:6px; }
            QListWidget::item:selected { background: #4a9eff; color:#fff; }
            QListWidget::item:hover { background: rgba(255,255,255,0.08); }
        """)
        self.list.itemDoubleClicked.connect(self._activate)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self.list, 1)

    def refresh(self, playlist, current_index):
        self.list.clear()
        for i, t in enumerate(playlist):
            title = t.title or Path(t.path).stem
            artist = t.artist or ""
            text = title + (f"  —  {artist}" if artist else "")
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, i)
            it.setToolTip(t.path)
            self.list.addItem(it)
        if 0 <= current_index < self.list.count():
            self.list.setCurrentRow(current_index)

    def _activate(self, item):
        idx = item.data(Qt.UserRole)
        self.track_activated.emit(idx)

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return
        idx = item.data(Qt.UserRole)
        m = QMenu(self)
        a_play = QAction("Воспроизвести", self)
        a_play.triggered.connect(lambda: self.track_activated.emit(idx))
        a_del = QAction("Удалить", self)
        a_del.triggered.connect(lambda: self.track_removed.emit(idx))
        m.addAction(a_play)
        m.addSeparator()
        m.addAction(a_del)
        m.exec(self.list.mapToGlobal(pos))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().toRectF(), 14, 14)
        p.fillPath(path, QColor(20, 20, 24, 250))
        p.setPen(QColor(255, 255, 255, 40))
        p.drawPath(path)

# ---------------------------------------------------------------- HotkeyEdit
class HotkeyEdit(QLineEdit):
    def __init__(self, value: str = "", parent=None):
        super().__init__(value, parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Нажми комбинацию…")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Кликни в поле и нажми нужную комбинацию клавиш.\n"
                        "Backspace — очистить.")

    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key_Backspace:
            self.setText("")
            return
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta,
                   Qt.Key_AltGr, Qt.Key_unknown):
            return
        mods = e.modifiers()
        parts = []
        if mods & Qt.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.ShiftModifier:
            parts.append("shift")
        if mods & Qt.AltModifier:
            parts.append("alt")
        if mods & Qt.MetaModifier:
            parts.append("windows")
        name = self._key_name(key, e.text())
        if name:
            parts.append(name)
            self.setText("+".join(parts))

    @staticmethod
    def _key_name(key: int, text: str) -> str:
        special = {
            Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
            Qt.Key_Tab: "tab", Qt.Key_Escape: "escape", Qt.Key_Delete: "delete",
            Qt.Key_Insert: "insert", Qt.Key_Home: "home", Qt.Key_End: "end",
            Qt.Key_PageUp: "page up", Qt.Key_PageDown: "page down",
            Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Up: "up", Qt.Key_Down: "down",
            Qt.Key_Comma: ",", Qt.Key_Period: ".", Qt.Key_Slash: "/",
            Qt.Key_Semicolon: ";", Qt.Key_Apostrophe: "'",
            Qt.Key_BracketLeft: "[", Qt.Key_BracketRight: "]",
            Qt.Key_Backslash: "\\", Qt.Key_Minus: "-", Qt.Key_Equal: "=",
            Qt.Key_QuoteLeft: "`",
        }
        if key in special:
            return special[key]
        if Qt.Key_F1 <= key <= Qt.Key_F35:
            return f"f{key - Qt.Key_F1 + 1}"
        if text and text.isprintable() and text.strip():
            return text.lower()
        return None

# ---------------------------------------------------------------- VK Login Dialog
class VkLoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Подключение VK")
        self.setMinimumWidth(420)
        self.setStyleSheet(
            "QDialog { background: #1c1c22; }"
            "QLabel { color: #eaeaea; font-size: 12px; }"
            "QLineEdit { background: #2a2a30; color: #fff; "
            "border: 1px solid #444; padding: 6px; border-radius: 4px; }"
            "QPushButton { background: #2a2a30; color: #fff; "
            "border: 1px solid #444; padding: 6px 12px; border-radius: 6px; }"
            "QPushButton:hover { background: #3a3a44; }"
            "QPushButton#primary { background: #4a9eff; border: none; font-weight: 700; }"
            "QPushButton#primary:hover { background: #5aaeff; }"
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        info = QLabel(
            "Введите логин и пароль от VK — библиотека получит токен и сохранит его.\n"
            "Пароль никуда не отправляется, используется только для авторизации через официальный API VK."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaa; font-size: 11px; background: transparent;")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(8)

        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText("+79991234567 или email")
        form.addRow("Логин:", self.login_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setPlaceholderText("Пароль")
        form.addRow("Пароль:", self.pass_edit)

        self.twofa_edit = QLineEdit()
        self.twofa_edit.setPlaceholderText("Оставьте пустым, если нет 2FA")
        form.addRow("2FA код (опц.):", self.twofa_edit)

        layout.addLayout(form)

        note = QLabel(
            "⚠️ Аккаунт может быть временно ограничен при слишком частых запросах.\n"
            "Используйте умеренно: не качайте сотни треков подряд."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #ffaa55; font-size: 11px; background: transparent;")
        layout.addWidget(note)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        ok_btn = QPushButton("Получить токен")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self.accept)
        btns.addWidget(ok_btn)
        layout.addLayout(btns)

    def get_credentials(self):
        return self.login_edit.text().strip(), self.pass_edit.text(), self.twofa_edit.text().strip()

# ---------------------------------------------------------------- settings
class SettingsDialog(QDialog):
    HOTKEYS = [
        ("toggle_overlay", "Показать/скрыть"),
        ("toggle_click_through", "Click-through"),
        ("prev_track", "Предыдущий трек"),
        ("next_track", "Следующий (с shuffle)"),
        ("next_track_in_order", "Следующий (по порядку)"),
        ("play_pause", "Плей/пауза"),
        ("volume_up", "Громкость +"),
        ("volume_down", "Громкость −"),
        ("quit_app", "Выход"),
    ]

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Настройки оверлея")
        self.setMinimumWidth(460)
        self.setStyleSheet(
            "QDialog { background: #1c1c22; }"
            "QLabel { color: #eaeaea; font-size: 12px; }"
            "QLineEdit { background: #2a2a30; color: #fff; "
            "border: 1px solid #444; padding: 4px 6px; border-radius: 4px; }"
            "QLineEdit:focus { border: 1px solid #4a9eff; }"
            "QCheckBox { color: #eaeaea; font-size: 12px; }"
            "QComboBox { background: #2a2a30; color: #fff; border: 1px solid #444; "
            "padding: 4px 6px; border-radius: 4px; }"
            "QPushButton { background: #2a2a30; color: #fff; border: 1px solid #444; "
            "padding: 5px 12px; border-radius: 6px; }"
            "QPushButton:hover { background: #3a3a44; }"
            "QPushButton#vk-btn { background: #4a9eff; border: none; font-weight: 700; }"
            "QPushButton#vk-btn:hover { background: #5aaeff; }"
            "QDialogButtonBox QPushButton { background: #2a2a30; color: #fff; "
            "border: 1px solid #444; padding: 5px 12px; border-radius: 6px; }"
            "QDialogButtonBox QPushButton:hover { background: #3a3a44; }"
        )
        form = QFormLayout(self)
        form.setSpacing(8)

        self.fields = {}
        for key, label in self.HOTKEYS:
            le = HotkeyEdit(cfg.get(key, ""))
            self.fields[key] = le
            form.addRow(label, le)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(int(cfg.get("opacity", 0.96) * 100))
        form.addRow("Прозрачность %", self.opacity_slider)

        self.notif_cb = QCheckBox("Всплывашка при смене трека")
        self.notif_cb.setChecked(bool(cfg.get("show_notification", True)))
        form.addRow("", self.notif_cb)

        self.media_cb = QCheckBox("Медиа-клавиши (⏯ ⏭ ⏮)")
        self.media_cb.setChecked(bool(cfg.get("media_keys_enabled", True)))
        form.addRow("", self.media_cb)

        self.autostart_cb = QCheckBox("Запускать вместе с Windows")
        self.autostart_cb.setChecked(is_autostart_enabled())
        form.addRow("", self.autostart_cb)

        # VK
        vk_label = QLabel("— VK Music (опционально) —")
        vk_label.setStyleSheet("color: #888; font-size: 11px; background: transparent; margin-top: 10px;")
        form.addRow(vk_label)

        vk_status_text = "Подключено" if cfg.get("vk_token") else "Не подключено"
        vk_status = QLabel(vk_status_text)
        vk_status.setStyleSheet(
            "color: #4aff88; font-size: 11px; background: transparent;"
            if cfg.get("vk_token") else
            "color: #ff8888; font-size: 11px; background: transparent;"
        )
        form.addRow("VK статус:", vk_status)

        self.vk_token_edit = QLineEdit(cfg.get("vk_token", ""))
        self.vk_token_edit.setPlaceholderText("Вставь токен или нажми «Получить токен»")
        self.vk_token_edit.setEchoMode(QLineEdit.Password)
        form.addRow("VK токен:", self.vk_token_edit)

        get_token_btn = QPushButton("Получить токен через логин/пароль")
        get_token_btn.setObjectName("vk-btn")
        get_token_btn.clicked.connect(self._on_get_vk_token)
        form.addRow("", get_token_btn)

        clear_vk_btn = QPushButton("Отключить VK (очистить токен)")
        clear_vk_btn.clicked.connect(self._on_clear_vk_token)
        form.addRow("", clear_vk_btn)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _on_get_vk_token(self):
        if not HAS_VKPYMUSIC:
            QMessageBox.critical(
                self, "VK недоступен",
                "Библиотека vkpymusic не установлена.\n\n"
                "Установи её командой:\n"
                "pip install vkpymusic"
            )
            return

        dlg = VkLoginDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return

        login, password, twofa = dlg.get_credentials()
        if not login or not password:
            QMessageBox.warning(self, "Заполни поля", "Нужны логин и пароль.")
            return

        prog = QProgressDialog("Авторизация в VK…", None, 0, 0, self)
        prog.setWindowTitle("VK")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setCancelButton(None)
        prog.show()
        QApplication.processEvents()

        try:
            receiver = VkTokenReceiver(login, password)
            ok = receiver.auth()
            if not ok:
                prog.close()
                QMessageBox.critical(
                    self, "Не удалось войти",
                    "VK отклонил авторизацию.\n\n"
                    "Возможные причины:\n"
                    "• Неверный логин/пароль.\n"
                    "• Требуется капча или 2FA.\n"
                    "• Аккаунт временно ограничен.\n\n"
                    "Альтернатива: получи токен через vkhost.github.io и вставь в поле «VK токен»."
                )
                return
            token = receiver.get_token()
            user_agent = getattr(receiver, "user_agent", "") or ""
            prog.close()
            if not token:
                QMessageBox.critical(self, "Ошибка", "Токен не получен.")
                return
            self.vk_token_edit.setText(token)
            if user_agent:
                self.cfg["vk_user_agent"] = user_agent
            QMessageBox.information(self, "Готово", "VK подключён. Нажми OK, чтобы сохранить.")
        except Exception as e:
            prog.close()
            QMessageBox.critical(self, "Ошибка VK", f"Что-то пошло не так:\n{e}")

    def _on_clear_vk_token(self):
        self.vk_token_edit.setText("")
        self.cfg["vk_token"] = ""
        self.cfg["vk_user_agent"] = ""
        QMessageBox.information(self, "VK", "Токен очищен. Не забудь нажать OK.")

    def apply_to(self, cfg):
        for k, le in self.fields.items():
            v = le.text().strip().lower()
            if v:
                cfg[k] = v
        cfg["opacity"] = self.opacity_slider.value() / 100
        cfg["show_notification"] = self.notif_cb.isChecked()
        cfg["media_keys_enabled"] = self.media_cb.isChecked()
        cfg["vk_token"] = self.vk_token_edit.text().strip()
        set_autostart(self.autostart_cb.isChecked())

# ---------------------------------------------------------------- overlay
OVERLAY_W = 460
OVERLAY_H = 250
CARD_RADIUS = 22
COVER_SIZE = 138

class Overlay(QWidget):
    def __init__(self, player: MusicPlayer, cfg: dict):
        super().__init__()
        self.player = player
        self.cfg = cfg
        self._drag_pos: QPoint | None = None
        self._last_playing_state = None
        self._volume_level = 2
        self._track_ever_shown = False

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.resize(OVERLAY_W, OVERLAY_H)
        self.move(cfg.get("window_x", 60), cfg.get("window_y", 60))
        self._full_geom = QRect(self.geometry())

        self._build_ui()

        self.player.repeat_mode = cfg.get("repeat_mode", "off")
        self.player.shuffle = bool(cfg.get("shuffle", False))
        self._refresh_mode_icons()

        player.track_changed.connect(self.on_track_changed)
        player.state_changed.connect(self.on_state_changed)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_progress)
        self.timer.start(300)

        self.setWindowOpacity(cfg.get("opacity", 0.96))

        self.playlist_popup = PlaylistPopup()
        self.playlist_popup.track_activated.connect(self._play_from_playlist)
        self.playlist_popup.track_removed.connect(self._remove_from_playlist)
        self.playlist_popup.clear_requested.connect(self.clear_playlist)

        self.notification = TrackNotification()

    def _build_ui(self):
        self.card = QWidget(self)
        self.card.setGeometry(0, 0, self.width(), self.height())
        self.card.setStyleSheet("background: transparent;")

        outer = QHBoxLayout(self.card)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(16)

        self.cover = QLabel()
        self.cover.setFixedSize(COVER_SIZE, COVER_SIZE)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background: rgba(255,255,255,0.10); border-radius: 14px;")
        self.cover.setScaledContents(False)
        outer.addWidget(self.cover, 0, Qt.AlignVCenter)

        right = QVBoxLayout()
        right.setSpacing(2)
        right.setContentsMargins(0, 0, 0, 0)
        right.setAlignment(Qt.AlignVCenter)
        outer.addLayout(right, 1)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(4)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.setContentsMargins(0, 0, 0, 0)

        self.title_lbl = QLabel("Ничего не играет")
        self.title_lbl.setStyleSheet(
            "color:#ffffff; font-size:15px; font-weight:700; background:transparent;"
        )
        self.title_lbl.setWordWrap(False)
        self.title_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        titles.addWidget(self.title_lbl)

        self.artist_lbl = QLabel("")
        self.artist_lbl.setStyleSheet(
            "color:rgba(255,255,255,0.65); font-size:11px; background:transparent;"
        )
        self.artist_lbl.setWordWrap(False)
        self.artist_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        titles.addWidget(self.artist_lbl)

        top_row.addLayout(titles, 1)

        self.btn_shuffle = self._mk_small_btn("shuffle")
        self.btn_repeat = self._mk_small_btn("repeat")
        self.btn_playlist = self._mk_small_btn("playlist")
        self.btn_shuffle.clicked.connect(self.toggle_shuffle)
        self.btn_repeat.clicked.connect(self.toggle_repeat)
        self.btn_playlist.clicked.connect(self.toggle_playlist)
        top_row.addWidget(self.btn_shuffle, 0, Qt.AlignTop)
        top_row.addWidget(self.btn_repeat, 0, Qt.AlignTop)
        top_row.addWidget(self.btn_playlist, 0, Qt.AlignTop)

        right.addLayout(top_row)
        right.addSpacing(10)

        self.progress = QSlider(Qt.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.setFixedHeight(16)
        self.progress.sliderReleased.connect(self.on_seek)
        self.progress.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px; background: rgba(255,255,255,0.22);
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal { background: #ffffff; border-radius: 2px; }
            QSlider::handle:horizontal {
                background: #ffffff; width: 12px; height: 12px;
                margin: -4px 0; border-radius: 6px;
            }
        """)
        right.addWidget(self.progress)

        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        self.time_cur = QLabel("0:00")
        self.time_len = QLabel("0:00")
        for lbl in (self.time_cur, self.time_len):
            lbl.setStyleSheet("color:rgba(255,255,255,0.65); font-size:10px; background:transparent;")
        time_row.addWidget(self.time_cur)
        time_row.addStretch(1)
        time_row.addWidget(self.time_len)
        right.addLayout(time_row)

        right.addSpacing(8)

        big_row = QHBoxLayout()
        big_row.setContentsMargins(0, 0, 0, 0)
        big_row.setSpacing(28)
        big_row.addStretch(1)

        self.btn_prev = self._mk_big_btn("prev")
        self.btn_play = self._mk_big_btn("play")
        self.btn_next = self._mk_big_btn("next")
        self.btn_prev.clicked.connect(self.player.prev)
        self.btn_play.clicked.connect(self.player.play_pause)
        self.btn_next.clicked.connect(self.player.next)

        big_row.addWidget(self.btn_prev)
        big_row.addWidget(self.btn_play)
        big_row.addWidget(self.btn_next)
        big_row.addStretch(1)
        right.addLayout(big_row)

        right.addSpacing(8)

        vol_row = QHBoxLayout()
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(8)

        self.vol_icon_left = QLabel()
        self.vol_icon_left.setFixedSize(14, 14)
        self.vol_icon_left.setStyleSheet("background:transparent;")
        vol_row.addWidget(self.vol_icon_left)

        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(int(self.cfg.get("volume", 70)))
        self.vol_slider.setFixedHeight(14)
        self.vol_slider.valueChanged.connect(self.on_volume_changed)
        self.vol_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 3px; background: rgba(255,255,255,0.22);
                border-radius: 1px;
            }
            QSlider::sub-page:horizontal { background: #ffffff; border-radius: 1px; }
            QSlider::handle:horizontal {
                background: #ffffff; width: 10px; height: 10px;
                margin: -4px 0; border-radius: 5px;
            }
        """)
        vol_row.addWidget(self.vol_slider, 1)

        self.vol_icon_right = QLabel()
        self.vol_icon_right.setFixedSize(14, 14)
        self.vol_icon_right.setStyleSheet("background:transparent;")
        vol_row.addWidget(self.vol_icon_right)

        self._update_volume_icons(int(self.cfg.get("volume", 70)))
        right.addLayout(vol_row)

        right.addSpacing(6)

        ind_wrap = QHBoxLayout()
        ind_wrap.setContentsMargins(0, 0, 0, 0)
        ind_wrap.addStretch(1)
        ind = QFrame()
        ind.setFixedSize(60, 3)
        ind.setStyleSheet("background: rgba(255,255,255,0.45); border-radius: 1px;")
        ind_wrap.addWidget(ind)
        ind_wrap.addStretch(1)
        right.addLayout(ind_wrap)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def _make_icon(self, kind: str, color: str = "#fff", size: int = 16) -> QIcon:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        s = size

        if kind == "play":
            path = QPainterPath()
            path.moveTo(s * 0.30, s * 0.14)
            path.lineTo(s * 0.86, s * 0.50)
            path.lineTo(s * 0.30, s * 0.86)
            path.closeSubpath()
            p.drawPath(path)
        elif kind == "pause":
            p.drawRoundedRect(int(s * 0.28), int(s * 0.14), int(s * 0.16), int(s * 0.72), 2, 2)
            p.drawRoundedRect(int(s * 0.56), int(s * 0.14), int(s * 0.16), int(s * 0.72), 2, 2)
        elif kind == "prev":
            path = QPainterPath()
            path.moveTo(s * 0.92, s * 0.16); path.lineTo(s * 0.44, s * 0.50); path.lineTo(s * 0.92, s * 0.84)
            path.closeSubpath(); p.drawPath(path)
            path = QPainterPath()
            path.moveTo(s * 0.52, s * 0.16); path.lineTo(s * 0.04, s * 0.50); path.lineTo(s * 0.52, s * 0.84)
            path.closeSubpath(); p.drawPath(path)
        elif kind == "next":
            path = QPainterPath()
            path.moveTo(s * 0.08, s * 0.16); path.lineTo(s * 0.56, s * 0.50); path.lineTo(s * 0.08, s * 0.84)
            path.closeSubpath(); p.drawPath(path)
            path = QPainterPath()
            path.moveTo(s * 0.48, s * 0.16); path.lineTo(s * 0.96, s * 0.50); path.lineTo(s * 0.48, s * 0.84)
            path.closeSubpath(); p.drawPath(path)
        elif kind == "shuffle":
            pen = QPen(QColor(color), max(1.4, s * 0.10)); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(s * 0.10, s * 0.32)
            path.cubicTo(s * 0.42, s * 0.32, s * 0.58, s * 0.68, s * 0.86, s * 0.68)
            p.drawPath(path)
            path2 = QPainterPath()
            path2.moveTo(s * 0.10, s * 0.68)
            path2.cubicTo(s * 0.42, s * 0.68, s * 0.58, s * 0.32, s * 0.86, s * 0.32)
            p.drawPath(path2)
            p.setPen(Qt.NoPen); p.setBrush(QColor(color))
            tri = QPainterPath()
            tri.moveTo(s * 0.80, s * 0.22); tri.lineTo(s * 0.96, s * 0.32); tri.lineTo(s * 0.80, s * 0.42)
            tri.closeSubpath(); p.drawPath(tri)
            tri2 = QPainterPath()
            tri2.moveTo(s * 0.80, s * 0.58); tri2.lineTo(s * 0.96, s * 0.68); tri2.lineTo(s * 0.80, s * 0.78)
            tri2.closeSubpath(); p.drawPath(tri2)
        elif kind == "repeat":
            pen = QPen(QColor(color), max(1.4, s * 0.10)); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            rect = QRect(int(s * 0.14), int(s * 0.18), int(s * 0.72), int(s * 0.64))
            p.drawArc(rect, 40 * 16, 280 * 16)
            p.setPen(Qt.NoPen); p.setBrush(QColor(color))
            tri = QPainterPath()
            tri.moveTo(s * 0.74, s * 0.12); tri.lineTo(s * 0.94, s * 0.24); tri.lineTo(s * 0.72, s * 0.34)
            tri.closeSubpath(); p.drawPath(tri)
        elif kind == "repeat_one":
            pen = QPen(QColor(color), max(1.4, s * 0.10)); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            rect = QRect(int(s * 0.14), int(s * 0.18), int(s * 0.72), int(s * 0.64))
            p.drawArc(rect, 40 * 16, 280 * 16)
            p.setPen(Qt.NoPen); p.setBrush(QColor(color))
            tri = QPainterPath()
            tri.moveTo(s * 0.74, s * 0.12); tri.lineTo(s * 0.94, s * 0.24); tri.lineTo(s * 0.72, s * 0.34)
            tri.closeSubpath(); p.drawPath(tri)
            p.setPen(QPen(QColor(color), max(1.4, s * 0.10)))
            p.drawLine(int(s * 0.46), int(s * 0.40), int(s * 0.46), int(s * 0.62))
            p.drawLine(int(s * 0.46), int(s * 0.40), int(s * 0.40), int(s * 0.46))
        elif kind == "playlist":
            pen = QPen(QColor(color), max(1.8, s * 0.12)); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            for i in range(3):
                y = s * (0.32 + i * 0.18)
                p.drawLine(int(s * 0.18), int(y), int(s * 0.82), int(y))
        elif kind == "volume_off":
            p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
            path = QPainterPath()
            path.moveTo(s * 0.10, s * 0.38); path.lineTo(s * 0.30, s * 0.38); path.lineTo(s * 0.55, s * 0.18)
            path.lineTo(s * 0.55, s * 0.82); path.lineTo(s * 0.30, s * 0.62); path.lineTo(s * 0.10, s * 0.62)
            path.closeSubpath(); p.drawPath(path)
            pen = QPen(QColor(color), max(1.8, s * 0.10)); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(int(s * 0.66), int(s * 0.36), int(s * 0.92), int(s * 0.64))
            p.drawLine(int(s * 0.92), int(s * 0.36), int(s * 0.66), int(s * 0.64))
        elif kind == "volume_low":
            p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
            path = QPainterPath()
            path.moveTo(s * 0.10, s * 0.38); path.lineTo(s * 0.30, s * 0.38); path.lineTo(s * 0.55, s * 0.18)
            path.lineTo(s * 0.55, s * 0.82); path.lineTo(s * 0.30, s * 0.62); path.lineTo(s * 0.10, s * 0.62)
            path.closeSubpath(); p.drawPath(path)
            pen = QPen(QColor(color), max(1.6, s * 0.09)); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            rect = QRect(int(s * 0.60), int(s * 0.36), int(s * 0.20), int(s * 0.28))
            p.drawArc(rect, -55 * 16, 110 * 16)
        elif kind == "volume_high":
            p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
            path = QPainterPath()
            path.moveTo(s * 0.10, s * 0.38); path.lineTo(s * 0.30, s * 0.38); path.lineTo(s * 0.55, s * 0.18)
            path.lineTo(s * 0.55, s * 0.82); path.lineTo(s * 0.30, s * 0.62); path.lineTo(s * 0.10, s * 0.62)
            path.closeSubpath(); p.drawPath(path)
            pen = QPen(QColor(color), max(1.6, s * 0.09)); pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            rect = QRect(int(s * 0.60), int(s * 0.36), int(s * 0.20), int(s * 0.28))
            p.drawArc(rect, -55 * 16, 110 * 16)
            rect2 = QRect(int(s * 0.68), int(s * 0.28), int(s * 0.26), int(s * 0.44))
            p.drawArc(rect2, -55 * 16, 110 * 16)
        p.end()
        return QIcon(pm)

    def _mk_big_btn(self, kind: str):
        b = QPushButton()
        s = 38
        b.setFixedSize(s, s)
        icon_size = int(s * 0.7)
        b.setProperty("icon_kind", kind)
        b.setProperty("icon_size", icon_size)
        b.setIcon(self._make_icon(kind, "#ffffff", icon_size))
        b.setIconSize(QSize(icon_size, icon_size))
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; border-radius: {s//2}px; }}
            QPushButton:hover {{ background: rgba(255,255,255,0.10); }}
            QPushButton:pressed {{ background: rgba(255,255,255,0.18); }}
        """)
        return b

    def _mk_small_btn(self, kind: str):
        b = QPushButton()
        s = 24
        b.setFixedSize(s, s)
        icon_size = int(s * 0.7)
        b.setProperty("icon_kind", kind)
        b.setProperty("icon_size", icon_size)
        b.setIcon(self._make_icon(kind, "#ffffff", icon_size))
        b.setIconSize(QSize(icon_size, icon_size))
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; border-radius: {s//2}px; }}
            QPushButton:hover {{ background: rgba(255,255,255,0.10); }}
            QPushButton:pressed {{ background: rgba(255,255,255,0.18); }}
        """)
        return b

    def _set_btn_icon(self, btn: QPushButton, kind: str, color: str = "#ffffff"):
        size = btn.property("icon_size") or int(btn.width() * 0.7)
        btn.setIcon(self._make_icon(kind, color, size))

    def _refresh_mode_icons(self):
        color = "#4a9eff" if self.player.shuffle else "#ffffff"
        self._set_btn_icon(self.btn_shuffle, "shuffle", color)

        mode = self.player.repeat_mode
        if mode == "off":
            self._set_btn_icon(self.btn_repeat, "repeat", "#ffffff")
        elif mode == "all":
            self._set_btn_icon(self.btn_repeat, "repeat", "#4a9eff")
        else:
            self._set_btn_icon(self.btn_repeat, "repeat_one", "#4a9eff")

    def _update_volume_icons(self, vol: int):
        if vol <= 0:
            level = 0
        elif vol <= 50:
            level = 1
        else:
            level = 2
        self._volume_level = level

        if level == 0:
            left = self._make_icon("volume_off", "#ffffff", 14).pixmap(14, 14)
            right = self._make_icon("volume_off", "#ffffff", 14).pixmap(14, 14)
        elif level == 1:
            left = self._make_icon("volume_low", "#ffffff", 14).pixmap(14, 14)
            right = self._make_icon("volume_low", "#ffffff", 14).pixmap(14, 14)
        else:
            left = self._make_icon("volume_low", "#ffffff", 14).pixmap(14, 14)
            right = self._make_icon("volume_high", "#ffffff", 14).pixmap(14, 14)

        self.vol_icon_left.setPixmap(left)
        self.vol_icon_right.setPixmap(right)

    def toggle_shuffle(self):
        self.player.shuffle = not self.player.shuffle
        self.cfg["shuffle"] = self.player.shuffle
        save_config(self.cfg)
        self._refresh_mode_icons()

    def toggle_repeat(self):
        mode = self.player.repeat_mode
        self.player.repeat_mode = {"off": "all", "all": "one", "one": "off"}[mode]
        self.cfg["repeat_mode"] = self.player.repeat_mode
        save_config(self.cfg)
        self._refresh_mode_icons()

    def toggle_playlist(self):
        if self.playlist_popup.isVisible():
            self.playlist_popup.hide()
            return
        self.playlist_popup.refresh(self.player.playlist, self.player.index)
        g = self.geometry()
        x = g.right() + 8
        y = max(20, g.top() + g.height() // 2 - 200)
        self.playlist_popup.move(x, y)
        self.playlist_popup.show()

    def _play_from_playlist(self, idx: int):
        self.player.play_index(idx)
        self.playlist_popup.refresh(self.player.playlist, self.player.index)

    def _remove_from_playlist(self, idx: int):
        if not (0 <= idx < len(self.player.playlist)):
            return
        if 0 <= idx < len(self.cfg["tracks"]):
            self.cfg["tracks"].pop(idx)
            save_config(self.cfg)
        self.player.playlist.pop(idx)
        if idx < self.player.index:
            self.player.index -= 1
        elif idx == self.player.index:
            self.player.index = min(self.player.index, len(self.player.playlist) - 1)
            if self.player.index < 0:
                self.player.player.stop()
                self.player.index = -1
                self.title_lbl.setText("Ничего не играет")
                self.artist_lbl.setText("")
                self.cover.clear()
        self.playlist_popup.refresh(self.player.playlist, self.player.index)

    def show_menu(self, pos):
        m = QMenu(self)
        a_add = QAction("Добавить файлы…", self)
        a_add.triggered.connect(self.add_files)
        a_url = QAction("Добавить ссылку (YouTube, SoundCloud)…", self)
        a_url.triggered.connect(self.add_url)
        a_vk = QAction("Добавить из VK…", self)
        a_vk.triggered.connect(self.add_vk_playlist)
        a_pl = QAction("Плейлист", self)
        a_pl.triggered.connect(self.toggle_playlist)
        a_clear = QAction("Очистить плейлист", self)
        a_clear.triggered.connect(self.clear_playlist)
        a_hide = QAction("Скрыть оверлей", self)
        a_hide.triggered.connect(self.animate_out)
        a_quit = QAction("Выход", self)
        a_quit.triggered.connect(QApplication.quit)

        m.addAction(a_add)
        m.addAction(a_url)
        m.addAction(a_vk)
        m.addAction(a_pl)
        m.addAction(a_clear)
        m.addSeparator()
        m.addAction(a_hide)
        m.addSeparator()
        m.addAction(a_quit)
        m.exec(self.mapToGlobal(pos))

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выбери треки", "", "Аудио (*.mp3 *.flac *.m4a *.ogg *.wav *.aac)"
        )
        if files:
            self.cfg["tracks"].extend(files)
            save_config(self.cfg)
            self.player.set_playlist(self.cfg["tracks"])
            if self.player.index == -1:
                self.player.play_index(0)

    @staticmethod
    def _find_yandex_profile():
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Yandex" / "YandexBrowser" / "User Data",
            Path(os.environ.get("APPDATA", "")) / "Yandex" / "YandexBrowser" / "User Data",
        ]
        for base in candidates:
            if base.exists():
                for prof in base.iterdir():
                    if prof.is_dir() and (prof / "Network" / "Cookies").exists():
                        return prof
                if (base / "Network" / "Cookies").exists():
                    return base
        return None

    def _pick_cookie_options(self):
        mode = self.cfg.get("browser_for_cookies", "auto")
        if mode == "none":
            return []
        if mode == "yandex":
            prof = self._find_yandex_profile()
            if prof is not None:
                return [("chrome", str(prof))]
            return [("chrome", None)]
        if mode != "auto":
            return [(mode, None)]
        result = []
        prof = self._find_yandex_profile()
        if prof is not None:
            result.append(("chrome", str(prof)))
        result.extend([
            ("chrome", None), ("edge", None), ("firefox", None),
            ("brave", None), ("opera", None), ("vivaldi", None),
        ])
        return result

    # -------------------- VK playlist --------------------
    def add_vk_playlist(self):
        if not HAS_VKPYMUSIC:
            QMessageBox.critical(
                self, "VK недоступен",
                "Библиотека vkpymusic не установлена.\n\n"
                "Установи её командой:\n"
                "pip install vkpymusic"
            )
            return

        token = self.cfg.get("vk_token", "").strip()
        if not token:
            QMessageBox.warning(
                self, "Нет VK токена",
                "Сначала подключи VK в настройках:\n"
                "ПКМ по трею → Настройки… → «Получить токен через логин/пароль»."
            )
            return

        url, ok = QInputDialog.getText(
            self, "VK плейлист",
            "Вставь ссылку на VK-плейлист:\n"
            "(например: https://vk.com/music/playlist/-12345_67890\n"
            "или с ключом: https://vk.com/music/playlist/-12345_67890_abc123)"
        )
        if not ok or not url.strip():
            return
        url = url.strip()

        prog = QProgressDialog("Подключаюсь к VK…", "Отмена", 0, 0, self)
        prog.setWindowTitle("VK")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setAutoClose(False)
        prog.setValue(0)
        prog.show()
        QApplication.processEvents()

        try:
            user_agent = self.cfg.get("vk_user_agent", "") or "Mozilla/5.0"
            service = VkService(user_agent, token)

            try:
                valid = service.is_token_valid()
            except Exception:
                valid = True  # если метода нет — пробуем дальше
            if not valid:
                prog.close()
                QMessageBox.critical(
                    self, "VK токен истёк",
                    "Токен больше не действителен. Подключи VK заново в настройках."
                )
                return

            # Парсим ссылку: /music/playlist/OWNERID_PLAYLISTID[_ACCESSKEY]
            import re
            m = re.search(r"/music/playlist/(-?\d+)_(\d+)(?:_([A-Za-z0-9]+))?", url)
            if not m:
                prog.close()
                QMessageBox.warning(
                    self, "Не понял ссылку",
                    "Ожидаю ссылку вида:\n"
                    "https://vk.com/music/playlist/-12345_67890\n"
                    "или с ключом доступа:\n"
                    "https://vk.com/music/playlist/-12345_67890_abcdef123456"
                )
                return

            owner_id = int(m.group(1))
            playlist_id = int(m.group(2))
            access_key = m.group(3) or ""

            prog.setLabelText("Получаю список треков…")
            QApplication.processEvents()

            # Пробуем разные сигнатуры get_songs_by_playlist_id
            songs = None
            try:
                if access_key:
                    songs = service.get_songs_by_playlist_id(
                        owner_id, playlist_id, access_key, count=200
                    )
                else:
                    songs = service.get_songs_by_playlist_id(
                        owner_id, playlist_id, count=200
                    )
            except TypeError:
                # старая сигнатура без access_key
                try:
                    songs = service.get_songs_by_playlist_id(owner_id, playlist_id)
                except Exception as e:
                    print("get_songs_by_playlist_id err:", e)

            if songs is None:
                prog.close()
                QMessageBox.warning(
                    self, "Не удалось получить плейлист",
                    "Библиотека не смогла загрузить список треков.\n\n"
                    "Возможные причины:\n"
                    "• Плейлист приватный (нужен access_key).\n"
                    "• Токен не имеет доступа к аудио.\n"
                    "• Устаревшая версия vkpymusic: pip install --upgrade vkpymusic"
                )
                return

            if not songs:
                prog.close()
                QMessageBox.information(self, "Пусто", "В плейлисте нет треков (или он приватный).")
                return

            prog.setLabelText(f"Скачиваю {len(songs)} треков…")
            prog.setRange(0, len(songs))
            QApplication.processEvents()

            added = 0
            for i, song in enumerate(songs):
                if prog.wasCanceled():
                    break
                try:
                    title = getattr(song, "title", "") or "?"
                    artist = getattr(song, "artist", "") or "?"
                    prog.setLabelText(f"[{i+1}/{len(songs)}] {title[:40]} — {artist[:30]}")
                    prog.setValue(i)
                    QApplication.processEvents()

                    path = None
                    # Пробуем с путём
                    try:
                        path = service.save_music(song, str(DOWNLOADS_DIR))
                    except TypeError:
                        pass
                    except Exception as e:
                        print("save_music(path) err:", e)

                    # Если не сработало — временно меняем cwd
                    if not path or not Path(path).exists():
                        old_cwd = os.getcwd()
                        try:
                            os.chdir(str(DOWNLOADS_DIR))
                            try:
                                path = service.save_music(song)
                            except Exception as e:
                                print("save_music() err:", e)
                                path = None
                        finally:
                            try:
                                os.chdir(old_cwd)
                            except Exception:
                                pass

                    if path and Path(path).exists():
                        self.cfg["tracks"].append(str(path))
                        added += 1
                except Exception as e:
                    print(f"VK download err: {e}")

            prog.close()
            save_config(self.cfg)
            self.player.set_playlist(self.cfg["tracks"])
            if self.player.index == -1 and self.cfg["tracks"]:
                self.player.play_index(0)

            QMessageBox.information(
                self, "VK",
                f"Готово: добавлено {added} из {len(songs)} треков.\n"
                f"Папка загрузок: {DOWNLOADS_DIR}"
            )
        except Exception as e:
            prog.close()
            QMessageBox.critical(
                self, "Ошибка VK",
                f"Не удалось обработать плейлист:\n{e}\n\n"
                "Возможные причины:\n"
                "• Ссылка неверного формата.\n"
                "• Плейлист приватный.\n"
                "• Токен отозван — переподключи VK."
            )

    # -------------------- обычная загрузка --------------------
    def add_url(self):
        url, ok = QInputDialog.getText(
            self, "Ссылка на трек или плейлист",
            "Вставь ссылку (YouTube, SoundCloud и др.):\n\n"
            "⚠️ Для музыки VK используй «Добавить из VK…»."
        )
        if not ok or not url.strip():
            return
        url = url.strip()

        prog = QProgressDialog("Готовлю загрузку…", "Отмена", 0, 0, self)
        prog.setWindowTitle("Скачивание")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setAutoClose(False)
        prog.setAutoReset(False)
        prog.setValue(0)
        prog.show()
        QApplication.processEvents()

        def _hook(d):
            if d.get("status") == "downloading":
                try:
                    pct = d.get("_percent_str", "").strip()
                    name = Path(d.get("filename", "")).name
                    prog.setLabelText(f"Скачиваю: {name[:45]}\n{pct}")
                    QApplication.processEvents()
                except Exception:
                    pass

        base_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(DOWNLOADS_DIR / "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,
            "ignoreerrors": True,
            "progress_hooks": [_hook],
            "nocheckcertificate": True,
        }

        attempts = self._pick_cookie_options()
        last_err = None
        info = None
        used_opts = None

        for browser, profile in attempts:
            if prog.wasCanceled():
                break
            try:
                opts = dict(base_opts)
                opts["cookiesfrombrowser"] = (browser, profile, None, None)
                label = f"{browser}" + (f" ({Path(profile).name})" if profile else "")
                prog.setLabelText(f"Пробую cookies: {label}…")
                QApplication.processEvents()
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                used_opts = opts
                if info is not None:
                    break
            except Exception as e:
                last_err = e
                print(f"[cookies {browser}/{profile}] {e}")
                continue

        if info is None:
            try:
                prog.setLabelText("Пробую без cookies…")
                QApplication.processEvents()
                with yt_dlp.YoutubeDL(base_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                used_opts = base_opts
            except Exception as e:
                last_err = e
                print("[no cookies]", e)

        prog.close()

        if info is None:
            QMessageBox.critical(
                self, "Не удалось скачать",
                "Не получилось загрузить трек/плейлист.\n\n"
                f"Ошибка: {last_err}\n\n"
                "Этот способ работает для YouTube/SoundCloud.\n"
                "Для музыки VK используй «Добавить из VK…» (нужен токен)."
            )
            return

        paths = []
        if isinstance(info, dict) and "entries" in info:
            for e in info["entries"]:
                if not e:
                    continue
                try:
                    if used_opts is not None:
                        with yt_dlp.YoutubeDL(used_opts) as ydl2:
                            paths.append(ydl2.prepare_filename(e))
                    else:
                        paths.append(e.get("filepath") or "")
                except Exception:
                    pass
        else:
            if used_opts is not None:
                with yt_dlp.YoutubeDL(used_opts) as ydl2:
                    paths.append(ydl2.prepare_filename(info))
            else:
                paths.append(info.get("filepath") or "")

        added = 0
        for p in paths:
            if p and Path(p).exists():
                self.cfg["tracks"].append(p)
                added += 1
        save_config(self.cfg)
        self.player.set_playlist(self.cfg["tracks"])
        if self.player.index == -1 and self.cfg["tracks"]:
            self.player.play_index(0)

        if added == 0:
            QMessageBox.warning(
                self, "Файлы не найдены",
                "Скачивание прошло, но файлы не найдены на диске.\n"
                f"Папка загрузок: {DOWNLOADS_DIR}"
            )
        elif added > 1:
            QMessageBox.information(self, "Готово", f"Добавлено треков: {added}")

    def clear_playlist(self):
        self.cfg["tracks"] = []
        save_config(self.cfg)
        self.player.set_playlist([])
        self.player.index = -1
        self.title_lbl.setText("Ничего не играет")
        self.artist_lbl.setText("")
        self.cover.clear()
        if self.playlist_popup.isVisible():
            self.playlist_popup.refresh(self.player.playlist, self.player.index)

    def on_volume_changed(self, v):
        self.player.set_volume(v)
        self.cfg["volume"] = int(v)
        save_config(self.cfg)
        self._update_volume_icons(int(v))

    def on_track_changed(self, track: Track):
        title = track.title or Path(track.path).stem
        artist = track.artist or ""
        album = track.album or ""
        subtitle = " — ".join([x for x in (artist, album) if x]) or ""

        self.title_lbl.setText(title)
        self.title_lbl.setToolTip(title)
        if self.title_lbl.width() > 0:
            self.title_lbl.setText(self._elide(self.title_lbl, title))

        self.artist_lbl.setText(subtitle)
        self.artist_lbl.setToolTip(subtitle)
        if subtitle and self.artist_lbl.width() > 0:
            self.artist_lbl.setText(self._elide(self.artist_lbl, subtitle))

        if track.cover_path and Path(track.cover_path).exists():
            size = self.cover.width()
            px = QPixmap(track.cover_path).scaled(
                size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            rounded = QPixmap(size, size)
            rounded.fill(Qt.transparent)
            rp = QPainter(rounded)
            rp.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(0, 0, size, size, 14, 14)
            rp.setClipPath(path)
            rp.drawPixmap(0, 0, px)
            rp.end()
            self.cover.setPixmap(rounded)
        else:
            self.cover.clear()

        if self._track_ever_shown and self.cfg.get("show_notification", True):
            self.notification.show_track(track)
        self._track_ever_shown = True

        if self.playlist_popup.isVisible():
            self.playlist_popup.refresh(self.player.playlist, self.player.index)

    def _update_play_icon(self, playing: bool):
        s = int(self.btn_play.width() * 0.7)
        self.btn_play.setIcon(
            self._make_icon("pause" if playing else "play", "#ffffff", s)
        )

    def on_state_changed(self, playing: bool):
        self._last_playing_state = playing
        self._update_play_icon(playing)

    def _fmt_time(self, ms: int) -> str:
        if ms is None or ms < 0:
            ms = 0
        s = ms // 1000
        return f"{s // 60}:{s % 60:02d}"

    def update_progress(self):
        self.player.tick()
        length = self.player.length()
        if length > 0:
            pos = self.player.time()
            if not self.progress.isSliderDown():
                self.progress.setValue(int(pos / length * 1000))
            self.time_cur.setText(self._fmt_time(pos))
            self.time_len.setText(self._fmt_time(length))
        playing = self.player.is_playing()
        if playing != self._last_playing_state:
            self._last_playing_state = playing
            self._update_play_icon(playing)

    def on_seek(self):
        length = self.player.length()
        if length > 0:
            self.player.seek(int(self.progress.value() / 1000 * length))

    def _elide(self, label: QLabel, text: str) -> str:
        fm = QFontMetrics(label.font())
        avail = max(40, label.width() - 4) if label.width() > 0 else 999
        return fm.elidedText(text, Qt.ElideRight, avail)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "card"):
            self.card.setGeometry(0, 0, self.width(), self.height())
        if not hasattr(self, "_full_geom"):
            self._full_geom = QRect(self.geometry())
        if self.title_lbl.toolTip():
            self.title_lbl.setText(self._elide(self.title_lbl, self.title_lbl.toolTip()))
        if self.artist_lbl.toolTip():
            self.artist_lbl.setText(self._elide(self.artist_lbl, self.artist_lbl.toolTip()))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().toRectF(), CARD_RADIUS, CARD_RADIUS)
        p.fillPath(path, QColor(58, 58, 64, 235))
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.drawPath(path)

    def animate_in(self):
        end_geom = QRect(self._full_geom)
        center = end_geom.center()
        start_geom = QRect(0, 0,
                           int(end_geom.width() * 0.7),
                           int(end_geom.height() * 0.7))
        start_geom.moveCenter(center)

        self.setGeometry(start_geom)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        anim_op = QPropertyAnimation(self, b"windowOpacity", self)
        anim_op.setDuration(400)
        anim_op.setStartValue(0.0)
        anim_op.setEndValue(self.cfg.get("opacity", 0.96))
        anim_op.setEasingCurve(QEasingCurve.OutCubic)

        anim_g = QPropertyAnimation(self, b"geometry", self)
        anim_g.setDuration(460)
        anim_g.setStartValue(start_geom)
        anim_g.setEndValue(end_geom)
        anim_g.setEasingCurve(QEasingCurve.OutBack)

        self._anim_group = QParallelAnimationGroup(self)
        self._anim_group.addAnimation(anim_op)
        self._anim_group.addAnimation(anim_g)
        self._anim_group.start()

    def animate_out(self):
        if self.playlist_popup.isVisible():
            self.playlist_popup.hide()

        self._full_geom = QRect(self.geometry())
        end_geom = QRect(self._full_geom)
        center = end_geom.center()
        shrink_geom = QRect(0, 0,
                            int(end_geom.width() * 0.7),
                            int(end_geom.height() * 0.7))
        shrink_geom.moveCenter(center)

        anim_op = QPropertyAnimation(self, b"windowOpacity", self)
        anim_op.setDuration(220)
        anim_op.setStartValue(self.windowOpacity())
        anim_op.setEndValue(0.0)
        anim_op.setEasingCurve(QEasingCurve.InCubic)

        anim_g = QPropertyAnimation(self, b"geometry", self)
        anim_g.setDuration(220)
        anim_g.setStartValue(end_geom)
        anim_g.setEndValue(shrink_geom)
        anim_g.setEasingCurve(QEasingCurve.InCubic)

        self._anim_out_group = QParallelAnimationGroup(self)
        self._anim_out_group.addAnimation(anim_op)
        self._anim_out_group.addAnimation(anim_g)

        def _finish():
            self.setGeometry(self._full_geom)
            self.hide()

        self._anim_out_group.finished.connect(_finish)
        self._anim_out_group.start()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        if self._drag_pos:
            self._drag_pos = None
            self._full_geom = QRect(self.geometry())
            self.cfg["window_x"] = self.x()
            self.cfg["window_y"] = self.y()
            save_config(self.cfg)

# ---------------------------------------------------------------- hotkeys
class HotkeyBridge(QObject):
    toggle_overlay = Signal()
    toggle_click = Signal()
    prev = Signal()
    next = Signal()
    next_in_order = Signal()
    play_pause = Signal()
    vol_up = Signal()
    vol_down = Signal()
    quit_app = Signal()

_click_state = {"on": False}

def toggle_click_through(overlay: "Overlay"):
    _click_state["on"] = not _click_state["on"]
    set_click_through(int(overlay.winId()), _click_state["on"])

def change_vol(player: "MusicPlayer", overlay: "Overlay", delta: int):
    new = max(0, min(100, player.player.audio_get_volume() + delta))
    player.set_volume(new)
    overlay.vol_slider.setValue(int(new))
    overlay.cfg["volume"] = new
    save_config(overlay.cfg)

def register_hotkeys(cfg, bridge):
    try:
        keyboard.unhook_all_hotkeys()
    except Exception:
        pass
    try:
        keyboard.add_hotkey(cfg["toggle_overlay"], bridge.toggle_overlay.emit)
        keyboard.add_hotkey(cfg["toggle_click_through"], bridge.toggle_click.emit)
        keyboard.add_hotkey(cfg["prev_track"], bridge.prev.emit)
        keyboard.add_hotkey(cfg["next_track"], bridge.next.emit)
        keyboard.add_hotkey(cfg["next_track_in_order"], bridge.next_in_order.emit)
        keyboard.add_hotkey(cfg["play_pause"], bridge.play_pause.emit)
        keyboard.add_hotkey(cfg["volume_up"], bridge.vol_up.emit)
        keyboard.add_hotkey(cfg["volume_down"], bridge.vol_down.emit)
        keyboard.add_hotkey(cfg["quit_app"], bridge.quit_app.emit)
    except Exception as e:
        try:
            print("hotkeys err:", e)
        except Exception:
            pass

    if cfg.get("media_keys_enabled", True):
        for key, sig in (("play/pause", bridge.play_pause),
                         ("next track", bridge.next),
                         ("previous track", bridge.prev)):
            try:
                keyboard.add_hotkey(key, sig.emit)
            except Exception as e:
                try:
                    print(f"media key {key} err:", e)
                except Exception:
                    pass

# ---------------------------------------------------------------- tray icon
def make_tray_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(58, 58, 64, 255))
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, 64, 64)
    p.setBrush(QColor(255, 255, 255, 255))
    p.drawEllipse(14, 40, 14, 11)
    p.drawEllipse(34, 34, 14, 11)
    p.drawRect(26, 20, 3, 26)
    p.drawRect(46, 14, 3, 26)
    p.drawRect(26, 18, 23, 4)
    p.end()
    try:
        pm.save(str(ASSETS_DIR / "tray_icon.png"), "PNG")
    except Exception:
        pass
    return QIcon(pm)

# ---------------------------------------------------------------- main
def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    cfg = load_config()

    player = MusicPlayer()
    player.set_playlist(cfg["tracks"])
    player.set_volume(cfg["volume"])

    overlay = Overlay(player, cfg)
    overlay.animate_in()

    try:
        set_click_through(int(overlay.winId()), False)
    except Exception as e:
        try:
            print("click_through err:", e)
        except Exception:
            pass

    bridge = HotkeyBridge()

    def toggle_overlay_animated():
        if overlay.isVisible() and overlay.windowOpacity() > 0.5:
            overlay.animate_out()
        else:
            overlay.animate_in()

    bridge.toggle_overlay.connect(toggle_overlay_animated)
    bridge.toggle_click.connect(lambda: toggle_click_through(overlay))
    bridge.prev.connect(player.prev)
    bridge.next.connect(player.next)
    bridge.next_in_order.connect(player.next_in_order)
    bridge.play_pause.connect(player.play_pause)
    bridge.vol_up.connect(lambda: change_vol(player, overlay, +5))
    bridge.vol_down.connect(lambda: change_vol(player, overlay, -5))
    bridge.quit_app.connect(QApplication.quit)

    register_hotkeys(cfg, bridge)

    tray = QSystemTrayIcon(make_tray_icon(), overlay)
    tray.setToolTip("Music Overlay")

    tray_menu = QMenu()

    a_toggle = QAction("Показать / Скрыть", overlay)
    a_toggle.triggered.connect(toggle_overlay_animated)

    a_add = QAction("Добавить файлы…", overlay)
    a_add.triggered.connect(overlay.add_files)

    a_url = QAction("Добавить ссылку (YouTube, SoundCloud)…", overlay)
    a_url.triggered.connect(overlay.add_url)

    a_vk = QAction("Добавить из VK…", overlay)
    a_vk.triggered.connect(overlay.add_vk_playlist)

    a_playlist = QAction("Плейлист", overlay)
    a_playlist.triggered.connect(overlay.toggle_playlist)

    a_settings = QAction("Настройки…", overlay)

    def open_settings():
        dlg = SettingsDialog(cfg, overlay)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply_to(cfg)
            save_config(cfg)
            overlay.setWindowOpacity(cfg["opacity"])
            register_hotkeys(cfg, bridge)

    a_settings.triggered.connect(open_settings)

    a_quit = QAction("Выход", overlay)
    a_quit.triggered.connect(QApplication.quit)

    tray_menu.addAction(a_toggle)
    tray_menu.addSeparator()
    tray_menu.addAction(a_add)
    tray_menu.addAction(a_url)
    tray_menu.addAction(a_vk)
    tray_menu.addAction(a_playlist)
    tray_menu.addSeparator()
    tray_menu.addAction(a_settings)
    tray_menu.addSeparator()
    tray_menu.addAction(a_quit)
    tray.setContextMenu(tray_menu)

    def on_tray_activated(reason):
        if reason == QSystemTrayIcon.Trigger:
            toggle_overlay_animated()

    tray.activated.connect(on_tray_activated)
    tray.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()

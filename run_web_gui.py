"""
PositionAnalyzer - Raw Input Mouse Tracker
==========================================
Uses Windows Raw Input API to capture actual hardware mickeys from any mouse.
Runs at the mouse's native polling rate (typically 125-1000 Hz).

NOTE ON POLLING RATE:
Windows WM_INPUT messages may be coalesced if the application can't keep up,
but each message contains the CUMULATIVE delta since the last message.
This means no position data is lost - only timestamp granularity.
For mouse tracking purposes, this is perfectly acceptable.
"""
import csv
import time
import requests
import json
import subprocess
import tkinter as tk
from tkinter import messagebox
from pynput import keyboard
import threading
import sys
import os
import ctypes
from ctypes import wintypes, Structure, POINTER, byref, sizeof


def get_app_base_dir():
    """Return the user-visible app directory for source and packaged runs."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_user_data_dir():
    """Return a writable per-user directory for local runner files."""
    base_dir = os.environ.get('LOCALAPPDATA')
    if not base_dir:
        base_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Local')

    user_data_dir = os.path.join(base_dir, 'PositionAnalyzer')
    os.makedirs(user_data_dir, exist_ok=True)
    return user_data_dir


def get_user_data_config_path():
    """Return the shared per-user config path."""
    return os.path.join(get_user_data_dir(), 'positionanalyzer_config.txt')


def get_install_info_path():
    """Return the packaged install registration path."""
    return os.path.join(get_user_data_dir(), 'runner_install.json')


def get_config_paths():
    """Return possible config file locations in priority order."""
    return [
        get_user_data_config_path(),
        os.path.join(get_app_base_dir(), 'positionanalyzer_config.txt'),
        os.path.join(os.path.expanduser('~'), '.positionanalyzer_config.txt'),
    ]


def load_local_config():
    """Load local config, supporting both legacy text and JSON formats."""
    for path in get_config_paths():
        if not os.path.exists(path):
            continue

        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = f.read().strip()
        except OSError:
            continue

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None

        if isinstance(data, dict):
            return normalize_local_config(data)

        return normalize_local_config({'username': raw})

    return normalize_local_config({})


def persist_local_config(config_data):
    """Persist config to the shared per-user location for future launches."""
    config_path = get_user_data_config_path()
    normalized = normalize_local_config(config_data)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(normalized, f, indent=2)


def register_packaged_installation():
    """Record the packaged executable path for future one-click launches."""
    if not getattr(sys, 'frozen', False):
        return False

    exe_path = os.path.abspath(sys.executable)
    install_info = {
        'exe_path': exe_path,
        'app_dir': os.path.dirname(exe_path),
        'registered_at': int(time.time()),
    }

    try:
        with open(get_install_info_path(), 'w', encoding='utf-8') as f:
            json.dump(install_info, f, indent=2)
        return True
    except OSError as exc:
        print(f"⚠️ Could not register packaged install path: {exc}")
        return False


def sync_local_config():
    """Copy any discovered config into the shared per-user location."""
    config = load_local_config()
    if not config:
        return

    try:
        persist_local_config(config)
    except OSError as exc:
        print(f"⚠️ Could not sync local config: {exc}")


def is_first_packaged_launch():
    """Return True when the packaged app has not registered itself yet."""
    return getattr(sys, 'frozen', False) and not os.path.exists(get_install_info_path())

# =============================================================================
# CONFIGURATION
# =============================================================================
RATIO = 31.50  # Default mickeys/mm, updated from user's calibration
DATA_FILE = "position_data.csv"
WEB_SERVER_URL = "http://localhost:5000"
MIN_SESSION_SECONDS = 300  # 5 minutes
MAX_SESSION_TIME = 28800  # 8 hours

# Lift detection thresholds
LIFT_DETECT_MIN = 0.240  # 240ms - minimum gap to consider a lift
LIFT_DETECT_MAX = 0.350  # 350ms - maximum gap to consider a lift
AFK_TIMEOUT = 180.0  # 3 minutes of no movement = auto-stop session
MIN_AFK_TIMEOUT = 15
MAX_AFK_TIMEOUT = 600

WINDOW_WIDTH = 420
WINDOW_HEIGHT = 320
DEFAULT_WINDOW_X = 50
DEFAULT_WINDOW_Y = 360
STARTUP_SHORTCUT_NAME = "PositionAnalyzer.lnk"

# Active Aiming Zone (AAZ) - adaptive model of where the user actually aims.
# If position drifts far outside the AAZ and any brief pause occurs,
# we assume a liftoff happened and snap back to AAZ center.
AAZ_INIT_RADIUS_X  = 80.0   # initial half-width of AAZ (mm)
AAZ_INIT_RADIUS_Y  = 60.0   # initial half-height of AAZ (mm)
AAZ_WARMUP_SECS    = 8.0    # seconds before AAZ liftoff detection activates
AAZ_LEARN_RATE     = 0.004  # how fast AAZ center drifts toward in-zone positions
AAZ_LIFTOFF_MULT   = 2.2    # normalised radii away before we suspect a liftoff
AAZ_LIFT_GAP       = 0.060  # 60ms pause while far outside AAZ triggers liftoff
AAZ_GROW_THRESHOLD = 0.25   # if >25% of recent samples are outside, grow AAZ
AAZ_GROW_RATE      = 1.008  # multiply radius by this each growth tick
AAZ_GROW_MAX_X     = 200.0  # AAZ half-width growth cap (mm)
AAZ_GROW_MAX_Y     = 150.0  # AAZ half-height growth cap (mm)
AAZ_OUTSIDE_WINDOW = 80     # rolling window size for outside-ratio check

# Boundary expansion for reset detection (invisible border larger than visual)
RESET_BOUNDARY_EXPANSION = 0.0775  # 7.75%

# Velocity sanity check: filter impossible speeds (sensor glitches)
MAX_VELOCITY_MM_SEC = 15000  # 15 m/sec - faster than any human

# Runner UI palette
RUNNER_BG = "#0E0E0E"
RUNNER_PRIMARY = "#FFB347"
RUNNER_MUTED = "#888888"
RUNNER_DANGER = "#F97316"
RUNNER_FONT_FAMILY = ('IBM Plex Mono', 'monospace')


def get_default_runner_settings():
    """Return the default user-configurable runner settings."""
    return {
        'launch_on_startup': False,
        'always_on_top': False,
        'remember_window_position': True,
        'afk_timeout_seconds': int(AFK_TIMEOUT),
        'show_notifications': True,
        'show_upload_result': True,
        'auto_login_web_account': True,
    }


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {'1', 'true', 'yes', 'on'}:
            return True
        if lowered in {'0', 'false', 'no', 'off'}:
            return False
    if value is None:
        return default
    return bool(value)


def _coerce_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_local_config(config_data):
    """Return a normalized config with default settings applied."""
    normalized = dict(config_data) if isinstance(config_data, dict) else {}

    username = normalized.get('username')
    if isinstance(username, str):
        username = username.strip()
    if username:
        normalized['username'] = username
    else:
        normalized.pop('username', None)

    session_token = normalized.get('session_token') or normalized.get('token')
    if isinstance(session_token, str):
        session_token = session_token.strip()
    if session_token:
        normalized['session_token'] = session_token
    else:
        normalized.pop('session_token', None)
    normalized.pop('token', None)

    settings = get_default_runner_settings()
    raw_settings = normalized.get('settings')
    if isinstance(raw_settings, dict):
        for key in ('launch_on_startup', 'always_on_top', 'remember_window_position', 'show_notifications', 'show_upload_result'):
            if key in raw_settings:
                settings[key] = _coerce_bool(raw_settings.get(key), settings[key])
        afk_timeout = _coerce_int(raw_settings.get('afk_timeout_seconds'), settings['afk_timeout_seconds'])
        if afk_timeout is None:
            afk_timeout = settings['afk_timeout_seconds']
        settings['afk_timeout_seconds'] = max(MIN_AFK_TIMEOUT, min(MAX_AFK_TIMEOUT, afk_timeout))

    normalized['settings'] = settings

    for key in ('window_x', 'window_y'):
        value = _coerce_int(normalized.get(key), None)
        if value is None:
            normalized.pop(key, None)
        else:
            normalized[key] = value

    return normalized


def update_local_config(top_level_updates=None, settings_updates=None, remove_keys=None):
    """Merge updates into the local config and persist the result."""
    config = load_local_config()

    if top_level_updates:
        for key, value in top_level_updates.items():
            if value is None:
                config.pop(key, None)
            else:
                config[key] = value

    if settings_updates:
        settings = dict(config.get('settings') or get_default_runner_settings())
        settings.update(settings_updates)
        config['settings'] = settings

    if remove_keys:
        for key in remove_keys:
            config.pop(key, None)

    persist_local_config(config)
    return load_local_config()


def clear_stored_session_token():
    """Clear the locally stored runner auth token while preserving settings."""
    return update_local_config(top_level_updates={'session_token': None})


def get_startup_dir():
    """Return the current user's Windows Startup folder."""
    base_dir = os.environ.get('APPDATA')
    if not base_dir:
        base_dir = os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
    return os.path.join(base_dir, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')


def get_startup_shortcut_path():
    """Return the path for the runner startup shortcut."""
    return os.path.join(get_startup_dir(), STARTUP_SHORTCUT_NAME)


def _ps_quote(value):
    return str(value).replace("'", "''")


def get_runner_launch_target_and_args():
    """Return the target, arguments, and working directory for startup launch."""
    if getattr(sys, 'frozen', False):
        exe_path = os.path.abspath(sys.executable)
        return exe_path, '', os.path.dirname(exe_path)

    script_path = os.path.abspath(__file__)
    python_exe = os.path.abspath(sys.executable)
    return python_exe, f'"{script_path}"', os.path.dirname(script_path)


def is_startup_enabled():
    """Return True when the Startup folder shortcut currently exists."""
    return os.path.exists(get_startup_shortcut_path())


def set_startup_enabled(enabled):
    """Create or remove the per-user Startup folder shortcut."""
    shortcut_path = get_startup_shortcut_path()
    if not enabled:
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)
        return

    os.makedirs(get_startup_dir(), exist_ok=True)
    target_path, arguments, working_directory = get_runner_launch_target_and_args()
    ps_script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut('{_ps_quote(shortcut_path)}'); "
        f"$shortcut.TargetPath = '{_ps_quote(target_path)}'; "
        f"$shortcut.Arguments = '{_ps_quote(arguments)}'; "
        f"$shortcut.WorkingDirectory = '{_ps_quote(working_directory)}'; "
        f"$shortcut.IconLocation = '{_ps_quote(target_path)},0'; "
        "$shortcut.Save()"
    )
    subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
        check=True,
        capture_output=True,
        text=True,
    )


def fetch_runner_bootstrap(username, session_token, timeout=5):
    """Fetch bootstrap data and surface explicit auth expiry separately."""
    if not session_token:
        return {'success': False, 'auth_invalid': True, 'error': 'Session token required'}

    try:
        resp = requests.post(
            f"{WEB_SERVER_URL}/api/client_bootstrap",
            json={'session_token': session_token, 'username': username},
            timeout=timeout,
        )
    except Exception as exc:
        return {'success': False, 'auth_invalid': False, 'error': str(exc)}

    try:
        data = resp.json()
    except Exception:
        data = {}

    if resp.status_code == 200 and data.get('success'):
        return {'success': True, 'auth_invalid': False, 'data': data}

    return {
        'success': False,
        'auth_invalid': resp.status_code == 401,
        'error': data.get('error') or f'Bootstrap failed ({resp.status_code})',
    }


def revoke_remote_session_token(session_token, timeout=5):
    """Best-effort revocation of the current runner token on manual logout."""
    if not session_token:
        return False

    try:
        resp = requests.post(
            f"{WEB_SERVER_URL}/api/client_logout",
            json={'session_token': session_token},
            timeout=timeout,
        )
        return resp.status_code == 200
    except Exception:
        return False

# =============================================================================
# WINDOWS RAW INPUT API
# =============================================================================
WM_INPUT = 0x00FF
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003


class RAWINPUTDEVICE(Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWMOUSE(Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("_padding1", wintypes.USHORT),
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


class RAWINPUTHEADER(Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWINPUT(Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("mouse", RAWMOUSE),
    ]


# Proper LRESULT type for 64-bit Windows
LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HANDLE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HANDLE),
    ]


# Windows API handles
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Configure DefWindowProcW for 64-bit
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

# Thread priority
THREAD_PRIORITY_TIME_CRITICAL = 15


# =============================================================================
# MAIN APPLICATION
# =============================================================================
class MouseTrackerGUI:
    def __init__(self, username, token=None, bootstrap_data=None):
        self.username = username
        self.session_token = token
        self.bootstrap_data = bootstrap_data if isinstance(bootstrap_data, dict) else None
        self.local_config = load_local_config()
        self.settings = dict(self.local_config.get('settings') or get_default_runner_settings())
        self.bring_to_front_on_launch = bool(self.local_config.get('bring_to_front_on_launch'))
        self.settings['launch_on_startup'] = is_startup_enabled()
        self.afk_timeout_seconds = int(self.settings.get('afk_timeout_seconds', int(AFK_TIMEOUT)))
        self.recording = False
        self.closing = False
        self.data_points = []
        self.start_time = 0
        self.window_hidden = False
        self.settings_window = None
        self.toast_window = None
        self.toast_after_id = None
        self.logout_message = ''
        
        # Position tracking (center of mousepad)
        self.center_x = 500.0
        self.center_y = 500.0
        self.current_x_mm = 500.0
        self.current_y_mm = 500.0
        
        # Mousepad dimensions (defaults, updated from user data)
        self.mousepad_width_mm = 450.0
        self.mousepad_height_mm = 400.0
        
        # Statistics
        self.raw_input_running = False
        self.event_count = 0
        self.total_mickeys = 0
        self.glitch_count = 0
        self.last_event_time = 0
        self.last_movement_time = 0

        # Click state (0=none, 1=left, 2=right)
        self.button_state = 0
        
        # Rate tracking
        self.last_rate_time = 0
        self.last_rate_count = 0

        # Logout flag
        self.logged_out = False
        self._auto_stopped_reason = None

        # Active Aiming Zone (AAZ) state - reset in start_recording()
        self.aaz_cx = self.center_x
        self.aaz_cy = self.center_y
        self.aaz_rx = AAZ_INIT_RADIUS_X
        self.aaz_ry = AAZ_INIT_RADIUS_Y
        self._aaz_recent = []   # rolling list of bools: True = outside AAZ
        
        # Fetch user data from server
        self.fetch_user_calibration()
        self.fetch_user_mousepad()
        self.setup_mousepad_bounds()
        
        # Setup GUI
        self.setup_gui()
        self._apply_initial_launch_focus()
        
        # Setup keyboard hotkeys
        self.setup_keyboard()
        
        # Start raw input capture thread
        self.start_raw_input()

    # -------------------------------------------------------------------------
    # User Data Fetching
    # -------------------------------------------------------------------------
    def _fetch_bootstrap_data(self):
        """Fetch calibration and mousepad bootstrap data from the web server."""
        if isinstance(self.bootstrap_data, dict) and self.bootstrap_data.get('success'):
            return self.bootstrap_data

        if not self.session_token:
            print("⚠️ No session token available for runner bootstrap")
            return None

        try:
            resp = requests.post(
                f"{WEB_SERVER_URL}/api/client_bootstrap",
                json={
                    'session_token': self.session_token,
                    'username': self.username,
                },
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    self.bootstrap_data = data
                    return data

            error = None
            try:
                error = resp.json().get('error')
            except Exception:
                error = None
            print(f"⚠️ Could not fetch runner bootstrap data: {error or resp.status_code}")
        except Exception as e:
            print(f"⚠️ Could not fetch runner bootstrap data: {e}")

        return None

    def fetch_user_calibration(self):
        """Fetch calibration from web server."""
        global RATIO
        bootstrap = self._fetch_bootstrap_data()
        try:
            calibration = (bootstrap or {}).get('calibration') or {}
            if calibration.get('available') and calibration.get('mickeys_per_mm'):
                    RATIO = calibration['mickeys_per_mm']
                    print(f"📊 Calibration loaded: {RATIO:.2f} mickeys/mm")
                    return
            print(f"📊 No calibration found, using default: {RATIO} mickeys/mm")
        except Exception as e:
            print(f"⚠️ Could not fetch calibration: {e}")

    def fetch_user_mousepad(self):
        """Fetch mousepad dimensions from web server."""
        bootstrap = self._fetch_bootstrap_data()
        try:
            mousepad = (bootstrap or {}).get('mousepad') or {}
            if mousepad.get('available'):
                    w_mm = mousepad.get('width_mm')
                    h_mm = mousepad.get('height_mm')
                    if w_mm and h_mm:
                        self.mousepad_width_mm = float(w_mm)
                        self.mousepad_height_mm = float(h_mm)
                        raw = mousepad.get('raw', '')
                        label = 'Desktop' if raw.lower().strip() == 'desktop' else f"{self.mousepad_width_mm:.0f}x{self.mousepad_height_mm:.0f}mm"
                        print(f"🖱️ Mousepad: {label}")
                        return
            print(f"🖱️ Using default mousepad: 450x400mm")
        except Exception as e:
            print(f"⚠️ Could not fetch mousepad: {e}")

    # -------------------------------------------------------------------------
    # GUI Setup
    # -------------------------------------------------------------------------
    def setup_gui(self):
        """Create the main GUI window."""
        self.root = tk.Tk()
        self.root.title("PositionAnalyzer")
        self.root.geometry(self._get_initial_geometry())
        self.root.resizable(False, False)
        self.root.attributes('-topmost', bool(self.settings.get('always_on_top')))
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.configure(bg=RUNNER_BG)

        shell = tk.Frame(self.root, bg=RUNNER_BG, padx=18, pady=18)
        shell.pack(fill=tk.BOTH, expand=True)
        shell.grid_columnconfigure(0, weight=1)

        top_button_style = {
            'font': (RUNNER_FONT_FAMILY, 11),
            'fg': RUNNER_MUTED,
            'bg': RUNNER_BG,
            'activeforeground': RUNNER_MUTED,
            'activebackground': RUNNER_BG,
            'relief': 'flat',
            'bd': 0,
            'highlightthickness': 0,
            'cursor': 'hand2',
            'padx': 4,
            'pady': 0,
        }

        top_actions = tk.Frame(shell, bg=RUNNER_BG)
        top_actions.grid(row=0, column=0)

        self.settings_btn = tk.Button(
            top_actions,
            text="Settings",
            command=self.open_settings_window,
            **top_button_style,
        )
        self.settings_btn.pack(side=tk.LEFT, padx=(0, 16))

        self.logout_btn = tk.Button(
            top_actions,
            text="Logout",
            command=self.do_logout,
            **top_button_style,
        )
        self.logout_btn.pack(side=tk.LEFT)

        self.user_label = tk.Label(
            shell,
            text=f"User: {self.username}",
            font=(RUNNER_FONT_FAMILY, 12),
            fg=RUNNER_MUTED,
            bg=RUNNER_BG,
            anchor="w",
        )
        self.user_label.grid(row=1, column=0, sticky="ew", pady=(16, 10))

        self.time_label = tk.Label(
            shell,
            font=(RUNNER_FONT_FAMILY, 12),
            fg=RUNNER_MUTED,
            bg=RUNNER_BG,
            anchor="w",
        )
        self.time_label.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        self.event_label = tk.Label(
            shell,
            font=(RUNNER_FONT_FAMILY, 12),
            fg=RUNNER_MUTED,
            bg=RUNNER_BG,
            anchor="w",
        )
        self.event_label.grid(row=3, column=0, sticky="ew")

        self.min_label = tk.Label(
            shell,
            text="Session lengths must be 5 minutes to 8 hours",
            font=(RUNNER_FONT_FAMILY, 11),
            fg=RUNNER_PRIMARY,
            bg=RUNNER_BG,
        )
        self.min_label.grid(row=4, column=0, pady=(24, 8))

        btn_frame = tk.Frame(shell, bg=RUNNER_BG)
        btn_frame.grid(row=5, column=0, sticky="ew", pady=(0, 12))
        btn_frame.grid_columnconfigure(0, weight=1)

        action_button_style = {
            'font': (RUNNER_FONT_FAMILY, 22, "bold"),
            'fg': RUNNER_PRIMARY,
            'bg': RUNNER_BG,
            'activeforeground': RUNNER_PRIMARY,
            'activebackground': RUNNER_BG,
            'relief': 'flat',
            'bd': 0,
            'highlightthickness': 0,
            'cursor': 'hand2',
            'padx': 0,
            'pady': 8,
        }

        self.start_btn = tk.Button(
            btn_frame,
            text="Start / F8",
            command=self.toggle_recording,
            **action_button_style,
        )
        self.start_btn.grid(row=0, column=0, sticky="ew")

        self._apply_runner_idle_state(0.0)

    def _format_duration_label(self, elapsed_seconds=0.0):
        """Return the session duration label in the runner UI format."""
        elapsed_seconds = max(0.0, float(elapsed_seconds or 0.0))
        mins = int(elapsed_seconds // 60)
        secs = int(elapsed_seconds % 60)
        return f"Session Duration - {mins:02d}:{secs:02d}"

    def _format_event_label(self):
        """Return the event counter label in the runner UI format."""
        return f"Events / Non-Zeros - {self.event_count}"

    def _apply_runner_idle_state(self, elapsed_seconds=0.0):
        """Update the runner UI for the non-recording state."""
        self.time_label.config(text="Session Duration - Off")
        self.event_label.config(text="Events / Non-Zeros - Off")
        self.start_btn.config(text="Start / F8")

    def _apply_runner_recording_state(self, elapsed_seconds=0.0):
        """Update the runner UI for the recording state."""
        self.time_label.config(text=self._format_duration_label(elapsed_seconds))
        self.event_label.config(text=self._format_event_label())
        self.start_btn.config(text="Stop / F8")

    def _get_initial_geometry(self):
        """Return the runner geometry string using any saved position."""
        x = DEFAULT_WINDOW_X
        y = DEFAULT_WINDOW_Y
        if self.settings.get('remember_window_position'):
            x = _coerce_int(self.local_config.get('window_x'), x)
            y = _coerce_int(self.local_config.get('window_y'), y)
        return f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}"

    def _close_settings_window(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.settings_window = None

    def _show_toast(self, message, *, is_error=False, duration_ms=1500):
        """Show a centered, topmost, non-modal toast message."""
        if not getattr(self, 'root', None) or not self.root.winfo_exists():
            return

        if self.toast_window and self.toast_window.winfo_exists():
            try:
                self.toast_window.destroy()
            except Exception:
                pass
            self.toast_window = None

        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes('-topmost', True)
        toast.configure(bg=RUNNER_DANGER if is_error else RUNNER_PRIMARY)

        outer = tk.Frame(toast, bg=RUNNER_DANGER if is_error else RUNNER_PRIMARY, padx=1, pady=1)
        outer.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(outer, bg=RUNNER_BG, padx=24, pady=16)
        inner.pack(fill=tk.BOTH, expand=True)

        label = tk.Label(
            inner,
            text=message,
            font=(RUNNER_FONT_FAMILY, 13, 'bold'),
            fg=RUNNER_DANGER if is_error else RUNNER_PRIMARY,
            bg=RUNNER_BG,
        )
        label.pack()

        toast.update_idletasks()
        width = toast.winfo_width()
        height = toast.winfo_height()
        x = max(0, (toast.winfo_screenwidth() - width) // 2)
        y = max(0, (toast.winfo_screenheight() - height) // 2)
        toast.geometry(f"{width}x{height}+{x}+{y}")

        self.toast_window = toast
        toast.after(duration_ms, lambda: self._dismiss_toast(toast))

    def _dismiss_toast(self, toast):
        if toast and toast.winfo_exists():
            toast.destroy()
        if self.toast_window is toast:
            self.toast_window = None

    def _persist_window_position(self):
        """Persist the current window position when enabled."""
        if not getattr(self, 'root', None) or not self.root.winfo_exists():
            return

        if self.settings.get('remember_window_position'):
            self.root.update_idletasks()
            self.local_config = update_local_config(
                top_level_updates={
                    'window_x': self.root.winfo_x(),
                    'window_y': self.root.winfo_y(),
                }
            )
        else:
            self.local_config = update_local_config(remove_keys=['window_x', 'window_y'])

    def _apply_topmost_setting(self):
        if getattr(self, 'root', None) and self.root.winfo_exists() and not self.window_hidden:
            self.root.attributes('-topmost', bool(self.settings.get('always_on_top')))

    def _apply_initial_launch_focus(self):
        if not self.bring_to_front_on_launch:
            return

        self.bring_to_front_on_launch = False
        self.local_config = update_local_config(top_level_updates={'bring_to_front_on_launch': None})

        def focus_window_once():
            if not getattr(self, 'root', None) or not self.root.winfo_exists() or self.window_hidden:
                return
            self.root.deiconify()
            self.root.attributes('-topmost', True)
            self.root.lift()
            try:
                self.root.focus_force()
            except tk.TclError:
                pass
            self.root.after(250, self._apply_topmost_setting)

        self.root.after(120, focus_window_once)

    def open_settings_window(self):
        """Open the local runner settings window."""
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return

        window = tk.Toplevel(self.root)
        window.title('PositionAnalyzer - Settings')
        window.resizable(False, False)
        window.configure(bg=RUNNER_BG)
        window.minsize(372, 0)
        window.transient(self.root)
        window.protocol('WM_DELETE_WINDOW', self._close_settings_window)
        window.grab_set()
        self.settings_window = window

        shell = tk.Frame(window, bg=RUNNER_BG, padx=18, pady=18)
        shell.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            shell,
            text='Software Settings / Not Account Specific',
            font=(RUNNER_FONT_FAMILY, 12),
            fg=RUNNER_PRIMARY,
            bg=RUNNER_BG,
            anchor='w',
        ).pack(fill=tk.X)

        launch_var = tk.BooleanVar(value=bool(self.settings.get('launch_on_startup')))
        topmost_var = tk.BooleanVar(value=bool(self.settings.get('always_on_top')))
        remember_pos_var = tk.BooleanVar(value=bool(self.settings.get('remember_window_position')))
        afk_var = tk.StringVar(value=str(int(self.settings.get('afk_timeout_seconds', int(AFK_TIMEOUT)))))
        notify_var = tk.BooleanVar(value=bool(self.settings.get('show_notifications')))
        upload_var = tk.BooleanVar(value=bool(self.settings.get('show_upload_result')))
        auto_login_var = tk.BooleanVar(value=bool(self.settings.get('auto_login_web_account', True)))
        status_var = tk.StringVar(value='')

        def add_toggle(text, variable):
            row = tk.Frame(shell, bg=RUNNER_BG)
            row.pack(fill=tk.X, pady=(12, 0))
            toggle = tk.Frame(row, bg=RUNNER_BG)
            toggle.pack(anchor='w')

            indicator = tk.Frame(
                toggle,
                width=16,
                height=16,
                bg=RUNNER_BG,
                highlightthickness=1,
                highlightbackground=RUNNER_PRIMARY,
                highlightcolor=RUNNER_PRIMARY,
                bd=0,
                cursor='hand2',
            )
            indicator.pack(side=tk.LEFT, padx=(0, 10), pady=2)
            indicator.pack_propagate(False)

            label = tk.Label(
                toggle,
                text=text,
                font=(RUNNER_FONT_FAMILY, 11),
                fg=RUNNER_PRIMARY,
                bg=RUNNER_BG,
                anchor='w',
            )
            label.pack(side=tk.LEFT)

            def toggle_value(_event=None):
                variable.set(not bool(variable.get()))

            def sync_toggle(*_args):
                is_selected = bool(variable.get())
                indicator.configure(bg=RUNNER_DANGER if is_selected else RUNNER_BG)

            indicator.bind('<Button-1>', toggle_value)

            variable.trace_add('write', sync_toggle)
            sync_toggle()

        add_toggle('Launch on Windows startup', launch_var)
        add_toggle('Always on top', topmost_var)
        add_toggle('Remember window position', remember_pos_var)
        add_toggle('Show start / stop notifications', notify_var)
        add_toggle('Show upload result', upload_var)
        add_toggle('Always stay logged in with website account', auto_login_var)

        afk_row = tk.Frame(shell, bg=RUNNER_BG)
        afk_row.pack(fill=tk.X, pady=(12, 0))
        tk.Label(
            afk_row,
            text='AFK auto-step / seconds',
            font=(RUNNER_FONT_FAMILY, 11),
            fg=RUNNER_PRIMARY,
            bg=RUNNER_BG,
            anchor='w',
        ).pack(fill=tk.X)
        tk.Entry(
            afk_row,
            textvariable=afk_var,
            font=(RUNNER_FONT_FAMILY, 11),
            fg=RUNNER_PRIMARY,
            bg=RUNNER_BG,
            insertbackground=RUNNER_PRIMARY,
            highlightthickness=0,
            relief='flat',
            width=8,
        ).pack(anchor='w', pady=(6, 0))

        afk_error_label = tk.Label(
            afk_row,
            text='Auto-stop must be set to 10 - 600 seconds',
            font=(RUNNER_FONT_FAMILY, 10),
            fg=RUNNER_DANGER,
            bg=RUNNER_BG,
            anchor='w',
        )

        status_label = tk.Label(
            shell,
            textvariable=status_var,
            font=(RUNNER_FONT_FAMILY, 10),
            fg=RUNNER_DANGER,
            bg=RUNNER_BG,
            anchor='w',
        )
        status_label.pack(fill=tk.X, pady=(14, 0))

        btn_row = tk.Frame(shell, bg=RUNNER_BG)
        btn_row.pack(fill=tk.X, pady=(16, 0))

        actions_hidden_for_afk_error = False

        def show_action_buttons():
            nonlocal actions_hidden_for_afk_error
            if not actions_hidden_for_afk_error:
                return
            btn_row.pack(fill=tk.X, pady=(16, 0))
            actions_hidden_for_afk_error = False

        def hide_action_buttons():
            nonlocal actions_hidden_for_afk_error
            if actions_hidden_for_afk_error:
                return
            btn_row.pack_forget()
            actions_hidden_for_afk_error = True

        def update_afk_validation_state(hide_actions=False):
            afk_timeout = _coerce_int(afk_var.get(), None)
            is_valid = afk_timeout is not None and MIN_AFK_TIMEOUT <= afk_timeout <= MAX_AFK_TIMEOUT

            if afk_var.get().strip() and not is_valid:
                afk_error_label.pack(anchor='w', pady=(6, 0))
                if hide_actions:
                    hide_action_buttons()
            else:
                afk_error_label.pack_forget()
                show_action_buttons()

            return is_valid

        afk_var.trace_add('write', lambda *_args: update_afk_validation_state())

        def reset_defaults():
            defaults = get_default_runner_settings()
            launch_var.set(defaults['launch_on_startup'])
            topmost_var.set(defaults['always_on_top'])
            remember_pos_var.set(defaults['remember_window_position'])
            afk_var.set(str(defaults['afk_timeout_seconds']))
            notify_var.set(defaults['show_notifications'])
            upload_var.set(defaults['show_upload_result'])
            auto_login_var.set(defaults['auto_login_web_account'])
            show_action_buttons()
            afk_error_label.pack_forget()
            status_var.set('')

        def save_settings():
            afk_timeout = _coerce_int(afk_var.get(), None)
            if not update_afk_validation_state(hide_actions=True):
                status_var.set('')
                return

            show_action_buttons()
            afk_error_label.pack_forget()

            new_settings = {
                'launch_on_startup': bool(launch_var.get()),
                'always_on_top': bool(topmost_var.get()),
                'remember_window_position': bool(remember_pos_var.get()),
                'afk_timeout_seconds': afk_timeout,
                'show_notifications': bool(notify_var.get()),
                'show_upload_result': bool(upload_var.get()),
                'auto_login_web_account': bool(auto_login_var.get()),
            }

            try:
                set_startup_enabled(new_settings['launch_on_startup'])
            except Exception as exc:
                status_var.set(f'Could not update startup entry: {exc}')
                return

            remove_keys = []
            top_level_updates = {}
            if new_settings['remember_window_position']:
                self.root.update_idletasks()
                top_level_updates = {
                    'window_x': self.root.winfo_x(),
                    'window_y': self.root.winfo_y(),
                }
            else:
                remove_keys.extend(['window_x', 'window_y'])

            self.local_config = update_local_config(
                top_level_updates=top_level_updates,
                settings_updates=new_settings,
                remove_keys=remove_keys,
            )

            self.settings = dict(self.local_config.get('settings') or get_default_runner_settings())
            self.settings['launch_on_startup'] = is_startup_enabled()
            self.afk_timeout_seconds = int(self.settings.get('afk_timeout_seconds', int(AFK_TIMEOUT)))
            self._apply_topmost_setting()
            self._close_settings_window()

        button_style = {
            'font': (RUNNER_FONT_FAMILY, 11),
            'fg': RUNNER_MUTED,
            'bg': RUNNER_BG,
            'activeforeground': RUNNER_PRIMARY,
            'activebackground': RUNNER_BG,
            'relief': 'flat',
            'bd': 0,
            'highlightthickness': 0,
            'cursor': 'hand2',
        }

        tk.Button(btn_row, text='Save', command=save_settings, **button_style).pack(side=tk.LEFT)
        tk.Button(btn_row, text='Reset to Defaults', command=reset_defaults, **button_style).pack(side=tk.LEFT, padx=(16, 0))
        tk.Button(btn_row, text='Cancel', command=self._close_settings_window, **button_style).pack(side=tk.RIGHT)

        update_afk_validation_state()

        window.update_idletasks()
        width = max(372, window.winfo_width())
        height = window.winfo_height()
        x = max(0, self.root.winfo_x() + (self.root.winfo_width() - width) // 2)
        y = max(0, self.root.winfo_y() + (self.root.winfo_height() - height) // 2)
        window.geometry(f'{width}x{height}+{x}+{y}')

    def setup_mousepad_bounds(self):
        """Compute mousepad/reset bounds for reset detection."""
        # Calculate boundaries
        hw, hh = self.mousepad_width_mm / 2, self.mousepad_height_mm / 2

        # Visual bounds
        self.pad_left = self.center_x - hw
        self.pad_right = self.center_x + hw
        self.pad_bottom = self.center_y - hh
        self.pad_top = self.center_y + hh

        # Reset bounds (expanded)
        exp_hw = hw * (1 + RESET_BOUNDARY_EXPANSION)
        exp_hh = hh * (1 + RESET_BOUNDARY_EXPANSION)
        self.reset_left = self.center_x - exp_hw
        self.reset_right = self.center_x + exp_hw
        self.reset_bottom = self.center_y - exp_hh
        self.reset_top = self.center_y + exp_hh

    def setup_keyboard(self):
        """Setup global hotkeys."""
        self.kb_listener = keyboard.GlobalHotKeys({
            '<f8>': self.toggle_recording,
            '<f12>': self.toggle_visibility
        })
        self.kb_listener.start()

    # -------------------------------------------------------------------------
    # Raw Input Thread
    # -------------------------------------------------------------------------
    def start_raw_input(self):
        """Start the raw input capture thread."""
        self.raw_input_running = True
        self.raw_thread = threading.Thread(target=self._raw_input_loop, daemon=True)
        self.raw_thread.start()

    def _raw_input_loop(self):
        """Background thread that captures raw mouse input."""
        try:
            # Elevate thread priority for low latency
            handle = kernel32.GetCurrentThread()
            if kernel32.SetThreadPriority(handle, THREAD_PRIORITY_TIME_CRITICAL):
                print("✅ Thread priority: TIME_CRITICAL")
            else:
                print("⚠️ Could not set thread priority")
            
            # Get module handle
            hInstance = kernel32.GetModuleHandleW(None)
            
            # Create window procedure callback (must keep reference!)
            self._wndproc = WNDPROC(self._handle_wndproc)
            
            # Register window class
            wc = WNDCLASSEXW()
            wc.cbSize = sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hInstance
            wc.lpszClassName = "RawInputWindow"
            
            if not user32.RegisterClassExW(byref(wc)):
                print(f"❌ RegisterClassExW failed: {kernel32.GetLastError()}")
                return
            
            # Create message-only window
            HWND_MESSAGE = wintypes.HWND(-3)
            self.hwnd = user32.CreateWindowExW(
                0, "RawInputWindow", "", 0,
                0, 0, 0, 0, HWND_MESSAGE, None, hInstance, None
            )
            
            if not self.hwnd:
                print(f"❌ CreateWindowExW failed: {kernel32.GetLastError()}")
                return
            
            # Register for raw mouse input
            rid = RAWINPUTDEVICE()
            rid.usUsagePage = 0x01  # Generic Desktop
            rid.usUsage = 0x02      # Mouse
            rid.dwFlags = RIDEV_INPUTSINK
            rid.hwndTarget = self.hwnd
            
            if not user32.RegisterRawInputDevices(byref(rid), 1, sizeof(RAWINPUTDEVICE)):
                print(f"❌ RegisterRawInputDevices failed: {kernel32.GetLastError()}")
                return
            
            print("✅ Raw Input registered - capturing hardware mickeys")
            
            # Message loop - GetMessage blocks efficiently until messages arrive
            msg = wintypes.MSG()
            while self.raw_input_running:
                ret = user32.GetMessageW(byref(msg), self.hwnd, 0, 0)
                if ret == 0 or ret == -1:
                    break
                user32.TranslateMessage(byref(msg))
                user32.DispatchMessageW(byref(msg))
            
        except Exception as e:
            print(f"❌ Raw input error: {e}")
            import traceback
            traceback.print_exc()

    def _handle_wndproc(self, hwnd, msg, wparam, lparam):
        """Window procedure - handles raw input messages."""
        if msg == WM_INPUT:
            self._process_raw_input(lparam)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _process_raw_input(self, lparam):
        """Extract and process raw mouse data from a WM_INPUT message."""
        # Get required buffer size
        size = wintypes.UINT()
        user32.GetRawInputData(lparam, RID_INPUT, None, byref(size), sizeof(RAWINPUTHEADER))
        
        if size.value == 0:
            return
        
        # Get the raw input data
        buf = ctypes.create_string_buffer(size.value)
        if user32.GetRawInputData(lparam, RID_INPUT, buf, byref(size), sizeof(RAWINPUTHEADER)) <= 0:
            return
        
        raw = ctypes.cast(buf, POINTER(RAWINPUT)).contents
        
        if raw.header.dwType != RIM_TYPEMOUSE:
            return
        
        dx = raw.mouse.lLastX
        dy = raw.mouse.lLastY

        # Track button state: 0=none, 1=left, 2=right (left takes priority if both)
        # RI_MOUSE_LEFT_BUTTON_DOWN=0x0001, LEFT_UP=0x0002
        # RI_MOUSE_RIGHT_BUTTON_DOWN=0x0004, RIGHT_UP=0x0008
        flags = raw.mouse.usButtonFlags
        prev_button_state = self.button_state
        if flags & 0x0001:
            self.button_state = 1  # left down
        elif flags & 0x0004:
            self.button_state = 2  # right down
        if flags & 0x0002 and self.button_state == 1:
            self.button_state = 0  # left released
        elif flags & 0x0008 and self.button_state == 2:
            self.button_state = 0  # right released

        if dx == 0 and dy == 0:
            # No movement — but if button state changed and we're recording,
            # still emit a row so the click is not lost in the data stream
            if self.recording and self.button_state != prev_button_state:
                event_time = time.perf_counter() - self.start_time
                self.data_points.append([event_time, self.current_x_mm, self.current_y_mm, self.button_state])
            return
        
        # Update statistics
        self.event_count += 1
        self.total_mickeys += abs(dx) + abs(dy)
        
        # If not recording, just track statistics
        if not self.recording:
            return
        
        # Get timing
        now = time.perf_counter()
        event_time = now - self.start_time
        time_delta = now - self.last_event_time
        
        # Velocity sanity check - filter sensor glitches
        if time_delta > 0:
            dist_mm = ((dx/RATIO)**2 + (dy/RATIO)**2) ** 0.5
            velocity = dist_mm / time_delta
            
            if velocity > MAX_VELOCITY_MM_SEC:
                self.glitch_count += 1
                self.last_event_time = now
                return
        
        self.last_event_time = now

        gap = now - self.last_movement_time

        # Classic lift detection (all pad types, anywhere on pad)
        if LIFT_DETECT_MIN <= gap <= LIFT_DETECT_MAX:
            self.current_x_mm = self.center_x
            self.current_y_mm = self.center_y

        self.last_movement_time = now

        # Update position
        self.current_x_mm += dx / RATIO
        self.current_y_mm -= dy / RATIO  # Y inverted

        # Hard boundary reset
        if (self.current_x_mm < self.reset_left or self.current_x_mm > self.reset_right or
                self.current_y_mm < self.reset_bottom or self.current_y_mm > self.reset_top):
            self.current_x_mm = self.center_x
            self.current_y_mm = self.center_y

        # Active Aiming Zone (AAZ) liftoff detection
        # After warmup, if position is far outside the learned aiming zone
        # and any brief pause occurs, we assume a liftoff and snap to AAZ center.
        session_elapsed = now - self.start_time
        if session_elapsed >= AAZ_WARMUP_SECS:
            norm_x = abs(self.current_x_mm - self.aaz_cx) / max(self.aaz_rx, 1.0)
            norm_y = abs(self.current_y_mm - self.aaz_cy) / max(self.aaz_ry, 1.0)
            inside = (norm_x <= 1.0 and norm_y <= 1.0)
            far_outside = (norm_x > AAZ_LIFTOFF_MULT and norm_y > AAZ_LIFTOFF_MULT)

            if far_outside and gap >= AAZ_LIFT_GAP:
                # Far outside + any brief pause = liftoff assumed, snap to AAZ center
                self.current_x_mm = self.aaz_cx
                self.current_y_mm = self.aaz_cy
            elif inside:
                # Inside AAZ: slowly pull the AAZ center toward current position
                self.aaz_cx += (self.current_x_mm - self.aaz_cx) * AAZ_LEARN_RATE
                self.aaz_cy += (self.current_y_mm - self.aaz_cy) * AAZ_LEARN_RATE

            # Track outside ratio over a rolling window; grow AAZ if needed
            self._aaz_recent.append(not inside)
            if len(self._aaz_recent) > AAZ_OUTSIDE_WINDOW:
                self._aaz_recent.pop(0)
            if len(self._aaz_recent) == AAZ_OUTSIDE_WINDOW:
                outside_ratio = sum(self._aaz_recent) / AAZ_OUTSIDE_WINDOW
                if outside_ratio > AAZ_GROW_THRESHOLD:
                    self.aaz_rx = min(self.aaz_rx * AAZ_GROW_RATE, AAZ_GROW_MAX_X)
                    self.aaz_ry = min(self.aaz_ry * AAZ_GROW_RATE, AAZ_GROW_MAX_Y)

        # Store data point (time, x, y, btn)
        self.data_points.append([event_time, self.current_x_mm, self.current_y_mm, self.button_state])

    # -------------------------------------------------------------------------
    # Recording Control
    # -------------------------------------------------------------------------
    def toggle_recording(self):
        """Start or stop recording."""
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        """Begin a new recording session."""
        print(f"\n🔴 RECORDING STARTED")
        
        self.recording = True
        self.data_points = []
        self.event_count = 0
        self.glitch_count = 0
        
        # Reset position to center
        self.current_x_mm = self.center_x
        self.current_y_mm = self.center_y

        # Reset AAZ to initial state
        self.aaz_cx = self.center_x
        self.aaz_cy = self.center_y
        self.aaz_rx = AAZ_INIT_RADIUS_X
        self.aaz_ry = AAZ_INIT_RADIUS_Y
        self._aaz_recent = []
        
        # Initialize timing
        self.start_time = time.perf_counter()
        self.last_event_time = self.start_time
        self.last_movement_time = self.start_time
        self.last_rate_time = self.start_time
        self.last_rate_count = 0
        
        # Reset click state
        self.button_state = 0

        # Add initial point
        self.data_points.append([0.0, self.center_x, self.center_y, 0])
        
        # Update UI
        self._apply_runner_recording_state(0.0)
        
        # Start UI update timers
        self._update_timer()

        if self.settings.get('show_notifications'):
            self._show_toast('Session Started', duration_ms=1800)
        
        # Auto-stop after max session time
        self.root.after(MAX_SESSION_TIME * 1000, self._auto_stop)

    def stop_recording(self):
        """End the current recording session."""
        if not self.recording:
            return
        
        self.recording = False
        duration = time.perf_counter() - self.start_time
        
        # Print summary
        hz = self.event_count / duration if duration > 0 else 0
        print(f"\n⏹️ RECORDING STOPPED")
        print(f"   Duration: {duration:.2f}s")
        print(f"   Events: {self.event_count}")
        print(f"   Rate: {hz:.0f} Hz")
        if self.glitch_count > 0:
            print(f"   Glitches filtered: {self.glitch_count}")
        
        # Update UI
        self._apply_runner_idle_state(duration)

        if self.settings.get('show_notifications'):
            reason = getattr(self, '_auto_stopped_reason', None)
            if reason == 'max_time':
                self._show_toast('Session Ended — 8 hour limit reached', duration_ms=3000)
            elif reason == 'afk':
                self._show_toast('Session Ended — AFK timeout', duration_ms=3000)
            else:
                self._show_toast('Session Ended', duration_ms=1800)
            self._auto_stopped_reason = None
        
        # Save and upload (only if 5+ minutes)
        if duration >= MIN_SESSION_SECONDS:
            self._save_session(duration)
        else:
            print(f"   ⚠️ Session too short ({duration:.1f}s < {MIN_SESSION_SECONDS}s) — not saved [{self.username}]")
            if self.settings.get('show_upload_result'):
                self._show_toast('Session too short. Minimum is 5 minutes.', is_error=True, duration_ms=3400)
            self._mark_recording_finished_on_server(duration, saved_to_server=False)

    def _auto_stop(self):
        """Auto-stop after max session time or AFK timeout."""
        if self.recording:
            print("\n⏰ Max session time reached")
            self._auto_stopped_reason = 'max_time'
            self.stop_recording()

    # -------------------------------------------------------------------------
    # UI Updates
    # -------------------------------------------------------------------------
    def _update_display(self):
        """(Visualization removed)"""
        return

    def _update_timer(self):
        """Periodic update for time display, rate display, and AFK check."""
        if self.closing or not self.recording:
            return
        
        try:
            now = time.perf_counter()
            
            # Update time display
            elapsed = now - self.start_time
            self._apply_runner_recording_state(elapsed)
            
            # AFK check
            if now - self.last_movement_time >= self.afk_timeout_seconds:
                print(f"\n💤 AFK detected - auto stopping")
                self._auto_stopped_reason = 'afk'
                self.root.after(0, self.stop_recording)
                return
            
            # Schedule next update
            self.root.after(200, self._update_timer)
        except:
            pass

    def toggle_visibility(self):
        """Toggle window between topmost and hidden."""
        if self.window_hidden:
            self.window_hidden = False
            self.root.deiconify()
            self.root.attributes('-topmost', True)
            self.root.lift()
            self.root.after(150, self._apply_topmost_setting)
        else:
            self.window_hidden = True
            self.root.withdraw()

    def _force_logout(self, message, show_toast=False):
        """Clear local auth and return the user to the login window."""
        clear_stored_session_token()
        self.session_token = None
        self.logged_out = True
        self.logout_message = message
        self.closing = True

        if show_toast and getattr(self, 'root', None) and self.root.winfo_exists():
            self._show_toast(message, is_error=True, duration_ms=2200)
            self.root.after(2200, self.root.destroy)
        elif getattr(self, 'root', None) and self.root.winfo_exists():
            self.root.destroy()

    # -------------------------------------------------------------------------
    # Data Save/Upload
    # -------------------------------------------------------------------------
    def _close_after_setup_complete(self):
        """Close the tool after onboarding recording completion is confirmed."""
        if self.closing:
            return

        print("✅ Setup complete — closing PositionAnalyzer")
        self.closing = True
        try:
            self.root.after(0, self.root.destroy)
        except Exception:
            pass

    def _mark_recording_finished_on_server(self, duration, saved_to_server):
        """Persist the onboarding recording-finished flag for the current account."""
        payload = {
            'session_token': self.session_token,
            'username': self.username,
            'duration': duration,
            'saved_to_server': bool(saved_to_server),
        }

        try:
            resp = requests.post(
                f"{WEB_SERVER_URL}/api/mark_recording_finished",
                json=payload,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('close_after_setup_completion'):
                    self._close_after_setup_complete()
                return True

            if resp.status_code == 401:
                error = None
                try:
                    error = resp.json().get('error')
                except Exception:
                    error = None
                print(f"🔒 Recording completion rejected: {error or 'Auth failed'}")
                self._force_logout(error or 'Session expired. Please log in again.', show_toast=True)
                return False

            error = None
            try:
                error = resp.json().get('error')
            except Exception:
                error = None
            print(f"⚠️ Could not mark onboarding recording complete: {error or resp.status_code}")
        except Exception as e:
            print(f"⚠️ Could not mark onboarding recording complete: {e}")

        return False

    def _save_session(self, duration):
        """Save session data locally and upload to server."""
        if not self.data_points:
            return

        backup_path = os.path.join(get_user_data_dir(), DATA_FILE)
        
        # Save local backup
        try:
            with open(backup_path, "w", newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["time", "x", "y", "btn"])
                for p in self.data_points:
                    btn_val = p[3] if len(p) > 3 else 0
                    writer.writerow([round(p[0], 4), round(p[1], 4), round(p[2], 4), btn_val])
            print(f"💾 Local backup: {backup_path}")
        except Exception as e:
            print(f"⚠️ Local save failed: {e}")
        
        # Upload to server
        try:
            points = [[round(p[0], 4), round(p[1], 4), round(p[2], 4), (p[3] if len(p) > 3 else 0)] for p in self.data_points]
            
            payload = {
                    'session_token': self.session_token,
                    'username': self.username,
                    'duration': duration,
                    'event_count': self.event_count,
                    'mickeys_per_mm': RATIO,
                    'session_name': f'Session {time.strftime("%Y-%m-%d %H:%M")}',
                    'points': points,
                    'mousepad_width_mm': self.mousepad_width_mm,
                    'mousepad_height_mm': self.mousepad_height_mm,
                    'start_timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }

            resp = requests.post(
                f"{WEB_SERVER_URL}/api/save_session",
                json=payload,
                timeout=30
            )

            if resp.status_code == 200:
                data = resp.json()
                print(f"☁️ Uploaded: {data.get('message', 'Success')}")
                if self.settings.get('show_upload_result'):
                    self._show_toast('Upload Complete', duration_ms=2600)
                if data.get('close_after_setup_completion'):
                    self._close_after_setup_complete()
            elif resp.status_code == 401:
                error = None
                try:
                    error = resp.json().get('error')
                except Exception:
                    error = None
                print(f"🔒 Upload rejected: {error or 'Auth failed'}")
                self._force_logout(error or 'Session expired. Please log in again.', show_toast=True)
            else:
                error = None
                try:
                    error = resp.json().get('error')
                except Exception:
                    error = None
                print(f"⚠️ Upload failed: {error or 'Unknown'}")
                if self.settings.get('show_upload_result'):
                    self._show_toast(error or 'Upload Failed', is_error=True, duration_ms=3400)
        except Exception as e:
            print(f"⚠️ Upload error: {e}")
            if self.settings.get('show_upload_result'):
                self._show_toast('Upload Failed', is_error=True, duration_ms=3400)

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    def run(self):
        """Start the application."""
        print(f"\n🎮 PositionAnalyzer")
        print(f"   User: {self.username}")
        print(f"   Calibration: {RATIO:.2f} mickeys/mm")
        print(f"   Controls: F8=Record, F12=Hide")
        print("=" * 40)
        
        try:
            self.root.mainloop()
        finally:
            self._cleanup()

        # If the user logged out, show the login window and restart
        if self.logged_out:
            login_result = show_login_window(
                username_prefill=self.username,
                error_message=self.logout_message or None,
            )
            if login_result:
                username, token = login_result
                update_local_config(top_level_updates={'username': username, 'session_token': token})
                new_app = MouseTrackerGUI(username, token)
                new_app.run()

    def do_logout(self):
        """Log out and return to the login window."""
        if self.recording:
            self.stop_recording()
        revoke_remote_session_token(self.session_token)
        clear_stored_session_token()
        self.logged_out = True
        self.closing = True
        self.logout_message = ''
        self.root.destroy()

    def on_closing(self):
        """Handle window close — auto-stop recording if active."""
        self.closing = True
        self._persist_window_position()
        if self.recording:
            print("\n🚪 Window closed while recording — auto-stopping session")
            self.stop_recording()
        self.root.destroy()

    def _cleanup(self):
        """Clean up resources."""
        self.closing = True
        self.recording = False
        self.raw_input_running = False
        try:
            self.kb_listener.stop()
        except:
            pass
        try:
            self._close_settings_window()
        except Exception:
            pass


# =============================================================================
# ENTRY POINT
# =============================================================================
def has_cli_flag(flag):
    """Return True when the exact CLI flag is present."""
    return any(arg == flag for arg in sys.argv[1:])


def show_setup_message(title, message, is_error=False):
    """Show a simple setup dialog for installer-driven launches."""
    dialog_root = tk.Tk()
    dialog_root.withdraw()
    dialog_root.attributes('-topmost', True)

    try:
        if is_error:
            messagebox.showerror(title, message, parent=dialog_root)
        else:
            messagebox.showinfo(title, message, parent=dialog_root)
    finally:
        dialog_root.destroy()


def initialize_installation(show_message=True):
    """Register the packaged install and optionally confirm completion."""
    registered = register_packaged_installation()
    sync_local_config()

    if getattr(sys, 'frozen', False) and not registered:
        message = (
            "PositionAnalyzer could not save its install location automatically. "
            "Run PositionAnalyzer.exe again from its installed folder to retry."
        )
        if show_message:
            show_setup_message("PositionAnalyzer Setup", message, is_error=True)
        return False

    message = (
        "PositionAnalyzer is initialized and ready. "
        "Return to the website to continue; this window will close after you confirm."
    )
    if show_message:
        show_setup_message("PositionAnalyzer Setup Complete", message)
    return True


def get_username():
    """Get username from command line or config file."""
    # Check CLI args (skip flags like --token)
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg.startswith('--'):
            continue
        if i > 1 and sys.argv[i - 1] == '--token':
            continue
        return arg

    config = load_local_config()
    username = config.get('username')
    if isinstance(username, str):
        username = username.strip()
        if username:
            return username
    
    return None


def get_token():
    """Get session token from --token CLI argument."""
    for i, arg in enumerate(sys.argv):
        if arg == '--token' and i + 1 < len(sys.argv):
            return sys.argv[i + 1]

    config = load_local_config()
    session_token = config.get('session_token') or config.get('token')
    if isinstance(session_token, str):
        session_token = session_token.strip()
        if session_token:
            return session_token

    return None


def show_login_window(username_prefill='', error_message=None):
    """Show a styled Tkinter login window and return (username, token) or None."""
    result = {}

    BG     = RUNNER_BG        # #0E0E0E
    ORANGE = RUNNER_PRIMARY   # #FFB347
    GREY   = RUNNER_MUTED     # #888888
    FONT   = RUNNER_FONT_FAMILY
    FS     = 12
    MAX_LEN = 128

    login_root = tk.Tk()
    login_root.title("PositionAnalyzer - Log In")
    login_root.configure(bg=BG)
    login_root.geometry("340x280")
    login_root.resizable(False, False)

    login_root.update_idletasks()
    x = (login_root.winfo_screenwidth()  // 2) - 170
    y = (login_root.winfo_screenheight() // 2) - 140
    login_root.geometry(f"+{x}+{y}")

    tk.Label(login_root, text="Log in to start recording",
             font=(FONT, FS), fg=GREY, bg=BG).pack(pady=(18, 10))

    frame = tk.Frame(login_root, bg=BG)
    frame.pack(padx=24, fill=tk.X)

    vcmd = (login_root.register(lambda P: len(P) <= MAX_LEN), '%P')

    tk.Label(frame, text="Username:", font=(FONT, FS), fg=ORANGE, bg=BG, anchor="w").pack(fill=tk.X)
    user_entry = tk.Entry(
        frame, font=(FONT, FS),
        bg="#1F1A12", fg=ORANGE, insertbackground=ORANGE,
        relief=tk.FLAT, highlightthickness=0,
        validate='key', validatecommand=vcmd,
    )
    user_entry.pack(fill=tk.X, pady=(2, 8))
    if username_prefill:
        user_entry.insert(0, username_prefill)

    tk.Label(frame, text="Password:", font=(FONT, FS), fg=ORANGE, bg=BG, anchor="w").pack(fill=tk.X)
    pass_entry = tk.Entry(
        frame, show="*", font=(FONT, FS),
        bg="#1F1A12", fg=ORANGE, insertbackground=ORANGE,
        relief=tk.FLAT, highlightthickness=0,
        validate='key', validatecommand=vcmd,
    )
    pass_entry.pack(fill=tk.X, pady=(2, 0))

    status_label = tk.Label(
        login_root,
        text=error_message or "",
        font=(FONT, FS), fg=GREY, bg=BG, wraplength=292,
    )
    status_label.pack(pady=(6, 0))

    def _check_limit(entry):
        at_limit = len(entry.get()) >= MAX_LEN
        if at_limit:
            status_label.config(text="Character limit hit", fg=GREY)
        elif status_label.cget('text') == "Character limit hit":
            status_label.config(text="")

    user_entry.bind("<KeyRelease>", lambda e: _check_limit(user_entry))
    pass_entry.bind("<KeyRelease>", lambda e: _check_limit(pass_entry))

    def do_login(event=None):
        username = user_entry.get().strip()
        password = pass_entry.get()
        if not username or not password:
            status_label.config(text="Enter username and password.", fg=GREY)
            return
        status_label.config(text="Logging in…", fg=GREY)
        login_btn.config(state=tk.DISABLED)
        login_root.update()
        try:
            resp = requests.post(
                f"{WEB_SERVER_URL}/api/client_login",
                json={"username": username, "password": password, "platform": "Windows"},
                timeout=10,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("success"):
                result["username"] = data["username"]
                result["token"] = data["session_token"]
                login_root.destroy()
            else:
                error_code = data.get("error_code", "")
                if error_code == "user_not_found":
                    msg = "Account does not exist"
                elif error_code == "wrong_password":
                    msg = "Password does not match"
                else:
                    msg = data.get("error") or "Login failed."
                status_label.config(text=msg, fg=GREY)
                login_btn.config(state=tk.NORMAL)
        except requests.ConnectionError:
            status_label.config(text="Cannot reach server. Is the website running?", fg=GREY)
            login_btn.config(state=tk.NORMAL)
        except Exception as e:
            status_label.config(text=str(e), fg=GREY)
            login_btn.config(state=tk.NORMAL)

    login_btn = tk.Button(
        login_root, text="Log In",
        font=(FONT, FS), fg=ORANGE, bg=BG,
        activebackground=BG, activeforeground=ORANGE,
        relief=tk.FLAT, bd=0, highlightthickness=0,
        cursor="hand2", command=do_login,
    )
    login_btn.pack(pady=(8, 0))

    pass_entry.bind("<Return>", do_login)
    user_entry.bind("<Return>", do_login)
    user_entry.focus_set()

    login_root.mainloop()
    if "token" in result:
        return result["username"], result["token"]
    return None


def main():
    if has_cli_flag('--initialize-only'):
        initialize_installation(show_message=False)
        return

    first_packaged_launch = is_first_packaged_launch()

    if first_packaged_launch:
        initialize_installation(show_message=True)
        return

    initialize_installation(show_message=False)

    config = load_local_config()
    settings = dict(config.get('settings') or get_default_runner_settings())
    auto_login_web = settings.get('auto_login_web_account', True)

    username = get_username()
    token = get_token()
    bootstrap_data = None
    login_error = None

    # If "always stay logged in with website account" is on, try to match the
    # most recently active web user before falling back to saved credentials.
    if auto_login_web:
        try:
            resp = requests.get(f"{WEB_SERVER_URL}/api/active_web_user", timeout=3)
            if resp.status_code == 200:
                web_username = resp.json().get('username')
                if web_username and web_username != username:
                    # Web account differs from saved — pre-fill login with web account
                    username = web_username
                    token = None  # Force re-auth for the new account
        except Exception:
            pass  # Server unreachable — continue with saved credentials

    if username and token:
        bootstrap_result = fetch_runner_bootstrap(username, token)
        if bootstrap_result.get('success'):
            bootstrap_data = bootstrap_result.get('data')
        elif bootstrap_result.get('auth_invalid'):
            clear_stored_session_token()
            token = None
            login_error = bootstrap_result.get('error') or 'Session expired. Please log in again.'

    # If launched without credentials, show login window
    if not username or not token:
        login_result = show_login_window(username_prefill=username or '', error_message=login_error)
        if not login_result:
            return  # User closed the window
        username, token = login_result

        try:
            update_local_config(top_level_updates={
                'username': username,
                'session_token': token,
            })
        except OSError as exc:
            print(f"⚠️ Could not persist login config: {exc}")

    app = MouseTrackerGUI(username, token, bootstrap_data=bootstrap_data)
    app.run()


if __name__ == "__main__":
    main()

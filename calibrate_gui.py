import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import requests
from pynput import mouse, keyboard

# --- Settings ---
CALIBRATION_DIST_INCHES = 5.0
CALIBRATION_DIST_MM = CALIBRATION_DIST_INCHES * 25.4
WEB_SERVER_URL = "http://localhost:5000"
CALIBRATION_BG = "#0E0E0E"
CALIBRATION_TEXT_COLOR = "#888888"
CALIBRATION_BUTTON_COLOR = "#FFB347"
CALIBRATION_FONT_FAMILY = "Segoe UI"
CALIBRATION_TEXT_SIZE = 12
MIN_DPI = 200
MAX_DPI = 16000
CALIBRATION_TIMEOUT_SECONDS = 600
CALIBRATION_TIMEOUT_WARNING_SECONDS = 15

class CalibrationGUI:
    def __init__(self, root, username=None, token=None):
        self.root = root
        self.root.title("PositionAnalyzer - DPI Calibration Test")
        self.root.geometry("500x420")
        self.root.configure(bg=CALIBRATION_BG)
        self.root.resizable(False, False)
        
        # Make window appear on top and focused
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.after_idle(lambda: self.root.attributes('-topmost', False))
        self.root.focus_force()
        
        # Center the window on screen
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
        # Calibration variables
        self.total_mickeys_x = 0
        self.recording = False
        self.last_x = None
        self.username = username or ""  # Use provided username or empty string
        self.token = token
        self.username_display_var = tk.StringVar(value=f"User: {self.username}" if self.username else "User:")
        
        # GUI Variables
        self.dpi_var = tk.StringVar(value="DPI: 0")
        self.message_var = tk.StringVar(value="")
        self.timeout_var = tk.StringVar(value="")

        self.calibration_started_at = None
        self.timeout_warning_after_id = None
        self.timeout_countdown_after_id = None
        self.timeout_deadline = None
        self._last_toggle_time = 0
        
        # Listeners
        self.mouse_listener = mouse.Listener(on_move=self.on_mouse_move)
        self.keyboard_listener = keyboard.Listener(on_release=self.on_key_release)
        self.mouse_listener.start()
        self.keyboard_listener.start()
        
        self.setup_gui()
        
    def setup_gui(self):
        # Prevent F10 from activating native Windows menu which pauses the app
        self.root.bind_all('<Key-F10>', lambda e: 'break')

        if not self.username:
            username_frame = tk.Frame(self.root, bg=CALIBRATION_BG)
            username_frame.pack(pady=(18, 10))

            tk.Label(
                username_frame,
                text="Username:",
                font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
                fg=CALIBRATION_TEXT_COLOR,
                bg=CALIBRATION_BG,
            ).pack(side=tk.LEFT, padx=5)

            self.username_entry_var = tk.StringVar()
            self.username_entry_var.trace_add('write', self._handle_username_entry_change)

            self.username_entry = tk.Entry(
                username_frame,
                textvariable=self.username_entry_var,
                font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
                width=20,
                fg=CALIBRATION_BUTTON_COLOR,
                bg=CALIBRATION_BG,
                insertbackground=CALIBRATION_BUTTON_COLOR,
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=CALIBRATION_BUTTON_COLOR,
                highlightcolor=CALIBRATION_BUTTON_COLOR,
            )
            self.username_entry.pack(side=tk.LEFT, padx=5)
            self.username_entry.bind('<Return>', lambda e: self.start_calibration())

        content_frame = tk.Frame(self.root, bg=CALIBRATION_BG)
        content_frame.pack(fill=tk.X, padx=20, pady=(8, 10))

        self.user_label = tk.Label(
            content_frame,
            textvariable=self.username_display_var,
            font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
            fg=CALIBRATION_BUTTON_COLOR,
            bg=CALIBRATION_BG,
            anchor='w',
            justify=tk.LEFT,
        )
        self.user_label.pack(anchor='w', pady=(0, 12))

        instructions_label = tk.Label(
            content_frame,
            text=(
                "1. Place your mouse parallel to your mousepad.\n"
                "2. Press F10 to start recording.\n"
                "3. Move the mouse 5 inches to the right.\n"
                "4. Press F10 when you finish."
            ),
            font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
            fg=CALIBRATION_TEXT_COLOR,
            bg=CALIBRATION_BG,
            anchor='w',
            justify=tk.LEFT,
        )
        instructions_label.pack(anchor='w')

        warning_label = tk.Label(
            content_frame,
            text=(
                "DPI must be between 200 and 16000, if DPI does not meet that "
                "requirement, it will be auto adjusted to fit."
            ),
            font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
            fg=CALIBRATION_BUTTON_COLOR,
            bg=CALIBRATION_BG,
            wraplength=440,
            anchor='center',
            justify=tk.CENTER,
        )
        warning_label.pack(anchor='center', pady=(18, 0))

        self.feedback_frame = tk.Frame(self.root, bg=CALIBRATION_BG, height=42)
        self.feedback_frame.pack(fill=tk.X, padx=20, pady=(12, 0))
        self.feedback_frame.pack_propagate(False)

        self.feedback_label = tk.Label(
            self.feedback_frame,
            font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
            fg=CALIBRATION_TEXT_COLOR,
            bg=CALIBRATION_BG,
            wraplength=440,
            justify=tk.CENTER,
        )
        self.feedback_label.pack(expand=True)

        self.button_frame = tk.Frame(self.root, bg=CALIBRATION_BG)
        self.button_frame.pack(pady=(16, 8))

        self.start_btn = tk.Button(
            self.button_frame,
            text="Start Calibration / F10",
            command=self.toggle_calibration,
            font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
            bg=CALIBRATION_BG,
            fg=CALIBRATION_BUTTON_COLOR,
            activebackground=CALIBRATION_BG,
            activeforeground=CALIBRATION_BUTTON_COLOR,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            width=18,
        )
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.reset_btn = tk.Button(
            self.button_frame,
            text="Cancel",
            command=self.cancel_calibration,
            font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
            bg=CALIBRATION_BG,
            fg=CALIBRATION_BUTTON_COLOR,
            activebackground=CALIBRATION_BG,
            activeforeground=CALIBRATION_BUTTON_COLOR,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            width=10,
        )
        self.reset_btn.pack(side=tk.LEFT, padx=5)

        self.dpi_label = tk.Label(
            self.root,
            textvariable=self.dpi_var,
            font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
            fg=CALIBRATION_TEXT_COLOR,
            bg=CALIBRATION_BG,
        )
        self.dpi_label.pack(pady=(4, 0))

    def _handle_username_entry_change(self, *_args):
        username_text = self.username_entry_var.get().strip() if hasattr(self, 'username_entry_var') else ''
        self.username_display_var.set(f"User: {username_text}" if username_text else "User:")

    def _refresh_feedback_label(self):
        timeout_text = self.timeout_var.get().strip()
        message_text = self.message_var.get().strip()
        self.feedback_label.config(text=timeout_text or message_text)

    def _set_message(self, text):
        self.message_var.set(text)
        self._refresh_feedback_label()

    def _set_timeout_message(self, text):
        self.timeout_var.set(text)
        self._refresh_feedback_label()
        
    def start_calibration(self):
        # Get username if not already provided
        if not self.username:
            username = self.username_entry.get().strip()
            if not username:
                messagebox.showerror("Error", "Please enter a username!")
                return
            self.username = username
            self.username_display_var.set(f"User: {self.username}")

        if self.recording:
            return
        
        self.reset_calibration()
        self.recording = True
        self.start_btn.config(text="Stop Calibration / F10")
        self._set_message("")
        self._set_timeout_message("")
        self.calibration_started_at = time.time()
        self.timeout_deadline = None
        self._schedule_timeout_warning()
        self.root.after(50, self.update_mickey_display_loop)

    def toggle_calibration(self, event=None):
        now = time.time()
        # Debounce multiple F10 calls that can cause looping issues
        if now - self._last_toggle_time < 0.3:
            return
        self._last_toggle_time = now

        if self.recording:
            self.recording = False
            self.finish_calibration()
            return

        self.start_calibration()
            
    def on_mouse_move(self, x, y):
        """Handle mouse movement during recording"""
        if self.recording:
            if self.last_x is not None:
                dx = abs(x - self.last_x)
                
                if dx > 0.5:  # Jitter filter
                    self.total_mickeys_x += dx
            
            self.last_x = x
            
    def update_mickey_display_loop(self):
        """Update the live DPI estimate display continuously during recording."""
        if not self.recording:
            return
        dpi_estimate = self.total_mickeys_x / CALIBRATION_DIST_INCHES
        self.dpi_var.set(f"DPI: {dpi_estimate:.0f}")
        self.root.after(50, self.update_mickey_display_loop)

    def _schedule_timeout_warning(self):
        self._cancel_timeout_jobs()
        self.timeout_warning_after_id = self.root.after(
            CALIBRATION_TIMEOUT_SECONDS * 1000,
            self._begin_timeout_countdown,
        )

    def _cancel_timeout_jobs(self):
        if self.timeout_warning_after_id is not None:
            self.root.after_cancel(self.timeout_warning_after_id)
            self.timeout_warning_after_id = None
        if self.timeout_countdown_after_id is not None:
            self.root.after_cancel(self.timeout_countdown_after_id)
            self.timeout_countdown_after_id = None

    def _begin_timeout_countdown(self):
        if not self.recording:
            return
        self.timeout_deadline = time.time() + CALIBRATION_TIMEOUT_WARNING_SECONDS
        self._tick_timeout_countdown()

    def _tick_timeout_countdown(self):
        if not self.recording or self.timeout_deadline is None:
            self._set_timeout_message("")
            self.timeout_countdown_after_id = None
            return

        seconds_left = max(0, int(round(self.timeout_deadline - time.time())))
        self._set_timeout_message(
            f"Finish this test or it will be stopped: {seconds_left}"
        )

        if seconds_left <= 0:
            self.recording = False
            self.finish_calibration_with_outcome(save_result=False, timed_out=True)
            return

        self.timeout_countdown_after_id = self.root.after(250, self._tick_timeout_countdown)

    def _coerce_saved_dpi(self):
        raw_dpi = int(round(self.total_mickeys_x / CALIBRATION_DIST_INCHES))
        clamped_dpi = max(MIN_DPI, min(MAX_DPI, raw_dpi))
        return raw_dpi, clamped_dpi
        
    def on_key_release(self, key):
        """Handle keyboard events"""
        try:
              if key == keyboard.Key.f10:
                self.root.after(0, self.toggle_calibration)
        except AttributeError:
            pass
            
    def finish_calibration(self):
        """Process calibration results"""
        self.finish_calibration_with_outcome(save_result=True, timed_out=False)

    def finish_calibration_with_outcome(self, save_result=True, timed_out=False):
        self._cancel_timeout_jobs()
        self._set_timeout_message("")
        self.calibration_started_at = None
        self.start_btn.config(text="Start Calibration / F10")

        if timed_out:
            self.dpi_var.set("DPI: 0")
            self._set_message("Test was not finished and will not be saved")
            return

        raw_dpi, clamped_dpi = self._coerce_saved_dpi()
        ratio = clamped_dpi / 25.4
        self.dpi_var.set(f"DPI: {clamped_dpi}")

        if save_result:
            threading.Thread(target=self.save_calibration_to_web, args=(ratio,), daemon=True).start()

        if clamped_dpi != raw_dpi:
            self._set_message(
                f"DPI requirements not met, DPI will be saved as {clamped_dpi}"
            )
        else:
            self._set_message(
                f"Success, new DPI saved for {self.username}"
            )
        self.root.after(4000, self._clear_feedback_and_dpi)

    def _clear_feedback_and_dpi(self):
        if not self.recording:
            self._set_message("")
            self.dpi_var.set("DPI: 0")
            
    def save_calibration_to_web(self, mickeys_per_mm):
        """Save calibration to web database"""
        try:
            print(f"Attempting to save calibration for user: {self.username}")
            print(f"Mickeys per mm: {mickeys_per_mm}")
            print(f"URL: {WEB_SERVER_URL}/api/save_calibration")
            
            response = requests.post(
                f"{WEB_SERVER_URL}/api/save_calibration",
                json={
                    'username': self.username,
                    'mickeys_per_mm': mickeys_per_mm,
                    'session_token': self.token
                },
                headers={'Content-Type': 'application/json'},
                timeout=5
            )
            
            print(f"Response status: {response.status_code}")
            print(f"Response content: {response.text}")
            
            if response.status_code == 200:
                return True
            else:
                print(f"Error response: {response.json()}")
                return False
            
        except requests.exceptions.RequestException as e:
            print(f"Connection error: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error: {e}")
            return False
            
    def reset_calibration(self):
        """Reset calibration state"""
        self.total_mickeys_x = 0
        self.recording = False
        self.start_btn.config(text="Start Calibration / F10")
        self.last_x = None
        self.dpi_var.set("DPI: 0")
        self._set_timeout_message("")
        self._set_message("")
        self._cancel_timeout_jobs()

    def cancel_calibration(self):
        """Stop the current calibration run without closing the window."""
        self.reset_calibration()
        
    def stop_listeners(self):
        """Stop all listeners"""
        if self.mouse_listener:
            self.mouse_listener.stop()
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            
    def on_closing(self):
        """Handle window close event"""
        self.stop_listeners()
        self.root.destroy()

def _show_calibration_login_window_unused():
    """Show a login window for the calibration tool. Returns (username, token) or None."""
    result = {}
    MAX_LEN = 128

    login_root = tk.Tk()
    login_root.title("PositionAnalyzer - Log In")
    login_root.configure(bg=CALIBRATION_BG)
    login_root.geometry("340x280")
    login_root.resizable(False, False)

    login_root.update_idletasks()
    x = (login_root.winfo_screenwidth()  // 2) - 170
    y = (login_root.winfo_screenheight() // 2) - 140
    login_root.geometry(f"+{x}+{y}")

    tk.Label(
        login_root, text="Log in to start recording",
        font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
        fg=CALIBRATION_TEXT_COLOR, bg=CALIBRATION_BG,
    ).pack(pady=(18, 10))

    frame = tk.Frame(login_root, bg=CALIBRATION_BG)
    frame.pack(padx=24, fill=tk.X)

    vcmd = (login_root.register(lambda P: len(P) <= MAX_LEN), '%P')

    tk.Label(frame, text="Username:", font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
             fg=CALIBRATION_BUTTON_COLOR, bg=CALIBRATION_BG, anchor="w").pack(fill=tk.X)
    user_entry = tk.Entry(
        frame, font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
        bg=CALIBRATION_BG, fg=CALIBRATION_BUTTON_COLOR, insertbackground=CALIBRATION_BUTTON_COLOR,
        relief=tk.FLAT, highlightthickness=1,
        highlightbackground=CALIBRATION_BUTTON_COLOR, highlightcolor=CALIBRATION_BUTTON_COLOR,
        validate='key', validatecommand=vcmd,
    )
    user_entry.pack(fill=tk.X, pady=(2, 8))

    tk.Label(frame, text="Password:", font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
             fg=CALIBRATION_BUTTON_COLOR, bg=CALIBRATION_BG, anchor="w").pack(fill=tk.X)
    pass_entry = tk.Entry(
        frame, show="*", font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
        bg=CALIBRATION_BG, fg=CALIBRATION_BUTTON_COLOR, insertbackground=CALIBRATION_BUTTON_COLOR,
        relief=tk.FLAT, highlightthickness=1,
        highlightbackground=CALIBRATION_BUTTON_COLOR, highlightcolor=CALIBRATION_BUTTON_COLOR,
        validate='key', validatecommand=vcmd,
    )
    pass_entry.pack(fill=tk.X, pady=(2, 0))

    status_label = tk.Label(
        login_root, text="",
        font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
        fg=CALIBRATION_TEXT_COLOR, bg=CALIBRATION_BG, wraplength=292,
    )
    status_label.pack(pady=(6, 0))

    def _check_limit(entry):
        at_limit = len(entry.get()) >= MAX_LEN
        if at_limit:
            status_label.config(text="Character limit hit", fg=CALIBRATION_TEXT_COLOR)
        elif status_label.cget('text') == "Character limit hit":
            status_label.config(text="")

    user_entry.bind("<KeyRelease>", lambda e: _check_limit(user_entry))
    pass_entry.bind("<KeyRelease>", lambda e: _check_limit(pass_entry))

    def do_login(event=None):
        username = user_entry.get().strip()
        password = pass_entry.get()
        if not username or not password:
            status_label.config(text="Enter username and password.", fg=CALIBRATION_TEXT_COLOR)
            return
        status_label.config(text="Logging in\u2026", fg=CALIBRATION_TEXT_COLOR)
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
                status_label.config(text=msg, fg=CALIBRATION_TEXT_COLOR)
                login_btn.config(state=tk.NORMAL)
        except requests.exceptions.ConnectionError:
            status_label.config(text="Cannot reach server. Is the website running?", fg=CALIBRATION_TEXT_COLOR)
            login_btn.config(state=tk.NORMAL)
        except Exception as e:
            status_label.config(text=str(e), fg=CALIBRATION_TEXT_COLOR)
            login_btn.config(state=tk.NORMAL)

    login_btn = tk.Button(
        login_root, text="Log In",
        font=(CALIBRATION_FONT_FAMILY, CALIBRATION_TEXT_SIZE),
        fg=CALIBRATION_BUTTON_COLOR, bg=CALIBRATION_BG,
        activebackground=CALIBRATION_BG, activeforeground=CALIBRATION_BUTTON_COLOR,
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
    import sys

    username = None
    token = None
    if len(sys.argv) > 1:
        username = sys.argv[1]
    if '--token' in sys.argv:
        idx = sys.argv.index('--token')
        if idx + 1 < len(sys.argv):
            token = sys.argv[idx + 1]

    root = tk.Tk()
    app = CalibrationGUI(root, username, token)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.deiconify()
    root.lift()
    root.focus_set()
    root.mainloop()


if __name__ == "__main__":
    main()
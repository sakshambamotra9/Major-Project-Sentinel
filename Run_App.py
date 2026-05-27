import os
import sys
import time
import threading
import urllib.request
import uvicorn
import webview
import keyboard
import subprocess
import socket

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

BASE_PATH = get_base_path()

def start_server():
    backend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
    os.chdir(backend_path)
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="warning")

def wait_for_server():
    print("Waiting for AI Models to load...")
    while True:
        try:
            res = urllib.request.urlopen("http://127.0.0.1:8000/", timeout=1)
            if res.getcode() == 200:
                break
        except Exception:
            time.sleep(1)
    print("Server is ready!")

# Maintain reference to hook to prevent GC
hhk = None
hook_proc_ptr = None

def block_system_keys():
    try:
        import keyboard
        # Suppress system hotkeys and Windows keys system-wide
        keyboard.block_key('left windows')
        keyboard.block_key('right windows')
        keyboard.add_hotkey('alt+tab', lambda: None, suppress=True)
        keyboard.add_hotkey('alt+esc', lambda: None, suppress=True)
        keyboard.add_hotkey('alt+f4', lambda: None, suppress=True)
        keyboard.add_hotkey('ctrl+esc', lambda: None, suppress=True)
        print("System keys blocked using keyboard library.")
    except Exception as e:
        print(f"Error blocking system keys: {e}")

def enforce_fullscreen(window_title):
    """
    Hooks WM_NCHITTEST and WM_WINDOWPOSCHANGING on the pywebview window so the 
    window cannot be dragged, moved, resized, or repositioned by snap commands.
    """
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        user32 = ctypes.windll.user32

        # DPI-aware screen resolution
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        print(f"Screen resolution: {screen_w}x{screen_h}")

        # Wait for window to appear
        hwnd = None
        while not hwnd:
            hwnd = user32.FindWindowW(None, window_title)
            time.sleep(0.3)

        print(f"Window found (HWND={hwnd}). Applying strict kiosk lock...")

        # Setup style getters/setters using pointer-safe ctypes sizes
        SetWindowStyle = getattr(user32, 'SetWindowLongPtrW', user32.SetWindowLongW)
        SetWindowStyle.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        SetWindowStyle.restype = ctypes.c_ssize_t

        GetWindowStyle = getattr(user32, 'GetWindowLongPtrW', user32.GetWindowLongW)
        GetWindowStyle.argtypes = [wintypes.HWND, ctypes.c_int]
        GetWindowStyle.restype = ctypes.c_ssize_t

        GWL_STYLE = -16
        GWL_EXSTYLE = -20
        WS_POPUP = 0x80000000
        WS_VISIBLE = 0x10000000
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000
        WS_EX_TOPMOST = 0x00000008

        # Force borderless WS_POPUP style to hide Taskbar
        style = GetWindowStyle(hwnd, GWL_STYLE)
        new_style = (style | WS_POPUP | WS_VISIBLE) & ~WS_CAPTION & ~WS_THICKFRAME & ~WS_MINIMIZEBOX & ~WS_MAXIMIZEBOX
        SetWindowStyle(hwnd, GWL_STYLE, new_style)

        # Force topmost extended style
        ex_style = GetWindowStyle(hwnd, GWL_EXSTYLE)
        SetWindowStyle(hwnd, GWL_EXSTYLE, ex_style | WS_EX_TOPMOST)

        # Immediately pin to fullscreen
        HWND_TOPMOST = ctypes.c_int(-1)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, screen_w, screen_h, 0x0020)

        # --- WM_NCHITTEST hook ---
        WM_NCHITTEST = 0x0084
        WM_MOVING    = 0x0216
        WM_WINDOWPOSCHANGING = 0x0046
        WM_SYSCOMMAND = 0x0112
        SC_MOVE = 0xF010
        HTCLIENT     = 1
        GWLP_WNDPROC = -4

        class WINDOWPOS(ctypes.Structure):
            _fields_ = [
                ("hwnd", ctypes.c_void_p),
                ("hwndInsertAfter", ctypes.c_void_p),
                ("x", ctypes.c_int),
                ("y", ctypes.c_int),
                ("cx", ctypes.c_int),
                ("cy", ctypes.c_int),
                ("flags", ctypes.c_uint),
            ]

        WNDPROCTYPE = ctypes.WINFUNCTYPE(
            wintypes.LPARAM, # LRESULT is same size as LPARAM
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM
        )

        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallWindowProcW.restype = wintypes.LPARAM

        SetWindowLong = getattr(user32, 'SetWindowLongPtrW', user32.SetWindowLongW)
        SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, WNDPROCTYPE]
        SetWindowLong.restype = ctypes.c_void_p

        old_proc = [0]

        @WNDPROCTYPE
        def kiosk_proc(h, msg, wp, lp):
            if msg == WM_NCHITTEST:
                return HTCLIENT
            if msg == WM_MOVING:
                return 1
            if msg == WM_SYSCOMMAND:
                if (wp & 0xFFF0) == SC_MOVE:
                    return 0
            if msg == WM_WINDOWPOSCHANGING:
                try:
                    pos = ctypes.cast(lp, ctypes.POINTER(WINDOWPOS)).contents
                    pos.x = 0
                    pos.y = 0
                    pos.cx = screen_w
                    pos.cy = screen_h
                except Exception:
                    pass
            return user32.CallWindowProcW(old_proc[0], h, msg, wp, lp)

        # Subclass the window (install our procedure)
        old_proc[0] = SetWindowLong(hwnd, GWLP_WNDPROC, kiosk_proc)
        print("Kiosk drag-lock applied. Window is now immovable.")

        # Keep thread alive so kiosk_proc is never garbage-collected
        while True:
            # Aggressive safety net: re-pin every 50ms
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, screen_w, screen_h, 0x0040 | 0x0020)
            
            # Pull focus back if we lost it (e.g. from Windows key press / start menu / taskbar overlays)
            fg_hwnd = user32.GetForegroundWindow()
            if fg_hwnd and fg_hwnd != hwnd:
                user32.ShowWindow(hwnd, 5) # SW_SHOW
                user32.SetForegroundWindow(hwnd)
                
            time.sleep(0.05)

    except Exception as e:
        print(f"Kiosk lock error: {e}")
        import traceback
        traceback.print_exc()


def is_port_open(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False

def start_ipfs_daemon():
    if is_port_open(5001):
        print("IPFS Daemon is already running.")
        return None

    # Check for IPFS binary path
    # 1. Bundled path (preferred for packaged release)
    ipfs_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "ipfs.exe")
    
    # 2. Local AppData fallback path (for developer machine testing)
    if not os.path.exists(ipfs_bin):
        appdata_path = os.getenv("LOCALAPPDATA", "")
        fallback_path = os.path.join(
            appdata_path, 
            "Programs", "IPFS Desktop", "resources", "app.asar.unpacked", 
            "node_modules", "kubo", "kubo", "ipfs.exe"
        )
        if os.path.exists(fallback_path):
            ipfs_bin = fallback_path

    if not os.path.exists(ipfs_bin):
        print("WARNING: IPFS executable not found. Please install IPFS Desktop or bundle ipfs.exe in bin/.")
        return None

    print(f"Using IPFS binary: {ipfs_bin}")

    # Initialize repository if it doesn't exist
    user_home = os.path.expanduser("~")
    ipfs_path = os.path.join(user_home, ".ipfs")
    if not os.path.exists(ipfs_path):
        print("Initializing IPFS repository...")
        subprocess.run([ipfs_bin, "init"], capture_output=True)
        # Enable CORS programmatically on init
        subprocess.run([ipfs_bin, "config", "set", "API.HTTPHeaders.Access-Control-Allow-Origin", '["*"]'], capture_output=True)

    print("Starting background IPFS daemon...")
    try:
        # Start daemon silently in background (hide console window using creationflags)
        proc = subprocess.Popen(
            [ipfs_bin, "daemon"], 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL, 
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )
        return proc
    except Exception as e:
        print(f"Failed to start IPFS daemon: {e}")
        return None

if __name__ == '__main__':
    # Start IPFS daemon in background if not running
    print("Checking local IPFS state...")
    ipfs_proc = start_ipfs_daemon()

    print("Starting Sentinel AI Server...")
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    wait_for_server()

    print("Securing environment (blocking Windows keys)...")
    block_system_keys()

    WINDOW_TITLE = 'Sentinel AI Proctoring Platform'

    print("Opening Native App Window...")
    window = webview.create_window(
        WINDOW_TITLE,
        'http://127.0.0.1:8000/',
        fullscreen=True,
        frameless=True,
        on_top=True,
        resizable=False,
    )

    # Start kiosk lock thread BEFORE the GUI loop
    lock_thread = threading.Thread(
        target=enforce_fullscreen,
        args=(WINDOW_TITLE,),
        daemon=True,
    )
    lock_thread.start()

    webview.start()

    # Clean up background IPFS process on exit
    if ipfs_proc:
        print("Stopping background IPFS daemon...")
        ipfs_proc.terminate()
        try:
            ipfs_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            ipfs_proc.kill()

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
    try:
        backend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
        os.chdir(backend_path)
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        # Set to info log level so we can see what's happening
        uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"CRITICAL ERROR in server thread:\n{tb}")
        try:
            log_path = os.path.join(os.path.expanduser("~"), "sentinel_backend_error.log")
            with open(log_path, "w") as f:
                f.write(tb)
        except:
            pass

def wait_for_server(thread):
    print("Waiting for AI Models to load...")
    start_time = time.time()
    while True:
        if not thread.is_alive():
            import ctypes
            error_msg = "The backend server failed to start.\n"
            log_path = os.path.join(os.path.expanduser("~"), "sentinel_backend_error.log")
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r") as f:
                        error_msg += f"\nError Traceback:\n{f.read()}"
                except:
                    pass
            
            ctypes.windll.user32.MessageBoxW(0, error_msg, "Sentinel Startup Error", 0x10 | 0x00020000)
            sys.exit(1)
            
        try:
            res = urllib.request.urlopen("http://127.0.0.1:8000/", timeout=1)
            if res.getcode() == 200:
                break
        except Exception:
            time.sleep(1)
            
        # 45 second timeout for slow model loading
        if time.time() - start_time > 45:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "Backend server took too long to load (Timeout).", "Sentinel Timeout", 0x10 | 0x00020000)
            sys.exit(1)
            
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

def get_ipfs_bin():
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

    if os.path.exists(ipfs_bin):
        return ipfs_bin
    return None

def start_ipfs_daemon():
    if is_port_open(5001):
        print("IPFS Daemon is already running.")
        return None

    ipfs_bin = get_ipfs_bin()
    if not ipfs_bin:
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

ipfs_proc = None

def init_app_async(window):
    global ipfs_proc
    
    # 1. Start IPFS daemon in background
    print("Checking local IPFS state...")
    ipfs_proc = start_ipfs_daemon()

    # 2. Start FastAPI Server
    print("Starting Sentinel AI Server...")
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # 3. Wait for the server thread to load AI models and boot
    wait_for_server(server_thread)

    # 4. Secure hotkeys
    print("Securing environment (blocking Windows keys)...")
    block_system_keys()

    # 5. Redirect webview to the initialized local backend server
    print("Loading application frontend...")
    window.load_url('http://127.0.0.1:8000/')

if __name__ == '__main__':
    WINDOW_TITLE = 'Sentinel AI Proctoring Platform'

    # Premium Loading Screen HTML
    loading_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sentinel OS Loading</title>
        <style>
            body {
                background-color: #0c0f16;
                color: #c9d1d9;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                overflow: hidden;
            }
            .container {
                text-align: center;
                display: flex;
                flex-direction: column;
                align-items: center;
                animation: fadeIn 1s ease-out;
            }
            .logo-container {
                display: flex;
                align-items: center;
                margin-bottom: 25px;
            }
            .shield-icon {
                width: 48px;
                height: 48px;
                fill: #38bdf8;
                margin-right: 12px;
                filter: drop-shadow(0 0 8px rgba(56, 189, 248, 0.4));
            }
            .logo-text {
                font-size: 36px;
                font-weight: 800;
                color: #ffffff;
                letter-spacing: 2px;
            }
            .subtitle {
                font-size: 14px;
                color: #38bdf8;
                text-transform: uppercase;
                letter-spacing: 3px;
                margin-bottom: 40px;
                font-weight: 600;
            }
            .spinner-box {
                position: relative;
                width: 70px;
                height: 70px;
                display: flex;
                justify-content: center;
                align-items: center;
                margin-bottom: 30px;
            }
            .circle-outer {
                width: 60px;
                height: 60px;
                border: 3px solid transparent;
                border-top-color: #38bdf8;
                border-bottom-color: #38bdf8;
                border-radius: 50%;
                animation: spin 1.5s linear infinite;
            }
            .circle-inner {
                position: absolute;
                width: 40px;
                height: 40px;
                border: 3px solid transparent;
                border-left-color: #ffffff;
                border-right-color: #ffffff;
                border-radius: 50%;
                animation: spin-reverse 1s linear infinite;
            }
            .status-text {
                font-size: 16px;
                color: #94a3b8;
                font-weight: 500;
                letter-spacing: 0.5px;
                min-height: 24px;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            @keyframes spin-reverse {
                0% { transform: rotate(360deg); }
                100% { transform: rotate(0deg); }
            }
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo-container">
                <svg class="shield-icon" viewBox="0 0 24 24">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                </svg>
                <div class="logo-text">Sentinel OS</div>
            </div>
            <div class="subtitle">Secure Examination Environment</div>
            <div class="spinner-box">
                <div class="circle-outer"></div>
                <div class="circle-inner"></div>
            </div>
            <div class="status-text">Initializing AI Proctoring Models...</div>
        </div>
    </body>
    </html>
    """

    print("Opening Native App Window (Loading Screen)...")
    window = webview.create_window(
        WINDOW_TITLE,
        html=loading_html,
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

    # Launch model loading and server initialization asynchronously
    webview.start(init_app_async, window)

    # Clean up background IPFS process on exit
    if ipfs_proc:
        # Run Garbage Collection to delete all unpinned image blocks from disk cache
        ipfs_bin = get_ipfs_bin()
        if ipfs_bin:
            try:
                print("Running local IPFS Garbage Collection to free up disk space...")
                # Run with CREATE_NO_WINDOW (0x08000000) to keep it silent
                subprocess.run([ipfs_bin, "repo", "gc"], capture_output=True, creationflags=0x08000000)
                print("IPFS storage cleaned successfully.")
            except Exception as gc_err:
                print(f"Failed to run IPFS GC: {gc_err}")

        print("Stopping background IPFS daemon...")
        ipfs_proc.terminate()
        try:
            ipfs_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            ipfs_proc.kill()

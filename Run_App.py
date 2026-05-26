import os
import sys
import time
import threading
import urllib.request
import uvicorn
import webview
import keyboard
import subprocess

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
    global hhk, hook_proc_ptr
    try:
        import ctypes
        from ctypes import wintypes
        
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        WH_KEYBOARD_LL = 13
        HC_ACTION = 0

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p),
            ]

        # Define Hook Procedure callback
        HOOKPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, ctypes.c_void_p)

        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p

        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, ctypes.c_void_p]
        user32.CallNextHookEx.restype = wintypes.LPARAM

        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p

        def keyboard_callback(nCode, wParam, lParam):
            if nCode == HC_ACTION:
                kbd = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk = kbd.vkCode
                flags = kbd.flags
                alt_pressed = (flags & 0x20) != 0  # LLKHF_ALTDOWN

                # Block Left/Right Windows keys (0x5B, 0x5C)
                if vk in (0x5B, 0x5C):
                    return 1

                # Block Alt+Tab (vk = 0x09, alt_pressed = True)
                if vk == 0x09 and alt_pressed:
                    return 1

                # Block Alt+Esc (vk = 0x1B, alt_pressed = True)
                if vk == 0x1B and alt_pressed:
                    return 1

                # Block Alt+F4 (vk = 0x70, alt_pressed = True)
                if vk == 0x70 and alt_pressed:
                    return 1

                # Block Ctrl+Esc (vk = 0x1B, Ctrl pressed)
                if vk == 0x1B:
                    ctrl_state = user32.GetAsyncKeyState(0x11) & 0x8000
                    if ctrl_state:
                        return 1

            return user32.CallNextHookEx(hhk, nCode, wParam, lParam)

        hook_proc_ptr = HOOKPROC(keyboard_callback)
        h_mod = kernel32.GetModuleHandleW(None)
        
        # Set the hook
        hhk = user32.SetWindowsHookExW(WH_KEYBOARD_LL, hook_proc_ptr, h_mod, 0)
        if hhk:
            print("Low-level keyboard hook installed. System keys (Win, Alt+Tab, Alt+F4) blocked.")
        else:
            err = kernel32.GetLastError()
            print(f"Failed to install low-level keyboard hook. Error code: {err}")
            
    except Exception as e:
        print(f"Error setting up low-level hook: {e}")

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
            time.sleep(0.05)

    except Exception as e:
        print(f"Kiosk lock error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
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

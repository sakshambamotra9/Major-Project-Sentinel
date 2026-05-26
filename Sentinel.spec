# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

# Paths
PROJECT_ROOT = os.path.abspath('.')
FRONTEND_DIST = os.path.join(PROJECT_ROOT, 'frontend', 'dist')
BACKEND_DIR = os.path.join(PROJECT_ROOT, 'backend')

a = Analysis(
    ['Run_App.py'],
    pathex=[PROJECT_ROOT, BACKEND_DIR],
    binaries=[],
    datas=[
        # Bundle the ONNX model
        (os.path.join(PROJECT_ROOT, 'yolov8n.onnx'), '.'),
        # Bundle the compiled React frontend
        (FRONTEND_DIST, 'frontend/dist'),
        # Bundle backend source files
        (os.path.join(BACKEND_DIR, 'main.py'), 'backend'),
        (os.path.join(BACKEND_DIR, 'models'), 'backend/models'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'fastapi',
        'mediapipe',
        'cv2',
        'onnxruntime',
        'numpy',
        'webview',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Explicitly exclude heavy unused packages
        'torch',
        'torchvision',
        'tensorflow',
        'deepface',
        'ultralytics',
        'matplotlib',
        'IPython',
        'jupyter',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Sentinel_Proctoring',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,       # Compress with UPX to reduce size further
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window — clean app
    icon=None,      # Add an .ico file path here if you have one
)

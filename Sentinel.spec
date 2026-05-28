# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Paths
PROJECT_ROOT = os.path.abspath('.')
FRONTEND_DIST = os.path.join(PROJECT_ROOT, 'frontend', 'dist')
BACKEND_DIR = os.path.join(PROJECT_ROOT, 'backend')

hidden_imports = [
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
    'mediapipe',
    'cv2',
    'onnxruntime',
    'numpy',
    'webview',
    'keyboard',
]

hidden_imports += collect_submodules('fastapi')
hidden_imports += collect_submodules('supabase')
hidden_imports += collect_submodules('dotenv')
hidden_imports += collect_submodules('pydantic')
hidden_imports += collect_submodules('pydantic_core')
hidden_imports += collect_submodules('requests')
hidden_imports += collect_submodules('urllib')

datas = [
    # Bundle the YOLO ONNX model
    (os.path.join(PROJECT_ROOT, 'yolo11n.onnx'), '.'),
    # Bundle the ArcFace ONNX model
    (os.path.join(PROJECT_ROOT, 'arc.onnx'), '.'),
    # Bundle the compiled React frontend
    (FRONTEND_DIST, 'frontend/dist'),
    # Bundle backend source files
    (os.path.join(BACKEND_DIR, 'main.py'), 'backend'),
    (os.path.join(BACKEND_DIR, 'models'), 'backend/models'),
    # Bundle the .env file with Supabase credentials
    (os.path.join(BACKEND_DIR, '.env'), 'backend'),
] + collect_data_files('mediapipe')

a = Analysis(
    ['Run_App.py'],
    pathex=[PROJECT_ROOT, BACKEND_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'torch',
        'torchvision',
        'tensorflow',
        'deepface',
        'ultralytics',
        'IPython',
        'jupyter',
        'notebook',
        'polars',
        'jax',
        'jaxlib',
        'scipy',
        'pandas',
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
    [],
    exclude_binaries=True,
    name='Sentinel_Proctoring',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,       # Compress with UPX to reduce size further
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window — clean app
    uac_admin=True, # Require Administrator privileges to block system/windows keys
    icon=None,      # Add an .ico file path here if you have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Sentinel_Proctoring',
)

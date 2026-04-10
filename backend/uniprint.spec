# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — compiles Flask backend into backend.exe

import os
block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('models.py',           '.'),
        ('extensions.py',       '.'),
        ('closed_state.py',     '.'),
        ('supabase_client.py',  '.'),
        ('api',                 'api'),
        ('workers',             'workers'),
    ],
    hiddenimports=[
        'flask',
        'flask_cors',
        'flask_socketio',
        'engineio',
        'socketio',
        'python_socketio',
        'dotenv',
        'bcrypt',
        'PyPDF2',
        'requests',
        'supabase',
        'zeroconf',
        'apscheduler',
        'apscheduler.schedulers.background',
        'apscheduler.triggers.cron',
        'sqlite3',
        'email.mime.text',
        'email.mime.multipart',
        'smtplib',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy'],
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
    name='backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No console window on Windows
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

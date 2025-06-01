# BOILIE_control.spec

block_cipher = None

from PyInstaller.utils.hooks import collect_submodules
import os

hidden = collect_submodules("ttkbootstrap")

a = Analysis(
    ['BOILIE_control.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Optional: Icons etc.
        # Achtung: KEINE .env hier einfügen!
    ],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
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
    name='gui_control',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)
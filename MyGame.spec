# build_game.spec
# -*- mode: python -*-

import glob
import os
from PyInstaller.utils.hooks import collect_submodules

# Path to working folder
project_folder = r'C:\Users\lalex\Game'

# Entry script
entry_script = os.path.join(project_folder, 'main.py')

# Hidden imports: all .py files in project folder except main.py
hiddenimports = [
    os.path.splitext(os.path.basename(f))[0]
    for f in glob.glob(os.path.join(project_folder, '*.py'))
    if not f.endswith('main.py')
]

# Add all modules in components folder
hiddenimports += collect_submodules('components')

# Include all PNG files in project folder
datas = [(f, '.') for f in glob.glob(os.path.join(project_folder, '*.png'))]

# Analysis
a = Analysis(
    [entry_script],
    pathex=[project_folder],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MyGame',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # change to True if you want a console window
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='MyGame'
)

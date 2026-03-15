# build_game.spec
# -*- mode: python -*-
# python -m PyInstaller MyGame.spec

import glob
import os
from PyInstaller.utils.hooks import collect_submodules

# Path to working folder (current directory)
project_folder = os.path.dirname(os.path.abspath(SPEC))

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

# Filter out excluded modules  
hiddenimports = [imp for imp in hiddenimports if imp not in ['inflect', 'typeguard', 'text_engine']]

# Include data files
datas = []
# PNG files
datas += [(f, '.') for f in glob.glob(os.path.join(project_folder, '*.png'))]
# JSON files (loot tables)
datas += [(f, '.') for f in glob.glob(os.path.join(project_folder, '*.json'))]
# RP folder (sounds, sprites, etc.)
datas += [('RP', 'RP')]
# Markdown documentation
datas += [(f, '.') for f in glob.glob(os.path.join(project_folder, '*.md'))]

a = Analysis(
    [entry_script],
    pathex=[project_folder, os.path.join(project_folder, 'dependencies')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['inflect', 'typeguard'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MyGame',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,  # Temporarily enable to see errors
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_folder, 'icon.ico')
)

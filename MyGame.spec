# MyGame.spec
# -*- mode: python -*-
# Build: python -m PyInstaller MyGame.spec
# 1. Create a clean virtual environment
#python -m venv build_env

# 2. Activate it and install only what the game needs
#build_env\Scripts\activate
#pip install -r requirements.txt
#pip install pyinstaller

# 3. Build from inside the venv
#python build_game.py

import glob
import os
from PyInstaller.utils.hooks import collect_submodules, collect_all

project_folder = os.path.dirname(os.path.abspath(SPEC))


# ── Native OpenGL packages (moderngl + glcontext) ─────────────────────────────
# collect_all handles submodules and data; the .pyd native extensions must be
# listed explicitly in binaries because collect_dynamic_libs misses them.

_mgl_datas,  _mgl_bins,  _mgl_hidden  = collect_all('moderngl')
_glc_datas,  _glc_bins,  _glc_hidden  = collect_all('glcontext')

import site
_sp = site.getsitepackages()
for _d in _sp:
    _mgl_pyd = os.path.join(_d, 'moderngl', 'mgl.cp312-win_amd64.pyd')
    _glc_pyd = os.path.join(_d, 'glcontext', 'wgl.cp312-win_amd64.pyd')
    if os.path.exists(_mgl_pyd):
        _mgl_bins.append((_mgl_pyd, 'moderngl'))
    if os.path.exists(_glc_pyd):
        _glc_bins.append((_glc_pyd, 'glcontext'))


# ── Hidden imports ────────────────────────────────────────────────────────────

hiddenimports = [
    os.path.splitext(os.path.basename(f))[0]
    for f in glob.glob(os.path.join(project_folder, '*.py'))
    if not f.endswith('main.py')
]
hiddenimports += collect_submodules('components')
hiddenimports += collect_submodules('worldgen')
hiddenimports += _mgl_hidden + _glc_hidden
hiddenimports = [
    imp for imp in hiddenimports
    if imp not in ['inflect', 'typeguard', 'text_engine']
]


# ── Data files ────────────────────────────────────────────────────────────────

def collect_tree(src_dir, dest_dir=None):
    """Recursively collect all files from src_dir, preserving relative paths."""
    result = []
    if not os.path.isdir(src_dir):
        return result
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for fname in files:
            src  = os.path.join(root, fname)
            rel  = os.path.relpath(root, project_folder)
            dest = dest_dir if dest_dir is not None else rel
            result.append((src, dest))
    return result


datas = []

# Root-level PNGs (tileset, icon, etc.)
datas += [(f, '.') for f in glob.glob(os.path.join(project_folder, '*.png'))]

# JSON config files
datas += collect_tree(os.path.join(project_folder, 'json'))

# Audio, graphics, tileset (RP/)
datas += collect_tree(os.path.join(project_folder, 'RP'))

# Portrait part layers — required for NPC/player portrait compositing
datas += collect_tree(os.path.join(project_folder, 'components', 'portrait_parts'))

# Character generation assets (base portrait images)
datas += collect_tree(os.path.join(project_folder, 'chargen'))

# Ensure logs directory exists in the bundle so the game can write to it
logs_dir = os.path.join(project_folder, 'logs')
os.makedirs(logs_dir, exist_ok=True)
_gitkeep = os.path.join(logs_dir, '.gitkeep')
if not os.path.exists(_gitkeep):
    open(_gitkeep, 'w').close()
datas += [(_gitkeep, 'logs')]


# ── Analysis ──────────────────────────────────────────────────────────────────

datas += _mgl_datas + _glc_datas

a = Analysis(
    [os.path.join(project_folder, 'main.py')],
    pathex=[
        project_folder,
        os.path.join(project_folder, 'dependencies'),
    ],
    binaries=[] + _mgl_bins + _glc_bins,
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
    name='Dungeons of Aerrok',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=True,   # Always build with console; game hides it via ctypes based on settings
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_folder, 'icon.ico'),
)

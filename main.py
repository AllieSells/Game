print("Starting DoA...")
import time
# Package with python -m PyInstaller MyGame.spec
initial_time = time.time() # Track total loading


import os
os.environ["SDL_APP_NAME"] = "DoA: Dungeons of Ærrok"
os.environ["SDL_APP_ID"] = "com.loxen.doa"
os.environ["SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR"] = "0"  
os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"] = "0"
os.environ["SDL_HINT_RENDER_DRIVER"] = "D3D11"
# Set version
os.environ["SDL_RENDER_SCALE_QUALITY"] = "1"  #  filtering when tiles are scaled
import warnings
import sys
import hashlib

from PIL import Image
import numpy as np
import random
import tcod.sdl.mouse

import sounds
sounds.play_boot_sound()
# Cursor variables will be initialized after tcod context is created
cursor = None
cursor_click = None

# CRT safety/fallback flags (module level)
_crt_force_fast_path = False

# Add dependencies folder to sys.path immediately
sys.path.append(os.path.join(os.path.dirname(__file__), "dependencies"))
log_path = os.path.join(os.path.dirname(__file__), "logs/log.txt")
if not os.path.exists(os.path.dirname(log_path)):
    os.makedirs(os.path.dirname(log_path))
    with open(log_path, "w") as log_file:
        log_file.write("Log file created.\n")
        log_file.write(f"{time.ctime()}: Game started.\n")
        
else:
    # Clear existing log file at startup
    with open(log_path, "w") as log_file:
        log_file.write("Log file cleared at startup.\n")
        log_file.write(f"{time.ctime()}: Game started.\n")


# --- Render checkpoint logger ---
# Opened once and kept open so each flush is guaranteed to reach disk before
# a GPU TDR can kill the process silently.
_render_log_file = open(log_path, "a", buffering=1)  # line-buffered
_render_frame = 0


def _dlog(msg: str) -> None:
    """Generic debug log message with timestamp."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    _render_log_file.write(f"[{timestamp}] [frame {_render_frame}] {msg}\n")
    _render_log_file.flush()

def _rlog(msg: str) -> None:
    """Write a checkpoint line to the log file and flush immediately."""
    _render_log_file.write(f"[frame {_render_frame}] {msg}\n")
    _render_log_file.flush()

# Suppress warnings immediately to prevent spam
if not os.environ.get("GAME_SHOW_WARNINGS"):
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning)

def get_data_path(filename):
    """Get the correct path for data files in both development and PyInstaller."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller executable
        base_path = sys._MEIPASS
    else:
        # Running in development
        base_path = os.path.dirname(__file__)
    return os.path.join(base_path, filename)

# Import tcod and create window as fast as possible

print("Opening window...")
import tcod
print(f"Version: {tcod.__version__}")

# Import color module immediately for loading screen
try:
    import color
except ImportError:
    # Fallback colors if color module fails
    class color:
        fantasy_text = (200, 180, 140)
        gold_accent = (255, 215, 0)
        dark_gray = (64, 64, 64)
        parchment_light = (180, 160, 120)

# Create window immediately
screen_width = 80
screen_height = 50
 
# Load tileset immediately - create a basic one if file fails
try:
    tileset = tcod.tileset.load_tilesheet(  
        get_data_path("RP/AllieClassic.png"), 16, 16, tcod.tileset.CHARMAP_CP437
    )
    tcod.tileset.Tileset.__add__
except Exception as e:
    print(f"Failed to load custom tileset: {e}, using basic tileset")
    # Create a basic empty tileset as fallback
    tileset = tcod.tileset.Tileset(16, 16)

# Load extra overlay sprites from RP/extras.png into PUA codepoints (U+E000+).
import sprite_manager
sprite_manager.load_extras(
    tileset,
    get_data_path("RP/extras.png"),
    normals_path=get_data_path("RP/extras_normals.png"),
)


# Create window immediately
context = tcod.context.new(
    columns=screen_width,
    rows=screen_height,
    width=1280,
    height=800,
    tileset=tileset,
    title="DoA: Dungeons of Ærrok ... Loading...",
    vsync=False,  # Software frame limiter (time.sleep) handles fps cap.
                  # vsync=True with D3D11 fullscreen causes Present() to block
                  # indefinitely when 500+ GPU calls exceed the vblank window.
)

from gpu_stack import (
    generate_scanlines_texture,
    create_vignette_texture,
    create_glare_texture,
    DegaussAnimation,
    CRTSwitchAnimation,
    VHSGlitchAnimation,
    VideoModeSwitchAnimation,
)
from modern_gl_lightmap_composer import ModernGLLightmapComposer
import render_boot_screen

# --- Procedural scanlines ---
renderer = context.sdl_renderer


# Scanline parameters (tweak these)
scanline_density = 2.0    # higher = more scanlines (thinner)
scanline_intensity = 0.35 # 0.0 = invisible, 1.0 = max darkening at troughs

try:
    scanlines_np = generate_scanlines_texture(scanline_density, scanline_intensity)
    scanlines_tex = renderer.upload_texture(scanlines_np)
    scanlines_tex.blend_mode = tcod.sdl.render.BlendMode.MOD
    scanlines_h = scanlines_np.shape[0]  # one sine period
    scanlines_scroll = 0.0
    scanlines_speed = 10.0  # pixels per second
except Exception:
    scanlines_tex = None
    scanlines_h = 2
    scanlines_scroll = 0.0
    scanlines_speed = 10.0

# Active degauss instance — set to a DegaussAnimation to run it; None = idle.
_active_degauss: "DegaussAnimation | None" = None
# Active VHS glitch — set to a VHSGlitchAnimation on game over; None = idle.
_active_vhs_glitch: "VHSGlitchAnimation | None" = None

vignette_tex = create_vignette_texture(renderer)
glare_tex = create_glare_texture(renderer)

game_width = 80
game_height = 40

# ZOOM CONTROL: Change this value to adjust game zoom level
game_zoom = 2.5  # Zoom level for game view rendering

# Dynamically calculate viewport size based on zoom
# Reserve ~11 rows for HUD at bottom of screen
hud_reserved_rows = 11
game_view_width = int(screen_width / game_zoom)
game_view_height = int((screen_height - hud_reserved_rows) / game_zoom)

game_console = tcod.console.Console(game_view_width, game_view_height, order="F")
ui_console = tcod.console.Console(screen_width, screen_height, order="F")

# Initialize tileset atlas and console renderer for later use in main()
tileset_atlas = tcod.render.SDLTilesetAtlas(renderer, tileset)
ui_console_renderer = tcod.render.SDLConsoleRender(tileset_atlas)

# Load settings before GPU initialization
def load_settings():
    """Load settings from JSON file."""
    import json  # Import here if not already imported
    try:
        with open(get_data_path("json/settings.json"), 'r') as f:
            content = f.read()
            # Remove JSON comments
            lines = [line for line in content.split('\n') if not line.strip().startswith('//')]
            clean_content = '\n'.join(lines)
            return json.loads(clean_content)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"fullscreen": False, "audio": 50, "crt_scanlines": True, "crt_vignette": True, "crt_bloom": True, "crt_ca": True, "crt_curvature": True}

settings = load_settings()

# Initialize GPU stack for CRT effects (used later in main loop and world gen)
from gpu_stack import GPUStack
gpu = GPUStack(
    renderer=renderer,
    tileset=tileset,
    game_view_width=game_view_width,
    game_view_height=game_view_height,
    screen_width=screen_width,
    screen_height=screen_height,
    get_data_path_fn=get_data_path,
)

# Sync CRT toggles from settings into the gpu stack
gpu.crt_scanlines_on = settings.get("crt_scanlines", True)
gpu.crt_vignette_on  = settings.get("crt_vignette",  True)
gpu.crt_bloom_on     = settings.get("crt_bloom",      True)
gpu.crt_ca_on        = settings.get("crt_ca",         True)
gpu.crt_curvature_on = settings.get("crt_curvature",  True)
gpu.crt_bands        = 116  # smooth curvature
# Optional unification bridge (default False): when True, GPUStack will attempt
# a ModernGL lightmap compose callback before falling back to SDL lightmap upload.
gpu.enable_modern_gl_lightmap_unified = bool(settings.get("modern_gl_lightmap_unified", False))
_modern_gl_lm_composer = ModernGLLightmapComposer(renderer)
if gpu.enable_modern_gl_lightmap_unified:
    gpu.modern_gl_lightmap_composer = _modern_gl_lm_composer
    _dlog("Unified ModernGL lightmap bridge: enabled (composer attached).")
else:
    gpu.modern_gl_lightmap_composer = None

_transparency_idx_cache: dict = {}  # (h, w, tile_h, tile_w) -> (x_idx, y_idx)

def render_console_with_transparency(console: tcod.console.Console) -> np.ndarray:
    """Render a console to RGBA pixels and make untouched blank cells transparent."""
    pixels = tileset.render(console)
    blank_mask = (console.ch == ord(" ")) & np.all(console.bg == 0, axis=2)
    fade_mask = (
        (console.ch == ord(" "))
        & np.all(console.bg <= (12, 12, 16), axis=2)
        & ~blank_mask
    )
    tile_h, tile_w = tileset.tile_height, tileset.tile_width

    cell_alpha = np.full(console.ch.shape, 255, dtype=np.uint8)
    cell_alpha[blank_mask] = 0
    cell_alpha[fade_mask] = 144

    alpha_channel = pixels[:, :, 3]
    cache_key = (alpha_channel.shape[0], alpha_channel.shape[1], tile_h, tile_w)
    if cache_key not in _transparency_idx_cache:
        _transparency_idx_cache[cache_key] = (
            np.arange(alpha_channel.shape[0]) // tile_h,
            np.arange(alpha_channel.shape[1]) // tile_w,
        )
    x_idx, y_idx = _transparency_idx_cache[cache_key]
    alpha_channel[:, :] = cell_alpha.T[x_idx[:, None], y_idx[None, :]]

    return pixels


def get_console_signature(console: tcod.console.Console) -> bytes:
    """Return a stable digest for ch/fg/bg so UI textures can be upload-cached."""
    digest = hashlib.blake2b(digest_size=16)
    digest.update(console.ch.tobytes(order="C"))
    digest.update(console.fg.tobytes(order="C"))
    digest.update(console.bg.tobytes(order="C"))
    return digest.digest()

def get_ui_mouse_tile(position: tuple[float, float], window_w: float, window_h: float) -> tuple[int, int]:
    """Return UI-layer tile coordinates for the base 80x50 layout."""
    pixel_x, pixel_y = position
    base_tile_w = window_w / screen_width
    base_tile_h = window_h / screen_height
    tile_x = int(pixel_x / base_tile_w)
    tile_y = int(pixel_y / base_tile_h)
    tile_x = max(0, min(screen_width - 1, tile_x))
    tile_y = max(0, min(screen_height - 1, tile_y))
    return tile_x, tile_y

def get_game_screen_tile(position: tuple[float, float], window_w: float, window_h: float) -> tuple[int, int]:
    """Return viewport-relative game-console coordinates for the zoomed gameplay area."""
    pixel_x, pixel_y = position
    base_tile_w = window_w / screen_width
    base_tile_h = window_h / screen_height

    tile_x = int(pixel_x / (base_tile_w * game_zoom))
    tile_y = int(pixel_y / (base_tile_h * game_zoom))
    tile_x = max(0, min(game_view_width - 1, tile_x))
    tile_y = max(0, min(game_view_height - 1, tile_y))
    return tile_x, tile_y


class GPUMenuBackgroundAnimation:
    """Preload and play a fullscreen menu animation directly as GPU textures."""

    def __init__(
        self,
        renderer,
        get_data_path_fn,
        frame_pattern: str = "RP/background/{:04d}.png",
        frame_count: int = 250,
        fps: int = 24,
        start_index: int = 1,
    ) -> None:
        self.renderer = renderer
        self.frames = []
        self.current_frame = 0
        self.frame_time = 1.0 / max(1, fps)
        self.last_update = time.time()
        self.frame_w = 0
        self.frame_h = 0

        for i in range(start_index, start_index + frame_count):
            frame_rel_path = frame_pattern.format(i)
            frame_abs_path = get_data_path_fn(frame_rel_path)
            if not os.path.isfile(frame_abs_path):
                break
            try:
                img = Image.open(frame_abs_path).convert("RGBA")
                px = np.array(img, dtype=np.uint8)
                tex = renderer.upload_texture(px)
                tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                self.frames.append(tex)
                if self.frame_w == 0 or self.frame_h == 0:
                    self.frame_h, self.frame_w = px.shape[:2]
            except Exception as exc:
                print(f"Menu background frame load failed ({frame_rel_path}): {exc}")
                break

    @property
    def available(self) -> bool:
        return bool(self.frames)

    def _step(self) -> None:
        if len(self.frames) <= 1:
            return
        now = time.time()
        elapsed = now - self.last_update
        if elapsed < self.frame_time:
            return
        steps = int(elapsed / self.frame_time)
        self.current_frame = (self.current_frame + steps) % len(self.frames)
        self.last_update += steps * self.frame_time

    def draw(self, window_w: int, window_h: int) -> bool:
        if not self.frames:
            return False
        self._step()
        # Stretch-fill mode: no letterbox and no cropping.
        self.renderer.copy(self.frames[self.current_frame], dest=(0, 0, window_w, window_h))
        return True

boot_str = []
def show_loading_screen(context, console, status: str) -> None:
    """Display a DOS BIOS-style boot loading screen with full CRT effects."""
    for _ in tcod.event.get():
        pass
    
    global boot_str, ui_console_renderer, gpu, renderer, scanlines_tex, scanlines_h, vignette_tex, glare_tex
    boot_str.append(status)

    window_w, window_h = context.sdl_window.size
    base_tile_w = window_w / screen_width
    base_tile_h = window_h / screen_height
    
    # Update GPU frame dimensions so barrel distortion works correctly
    gpu.update_frame_dims(window_w, window_h, base_tile_w, base_tile_h, game_zoom)
    
    # Render to scene_tex for CRT processing
    gpu.ensure_bloom_targets(window_w, window_h)
    with renderer.set_render_target(gpu.scene_tex):
        renderer.draw_color = (0, 0, 0, 255)
        renderer.clear()
        render_boot_screen.render_boot_screen(renderer, boot_str, window_w, window_h, ui_console_renderer)
    
    # Apply barrel distortion + chromatic aberration: scene_tex → post_crt_tex
    gpu.apply_barrel_and_ca(window_w, window_h)
    
    # Blit post_crt_tex to framebuffer with full CRT effects
    renderer.draw_color = (0, 0, 0, 255)
    renderer.clear()
    gpu.post_crt_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
    gpu.post_crt_tex.alpha_mod = 255
    gpu.post_crt_tex.color_mod = (255, 255, 255)
    renderer.copy(gpu.post_crt_tex, dest=(0, 0, window_w, window_h))
    
    # Apply scanlines
    if gpu.crt_scanlines_on and scanlines_tex is not None:
        y = 0
        while y < window_h:
            draw_h = min(scanlines_h, window_h - y)
            if draw_h > 0:
                renderer.copy(scanlines_tex,
                              source=(0, 0, 1, draw_h),
                              dest=(0, y, window_w, draw_h))
            y += scanlines_h
    
    if gpu.crt_vignette_on and vignette_tex is not None:
        renderer.copy(vignette_tex, dest=(0, 0, window_w, window_h))
    
    if glare_tex is not None:
        renderer.copy(glare_tex, dest=(0, 0, window_w, window_h))
    
    # Apply bloom (must be after vignette/glare, before present)
    if gpu.crt_bloom_on:
        gpu.gpu_bloom(gpu.post_crt_tex, window_w, window_h)
    
    renderer.present()

# Show loading screen immediately
show_loading_screen(context, ui_console, "Initializing hardware...")




# Now load remaining modules
import json

start_time = time.time() # Track total loading


# Continue with module imports


show_loading_screen(context, ui_console, "Checking extended memory... OK")
import exceptions
str = (f"Loaded exceptions module in {time.time() - start_time:.2f} seconds")
print(str)
with open(get_data_path('logs/log.txt'), 'a') as log_file:
    log_file.write(str + "\n")

start_time = time.time() # Track total loading
show_loading_screen(context, ui_console, "Loading device drivers...")
import input_handlers
import inventory_ui
str = (f"Loaded input_handlers module in {time.time() - start_time:.2f} seconds")
print(str)
with open(get_data_path('logs/log.txt'), 'a') as log_file:
    log_file.write(str + "\n")

start_time = time.time() # Track total loading
show_loading_screen(context, ui_console, "Drive A: detected. Insert game disk and press any key...")
import setup_game
str = (f"Loaded setup_game module in {time.time() - start_time:.2f} seconds")
print(str)
with open(get_data_path('logs/log.txt'), 'a') as log_file:
    log_file.write(str + "\n")

start_time = time.time() # Track total loading
show_loading_screen(context, ui_console, "Reading from A:\\...")
import tcod.sdl.video
import traceback

str = (f"Loaded tcod.sdl.video and traceback modules in {time.time() - start_time:.2f} seconds")
print(str)
with open(get_data_path('logs/log.txt'), 'a') as log_file:
    log_file.write(str + "\n")

# Global reference for settings access
_game_context = None
# Global reference to the active GPUStack — set in main() so reload_crt_settings can sync it
_gpu_instance = None

# --- CRT toggle flags (loaded from settings.json) ---
_crt_scanlines_on = True
_crt_vignette_on = True
_crt_bloom_on = True
_crt_ca_on = True
_crt_curvature_on = True

def reload_crt_settings(gpu_stack=None):
    """Reload CRT toggle flags from settings.json, optionally syncing a GPUStack object."""
    global _crt_scanlines_on, _crt_vignette_on, _crt_bloom_on, _crt_ca_on, _crt_curvature_on
    s = load_settings()
    _crt_scanlines_on = s.get("crt_scanlines", True)
    _crt_vignette_on = s.get("crt_vignette", True)
    _crt_bloom_on = s.get("crt_bloom", True)
    _crt_ca_on = s.get("crt_ca", True)
    _crt_curvature_on = s.get("crt_curvature", True)
    target = gpu_stack if gpu_stack is not None else _gpu_instance
    if target is not None:
        target.crt_scanlines_on = _crt_scanlines_on
        target.crt_vignette_on = _crt_vignette_on
        target.crt_bloom_on = _crt_bloom_on
        target.crt_ca_on = _crt_ca_on
        target.crt_curvature_on = _crt_curvature_on


"""
GAME RULES:
- Each tile is 



"""

# By default suppress noisy FutureWarning/DeprecationWarning messages from
# third-party libraries (numpy, tcod, etc). Set the environment variable
# GAME_SHOW_WARNINGS=1 to opt into seeing warnings during development.
# (Do this early, before heavy imports)
if not os.environ.get("GAME_SHOW_WARNINGS"):
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning)

def toggle_fullscreen(context: tcod.context.Context) -> None:
    """Toggle context window between fullscreen and windowed mode"""
    
    if not context:
        return
        
    window = context.sdl_window
    if not window:
        return

    if window.fullscreen:
        window.fullscreen = False

    else:
        window.fullscreen = tcod.sdl.video.WindowFlags.FULLSCREEN

def save_game(handler, filename):
    # If current event handler has active engine then save it
    if isinstance(handler, input_handlers.EventHandler):
        handler.engine.save_as(filename)
        print("Game saved.")    


def main() -> None:
    
    global _game_context, context, game_console, ui_console, cursor, cursor_click, _crt_force_fast_path, _render_frame, _active_degauss, _active_vhs_glitch
    
    # Use the global context and console that were created during initial loading
    _game_context = context

    # Transition helper: avoid heavy CRT passes while entering gameplay
    previous_has_game_view = False
    transition_frame_counter = 0
    transition_cooldown_frames = 0
    quick_start = os.environ.get("DOA_QUICK_START", "0") == "1"
    # Continue with actual loading operations
    if not quick_start:
        show_loading_screen(context, ui_console, "A:\\SYSTEM.DAT loaded OK")
    settings = load_settings()
    setting_fullscreen = settings.get("fullscreen", False)
    reload_crt_settings()
    if not quick_start:
        time.sleep(0.3)
        show_loading_screen(context, ui_console, "A:\\MENU.EXE found. Launching...")
        handler: input_handlers.BaseEventHandler = setup_game.MainMenu()
        time.sleep(0.3)
    else:
        engine = setup_game.new_game()
        handler = input_handlers.MainGameEventHandler(engine)
        sounds.stop_menu_ambience()
        sounds.stop_all_music()
        sounds.start_dungeon_music()
    
    if not quick_start:
        show_loading_screen(context, ui_console, "Allocating memory blocks...")
    # Update context title
    context.sdl_window.title = "DoA: Dungeons of Ærrok"
    if not quick_start:
        time.sleep(0.3)
    # Set initial fullscreen state based on settings
    window = context.sdl_window
    if window and setting_fullscreen:
        window.fullscreen = True
        print("DEBUG: Set initial fullscreen mode from settings")

    if not quick_start:
        show_loading_screen(context, ui_console, "Ready. Type A:\\GAME to play.")
    str = (f"Finished loading in {time.time() - initial_time:.2f} seconds")
    print(str)
    with open(get_data_path('logs/log.txt'), 'a') as log_file:
        log_file.write(str + "\n")
        log_file.write(f"Settings loaded: {settings}\n")
        log_file.write(f"=========================================================================================================================================================================================================================\n")
    # Brief pause to show completion
    if not quick_start:
        time.sleep(0.3)
    
    # Load custom cursors after tcod context is fully initialized
    cursor_point = Image.open(get_data_path("RP/cursors/cursor_point.png")).convert("RGBA")
    pixels_cursor_point = np.array(cursor_point, dtype=np.uint8)
    cursor = tcod.sdl.mouse.new_color_cursor(pixels_cursor_point, (0, 0))   

    cursor_click_img = Image.open(get_data_path("RP/cursors/cursor_click.png")).convert("RGBA")
    pixels_cursor_click = np.array(cursor_click_img, dtype=np.uint8)
    cursor_click = tcod.sdl.mouse.new_color_cursor(pixels_cursor_click, (0, 0))

    cursor_bag_img = Image.open(get_data_path("RP/cursors/cursor_bag.png")).convert("RGBA")
    pixels_cursor_bag = np.array(cursor_bag_img, dtype=np.uint8)
    cursor_bag = tcod.sdl.mouse.new_color_cursor(pixels_cursor_bag, (0, 0))

    cursor_interact_img =  Image.open(get_data_path("RP/cursors/cursor_open.png")).convert("RGBA")
    pixels_cursor_interact = np.array(cursor_interact_img, dtype=np.uint8)
    cursor_interact = tcod.sdl.mouse.new_color_cursor(pixels_cursor_interact, (0, 0))

    cursor_sword_img = Image.open(get_data_path("RP/cursors/cursor_sword.png")).convert("RGBA")
    pixels_cursor_sword = np.array(cursor_sword_img, dtype=np.uint8)
    cursor_sword = tcod.sdl.mouse.new_color_cursor(pixels_cursor_sword, (0, 0))
    
    cursor_walk_img = Image.open(get_data_path("RP/cursors/cursor_walk.png")).convert("RGBA")
    pixels_cursor_walk = np.array(cursor_walk_img, dtype=np.uint8)
    cursor_walk = tcod.sdl.mouse.new_color_cursor(pixels_cursor_walk, (0, 0))

    import render_functions
    target_fps = 30
    frame_time = 1.0 / target_fps
    last_time = time.time()
    # tileset_atlas and ui_console_renderer already created earlier for boot screen
    game_console_renderer = tcod.render.SDLConsoleRender(tileset_atlas)
    # ui_console_renderer already created earlier for boot screen CRT effects
    debug_console_renderer = tcod.render.SDLConsoleRender(tileset_atlas)
    # Dedicated renderer for the 40×25 inventory grid (never shares state with game renderer)
    inv_console_renderer = tcod.render.SDLConsoleRender(tileset_atlas)
    debug_console = tcod.console.Console(40, 24, order="F")
    # 1×1 dim texture stretched over full screen for overlay fade (GPU-only, no CPU pixel work)
    dim_pixels = np.array([[[20, 20, 30, 100]]], dtype=np.uint8)
    dim_tex = renderer.upload_texture(dim_pixels)
    dim_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
    # 1×1 texture for the equipment panel background (_BG colour, fully opaque).
    # Stretched over the eq_grid area before the body diagram PNG so background matches the panel.
    _eq_bg_pixels = np.array([[[25, 18, 12, 255]]], dtype=np.uint8)
    _eq_bg_tex = renderer.upload_texture(_eq_bg_pixels)
    _eq_bg_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
    # Body diagram PNG — load RP/eqback.png as the equipment panel background art.
    _body_diagram_tex = None
    _body_diagram_path = get_data_path("RP/eqback.png")
    if os.path.isfile(_body_diagram_path):
        try:
            _bdiag_img = Image.open(_body_diagram_path).convert("RGBA")
            _bdiag_np  = np.array(_bdiag_img, dtype=np.uint8)
            _body_diagram_tex = renderer.upload_texture(_bdiag_np)
            _body_diagram_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
        except Exception as _e:
            print(f"eqback.png failed to load: {_e}")

    # Body-part damage overlay textures — one PNG per part in RP/body_parts/.
    # Each PNG should be a white (255,255,255) silhouette on a transparent background.
    # SDL color_mod tints the white pixels to the damage colour each frame;
    # alpha_mod controls opacity so undamaged parts are invisible.
    # Naming matches BodyPartType: HEAD.png, TORSO.png, LEFT_ARM.png, etc.
    _BODY_PART_MASK_NAMES = [
        "HEAD", "TORSO", "LEFT_ARM", "RIGHT_ARM",
        "LEFT_HAND", "RIGHT_HAND",
        "LEFT_LEG", "RIGHT_LEG",
        "LEFT_FOOT", "RIGHT_FOOT",
    ]
    _body_part_texes: dict = {}  # {part_name: Texture}
    _body_parts_dir = get_data_path("RP/body_parts")
    for _bpn in _BODY_PART_MASK_NAMES:
        _bpp = os.path.join(_body_parts_dir, f"{_bpn}.png")
        if os.path.isfile(_bpp):
            try:
                _bpimg = Image.open(_bpp).convert("RGBA")
                _bpnp  = np.array(_bpimg, dtype=np.uint8)
                _bptex = renderer.upload_texture(_bpnp)
                _bptex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                _body_part_texes[_bpn] = _bptex
            except Exception as _e:
                print(f"body_parts/{_bpn}.png failed: {_e}")

    # --- Regenerate procedural scanlines for current window size ---
    scanlines_np = generate_scanlines_texture(scanline_density, scanline_intensity)
    scanlines_tex = renderer.upload_texture(scanlines_np)
    scanlines_tex.blend_mode = tcod.sdl.render.BlendMode.MOD
    scanlines_h = scanlines_np.shape[0]
    scanlines_scroll = 0.0
    scanlines_speed = 10.0  # pixels per second
    game_tex = None
    ui_tex = None
    overlay_popup_console = None   # small console sized to menu bounding box (fallback path)
    overlay_popup_tex     = None   # BLEND-mode GPU texture for fallback path
    overlay_popup_dest    = None   # screen dest rect for popup
    overlay_popup_src_rect = None   # source rect in ui_tex (pixel coords) for GPU-direct path
    # Dialogue portrait texture cache — lazy-loaded when a dialogue opens
    _dialogue_portrait_tex  = None   # GPU BLEND texture for NPC portrait PNG
    _dialogue_portrait_path = None   # file path used to build _dialogue_portrait_tex
    overlay_hints_console = None   # 1-row sub-console for context hints (GPU-direct path)
    overlay_hints_tex     = None   # BLEND-mode GPU texture for hints row
    overlay_hints_dest    = None   # screen dest rect for hints row
    cached_overlay_handler = None
    menu_ui_tex = None
    menu_ui_signature = None
    menu_ui_cached_handler = None
    menu_ui_cached_token = None
    menu_static_tex = None
    menu_static_handler = None
    menu_static_token = None
    menu_static_console = None
    menu_dynamic_console = None
    menu_dynamic_tex = None
    menu_dynamic_token = None
    menu_dynamic_handler = None
    menu_dynamic_region = (0, 0, 0, 0)
    # Inspect-overlay (F3 / LookHandler) cached UI texture --- rebuilt only when
    # mouse_location changes so render_ui_overlay() isn't called every frame.
    inspect_ui_tex          = None  # BLEND-mode GPU texture of last UI render
    inspect_ui_cursor_cache = None  # (cursor_x, cursor_y) that produced that texture
    inspect_sub_console     = None  # small 35×30 console for sidebar-only pixel conversion
    inspect_hints_console   = None  # 1-row console for context hints BLEND texture
    inspect_hints_tex       = None  # BLEND-mode GPU texture for context hints row
    inspect_preview_tex     = None  # GPU texture for the scaled 7x7 inspect preview console
    _inspect_preview_dest   = None  # screen dest rect for the scaled preview texture
    _inspect_sidebar_dest   = None  # screen dest rect for sidebar panel
    _prev_inspect_overlay   = False # True when previous frame was inspect_overlay_view
    overlay_dirty = True
    _last_dirty_ui_tile = None  # track tile under cursor to avoid per-pixel dirty
    # SelectIndexHandler animated cursor — BLEND SDL texture drawn after lightmap.
    _map_cursor_tex     = None  # BLEND-mode GPU texture (32×32 cursor sprite)
    _map_cursor_last_cp = -1    # cursor codepoint currently baked into _map_cursor_tex
    _lag_profiler_tex   = None  # BLEND-mode texture for F1 profiler overlay

    # Precompute texture source sizes for curvature helper
    _game_tex_w = game_console.width * tileset.tile_width
    _game_tex_h = game_console.height * tileset.tile_height
    _ui_tex_w = screen_width * tileset.tile_width
    _ui_tex_h = screen_height * tileset.tile_height
    _dbg_tex_w = 40 * tileset.tile_width
    _dbg_tex_h = 9 * tileset.tile_height

    # GPU stack and CRT settings already initialized earlier for boot screen
    global _gpu_instance
    _gpu_instance = gpu

    # Convenience aliases used in the loop below
    def copy_curved(tex, dest, source=None, src_size=None):
        gpu.copy_curved(tex, dest, source=source, src_size=src_size)
    def undistort_mouse(px, py):
        return gpu.undistort_mouse(px, py)



    # Set initial cursor (cursors were already loaded at top of file)
    tcod.sdl.mouse.set_cursor(cursor)
    _mouse_held = False

    # CRT power-switch state for the LoadingScreen world-generation transition.
    # _gen_scene_tex is a rolling snapshot of the last non-LoadingScreen frame
    # (main menu / seed entry) so the screen-off shrinks the correct image.
    _crt_off_played         = False  # True once the screen-off anim has run
    _crt_on_played          = False  # True once the screen-on  anim has run
    _gen_scene_tex          = None   # TARGET texture — last pre-gen post-CRT frame
    _gen_scene_tex_size     = (0, 0) # (w, h) of _gen_scene_tex
    _suppress_degauss_once  = False  # skip auto-degauss after CRT-switch entry
    _gen_bar_start_time     = None   # monotonic time when gen thread started
    # CRT power-on capture: after gen, we flip to MainGameEventHandler first,
    # then let the game render one full frame, capture it, and reveal it via play_on.
    _crt_on_capture_pending = False  # waiting to capture the first real game frame
    _crt_on_scene_tex       = None   # captured game frame for play_on
    _crt_on_scene_tex_size  = (0, 0)

    # Load channel splash overlays and kick off the menu one immediately
    gpu.load_channel_overlays(
        get_data_path("RP/ch032.png"),
        get_data_path("RP/ch000.png"),
    )
    gpu.start_wobble()
    gpu.start_channel_overlay("menu")

    menu_bg_anim = GPUMenuBackgroundAnimation(
        renderer=renderer,
        get_data_path_fn=get_data_path,
        frame_pattern="RP/background/{:04d}.png",
        frame_count=250,
        fps=24,
        start_index=1,
    )
    setup_game.set_gpu_menu_background_enabled(menu_bg_anim.available)

    try:
        last_frame = time.time()
        while True:
            now = time.time()
            delta = now - last_frame
            last_frame = now
            #_dlog(f"Main loop start: delta={delta:.4f}s")
            # Process deferred handler transitions (e.g., GameOver) after one final frame update.
            pending_engine = getattr(handler, 'engine', None)
            if pending_engine is not None:
                pending_handler = getattr(pending_engine, '_pending_handler', None)
                pending_ready = getattr(pending_engine, '_pending_handler_ready', False)
                if pending_handler is not None:
                    if pending_ready:
                        handler = pending_handler
                        pending_engine._pending_handler = None
                        pending_engine._pending_handler_ready = False
                        # Ensure rendering resets overlay caches when handler changes.
                        overlay_dirty = True
                        # Fire degauss + VHS glitch when the player dies
                        if isinstance(handler, input_handlers.GameOverEventHandler):
                            _active_degauss  = DegaussAnimation(renderer)
                            _active_vhs_glitch = VHSGlitchAnimation(renderer)
                    else:
                        pending_engine._pending_handler_ready = True

            hint = getattr(getattr(handler, 'engine', None), 'cursor_hint', None)
            if hint == 'bag':
                tcod.sdl.mouse.set_cursor(cursor_bag)
            elif hint == "fight":
                tcod.sdl.mouse.set_cursor(cursor_sword)
            elif hint == 'interact':
                tcod.sdl.mouse.set_cursor(cursor_interact)
            elif hint == 'walk':
                tcod.sdl.mouse.set_cursor(cursor_walk)
            elif _mouse_held:
                tcod.sdl.mouse.set_cursor(cursor_click)
            else:
                tcod.sdl.mouse.set_cursor(cursor)

            active_engine = getattr(handler, "engine", None)
            # Suppress game-view detection while LoadingScreen generation is still
            # in progress — engine.game_map exists before game_load=True,
            # which would prematurely fire TRANSITION and break the CRT timing.
            _loading_in_progress = (
                hasattr(handler, 'game_load')
                and not handler.game_load
                and isinstance(handler, setup_game.LoadingScreen)
            )
            has_game_view = (
                active_engine is not None
                and getattr(active_engine, "game_map", None) is not None
                and not _loading_in_progress
            )
            map_overlay_view = (
                has_game_view
                and isinstance(handler, input_handlers.SelectIndexHandler)
            )
            inspect_overlay_view = isinstance(handler, (input_handlers.LookHandler, input_handlers.EntityDebugHandler))
            main_game_view = (
                has_game_view
                and isinstance(handler, input_handlers.MainGameEventHandler)
            )
            fast_main_view = main_game_view  # debug overlay uses dirty-tracking, no need to exclude
            needs_live_game_frame = main_game_view or game_tex is None

            # Transition fast-path: disable expensive CRT effects during initial world entry
            if has_game_view and not previous_has_game_view:
                transition_frame_counter = 0
                _rlog(f"TRANSITION: entering game view (handler={type(handler).__name__})")
                _suppress_degauss_once = False
            _gen_in_progress = _loading_in_progress or (
                isinstance(handler, input_handlers.CRTTransition)
                and not handler.game_load
            )
            if has_game_view and transition_frame_counter < transition_cooldown_frames:
                transition_frame_counter += 1
                _crt_force_fast_path = True
            else:
                if _crt_force_fast_path:
                    _rlog(f"TRANSITION END: postprocessing re-enabled (handler={type(handler).__name__})")
                _crt_force_fast_path = False
            previous_has_game_view = has_game_view
            _render_frame += 1

            current_time = time.time()
            # Real displayed frame cadence (includes GPU present + sleep cap).
            frame_dt = max(1e-6, current_time - last_time)
            real_frame_fps = 1.0 / frame_dt
            real_frame_ms = frame_dt * 1000.0
            if active_engine is not None:
                active_engine.frame_fps = real_frame_fps
                active_engine.frame_time_ms = real_frame_ms
            window_w, window_h = context.sdl_window.size

            # ------------------------------------------------------------------
            # CRT POWER-SWITCH fast path for LoadingScreen world generation
            # ------------------------------------------------------------------
            # Phase 1 — screen-off: played once on the first frame _gen_in_progress
            #           becomes True.  Runs blocking on main thread; GPU is trivially
            #           idle, so no vsync stalls possible.
            # Phase 2 — black hold: while gen is running, render nothing but black
            #           + a "..." dot animation via draw_color only (zero textures).
            # Phase 3 — screen-on: played once when game_load flips True.
            #           Expands from line to full scene, then falls through normally,
            #           allowing the main loop to transition to MainGameEventHandler.
            #(f"CRT_STATE frame={_render_frame} gen={_gen_in_progress} off={_crt_off_played} on={_crt_on_played} snap={'yes' if _gen_scene_tex is not None else 'no'} handler={type(handler).__name__} gen_complete={getattr(handler,'game_load',None)}")
            if _gen_in_progress:
                # Start gen thread immediately — no CRT off before loading, the screen
                # stays visible so the player can watch the boot progress.
                if hasattr(handler, 'generation_started') and not handler.generation_started:
                    _rlog(f"CRT: starting generation thread (loading screen visible)")
                    handler.generation_started = True
                    handler.start_generation()
                    _gen_bar_start_time = time.monotonic()
                    if isinstance(handler, setup_game.LoadingScreen):
                        sounds.play_video_mode_switch_sound()
                        sounds.play_floppy_seek_sound()  # immediate seek on spin-up
                # Render the BIOS-style loading screen on black (LoadingScreen only;
                # CRTTransition just holds black for one frame then falls to the elif branch)
                
                if isinstance(handler, setup_game.LoadingScreen) and _gen_bar_start_time is not None:
                    _bar_elapsed = time.monotonic() - _gen_bar_start_time
                    _bar_progress = min(0.92, _bar_elapsed / 8.0)
                    
                    # Render to scene_tex for full CRT pipeline
                    gpu.ensure_bloom_targets(window_w, window_h)
                    with renderer.set_render_target(gpu.scene_tex):
                        renderer.draw_color = (0, 0, 0, 255)
                        renderer.clear()
                        render_functions.render_gpu_loading_bar(renderer, _bar_progress, window_w, window_h, ui_console_renderer)
                    
                    # Apply barrel distortion + chromatic aberration: scene_tex → post_crt_tex
                    gpu.apply_barrel_and_ca(window_w, window_h)
                    
                    # Blit post_crt_tex to framebuffer with full CRT effects
                    renderer.draw_color = (0, 0, 0, 255)
                    renderer.clear()
                    gpu.post_crt_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    gpu.post_crt_tex.alpha_mod = 255
                    gpu.post_crt_tex.color_mod = (255, 255, 255)
                    renderer.copy(gpu.post_crt_tex, dest=(0, 0, window_w, window_h))
                    
                    # Apply scanlines with scroll
                    if gpu.crt_scanlines_on and scanlines_tex is not None:
                        scanlines_scroll = (scanlines_scroll + scanlines_speed * (1.0 / target_fps)) % scanlines_h
                        y = -int(scanlines_scroll)
                        while y < window_h:
                            src_y = 0 if y >= 0 else -y
                            dst_y = max(y, 0)
                            draw_h = min(scanlines_h - src_y, window_h - dst_y)
                            if draw_h > 0:
                                renderer.copy(scanlines_tex,
                                              source=(0, src_y, 1, draw_h),
                                              dest=(0, dst_y, window_w, draw_h))
                            y += scanlines_h
                    
                    if gpu.crt_vignette_on and vignette_tex is not None:
                        renderer.copy(vignette_tex, dest=(0, 0, window_w, window_h))
                    
                    if glare_tex is not None:
                        renderer.copy(glare_tex, dest=(0, 0, window_w, window_h))
                    
                    # Apply bloom (must be after vignette/glare, before present)
                    if gpu.crt_bloom_on:
                        gpu.gpu_bloom(gpu.post_crt_tex, window_w, window_h)
                else:
                    # CRTTransition or early frame - just black
                    renderer.draw_color = (0, 0, 0, 255)
                    renderer.clear()
                
                renderer.present()
                for _ in tcod.event.get():
                    pass
                time.sleep(frame_time)
                continue

            elif _gen_bar_start_time is not None and not _crt_off_played:
                # Gen (or synchronous CRTTransition) just completed.
                # For LoadingScreen: flush tiles, show 100%, capture bar into _gen_scene_tex.
                # For CRTTransition: _gen_scene_tex already holds the last game frame
                #   (rolling snapshot kept it fresh); skip loading bar entirely.
                if isinstance(handler, setup_game.LoadingScreen):
                    import sprite_manager as _sm
                    _sm.flush_deferred_tiles()

                    # Show 100% loading screen briefly so player sees completion
                    # Render to scene_tex for full CRT pipeline
                    gpu.ensure_bloom_targets(window_w, window_h)
                    with renderer.set_render_target(gpu.scene_tex):
                        renderer.draw_color = (0, 0, 0, 255)
                        renderer.clear()
                        render_functions.render_gpu_loading_bar(renderer, 1.0, window_w, window_h, ui_console_renderer)
                    
                    # Apply barrel distortion + chromatic aberration
                    gpu.apply_barrel_and_ca(window_w, window_h)
                    
                    # Blit to framebuffer with full CRT effects
                    renderer.draw_color = (0, 0, 0, 255)
                    renderer.clear()
                    gpu.post_crt_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    gpu.post_crt_tex.alpha_mod = 255
                    gpu.post_crt_tex.color_mod = (255, 255, 255)
                    renderer.copy(gpu.post_crt_tex, dest=(0, 0, window_w, window_h))
                    
                    # Apply scanlines
                    if gpu.crt_scanlines_on and scanlines_tex is not None:
                        y = -int(scanlines_scroll)
                        while y < window_h:
                            src_y = 0 if y >= 0 else -y
                            dst_y = max(y, 0)
                            draw_h = min(scanlines_h - src_y, window_h - dst_y)
                            if draw_h > 0:
                                renderer.copy(scanlines_tex,
                                              source=(0, src_y, 1, draw_h),
                                              dest=(0, dst_y, window_w, draw_h))
                            y += scanlines_h
                    
                    if gpu.crt_vignette_on and vignette_tex is not None:
                        renderer.copy(vignette_tex, dest=(0, 0, window_w, window_h))
                    
                    if glare_tex is not None:
                        renderer.copy(glare_tex, dest=(0, 0, window_w, window_h))
                    
                    # Apply bloom
                    if gpu.crt_bloom_on:
                        gpu.gpu_bloom(gpu.post_crt_tex, window_w, window_h)
                    
                    renderer.present()
                    time.sleep(0.45)

                    # Capture the 100% loading screen into a texture for CRT off
                    if _gen_scene_tex_size != (window_w, window_h):
                        _gen_scene_tex = renderer.new_texture(
                            window_w, window_h, access=tcod.sdl.render.TextureAccess.TARGET
                        )
                        _gen_scene_tex_size = (window_w, window_h)
                    with renderer.set_render_target(_gen_scene_tex):
                        # Capture the full CRT-processed frame for the video mode switch animation
                        renderer.draw_color = (0, 0, 0, 255)
                        renderer.clear()
                        gpu.post_crt_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                        gpu.post_crt_tex.alpha_mod = 255
                        gpu.post_crt_tex.color_mod = (255, 255, 255)
                        renderer.copy(gpu.post_crt_tex, dest=(0, 0, window_w, window_h))
                        
                        # Include scanlines in the capture
                        if gpu.crt_scanlines_on and scanlines_tex is not None:
                            y = -int(scanlines_scroll)
                            while y < window_h:
                                src_y = 0 if y >= 0 else -y
                                dst_y = max(y, 0)
                                draw_h = min(scanlines_h - src_y, window_h - dst_y)
                                if draw_h > 0:
                                    renderer.copy(scanlines_tex,
                                                  source=(0, src_y, 1, draw_h),
                                                  dest=(0, dst_y, window_w, draw_h))
                                y += scanlines_h
                        
                        if gpu.crt_vignette_on and vignette_tex is not None:
                            renderer.copy(vignette_tex, dest=(0, 0, window_w, window_h))
                        
                        # Bloom is applied to the capture via ADD compositing
                        if gpu.crt_bloom_on:
                            gpu.gpu_bloom(gpu.post_crt_tex, window_w, window_h)

                # Video mode switch — register tear → noise → blank (no CRT power-off)
                _rlog(f"CRT: playing video mode switch (INT 10h) from completed loading screen")
                _crt_off_played = True
                sounds.play_video_mode_switch_sound()
                _sw_anim = VideoModeSwitchAnimation(renderer, window_w, window_h)
                _sw_anim.play_off(_gen_scene_tex, event_pump=tcod.event.get, glare_tex=glare_tex)
                del _sw_anim
                _rlog(f"CRT: video mode switch blank phase done, transitioning handler")

                # Release capture texture and reset state
                _gen_scene_tex      = None
                _gen_scene_tex_size = (0, 0)
                _crt_off_played     = False
                _gen_bar_start_time = None
                _suppress_degauss_once = True
                _crt_on_capture_pending = True
                class _CRTTransitionEvent:
                    _crt_transition = True
                new_handler = handler.handle_events(_CRTTransitionEvent())
                _rlog(f"CRT: handler after transition = {type(new_handler).__name__}")
                if new_handler is not handler:
                    handler = new_handler
                    overlay_dirty = True
                    # Re-evaluate view flags so engine.tick() runs this frame and
                    # the _crt_on_capture_pending frame captures a fully-ticked state.
                    # Without this, main_game_view is stale-False (was LoadingScreen),
                    # tick() is skipped, and the player appears one step off for one frame.
                    if isinstance(handler, input_handlers.MainGameEventHandler):
                        active_engine     = handler.engine
                        has_game_view     = (active_engine is not None
                                             and getattr(active_engine, 'game_map', None) is not None)
                        main_game_view    = has_game_view
                        fast_main_view    = has_game_view
                        needs_live_game_frame = True
                # Render black this frame while the new handler initialises
                renderer.draw_color = (0, 0, 0, 255)
                renderer.clear()


            # Channel overlay (menu boot or game load)
            gpu.draw_channel_overlay(glare_tex)

            # Always use context.sdl_window.size for window and mouse mapping
            base_tile_w = window_w / screen_width
            base_tile_h = window_h / screen_height
            game_dest_w = game_view_width * base_tile_w * game_zoom
            game_dest_h = game_view_height * base_tile_h * game_zoom
            hud_top_row = game_height - 1
            hud_rows = screen_height - hud_top_row
            hud_source_y = hud_top_row * tileset.tile_height
            hud_source_h = hud_rows * tileset.tile_height
            hud_dest_h = hud_rows * base_tile_h

            # Expose tile size to input handlers for pixel-accurate minimap click mapping
            if active_engine is not None:
                active_engine.base_tile_w = base_tile_w
                active_engine.base_tile_h = base_tile_h
                active_engine.game_zoom = game_zoom

            world_offset_x = 0
            world_offset_y = 0

            if main_game_view:
                game_console.clear()
                handler.engine.tick(console=game_console)

            if has_game_view and needs_live_game_frame and not map_overlay_view:
                active_engine.render_game(game_console)

            if has_game_view and active_engine is not None:
                # Update camera smoothing after gameplay state changes this frame
                # (including auto-move), so camera motion tracks current player state.
                active_engine.update_camera_interpolation(
                    base_tile_w * game_zoom,
                    base_tile_h * game_zoom,
                    game_view_width,
                    game_view_height,
                )
                world_offset_x, world_offset_y = active_engine.get_camera_render_offset_px(
                    base_tile_w * game_zoom,
                    base_tile_h * game_zoom,
                )

            # --- Update gpu object with current frame dimensions ---
            gpu.update_frame_dims(window_w, window_h, base_tile_w, base_tile_h, game_zoom)
            gpu.crt_force_fast_path = _crt_force_fast_path

            # --- Begin scene rendering to off-screen target for GPU bloom ---
            #_rlog(f"ensure_bloom_targets({window_w},{window_h}) fast={_crt_force_fast_path}")
            gpu.ensure_bloom_targets(window_w, window_h)
            #_rlog("set_render_target(scene_tex)")
            _scene_ctx = renderer.set_render_target(gpu.scene_tex)

            def _apply_lightmap():
                if _crt_force_fast_path or not has_game_view:
                    return
                gpu.apply_lightmap(
                    active_engine,
                    game_dest_w,
                    game_dest_h,
                    game_console,
                    dest_offset_x=world_offset_x,
                    dest_offset_y=world_offset_y,
                )

            def _render_game_tex_profiled():
                _t0 = time.perf_counter()
                _tex = game_console_renderer.render(game_console)
                _t1 = time.perf_counter()
                try:
                    if active_engine is not None:
                        active_engine.profile_external_ms("console_render", (_t1 - _t0) * 1000.0)
                except Exception:
                    pass
                return _tex

            if fast_main_view:
                # Clear inspect cache when returning to normal gameplay
                if _prev_inspect_overlay:
                    inspect_ui_tex          = None
                    inspect_ui_cursor_cache = None
                _prev_inspect_overlay = False
                renderer.clear()
                game_tex = _render_game_tex_profiled()
                renderer.copy(game_tex, dest=(int(world_offset_x), int(world_offset_y), int(game_dest_w), int(game_dest_h)))
                _apply_lightmap()

                # GPU game-layer animations drawn into scene_tex so they sit UNDER CRT effects
                if not _crt_force_fast_path and active_engine is not None and (gpu.gpu_anim_registry or gpu.gpu_anim_nobloom_registry):
                    gpu.ensure_gpu_anim_layer(game_dest_w, game_dest_h)
                    gpu.run_gpu_anim_passes(
                        active_engine,
                        game_dest_w,
                        game_dest_h,
                        dest_offset_x=world_offset_x,
                        dest_offset_y=world_offset_y,
                    )

                if getattr(active_engine, "debug", False):
                    cached_overlay_handler = None
                    overlay_dirty = True
                    ui_console.clear()
                    active_engine.render_ui(ui_console, skip_debug=True)
                    hud_tex = ui_console_renderer.render(ui_console)
                    renderer.copy(hud_tex,
                                  source=(0, int(hud_source_y), int(_ui_tex_w), int(hud_source_h)),
                                  dest=(0, int(window_h - hud_dest_h), window_w, int(hud_dest_h)))
                    # Minimap / hints panel (auto side)
                    _tw, _th = tileset.tile_width, tileset.tile_height
                    _mm_x = render_functions.get_minimap_origin_x(active_engine)
                    _mm_y, _mm_w, _mm_h = render_functions._MM_Y, render_functions._MM_W, render_functions._MM_H
                    _mm_mode = getattr(active_engine, 'show_minimap', 0)
                    _mm_on_overworld = getattr(getattr(active_engine, 'game_map', None), 'type', '') == 'overworld'
                    if _mm_mode == 2 and not _mm_on_overworld:
                        renderer.copy(hud_tex,
                                      source=(int(_mm_x * _tw), int(_mm_y * _th), int(_mm_w * _tw), int(_th)),
                                      dest=(int(_mm_x * base_tile_w), int(_mm_y * base_tile_h),
                                            int(_mm_w * base_tile_w), int(base_tile_h)))
                    elif _mm_mode != 3 and not _mm_on_overworld:
                        renderer.copy(hud_tex,
                                      source=(int(_mm_x * _tw), int(_mm_y * _th), int(_mm_w * _tw), int(_mm_h * _th)),
                                      dest=(int(_mm_x * base_tile_w), int(_mm_y * base_tile_h),
                                            int(_mm_w * base_tile_w), int(_mm_h * base_tile_h)))
                        render_functions.render_gpu_minimap_body(renderer, active_engine, base_tile_w, base_tile_h)
                    render_functions.render_gpu_reset_bar(renderer, handler, window_w, window_h, ui_console_renderer, hud_dest_h)
                    debug_console.clear()
                    render_functions.render_debug_overlay(
                        debug_console,
                        getattr(active_engine, "frame_fps", active_engine.tick_rate),
                        (active_engine.player.x, active_engine.player.y),
                        type(handler).__name__,
                        len(active_engine.game_map.entities),
                        active_engine,
                    )
                    dbg_tex = debug_console_renderer.render(debug_console)
                    renderer.copy(
                        dbg_tex,
                        dest=(
                            0,
                            0,
                            int(debug_console.width * base_tile_w),
                            int(debug_console.height * base_tile_h),
                        ),
                    )
                if getattr(active_engine, "show_lag_profiler", False) or getattr(active_engine, "show_perf_profiler", False):
                    cached_overlay_handler = None
                    overlay_dirty = True
                    ui_console.clear()
                    active_engine.render_ui(ui_console, skip_debug=True)
                    hud_tex = ui_console_renderer.render(ui_console)
                    renderer.copy(hud_tex,
                                  source=(0, int(hud_source_y), int(_ui_tex_w), int(hud_source_h)),
                                  dest=(0, int(window_h - hud_dest_h), window_w, int(hud_dest_h)))
                    _tw, _th = tileset.tile_width, tileset.tile_height
                    _mm_x = render_functions.get_minimap_origin_x(active_engine)
                    _mm_y, _mm_w, _mm_h = render_functions._MM_Y, render_functions._MM_W, render_functions._MM_H
                    _mm_mode = getattr(active_engine, 'show_minimap', 0)
                    _mm_on_overworld = getattr(getattr(active_engine, 'game_map', None), 'type', '') == 'overworld'
                    if _mm_mode == 2 and not _mm_on_overworld:
                        renderer.copy(hud_tex,
                                      source=(int(_mm_x * _tw), int(_mm_y * _th), int(_mm_w * _tw), int(_th)),
                                      dest=(int(_mm_x * base_tile_w), int(_mm_y * base_tile_h),
                                            int(_mm_w * base_tile_w), int(base_tile_h)))
                    elif _mm_mode != 3 and not _mm_on_overworld:
                        renderer.copy(hud_tex,
                                      source=(int(_mm_x * _tw), int(_mm_y * _th), int(_mm_w * _tw), int(_mm_h * _th)),
                                      dest=(int(_mm_x * base_tile_w), int(_mm_y * base_tile_h),
                                            int(_mm_w * base_tile_w), int(_mm_h * base_tile_h)))
                        render_functions.render_gpu_minimap_body(renderer, active_engine, base_tile_w, base_tile_h)
                    render_functions.render_gpu_reset_bar(renderer, handler, window_w, window_h, ui_console_renderer, hud_dest_h)
                    debug_console.clear()
                    if getattr(active_engine, "show_perf_profiler", False):
                        render_functions.render_perf_profiler(debug_console, active_engine)
                    else:
                        render_functions.render_lag_profiler(debug_console, active_engine)
                    _lag_pixels = render_console_with_transparency(debug_console)
                    if _lag_profiler_tex is None:
                        _lag_profiler_tex = renderer.upload_texture(_lag_pixels)
                        _lag_profiler_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    else:
                        _lag_profiler_tex.update(_lag_pixels)
                    renderer.copy(
                        _lag_profiler_tex,
                        dest=(
                            0,
                            0,
                            int(debug_console.width * base_tile_w),
                            int(debug_console.height * base_tile_h),
                        ),
                    )
                else:
                    cached_overlay_handler = None
                    overlay_dirty = True
                    ui_console.clear()
                    active_engine.render_ui(ui_console)
                    hud_tex = ui_console_renderer.render(ui_console)
                    renderer.copy(hud_tex,
                                  source=(0, int(hud_source_y), int(_ui_tex_w), int(hud_source_h)),
                                  dest=(0, int(window_h - hud_dest_h), window_w, int(hud_dest_h)))
                    # Minimap / hints panel (auto side)
                    _tw, _th = tileset.tile_width, tileset.tile_height
                    _mm_x = render_functions.get_minimap_origin_x(active_engine)
                    _mm_y, _mm_w, _mm_h = render_functions._MM_Y, render_functions._MM_W, render_functions._MM_H
                    _mm_mode = getattr(active_engine, 'show_minimap', 0)
                    _mm_on_overworld = getattr(getattr(active_engine, 'game_map', None), 'type', '') == 'overworld'
                    if _mm_mode == 2 and not _mm_on_overworld:
                        renderer.copy(hud_tex,
                                      source=(int(_mm_x * _tw), int(_mm_y * _th), int(_mm_w * _tw), int(_th)),
                                      dest=(int(_mm_x * base_tile_w), int(_mm_y * base_tile_h),
                                            int(_mm_w * base_tile_w), int(base_tile_h)))
                    elif _mm_mode != 3 and not _mm_on_overworld:
                        renderer.copy(hud_tex,
                                      source=(int(_mm_x * _tw), int(_mm_y * _th), int(_mm_w * _tw), int(_mm_h * _th)),
                                      dest=(int(_mm_x * base_tile_w), int(_mm_y * base_tile_h),
                                            int(_mm_w * base_tile_w), int(_mm_h * base_tile_h)))
                        render_functions.render_gpu_minimap_body(renderer, active_engine, base_tile_w, base_tile_h)
                    render_functions.render_gpu_reset_bar(renderer, handler, window_w, window_h, ui_console_renderer, hud_dest_h)
                    _sb = getattr(active_engine, 'speech_bubble_ui_rect', None)
                    if _sb:
                        _sb_x, _sb_y, _sb_w, _sb_h = _sb
                        _tw, _th = tileset.tile_width, tileset.tile_height
                        renderer.copy(hud_tex,
                                      source=(int(_sb_x * _tw), int(_sb_y * _th), int(_sb_w * _tw), int(_sb_h * _th)),
                                      dest=(int(_sb_x * base_tile_w), int(_sb_y * base_tile_h),
                                            int(_sb_w * base_tile_w), int(_sb_h * base_tile_h)))

            elif map_overlay_view:
                cached_overlay_handler = None
                overlay_dirty = True

                # --- Shadow-clearing: if the previous frame was inspect_overlay_view
                # but this one is not (or is a different handler), drop the cached
                # inspect texture so no ghost image bleeds into the regular overlay path.
                if _prev_inspect_overlay and not inspect_overlay_view:
                    inspect_ui_tex          = None
                    inspect_ui_cursor_cache = None
                    inspect_sub_console     = None
                    inspect_hints_console   = None
                    inspect_hints_tex       = None
                    inspect_preview_tex     = None
                    _inspect_preview_dest   = None
                    _inspect_sidebar_dest   = None
                    overlay_popup_tex       = None
                    overlay_popup_dest      = None
                _prev_inspect_overlay = inspect_overlay_view

                renderer.clear()

                game_console.clear()
                if inspect_overlay_view:
                    active_engine.render_game(game_console)
                    handler.render_game_overlay(game_console)
                else:
                    handler.on_render(console=game_console)
                game_tex = _render_game_tex_profiled()
                renderer.copy(game_tex, dest=(int(world_offset_x), int(world_offset_y), int(game_dest_w), int(game_dest_h)))
                _apply_lightmap()

                # GPU game-layer animations (same pass as fast_main_view)
                if not _crt_force_fast_path and active_engine is not None and (gpu.gpu_anim_registry or gpu.gpu_anim_nobloom_registry):
                    gpu.ensure_gpu_anim_layer(game_dest_w, game_dest_h)
                    gpu.run_gpu_anim_passes(
                        active_engine,
                        game_dest_w,
                        game_dest_h,
                        dest_offset_x=world_offset_x,
                        dest_offset_y=world_offset_y,
                    )

                # ── Animated targeting cursor (BLEND sprite over game view) ───────────
                # Drawn after lightmap so it's always at full brightness regardless of
                # local tile lighting.  Reads cursor codepoint + screen position that
                # render_game_overlay() stored on the handler without touching the console.
                _cpos = getattr(handler, '_cursor_screen_pos', None)
                _ccp  = getattr(handler, '_cursor_cp', 0xE0F6)
                if _cpos is not None:
                    try:
                        import sprite_manager as _sm
                        _cpx = _sm._get_tile(_ccp)
                        if _map_cursor_tex is None or _map_cursor_last_cp != _ccp:
                            _cpx_c = np.ascontiguousarray(_cpx)
                            if _map_cursor_tex is None:
                                _map_cursor_tex = renderer.upload_texture(_cpx_c)
                                _map_cursor_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                            else:
                                _map_cursor_tex.update(_cpx_c)
                            _map_cursor_last_cp = _ccp
                        _cs_x, _cs_y = _cpos
                        _ctw = base_tile_w * game_zoom  # game tiles are rendered at current zoom scale
                        _cth = base_tile_h * game_zoom
                        renderer.copy(_map_cursor_tex, dest=(
                            int(_cs_x * _ctw) + int(world_offset_x), int(_cs_y * _cth) + int(world_offset_y),
                            int(_ctw), int(_cth),
                        ))
                    except Exception as _cursor_err:
                        print(f"[cursor render] ERROR: {_cursor_err}")

                if inspect_overlay_view:
                    # Rebuild textures only when cursor tile OR handler state changes.
                    # Game is paused in look mode — skip UI render entirely on cache-hit frames.
                    cur_cursor = (
                        tuple(getattr(active_engine, 'mouse_location',
                                      active_engine.mouse_location)),
                        getattr(handler, 'current_tab', 0),
                        getattr(handler, 'scroll_offset', getattr(handler, '_scroll_offset', 0)),
                        getattr(handler, 'detail_index', 0),
                    )
                    if inspect_ui_cursor_cache != cur_cursor or inspect_ui_tex is None:
                        inspect_ui_cursor_cache = cur_cursor
                        # Full UI rebuild only on cache miss (game paused, HUD static)
                        ui_console.clear()
                        active_engine.render_ui(ui_console)
                        handler.render_ui_overlay(ui_console)
                        # HUD strip — GPU opaque path, no numpy needed
                        hud_tex = ui_console_renderer.render(ui_console)
                        # Context hints row — small 1-row BLEND texture
                        _hints_row = hud_top_row - 1
                        if inspect_hints_console is None:
                            inspect_hints_console = tcod.Console(screen_width, 1, order="F")
                        ui_console.blit(inspect_hints_console, dest_x=0, dest_y=0,
                                        src_x=0, src_y=_hints_row,
                                        width=screen_width, height=1)
                        _hints_px = render_console_with_transparency(inspect_hints_console)
                        if inspect_hints_tex is None:
                            inspect_hints_tex = renderer.upload_texture(_hints_px)
                            inspect_hints_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                        else:
                            inspect_hints_tex.update(_hints_px)
                        # Sidebar — blit only the sub-region the handler reported
                        _sb_x = getattr(handler, '_sidebar_x', 0)
                        _sb_y = getattr(handler, '_sidebar_y', 0)
                        _sb_w = getattr(handler, '_sidebar_w', 35)
                        _sb_h = getattr(handler, '_sidebar_h', 30)
                        if (inspect_sub_console is None
                                or inspect_sub_console.width  != _sb_w
                                or inspect_sub_console.height != _sb_h):
                            inspect_sub_console = tcod.Console(_sb_w, _sb_h, order="F")
                            inspect_ui_tex = None  # force texture re-upload on size change
                        ui_console.blit(inspect_sub_console, dest_x=0, dest_y=0,
                                        src_x=_sb_x, src_y=_sb_y,
                                        width=_sb_w, height=_sb_h)
                        ui_pixels = render_console_with_transparency(inspect_sub_console)
                        if inspect_ui_tex is None:
                            inspect_ui_tex = renderer.upload_texture(ui_pixels)
                            inspect_ui_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                        else:
                            inspect_ui_tex.update(ui_pixels)
                        inspect_preview_tex = None
                        _inspect_preview_dest = None
                        _inspect_sidebar_dest = (
                            int(_sb_x * base_tile_w), int(_sb_y * base_tile_h),
                            int(_sb_w * base_tile_w), int(_sb_h * base_tile_h),
                        )
                    # Render HUD strip (GPU opaque — reuses last hud_tex, valid since game paused)
                    if hud_tex is not None:
                        renderer.copy(hud_tex,
                                      source=(0, int(hud_source_y), int(_ui_tex_w), int(hud_source_h)),
                                      dest=(0, int(window_h - hud_dest_h), window_w, int(hud_dest_h)))
                    # Render context hints row (BLEND, preserves game view underneath)
                    if inspect_hints_tex is not None:
                        _hints_row = hud_top_row - 1
                        renderer.copy(inspect_hints_tex, dest=(
                            0, int(_hints_row * base_tile_h),
                            window_w, int(base_tile_h),
                        ))
                    # Render sidebar panel
                    if inspect_ui_tex is not None and _inspect_sidebar_dest is not None:
                        renderer.copy(inspect_ui_tex, dest=_inspect_sidebar_dest)
                    if inspect_preview_tex is not None and _inspect_preview_dest is not None:
                        renderer.copy(inspect_preview_tex, dest=_inspect_preview_dest)
                else:
                    ui_console.clear()
                    active_engine.render_ui(ui_console)
                    hud_tex = ui_console_renderer.render(ui_console)
                    renderer.copy(hud_tex,
                                  source=(0, int(hud_source_y), int(_ui_tex_w), int(hud_source_h)),
                                  dest=(0, int(window_h - hud_dest_h), window_w, int(hud_dest_h)))
            elif has_game_view:
                # Clear inspect cache whenever we leave inspect_overlay_view.
                if _prev_inspect_overlay:
                    inspect_ui_tex          = None
                    inspect_ui_cursor_cache = None
                    inspect_sub_console     = None
                    inspect_hints_console   = None
                    inspect_hints_tex       = None
                    inspect_preview_tex     = None
                    _inspect_preview_dest   = None
                    _inspect_sidebar_dest   = None
                    overlay_dirty           = True   # force popup re-render this frame
                _prev_inspect_overlay = False

                renderer.clear()
                if needs_live_game_frame:
                    game_tex = _render_game_tex_profiled()
                renderer.copy(game_tex, dest=(int(world_offset_x), int(world_offset_y), int(game_dest_w), int(game_dest_h)))
                _apply_lightmap()

                # Dim the game underneath the overlay
                renderer.copy(dim_tex, dest=(0, 0, window_w, window_h))

                # Force re-render every frame while the game-over fade-in is active
                if (isinstance(handler, input_handlers.GameOverEventHandler)
                        and handler._get_fade_alpha() < 1.0):
                    overlay_dirty = True

                # Detect InventoryGridUI (either as direct handler or as parent of
                # a context-menu overlay) so the scaled inventory stays visible.
                _is_scaled_inv = getattr(handler, '_is_scaled_inventory', False)
                _parent_handler = getattr(handler, 'parent_handler', None)
                _scaled_inv_src = (handler if _is_scaled_inv
                                   else _parent_handler if getattr(_parent_handler, '_is_scaled_inventory', False)
                                   else None)
                if _scaled_inv_src is not None and getattr(_scaled_inv_src, '_drag_item', None) is not None:
                    overlay_dirty = True

                if overlay_dirty or cached_overlay_handler is not handler:
                    ui_console.clear()
                    # Signal PopupEventHandler subclasses to skip redundant numpy fade
                    # (dim_tex already handles dimming on the GPU; render_faded is only
                    # needed for the BLEND fallback path below where the sub-console copy
                    # relies on near-black cells being made transparent).
                    _is_gpu_popup = (isinstance(handler, input_handlers.PopupEventHandler)
                                     and not isinstance(handler, input_handlers.ItemContextMenu)
                                     and not _is_scaled_inv)
                    if _is_gpu_popup and active_engine is not None:
                        active_engine._popup_overlay_active = True
                    handler.on_render(console=ui_console)
                    if _is_gpu_popup and active_engine is not None:
                        active_engine._popup_overlay_active = False
                    cached_overlay_handler = handler
                    overlay_dirty = False

                    _tw, _th = tileset.tile_width, tileset.tile_height
                    if _is_gpu_popup and handler._px is not None:
                        # ── Fast GPU path ──────────────────────────────────────────────────
                        # PopupEventHandler subclasses register exact parchment bounds via
                        # _set_popup_bounds(). Copy that region directly from the atlas
                        # renderer texture — zero sub-console allocation, zero CPU pixel work.
                        _px, _py, _pw, _ph = handler._px, handler._py, handler._pw, handler._ph
                        overlay_popup_dest = (
                            int(_px * base_tile_w), int(_py * base_tile_h),
                            int(_pw * base_tile_w), int(_ph * base_tile_h),
                        )
                        overlay_popup_src_rect = (
                            int(_px * _tw), int(_py * _th),
                            int(_pw * _tw), int(_ph * _th),
                        )
                        overlay_popup_tex = None  # not used in this path

                        # Context hints at row 38 render over the game map and need
                        # transparency — handle them with a small BLEND sub-texture.
                        _hints_row = hud_top_row - 1
                        _hints_ch = ui_console.ch[:, _hints_row]
                        _hints_bg = ui_console.bg[:, _hints_row, :]
                        _hints_cols = np.where(
                            (_hints_ch != ord(' ')) | np.any(_hints_bg > 16, axis=1)
                        )[0]
                        if _hints_cols.size > 0:
                            _hx1 = int(_hints_cols.min())
                            _hx2 = int(_hints_cols.max()) + 1
                            _hw   = _hx2 - _hx1
                            if (overlay_hints_console is None
                                    or overlay_hints_console.width  != _hw
                                    or overlay_hints_console.height != 1):
                                overlay_hints_console = tcod.console.Console(_hw, 1, order="F")
                                overlay_hints_tex = None
                            ui_console.blit(overlay_hints_console,
                                            dest_x=0, dest_y=0,
                                            src_x=_hx1, src_y=_hints_row,
                                            width=_hw, height=1)
                            _hints_pixels = render_console_with_transparency(overlay_hints_console)
                            if overlay_hints_tex is None:
                                overlay_hints_tex = renderer.upload_texture(_hints_pixels)
                                overlay_hints_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                            else:
                                overlay_hints_tex.update(_hints_pixels)
                            overlay_hints_dest = (
                                int(_hx1 * base_tile_w), int(_hints_row * base_tile_h),
                                int(_hw   * base_tile_w), int(base_tile_h),
                            )
                        else:
                            overlay_hints_tex  = None
                            overlay_hints_dest = None
                    else:
                        # ── BLEND fallback path ────────────────────────────────────────────
                        # Used for ItemContextMenu and any other non-PopupEventHandler popup.
                        # The context menu may extend slightly outside the parent parchment,
                        # leaving gap cells with bg=(0,0,0). render_console_with_transparency
                        # + BLEND upload makes those cells transparent so the game shows through.
                        overlay_popup_src_rect = None
                        if _is_scaled_inv:
                            # InventoryGridUI renders to its own console; nothing to blit here.
                            overlay_popup_tex  = None
                            overlay_popup_dest = None
                            overlay_hints_tex  = None
                            overlay_hints_dest = None
                        else:
                            _ch2 = ui_console.ch[:, :hud_top_row]
                            _bg2 = ui_console.bg[:, :hud_top_row, :]
                            _content = (_ch2 != ord(' ')) | np.any(_bg2 > 16, axis=2)
                            _cells = np.where(_content)
                            if _cells[0].size > 0:
                                _mx1 = int(_cells[0].min())
                                _my1 = int(_cells[1].min())
                                _mx2 = int(_cells[0].max()) + 1
                                _my2 = int(_cells[1].max()) + 1
                                _sw, _sh = _mx2 - _mx1, _my2 - _my1
                                if (overlay_popup_console is None
                                        or overlay_popup_console.width  != _sw
                                        or overlay_popup_console.height != _sh):
                                    overlay_popup_console = tcod.console.Console(_sw, _sh, order="F")
                                    overlay_popup_tex = None
                                ui_console.blit(overlay_popup_console,
                                                dest_x=0, dest_y=0,
                                                src_x=_mx1, src_y=_my1,
                                                width=_sw, height=_sh)
                                _popup_pixels = render_console_with_transparency(overlay_popup_console)
                                if overlay_popup_tex is None:
                                    overlay_popup_tex = renderer.upload_texture(_popup_pixels)
                                    overlay_popup_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                                else:
                                    overlay_popup_tex.update(_popup_pixels)
                                overlay_popup_dest = (
                                    int(_mx1 * base_tile_w), int(_my1 * base_tile_h),
                                    int(_sw  * base_tile_w), int(_sh  * base_tile_h),
                                )
                            else:
                                overlay_popup_tex  = None
                                overlay_popup_dest = None
                            # Hints are included in the BLEND fallback bbox scan above
                            overlay_hints_tex  = None
                            overlay_hints_dest = None

                # Render ui_console to GPU texture once — reused for both popup and HUD strip.

                # ── Detect inventory grid handler ──────────────────────────────────────────────
                _ph = getattr(handler, 'parent_handler', None)
                _inv_grid_handler = (
                    handler if hasattr(handler, '_grid_console')
                    else _ph   if hasattr(_ph,  '_grid_console') else None
                )
                # _grid_is_direct: InventoryGridUI is the active handler (GPU-direct path).
                # When False (context menu on top): render grid PRE-chrome so the BLEND
                # layer (chrome with transparent hole + context menu) sits on top.
                _grid_is_direct = _inv_grid_handler is not None and handler is _inv_grid_handler

                # ── Eq panel helper — called from both pre-chrome and post-chrome blocks ───────
                # Normal : slots fully opaque (NONE blend) covering the body diagram.
                # Alt held: slots first (opaque), then white body-part masks on top
                #           tinted dim-grey (healthy) or amber→red (damaged).
                #           The main body PNG is never rendered — it is black and cannot
                #           be tinted, so the white per-part mask PNGs handle all body art.
                def _render_eq_panel(_eq_px):
                    _alt = bool(getattr(_inv_grid_handler, '_alt_damage_view', False))
                    _eq_body_nudge_tiles = float(getattr(inventory_ui, "_EQ_BODY_NUDGE_X_TILES", 0.0))
                    _eq_body_nudge_px_legacy = int(getattr(inventory_ui, "_EQ_BODY_NUDGE_X_PX", 0))
                    _eq_body_nudge_x = int(round(_eq_body_nudge_tiles * base_tile_w)) + _eq_body_nudge_px_legacy
                    _eq_body_px = (
                        _eq_px[0] + _eq_body_nudge_x,
                        _eq_px[1],
                        _eq_px[2],
                        _eq_px[3],
                    )
                    # Build damage map once
                    _bp_dmg: dict = {}
                    try:
                        _bp_comp = getattr(getattr(active_engine.player, 'body_parts', None),
                                           'body_parts', None)
                        if _bp_comp:
                            _bp_dmg = {bpt.name: bp.damage_level_float
                                       for bpt, bp in _bp_comp.items()}
                    except Exception:
                        pass
                    def _draw_slot_layers():
                        # ADD blend → black non-slot cells are transparent (show bg/masks),
                        # coloured slot cells light up additively on top.
                        _eqgrid_tex = inv_console_renderer.render(_inv_grid_handler._eq_grid_console)
                        _eqgrid_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                        renderer.copy(_eqgrid_tex, dest=_eq_px)
                        if hasattr(_inv_grid_handler, '_eq_qty_console'):
                            _eq_qty_tex = inv_console_renderer.render(_inv_grid_handler._eq_qty_console)
                            _eq_qty_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                            renderer.copy(_eq_qty_tex, dest=_eq_px)
                    def _draw_body_diagram(bright: bool):
                        # White per-part mask PNGs tinted by damage level.
                        # bright=False (behind opaque slots): dim silhouette
                        # bright=True  (Alt, no slots):       vivid, fully visible
                        for _bpn, _bptex in _body_part_texes.items():
                            _d = _bp_dmg.get(_bpn, 0.0)
                            if _d > 0.02:
                                # yellow(255,220,0) → orange(255,120,0) → dark red(160,0,0) → bright red(255,0,0)
                                if _d < 0.33:
                                    _t = _d / 0.33          # yellow → orange
                                    _r = 255
                                    _g = int(220 - _t * 100)
                                elif _d < 0.66:
                                    _t = (_d - 0.33) / 0.33  # orange → dark red
                                    _r = int(255 - _t * 95)
                                    _g = int(120 - _t * 120)
                                else:
                                    _t = (_d - 0.66) / 0.34  # dark red → bright red
                                    _r = int(160 + _t * 95)
                                    _g = 0
                                _bptex.color_mod = (_r, _g, 0)
                                _bptex.alpha_mod = min(255, int(80 + _d * 175)) if bright else min(220, int(40 + _d * 180))
                            else:
                                _bptex.color_mod = (80, 220, 100) if bright else (40, 45, 65)
                                _bptex.alpha_mod = 220 if bright else 110
                            renderer.copy(_bptex, dest=_eq_body_px)
                    renderer.copy(_eq_bg_tex, dest=_eq_px)
                    if _body_part_texes:
                        _draw_body_diagram(bright=False)   # always behind slots
                    if not _alt:
                        _draw_slot_layers()                # opaque slots cover dim masks
                    elif _body_part_texes:
                        _draw_body_diagram(bright=True)    # Alt: bright diagram, no slots

                # Pre-chrome grid render — context menu / BLEND overlay case only
                if _inv_grid_handler is not None and not _grid_is_direct:
                    _gdt = _inv_grid_handler._grid_dest_tiles
                    _grid_item_tex = inv_console_renderer.render(_inv_grid_handler._grid_console)
                    _grid_item_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                    renderer.copy(_grid_item_tex, dest=(
                        int(_gdt[0] * base_tile_w), int(_gdt[1] * base_tile_h),
                        int(_gdt[2] * base_tile_w), int(_gdt[3] * base_tile_h),
                    ))
                    if hasattr(_inv_grid_handler, '_qty_console'):
                        _qty_tex = inv_console_renderer.render(_inv_grid_handler._qty_console)
                        _qty_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                        renderer.copy(_qty_tex, dest=(
                            int(_gdt[0] * base_tile_w), int(_gdt[1] * base_tile_h),
                            int(_gdt[2] * base_tile_w), int(_gdt[3] * base_tile_h),
                        ))
                        _qty_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                    if hasattr(_inv_grid_handler, '_player_qty_console'):
                        _pqty_tex = inv_console_renderer.render(_inv_grid_handler._player_qty_console)
                        _pqty_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                        renderer.copy(_pqty_tex, dest=(
                            int(_gdt[0] * base_tile_w), int(_gdt[1] * base_tile_h),
                            int(_gdt[2] * base_tile_w), int(_gdt[3] * base_tile_h),
                        ))
                        _pqty_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                    if hasattr(_inv_grid_handler, '_container_grid_console'):
                        _cgdt = _inv_grid_handler._container_grid_dest_tiles
                        _cgrid_tex = inv_console_renderer.render(_inv_grid_handler._container_grid_console)
                        _cgrid_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                        renderer.copy(_cgrid_tex, dest=(
                            int(_cgdt[0] * base_tile_w), int(_cgdt[1] * base_tile_h),
                            int(_cgdt[2] * base_tile_w), int(_cgdt[3] * base_tile_h),
                        ))
                    if hasattr(_inv_grid_handler, '_container_qty_console'):
                        _cqty_tex = inv_console_renderer.render(_inv_grid_handler._container_qty_console)
                        _cqty_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                        renderer.copy(_cqty_tex, dest=(
                            int(_cgdt[0] * base_tile_w), int(_cgdt[1] * base_tile_h),
                            int(_cgdt[2] * base_tile_w), int(_cgdt[3] * base_tile_h),
                        ))
                        _cqty_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                    if hasattr(_inv_grid_handler, '_eq_grid_console'):
                        _egdt = _inv_grid_handler._eq_grid_dest_tiles
                        _eq_px = (int(_egdt[0]*base_tile_w), int(_egdt[1]*base_tile_h),
                                  int(_egdt[2]*base_tile_w), int(_egdt[3]*base_tile_h))
                        _render_eq_panel(_eq_px)

                _ov_tex = ui_console_renderer.render(ui_console)

                if _scaled_inv_src is not None:
                    # ── Scaled inventory path: full-window GPU layer ───────────────────────
                    # Render the InventoryGridUI's dedicated 40×25 console via its own
                    # renderer so it never shares a texture with game_console_renderer.
                    # Dest = full window → each tile is (window_w/40) × (window_h/25) = 32×32 px
                    # at the default 1280×800 resolution, giving clean 2× readable characters.
                    _inv_tex = inv_console_renderer.render(_scaled_inv_src._inv_console)
                    renderer.copy(_inv_tex, dest=(0, 0, window_w, window_h))
                    
                    # ── Tooltip overlay (stat breakdown) ──────────────────────────────────────
                    if getattr(_scaled_inv_src, '_tooltip_visible', False):
                        _tooltip_tex = inv_console_renderer.render(_scaled_inv_src._tooltip_console)
                        _tooltip_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                        _ttx = _scaled_inv_src._tooltip_screen_x * base_tile_w
                        _tty = _scaled_inv_src._tooltip_screen_y * base_tile_h
                        _ttw = _scaled_inv_src._tooltip_console.width * base_tile_w
                        _tth = _scaled_inv_src._tooltip_console.height * base_tile_h
                        renderer.copy(_tooltip_tex, dest=(_ttx, _tty, _ttw, _tth))
                        _tooltip_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                    
                    # If a context menu is floating on top (handler != _scaled_inv_src),
                    # draw it via the BLEND path so it appears over the inventory.
                    if not _is_scaled_inv and overlay_popup_tex is not None and overlay_popup_dest is not None:
                        renderer.copy(overlay_popup_tex, dest=overlay_popup_dest)
                elif overlay_popup_src_rect is not None and overlay_popup_dest is not None:
                    # GPU-direct path: single source-rect copy, fully opaque (parchment fills bounds)
                    renderer.copy(_ov_tex, source=overlay_popup_src_rect, dest=overlay_popup_dest)
                    # Context hints (row 38) sit outside the parchment — render with BLEND transparency
                    if overlay_hints_tex is not None and overlay_hints_dest is not None:
                        renderer.copy(overlay_hints_tex, dest=overlay_hints_dest)
                elif overlay_popup_tex is not None and overlay_popup_dest is not None:
                    # BLEND path: transparency-aware copy for ItemContextMenu / fallback handlers
                    renderer.copy(overlay_popup_tex, dest=overlay_popup_dest)

                # ── Post-chrome grid render — direct handler only (items on top of chrome) ───────
                if _grid_is_direct:
                    _gdt = _inv_grid_handler._grid_dest_tiles
                    _grid_item_tex = inv_console_renderer.render(_inv_grid_handler._grid_console)
                    _grid_item_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                    renderer.copy(_grid_item_tex, dest=(
                        int(_gdt[0] * base_tile_w), int(_gdt[1] * base_tile_h),
                        int(_gdt[2] * base_tile_w), int(_gdt[3] * base_tile_h),
                    ))
                    if hasattr(_inv_grid_handler, '_qty_console'):
                        _qty_tex = inv_console_renderer.render(_inv_grid_handler._qty_console)
                        _qty_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                        renderer.copy(_qty_tex, dest=(
                            int(_gdt[0] * base_tile_w), int(_gdt[1] * base_tile_h),
                            int(_gdt[2] * base_tile_w), int(_gdt[3] * base_tile_h),
                        ))
                        _qty_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                    if hasattr(_inv_grid_handler, '_player_qty_console'):
                        _pqty_tex = inv_console_renderer.render(_inv_grid_handler._player_qty_console)
                        _pqty_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                        renderer.copy(_pqty_tex, dest=(
                            int(_gdt[0] * base_tile_w), int(_gdt[1] * base_tile_h),
                            int(_gdt[2] * base_tile_w), int(_gdt[3] * base_tile_h),
                        ))
                        _pqty_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                    if hasattr(_inv_grid_handler, '_container_grid_console'):
                        _cgdt = _inv_grid_handler._container_grid_dest_tiles
                        _cgrid_tex = inv_console_renderer.render(_inv_grid_handler._container_grid_console)
                        _cgrid_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                        renderer.copy(_cgrid_tex, dest=(
                            int(_cgdt[0] * base_tile_w), int(_cgdt[1] * base_tile_h),
                            int(_cgdt[2] * base_tile_w), int(_cgdt[3] * base_tile_h),
                        ))
                    if hasattr(_inv_grid_handler, '_container_qty_console'):
                        _cqty_tex = inv_console_renderer.render(_inv_grid_handler._container_qty_console)
                        _cqty_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                        renderer.copy(_cqty_tex, dest=(
                            int(_cgdt[0] * base_tile_w), int(_cgdt[1] * base_tile_h),
                            int(_cgdt[2] * base_tile_w), int(_cgdt[3] * base_tile_h),
                        ))
                        _cqty_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
                    if hasattr(_inv_grid_handler, '_eq_grid_console'):
                        _egdt = _inv_grid_handler._eq_grid_dest_tiles
                        _eq_px = (int(_egdt[0]*base_tile_w), int(_egdt[1]*base_tile_h),
                                  int(_egdt[2]*base_tile_w), int(_egdt[3]*base_tile_h))
                        _render_eq_panel(_eq_px)

                # ── Drag icon (pixel-smooth, ADD blend → transparent bg, solid glyph) ─────
                if (_inv_grid_handler is not None
                        and getattr(_inv_grid_handler, '_drag_item', None) is not None):
                    _ddt = _inv_grid_handler._drag_dest_pixels
                    _drag_tex = inv_console_renderer.render(_inv_grid_handler._drag_console)
                    _drag_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                    renderer.copy(_drag_tex, dest=_ddt)
                    _drag_tex.blend_mode = tcod.sdl.render.BlendMode.NONE

                # HUD strip (from the same already-rendered GPU texture)
                renderer.copy(_ov_tex,
                              source=(0, int(hud_source_y), int(_ui_tex_w), int(hud_source_h)),
                              dest=(0, int(window_h - hud_dest_h), window_w, int(hud_dest_h)))

                # ── Tooltip overlay (stat breakdown) - RENDERED LAST ON TOP OF EVERYTHING ──
                if (_inv_grid_handler is not None
                        and getattr(_inv_grid_handler, '_tooltip_visible', False)):
                    _tooltip_tex = inv_console_renderer.render(_inv_grid_handler._tooltip_console)
                    _tooltip_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    _ttx = _inv_grid_handler._tooltip_screen_x * base_tile_w
                    _tty = _inv_grid_handler._tooltip_screen_y * base_tile_h
                    _ttw = _inv_grid_handler._tooltip_console.width * base_tile_w
                    _tth = _inv_grid_handler._tooltip_console.height * base_tile_h
                    renderer.copy(_tooltip_tex, dest=(_ttx, _tty, _ttw, _tth))
                    _tooltip_tex.blend_mode = tcod.sdl.render.BlendMode.NONE
            else:
                # Clear inspect cache when in main-menu / no-game-view path
                if _prev_inspect_overlay:
                    inspect_ui_tex          = None
                    inspect_ui_cursor_cache = None
                    inspect_preview_tex     = None
                    _inspect_preview_dest   = None
                _prev_inspect_overlay = False
                cached_overlay_handler = None
                overlay_dirty = True
                renderer.clear()
                if menu_bg_anim.available:
                    menu_bg_anim.draw(window_w, window_h)

                    static_layer_fn = getattr(handler, "render_static_menu_layer", None)
                    dynamic_region_fn = getattr(handler, "get_dynamic_region_tiles", None)
                    dynamic_layer_fn = getattr(handler, "render_dynamic_menu_region", None)

                    if callable(static_layer_fn) and callable(dynamic_layer_fn):
                        static_token_fn = getattr(handler, "get_static_visual_state_token", None)
                        dynamic_token_fn = getattr(handler, "get_dynamic_visual_state_token", None)

                        static_token = static_token_fn() if callable(static_token_fn) else type(handler).__name__
                        if (
                            menu_static_tex is None
                            or menu_static_handler is not handler
                            or menu_static_token != static_token
                        ):
                            if (
                                menu_static_console is None
                                or menu_static_console.width != screen_width
                                or menu_static_console.height != screen_height
                            ):
                                menu_static_console = tcod.console.Console(screen_width, screen_height, order="F")
                            menu_static_console.clear()
                            static_layer_fn(menu_static_console)
                            _static_pixels = render_console_with_transparency(menu_static_console)
                            menu_static_tex = renderer.upload_texture(_static_pixels)
                            menu_static_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                            menu_static_handler = handler
                            menu_static_token = static_token

                        renderer.copy(menu_static_tex, dest=(0, 0, window_w, window_h))

                        rx, ry, rw, rh = dynamic_region_fn(ui_console) if callable(dynamic_region_fn) else (0, 0, 0, 0)
                        if rw > 0 and rh > 0:
                            dynamic_token = dynamic_token_fn() if callable(dynamic_token_fn) else None
                            if (
                                menu_dynamic_console is None
                                or menu_dynamic_console.width != rw
                                or menu_dynamic_console.height != rh
                            ):
                                menu_dynamic_console = tcod.console.Console(rw, rh, order="F")
                                menu_dynamic_region = (rx, ry, rw, rh)
                                menu_dynamic_token = None

                            if (
                                menu_dynamic_tex is None
                                or menu_dynamic_handler is not handler
                                or menu_dynamic_region != (rx, ry, rw, rh)
                                or menu_dynamic_token != dynamic_token
                            ):
                                menu_dynamic_console.clear()
                                dynamic_layer_fn(menu_dynamic_console)
                                _dynamic_pixels = render_console_with_transparency(menu_dynamic_console)
                                menu_dynamic_tex = renderer.upload_texture(_dynamic_pixels)
                                menu_dynamic_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                                menu_dynamic_token = dynamic_token
                                menu_dynamic_handler = handler
                                menu_dynamic_region = (rx, ry, rw, rh)

                            renderer.copy(
                                menu_dynamic_tex,
                                dest=(
                                    int(rx * base_tile_w),
                                    int(ry * base_tile_h),
                                    int(rw * base_tile_w),
                                    int(rh * base_tile_h),
                                ),
                            )

                        ui_tex = None
                    else:
                        token_fn = getattr(handler, "get_visual_state_token", None)
                        _render_menu_ui = True
                        if callable(token_fn):
                            _token = token_fn()
                            if (
                                menu_ui_tex is not None
                                and menu_ui_cached_handler is handler
                                and menu_ui_cached_token == _token
                            ):
                                _render_menu_ui = False
                        else:
                            _token = None

                        if _render_menu_ui:
                            ui_console.clear()
                            handler.on_render(console=ui_console)
                            if callable(token_fn):
                                _ui_pixels = render_console_with_transparency(ui_console)
                                menu_ui_tex = renderer.upload_texture(_ui_pixels)
                                menu_ui_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                                menu_ui_cached_handler = handler
                                menu_ui_cached_token = _token
                                menu_ui_signature = None
                            else:
                                _menu_sig = get_console_signature(ui_console)
                                if menu_ui_tex is None or _menu_sig != menu_ui_signature:
                                    _ui_pixels = render_console_with_transparency(ui_console)
                                    menu_ui_tex = renderer.upload_texture(_ui_pixels)
                                    menu_ui_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                                    menu_ui_signature = _menu_sig
                                menu_ui_cached_handler = None
                                menu_ui_cached_token = None

                        ui_tex = menu_ui_tex
                else:
                    ui_console.clear()
                    handler.on_render(console=ui_console)
                    ui_tex = ui_console_renderer.render(ui_console)
                if ui_tex is not None:
                    renderer.copy(ui_tex, dest=(0, 0, window_w, window_h))

            # --- End scene rendering: restore default target, apply global CRT post-process ---
            #_rlog("restore_render_target")
            _scene_ctx.__exit__(None, None, None)  # restore default render target

            # Barrel distortion + chromatic aberration: scene_tex → post_crt_tex
            gpu.apply_barrel_and_ca(window_w, window_h)

            # Rolling snapshot of the last pre-gen post-CRT frame.
            # Updated every frame where generation is NOT in progress so it always
            # holds the most recent non-LoadingScreen image (main menu, seed entry…).
            # Used by play_off() as the scene to shrink.
            if not _gen_in_progress and not _crt_off_played:
                if _gen_scene_tex_size != (window_w, window_h):
                    _gen_scene_tex      = renderer.new_texture(
                        window_w, window_h, access=tcod.sdl.render.TextureAccess.TARGET
                    )
                    _gen_scene_tex_size = (window_w, window_h)
                with renderer.set_render_target(_gen_scene_tex):
                    renderer.draw_color = (0, 0, 0, 255)
                    renderer.clear()
                    gpu.post_crt_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    gpu.post_crt_tex.alpha_mod  = 255
                    gpu.post_crt_tex.color_mod  = (255, 255, 255)
                    renderer.copy(gpu.post_crt_tex, dest=(0, 0, window_w, window_h))
                    if gpu.crt_scanlines_on and scanlines_tex is not None:
                        for _fy in range(0, window_h, scanlines_h):
                            _fdh = min(scanlines_h, window_h - _fy)
                            renderer.copy(scanlines_tex,
                                          source=(0, 0, 1, _fdh),
                                          dest=(0, _fy, window_w, _fdh))
                    if gpu.crt_vignette_on:
                        renderer.copy(vignette_tex, dest=(0, 0, window_w, window_h))
                        renderer.copy(glare_tex,    dest=(0, 0, window_w, window_h))

            # CRT power-on: fire for ALL transition targets (game or menu)
            if _crt_on_capture_pending:
                _rlog(f"CRT: capturing game frame for play_on")
                if _crt_on_scene_tex_size != (window_w, window_h):
                    _crt_on_scene_tex = renderer.new_texture(
                        window_w, window_h, access=tcod.sdl.render.TextureAccess.TARGET
                    )
                    _crt_on_scene_tex_size = (window_w, window_h)
                with renderer.set_render_target(_crt_on_scene_tex):
                    renderer.draw_color = (0, 0, 0, 255)
                    renderer.clear()
                    gpu.post_crt_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    gpu.post_crt_tex.alpha_mod  = 255
                    gpu.post_crt_tex.color_mod  = (255, 255, 255)
                    renderer.copy(gpu.post_crt_tex, dest=(0, 0, window_w, window_h))
                    if gpu.crt_scanlines_on and scanlines_tex is not None:
                        for _fy in range(0, window_h, scanlines_h):
                            _fdh = min(scanlines_h, window_h - _fy)
                            renderer.copy(scanlines_tex,
                                          source=(0, 0, 1, _fdh),
                                          dest=(0, _fy, window_w, _fdh))
                    if gpu.crt_vignette_on:
                        renderer.copy(vignette_tex, dest=(0, 0, window_w, window_h))
                        # glare_tex intentionally excluded — play_on draws it as a
                        # separate top layer so it stays consistent across all frames.
                    # Bake bloom into the capture so the final play_on frame matches
                    # the first live game frame (bloom is ADD-composited onto whatever
                    # the current render target is, so it lands on _crt_on_scene_tex).
                    if gpu.crt_bloom_on:
                        gpu.gpu_bloom(gpu.post_crt_tex, window_w, window_h)
                _crt_on_capture_pending = False
                _rlog(f"CRT: playing video mode resync + snap with real game frame")
                _sw_anim = VideoModeSwitchAnimation(renderer, window_w, window_h)
                _sw_anim.play_on(_crt_on_scene_tex, event_pump=tcod.event.get,
                                 glare_tex=glare_tex, gpu_stack=gpu,
                                 scanlines_tex=scanlines_tex, scanlines_h=scanlines_h,
                                 vignette_tex=vignette_tex)
                del _sw_anim
                _rlog(f"CRT: video mode resync done")
                _crt_on_scene_tex      = None
                _crt_on_scene_tex_size = (0, 0)
                # Re-trigger channel splash (no wobble — INT 10h mode switch, not CRT power cycle)
                _new_has_game = (
                    getattr(handler, 'engine', None) is not None
                    and getattr(getattr(handler, 'engine', None), 'game_map', None) is not None
                )
                gpu.start_channel_overlay("game" if _new_has_game else "menu")
                continue   # skip outer present(); play_on already presented final frame

            # Wobble offset (decaying screen-shake on CRT power-on)
            _wx, _wy = gpu.tick_wobble(1.0 / target_fps)

            # Composite post_crt_tex onto the framebuffer (with wobble, vroll, and
            # AGC oversaturation/bloom-wash while the wobble is active)
            gpu.blit_post_crt(_wx, _wy)

            # ── Dialogue portrait: drawn AFTER blit_post_crt so bloom never touches it ──
            _dlg_port_dest = getattr(handler, '_portrait_dest_tiles', None)
            _dlg_port_path = getattr(handler, '_portrait_path', None)
            if _dlg_port_dest is not None and _dlg_port_path is not None:
                if _dialogue_portrait_path != _dlg_port_path or _dialogue_portrait_tex is None:
                    try:
                        _dp_img = Image.open(_dlg_port_path).convert("RGBA")
                        _dp_np  = np.array(_dp_img, dtype=np.uint8)
                        _dialogue_portrait_tex  = renderer.upload_texture(_dp_np)
                        _dialogue_portrait_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                        _dialogue_portrait_path = _dlg_port_path
                    except Exception as _dpe:
                        print(f"[portrait] load failed: {_dpe}")
                if _dialogue_portrait_tex is not None:
                    _dpx, _dpy, _dpw, _dph = _dlg_port_dest
                    renderer.copy(_dialogue_portrait_tex, dest=(
                        int(_dpx * base_tile_w), int(_dpy * base_tile_h),
                        int(_dpw * base_tile_w), int(_dph * base_tile_h),
                    ))

            if not _crt_force_fast_path:

                # Advance + draw CRT glitch effects (jitter band, vertical roll)
                gpu.tick_crt_glitches(1.0 / target_fps)
                gpu.draw_scanline_jitter()

                # Degauss (chromatic fringe on player death)
                if _active_degauss is not None:
                    _active_degauss.tick(1.0 / target_fps)
                    _active_degauss.draw(window_w, window_h, scene_tex=gpu.post_crt_tex)
                    if _active_degauss.done:
                        _active_degauss = None

                # VHS glitch (persistent distortion on game over screen)
                if _active_vhs_glitch is not None:
                    if isinstance(handler, input_handlers.GameOverEventHandler):
                        _active_vhs_glitch.tick(1.0 / target_fps)
                        _active_vhs_glitch.draw(window_w, window_h, scene_tex=gpu.post_crt_tex, gpu=gpu)
                    else:
                        _active_vhs_glitch = None

                # Scanlines (scrolling MOD pass)
                if gpu.crt_scanlines_on:
                    scanlines_scroll = (scanlines_scroll + scanlines_speed * (1.0 / target_fps)) % scanlines_h
                gpu.apply_crt_overlays(
                    window_w, window_h,
                    scanlines_tex=scanlines_tex, scanlines_h=scanlines_h,
                    scanlines_y_offset=int(scanlines_scroll),
                    skip_vignette=True,
                )

                # Vignette + glare + bloom (drawn after game-layer anims so they glow)
                gpu.apply_crt_overlays(
                    window_w, window_h,
                    skip_scanlines=True,
                    vignette_tex=vignette_tex, glare_tex=glare_tex,
                    bloom_source=gpu.post_crt_tex,
                )

            #_rlog("renderer.present")
            try:
                renderer.present()
            except Exception as e:
                print(f"Error during renderer.present(): {e}")
                raise
            #_rlog("present done")

# ---------------------- # 
# MAIN GAME LOOP
# ---------------------- #

            try:
                for event in tcod.event.get():
                    context.convert_event(event)
                    # Always map mouse events to UI tile coordinates
                    if hasattr(event, "position"):
                        # Undo CRT barrel distortion so mouse maps to logical positions
                        raw_pos = tuple(event.position)
                        logical_pos = undistort_mouse(raw_pos[0], raw_pos[1])
                        ui_tile = get_ui_mouse_tile(logical_pos, window_w, window_h)
                        event.ui_tile = ui_tile
                        event.tile = ui_tile
                        # Only map to game/world tiles if in game view
                        if has_game_view:
                            game_screen_tile = get_game_screen_tile(logical_pos, window_w, window_h)
                            world_tile = None
                            if active_engine is not None:
                                active_engine.mouse_ui_x, active_engine.mouse_ui_y = ui_tile
                                if ui_tile[1] < hud_top_row:
                                    world_tile = active_engine.screen_to_world(
                                        game_screen_tile[0], game_screen_tile[1], game_view_width, game_view_height
                                    )
                            event.world_tile = world_tile
                            if isinstance(handler, input_handlers.MainGameEventHandler):
                                if world_tile is not None and active_engine is not None:
                                    active_engine.mouse_x, active_engine.mouse_y = world_tile
                                elif active_engine is not None:
                                    # Keep last world-space mouse tile while easing;
                                    # do not warp to UI-space coordinates.
                                    if ui_tile[1] >= hud_top_row:
                                        active_engine.mouse_x, active_engine.mouse_y = ui_tile
                            elif isinstance(handler, input_handlers.SelectIndexHandler):
                                if world_tile is None and active_engine is not None:
                                    world_tile = active_engine.screen_to_world(
                                        game_screen_tile[0], game_screen_tile[1], game_view_width, game_view_height
                                    )
                                    event.world_tile = world_tile
                                if world_tile is not None:
                                    event.tile = world_tile
                                    if active_engine is not None:
                                        active_engine.mouse_x, active_engine.mouse_y = world_tile
                                        active_engine.mouse_location = world_tile
                            elif active_engine is not None:
                                active_engine.mouse_x, active_engine.mouse_y = ui_tile
                    # Mouse button state
                    if isinstance(event, tcod.event.MouseButtonDown) and event.button == tcod.event.BUTTON_LEFT:
                        _mouse_held = True
                    elif isinstance(event, tcod.event.MouseButtonUp) and event.button == tcod.event.BUTTON_LEFT:
                        _mouse_held = False
                    handler = handler.handle_events(event)
                    # Overlay dirty tracking
                    if isinstance(event, tcod.event.MouseMotion):
                        current_ui_tile = getattr(event, 'ui_tile', None)
                        if current_ui_tile != _last_dirty_ui_tile:
                            _last_dirty_ui_tile = current_ui_tile
                            overlay_dirty = True
                    else:
                        overlay_dirty = True
            except Exception: # handles game exceptions
                traceback.print_exc() #prints error to stderr
                if isinstance(handler, input_handlers.EventHandler):
                    handler.engine.message_log.add_message(
                        traceback.format_exc(), color.error 
                    )

            # Fire degauss + VHS glitch if handler transitioned to GameOver
            # during event processing (the pending_handler path at the top of
            # the loop may have been consumed by EventHandler.handle_events).
            if (isinstance(handler, input_handlers.GameOverEventHandler)
                    and _active_vhs_glitch is None):
                _active_degauss = DegaussAnimation(renderer)
                _active_vhs_glitch = VHSGlitchAnimation(renderer)

            # Frame limiting 
            elapsed = time.time() - current_time
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            last_time = current_time

    except exceptions.QuitWithoutSaving:
        raise
    except SystemExit: # save and quit
        save_game(handler, setup_game.get_save_path("savegame.sav"))
        raise
    except BaseException: # Save on any other unexpected exception
        save_game(handler, setup_game.get_save_path("savegame.sav"))
        raise


if __name__ == "__main__":
    # Context is already created and being used globally
    try:
        main()
    except Exception as e:
        print(f"Error during startup: {e}")
        raise
    finally:
        # Properly close the context when done
        if 'context' in globals():
            context.close()

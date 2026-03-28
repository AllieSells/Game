print("Starting THE Game...")
import time
# Package with python -m PyInstaller MyGame.spec
initial_time = time.time() # Track total loading


import os
os.environ["SDL_RENDER_SCALE_QUALITY"] = "1"  #  filtering when tiles are scaled
import warnings
import sys

from PIL import Image
import numpy as np

import tcod.sdl.mouse


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
sprite_manager.load_extras(tileset, get_data_path("RP/extras.png"))


# Create window immediately
context = tcod.context.new(
    columns=screen_width,
    rows=screen_height,
    width=1280,
    height=800,
    tileset=tileset,
    title="THE Game... Loading",
    vsync=False,  # Disable vsync for faster initial loading
)

# --- Procedural scanlines: sine-wave brightness modulation ---
renderer = context.sdl_renderer

def generate_scanlines_texture(line_density=3.0, intensity=0.35):
    """Generate a seamlessly tileable scanline overlay texture.

    *line_density* – controls how many scanlines per pixel (higher = thinner lines).
    *intensity*    – 0.0 = no effect, 1.0 = fully black troughs.
    The texture is 1 pixel wide (SDL stretches it horizontally) and its
    height is many exact sine periods so scrolling by 1px is smooth.
    """
    # Use many periods so each 1px scroll is a tiny fraction of the pattern
    period = 2.0 * np.pi / line_density
    single_h = max(int(np.round(period)), 2)
    # Make texture at least ~1024px tall for smooth sub-period scrolling
    repeats = max(1024 // single_h, 1)
    tile_h = single_h * repeats
    y = np.arange(tile_h, dtype=np.float32)
    scanline = 0.5 + 0.5 * np.sin(y * line_density)
    brightness = (1.0 - intensity * (1.0 - scanline))
    brightness_u8 = (np.clip(brightness, 0.0, 1.0) * 255).astype(np.uint8)
    # 1px wide RGBA texture
    tex_np = np.empty((tile_h, 1, 4), dtype=np.uint8)
    tex_np[..., 0] = brightness_u8[:, np.newaxis]
    tex_np[..., 1] = brightness_u8[:, np.newaxis]
    tex_np[..., 2] = brightness_u8[:, np.newaxis]
    tex_np[..., 3] = 255
    return tex_np

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

# --- CRT EFFECT: VIGNETTE ONLY ---
def create_vignette_texture(renderer, w=512, h=512):
    import numpy as np
    y, x = np.ogrid[:h, :w]
    cx, cy = w / 2, h / 2
    dist = ((x - cx)**2 + (y - cy)**2) / (cx*cx + cy*cy)
    vignette = np.clip(dist, 0, 1)
    alpha = (vignette * 50).astype(np.uint8)
    tex = np.zeros((h, w, 4), dtype=np.uint8)
    tex[..., 3] = alpha  # black with alpha only
    texture = renderer.upload_texture(tex)
    texture.blend_mode = tcod.sdl.render.BlendMode.BLEND
    return texture

vignette_tex = create_vignette_texture(renderer)

game_width = 80
game_height = 40
game_view_width = game_width // 2
game_view_height = game_height // 2


game_console = tcod.console.Console(game_view_width, game_view_height, order="F")
ui_console = tcod.console.Console(screen_width, screen_height, order="F")

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

    tile_x = int(pixel_x / (base_tile_w * 2))
    tile_y = int(pixel_y / (base_tile_h * 2))
    tile_x = max(0, min(game_view_width - 1, tile_x))
    tile_y = max(0, min(game_view_height - 1, tile_y))
    return tile_x, tile_y

def show_loading_screen(context, console, progress: float, status: str) -> None:
    """Display a loading screen with progress bar."""
    console.clear()
    # Center the loading screen
    screen_center_x = console.width // 2
    screen_center_y = console.height // 2
    # Title
    title = "Loading..."
    console.print(screen_center_x - len(title) // 2, screen_center_y - 4, title, fg=color.fantasy_text)
    # Progress bar
    bar_width = 40
    bar_x = screen_center_x - bar_width // 2
    bar_y = screen_center_y
    for i in range(bar_width):
        console.print(bar_x + i, bar_y, "░", fg=color.parchment_light)
    fill_width = int(bar_width * progress)
    for i in range(fill_width):
        console.print(bar_x + i, bar_y, "█", fg=color.gold_accent)
    percentage = f"{int(progress * 100)}%"
    console.print(screen_center_x - len(percentage) // 2, bar_y + 2, percentage, fg=color.gold_accent)
    console.print(screen_center_x - len(status) // 2, bar_y + 4, status, fg=color.fantasy_text)
    context.present(console)
    # --- Overlay scanlines statically ---
    try:
        renderer = context.sdl_renderer
        window_w, window_h = context.sdl_window.size
        if 'scanlines_tex' in globals() and scanlines_tex is not None:
            for _y in range(0, window_h, scanlines_h):
                _dh = min(scanlines_h, window_h - _y)
                renderer.copy(scanlines_tex,
                              source=(0, 0, 1, _dh),
                              dest=(0, _y, window_w, _dh))
            renderer.present()
    except Exception:
        pass

# Show loading screen immediately
show_loading_screen(context, ui_console, 0.05, "Starting...")

# Now load remaining modules
import json

start_time = time.time() # Track total loading


# Continue with module imports
show_loading_screen(context, ui_console, 0.15, "Avoiding glitches...")
import exceptions
str = (f"Loaded exceptions module in {time.time() - start_time:.2f} seconds")
print(str)
with open(get_data_path('logs/log.txt'), 'a') as log_file:
    log_file.write(str + "\n")

start_time = time.time() # Track total loading
show_loading_screen(context, ui_console, 0.30, "Building inputs...")
import input_handlers
str = (f"Loaded input_handlers module in {time.time() - start_time:.2f} seconds")
print(str)
with open(get_data_path('logs/log.txt'), 'a') as log_file:
    log_file.write(str + "\n")

start_time = time.time() # Track total loading
show_loading_screen(context, ui_console, 0.45, "Setting up dungeons...")
import setup_game
str = (f"Loaded setup_game module in {time.time() - start_time:.2f} seconds")
print(str)
with open(get_data_path('logs/log.txt'), 'a') as log_file:
    log_file.write(str + "\n")

start_time = time.time() # Track total loading
show_loading_screen(context, ui_console, 0.60, "Importing bananas...")
import tcod.sdl.video
import traceback
str = (f"Loaded tcod.sdl.video and traceback modules in {time.time() - start_time:.2f} seconds")
print(str)
with open(get_data_path('logs/log.txt'), 'a') as log_file:
    log_file.write(str + "\n")

def load_settings():
    """Load settings from JSON file."""
    try:
        with open("settings.json", 'r') as f:
            content = f.read()
            # Remove JSON comments
            lines = [line for line in content.split('\n') if not line.strip().startswith('//')]
            clean_content = '\n'.join(lines)
            return json.loads(clean_content)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"fullscreen": False, "audio": 50, "crt_scanlines": True, "crt_vignette": True, "crt_bloom": True, "crt_ca": True, "crt_curvature": True}

# Global reference for settings access
_game_context = None

# --- CRT toggle flags (loaded from settings.json) ---
_crt_scanlines_on = True
_crt_vignette_on = True
_crt_bloom_on = True
_crt_ca_on = True
_crt_curvature_on = True

def reload_crt_settings():
    """Reload CRT toggle flags from settings.json."""
    global _crt_scanlines_on, _crt_vignette_on, _crt_bloom_on, _crt_ca_on, _crt_curvature_on
    s = load_settings()
    _crt_scanlines_on = s.get("crt_scanlines", True)
    _crt_vignette_on = s.get("crt_vignette", True)
    _crt_bloom_on = s.get("crt_bloom", True)
    _crt_ca_on = s.get("crt_ca", True)
    _crt_curvature_on = s.get("crt_curvature", True)


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
    
    global _game_context, context, game_console, ui_console, cursor, cursor_click, _crt_force_fast_path
    
    # Use the global context and console that were created during initial loading
    _game_context = context

    # Transition helper: avoid heavy CRT passes while entering gameplay
    previous_has_game_view = False
    transition_frame_counter = 0
    transition_cooldown_frames = 8
    
    # Continue with actual loading operations
    show_loading_screen(context, ui_console, 0.75, "Loading game settings...")
    settings = load_settings()
    setting_fullscreen = settings.get("fullscreen", False)
    reload_crt_settings()
    
    show_loading_screen(context, ui_console, 0.85, "Initializing main menu...")
    handler: input_handlers.BaseEventHandler = setup_game.MainMenu()
   
    
    show_loading_screen(context, ui_console, 0.95, "Finalizing setup...")
    # Update context title
    context.sdl_window.title = "THE Game... idk"

    # Set initial fullscreen state based on settings
    window = context.sdl_window
    if window and setting_fullscreen:
        window.fullscreen = True
        print("DEBUG: Set initial fullscreen mode from settings")

    show_loading_screen(context, ui_console, 1.0, "Ready!")
    str = (f"Finished loading in {time.time() - initial_time:.2f} seconds")
    print(str)
    with open(get_data_path('logs/log.txt'), 'a') as log_file:
        log_file.write(str + "\n")
        log_file.write(f"Settings loaded: {settings}\n")
        log_file.write(f"=========================================================================================================================================================================================================================\n")
    # Brief pause to show completion
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


    # Start the main game loop
    import render_functions
    target_fps = 30
    frame_time = 1.0 / target_fps
    last_time = time.time()
    renderer = context.sdl_renderer
    tileset_atlas = tcod.render.SDLTilesetAtlas(renderer, tileset)
    game_console_renderer = tcod.render.SDLConsoleRender(tileset_atlas)
    ui_console_renderer = tcod.render.SDLConsoleRender(tileset_atlas)
    debug_console_renderer = tcod.render.SDLConsoleRender(tileset_atlas)
    debug_console = tcod.console.Console(40, 9, order="F")
    # 1×1 dim texture stretched over full screen for overlay fade (GPU-only, no CPU pixel work)
    dim_pixels = np.array([[[20, 20, 30, 100]]], dtype=np.uint8)
    dim_tex = renderer.upload_texture(dim_pixels)
    dim_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND

    # --- Regenerate procedural scanlines for current window size ---
    scanlines_np = generate_scanlines_texture(scanline_density, scanline_intensity)
    scanlines_tex = renderer.upload_texture(scanlines_np)
    scanlines_tex.blend_mode = tcod.sdl.render.BlendMode.MOD
    scanlines_h = scanlines_np.shape[0]
    scanlines_scroll = 0.0
    scanlines_speed = 10.0  # pixels per second
    game_tex = None
    ui_tex = None
    overlay_popup_console = None   # small console sized to menu bounding box
    overlay_popup_tex     = None   # GPU texture for popup (BLEND mode)
    overlay_popup_dest    = None   # screen dest rect for popup
    overlay_popup_src_size = None   # (w, h) pixel dimensions of popup texture
    cached_overlay_handler = None
    overlay_dirty = True
    _last_dirty_ui_tile = None  # track tile under cursor to avoid per-pixel dirty

    # Precompute texture source sizes for curvature helper
    _game_tex_w = game_console.width * tileset.tile_width
    _game_tex_h = game_console.height * tileset.tile_height
    _ui_tex_w = screen_width * tileset.tile_width
    _ui_tex_h = screen_height * tileset.tile_height
    _dbg_tex_w = 40 * tileset.tile_width
    _dbg_tex_h = 9 * tileset.tile_height
    _crt_bands = 96
    _crt_strength = 0.05  # horizontal barrel strength
    _crt_strength_v = 0.05  # vertical barrel strength

    # --- Chromatic aberration parameters ---
    _ca_shift = 1.5        # pixel shift for R/B channels (0 = disabled)

    # --- GPU bloom parameters ---
    _bloom_intensity = 255    # alpha_mod for final bloom composite (0-255)
    _bloom_passes = 1         # Kawase iterations (fewer = tighter glow)
    _bloom_downsample = 2     # downsample factor for bloom targets
    _bloom_threshold = 255    # soft threshold (0-255): lower = more glow, higher = only brights
    _bloom_spread = 1.0       # sample offset multiplier (lower = tighter, higher = wider)

    # --- GPU bloom render targets (created/resized lazily) ---
    _scene_tex = None         # full-res render target for scene capture
    _bloom_a = None           # small render target (ping)
    _bloom_b = None           # small render target (pong)
    _bloom_scene_w = 0        # cached scene dimensions for resize detection
    _bloom_scene_h = 0

    def copy_curved(tex, dest, source=None, src_size=None):
        """Copy a texture with CRT barrel curvature.

        Horizontal barrel narrows width toward top/bottom edges.
        Vertical barrel shifts height toward left/right edges.
        Set either strength to 0 to disable that axis.

        *source*  – optional (x, y, w, h) crop rect inside the texture.
        *src_size* – (w, h) of the full texture; needed when *source*
                     is ``None`` so we can split it into bands.
        """
        # Short-circuit when curvature is disabled or we are in transition fast-path
        if not _crt_curvature_on or _crt_force_fast_path:
            if source is not None:
                renderer.copy(tex, source=source, dest=dest)
            else:
                renderer.copy(tex, dest=dest)
            return
        dst_x, dst_y, dst_w, dst_h = (float(v) for v in dest)
        have_src = source is not None or src_size is not None
        if source is not None:
            sx, sy, sw, sh = (float(v) for v in source)
        elif src_size is not None:
            sx, sy, sw, sh = 0.0, 0.0, float(src_size[0]), float(src_size[1])
        else:
            sx, sy, sw, sh = 0.0, 0.0, 0.0, 0.0

        wh = float(window_h)
        ww = float(window_w)
        inv_wh = 1.0 / wh if wh > 0 else 1.0
        inv_ww = 1.0 / ww if ww > 0 else 1.0
        st_h = _crt_strength
        st_v = _crt_strength_v

        # Helper: compute the distorted Y for a given normalized fraction f
        # along the destination rect.  Vertical barrel shrinks toward left/right.
        def _distort_y(f, horz_scale_at_f):
            """Return distorted pixel-Y for fraction f of the dest rect."""
            base_y = dst_y + f * dst_h
            if st_v > 0:
                # Use the horizontal scale at this band to estimate X center
                bw_est = dst_w * horz_scale_at_f
                cx_est = dst_x + (dst_w - bw_est) * 0.5 + bw_est * 0.5
                nx = (cx_est * inv_ww - 0.5) * 2.0
                vert_scale = 1.0 - st_v * nx * nx
                center_y = dst_y + 0.5 * dst_h
                base_y = center_y + (base_y - center_y) * vert_scale
            return base_y

        for i in range(_crt_bands):
            f0 = i / _crt_bands
            f1 = (i + 1) / _crt_bands

            # Horizontal barrel at this band's center
            f_mid = (f0 + f1) * 0.5
            mid_y = dst_y + f_mid * dst_h
            ny = (mid_y * inv_wh - 0.5) * 2.0
            horz_scale = 1.0 - st_h * ny * ny
            bw = int(dst_w * horz_scale)
            bx = int(dst_x + (dst_w - bw) * 0.5)

            # Continuous vertical barrel: distort top/bottom edges so bands
            # share boundaries — no gaps.
            by0 = int(_distort_y(f0, horz_scale))
            by1 = int(_distort_y(f1, horz_scale))
            bh = by1 - by0
            if bh <= 0:
                continue

            if have_src and sh > 1:
                bsy0 = int(sy + f0 * sh)
                bsy1 = int(sy + f1 * sh)
                bsh = bsy1 - bsy0
                if bsh <= 0:
                    continue
                renderer.copy(tex,
                              source=(int(sx), bsy0, int(sw), bsh),
                              dest=(bx, by0, bw, bh))
            elif have_src:
                renderer.copy(tex,
                              source=(int(sx), int(sy), int(sw), max(1, int(sh))),
                              dest=(bx, by0, bw, bh))
            else:
                renderer.copy(tex, dest=(bx, by0, bw, bh))

    def undistort_mouse(px, py):
        """Map a screen pixel back to the logical (pre-distortion) position."""
        if not _crt_curvature_on:
            return float(px), float(py)
        wh = float(window_h)
        ww = float(window_w)
        st_h = _crt_strength
        st_v = _crt_strength_v
        # Invert horizontal barrel
        ny = (py / wh - 0.5) * 2.0 if wh > 0 else 0.0
        horz_scale = 1.0 - st_h * ny * ny
        if horz_scale > 0:
            center_offset = ww * (1.0 - horz_scale) * 0.5
            logical_x = (px - center_offset) / horz_scale
        else:
            logical_x = px
        # Invert vertical barrel
        if st_v > 0:
            nx = (logical_x / ww - 0.5) * 2.0 if ww > 0 else 0.0
            vert_scale = 1.0 - st_v * nx * nx
            if vert_scale > 0:
                center_offset_y = wh * (1.0 - vert_scale) * 0.5
                logical_y = (py - center_offset_y) / vert_scale
            else:
                logical_y = py
        else:
            logical_y = py
        return logical_x, logical_y

    def copy_curved_crt(tex, dest, source=None, src_size=None):
        """Draw a texture with CRT curvature and chromatic aberration."""
        ca = _ca_shift if (_crt_ca_on and not _crt_force_fast_path) else 0

        # Save original texture properties
        orig_color = tex.color_mod
        orig_blend = tex.blend_mode
        orig_alpha = tex.alpha_mod

        if ca > 0:
            # --- Chromatic aberration: 3 additive colour-channel passes ---
            dx, dy, dw, dh = dest
            tex.blend_mode = tcod.sdl.render.BlendMode.ADD

            # Red channel – shifted left
            tex.color_mod = (255, 0, 0)
            copy_curved(tex, (dx - ca, dy, dw, dh), source=source, src_size=src_size)

            # Green channel – centred
            tex.color_mod = (0, 255, 0)
            copy_curved(tex, dest, source=source, src_size=src_size)

            # Blue channel – shifted right
            tex.color_mod = (0, 0, 255)
            copy_curved(tex, (dx + ca, dy, dw, dh), source=source, src_size=src_size)
        else:
            # No CA – single normal draw
            tex.color_mod = orig_color
            tex.blend_mode = orig_blend
            copy_curved(tex, dest, source=source, src_size=src_size)

        # Restore original texture properties
        tex.color_mod = orig_color
        tex.blend_mode = orig_blend
        tex.alpha_mod = orig_alpha

    def _ensure_bloom_targets(w, h):
        """Create or resize GPU render targets for bloom."""
        nonlocal _scene_tex, _bloom_a, _bloom_b, _bloom_scene_w, _bloom_scene_h
        if w == _bloom_scene_w and h == _bloom_scene_h:
            return
        _bloom_scene_w, _bloom_scene_h = w, h
        ds = _bloom_downsample
        bw, bh = max(1, w // ds), max(1, h // ds)
        _TA = tcod.sdl.render.TextureAccess.TARGET
        _scene_tex = renderer.new_texture(w, h, access=_TA)
        _bloom_a = renderer.new_texture(bw, bh, access=_TA)
        _bloom_b = renderer.new_texture(bw, bh, access=_TA)

    def gpu_bloom():
        """Run a full GPU Kawase bloom pass from _scene_tex.

        1. Downsample scene into bloom_a (GPU bilinear filtering)
        2. Ping-pong Kawase blur between bloom_a and bloom_b
        3. Copy final result onto the default framebuffer with ADD blend
        All GPU-side — zero CPU pixel work.
        """
        if _scene_tex is None or _bloom_intensity <= 0:
            return
        ds = _bloom_downsample
        bw = max(1, _bloom_scene_w // ds)
        bh = max(1, _bloom_scene_h // ds)

        # 1. Downsample with soft threshold via color_mod
        # color_mod dims all pixels proportionally (GPU multiply).
        # A single pass acts as a soft brightness gate.
        t = _bloom_threshold  # 0-255
        tex_a, tex_b = _bloom_a, _bloom_b
        with renderer.set_render_target(tex_a):
            renderer.draw_color = (0, 0, 0, 255)
            renderer.clear()
            _scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
            _scene_tex.alpha_mod = 255
            _scene_tex.color_mod = (t, t, t)
            renderer.copy(_scene_tex, dest=(0, 0, bw, bh))

        # 2. Kawase blur ping-pong — small offsets, many passes = round glow
        # Standard Kawase sequence: offset grows slowly (i+1 texels)
        src, dst = tex_a, tex_b
        for i in range(_bloom_passes):
            offset = max(1, int((i + 1) * _bloom_spread))  # controlled by _bloom_spread
            src.blend_mode = tcod.sdl.render.BlendMode.ADD
            src.alpha_mod = 51  # ~1/5 per tap, 5 taps ≈ 1.0
            with renderer.set_render_target(dst):
                renderer.draw_color = (0, 0, 0, 255)
                renderer.clear()
                # 5-tap Kawase: center + 4 diagonal offsets
                for dx, dy in [(0, 0), (-offset, -offset), (offset, -offset),
                                (-offset, offset), (offset, offset)]:
                    renderer.copy(src, dest=(dx, dy, bw, bh))
            src.alpha_mod = 255
            src, dst = dst, src  # swap for next pass

        # After the loop, `src` holds the final blurred result
        # 3. Composite bloom onto the default framebuffer
        src.blend_mode = tcod.sdl.render.BlendMode.ADD
        src.alpha_mod = _bloom_intensity
        renderer.copy(src, dest=(0, 0, window_w, window_h))

    # Set initial cursor (cursors were already loaded at top of file)
    tcod.sdl.mouse.set_cursor(cursor)
    _mouse_held = False

    try:
        while True:

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
            has_game_view = (
                active_engine is not None
                and getattr(active_engine, "game_map", None) is not None
            )
            map_overlay_view = (
                has_game_view
                and isinstance(handler, input_handlers.SelectIndexHandler)
            )
            inspect_overlay_view = isinstance(handler, input_handlers.LookHandler)
            main_game_view = (
                has_game_view
                and isinstance(handler, input_handlers.MainGameEventHandler)
            )
            fast_main_view = main_game_view  # debug overlay uses dirty-tracking, no need to exclude
            needs_live_game_frame = main_game_view or game_tex is None

            # Transition fast-path: disable expensive CRT effects during initial world entry
            if has_game_view and not previous_has_game_view:
                transition_frame_counter = 0
            if has_game_view and transition_frame_counter < transition_cooldown_frames:
                transition_frame_counter += 1
                _crt_force_fast_path = True
            else:
                _crt_force_fast_path = False
            previous_has_game_view = has_game_view

            current_time = time.time()
            # Always use context.sdl_window.size for window and mouse mapping
            window_w, window_h = context.sdl_window.size
            base_tile_w = window_w / screen_width
            base_tile_h = window_h / screen_height
            game_dest_w = game_view_width * base_tile_w * 2
            game_dest_h = game_view_height * base_tile_h * 2
            hud_top_row = game_height - 1
            hud_rows = screen_height - hud_top_row
            hud_source_y = hud_top_row * tileset.tile_height
            hud_source_h = hud_rows * tileset.tile_height
            hud_dest_h = hud_rows * base_tile_h

            if main_game_view:
                game_console.clear()
                handler.engine.tick(console=game_console)

            if has_game_view and needs_live_game_frame and not map_overlay_view:
                active_engine.render_game(game_console)

            # --- Begin scene rendering to off-screen target for GPU bloom ---
            _ensure_bloom_targets(window_w, window_h)
            _scene_ctx = renderer.set_render_target(_scene_tex)

            if fast_main_view:
                renderer.clear()
                game_tex = game_console_renderer.render(game_console)
                # Game view — GPU curvature via copy_curved
                copy_curved_crt(game_tex,
                            dest=(0, 0, game_dest_w, game_dest_h),
                            src_size=(_game_tex_w, _game_tex_h))

                if getattr(active_engine, "debug", False):
                    cached_overlay_handler = None
                    overlay_dirty = True
                    ui_console.clear()
                    active_engine.render_ui(ui_console, skip_debug=True)
                    hud_tex = ui_console_renderer.render(ui_console)
                    copy_curved_crt(hud_tex,
                                dest=(0, window_h - hud_dest_h, window_w, hud_dest_h),
                                source=(0, hud_source_y, _ui_tex_w, hud_source_h))
                    debug_console.clear()
                    render_functions.render_debug_overlay(
                        debug_console,
                        active_engine.tick_rate,
                        (active_engine.player.x, active_engine.player.y),
                        type(handler).__name__,
                        len(active_engine.game_map.entities),
                        active_engine,
                    )
                    dbg_tex = debug_console_renderer.render(debug_console)
                    copy_curved_crt(dbg_tex,
                                dest=(0, 0, int(40 * base_tile_w), int(9 * base_tile_h)),
                                src_size=(_dbg_tex_w, _dbg_tex_h))
                else:
                    cached_overlay_handler = None
                    overlay_dirty = True
                    ui_console.clear()
                    active_engine.render_ui(ui_console)
                    hud_tex = ui_console_renderer.render(ui_console)
                    copy_curved_crt(hud_tex,
                                dest=(0, window_h - hud_dest_h, window_w, hud_dest_h),
                                source=(0, hud_source_y, _ui_tex_w, hud_source_h))
                    _sb = getattr(active_engine, 'speech_bubble_ui_rect', None)
                    if _sb:
                        _sb_x, _sb_y, _sb_w, _sb_h = _sb
                        _tw, _th = tileset.tile_width, tileset.tile_height
                        copy_curved_crt(hud_tex,
                                    dest=(int(_sb_x * base_tile_w), int(_sb_y * base_tile_h),
                                          int(_sb_w * base_tile_w), int(_sb_h * base_tile_h)),
                                    source=(_sb_x * _tw, _sb_y * _th, _sb_w * _tw, _sb_h * _th))
                # CRT effects are now applied globally after all rendering, see below

            elif map_overlay_view:
                cached_overlay_handler = None
                overlay_dirty = True
                renderer.clear()

                game_console.clear()
                if inspect_overlay_view:
                    active_engine.render_game(game_console)
                    handler.render_game_overlay(game_console)
                else:
                    handler.on_render(console=game_console)
                game_tex = game_console_renderer.render(game_console)
                copy_curved_crt(game_tex,
                            dest=(0, 0, game_dest_w, game_dest_h),
                            src_size=(_game_tex_w, _game_tex_h))

                ui_console.clear()
                active_engine.render_ui(ui_console)
                if inspect_overlay_view:
                    handler.render_ui_overlay(ui_console)
                    ui_pixels = render_console_with_transparency(ui_console)
                    if ui_tex is None:
                        ui_tex = renderer.upload_texture(ui_pixels)
                        ui_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    else:
                        ui_tex.update(ui_pixels)
                        # No CA for transparent overlays — ADD blend breaks transparency
                        copy_curved(ui_tex,
                                    dest=(0, 0, window_w, window_h),
                                    src_size=(_ui_tex_w, _ui_tex_h))
                else:
                    hud_tex = ui_console_renderer.render(ui_console)
                    copy_curved_crt(hud_tex,
                                dest=(0, window_h - hud_dest_h, window_w, hud_dest_h),
                                source=(0, hud_source_y, _ui_tex_w, hud_source_h))
                # CRT effects are now applied globally after all rendering, see below
            elif has_game_view:
                renderer.clear()
                if needs_live_game_frame:
                    game_tex = game_console_renderer.render(game_console)
                copy_curved_crt(game_tex,
                            dest=(0, 0, game_dest_w, game_dest_h),
                            src_size=(_game_tex_w, _game_tex_h))

                # Dim the game underneath the overlay (1×1 GPU pixel stretched to full screen)
                copy_curved(dim_tex,
                            dest=(0, 0, window_w, window_h),
                            src_size=(1, 1))

                if overlay_dirty or cached_overlay_handler is not handler:
                    ui_console.clear()
                    handler.on_render(console=ui_console)
                    cached_overlay_handler = handler
                    overlay_dirty = False

                    # Find the bounding box of non-blank popup content (above HUD)
                    _ch  = ui_console.ch[:, :hud_top_row]
                    _bg  = ui_console.bg[:, :hud_top_row, :]
                    _content = (_ch != ord(' ')) | np.any(_bg > 16, axis=2)
                    _cells = np.where(_content)

                    if _cells[0].size > 0:
                        _mx1 = int(_cells[0].min())
                        _my1 = int(_cells[1].min())
                        _mx2 = int(_cells[0].max()) + 1
                        _my2 = int(_cells[1].max()) + 1
                        _sw, _sh = _mx2 - _mx1, _my2 - _my1

                        # Reuse sub-console when size is unchanged (avoids allocation)
                        if (overlay_popup_console is None
                                or overlay_popup_console.width  != _sw
                                or overlay_popup_console.height != _sh):
                            overlay_popup_console = tcod.console.Console(_sw, _sh, order="F")
                            overlay_popup_tex = None  # texture size changed — must recreate

                        # Blit only the menu region — tiny CPU transparency render
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
                        overlay_popup_src_size = (_popup_pixels.shape[1], _popup_pixels.shape[0])
                    else:
                        overlay_popup_tex  = None
                        overlay_popup_dest = None
                        overlay_popup_src_size = None

                # Draw cached popup (BLEND — transparent cells show game behind)
                # No CA here — ADD blend from CA would break popup transparency
                if overlay_popup_tex is not None and overlay_popup_dest is not None:
                    copy_curved(overlay_popup_tex, dest=overlay_popup_dest,
                                src_size=overlay_popup_src_size)

                # HUD strip — fast GPU path, no CPU pixel work
                _ov_hud_tex = ui_console_renderer.render(ui_console)
                copy_curved_crt(_ov_hud_tex,
                            dest=(0, window_h - hud_dest_h, window_w, hud_dest_h),
                            source=(0, hud_source_y, _ui_tex_w, hud_source_h))
                # CRT effects are now applied globally after all rendering, see below
            else:
                cached_overlay_handler = None
                overlay_dirty = True
                ui_console.clear()
                handler.on_render(console=ui_console)
                # Render UI console to GPU texture, then draw with curvature
                renderer.clear()
                ui_tex = ui_console_renderer.render(ui_console)
                copy_curved_crt(ui_tex,
                            dest=(0, 0, window_w, window_h),
                            src_size=(_ui_tex_w, _ui_tex_h))
                # CRT effects are now applied globally after all rendering, see below

            # --- End scene rendering: restore default target, blit scene, bloom ---
            _scene_ctx.__exit__(None, None, None)  # restore default render target

            # Copy rendered scene from off-screen target to the default framebuffer
            _scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
            _scene_tex.alpha_mod = 255
            _scene_tex.color_mod = (255, 255, 255)
            renderer.copy(_scene_tex, dest=(0, 0, window_w, window_h))

            # GPU bloom: downsample + Kawase blur + ADD composite (all GPU)
            if _crt_bloom_on and not _crt_force_fast_path:
                gpu_bloom()

            # Scanlines
            if _crt_scanlines_on and not _crt_force_fast_path:
                scanlines_scroll = (scanlines_scroll + scanlines_speed * (1.0 / target_fps)) % scanlines_h
                y_offset = int(scanlines_scroll)
                # Tile the 1px-wide scanline texture across the screen, wrapping vertically
                y = -y_offset
                while y < window_h:
                    tile_h = min(scanlines_h, window_h - y) if y >= 0 else min(scanlines_h + y, window_h)
                    src_y = 0 if y >= 0 else -y
                    dst_y = max(y, 0)
                    draw_h = min(scanlines_h - src_y, window_h - dst_y)
                    if draw_h > 0:
                        renderer.copy(scanlines_tex,
                                      source=(0, src_y, 1, draw_h),
                                      dest=(0, dst_y, window_w, draw_h))
                    y += scanlines_h
            if _crt_vignette_on and not _crt_force_fast_path:
                renderer.copy(vignette_tex, dest=(0, 0, window_w, window_h))
            renderer.present()

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

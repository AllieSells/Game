print("Starting DoA...")
import time
# Package with python -m PyInstaller MyGame.spec
initial_time = time.time() # Track total loading


import os
os.environ["SDL_RENDER_SCALE_QUALITY"] = "1"  #  filtering when tiles are scaled
import warnings
import sys

from PIL import Image
import numpy as np
import random
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


# --- Render checkpoint logger ---
# Opened once and kept open so each flush is guaranteed to reach disk before
# a GPU TDR can kill the process silently.
_render_log_file = open(log_path, "a", buffering=1)  # line-buffered
_render_frame = 0

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
sprite_manager.load_extras(tileset, get_data_path("RP/extras.png"))


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
)

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

vignette_tex = create_vignette_texture(renderer)
glare_tex = create_glare_texture(renderer)

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
    # Pump the SDL event queue so the OS doesn't mark the window as
    # non-responsive during heavy loading pauses.  Events are discarded
    # because no input is processed on the loading screen.
    for _ in tcod.event.get():
        pass
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
    # context.present() renders the console AND calls SDL_RenderPresent internally.
    # Do NOT call renderer.present() afterwards — that would be a second
    # SDL_RenderPresent on an undefined backbuffer while vsync=True, which
    # causes a GPU pipeline stall / hang on Windows DXGI backends.
    context.present(console)

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
    
    global _game_context, context, game_console, ui_console, cursor, cursor_click, _crt_force_fast_path, _render_frame, _active_degauss
    
    # Use the global context and console that were created during initial loading
    _game_context = context

    # Transition helper: avoid heavy CRT passes while entering gameplay
    previous_has_game_view = False
    transition_frame_counter = 0
    transition_cooldown_frames = 0
    
    # Continue with actual loading operations
    show_loading_screen(context, ui_console, 0.75, "Loading game settings...")
    settings = load_settings()
    setting_fullscreen = settings.get("fullscreen", False)
    reload_crt_settings()
    
    show_loading_screen(context, ui_console, 0.85, "Initializing main menu...")
    handler: input_handlers.BaseEventHandler = setup_game.MainMenu()
   
    
    show_loading_screen(context, ui_console, 0.95, "Finalizing setup...")
    # Update context title
    context.sdl_window.title = "DoA: Dungeons of Ærrok"

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
    # CRT jitter state — rare single-scanline drift (electron beam slip)
    _jitter_x = 0        # horizontal pixel offset for the jitter band
    _jitter_y = 0        # top Y coordinate of the jitter band on screen
    _jitter_band_h = 3   # height of the jitter band in pixels
    _jitter_frames = 0   # frames remaining for active jitter
    # CRT vertical-roll state — very rare, slow screen-roll (sync loss)
    _vroll_offset = 0.0      # current vertical pixel offset of the scene
    _vroll_speed  = 0.0      # pixels/sec (positive = rolling downward)
    _vroll_ttl    = 0.0      # seconds remaining for this roll event
    _vroll_next   = float(np.random.uniform(5.0, 10.0))  # seconds until next roll
    _vroll_elapsed = 0.0     # total seconds in main loop (for roll scheduling)
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
    _crt_bands = 116  # smooth curvature

    # --- Create GPU stack (owns all render targets, particles, post-processing) ---
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
    global _gpu_instance
    _gpu_instance = gpu
    # Sync CRT toggles from settings into the gpu stack
    s = load_settings()
    gpu.crt_scanlines_on = s.get("crt_scanlines", True)
    gpu.crt_vignette_on  = s.get("crt_vignette",  True)
    gpu.crt_bloom_on     = s.get("crt_bloom",      True)
    gpu.crt_ca_on        = s.get("crt_ca",         True)
    gpu.crt_curvature_on = s.get("crt_curvature",  True)
    gpu.crt_bands        = _crt_bands

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
    # CRT power-on capture: after gen, we flip to MainGameEventHandler first,
    # then let the game render one full frame, capture it, and reveal it via play_on.
    _crt_on_capture_pending = False  # waiting to capture the first real game frame
    _crt_on_scene_tex       = None   # captured game frame for play_on
    _crt_on_scene_tex_size  = (0, 0)

    try:
        while True:

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
                        # Fire degauss when the player dies
                        if isinstance(handler, input_handlers.GameOverEventHandler):
                            _active_degauss = DegaussAnimation(renderer)
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
            # in progress — engine.game_map exists before generation_complete=True,
            # which would prematurely fire TRANSITION and break the CRT timing.
            _loading_in_progress = (
                hasattr(handler, 'generation_complete')
                and not handler.generation_complete
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
                _rlog(f"TRANSITION: entering game view (handler={type(handler).__name__})")
                _suppress_degauss_once = False
            _gen_in_progress = _loading_in_progress
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
            window_w, window_h = context.sdl_window.size

            # ------------------------------------------------------------------
            # CRT POWER-SWITCH fast path for LoadingScreen world generation
            # ------------------------------------------------------------------
            # Phase 1 — screen-off: played once on the first frame _gen_in_progress
            #           becomes True.  Runs blocking on main thread; GPU is trivially
            #           idle, so no vsync stalls possible.
            # Phase 2 — black hold: while gen is running, render nothing but black
            #           + a "..." dot animation via draw_color only (zero textures).
            # Phase 3 — screen-on: played once when generation_complete flips True.
            #           Expands from line to full scene, then falls through normally,
            #           allowing the main loop to transition to MainGameEventHandler.
            _rlog(f"CRT_STATE frame={_render_frame} gen={_gen_in_progress} off={_crt_off_played} on={_crt_on_played} snap={'yes' if _gen_scene_tex is not None else 'no'} handler={type(handler).__name__} gen_complete={getattr(handler,'generation_complete',None)}")
            if _gen_in_progress:
                # Kick off the generation thread if on_render() hasn't done it
                # (we bypass on_render entirely to prevent the loading screen UI
                # from ever appearing, so we must start it ourselves).
                if hasattr(handler, 'generation_started') and not handler.generation_started:
                    _rlog(f"CRT: starting generation thread")
                    handler.generation_started = True
                    handler.start_generation()

                if not _crt_off_played:
                    if _gen_scene_tex is not None:
                        _rlog(f"CRT: playing screen-OFF animation")
                        _crt_off_played = True
                        _sw_anim = CRTSwitchAnimation(renderer, window_w, window_h)
                        _sw_anim.play_off(_gen_scene_tex, event_pump=tcod.event.get, glare_tex=glare_tex)
                        del _sw_anim
                        _rlog(f"CRT: screen-OFF done")
                    else:
                        _rlog(f"CRT: waiting for snapshot (gen in progress, no snap yet)")
                    # else: snapshot not ready yet — drop one black frame, try next
                renderer.draw_color = (0, 0, 0, 255)
                renderer.clear()
                renderer.copy(glare_tex, dest=(0, 0, window_w, window_h))
                renderer.present()
                for _ in tcod.event.get():
                    pass
                time.sleep(frame_time)
                continue

            elif _crt_off_played and not _crt_on_played:
                # Generation finished — flip to game handler NOW so the engine
                # renders a real frame next iteration, which we capture and
                # reveal via the CRT power-on animation.
                _rlog(f"CRT: gen done — transitioning to MainGameEventHandler (capture pending)")
                _crt_on_played = True
                _gen_scene_tex       = None
                _gen_scene_tex_size  = (0, 0)
                _crt_off_played      = False
                _crt_on_played       = False
                _suppress_degauss_once = True
                class _CRTTransitionEvent:
                    _crt_transition = True
                new_handler = handler.handle_events(_CRTTransitionEvent())
                _rlog(f"CRT: handler after transition = {type(new_handler).__name__}")
                if new_handler is not handler:
                    handler = new_handler
                    overlay_dirty = True
                # Flag the main loop to capture the next rendered game frame
                _crt_on_capture_pending = True
                # Render black this frame while the new handler initialises
                renderer.draw_color = (0, 0, 0, 255)
                renderer.clear()
                renderer.copy(glare_tex, dest=(0, 0, window_w, window_h))
                renderer.present()
                for _ in tcod.event.get():
                    pass
                time.sleep(frame_time)
                continue

            # Always use context.sdl_window.size for window and mouse mapping
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

            # --- Update gpu object with current frame dimensions ---
            gpu.update_frame_dims(window_w, window_h, base_tile_w, base_tile_h)
            gpu.crt_force_fast_path = _crt_force_fast_path

            # --- Begin scene rendering to off-screen target for GPU bloom ---
            _rlog(f"ensure_bloom_targets({window_w},{window_h}) fast={_crt_force_fast_path}")
            gpu.ensure_bloom_targets(window_w, window_h)
            _rlog("set_render_target(scene_tex)")
            _scene_ctx = renderer.set_render_target(gpu.scene_tex)

            def _apply_lightmap():
                if _crt_force_fast_path or not has_game_view:
                    return
                gpu.apply_lightmap(active_engine, game_dest_w, game_dest_h, game_console)

            if fast_main_view:
                renderer.clear()
                game_tex = game_console_renderer.render(game_console)
                renderer.copy(game_tex, dest=(0, 0, int(game_dest_w), int(game_dest_h)))
                _apply_lightmap()

                if getattr(active_engine, "debug", False):
                    cached_overlay_handler = None
                    overlay_dirty = True
                    ui_console.clear()
                    active_engine.render_ui(ui_console, skip_debug=True)
                    hud_tex = ui_console_renderer.render(ui_console)
                    renderer.copy(hud_tex,
                                  source=(0, int(hud_source_y), int(_ui_tex_w), int(hud_source_h)),
                                  dest=(0, int(window_h - hud_dest_h), window_w, int(hud_dest_h)))
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
                    renderer.copy(dbg_tex, dest=(0, 0, int(40 * base_tile_w), int(9 * base_tile_h)))
                else:
                    cached_overlay_handler = None
                    overlay_dirty = True
                    ui_console.clear()
                    active_engine.render_ui(ui_console)
                    hud_tex = ui_console_renderer.render(ui_console)
                    renderer.copy(hud_tex,
                                  source=(0, int(hud_source_y), int(_ui_tex_w), int(hud_source_h)),
                                  dest=(0, int(window_h - hud_dest_h), window_w, int(hud_dest_h)))
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
                renderer.clear()

                game_console.clear()
                if inspect_overlay_view:
                    active_engine.render_game(game_console)
                    handler.render_game_overlay(game_console)
                else:
                    handler.on_render(console=game_console)
                game_tex = game_console_renderer.render(game_console)
                renderer.copy(game_tex, dest=(0, 0, int(game_dest_w), int(game_dest_h)))
                _apply_lightmap()

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
                    renderer.copy(ui_tex, dest=(0, 0, window_w, window_h))
                else:
                    hud_tex = ui_console_renderer.render(ui_console)
                    renderer.copy(hud_tex,
                                  source=(0, int(hud_source_y), int(_ui_tex_w), int(hud_source_h)),
                                  dest=(0, int(window_h - hud_dest_h), window_w, int(hud_dest_h)))
            elif has_game_view:
                renderer.clear()
                if needs_live_game_frame:
                    game_tex = game_console_renderer.render(game_console)
                renderer.copy(game_tex, dest=(0, 0, int(game_dest_w), int(game_dest_h)))
                _apply_lightmap()

                # Dim the game underneath the overlay
                renderer.copy(dim_tex, dest=(0, 0, window_w, window_h))

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

                if overlay_popup_tex is not None and overlay_popup_dest is not None:
                    renderer.copy(overlay_popup_tex, dest=overlay_popup_dest)

                # HUD strip
                _ov_hud_tex = ui_console_renderer.render(ui_console)
                renderer.copy(_ov_hud_tex,
                              source=(0, int(hud_source_y), int(_ui_tex_w), int(hud_source_h)),
                              dest=(0, int(window_h - hud_dest_h), window_w, int(hud_dest_h)))
            else:
                cached_overlay_handler = None
                overlay_dirty = True
                ui_console.clear()
                handler.on_render(console=ui_console)
                renderer.clear()
                ui_tex = ui_console_renderer.render(ui_console)
                renderer.copy(ui_tex, dest=(0, 0, window_w, window_h))

            # --- End scene rendering: restore default target, apply global CRT post-process ---
            _rlog("restore_render_target")
            _scene_ctx.__exit__(None, None, None)  # restore default render target

            # Global CRT post-process pipeline:
            # 1. Barrel+CA on _scene_tex → captured into _post_crt_tex
            # 2. _post_crt_tex copied to default framebuffer
            # 3. Scanlines (MOD) → dims the CRT image
            # 4. Vignette (BLEND) → darkens edges
            # 5. Bloom (ADD) → sourced from _post_crt_tex so glow positions
            #    match the barrel-distorted display exactly
            _rlog("copy_scene_tex")
            # Step 1: barrel distortion only — 96 calls, single colour pass
            with renderer.set_render_target(gpu.barrel_tex):
                renderer.draw_color = (0, 0, 0, 255)
                renderer.clear()
                gpu.scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                gpu.scene_tex.alpha_mod = 255
                gpu.scene_tex.color_mod = (255, 255, 255)
                copy_curved(gpu.scene_tex, dest=(0, 0, window_w, window_h), src_size=(window_w, window_h))

            # Step 2: chromatic aberration — 3 flat pixel-shifts of the barrel result
            with renderer.set_render_target(gpu.post_crt_tex):
                renderer.draw_color = (0, 0, 0, 255)
                renderer.clear()
                if gpu.crt_ca_on and not _crt_force_fast_path and gpu.ca_shift > 0:
                    ca = round(gpu.ca_shift)
                    gpu.barrel_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                    gpu.barrel_tex.alpha_mod = 255
                    gpu.barrel_tex.color_mod = (255, 0, 0)
                    renderer.copy(gpu.barrel_tex, dest=(-ca, 0, window_w, window_h))
                    gpu.barrel_tex.color_mod = (0, 255, 0)
                    renderer.copy(gpu.barrel_tex, dest=(0, 0, window_w, window_h))
                    gpu.barrel_tex.color_mod = (0, 0, 255)
                    renderer.copy(gpu.barrel_tex, dest=(ca, 0, window_w, window_h))
                    gpu.barrel_tex.color_mod = (255, 255, 255)
                    gpu.barrel_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                else:
                    gpu.barrel_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    gpu.barrel_tex.alpha_mod = 255
                    gpu.barrel_tex.color_mod = (255, 255, 255)
                    renderer.copy(gpu.barrel_tex, dest=(0, 0, window_w, window_h))

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

            # CRT power-on: once the game handler has rendered its first real frame,
            # capture it and play the reveal animation into it.
            if _crt_on_capture_pending and has_game_view:
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
                _rlog(f"CRT: playing screen-ON animation with real game frame")
                _sw_anim = CRTSwitchAnimation(renderer, window_w, window_h)
                _sw_anim.play_on(_crt_on_scene_tex, event_pump=tcod.event.get, glare_tex=glare_tex)
                del _sw_anim
                _rlog(f"CRT: screen-ON done")
                _crt_on_scene_tex      = None
                _crt_on_scene_tex_size = (0, 0)
                continue   # skip outer present(); play_on already presented final frame

            # Blit post-CRT image to default framebuffer
            gpu.post_crt_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
            gpu.post_crt_tex.alpha_mod = 255
            gpu.post_crt_tex.color_mod = (255, 255, 255)
            if not _crt_force_fast_path and _vroll_offset != 0.0:
                _vo = int(_vroll_offset) % window_h
                if _vo < 0:
                    _vo += window_h
                if _vo == 0:
                    renderer.copy(gpu.post_crt_tex, dest=(0, 0, window_w, window_h))
                else:
                    # Bottom strip: source [0 .. window_h-_vo] → dest [_vo .. window_h]
                    _bot_h = window_h - _vo
                    renderer.copy(gpu.post_crt_tex,
                                  source=(0, 0, window_w, _bot_h),
                                  dest=(0, _vo, window_w, _bot_h))
                    # Top strip: source [window_h-_vo .. window_h] → dest [0 .. _vo]
                    renderer.copy(gpu.post_crt_tex,
                                  source=(0, _bot_h, window_w, _vo),
                                  dest=(0, 0, window_w, _vo))
            else:
                renderer.copy(gpu.post_crt_tex, dest=(0, 0, window_w, window_h))

            # CRT scanline jitter: occasionally one thin horizontal band slips sideways
            if not _crt_force_fast_path:
                if _jitter_frames > 0:
                    _jitter_frames -= 1
                    _src_x = max(-_jitter_x, 0)
                    _dst_x = max(_jitter_x, 0)
                    _band_w = window_w - abs(_jitter_x)
                    renderer.copy(
                        gpu.post_crt_tex,
                        source=(_src_x, _jitter_y, _band_w, _jitter_band_h),
                        dest=(_dst_x, _jitter_y, _band_w, _jitter_band_h),
                    )
                    if _jitter_frames == 0:
                        _jitter_x = 0
                elif np.random.random() < 0.25:  # ~0.8% chance/frame ≈ once per ~4 s at 30 fps
                    _jitter_x = int(np.random.choice([-4, -3, -2, 2, 3, 4]))
                    _jitter_y = int(np.random.randint(4, window_h - 8))
                    _jitter_band_h = int(np.random.choice([2, 2, 3, 3, 4]))
                    _jitter_frames = int(np.random.randint(1, 3))

            # CRT vertical roll: schedule and advance
            if not _crt_force_fast_path:
                _dt_frame = 1.0 / target_fps
                _vroll_elapsed += _dt_frame
                if _vroll_ttl > 0.0:
                    _vroll_offset = (_vroll_offset + _vroll_speed * _dt_frame) % window_h
                    _vroll_ttl -= _dt_frame
                    if _vroll_ttl <= 0.0:
                        # Ease offset back to 0 over next ~0.3 s by decaying speed
                        _vroll_speed *= 0.0  # stop immediately; offset snaps on next roll
                        _vroll_offset = 0.0
                elif _vroll_elapsed >= _vroll_next:
                    # Trigger a subtle roll: 3–8 px/s for 0.4–1.2 s
                    _vroll_speed  = float(np.random.uniform(3.0, 8.0))
                    _vroll_ttl    = float(np.random.uniform(0.4, 1.2))
                    _vroll_elapsed = 0.0
                    _vroll_next   = float(np.random.uniform(30.0, 90.0))

            # Degauss: advance and draw chromatic fringe + overlays on top of scene
            if not _crt_force_fast_path and _active_degauss is not None:
                _active_degauss.tick(1.0 / target_fps)
                _active_degauss.draw(window_w, window_h, scene_tex=gpu.post_crt_tex)
                if _active_degauss.done:
                    _active_degauss = None

            if not _crt_force_fast_path:
                # Scanlines (MOD — dims the barrel-distorted image)
                if gpu.crt_scanlines_on:
                    _rlog("scanlines start")
                    scanlines_scroll = (scanlines_scroll + scanlines_speed * (1.0 / target_fps)) % scanlines_h
                    y_offset = int(scanlines_scroll)
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


# ----------------------------------------- #
# POST PROCESSING PASSES (CRT shader effects, bloom, and GPU game-layer animations)
# ------------------------------------------ #


                # GPU game-layer animation passes (embers etc.)
                # Only run when in pure main-game view (no popups, overlays, or
                # menus). fast_main_view is False whenever an inventory, popup,
                # look handler, or any other overlay is active, so embers never
                # composite on top of UI layers.
                if fast_main_view and active_engine is not None and (gpu.gpu_anim_registry or gpu.gpu_anim_nobloom_registry):
                    gpu.ensure_gpu_anim_layer(game_dest_w, game_dest_h)
                    gpu.run_gpu_anim_passes(active_engine, game_dest_w, game_dest_h)


                # Vignette (BLEND — darkens edges)
                if gpu.crt_vignette_on:
                    _rlog("vignette")
                    renderer.copy(vignette_tex, dest=(0, 0, window_w, window_h))
                    renderer.copy(glare_tex, dest=(0, 0, window_w, window_h))
                # Bloom last — ADD glow bleeds over scanlines and vignette
                if gpu.crt_bloom_on:
                    _rlog("gpu_bloom start")
                    gpu.gpu_bloom(gpu.post_crt_tex, window_w, window_h)
                    _rlog("gpu_bloom done")

            _rlog("renderer.present")
            try:
                renderer.present()
            except Exception as e:
                print(f"Error during renderer.present(): {e}")
                raise
            _rlog("present done")

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

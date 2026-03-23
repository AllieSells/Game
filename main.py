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

game_width = 80
game_height = 40
game_view_width = game_width // 2
game_view_height = game_height // 2


game_console = tcod.console.Console(game_view_width, game_view_height, order="F")
ui_console = tcod.console.Console(screen_width, screen_height, order="F")

def render_console_with_transparency(console: tcod.console.Console) -> np.ndarray:
    """Render a console to RGBA pixels and make untouched blank cells transparent."""
    pixels = tileset.render(console).copy()
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

    alpha_mask = np.repeat(np.repeat(cell_alpha.T, tile_h, axis=0), tile_w, axis=1)
    pixels[:, :, 3] = alpha_mask

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
    
    # Draw progress bar background
    for i in range(bar_width):
        console.print(bar_x + i, bar_y, "░", fg=color.parchment_light)
    
    # Draw progress bar fill
    fill_width = int(bar_width * progress)
    for i in range(fill_width):
        console.print(bar_x + i, bar_y, "█", fg=color.gold_accent)
    
    # Progress percentage
    percentage = f"{int(progress * 100)}%"
    console.print(screen_center_x - len(percentage) // 2, bar_y + 2, percentage, fg=color.gold_accent)
    
    # Status text
    console.print(screen_center_x - len(status) // 2, bar_y + 4, status, fg=color.fantasy_text)
    
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
        return {"fullscreen": False, "audio": 50, "graphics": "high"}

# Global reference for settings access
_game_context = None


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

def save_game(handler, filename: str) -> None:
    # If current event handler has active engine then save it
    if isinstance(handler, input_handlers.EventHandler):
        handler.engine.save_as(filename)
        print("Game saved.")    


def main() -> None:
    
    global _game_context, context, game_console, ui_console, cursor, cursor_click
    
    # Use the global context and console that were created during initial loading
    _game_context = context
    
    # Continue with actual loading operations
    show_loading_screen(context, ui_console, 0.75, "Loading game settings...")
    settings = load_settings()
    setting_fullscreen = settings.get("fullscreen", False)
    
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
    cursor_point = Image.open("RP/cursors/cursor_point.png").convert("RGBA")
    pixels_cursor_point = np.array(cursor_point, dtype=np.uint8)
    cursor = tcod.sdl.mouse.new_color_cursor(pixels_cursor_point, (0, 0))   

    cursor_click_img = Image.open("RP/cursors/cursor_click.png").convert("RGBA")
    pixels_cursor_click = np.array(cursor_click_img, dtype=np.uint8)
    cursor_click = tcod.sdl.mouse.new_color_cursor(pixels_cursor_click, (0, 0))

    cursor_bag_img = Image.open("RP/cursors/cursor_bag.png").convert("RGBA")
    pixels_cursor_bag = np.array(cursor_bag_img, dtype=np.uint8)
    cursor_bag = tcod.sdl.mouse.new_color_cursor(pixels_cursor_bag, (0, 0))

    cursor_interact_img =  Image.open("RP/cursors/cursor_open.png").convert("RGBA")
    pixels_cursor_interact = np.array(cursor_interact_img, dtype=np.uint8)
    cursor_interact = tcod.sdl.mouse.new_color_cursor(pixels_cursor_interact, (0, 0))

    cursor_sword_img = Image.open("RP/cursors/cursor_sword.png").convert("RGBA")
    pixels_cursor_sword = np.array(cursor_sword_img, dtype=np.uint8)
    cursor_sword = tcod.sdl.mouse.new_color_cursor(pixels_cursor_sword, (0, 0))
    
    cursor_walk_img = Image.open("RP/cursors/cursor_walk.png").convert("RGBA")
    pixels_cursor_walk = np.array(cursor_walk_img, dtype=np.uint8)
    cursor_walk = tcod.sdl.mouse.new_color_cursor(pixels_cursor_walk, (0, 0))


    # Start the main game loop
    target_fps = 30
    frame_time = 1.0 / target_fps
    last_time = time.time()
    renderer = context.sdl_renderer
    tileset_atlas = tcod.render.SDLTilesetAtlas(renderer, tileset)
    game_console_renderer = tcod.render.SDLConsoleRender(tileset_atlas)
    ui_console_renderer = tcod.render.SDLConsoleRender(tileset_atlas)
    game_tex = None
    ui_tex = None
    cached_overlay_handler = None
    overlay_dirty = True

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

            current_time = time.time()
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
            fast_main_view = (
                main_game_view
                and not getattr(active_engine, "debug", False)
            )
            needs_live_game_frame = main_game_view or game_tex is None

            if main_game_view:
                game_console.clear()
                handler.engine.tick(console=game_console)

            if has_game_view and needs_live_game_frame and not map_overlay_view:
                active_engine.render_game(game_console)

            if fast_main_view:
                cached_overlay_handler = None
                overlay_dirty = True
                renderer.clear()
                game_tex = game_console_renderer.render(game_console)
                renderer.copy(
                    game_tex,
                    dest=(0, 0, game_dest_w, game_dest_h),
                )

                active_engine.render_ui(ui_console)
                hud_tex = ui_console_renderer.render(ui_console)
                renderer.copy(
                    hud_tex,
                    source=(0, hud_source_y, screen_width * tileset.tile_width, hud_source_h),
                    dest=(0, window_h - hud_dest_h, window_w, hud_dest_h),
                )
                renderer.present()
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
                renderer.copy(
                    game_tex,
                    dest=(0, 0, game_dest_w, game_dest_h),
                )

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
                    renderer.copy(
                        hud_tex,
                        source=(0, hud_source_y, screen_width * tileset.tile_width, hud_source_h),
                        dest=(0, window_h - hud_dest_h, window_w, hud_dest_h),
                    )
                renderer.present()
            elif has_game_view:
                renderer.clear()
                if needs_live_game_frame:
                    game_tex = game_console_renderer.render(game_console)
                renderer.copy(
                    game_tex,
                    dest=(0, 0, game_dest_w, game_dest_h),
                )

                if overlay_dirty or cached_overlay_handler is not handler or getattr(active_engine, "debug", False):
                    ui_console.clear()
                    handler.on_render(console=ui_console)
                    ui_pixels = render_console_with_transparency(ui_console)
                    if ui_tex is None:
                        ui_tex = renderer.upload_texture(ui_pixels)
                        ui_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    else:
                        ui_tex.update(ui_pixels)
                    cached_overlay_handler = handler
                    overlay_dirty = False

                renderer.copy(ui_tex, dest=(0, 0, window_w, window_h))
                renderer.present()
            else:
                cached_overlay_handler = None
                overlay_dirty = True
                ui_console.clear()
                handler.on_render(console=ui_console)
                context.present(ui_console)

            try:
                for event in tcod.event.get():
                    context.convert_event(event)
                    if has_game_view and hasattr(event, "position"):
                        ui_tile = get_ui_mouse_tile(tuple(event.position), window_w, window_h)
                        game_screen_tile = get_game_screen_tile(tuple(event.position), window_w, window_h)
                        world_tile = None
                        if active_engine is not None:
                            active_engine.mouse_ui_x, active_engine.mouse_ui_y = ui_tile
                            if ui_tile[1] < hud_top_row:
                                world_tile = active_engine.screen_to_world(
                                    game_screen_tile[0], game_screen_tile[1], game_view_width, game_view_height
                                )

                        event.ui_tile = ui_tile
                        event.world_tile = world_tile
                        event.tile = ui_tile

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

                    if isinstance(event, tcod.event.MouseButtonDown) and event.button == tcod.event.BUTTON_LEFT:
                        _mouse_held = True
                    elif isinstance(event, tcod.event.MouseButtonUp) and event.button == tcod.event.BUTTON_LEFT:
                        _mouse_held = False
                    handler = handler.handle_events(event)
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

print("Starting THE Game...")
import time
# Package with python -m PyInstaller MyGame.spec
initial_time = time.time() # Track total loading


import os
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
except Exception as e:
    print(f"Failed to load custom tileset: {e}, using basic tileset")
    # Create a basic empty tileset as fallback
    tileset = tcod.tileset.Tileset(16, 16)

# Create window immediately
context = tcod.context.new(
    columns=screen_width,
    rows=screen_height,
    tileset=tileset,
    title="THE Game... Loading",
    vsync=False,  # Disable vsync for faster initial loading
)

console = tcod.console.Console(screen_width, screen_height, order="F")

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
show_loading_screen(context, console, 0.05, "Starting...")

# Now load remaining modules
import json

start_time = time.time() # Track total loading


# Continue with module imports
show_loading_screen(context, console, 0.15, "Avoiding glitches...")
import exceptions
str = (f"Loaded exceptions module in {time.time() - start_time:.2f} seconds")
print(str)
with open(get_data_path('logs/log.txt'), 'a') as log_file:
    log_file.write(str + "\n")

start_time = time.time() # Track total loading
show_loading_screen(context, console, 0.30, "Building inputs...")
import input_handlers
str = (f"Loaded input_handlers module in {time.time() - start_time:.2f} seconds")
print(str)
with open(get_data_path('logs/log.txt'), 'a') as log_file:
    log_file.write(str + "\n")

start_time = time.time() # Track total loading
show_loading_screen(context, console, 0.45, "Setting up dungeons...")
import setup_game
str = (f"Loaded setup_game module in {time.time() - start_time:.2f} seconds")
print(str)
with open(get_data_path('logs/log.txt'), 'a') as log_file:
    log_file.write(str + "\n")

start_time = time.time() # Track total loading
show_loading_screen(context, console, 0.60, "Importing bananas...")
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

def save_game(handler: input_handlers.BaseEventHandler, filename: str) -> None:
    # If current event handler has active engine then save it
    if isinstance(handler, input_handlers.EventHandler):
        handler.engine.save_as(filename)
        print("Game saved.")    


def main() -> None:
    
    global _game_context, context, console, cursor, cursor_click
    
    # Use the global context and console that were created during initial loading
    _game_context = context
    
    # Continue with actual loading operations
    show_loading_screen(context, console, 0.75, "Loading game settings...")
    settings = load_settings()
    setting_fullscreen = settings.get("fullscreen", False)
    
    show_loading_screen(context, console, 0.85, "Initializing main menu...")
    handler: input_handlers.BaseEventHandler = setup_game.MainMenu()
   
    
    show_loading_screen(context, console, 0.95, "Finalizing setup...")
    # Update context title
    context.sdl_window.title = "THE Game... idk"

    # Set initial fullscreen state based on settings
    window = context.sdl_window
    if window and setting_fullscreen:
        window.fullscreen = True
        print("DEBUG: Set initial fullscreen mode from settings")

    show_loading_screen(context, console, 1.0, "Ready!")
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
    
    # Start the main game loop
    target_fps = 30
    frame_time = 1.0 / target_fps
    last_time = time.time()

    # Set initial cursor (cursors were already loaded at top of file)
    tcod.sdl.mouse.set_cursor(cursor)
    _mouse_held = False

    try:
        while True:
            hint = getattr(getattr(handler, 'engine', None), 'cursor_hint', None)
            if hint == 'bag':
                tcod.sdl.mouse.set_cursor(cursor_bag)
            elif _mouse_held:
                tcod.sdl.mouse.set_cursor(cursor_click)
            else:
                tcod.sdl.mouse.set_cursor(cursor)

            current_time = time.time()
            
            console.clear()
            handler.on_render(console=console)
            context.present(console)

            if isinstance(handler, input_handlers.EventHandler):
                handler.engine.tick(console=console)

            try:
                for event in tcod.event.get():
                    context.convert_event(event)
                    if isinstance(event, tcod.event.MouseButtonDown) and event.button == tcod.event.BUTTON_LEFT:
                        _mouse_held = True
                    elif isinstance(event, tcod.event.MouseButtonUp) and event.button == tcod.event.BUTTON_LEFT:
                        _mouse_held = False
                    handler = handler.handle_events(event)
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

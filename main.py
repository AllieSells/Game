
# Package with python -m PyInstaller MyGame.spec

print("Starting THE Game...")

import os
import warnings
import sys

# Add dependencies folder to sys.path immediately
sys.path.append(os.path.join(os.path.dirname(__file__), "dependencies"))

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
import time
start_time = time.time() # Track total loading


# Continue with module imports
show_loading_screen(context, console, 0.15, "Avoiding glitches...")
import exceptions
print(f"DEBUG: Loaded exceptions module in {time.time() - start_time:.2f} seconds")

start_time = time.time() # Track total loading
show_loading_screen(context, console, 0.30, "Building inputs...")
import input_handlers
print(f"DEBUG: Loaded input_handlers module in {time.time() - start_time:.2f} seconds")

start_time = time.time() # Track total loading
show_loading_screen(context, console, 0.45, "Setting up dungeons...")
import setup_game
print(f"DEBUG: Loaded setup_game module in {time.time() - start_time:.2f} seconds")

start_time = time.time() # Track total loading
show_loading_screen(context, console, 0.60, "Importing bananas...")
import tcod.sdl.video
import traceback
print(f"DEBUG: Loaded tcod.sdl.video and traceback modules in {time.time() - start_time:.2f} seconds")

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
    start_time = time.time() # Track total loading
    global _game_context, context, console
    
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
    print(f"Finished loading in {time.time() - start_time:.2f} seconds")
    # Brief pause to show completion
    time.sleep(0.3)
    
    # Start the main game loop
    try:
        while True:
            console.clear()
            handler.on_render(console=console)
            context.present(console)

            if isinstance(handler, input_handlers.EventHandler):
                handler.engine.tick(console=console)

            try:
                for event in tcod.event.get():
                    context.convert_event(event)
                    handler = handler.handle_events(event)
            except Exception: # handles game exceptions
                traceback.print_exc() #prints error to stderr
                if isinstance(handler, input_handlers.EventHandler):
                    handler.engine.message_log.add_message(
                        traceback.format_exc(), color.error 
                    )

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

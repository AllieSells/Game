import os
import warnings
import tcod
import tcod.sdl.video
import traceback
import sys
import json

# Add dependencies folder to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), "dependencies"))

import color
import exceptions
import input_handlers
import setup_game


def get_data_path(filename):
    """Get the correct path for data files in both development and PyInstaller."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller executable
        base_path = sys._MEIPASS
    else:
        # Running in development
        base_path = os.path.dirname(__file__)
    return os.path.join(base_path, filename)

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
if not os.environ.get("GAME_SHOW_WARNINGS"):
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning)




def save_game(handler: input_handlers.BaseEventHandler, filename: str) -> None:
    # If current event handler has active engine then save it
    if isinstance(handler, input_handlers.EventHandler):
        handler.engine.save_as(filename)
        print("Game saved.")    


def main() -> None:
    screen_width = 80 # was 80
    screen_height = 50  # was 50

    # Load settings to determine initial fullscreen state
    settings = load_settings()
    initial_fullscreen = settings.get("fullscreen", False)
    
    tileset = tcod.tileset.load_tilesheet(  
        get_data_path("RP/AllieClassic.png"), 16, 16, tcod.tileset.CHARMAP_CP437
    )

    handler: input_handlers.BaseEventHandler = setup_game.MainMenu()
    
    # Set SDL window flags based on settings
    if initial_fullscreen:
        sdl_flags = tcod.context.SDL_WINDOW_FULLSCREEN
    else:
        # Allow window resizing in windowed mode
        sdl_flags = tcod.context.SDL_WINDOW_RESIZABLE

    with tcod.context.new_terminal(
        screen_width,
        screen_height,
        tileset=tileset,
        title="THE Game... idk",
        vsync=True,
        sdl_window_flags=sdl_flags,
    ) as context:
        global _game_context
        _game_context = context  # Store for settings access
        
        console = tcod.console.Console(screen_width, screen_height, order="F")
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
            os.makedirs("SAVEGAME", exist_ok=True)
            save_game(handler, "SAVEGAME/savegame.sav")
            raise
        except BaseException: # Save on any other unexpected exception
            os.makedirs("SAVEGAME", exist_ok=True)
            save_game(handler, "SAVEGAME/savegame.sav")
            raise


main()



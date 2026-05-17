"""Handle the loading and initialization of game sessions."""
from __future__ import annotations

import copy
import lzma
import pickle
import traceback
from typing import Optional

import tcod

import color
from engine import Engine
import entity_factories
from game_map import GameWorld
import input_handlers
from render_functions import MenuRenderer
import sounds
import random
import hashlib
import sys
import os
import time


def get_data_path(filename):
    """Get the correct path for data files in both development and PyInstaller."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller executable
        base_path = sys._MEIPASS
    else:
        # Running in development
        base_path = os.path.dirname(__file__)
    return os.path.join(base_path, filename)


def get_save_path(filename=""):
    """Get the correct path for save files that need to be writable."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller executable - store saves next to the .exe
        base_path = os.path.dirname(sys.executable)
    else:
        # Running in development - use current directory
        base_path = os.path.dirname(__file__)
    
    save_dir = os.path.join(base_path, "SAVEGAME")
    
    # Create save directory if it doesn't exist
    os.makedirs(save_dir, exist_ok=True)
    
    if filename:
        return os.path.join(save_dir, filename)
    else:
        return save_dir


# Simple animated background
class SimpleAnimatedBackground:
    def __init__(self, frame_pattern="RP/background/frame_{:03d}.png", frame_count=240, fps=20):
        self.frames = []
        self.current_frame = 0
        self.frame_time = 1.0 / fps
        self.last_update = time.time()
        
        # Load frames
        for i in range(frame_count):
            frame_path = frame_pattern.format(i)
            try:
                frame = tcod.image.load(get_data_path(frame_path))[:, :, :3]
                self.frames.append(frame)
            except Exception:
                # Try alternative delay pattern
                alt_path = frame_pattern.replace("0.03s", "0.06s").format(i)
                try:
                    frame = tcod.image.load(get_data_path(alt_path))[:, :, :3]
                    self.frames.append(frame)
                except Exception:
                    break
        
        with open(get_data_path('logs/log.txt'), 'a') as log_file:
            log_file.write(f"Loaded {len(self.frames)} frames for animated background.\n")
        
        # Fallback to static image
        if not self.frames:
            try:
                frame = tcod.image.load(get_data_path("image.png"))[:, :, :3]
                self.frames.append(frame)
                with open(get_data_path('logs/log.txt'), 'a') as log_file:
                    log_file.write("Using static background.\n")
            except Exception:
                with open(get_data_path('logs/log.txt'), 'a') as log_file:
                    log_file.write("No background found.\n")
    
    def get_current_frame(self):
        if not self.frames:
            return None
        
        # Update frame
        current_time = time.time()
        if len(self.frames) > 1 and current_time - self.last_update >= self.frame_time:
            self.current_frame = (self.current_frame + 1) % len(self.frames)
            self.last_update = current_time
        
        return self.frames[self.current_frame]

# Create animated background
animated_bg = SimpleAnimatedBackground()

# For compatibility with existing code
def get_background_image():
    return animated_bg.get_current_frame()

background_image = get_background_image()

# Global variable to store the current seed for display
_current_seed = None

def _convert_seed(seed_string: str) -> int:
    """Convert a string seed to an integer using hash."""
    return int(hashlib.md5(seed_string.encode()).hexdigest()[:8], 16)

def _set_global_seed(game_seed: Optional[int] = None, seed_string: Optional[str] = None) -> int:
    """Set the global random seed and return the seed used."""
    global _current_seed
    
    
    if seed_string:
        _current_seed = _convert_seed(seed_string)
    elif game_seed is not None:
        _current_seed = game_seed
    else:
        _current_seed = random.randint(0, 2**31 - 1)
    
    random.seed(_current_seed)
    return _current_seed

def get_current_seed() -> Optional[int]:
    """Get the current seed for display purposes."""
    return _current_seed


    
def new_game(game_seed: Optional[int] = None, seed_string: Optional[str] = None) -> Engine:
    """Return a brand new game session as an Engine instance."""
    map_width = 80    # dungeon map width
    map_height = 40   # dungeon map height

    room_max_size = 10
    room_min_size = 6
    max_rooms = 30

    # Set global seed once for the entire generation
    _set_global_seed(game_seed=game_seed, seed_string=seed_string)

    import sprite_manager as _sm
    _sm.reset_sprite_cache()

    player = copy.deepcopy(entity_factories.player)
    player.char = None
    player.level.current_xp = 0

    engine = Engine(player=player)
    engine.debug_log(f"Starting new game with seed: {get_current_seed()}", handler=type(engine).__name__, event="game_start")
    engine.debug_log(f"Engine: {engine}", handler=type(engine).__name__, event="game_start")
    
    # Set world generation flag to suppress equipment sounds
    engine.is_generating_world = True

    engine.game_world = GameWorld(
        engine=engine,
        max_rooms=max_rooms,
        room_min_size=room_min_size,
        room_max_size=room_max_size,
        map_width=map_width,
        map_height=map_height,
    )

    # Global variance generation
    import random  # Keep local for compatibility
    for x in range(random.randint(5, 10)):
        fungus = entity_factories.get_random_fungus()
        engine.game_world.fungi.append(fungus)
        engine.debug_log(f"Generated fungus: {fungus.name}", handler=type(engine).__name__, event="world_gen")
    
    # Generate world noise 
    engine.game_world.generate_world()
    
    from pathlib import Path
    cache = Path("portrait_cache")
    if not cache.exists():
        cache.mkdir()
    for item in cache.iterdir():
        if item.is_file():
            try:
                item.unlink()
            except Exception:
                print("ERROR: Failed to clear portrait cache:", item)

    # Enter the tutorial floor directly, pushing the overworld onto the up_stack.
    # The player starts inside the first dungeon; the locked door is the only exit.
    tut_loc = getattr(engine.game_map, 'tutorial_dungeon_entrance', None)
    if tut_loc is not None:
        from procgen import generate_first_floor
        overworld_map = engine.game_map
        tut_map = generate_first_floor(map_width, map_height, engine)
        # Cache the tutorial map so re-entry (after ascending) reuses it
        player_start = getattr(tut_map, 'player_start', (42, 24))
        engine.game_world.dungeon_cache[tut_loc] = (tut_map, player_start)
        engine.game_world.up_stack.append((overworld_map, tut_loc, 0))
        engine.game_world.current_floor = 1
        engine.game_map = tut_map

    engine.update_fov()
    
    # Clear world generation flag after generation is complete
    engine.is_generating_world = False

    engine.message_log.add_message("Press ? For Controls")
    engine.message_log.add_message(
        f"Seed: {get_current_seed()}", color.welcome_text
    )
    engine.show_minimap = 1  # Show controls by default — player spawns inside dungeon
    return engine

def tutorial_game(game_seed = None, seed_string = None) -> Engine:
    """Return a new game session with a custom tutorial map."""
    """Return a brand new game session as an Engine instance."""
    map_width = 80
    map_height = 40

    room_max_size = 10
    room_min_size = 6
    max_rooms = 30

    # Set global seed once for the entire generation
    _set_global_seed(game_seed=game_seed, seed_string=seed_string)

    import sprite_manager as _sm
    _sm.reset_sprite_cache()
    entity_factories.refresh_scroll_prototype_sprites()

    player = copy.deepcopy(entity_factories.player)
    player.level.current_xp = 0

    engine = Engine(player=player)
    engine.debug_log(f"Starting new game with seed: {get_current_seed()}", handler=type(engine).__name__, event="game_start")
    engine.debug_log(f"Engine: {engine}", handler=type(engine).__name__, event="game_start")
    
    # Set world generation flag to suppress equipment sounds
    engine.is_generating_world = True

    engine.game_world = GameWorld(
        engine=engine,
        max_rooms=max_rooms,
        room_min_size=room_min_size,
        room_max_size=room_max_size,
        map_width=map_width,
        map_height=map_height,
    )

    # Global variance generation
    import random  # Keep local for compatibility
    for x in range(random.randint(5, 10)):
        fungus = entity_factories.get_random_fungus()
        engine.game_world.fungi.append(fungus)
        engine.debug_log(f"Generated fungus: {fungus.name}", handler=type(engine).__name__, event="world_gen")
    
    # Generate world noise 
    engine.game_world.generate_tutorial()
    engine.update_fov()
    
    # Clear world generation flag after generation is complete
    engine.is_generating_world = False

    engine.message_log.add_message("Press ? For Controls")
    engine.message_log.add_message(
        f"Seed: {get_current_seed()}", color.welcome_text
    )
    engine.message_log.add_message(
        "You enter the dungeon. Haunted figures move in the dark...", color.welcome_text
    )

    return engine



def new_debug_game(game_seed: Optional[int] = None, seed_string: Optional[str] = None) -> Engine:
    """Return a debug game session using overworld chunk generation."""
    map_width = 80
    map_height = 40
    
    # Set global seed once at the start
    _set_global_seed(game_seed=game_seed, seed_string=seed_string)

    import sprite_manager as _sm
    _sm.reset_sprite_cache()
    entity_factories.refresh_scroll_prototype_sprites()
    
    player = copy.deepcopy(entity_factories.player)
    
    engine = Engine(player=player)
    
    # Set world generation flag to suppress equipment sounds
    engine.is_generating_world = True
    
    # Import overworld chunk generator
    from procgen import generate_overworld_chunk
    # Generate overworld chunk for debug (this creates the GameMap with player placed)
    game_map = generate_overworld_chunk(map_width, map_height, engine)
    
    # Change map type to debug for proper FOV behavior
    game_map.type = "debug"
    game_map.name = "Debug Level"
    
    # Add some random walls for testing FOV and pathfinding
    import tile_types
    import random
    
    # Place random walls scattered across the map
    num_walls = random.randint(15, 25)
    for _ in range(num_walls):
        wall_x = random.randint(5, map_width - 6)
        wall_y = random.randint(5, map_height - 6)
        
        # Don't place walls too close to player spawn (center)
        center_x, center_y = map_width // 2, map_height // 2
        if abs(wall_x - center_x) < 3 and abs(wall_y - center_y) < 3:
            continue
            
        # Place a small wall cluster (1x1 to 3x3)
        cluster_size = random.randint(1, 3)
        for dx in range(cluster_size):
            for dy in range(cluster_size):
                if wall_x + dx < map_width and wall_y + dy < map_height:
                    if random.random() < 0.7:  # 70% chance for each wall tile in cluster
                        game_map.tiles[wall_x + dx, wall_y + dy] = tile_types.wall
    
    # Make the entire map fully lit
    for x in range(map_width):
        for y in range(map_height):
            current_tile = game_map.tiles[x, y]
            # Create new tile with lit=True while preserving other properties
            new_tile = (
                True,  # lit
                current_tile[1],  # name  
                current_tile[2],  # walkable
                current_tile[3],  # transparent
                current_tile[4],  # dark
                current_tile[5],  # light
                current_tile[6],  # interactable
            )
            game_map.tiles[x, y] = new_tile
    
    # Simple GameWorld for debug
    engine.game_world = GameWorld(
        engine=engine,
        max_rooms=0,
        room_min_size=0,
        room_max_size=0,
        map_width=map_width,
        map_height=map_height,
    )
    engine.game_world.current_floor = 0
    engine.game_map = game_map
    
    engine.update_fov()
    
    # Import and set turn manager
    from turn_manager import TurnManager
    engine.turn_manager = TurnManager(engine)
    
    from message_log import MessageLog
    engine.message_log = MessageLog()
    engine.message_log.add_message("Welcome to Debug Level!", color.welcome_text)
    engine.message_log.add_message("Natural grass distribution test area.", color.gray)
    
    # Clear world generation flag after debug setup is complete
    engine.is_generating_world = False
    
    return engine

def load_game(filename: str) -> Engine:
    """Load engine instance from file."""
    # Use get_save_path to get the correct save directory
    if not filename.startswith("SAVEGAME"):
        filepath = get_save_path(filename)
    else:
        # Handle legacy format "SAVEGAME/filename.sav"
        filename = filename.replace("SAVEGAME/", "")
        filepath = get_save_path(filename)
    
    with open(filepath, "rb") as f:
        engine = pickle.loads(lzma.decompress(f.read()))
    assert isinstance(engine, Engine)
    # Clear any pending animations that may have been serialized or leftover
    try:
        if hasattr(engine, "animation_queue"):
            try:
                engine.animation_queue.clear()
            except Exception:
                try:
                    from collections import deque
                    engine.animation_queue = deque()
                except Exception:
                    pass
    except Exception:
        pass

    import sprite_manager
    sprite_manager.reset_sprite_cache()
    entity_factories.refresh_scroll_prototype_sprites()
    _rehydrate_loaded_sprite_state(engine)
    return engine


def _iter_engine_maps(engine: Engine):
    """Yield every GameMap reachable from the loaded engine."""
    seen = set()

    def _yield_map(game_map):
        if game_map is None:
            return
        obj_id = id(game_map)
        if obj_id in seen:
            return
        seen.add(obj_id)
        yield game_map

    yield from _yield_map(getattr(engine, "game_map", None))

    game_world = getattr(engine, "game_world", None)
    if game_world is None:
        return

    for stack_name in ("up_stack", "down_stack"):
        for entry in list(getattr(game_world, stack_name, []) or []):
            if isinstance(entry, tuple) and entry:
                yield from _yield_map(entry[0])

    for cached in (getattr(game_world, "dungeon_cache", {}) or {}).values():
        if isinstance(cached, tuple) and cached:
            yield from _yield_map(cached[0])


def _entity_needs_portrait_rebuild(entity) -> bool:
    """Return True if this entity has portrait-driven appearance fields."""
    know = getattr(entity, "knowledge", None)
    if not isinstance(know, dict):
        return False
    portrait_keys = {
        "gender",
        "skin_tone",
        "hair_color",
        "hair_style",
        "facial_hair",
        "head",
        "body",
        "legs",
        "feet",
    }
    return any(key in know for key in portrait_keys)


def _rehydrate_loaded_sprite_state(engine: Engine) -> None:
    """Rebuild runtime sprite composites after loading a save.

    Save files serialize codepoints in map/entity fields, but sprite_manager's
    runtime tileset cache is process-local and is not serialized with saves.
    Rebuild known dynamic composites (portraits/equipment/liquids/dungeon water)
    so codepoints in loaded maps point to valid tileset entries.
    """
    try:
        import sprite_manager as _sm
    except Exception:
        return

    rebuilt_entities = set()

    for game_map in _iter_engine_maps(engine):
        try:
            liquid_system = getattr(game_map, "liquid_system", None)
            if liquid_system is not None:
                # Defensive relink: old saves may deserialize with stale backrefs.
                liquid_system.game_map = game_map
        except Exception:
            pass

        for entity in list(getattr(game_map, "entities", []) or []):
            ent_id = id(entity)
            if ent_id in rebuilt_entities:
                continue
            rebuilt_entities.add(ent_id)

            try:
                if _entity_needs_portrait_rebuild(entity):
                    _sm.compose_portrait(entity)
            except Exception:
                pass

            if hasattr(entity, "base_char"):
                try:
                    if hasattr(entity, "equipment"):
                        _sm.refresh_actor_sprite(entity)
                    else:
                        entity.char = entity.base_char
                except Exception:
                    try:
                        entity.char = entity.base_char
                    except Exception:
                        pass

            try:
                entity_factories.refresh_scroll_item_sprite(entity)
            except Exception:
                pass

        # Regenerate liquid composites from serialized coating data.
        try:
            liquid_system = getattr(game_map, "liquid_system", None)
            if liquid_system is not None:
                liquid_system.refresh_all_graphics()
        except Exception:
            pass

        # Rebuild cached dungeon-water composites for this process/tileset.
        try:
            if getattr(game_map, "type", None) == "dungeon":
                _sm.build_dungeon_water_anim(game_map)
                game_map.dungeon_water_current = {}
        except Exception:
            pass

    # Final defensive refresh for the player object.
    player = getattr(engine, "player", None)
    if player is not None:
        try:
            if _entity_needs_portrait_rebuild(player):
                _sm.compose_portrait(player)
        except Exception:
            pass
        try:
            if hasattr(player, "equipment"):
                _sm.refresh_actor_sprite(player)
            elif hasattr(player, "base_char"):
                player.char = player.base_char
        except Exception:
            pass


def get_available_saves():
    """Get list of available save files in SAVEGAME directory."""
    save_files = []
    save_dir = get_save_path()  # Use get_save_path instead of get_data_path
    
    try:
        if os.path.exists(save_dir):
            for filename in os.listdir(save_dir):
                if filename.endswith('.sav'):
                    filepath = os.path.join(save_dir, filename)
                    # Get file modification time for sorting
                    try:
                        mtime = os.path.getmtime(filepath)
                        # Remove .sav extension for display
                        display_name = filename[:-4]
                        save_files.append((display_name, filename, mtime))
                    except OSError:
                        continue
    except OSError:
        pass
    
    # Sort by modification time (newest first)
    save_files.sort(key=lambda x: x[2], reverse=True)
    return save_files 

# Removed SeedInputScreen class - now using TextInputHandler from input_handlers


class LoadingScreen(input_handlers.BaseEventHandler):
    """Display a loading screen while generating the world."""
    
    def __init__(self, parent_menu, game_seed=None, seed_string=None):
        self.parent_menu = parent_menu
        self.game_seed = game_seed
        self.seed_string = seed_string
        self.generation_steps = [
            "Initializing world...",
            "Generating rooms...",
            "Placing loot...",
            "Adding campfires...",
            "Spawning entities...",
            "Feeding critters...",
            "Freezing graphics temporarily...",
            "Finalizing world...",
            "World generation complete!"
        ]
        self.current_step = 0
        self.dots = 0
        self.max_dots = 3
        self.frame_count = 0
        self.engine = None
        self.generation_started = False
        self.game_load = False
        self.completion_delay = 0  # Frames to show completion before transitioning
    
    def cleanup_resources(self):
        """Release any resources used during the loading screen."""
        animated_bg.release_resources()
        print("Loading screen resources cleaned up.")

    def on_render(self, console: tcod.console.Console) -> None:
        try:
            """Render the loading screen with parchment styling."""
            # Use animated background
            current_bg = animated_bg.get_current_frame()
            if current_bg is not None:
                console.draw_semigraphics(current_bg, 0, 0)
            
            # Calculate window dimensions and position
            window_width = 60
            window_height = 20
            x = (console.width - window_width) // 2
            y = (console.height - window_height) // 2
            
            # Draw parchment background and ornate border
            MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
            MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "World Generation")
            
            # Animate dots
            self.frame_count += 1
            if self.frame_count % 20 == 0:  # Change dots every 20 frames
                self.dots = (self.dots + 1) % (self.max_dots + 1)
            
            # Display current step
            if self.current_step < len(self.generation_steps):
                current_text = self.generation_steps[self.current_step]
                if not self.game_load:
                    current_text += "." * self.dots + " " * (self.max_dots - self.dots)
            else:
                current_text = "World generated!"
            
            # Display loading message
            console.print(
                x + (window_width // 2),
                y + 3,
                current_text,
                fg=color.gold_accent,
                bg=color.parchment_bg,
                alignment=tcod.CENTER,
            )
            
            # Show ornate progress bar
            bar_width = window_width - 8  # Leave margin inside window
            bar_x = x + 4
            bar_y = y + 5
            
            # Calculate progress percentage
            if self.game_load:
                progress = 1.0
            else:
                progress = self.current_step / len(self.generation_steps)
            
            # Draw ornate progress bar frame with fantasy styling
            console.print(bar_x, bar_y, "╟", fg=color.bronze_border, bg=color.parchment_bg)
            console.print(bar_x + bar_width - 1, bar_y, "╢", fg=color.bronze_border, bg=color.parchment_bg)
            
            # Fill the bar interior
            fill_width = int((bar_width - 2) * progress)
            for i in range(bar_width - 2):
                if i < fill_width:
                    if self.game_load:
                        char = "█"
                        fg = color.gold_accent
                    else:
                        char = "▓"
                        fg = color.bronze_text
                else:
                    char = "░"
                    fg = color.dark_gray
                console.print(bar_x + 1 + i, bar_y, char, fg=fg, bg=color.parchment_bg)
            
            # Show percentage with ornate styling
            percentage = int(progress * 100)
            console.print(
                x + (window_width // 2),
                bar_y + 2,
                f"◦ {percentage}% Complete ◦",
                fg=color.bronze_text,
                bg=color.parchment_bg,
                alignment=tcod.CENTER,
            )
            
            # Show completed steps in a fancy list
            step_y = y + 9
            steps_shown = 0
            for i, step in enumerate(self.generation_steps[:self.current_step]):
                if step_y + steps_shown < y + window_height - 3:  # Make sure we don't go off screen
                    # Use ornate checkmark and fantasy styling
                    step_text = f"✦ {step.replace('...', '')}"
                    console.print(
                        x + 3,
                        step_y + steps_shown,
                        step_text[:window_width - 6],  # Truncate if too long
                        fg=color.fantasy_text,
                        bg=color.parchment_bg,
                    )
                    steps_shown += 1
            
            # Show instructions
            if not self.game_load:
                instructions_y = y + window_height - 2
                console.print(
                    x + (window_width // 2),
                    instructions_y,
                    "[Esc] Cancel",
                    fg=color.light_gray,
                    bg=color.parchment_bg,
                    alignment=tcod.CENTER,
                )
            else:
                instructions_y = y + window_height - 2
                console.print(
                    x + (window_width // 2),
                    instructions_y,
                    "[Any Key] Continue",
                    fg=color.gold_accent,
                    bg=color.parchment_bg,
                    alignment=tcod.CENTER,
                )
            
            # If generation hasn't started, start it
            if not self.generation_started:
                self.generation_started = True
                self.start_generation()

            print("done!")

        except Exception as e:
            traceback.print_exc()
            console.print(
                0,
                0,
                f"Error during loading: {e}",
                fg=color.error,
                bg=color.black,
            )
        
    def start_generation(self):
        """Start the world generation process with step tracking."""
        import threading
        self.generation_thread = threading.Thread(target=self.generate_world_with_steps)
        self.generation_thread.start()
    
    def generate_world_with_steps(self):
        """Generate the world in a background thread."""
        import sprite_manager as _sm
        _sm.set_deferred_mode(True)
        try:
            self.current_step = 0
            self.engine = new_game(
                game_seed=self.game_seed,
                seed_string=self.seed_string,
            )
            self.current_step = len(self.generation_steps) - 1
            self.game_load = True
        except Exception:
            self.current_step = len(self.generation_steps)
            self.game_load = True
            self.engine = None
            traceback.print_exc()
        finally:
            _sm.set_deferred_mode(False)

    
    def handle_events(self, event: tcod.event.Event) -> input_handlers.BaseEventHandler:
        """Handle events during loading.

        The CRT screen-off/on animation and the transition to MainGameEventHandler
        are driven by the main render loop (main.py) once game_load is True.
        handle_events only needs to handle ESC-to-cancel; everything else is a no-op
        so the main loop stays in control of the timing.
        """
        # Allow ESC to cancel and return to main menu at any time
        if isinstance(event, tcod.event.KeyDown) and event.sym == tcod.event.K_ESCAPE:
            return self.parent_menu

        # Once generation is complete the main loop will play the screen-on animation
        # and then call handle_events with a synthetic event to trigger the transition.
        if self.game_load:
            if self.engine is None:
                # Generation failed — return to main menu
                return self.parent_menu
            if getattr(event, '_crt_transition', False):
                from chargen_ui import CharacterCreationHandler
                return CharacterCreationHandler(self.engine)

        return self


class SaveGameMenu(input_handlers.BaseEventHandler):
    """Handle the save game selection menu."""
    
    def __init__(self, parent_menu):
        super().__init__()
        self.parent_menu = parent_menu
        self.save_files = get_available_saves()
        self.selected_option = 0
        self.hovered_option = -1

        # Cached layout for mouse interaction (updated each render).
        self._window_x = 0
        self._window_y = 0
        self._window_width = 0
        self._window_height = 0
        self._menu_start_y = 0
        self._visible_saves = 0
        
        # If no saves found, show message
        if not self.save_files:
            self.no_saves = True
        else:
            self.no_saves = False
    
    def refresh_saves(self):
        """Refresh the save file list."""
        self.save_files = get_available_saves()
        if not self.save_files:
            self.no_saves = True
            self.selected_option = 0
            self.hovered_option = -1
        else:
            self.no_saves = False
            # Keep selection valid
            if self.selected_option >= len(self.save_files):
                self.selected_option = max(0, len(self.save_files) - 1)
            if self.hovered_option >= len(self.save_files):
                self.hovered_option = -1
    
    def delete_save(self, save_index):
        """Delete a save file by index."""
        if 0 <= save_index < len(self.save_files):
            display_name, filename, mtime = self.save_files[save_index]
            filepath = get_save_path(filename)  # Use get_save_path instead of get_data_path
            
            try:
                os.remove(filepath)
                return True, f"Deleted '{display_name}' successfully."
            except OSError as e:
                return False, f"Failed to delete '{display_name}': {e}"
        return False, "Invalid save selection."
    
    def on_render(self, console: tcod.console.Console) -> None:
        """Render the save game selection menu."""
        current_bg = animated_bg.get_current_frame()
        if current_bg is not None:
            console.draw_semigraphics(current_bg, 0, 0)
        
        # Calculate window dimensions
        window_width = 60
        window_height = min(20, len(self.save_files) + 8) if not self.no_saves else 12
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2

        # Cache current layout for mouse hit-testing.
        self._window_x = x
        self._window_y = y
        self._window_width = window_width
        self._window_height = window_height
        
        # Draw parchment background and border
        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "Load Saved Game")
        
        if self.no_saves:
            # Show no saves message
            console.print(
                x + (window_width // 2),
                y + 5,
                "No saved games found.",
                fg=color.fantasy_text,
                bg=color.parchment_bg,
                alignment=tcod.CENTER,
            )
            console.print(
                x + (window_width // 2),
                y + 7,
                "[Esc] Back to Main Menu",
                fg=color.light_gray,
                bg=color.parchment_bg,
                alignment=tcod.CENTER,
            )
        else:
            # Show save file list
            menu_start_y = y + 3
            visible_saves = min(10, len(self.save_files))  # Show max 10 saves
            self._menu_start_y = menu_start_y
            self._visible_saves = visible_saves
            
            for i in range(visible_saves):
                save_index = i
                if save_index >= len(self.save_files):
                    break
                    
                display_name, filename, mtime = self.save_files[save_index]
                is_selected = save_index == self.selected_option
                is_hovered = save_index == self.hovered_option and not is_selected
                
                bg_color = (80, 60, 30) if is_selected else (60, 45, 22) if is_hovered else (45, 35, 25)
                fg_color = color.gold_accent if is_selected else color.white if is_hovered else color.fantasy_text
                marker = "> " if is_selected else "~ " if is_hovered else "  "
                marker2 = " <" if is_selected else " ~" if is_hovered else "  "
                
                option_y = menu_start_y + i
                
                # Format save info with date
                date_str = time.strftime("%m/%d/%y %H:%M", time.localtime(mtime))
                save_text = f"{display_name} ({date_str})"
                
                # Truncate if too long
                max_text_len = window_width - 8
                if len(save_text) > max_text_len:
                    save_text = save_text[:max_text_len-3] + "..."
                
                full_text = f"{marker}{save_text}{marker2}"
                
                # Draw background for the entire line
                for dx in range(window_width - 2):
                    console.print(x + 1 + dx, option_y, " ", bg=bg_color)
                
                console.print(
                    x + 2,
                    option_y,
                    full_text,
                    fg=fg_color,
                    bg=bg_color,
                )
            
            # Show instructions
            instructions_y = y + window_height - 2
            console.print(
                x + (window_width // 2),
                instructions_y,
                "[LMB] Load  [RMB] Context  [↑↓] Navigate  [Del] Delete  [Esc] Back",
                fg=color.light_gray,
                bg=color.parchment_bg,
                alignment=tcod.CENTER,
            )

    def _load_selected_save(self) -> Optional[input_handlers.BaseEventHandler]:
        """Load the currently selected save file."""
        if not (0 <= self.selected_option < len(self.save_files)):
            return None

        display_name, filename, _mtime = self.save_files[self.selected_option]

        try:
            engine = load_game(filename)  # Just pass filename, load_game handles the path

            # Stop menu ambience when leaving menu
            sounds.stop_menu_ambience()
            sounds.stop_all_music()

            return input_handlers.CRTTransition(
                input_handlers.MainGameEventHandler(engine),
                post_fn=sounds.start_dungeon_music
            )
        except FileNotFoundError:
            return input_handlers.PopupMessage(self, f"Save file '{display_name}' not found.")
        except Exception as exc:
            traceback.print_exc()
            return input_handlers.PopupMessage(self, f"Failed to load save:\n{exc}")

    def _open_delete_confirmation(self, save_index: int) -> Optional[input_handlers.BaseEventHandler]:
        """Open delete confirmation dialog for a selected save index."""
        if not (0 <= save_index < len(self.save_files)):
            return None

        display_name, _filename, _mtime = self.save_files[save_index]

        def confirm_delete(confirmed):
            if confirmed:
                self.delete_save(save_index)
                self.refresh_saves()
                return self
            return self

        return ConfirmationDialog(
            parent_handler=self,
            message=f"Delete save '{display_name}'?\n\nThis cannot be undone!",
            callback=confirm_delete
        )

    def _row_to_save_index(self, mouse_y: int) -> int:
        """Convert a mouse y-position to a visible save row index, or -1."""
        if self.no_saves:
            return -1
        if mouse_y < self._menu_start_y or mouse_y >= self._menu_start_y + self._visible_saves:
            return -1
        idx = mouse_y - self._menu_start_y
        return idx if 0 <= idx < len(self.save_files) else -1

    def _mouse_over_list(self, mouse_x: int, mouse_y: int) -> bool:
        """Return True if mouse is inside the save list clickable region."""
        if self.no_saves:
            return False
        left = self._window_x + 1
        right = self._window_x + self._window_width - 2
        top = self._menu_start_y
        bottom = self._menu_start_y + self._visible_saves - 1
        return left <= mouse_x <= right and top <= mouse_y <= bottom

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> Optional[input_handlers.BaseEventHandler]:
        """Allow mouse hover to change save selection."""
        if self.no_saves:
            self.hovered_option = -1
            return None

        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        if self._mouse_over_list(mouse_x, mouse_y):
            hovered = self._row_to_save_index(mouse_y)
            if hovered != self.hovered_option:
                sounds.play_ui_move_sound()
            self.hovered_option = hovered
            if hovered >= 0:
                self.selected_option = hovered
        else:
            self.hovered_option = -1

        return None

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[input_handlers.BaseEventHandler]:
        """Mouse actions: left-click loads, right-click opens context menu."""
        if self.no_saves:
            if event.button == tcod.event.MouseButton.LEFT:
                return self.parent_menu
            return None

        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        if not self._mouse_over_list(mouse_x, mouse_y):
            return None

        clicked_index = self._row_to_save_index(mouse_y)
        if clicked_index < 0:
            return None

        self.selected_option = clicked_index
        if event.button == tcod.event.MouseButton.LEFT:
            return self._load_selected_save()
        if event.button == tcod.event.MouseButton.RIGHT:
            return SaveFileContextMenu(self, clicked_index, mouse_x, mouse_y)
        return None
    
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[input_handlers.BaseEventHandler]:
        """Handle key input for save selection."""
        if event.sym == tcod.event.K_ESCAPE:
            # Return to main menu (music should already be playing)
            return self.parent_menu
        
        if self.no_saves:
            return None
        
        if event.sym == tcod.event.KeySym.UP:
            sounds.play_ui_move_sound()
            self.selected_option = (self.selected_option - 1) % len(self.save_files)
            return None
        elif event.sym == tcod.event.KeySym.DOWN:
            sounds.play_ui_move_sound()
            self.selected_option = (self.selected_option + 1) % len(self.save_files)
            return None
        elif event.sym in (tcod.event.KeySym.RETURN, tcod.event.KeySym.KP_ENTER, tcod.event.KeySym.SPACE):
            return self._load_selected_save()
        elif event.sym == tcod.event.KeySym.DELETE:
            return self._open_delete_confirmation(self.selected_option)
        
        return None


class SaveFileContextMenu(input_handlers.BaseEventHandler):
    """Right-click context menu for save rows (load/delete/cancel)."""

    def __init__(self, parent_menu: SaveGameMenu, save_index: int, mouse_x: int, mouse_y: int):
        super().__init__()
        self.parent_menu = parent_menu
        self.save_index = save_index
        self.options = [
            ("Load Save", "load"),
            ("Delete Save", "delete"),
            ("Cancel", "cancel"),
        ]
        self.selected_option = 0
        self.hovered_option = -1

        # Position menu near cursor, clamped in on_render.
        self.anchor_x = mouse_x
        self.anchor_y = mouse_y
        self.menu_x = 0
        self.menu_y = 0
        self.menu_w = 18
        self.menu_h = len(self.options) + 3

    def _run_selected(self) -> Optional[input_handlers.BaseEventHandler]:
        if not (0 <= self.selected_option < len(self.options)):
            return self.parent_menu

        _label, action = self.options[self.selected_option]
        if action == "cancel":
            return self.parent_menu

        self.parent_menu.selected_option = self.save_index
        if action == "load":
            return self.parent_menu._load_selected_save()
        if action == "delete":
            return self.parent_menu._open_delete_confirmation(self.save_index)
        return self.parent_menu

    def on_render(self, console: tcod.console.Console) -> None:
        if hasattr(self.parent_menu, 'on_render'):
            self.parent_menu.on_render(console)

        max_label_len = max(len(label) for label, _ in self.options)
        self.menu_w = max(18, max_label_len + 6)
        self.menu_h = len(self.options) + 3

        self.menu_x = max(0, min(self.anchor_x, console.width - self.menu_w))
        self.menu_y = max(0, min(self.anchor_y, console.height - self.menu_h))

        MenuRenderer.draw_parchment_background(console, self.menu_x, self.menu_y, self.menu_w, self.menu_h)
        MenuRenderer.draw_ornate_border(console, self.menu_x, self.menu_y, self.menu_w, self.menu_h, "Save")

        for i, (label, action) in enumerate(self.options):
            row_y = self.menu_y + 1 + i
            is_selected = i == self.selected_option
            is_hovered = i == self.hovered_option and not is_selected
            bg_color = (80, 60, 30) if is_selected else (60, 45, 22) if is_hovered else (45, 35, 25)
            if action == "delete" and (is_selected or is_hovered):
                fg_color = color.red
            else:
                fg_color = color.gold_accent if is_selected else color.white if is_hovered else color.fantasy_text
            marker = "> " if is_selected else "~ " if is_hovered else "  "

            for dx in range(self.menu_w - 2):
                console.print(self.menu_x + 1 + dx, row_y, " ", bg=bg_color)
            console.print(
                self.menu_x + 2,
                row_y,
                f"{marker}{label}",
                fg=fg_color,
                bg=bg_color,
            )

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> Optional[input_handlers.BaseEventHandler]:
        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        within = (
            self.menu_x + 1 <= mouse_x <= self.menu_x + self.menu_w - 2
            and self.menu_y + 1 <= mouse_y <= self.menu_y + len(self.options)
        )
        if not within:
            self.hovered_option = -1
            return None

        hovered = mouse_y - (self.menu_y + 1)
        if 0 <= hovered < len(self.options):
            if hovered != self.hovered_option:
                sounds.play_ui_move_sound()
            self.hovered_option = hovered
            self.selected_option = hovered
        return None

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[input_handlers.BaseEventHandler]:
        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        within = (
            self.menu_x + 1 <= mouse_x <= self.menu_x + self.menu_w - 2
            and self.menu_y + 1 <= mouse_y <= self.menu_y + len(self.options)
        )

        if event.button == tcod.event.MouseButton.LEFT:
            if within:
                self.selected_option = mouse_y - (self.menu_y + 1)
                return self._run_selected()
            return self.parent_menu

        if event.button == tcod.event.MouseButton.RIGHT:
            # Right click outside closes; inside confirms hovered action.
            if within:
                self.selected_option = mouse_y - (self.menu_y + 1)
                return self._run_selected()
            return self.parent_menu

        return None

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[input_handlers.BaseEventHandler]:
        if event.sym in (tcod.event.K_ESCAPE, tcod.event.KeySym.BACKSPACE):
            return self.parent_menu
        if event.sym == tcod.event.KeySym.UP:
            sounds.play_ui_move_sound()
            self.selected_option = (self.selected_option - 1) % len(self.options)
            return None
        if event.sym == tcod.event.KeySym.DOWN:
            sounds.play_ui_move_sound()
            self.selected_option = (self.selected_option + 1) % len(self.options)
            return None
        if event.sym in (tcod.event.KeySym.RETURN, tcod.event.KeySym.KP_ENTER, tcod.event.KeySym.SPACE):
            return self._run_selected()
        return None


class ConfirmationDialog(input_handlers.BaseEventHandler):
    """A confirmation dialog with Yes/No options."""
    
    def __init__(self, parent_handler, message: str, callback):
        super().__init__()
        self.parent_handler = parent_handler
        self.message = message
        self.callback = callback
        self.selected_option = 1  # Default to "No" for safety
        self.options = ["Yes", "No"]
        self.hovered_option = -1
        self._dialog_x = 0
        self._dialog_y = 0
        self._dialog_w = 0
        self._dialog_h = 0
        self._options_y = 0
        self._option_cells: list[tuple[int, int, int]] = []
    
    def on_render(self, console: tcod.console.Console) -> None:
        """Render the confirmation dialog."""
        # Render parent in background
        if hasattr(self.parent_handler, 'on_render'):
            self.parent_handler.on_render(console)
        
        # Calculate dialog dimensions
        lines = self.message.split('\n')
        dialog_width = max(30, max(len(line) for line in lines) + 4)
        dialog_height = len(lines) + 6
        
        x = (console.width - dialog_width) // 2
        y = (console.height - dialog_height) // 2
        self._dialog_x = x
        self._dialog_y = y
        self._dialog_w = dialog_width
        self._dialog_h = dialog_height
        
        # Apply faded background effect (dims everything except dialog area)
        # self.render_faded(console, x, y, dialog_width, dialog_height)
        
        # Draw dialog box with parchment styling
        MenuRenderer.draw_parchment_background(console, x, y, dialog_width, dialog_height)
        MenuRenderer.draw_ornate_border(console, x, y, dialog_width, dialog_height, "Confirm")
        
        # Draw message
        for i, line in enumerate(lines):
            console.print(
                x + (dialog_width // 2),
                y + 2 + i,
                line,
                fg=color.fantasy_text,
                bg=color.parchment_bg,
                alignment=tcod.CENTER,
            )
        
        # Draw Yes/No options
        options_y = y + dialog_height - 3
        self._options_y = options_y
        total_width = sum(len(opt) for opt in self.options) + 6  # 3 spaces between options
        start_x = x + (dialog_width - total_width) // 2
        self._option_cells = []
        
        for i, option in enumerate(self.options):
            is_selected = i == self.selected_option
            fg_color = color.red if is_selected and option == "Yes" else color.gold_accent if is_selected else color.fantasy_text
            bg_color = (80, 60, 30) if is_selected else (45, 35, 25)
            
            text = f"[{option}]" if is_selected else f" {option} "
            option_x = start_x + i * (len(text) + 3)
            console.print(
                option_x,
                options_y,
                text,
                fg=fg_color,
                bg=bg_color,
            )
            self._option_cells.append((i, option_x, len(text)))

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> Optional[input_handlers.BaseEventHandler]:
        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        if mouse_y != self._options_y:
            self.hovered_option = -1
            return None

        hit = -1
        for idx, option_x, option_w in self._option_cells:
            if option_x <= mouse_x < option_x + option_w:
                hit = idx
                break

        if hit != self.hovered_option and hit >= 0:
            sounds.play_ui_move_sound()
        self.hovered_option = hit
        if hit >= 0:
            self.selected_option = hit
        return None

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[input_handlers.BaseEventHandler]:
        if event.button != tcod.event.MouseButton.LEFT:
            return None

        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        if mouse_y == self._options_y:
            for idx, option_x, option_w in self._option_cells:
                if option_x <= mouse_x < option_x + option_w:
                    self.selected_option = idx
                    return self.callback(self.selected_option == 0)

        # Click outside dialog cancels (same as Esc/No).
        if not (
            self._dialog_x <= mouse_x < self._dialog_x + self._dialog_w
            and self._dialog_y <= mouse_y < self._dialog_y + self._dialog_h
        ):
            return self.callback(False)

        return None
    
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[input_handlers.BaseEventHandler]:
        """Handle confirmation dialog input."""
        if event.sym in (tcod.event.K_ESCAPE, tcod.event.KeySym.N):
            # Cancel/No
            return self.callback(False)
        elif event.sym == tcod.event.KeySym.Y:
            # Yes
            return self.callback(True)
        elif event.sym in (tcod.event.KeySym.LEFT, tcod.event.KeySym.RIGHT):
            # Toggle between Yes/No
            sounds.play_ui_move_sound()
            self.selected_option = 1 - self.selected_option
            return None
        elif event.sym in (tcod.event.KeySym.RETURN, tcod.event.KeySym.KP_ENTER, tcod.event.KeySym.SPACE):
            # Confirm current selection
            return self.callback(self.selected_option == 0)  # 0 = Yes, 1 = No
        
        return None


class DebugLevelScreen(input_handlers.BaseEventHandler):
    """Create a simple debug level immediately."""
    
    def __init__(self, parent_menu, game_seed=None, seed_string=None):
        self.parent_menu = parent_menu
        self.engine = new_debug_game(game_seed=game_seed, seed_string=seed_string)
    
    def handle_events(self, event: tcod.event.Event) -> input_handlers.BaseEventHandler:
        """Immediately transition to debug level."""
        from input_handlers import MainGameEventHandler
        return MainGameEventHandler(self.engine)
    
    def on_render(self, console: tcod.console.Console) -> None:
        """This shouldn't be called since we transition immediately."""
        console.clear()
        console.print(
            console.width // 2,
            console.height // 2,
            "Loading Debug Level...",
            fg=color.white,
            alignment=tcod.CENTER,
        )


class MainMenu(input_handlers.BaseEventHandler):
    """Handle the main menu rendering and input."""
    
    def __init__(self, _auto_music=True):
        super().__init__()
        self.menu_options = [
            ("Enter New Dungeon", "start_new"),
            ("Reenter Saved Dungeon", "load_game"), 
            #("Tutorial", "tutorial"),
            ("Settings", "settings"),
            #("Debug Level", "debug_level"),
            ("Quit", "quit")
        ]
        self.selected_option = 0
        self.engine = Engine()
        self.engine.debug_log("Menu Engine init", handler=type(self).__name__, event="menu_init")
        # Start menu ambience and music (suppressed when entering via CRT transition
        # so the VHS warp triggers first, then post_fn starts music)
        if _auto_music:
            sounds.start_menu_ambience()
            sounds.start_menu_music()
        self.menu_start_y = 0
        self.menu_x = 0 

    def on_render(self, console: tcod.console.Console) -> None:
        """Render the main menu with parchment styling and arrow key selection."""
        current_bg = animated_bg.get_current_frame()
        if current_bg is not None:
            console.draw_semigraphics(current_bg, 0, 0) 

        # Calculate menu window dimensions and position
        window_width = 45
        window_height = 16
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2 - 2

        # Draw parchment background and ornate border
        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "Dungeons of \u00c6rrok: The Divine Stone", title_fg=(182, 255, 245))

        # Draw menu options with selection highlighting
        # Set menu_start_y here so it can be used for mouse hover calculations in ev_mousemotion
        self.menu_start_y = y + 3
        for i, (option_text, _) in enumerate(self.menu_options):
            is_selected = i == self.selected_option
            bg_color = (80, 60, 30) if is_selected else (45, 35, 25)
            fg_color = color.gold_accent if is_selected else color.fantasy_text
            marker = "> " if is_selected else "  "
            marker2 = " <" if is_selected else "  "
            
            # Draw option with background
            option_y = self.menu_start_y + i * 2
            full_text = f"{marker}{option_text}{marker2}".center(window_width - 4)
            
            # Set menu_start_x for mouse hover calculations
            self.menu_start_x = x + (window_width // 2)

            # Draw background for the entire line
            for dx in range(window_width - 2):
                console.print(x + 1 + dx, option_y, " ", bg=bg_color)

             
            console.print(
                x + (window_width // 2),
                option_y,
                full_text.strip(),
                fg=fg_color,
                bg=bg_color,
                alignment=tcod.CENTER
            )
        

        # Draw footer information with parchment styling
        footer_y = y + window_height - 3
        console.print(
            x + (window_width // 2) + 38,
            footer_y + 20,
            "loxen",
            fg=color.gold_accent,
            bg=None,
            alignment=tcod.CENTER,
        )
        console.print(
            x + (window_width // 2) + 28,
            footer_y + 21,
            "2026 - Early Beta Release",
            fg=color.gold_accent,
            # No background
            bg=None,
            alignment=tcod.CENTER,
        )

        # Draw instructions outside the window
        instructions_y = y + window_height + 1
        console.print(
            console.width // 2,
            instructions_y,
            "[\u2191\u2193] Navigate  [Space] Select  [Esc] Quit",
            fg=color.fantasy_text,
            alignment=tcod.CENTER,
        )
    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> Optional[input_handlers.BaseEventHandler]:
        """Allow mouse hover to change selection."""
        # Calculate menu window dimensions and position
        window_width = 40
        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        
        if (self.menu_start_x - window_width // 2 <= mouse_x <= self.menu_start_x + window_width // 2 and
            self.menu_start_y <= mouse_y < self.menu_start_y + len(self.menu_options) * 2):
            # Calculate which option is hovered
            hovered_option = (mouse_y - self.menu_start_y) // 2
            if 0 <= hovered_option < len(self.menu_options):
                if hovered_option != self.selected_option:
                    sounds.play_ui_move_sound()
                self.selected_option = hovered_option
        else:
            self.selected_option = -1
        
        return None
        
    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[input_handlers.BaseEventHandler]:
        if event.button == tcod.event.MouseButton.LEFT:
            return self._handle_selection()
        return None
        

    def ev_keydown(
        self, event: tcod.event.KeyDown) -> Optional[input_handlers.BaseEventHandler]:
        sounds.play_ui_move_sound()
        print(self.engine.mouse_held)
        if event.sym == tcod.event.KeySym.UP:
            self.selected_option = (self.selected_option - 1) % len(self.menu_options)
            return None
        elif event.sym == tcod.event.KeySym.DOWN:
            self.selected_option = (self.selected_option + 1) % len(self.menu_options)
            return None
        
        elif self.engine.mouse_held:
            return self._handle_selection()
        elif event.sym in (tcod.event.KeySym.RETURN, tcod.event.KeySym.KP_ENTER, tcod.event.KeySym.SPACE):
            return self._handle_selection()
        elif event.sym in (tcod.event.KeySym.Q, tcod.event.K_ESCAPE):
            if self.selected_option == 5:  # Quit option
                raise SystemExit()
            else:
                # Move selection to Quit option
                self.selected_option = 5
                return None
        
        return None
    
    def _handle_selection(self) -> Optional[input_handlers.BaseEventHandler]:
        """Handle the currently selected menu option."""
        if self.selected_option < 0:
            return None
        if self.selected_option >= len(self.menu_options):
            return None
            
        _, action = self.menu_options[self.selected_option]
        
        if action == "quit":
            print("Quitting game...")
            sounds.stop_menu_ambience()
            sounds.stop_all_music()
            return input_handlers.CRTTransition(
                lambda: None,
                pre_fn=lambda: (sounds.stop_all_sounds(), sys.exit()),
            )
        elif action == "load_game":
            # Show save game selection menu
            return SaveGameMenu(self)
        elif action == "tutorial":
            
            # Create tutorial game engine
            engine = tutorial_game()
            
            return input_handlers.CRTTransition(
                input_handlers.MainGameEventHandler(engine),
                pre_fn=lambda: (sounds.stop_menu_ambience(), sounds.stop_all_music()),
                post_fn=sounds.start_dungeon_music
            )
        elif action == "start_new":

            
            # Create callback for seed input
            def handle_seed_input(entered_seed):
                """Handle seed input and start loading screen."""
                # Handle cancellation (ESC was pressed)
                if entered_seed is None:
                    return self
                    
                game_seed = None
                seed_string = None
                if entered_seed.strip():  # Only set seed if something was entered
                    # Try to parse as integer first, otherwise use as string
                    if entered_seed.strip().isdigit():
                        game_seed = int(entered_seed.strip())
                    else:
                        seed_string = entered_seed.strip()
                loading_screen = LoadingScreen(self, game_seed=game_seed, seed_string=seed_string)
                # Stop menu ambience when leaving menu  
                sounds.stop_menu_ambience()
                sounds.stop_all_music()
                sounds.stop_all_sounds()
                return loading_screen
            
            return input_handlers.TextInputHandler(
                engine=None,  # Setup screens don't need engine
                title="Enter Seed",
                prompt="Enter world seed (optional):",
                max_length=40,
                callback=handle_seed_input,
                parent_handler=self  # Pass self so background can be rendered
            )
        elif action == "debug_level":
            return input_handlers.CRTTransition(
                lambda: input_handlers.MainGameEventHandler(new_debug_game()),
                pre_fn=lambda: (sounds.stop_menu_ambience(), sounds.stop_all_music()),
                post_fn=sounds.start_dungeon_music
            )
        elif action == "settings":
            from input_handlers import Settings
            return Settings(parent_handler=self)
        return None


# Set up music tracks - add your music files here!
def initialize_music():
    """Initialize music tracks. Call this to add your music files."""
    # Example: uncomment and use your actual music files
    # sounds.add_dungeon_track("RP/music/dungeon_ambient1.ogg")
    # sounds.add_dungeon_track("RP/music/dungeon_ambient2.ogg") 
    # sounds.add_menu_track("RP/music/menu_theme1.ogg")
    # sounds.add_menu_track("RP/music/menu_theme2.ogg")
    
    # For testing, you can use existing sound files as music:
    # sounds.add_dungeon_track("RP/sfx/loops/dungeon/ambience.wav")
    # sounds.add_menu_track("RP/sfx/loops/menu/theme.wav")
    
    pass

# Initialize music tracks when module loads
initialize_music()


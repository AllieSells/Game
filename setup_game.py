"""Handle the loading and initialization of game sessions."""
from __future__ import annotations

import copy
import lzma
import pickle
from tempfile import TemporaryFile
import traceback
from typing import Optional

import tcod

import color
from components import equipment
from engine import Engine
import entity_factories
from game_map import GameWorld
import input_handlers
from render_functions import MenuRenderer
import sounds


# Load the background image and remove the alpha channel.
background_image = tcod.image.load("image.png")[:, :, :3]



def new_game() -> Engine:
    """Return a brand new game session as an Engine instance."""
    map_width = 80
    map_height = 40

    room_max_size = 10
    room_min_size = 6
    max_rooms = 30



    import random

    


    player = copy.deepcopy(entity_factories.player)
    
    # DEBUG: Set XP close to level up (350 needed for level 2)
    player.level.current_xp = 0

    engine = Engine(player=player)
    print(engine)
    
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
    for x in range(random.randint(5, 10)):
        fungus = entity_factories.get_random_fungus()
        engine.game_world.fungi.append(fungus)
        print(fungus.name)

    engine.game_world.generate_floor()
    engine.update_fov()
    
    # Clear world generation flag after generation is complete
    engine.is_generating_world = False

    engine.message_log.add_message("Press ? For Controls")
    engine.message_log.add_message(
        "You enter the dungeon. Haunted figures move in the dark...", color.welcome_text
    )

    return engine

def new_debug_game() -> Engine:
    """Return a debug game session with an empty wallless map."""
    map_width = 80
    map_height = 40
    
    player = copy.deepcopy(entity_factories.player)
    
    # DEBUG: Set XP close to level up (350 needed for level 2)
    player.level.current_xp = 340
    
    engine = Engine(player=player)
    
    # Set world generation flag to suppress equipment sounds
    engine.is_generating_world = True
    
    # Create a simple empty map
    from game_map import GameMap
    import tile_types
    import numpy as np
    
    # Create empty map with all floor tiles
    game_map = GameMap(engine, map_width, map_height, entities=[player], type="debug", name="Debug Level")
    game_map.tiles[:] = tile_types.floor
    
    # Make the entire map fully lit
    import numpy as np
    lit_array = np.full((map_width, map_height), True, dtype=bool)
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
    
    # Add test walls and doors for sound obstruction testing
    
    # Test 1: Campfire behind a wall (heavy obstruction)
    # Build wall at x=15, from y=5 to y=15
    for y in range(5, 16):
        game_map.tiles[15, y] = tile_types.wall
        # Make wall lit too
        current_tile = game_map.tiles[15, y]
        new_tile = (
            True,  # lit
            current_tile[1],  # name  
            current_tile[2],  # walkable
            current_tile[3],  # transparent
            current_tile[4],  # dark
            current_tile[5],  # light
            current_tile[6],  # interactable
        )
        game_map.tiles[15, y] = new_tile
    campfire1 = copy.deepcopy(entity_factories.campfire)
    campfire1.spawn(game_map, 12, 10)  # Campfire behind wall
    
    # Test 2: Campfire behind a closed door (medium obstruction) 
    # Build wall with door at x=35, from y=15 to y=25
    for y in range(15, 26):
        if y == 20:  # Door position
            game_map.tiles[35, y] = tile_types.closed_door
        else:
            game_map.tiles[35, y] = tile_types.wall
        # Make door/wall lit 
        current_tile = game_map.tiles[35, y]
        new_tile = (
            True,  # lit
            current_tile[1],  # name  
            current_tile[2],  # walkable
            current_tile[3],  # transparent
            current_tile[4],  # dark
            current_tile[5],  # light
            current_tile[6],  # interactable
        )
        game_map.tiles[35, y] = new_tile
    campfire2 = copy.deepcopy(entity_factories.campfire)
    campfire2.spawn(game_map, 32, 20)  # Campfire behind door
    
    # Test 3: Campfire behind an open door (minimal obstruction)
    # Build wall with open door at x=55, from y=10 to y=20  
    for y in range(10, 21):
        if y == 15:  # Open door position
            game_map.tiles[55, y] = tile_types.open_door
        else:
            game_map.tiles[55, y] = tile_types.wall
        # Make door/wall lit
        current_tile = game_map.tiles[55, y]
        new_tile = (
            True,  # lit
            current_tile[1],  # name  
            current_tile[2],  # walkable
            current_tile[3],  # transparent
            current_tile[4],  # dark
            current_tile[5],  # light
            current_tile[6],  # interactable
        )
        game_map.tiles[55, y] = new_tile
    campfire3 = copy.deepcopy(entity_factories.campfire)
    campfire3.spawn(game_map, 52, 15)  # Campfire behind open door
    
    # Test 4: Unobstructed campfire for comparison
    campfire4 = copy.deepcopy(entity_factories.campfire)
    campfire4.spawn(game_map, 25, 30)  # Open area campfire

    
    # Place player in center
    player.place(map_width // 2, map_height // 2, game_map)
    
    # Add some test liquid coatings for demonstration
    from liquid_system import LiquidType
    
    # Water splash near player
    game_map.liquid_system.create_splash(
        map_width // 2 + 5, map_height // 2 + 3, 
        LiquidType.WATER, radius=3, max_depth=2
    )
    
    # Blood splatter
    game_map.liquid_system.create_splash(
        map_width // 2 - 7, map_height // 2 - 2,
        LiquidType.BLOOD, radius=2, max_depth=3
    )
    
    # Oil spill
    game_map.liquid_system.create_splash(
        map_width // 2 + 8, map_height // 2 - 5,
        LiquidType.OIL, radius=4, max_depth=2
    )
    
    # Slime trail
    game_map.liquid_system.create_trail(
        map_width // 2 - 10, map_height // 2 + 8,
        map_width // 2 - 3, map_height // 2 + 12,
        LiquidType.SLIME, width=1
    )
    
    # Give player one of every item for testing
    try:
        all_items = [
            entity_factories.lesser_health_potion,
            entity_factories.lightning_scroll, 
            entity_factories.confusion_scroll,
            entity_factories.fireball_scroll,
            entity_factories.torch,
            entity_factories.dagger,
            entity_factories.sword,
            entity_factories.leather_armor,
            entity_factories.chain_mail,
            entity_factories.dev_tool,
            entity_factories.backpack,
            entity_factories.coin,
        ]
        
        # Add items to inventory properly
        for item_template in all_items:
            try:
                item = copy.deepcopy(item_template)
                item.parent = player.inventory
                if item.consumable or item.equippable:
                    player.inventory.items.append(item)
            except:
                pass
    except:
        pass
    
    # Spawn test enemies around the player
    try:
        center_x = map_width // 2
        center_y = map_height // 2
        
        # Spawn enemies at various positions
        test_enemies = [
            (entity_factories.goblin, center_x + 8, center_y),
            (entity_factories.goblin, center_x - 8, center_y),
            (entity_factories.troll, center_x, center_y + 8),
            (entity_factories.shade, center_x + 5, center_y + 5),
        ]
        
        for enemy_template, x, y in test_enemies:
            if (0 <= x < map_width and 0 <= y < map_height and 
                game_map.tiles["walkable"][x, y]):
                enemy = copy.deepcopy(enemy_template)
                enemy.spawn(game_map, x, y)
    except:
        pass
    
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
    engine.message_log.add_message("Empty map with test enemies and all items.", color.gray)
    engine.message_log.add_message("Features: Sound test areas, liquid coating system", color.yellow)
    engine.message_log.add_message("Check your inventory (I) and test wandering enemies!", color.yellow)
    
    # Clear world generation flag after debug setup is complete
    engine.is_generating_world = False
    
    return engine

def load_game(filename: str) -> Engine:
    # Load engine instance from file
    with open(filename, "rb") as f:
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
    return engine 

class LoadingScreen(input_handlers.BaseEventHandler):
    """Display a loading screen while generating the world."""
    
    def __init__(self, parent_menu):
        self.parent_menu = parent_menu
        self.generation_steps = [
            "Initializing world...",
            "Generating rooms...",
            "Placing loot...",
            "Adding campfires...",
            "Spawning entities...",
            "Feeding critters...",
            "Finalizing world...",
            "World generation complete!"
        ]
        self.current_step = 0
        self.dots = 0
        self.max_dots = 3
        self.frame_count = 0
        self.engine = None
        self.generation_started = False
        self.generation_complete = False
        self.completion_delay = 0  # Frames to show completion before transitioning
    
    def on_render(self, console: tcod.Console) -> None:
        try:
            """Render the loading screen with parchment styling."""
            # Use the same background as main menu
            console.draw_semigraphics(background_image, 0, 0)
            
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
                if not self.generation_complete:
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
            if self.generation_complete:
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
                    if self.generation_complete:
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
            if not self.generation_complete:
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
        """Generate the world with step-by-step progress updates."""
        import time
        
        try:
            # Step 1: Initializing
            self.current_step = 0
            
            # Step 2: Creating terrain
            self.current_step = 1
            
            # Step 3: Generate buildings (this is where most of the work happens)
            self.current_step = 2
            
            # Start actual generation
            self.engine = new_game()
            
            # Step 4: Doors and entrances (already done in new_game)
            self.current_step = 3
            
            # Step 5: Campfires (already done)
            self.current_step = 4
            
            # Step 6: Villagers (already done)
            self.current_step = 5
            
            # Step 7: Finalizing
            self.current_step = 6
            
            # Step 8: Complete
            self.current_step = 7
            self.generation_complete = True
            
            # Wait a moment to show completion, then auto-transition
            
        except Exception as e:
            # If generation fails
            self.current_step = len(self.generation_steps)
            self.generation_complete = True
            self.engine = None
            print(f"Generation failed: {e}")
            import traceback
            traceback.print_exc()

    
    def handle_events(self, event: tcod.event.Event) -> input_handlers.BaseEventHandler:
        """Handle events during loading."""
        # Auto-transition to game when generation is complete (after brief delay)
        if self.generation_complete and self.engine is not None:
            self.completion_delay += 1
            if self.completion_delay > 60:  # Wait about 1 second at 60 FPS
                from input_handlers import MainGameEventHandler
                return MainGameEventHandler(self.engine)
        
        # Allow ESC to cancel and return to main menu at any time
        if isinstance(event, tcod.event.KeyDown) and event.sym == tcod.event.K_ESCAPE:
            return self.parent_menu
        
        # Allow any key to skip waiting and go directly to game if generation is done
        if self.generation_complete and isinstance(event, tcod.event.KeyDown):
            if self.engine is not None:
                from input_handlers import MainGameEventHandler
                return MainGameEventHandler(self.engine)
            else:
                # Generation failed, return to main menu
                return self.parent_menu
            
        return self


class DebugLevelScreen(input_handlers.BaseEventHandler):
    """Create a simple debug level immediately."""
    
    def __init__(self, parent_menu):
        self.parent_menu = parent_menu
        self.engine = new_debug_game()
    
    def handle_events(self, event: tcod.event.Event) -> input_handlers.BaseEventHandler:
        """Immediately transition to debug level."""
        from input_handlers import MainGameEventHandler
        return MainGameEventHandler(self.engine)
    
    def on_render(self, console: tcod.Console) -> None:
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
    
    def __init__(self):
        super().__init__()
        self.menu_options = [
            ("Play a new game", "start_new"),
            ("Continue last game", "load_game"), 
            ("Debug Level", "debug_level"),
            ("Quit", "quit")
        ]
        self.selected_option = 0
        # Start menu ambience only if not already playing
        sounds.start_menu_ambience()

    def on_render(self, console: tcod.Console) -> None:
        """Render the main menu with parchment styling and arrow key selection."""
        console.draw_semigraphics(background_image, 0, 0)

        # Calculate menu window dimensions and position
        window_width = 40
        window_height = 16
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2 - 2

        # Draw parchment background and ornate border
        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "WORK IN PROGRESS TITLE?")

        # Draw menu options with selection highlighting
        menu_start_y = y + 4
        for i, (option_text, _) in enumerate(self.menu_options):
            is_selected = i == self.selected_option
            bg_color = (80, 60, 30) if is_selected else (45, 35, 25)
            fg_color = color.gold_accent if is_selected else color.fantasy_text
            marker = "> " if is_selected else "  "
            marker2 = " <" if is_selected else "  "
            
            # Draw option with background
            option_y = menu_start_y + i * 2
            full_text = f"{marker}{option_text}{marker2}".center(window_width - 4)
            
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
            x + (window_width // 2),
            footer_y,
            "oxenfree",
            fg=color.bronze_text,
            bg=color.parchment_bg,
            alignment=tcod.CENTER,
        )
        console.print(
            x + (window_width // 2),
            footer_y + 1,
            "2026 - Version 0.1.2 Beta",
            fg=color.bronze_text,
            bg=color.parchment_bg,
            alignment=tcod.CENTER,
        )

        # Draw instructions outside the window
        instructions_y = y + window_height + 1
        console.print(
            console.width // 2,
            instructions_y,
            "[↑↓] Navigate  [Space] Select  [Esc] Quit",
            fg=color.fantasy_text,
            alignment=tcod.CENTER,
        )

    def ev_keydown(
        self, event: tcod.event.KeyDown
    ) -> Optional[input_handlers.BaseEventHandler]:
        sounds.play_menu_move_sound()
        if event.sym == tcod.event.KeySym.UP:
            self.selected_option = (self.selected_option - 1) % len(self.menu_options)
            return None
        elif event.sym == tcod.event.KeySym.DOWN:
            self.selected_option = (self.selected_option + 1) % len(self.menu_options)
            return None
        elif event.sym in (tcod.event.KeySym.RETURN, tcod.event.KeySym.KP_ENTER, tcod.event.KeySym.SPACE):
            return self._handle_selection()
        elif event.sym in (tcod.event.KeySym.Q, tcod.event.K_ESCAPE):
            if self.selected_option == 3:  # Quit option
                raise SystemExit()
            else:
                # Move selection to Quit option
                self.selected_option = 3
                return None
            
        # Legacy key support (optional - can be removed if desired)
        elif event.sym == tcod.event.KeySym.C:
            self.selected_option = 1  # Continue option
            return self._handle_selection()
        elif event.sym == tcod.event.KeySym.N:
            self.selected_option = 0  # New game option 
            return self._handle_selection()
        elif event.sym == tcod.event.KeySym.D:
            self.selected_option = 2  # Debug option
            return self._handle_selection()

        return None
    
    def _handle_selection(self) -> Optional[input_handlers.BaseEventHandler]:
        """Handle the currently selected menu option."""
        if self.selected_option >= len(self.menu_options):
            return None
            
        _, action = self.menu_options[self.selected_option]
        
        if action == "quit":
            sounds.stop_menu_ambience()
            raise SystemExit()
        elif action == "load_game":
            # Stop menu ambience when leaving menu
            sounds.stop_menu_ambience()
            print("TEST")
            try:
                sounds.play_stairs_sound()
                return input_handlers.MainGameEventHandler(load_game("savegame.sav"))
            except FileNotFoundError:
                return input_handlers.PopupMessage(self, "No saved game to load.")
            except Exception as exc:
                traceback.print_exc() # print to stderr
                return input_handlers.PopupMessage(self, f"Failed to load save :\n{exc}")
        elif action == "start_new":
            # Stop menu ambience when leaving menu  
            sounds.stop_menu_ambience()
            # Skip character creation and start game directly
            sounds.play_stairs_sound()
            return LoadingScreen(self)
        elif action == "debug_level":
            # Stop menu ambience when leaving menu
            sounds.stop_menu_ambience() 
            # Create debug level
            return DebugLevelScreen(self)
        
        return None
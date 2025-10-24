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

    engine = Engine(player=player)
    print(engine)

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

    engine.message_log.add_message("Press ? For Controls")
    engine.message_log.add_message(
        "You enter the dungeon. Haunted figures move in the dark...", color.welcome_text
    )

    dagger = copy.deepcopy(entity_factories.dagger)
    leather_armor = copy.deepcopy(entity_factories.leather_armor)


    dagger.parent = player.inventory
    leather_armor.parent = player.inventory

    player.inventory.items.append(dagger)
    player.equipment.toggle_equip(dagger, add_message=False)

    player.inventory.items.append(leather_armor)
    player.equipment.toggle_equip(leather_armor, add_message=False)


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
            """Render the loading screen."""
            # Use the same background as main menu
            console.draw_semigraphics(background_image, 0, 0)
            
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
                console.width // 2,
                console.height // 2 - 2,
                current_text,
                fg=color.menu_title,
                bg=color.black,
                alignment=tcod.CENTER,
                bg_blend=tcod.BKGND_ALPHA(64),
            )
            
            # Show progress bar
            bar_width = 50
            bar_x = (console.width - bar_width) // 2
            bar_y = console.height // 2 + 1
            
            # Calculate progress percentage
            if self.generation_complete:
                progress = 1.0
            else:
                progress = self.current_step / len(self.generation_steps)
            
            # Draw progress bar frame
            console.print(bar_x, bar_y, "[" + " " * (bar_width - 2) + "]", fg=color.white)
            
            # Fill progress bar
            fill_width = int((bar_width - 2) * progress)
            if fill_width > 0:
                console.print(bar_x + 1, bar_y, "=" * fill_width, fg=color.green if self.generation_complete else color.yellow)
            
            # Show percentage
            percentage = int(progress * 100)
            console.print(
                console.width // 2,
                bar_y + 2,
                f"{percentage}%",
                fg=color.white,
                alignment=tcod.CENTER,
            )
            
            # Show completed steps
            step_y = console.height // 2 + 4
            for i, step in enumerate(self.generation_steps[:self.current_step]):
                if step_y + i < console.height - 3:  # Make sure we don't go off screen
                    console.print(
                        console.width // 2,
                        step_y + i,
                        f"✓ {step.replace('...', '')}",
                        fg=color.green,
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


class MainMenu(input_handlers.BaseEventHandler):
    """Handle the main menu rendering and input."""

    def on_render(self, console: tcod.Console) -> None:
        """Render the main menu on a background image."""
        console.draw_semigraphics(background_image, 0, 0)

        console.print(
            console.width // 2,
            console.height // 2 - 4,
            "WORK IN PROGRESS TITLE?",
            fg=color.menu_title,
            bg=color.black,
            alignment=tcod.CENTER,
            bg_blend=tcod.BKGND_ALPHA(64),
        )
        console.print(
            console.width // 2,
            console.height - 3,
            "oxenfree\n2025\nVersion 0.11 Pre-Alpha",
            fg=color.menu_title,
            alignment=tcod.CENTER,
        )

        menu_width = 24
        for i, text in enumerate(
            ["[N] Play a new game", "[C] Continue last game", "[Q] Quit"]
        ):
            console.print(
                console.width // 2,
                console.height // 2 - 2 + i,
                text.ljust(menu_width),
                fg=color.menu_text,
                bg=color.black,
                alignment=tcod.CENTER,
                bg_blend=tcod.BKGND_ALPHA(64),
            )

    def ev_keydown(
        self, event: tcod.event.KeyDown
    ) -> Optional[input_handlers.BaseEventHandler]:
        if event.sym in (tcod.event.KeySym.Q, tcod.event.K_ESCAPE):
            raise SystemExit()
        elif event.sym == tcod.event.KeySym.C:
            print("TEST")
            try:
                return input_handlers.MainGameEventHandler(load_game("savegame.sav"))
            except FileNotFoundError:
                return input_handlers.PopupMessage(self, "No saved game to load.")
            except Exception as exc:
                traceback.print_exc() # print to stderr
                return input_handlers.PopupMessage(self, f"Failed to load save :\n{exc}")
            pass
        elif event.sym == tcod.event.KeySym.N:
            # Skip character creation and start game directly
            return LoadingScreen(self)

        return None
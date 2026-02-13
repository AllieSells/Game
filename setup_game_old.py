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

    engine.game_world.generate_floor()
    engine.update_fov()

    engine.message_log.add_message("Press ? For Controls")
    engine.message_log.add_message(
        "You enter the dungeon. Haunted figures move in the dark...", color.welcome_text
    )

    dagger = copy.deepcopy(entity_factories.dagger)
    leather_armor = copy.deepcopy(entity_factories.leather_armor)
    leather_cap = copy.deepcopy(entity_factories.leather_cap)


    dagger.parent = player.inventory
    leather_armor.parent = player.inventory
    leather_cap.parent = player.inventory

    player.inventory.items.append(dagger)
    player.equipment.toggle_equip(dagger, add_message=False)

    player.inventory.items.append(leather_armor)
    player.equipment.toggle_equip(leather_armor, add_message=False)

    player.inventory.items.append(leather_cap)
    player.equipment.toggle_equip(leather_cap, add_message=False)

    return engine

def load_game(filename: str) -> Engine:
    # Load engine instance from file
    with open(filename, "rb") as f:
        engine = pickle.loads(lzma.decompress(f.read()))
    assert isinstance(engine, Engine)
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
            time.sleep(0.3)
            
            # Step 2: Creating terrain
            self.current_step = 1
            time.sleep(0.3)
            
            # Step 3: Generate buildings (this is where most of the work happens)
            self.current_step = 2
            
            # Start actual generation
            self.engine = new_game()
            
            # Step 4: Doors and entrances (already done in new_game)
            self.current_step = 3
            time.sleep(0.3)
            
            # Step 5: Campfires (already done)
            self.current_step = 4
            time.sleep(0.3)
            
            # Step 6: Villagers (already done)
            self.current_step = 5
            time.sleep(0.3)
            
            # Step 7: Finalizing
            self.current_step = 6
            time.sleep(0.3)
            
            # Step 8: Complete
            self.current_step = 7
            self.generation_complete = True
            
            # Wait a moment to show completion, then auto-transition
            time.sleep(0.8)
            
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


# Character Customization Configuration - Easy to modify for mods
CHARACTER_CONFIG = {
    "defaults": {
        "name": "Player",
        "char": "@", 
        "sponsor": 25,
        "equipment_points": 10,
        "skill_points": 5
    },
    "options": {
        "char": {
            "values": ["@", "&", "%", "#", "○"],
            "display_name": "Symbol"
        },
        "sponsor": {
            "type": "slider",
            "min_value": 0,
            "max_value": 50,
            "display_name": "Sponsor"
        },
        "equipment_points": {
            "type": "slider",
            "min_value": 2,
            "max_value": 15,
            "display_name": "Equipment Points"
        },
        "skill_points": {
            "type": "slider",
            "min_value": 0,
            "max_value": 15,
            "display_name": "Skill Points"
        }
    },
    "menu_layout": ["Name", "Symbol", "Sponsor", "Equipment Points", "Skill Points", "Start Game", "Back"]
}


# Skill System Configuration - Modular and extensible
SKILL_CONFIG = {
    "categories": {
        "combat": {
            "name": "Combat Skills",
            "color": (255, 100, 100),  # Red
            "skills": {
                "melee": {"name": "Melee Combat", "description": "Skill with swords, axes, and other close weapons", "max_level": 10},
                "ranged": {"name": "Ranged Combat", "description": "Skill with bows, crossbows, and thrown weapons", "max_level": 10},
                "defense": {"name": "Defense", "description": "Ability to block, parry, and avoid damage", "max_level": 10},
                "tactics": {"name": "Tactics", "description": "Combat strategy and battlefield awareness", "max_level": 10}
            }
        },
        "survival": {
            "name": "Survival Skills", 
            "color": (128, 0, 128),  # Purple
            "skills": {
                "stealth": {"name": "Stealth", "description": "Moving unseen and unheard", "max_level": 10},
                "perception": {"name": "Perception", "description": "Noticing hidden things and danger", "max_level": 10},
                "lockpicking": {"name": "Lockpicking", "description": "Opening locks and disabling traps", "max_level": 10},
                "foraging": {"name": "Foraging", "description": "Finding food and useful materials", "max_level": 10}
            }
        },
        "knowledge": {
            "name": "Knowledge Skills",
            "color": (100, 100, 255),  # Blue
            "skills": {
                "lore": {"name": "Lore", "description": "Knowledge of history, legends, and creatures", "max_level": 10},
                "medicine": {"name": "Medicine", "description": "Healing and treating injuries", "max_level": 10},
                "magic": {"name": "Magic Theory", "description": "Understanding magical forces and spells", "max_level": 10},
                "crafting": {"name": "Crafting", "description": "Creating and repairing equipment", "max_level": 10}
            }
        },
        "social": {
            "name": "Social Skills",
            "color": (255, 255, 100),  # Yellow
            "skills": {
                "persuasion": {"name": "Persuasion", "description": "Convincing others and negotiation", "max_level": 10},
                "deception": {"name": "Deception", "description": "Lying and misdirection", "max_level": 10},
                "leadership": {"name": "Leadership", "description": "Inspiring and commanding others", "max_level": 10},
                "trade": {"name": "Trade", "description": "Getting better deals and market knowledge", "max_level": 10}
            }
        }
    },
    "layout": ["combat", "survival", "knowledge", "social"]
}


class CharacterCustomizationScreen(input_handlers.BaseEventHandler):
    """Handle character customization before starting the game."""
    
    def __init__(self, parent_menu):
        self.parent_menu = parent_menu
        self.selected_option = 0
        
        # Initialize character data from config
        self.character_data = CHARACTER_CONFIG["defaults"].copy()
        
        # Initialize selection indices for each customizable option
        self.selected_indices = {}
        for option_key in CHARACTER_CONFIG["options"]:
            option_config = CHARACTER_CONFIG["options"][option_key]
            if option_config.get("type") == "slider":
                # For sliders, store the current value (not an index)
                self.selected_indices[option_key] = self.character_data[option_key]
            else:
                # For dropdown options, store the index
                self.selected_indices[option_key] = 0
        
        # Menu options from config
        self.menu_options = CHARACTER_CONFIG["menu_layout"]
        
        # Update character color based on RGB sliders
        self.update_color_from_sliders()
    
    def get_option_value(self, option_key, index_or_value):
        """Get the actual value for an option at the given index or slider value."""
        option_config = CHARACTER_CONFIG["options"][option_key]
        
        if option_config.get("type") == "slider":
            # For sliders, index_or_value is the actual value
            return index_or_value
        else:
            # For dropdown options, index_or_value is an index
            values = option_config["values"]
            if isinstance(values[index_or_value], dict):
                return values[index_or_value]["value"] if "value" in values[index_or_value] else values[index_or_value]["name"]
            else:
                return values[index_or_value]
    
    def get_option_display_name(self, option_key, index_or_value):
        """Get the display name for an option at the given index or slider value."""
        option_config = CHARACTER_CONFIG["options"][option_key]
        
        if option_config.get("type") == "slider":
            # For sliders, just return the value as string
            return str(index_or_value)
        else:
            # For dropdown options, index_or_value is an index
            values = option_config["values"]
            if isinstance(values[index_or_value], dict):
                return values[index_or_value]["name"]
            else:
                return str(values[index_or_value])
    
    def update_color_from_sliders(self):
        """Update the character color based on RGB slider values."""
        r = self.character_data.get("color_red", 52)
        g = self.character_data.get("color_green", 222)
        b = self.character_data.get("color_blue", 235)
        self.character_data["color"] = (r, g, b)
    
    def update_character_data(self, option_key):
        """Update character data when an option changes."""
        index_or_value = self.selected_indices[option_key]
        self.character_data[option_key] = self.get_option_value(option_key, index_or_value)
        
        # Update color if any RGB slider changed
        if option_key in ["color_red", "color_green", "color_blue"]:
            self.update_color_from_sliders()
    
    def on_render(self, console: tcod.Console) -> None:
        """Render the character customization screen."""
        console.draw_semigraphics(background_image, 0, 0)
        
        # Main character creation box
        box_width = 60
        box_height = 25
        box_x = (console.width - box_width) // 2
        box_y = (console.height - box_height) // 2
        
        console.draw_frame(
            x=box_x,
            y=box_y,
            width=box_width,
            height=box_height,
            title="CHARACTER CREATION",
            clear=True,
            fg=color.white,
            bg=color.black
        )
        
        # Character preview section
        preview_x = box_x + 5
        preview_y = box_y + 3
        
        console.print(
            preview_x,
            preview_y,
            "",
            fg=color.white,
        )
        
        # Character preview box (smaller frame inside main frame)
        preview_box_x = preview_x + 5
        preview_box_y = preview_y
        console.draw_frame(
            x=preview_box_x,
            y=preview_box_y,
            width=7,
            height=5,
            title="",
            clear=True,
            fg=color.white,
            bg=(0, 0, 0)
        )
        
        # Draw the character in center of preview box
        console.print(
            preview_box_x + 3,
            preview_box_y + 2,
            self.character_data["char"],
            fg=self.character_data["color"],
            bg=(0, 0, 0)
        )

        # Draw the character stats
        statbox_x = preview_box_x + 25
        statbox_y = preview_box_y - 1
        console.print(
            statbox_x,
            statbox_y + 2,
            f"Name: {self.character_data['name']}",
            fg=color.white,
            bg=(0, 0, 0)
        )
        console.print(
            statbox_x,
            statbox_y + 7,
            f"Sponsor: {self.character_data['sponsor']}",
            fg=color.white,
            bg=(0, 0, 0)
        )
        console.print(
            statbox_x,
            statbox_y + 8,
            f"Equipment Pts: {self.character_data['equipment_points']}",
            fg=color.white,
            bg=(0, 0, 0)
        )
        console.print(
            statbox_x,
            statbox_y + 9,
            f"Skill Pts: {self.character_data['skill_points']}",
            fg=color.white,
            bg=(0, 0, 0)
        )

        # Vertical divider from selection to stat preview
        console.vline(preview_x + 25, preview_y-3, 22)
        
        # Menu options section (moved up, no character info display)
        menu_start_y = preview_y + 7  # Just below the preview box
        
        for i, option in enumerate(self.menu_options):
            fg_color = color.green if i == self.selected_option else color.menu_text
            
            text = f"> {option}" if i == self.selected_option else f"  {option}"
            
            # Show current selection for customizable options
            if option == "Name":
                text += f": {self.character_data['name']}"
            else:
                # Map menu option to data key
                option_key = self._get_option_key(option)
                if option_key and option_key in CHARACTER_CONFIG["options"]:
                    option_config = CHARACTER_CONFIG["options"][option_key]
                    
                    if option_config.get("type") == "slider":
                        # Display slider with current value
                        current_value = self.selected_indices[option_key]
                        text += f": {current_value}"
                    else:
                        # Display dropdown option
                        display_name = self.get_option_display_name(option_key, self.selected_indices[option_key])
                        text += f": {display_name}"
            
            console.print(
                box_x + 3,
                menu_start_y + i,
                text,
                fg=fg_color,
            )
            
            # Show slider bar for slider options
            option_key = self._get_option_key(option)
            if option_key and option_key in CHARACTER_CONFIG["options"]:
                option_config = CHARACTER_CONFIG["options"][option_key]
                if option_config.get("type") == "slider":
                    current_value = self.selected_indices[option_key]
                    min_val = option_config["min_value"]
                    max_val = option_config["max_value"]
                    
                    # Draw slider bar
                    slider_length = 15
                    slider_x = box_x + 35
                    
                    # Calculate fill percentage
                    fill_ratio = (current_value - min_val) / (max_val - min_val) if max_val > min_val else 0
                    fill_length = int(slider_length * fill_ratio)
                    
                    # Draw the slider background
                    console.print(slider_x, menu_start_y + i, "[" + "-" * slider_length + "]", fg=color.gray)
                    
                    # Draw the filled portion
                    if fill_length > 0:
                        filled_bar = "=" * fill_length
                        console.print(slider_x + 1, menu_start_y + i, filled_bar, 
                                    fg=color.green if i == self.selected_option else color.yellow)
                
                # Show color preview for RGB sliders
                elif option_key in ["color_red", "color_green", "color_blue"]:
                    console.print(
                        box_x + 55,
                        menu_start_y + i,
                        "●",
                        fg=self.character_data['color'],
                    )
        
        # Instructions at bottom of box
        console.print(
            box_x + box_width // 2,
            box_y + box_height - 2,
            "↑/↓: Navigate  ←/→: Change  Enter: Select  Escape: Back",
            fg=color.grey,
            alignment=tcod.CENTER,
        )
    
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[input_handlers.BaseEventHandler]:
        """Handle input for character customization."""
        
        if event.sym == tcod.event.K_ESCAPE:
            return self.parent_menu
            
        elif event.sym in (tcod.event.K_UP, tcod.event.K_KP_8):
            self.selected_option = (self.selected_option - 1) % len(self.menu_options)
            
        elif event.sym in (tcod.event.K_DOWN, tcod.event.K_KP_2):
            self.selected_option = (self.selected_option + 1) % len(self.menu_options)
            
        elif event.sym in (tcod.event.K_LEFT, tcod.event.K_KP_4):
            self._change_option(-1)
            
        elif event.sym in (tcod.event.K_RIGHT, tcod.event.K_KP_6):
            self._change_option(1)
            
        elif event.sym in (tcod.event.K_RETURN, tcod.event.K_KP_ENTER):
            return self._select_option()
            
        return None
    
    def _get_option_key(self, menu_option):
        """Map menu option names to data keys."""
        mapping = {
            "Symbol": "char",
            "Sponsor": "sponsor",
            "Equipment Points": "equipment_points",
            "Skill Points": "skill_points"
        }
        return mapping.get(menu_option)
    
    def _change_option(self, direction: int):
        """Change the selected customization option."""
        current_menu = self.menu_options[self.selected_option]
        option_key = self._get_option_key(current_menu)
        
        if option_key and option_key in CHARACTER_CONFIG["options"]:
            option_config = CHARACTER_CONFIG["options"][option_key]
            
            if option_config.get("type") == "slider":
                # Handle slider values
                current_value = self.selected_indices[option_key]
                min_value = option_config["min_value"]
                max_value = option_config["max_value"]
                
                new_value = current_value + direction
                # Clamp to min/max values
                new_value = max(min_value, min(max_value, new_value))
                
                self.selected_indices[option_key] = new_value
            else:
                # Handle dropdown options
                max_index = len(option_config["values"]) - 1
                self.selected_indices[option_key] = (self.selected_indices[option_key] + direction) % (max_index + 1)
            
            # Update character data
            self.update_character_data(option_key)
    
    def _select_option(self) -> Optional[input_handlers.BaseEventHandler]:
        """Handle selecting a menu option."""
        current_menu = self.menu_options[self.selected_option]
        
        if current_menu == "Name":
            # Open text input for name editing
            return NameInputHandler(self)
            
        elif current_menu == "Start Game":
            # Go to skill selection screen
            return SkillSelectionScreen(self.parent_menu, self.character_data)
            
        elif current_menu == "Back":
            return self.parent_menu
            
        return None


class NameInputHandler(input_handlers.BaseEventHandler):
    """Handle text input for character name."""
    
    def __init__(self, character_screen):
        self.character_screen = character_screen
        self.input_text = character_screen.character_data["name"]
        self.cursor_pos = len(self.input_text)
        self.max_length = 20  # Maximum name length
    
    def on_render(self, console: tcod.Console) -> None:
        """Render the character customization screen with name input overlay."""
        # First render the character screen
        self.character_screen.on_render(console)
        
        # Create input box overlay
        box_width = 40
        box_height = 7
        box_x = (console.width - box_width) // 2
        box_y = (console.height - box_height) // 2
        
        console.draw_frame(
            x=box_x,
            y=box_y,
            width=box_width,
            height=box_height,
            title="Enter Character Name",
            clear=True,
            fg=color.white,
            bg=color.black
        )
        
        # Input field
        input_y = box_y + 3
        console.print(
            box_x + 2,
            input_y - 1,
            "Name:",
            fg=color.white
        )
        
        # Draw input box
        input_box_width = box_width - 4
        for i in range(input_box_width):
            console.print(box_x + 2 + i, input_y, " ", bg=(40, 40, 40))
        
        # Draw text
        display_text = self.input_text
        if len(display_text) > input_box_width - 2:
            # Scroll text if too long
            start_pos = max(0, self.cursor_pos - input_box_width + 3)
            display_text = display_text[start_pos:start_pos + input_box_width - 2]
            cursor_display_pos = self.cursor_pos - start_pos
        else:
            cursor_display_pos = self.cursor_pos
        
        console.print(
            box_x + 3,
            input_y,
            display_text,
            fg=color.white,
            bg=(40, 40, 40)
        )
        
        # Draw cursor
        if cursor_display_pos < input_box_width - 2:
            console.print(
                box_x + 3 + cursor_display_pos,
                input_y,
                "_",
                fg=color.yellow,
                bg=(40, 40, 40)
            )
        
        # Instructions
        console.print(
            box_x + box_width // 2,
            input_y + 2,
            "Enter: Confirm  Escape: Cancel",
            fg=color.menu_text,
            alignment=tcod.CENTER
        )
    
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[input_handlers.BaseEventHandler]:
        """Handle text input."""
        
        if event.sym == tcod.event.K_ESCAPE:
            # Cancel - return to character screen without changes
            return self.character_screen
        
        elif event.sym in (tcod.event.K_RETURN, tcod.event.K_KP_ENTER):
            # Confirm - save name and return to character screen
            if self.input_text.strip():  # Don't allow empty names
                self.character_screen.character_data["name"] = self.input_text.strip()
            return self.character_screen
        
        elif event.sym == tcod.event.K_BACKSPACE:
            # Delete character before cursor
            if self.cursor_pos > 0:
                self.input_text = self.input_text[:self.cursor_pos-1] + self.input_text[self.cursor_pos:]
                self.cursor_pos -= 1
        
        elif event.sym == tcod.event.K_DELETE:
            # Delete character at cursor
            if self.cursor_pos < len(self.input_text):
                self.input_text = self.input_text[:self.cursor_pos] + self.input_text[self.cursor_pos+1:]
        
        elif event.sym == tcod.event.K_LEFT:
            # Move cursor left
            self.cursor_pos = max(0, self.cursor_pos - 1)
        
        elif event.sym == tcod.event.K_RIGHT:
            # Move cursor right
            self.cursor_pos = min(len(self.input_text), self.cursor_pos + 1)
        
        elif event.sym == tcod.event.K_HOME:
            # Move cursor to beginning
            self.cursor_pos = 0
        
        elif event.sym == tcod.event.K_END:
            # Move cursor to end
            self.cursor_pos = len(self.input_text)
        
        else:
            # Try unicode first, then fall back to simple character mapping
            char = None
            if (hasattr(event, 'unicode') and event.unicode and 
                event.unicode.isprintable() and len(event.unicode) == 1):
                char = event.unicode
            else:
                # Simple fallback for common keys
                if event.sym == tcod.event.KeySym.SPACE:
                    char = " "
                elif tcod.event.KeySym.A <= event.sym <= tcod.event.KeySym.Z:
                    # Letters - use shift state for case
                    base_char = chr(ord('a') + (event.sym - tcod.event.KeySym.A))
                    if event.mod & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT):
                        char = base_char.upper()
                    else:
                        char = base_char
                elif hasattr(tcod.event.KeySym, 'N0') and tcod.event.KeySym.N0 <= event.sym <= tcod.event.KeySym.N9:
                    # Numbers
                    char = str(event.sym - tcod.event.KeySym.N0)
                elif event.sym == tcod.event.KeySym.PERIOD:
                    char = "."
                elif event.sym == tcod.event.KeySym.COMMA:
                    char = ","
                elif event.sym == tcod.event.KeySym.MINUS:
                    char = "-"
                elif event.sym == tcod.event.KeySym.SLASH:
                    char = "/"
            
            # Add character if we found one and have room
            if char and len(self.input_text) < self.max_length:
                self.input_text = self.input_text[:self.cursor_pos] + char + self.input_text[self.cursor_pos:]
                self.cursor_pos += 1
        
        
        return None
    
    def ev_textinput(self, event: tcod.event.TextInput) -> Optional[input_handlers.BaseEventHandler]:
        """Handle text input events (better for modern tcod)."""
        if len(self.input_text) < self.max_length:
            # Insert text at cursor position
            self.input_text = self.input_text[:self.cursor_pos] + event.text + self.input_text[self.cursor_pos:]
            self.cursor_pos += len(event.text)
        return None


class SkillSelectionScreen(input_handlers.BaseEventHandler):
    """Handle skill point allocation screen."""
    
    def __init__(self, parent_menu, character_data):
        self.parent_menu = parent_menu
        self.character_data = character_data
        
        # Initialize skill levels (all start at 0)
        self.skill_levels = {}
        for category_key in SKILL_CONFIG["categories"]:
            category = SKILL_CONFIG["categories"][category_key]
            for skill_key in category["skills"]:
                self.skill_levels[skill_key] = 0
        
        self.available_points = self.character_data.get("Skill Points", 0)
        
        # Track which sections are expanded (all start expanded)
        self.expanded_sections = {}
        for category_key in SKILL_CONFIG["layout"]:
            self.expanded_sections[category_key] = True
        
        # Build flattened list for scrolling (headers + skills)
        self.skill_list = []
        self.build_skill_list()
        
        # Start selection on first item (could be header or skill)
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible_items = 15  # How many items to show at once
    
    def build_skill_list(self):
        """Build a flattened list of headers and skills for scrolling."""
        self.skill_list = []
        
        for category_key in SKILL_CONFIG["layout"]:
            category = SKILL_CONFIG["categories"][category_key]
            is_expanded = self.expanded_sections.get(category_key, True)
            
            # Add category header with expand/collapse indicator
            expand_indicator = "▼" if is_expanded else "►"
            self.skill_list.append({
                "type": "header",
                "category_key": category_key,
                "name": f"{expand_indicator} {category['name']}",
                "color": category["color"]
            })
            
            # Add skills in this category only if expanded
            if is_expanded:
                for skill_key in category["skills"]:
                    skill_info = category["skills"][skill_key]
                    self.skill_list.append({
                        "type": "skill",
                        "skill_key": skill_key,
                        "category_key": category_key,
                        "name": skill_info["name"],
                        "description": skill_info["description"],
                        "max_level": skill_info["max_level"],
                        "category_color": category["color"]
                    })
    
    def get_skill_info(self, skill_key):
        """Get skill information from any category."""
        for category_key in SKILL_CONFIG["categories"]:
            category = SKILL_CONFIG["categories"][category_key]
            if skill_key in category["skills"]:
                return category["skills"][skill_key]
        return None
    
    def get_current_item(self):
        """Get the currently selected item."""
        if 0 <= self.selected_index < len(self.skill_list):
            return self.skill_list[self.selected_index]
        return None
    
    def is_skill_selected(self):
        """Check if current selection is a skill (not header)."""
        item = self.get_current_item()
        return item and item["type"] == "skill"
    
    def is_header_selected(self):
        """Check if current selection is a header."""
        item = self.get_current_item()
        return item and item["type"] == "header"
    
    def toggle_section(self, category_key):
        """Toggle the expanded/collapsed state of a section."""
        self.expanded_sections[category_key] = not self.expanded_sections.get(category_key, True)
        # Rebuild the skill list to reflect the change
        old_selected_item = self.get_current_item()
        self.build_skill_list()
        
        # Try to keep selection on the same item
        if old_selected_item and old_selected_item["type"] == "skill":
            # Find the skill in the new list
            for i, item in enumerate(self.skill_list):
                if (item["type"] == "skill" and 
                    item["skill_key"] == old_selected_item["skill_key"]):
                    self.selected_index = i
                    break
            else:
                # If skill not found, move to next available skill
                self.move_to_next_skill()
        elif old_selected_item and old_selected_item["type"] == "header":
            # If we were on a header, find the same header in the new list
            for i, item in enumerate(self.skill_list):
                if (item["type"] == "header" and 
                    item["category_key"] == old_selected_item["category_key"]):
                    self.selected_index = i
                    break
            else:
                # If header not found, move to first header
                self.selected_index = 0
        else:
            # Fallback - ensure we have a valid selection
            if len(self.skill_list) > 0:
                self.selected_index = 0
        
        self.update_scroll()
    
    def has_available_skills(self):
        """Check if there are any skills currently visible (sections expanded)."""
        for item in self.skill_list:
            if item["type"] == "skill":
                return True
        return False
    
    def move_to_next_skill(self):
        """Move selection to the next available skill, or first header if no skills."""
        for i in range(len(self.skill_list)):
            if self.skill_list[i]["type"] == "skill":
                self.selected_index = i
                return
        # If no skills available, go to first header
        self.selected_index = 0
    
    def can_increase_skill(self, skill_key):
        """Check if a skill can be increased."""
        if self.available_points <= 0:
            return False
        skill_info = self.get_skill_info(skill_key)
        if not skill_info:
            return False
        current_level = self.skill_levels.get(skill_key, 0)
        max_level = skill_info.get("max_level", 10)
        return current_level < max_level
    
    def can_decrease_skill(self, skill_key):
        """Check if a skill can be decreased."""
        return self.skill_levels.get(skill_key, 0) > 0
    
    def increase_skill(self, skill_key):
        """Increase a skill level."""
        if self.can_increase_skill(skill_key):
            self.skill_levels[skill_key] = self.skill_levels.get(skill_key, 0) + 1
            self.available_points -= 1
    
    def decrease_skill(self, skill_key):
        """Decrease a skill level."""
        if self.can_decrease_skill(skill_key):
            self.skill_levels[skill_key] -= 1
            self.available_points += 1
    
    def on_render(self, console: tcod.Console) -> None:
        """Render the skill selection screen."""
        console.clear()
        console.draw_semigraphics(background_image, 0, 0)
        
        # Main skill selection box
        box_width = 70
        box_height = 25
        box_x = (console.width - box_width) // 2
        box_y = (console.height - box_height) // 2
        
        console.draw_frame(
            x=box_x,
            y=box_y,
            width=box_width,
            height=box_height,
            title="SKILL SELECTION",
            clear=True,
            fg=color.white,
            bg=color.black
        )
        
        # Available points display
        console.print(
            box_x + box_width // 2,
            box_y + 2,
            f"Available Skill Points: {self.available_points}",
            fg=color.yellow if self.available_points > 0 else color.gray,
            alignment=tcod.CENTER,
        )
        
        # Scrollable skill list
        list_start_y = box_y + 4
        list_height = box_height - 7  # Leave room for title and instructions
        
        # Calculate visible range
        visible_start = self.scroll_offset
        visible_end = min(visible_start + list_height, len(self.skill_list))
        
        # Render visible items
        for i in range(visible_start, visible_end):
            item = self.skill_list[i]
            y_pos = list_start_y + (i - visible_start)
            is_selected = (i == self.selected_index)

            if item["type"] == "header":
                # Category header with selection indicator
                prefix = "► " if is_selected else "  "
                # Section header (no total points displayed here)
                header_text = f"{prefix} {item['name']}"
                header_color = color.green if is_selected else item["color"]
                console.print(
                    box_x + 3,
                    y_pos,
                    header_text,
                    fg=header_color,
                )
                
            elif item["type"] == "skill":
                # Skill entry
                current_level = self.skill_levels.get(item["skill_key"], 0)
                max_level = item["max_level"]
                
                # Selection indicator and skill name
                prefix = "► " if is_selected else "  "
                skill_text = f"{prefix}{item['name']}"
                
                # Level display
                level_text = f"({current_level}/{max_level})"
                
                # Color based on selection and level
                if is_selected:
                    name_color = color.green  # Green reserved for selection only
                else:
                    if current_level >= max_level:
                        name_color = color.yellow  # Maxed skills in yellow instead of green
                    elif current_level > 0:
                        name_color = color.white
                    else:
                        name_color = color.gray
                
                # Print skill name and level
                console.print(box_x + 5, y_pos, skill_text, fg=name_color)
                console.print(box_x + box_width - 15, y_pos, level_text, fg=color.white)
                
                # Progress bar for ALL skills
                bar_length = 10
                # Calculate filled length - ensure we handle the case where current_level is 0
                if max_level > 0:
                    filled_length = int((current_level / max_level) * bar_length)
                else:
                    filled_length = 0
                
                # Create the progress bar using simple characters first
                filled_bars = "#" * filled_length
                empty_bars = "-" * (bar_length - filled_length)
                bar = filled_bars + empty_bars
                
                # Show progress bar for all skills (highlight selected one)
                bar_color = color.green if is_selected else color.gray
                console.print(box_x + box_width - 27, y_pos, f"[{bar}]", fg=bar_color)
        
        # Scroll indicators
        if self.scroll_offset > 0:
            console.print(box_x + box_width - 3, list_start_y, "↑", fg=color.white)
        if visible_end < len(self.skill_list):
            console.print(box_x + box_width - 3, list_start_y + list_height - 1, "↓", fg=color.white)
        
        # Show description of selected skill
        if self.is_skill_selected():
            current_item = self.get_current_item()
            desc_y = box_y + box_height - 4
            console.print(
                box_x + 3,
                desc_y,
                f"Description: {current_item['description'][:60]}",
                fg=color.gray,
            )
            if len(current_item['description']) > 60:
                console.print(
                    box_x + 3,
                    desc_y + 1,
                    current_item['description'][60:120] + ("..." if len(current_item['description']) > 120 else ""),
                    fg=color.gray,
                )
        
        # Instructions
        if self.is_skill_selected():
            instructions = "↑/↓: Navigate  ←/→: Adjust Skill  F: Finish  Escape: Back"
        elif self.is_header_selected():
            instructions = "↑/↓: Navigate  ←/→: Collapse/Expand Section  F: Finish  Escape: Back"
        else:
            instructions = "↑/↓: Navigate  F: Finish  Escape: Back"
        
        console.print(
            box_x + box_width // 2,
            box_y + box_height - 2,
            instructions,
            fg=color.gray,
            alignment=tcod.CENTER,
        )
    
    def update_scroll(self):
        """Update scroll offset to keep selected item visible."""
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.max_visible_items:
            self.scroll_offset = self.selected_index - self.max_visible_items + 1
    
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[input_handlers.BaseEventHandler]:
        """Handle input for skill selection."""
        
        if event.sym == tcod.event.K_ESCAPE:
            return self.parent_menu
            
        elif event.sym == tcod.event.KeySym.F:
            # Finish skill selection and go to game
            return CharacterLoadingScreen(self.parent_menu, self.character_data)
            
        elif event.sym in (tcod.event.K_UP, tcod.event.K_KP_8):
            # Navigate up through all items (headers and skills)
            if self.selected_index > 0:
                self.selected_index -= 1
            self.update_scroll()
                
        elif event.sym in (tcod.event.K_DOWN, tcod.event.K_KP_2):
            # Navigate down through all items (headers and skills)
            if self.selected_index < len(self.skill_list) - 1:
                self.selected_index += 1
            self.update_scroll()
                
        elif event.sym in (tcod.event.K_RIGHT, tcod.event.K_KP_6):
            # Right arrow: Expand section if header selected, increase skill if skill selected
            current_item = self.get_current_item()
            if self.is_header_selected():
                # Expand section if header is selected
                category_key = current_item["category_key"]
                if not self.expanded_sections.get(category_key, True):
                    self.toggle_section(category_key)
            elif self.is_skill_selected():
                # Increase skill if skill is selected
                self.increase_skill(current_item["skill_key"])
                
        elif event.sym in (tcod.event.K_LEFT, tcod.event.K_KP_4):
            # Left arrow: Collapse section if header selected, decrease skill if skill selected
            current_item = self.get_current_item()
            if self.is_header_selected():
                # Collapse section if header is selected
                category_key = current_item["category_key"]
                if self.expanded_sections.get(category_key, True):
                    self.toggle_section(category_key)
            elif self.is_skill_selected():
                # Decrease skill if skill is selected
                self.decrease_skill(current_item["skill_key"])
        
        return None


class CharacterLoadingScreen(LoadingScreen):
    """Loading screen that uses custom character data."""
    
    def __init__(self, parent_menu, character_data):
        super().__init__(parent_menu)
        self.character_data = character_data
        
    def generate_world_with_steps(self):
        """Generate the world with custom character data."""
        import time
        
        try:
            # Step 1: Initializing
            self.current_step = 0
            time.sleep(0.3)
            
            # Step 2: Creating terrain
            self.current_step = 1
            time.sleep(0.3)
            
            # Step 3: Generate buildings (this is where most of the work happens)
            self.current_step = 2
            
            # Start actual generation with custom character
            self.engine = self.new_game_with_custom_character()
            
            # Step 4: Doors and entrances (already done in new_game)
            self.current_step = 3
            time.sleep(0.3)
            
            # Step 5: Campfires (already done)
            self.current_step = 4
            time.sleep(0.3)
            
            # Step 6: Villagers (already done)
            self.current_step = 5
            time.sleep(0.3)
            
            # Step 7: Finalizing
            self.current_step = 6
            time.sleep(0.3)
            
            # Step 8: Complete
            self.current_step = 7
            self.generation_complete = True
            
            # Wait a moment to show completion, then auto-transition
            time.sleep(0.8)
            
        except Exception as e:
            # If generation fails
            self.current_step = len(self.generation_steps)
            self.generation_complete = True
            self.engine = None
            print(f"Generation failed: {e}")
            import traceback
            traceback.print_exc()
            
    def new_game_with_custom_character(self) -> Engine:
        """Create a new game with custom character data."""
        map_width = 80
        map_height = 40

        room_max_size = 10
        room_min_size = 6
        max_rooms = 30

        # Create custom player
        player = copy.deepcopy(entity_factories.player)
        player.char = self.character_data["char"]
        player.color = self.character_data["color"]
        player.name = self.character_data["name"]
        
        # Apply custom stats to the fighter component
        player.fighter.max_hp = self.character_data["health_points"]
        player.fighter._hp = self.character_data["health_points"]  # Set current HP to max HP
        player.fighter.base_power = self.character_data["attack_power"]
        player.fighter.base_defense = self.character_data["defense"]

        engine = Engine(player=player)

        engine.game_world = GameWorld(
            engine=engine,
            max_rooms=max_rooms,
            room_min_size=room_min_size,
            room_max_size=room_max_size,
            map_width=map_width,
            map_height=map_height,
        )

        engine.game_world.generate_floor()
        engine.update_fov()

        engine.message_log.add_message(
            f"Hello {self.character_data['name']}, welcome to the world!", color.welcome_text
        )

        return engine


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
            "oxenfree\n2026\nVersion 0.18.1 Beta",
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
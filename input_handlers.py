from __future__ import annotations

import os
from typing import Callable, Tuple, Optional, TYPE_CHECKING, Union

import tcod.event
import random
import traceback

import actions
from actions import (
    Action,
    BumpAction,
    PickupAction,
    WaitAction,
    InteractAction,
)

import color
from dialogue_generator import ConversationNode
import engine
import exceptions
from render_functions import MenuRenderer

from text_utils import *
from text_engine import TextEngine
import sounds


if TYPE_CHECKING:
    from engine import Engine
    from entity import Item, Actor
    from components.container import Container


MOVE_KEYS = {
    # Arrow keys.
    tcod.event.KeySym.UP: (0, -1),
    tcod.event.KeySym.DOWN: (0, 1),
    tcod.event.KeySym.LEFT: (-1, 0),
    tcod.event.KeySym.RIGHT: (1, 0),
    tcod.event.KeySym.HOME: (-1, -1),
    tcod.event.KeySym.END: (-1, 1),
    tcod.event.KeySym.PAGEUP: (1, -1),
    tcod.event.KeySym.PAGEDOWN: (1, 1),
    # Numpad keys.
    tcod.event.KeySym.KP_1: (-1, 1),
    tcod.event.KeySym.KP_2: (0, 1),
    tcod.event.KeySym.KP_3: (1, 1),
    tcod.event.KeySym.KP_4: (-1, 0),
    tcod.event.KeySym.KP_6: (1, 0),
    tcod.event.KeySym.KP_7: (-1, -1),
    tcod.event.KeySym.KP_8: (0, -1),
    tcod.event.KeySym.KP_9: (1, -1),
}

WAIT_KEYS = {
    tcod.event.KeySym.PERIOD,
    tcod.event.KeySym.KP_5,
    tcod.event.KeySym.CLEAR,
}

CONFIRM_KEYS = {
    tcod.event.KeySym.RETURN,
    tcod.event.KeySym.KP_ENTER,
    tcod.event.KeySym.SPACE,
    tcod.event.KeySym.RIGHT,
}


ActionOrHandler = Union[Action, "BaseEventHandler"]
#An event handler return value which can trigger an action or switch active handlers.

# If a handler is returned then it will become the active handler for future events.
# If an action is returned it will be attempted and if it's valid then
# MainGameEventHandler will become the active handler.

class BaseEventHandler(tcod.event.EventDispatch[ActionOrHandler]):
    def handle_events(self, event: tcod.event.Event) -> BaseEventHandler:
        # handles events and returns next active handler
        state = self.dispatch(event)
        if isinstance(state, BaseEventHandler):
            return state
        assert not isinstance(state, Action), f"{self!r} can not handle actions."
        return self
    
    def on_render(self, console: tcod.Console) -> None:
        raise NotImplementedError()
    
    def ev_quit(self, event: tcod.event.Quit) -> Optional[Action]:
        raise SystemExit()


    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[BaseEventHandler]:
        """Any key returns to the parent handler."""
        return self.parent


class EventHandler(BaseEventHandler):
    def __init__(self, engine: Engine):
        self.engine = engine
        # Initialize turn manager if not already set
        if not hasattr(engine, 'turn_manager') or engine.turn_manager is None:
            from turn_manager import TurnManager
            engine.turn_manager = TurnManager(engine)

    def handle_events(self, event: tcod.event.Event) -> BaseEventHandler:
        # handles events for input handlers with an engine
        action_or_state = self.dispatch(event)
        if isinstance(action_or_state, BaseEventHandler):
            return action_or_state
        
        # Handle fast enemy turns before processing valid player actions
        if action_or_state is not None:
            handler_change = self.engine.turn_manager.process_pre_player_turn()
            if handler_change:
                return handler_change
        
        handled = self.handle_action(action_or_state)
        # If an action returned a handler, switch to it directly.
        if isinstance(handled, BaseEventHandler):
            return handled
        if handled:
            # Valid action - use centralized turn manager for all post-action processing
            handler_change = self.engine.turn_manager.process_player_turn_end()
            if handler_change:
                return handler_change

            return MainGameEventHandler(self.engine) # Return to main handler
        
        return self

    def handle_action(self, action: Optional[Action]) -> Union[bool, BaseEventHandler]:
        
        # Handles actions returned from event methods
        #Returns true is action will advance a turn
        if action is None:
            return False
        try:
            result = action.perform()
        except exceptions.Impossible as exc:
            self.engine.message_log.add_message(exc.args[0], color.impossible)
            return False #skip enemy turn
        # If an action returns a handler, switch without advancing the turn.
        if isinstance(result, BaseEventHandler):
            return result
        
        # Turn advancement is now handled by the turn manager
        return True

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> None:
        if self.engine.game_map.in_bounds(event.position.x, event.position.y):
            self.engine.mouse_location = event.position.x, event.position.y
    
    def on_render(self, console: tcod.Console) -> None:
        self.engine.render(console)
    
class AskUserEventHandler(EventHandler):
    # Handles user input for actions with special input
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        
        # any key exits this handler
        if event.sym in {  # Ignore modifier keys.
            tcod.event.K_LSHIFT,
            tcod.event.K_RSHIFT,
            tcod.event.K_LCTRL,
            tcod.event.K_RCTRL,
            tcod.event.K_LALT,
            tcod.event.K_RALT,
        }:
            return None
        return self.on_exit()
    def ev_mousebuttondown(
        self, event: tcod.event.MouseButtonDown
    ) -> Optional[ActionOrHandler]:
        """By default any mouse click exits this input handler."""
        return self.on_exit()
    
    def on_exit(self) -> Optional[ActionOrHandler]:
        # user is cancelling action
        return MainGameEventHandler(self.engine)


class CharacterScreenEventHandler(EventHandler):
    TITLE = "Character Sheet"

    def __init__(self, engine):
        super().__init__(engine)
        # Collapsible sections state (kept for future use). Sections removed per request.
        self.collapsed_sections = set()
        



class DialogueEventHandler(AskUserEventHandler):
    """Handles dialogue interactions with NPCs with hierarchical menu system."""
    
    def __init__(self, engine: Engine, npc: Actor):
        super().__init__(engine)
        self.npc = npc
        # Initialize dialogue system
        from dialogue_generator import ConversationNode
        self.dialogue = ConversationNode()
        
        # Menu system
        self.current_menu = "main"
        if npc.is_known:
            knows_name = npc.name
        else:
            knows_name = npc.unknown_name
        self.selected_index = 0
        self.menu_structure = {
            "main": {
                "title": f"Talking to {knows_name}",
                "options": [
                    {"text": "Hello", "action": "dialogue", "context": ["Greeting"]},
                    {"text": "Questions", "action": "submenu", "target": "questions"},
                    {"text": "Farewell", "action": "dialogue", "context": ["Goodbye"]},
                    {"text": "[Exit]", "action": "exit"}
                ]
            },
            "questions": {
                "title": "Questions",
                "options": [
                    {"text": "Where are we?", "action": "dialogue", "context": ["Location"]},
                    {"text": "What are you called?", "action": "dialogue", "context": ["Identity"]},
                    {"text": "What do you know?", "action": "dialogue", "context": ["Knowledge"]},
                    {"text": "[Back]", "action": "submenu", "target": "main"}
                ]
            }
        }

        
        # Generate initial dialogue text
        self.current_dialogue = self.dialogue.generate_dialogue(character=self.npc, context=self.npc.dialogue_context)
        print(self.npc.dialogue_context)
        if "Identity" in self.npc.dialogue_context:
            print("KNOWN")
            self.npc.is_known = True
            # Increase opinion when identity is known
            self.npc.opinion += 10

        # Safety check
        if self.current_dialogue is None:
            self.current_dialogue = ("Hello there.", ["Greeting"])
        if len(self.current_dialogue) < 2:
            self.current_dialogue = ("Hello there.", ["Greeting"])
            
        display_name = self.npc.name if self.npc.is_known else self.npc.unknown_name
        self.engine.message_log.add_message(f"{display_name}: {self.current_dialogue[0]}", color.blue)
        if isinstance(self.current_dialogue[1], str):
            self.npc.dialogue_context = [self.current_dialogue[1]]
        else:
            self.npc.dialogue_context = self.current_dialogue[1]

    def update_menu_title(self):
        """Update the main menu title when NPC becomes known."""
        knows_name = self.npc.name if self.npc.is_known else self.npc.unknown_name
        self.menu_structure["main"]["title"] = f"Talking to {knows_name}"
    
    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)
        
        # Draw the dialogue box
        width = 65
        height = 20
        x = (self.engine.game_map.width - width) // 2
        y = (self.engine.game_map.height - height) // 2

        current_menu_data = self.menu_structure[self.current_menu]
        
        # Draw parchment background and ornate border
        MenuRenderer.draw_parchment_background(console, x, y, width, height)
        MenuRenderer.draw_ornate_border(console, x, y, width, height, current_menu_data["title"])
        
        # Display current dialogue if available
        if hasattr(self, 'current_dialogue') and self.current_dialogue:
            console.print(x + 2, y + 2, self.current_dialogue[0], fg=color.teal)
        
        # Display menu options in inventory-style format
        start_y = y + 5
        options = current_menu_data["options"]
        
        for i, option in enumerate(options):
            option_y = start_y + i
            if option_y >= y + height - 3:  # Leave room for instructions
                break
            
            # Generate letter key for this option
            item_key = chr(ord("a") + i)
            option_text = f"({item_key}) {option['text']}"
            
            # Draw selection marker for arrow navigation (like inventory)
            marker = ">" if i == self.selected_index else " "
            
            # Highlight selected option with white background and black text
            if i == self.selected_index:
                # Draw white background for the entire line
                line_width = len(marker + option_text) + 2  # Extra space for padding
                for j in range(line_width):
                    console.print(x + 1 + j, option_y, " ", fg=color.black, bg=color.white)
                # Draw the text on top with black text
                console.print(x + 1, option_y, marker, fg=color.black, bg=color.white)
                console.print(x + 2, option_y, option_text, fg=color.black, bg=color.white)
            else:
                console.print(x + 1, option_y, marker)
                console.print(x + 2, option_y, option_text, fg=color.white)
        
        # Instructions
        instructions_y = y + height - 3
        console.print(x + 2, instructions_y, "↑↓: Navigate  Enter: Select  Esc: Exit", fg=color.grey)

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        sounds.play_ui_move_sound()
        current_menu_data = self.menu_structure[self.current_menu]
        options = current_menu_data["options"]
        key = event.sym
        
        # Arrow key navigation (like inventory)
        if key == tcod.event.KeySym.UP:
            self.selected_index = max(0, self.selected_index - 1)
            return None
        elif key == tcod.event.KeySym.DOWN:
            self.selected_index = min(len(options) - 1 if options else 0, self.selected_index + 1)
            return None
            
        # Enter key to select option (Return, enter, space, or right key)
        elif key == tcod.event.KeySym.RETURN or key == tcod.event.KeySym.KP_ENTER or key == tcod.event.KeySym.SPACE or key == tcod.event.KeySym.RIGHT:
            if len(options) == 0:
                return None
            return self.handle_menu_selection()
            
        # Letter selection (like inventory system)
        index = key - tcod.event.KeySym.A
        if 0 <= index < len(options):
            self.selected_index = index
            return self.handle_menu_selection()
    
                
        # Escape to exits current menu, or back to main event
        elif key == tcod.event.KeySym.ESCAPE:
            return MainGameEventHandler(self.engine)
        
        return None
        
        return None
    
    def handle_menu_selection(self) -> Optional[ActionOrHandler]:
        """Handle the selected menu option."""
        current_menu_data = self.menu_structure[self.current_menu]
        options = current_menu_data["options"]
        
        if self.selected_index >= len(options):
            return None
            
        selected_option = options[self.selected_index]
        action = selected_option["action"]
        
        if action == "exit":
            self.npc.dialogue_context = ["Goodbye"]
            return MainGameEventHandler(self.engine)
            
        elif action == "submenu":
            # Navigate to submenu
            target_menu = selected_option["target"]
            if target_menu in self.menu_structure:
                self.current_menu = target_menu
                self.selected_index = 0  # Reset selection in new menu
            return None
            
        elif action == "dialogue":
            # Execute dialogue with given context
            context = selected_option.get("context", [])
            self.npc.dialogue_context = context
            self.current_dialogue = self.dialogue.generate_dialogue(
                character=self.npc, context=context
            )
            
            # Safety check
            if self.current_dialogue is None:
                self.current_dialogue = ("I have nothing to say about that.", ["Default"])
            if len(self.current_dialogue) < 2:
                self.current_dialogue = ("I have nothing to say about that.", ["Default"])
                
            display_name = self.npc.name if self.npc.is_known else self.npc.unknown_name
            self.engine.message_log.add_message(f"{display_name}: {self.current_dialogue[0]}", color.blue)
            
            # Update dialogue context
            if isinstance(self.current_dialogue[1], str):
                self.npc.dialogue_context = [self.current_dialogue[1]]
            else:
                self.npc.dialogue_context = self.current_dialogue[1]
            
            # Check if this was an identity dialogue and update menu title if NPC becomes known
            if "Identity" in context:
                self.npc.is_known = True
                self.update_menu_title()
            
            return None
        
        return None


class LevelUpEventHandler(AskUserEventHandler):
    TITLE = "Level Up!"

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)

        # Center the menu on the screen
        width = 50
        height = 12
        x = (console.width - width) // 2
        y = (console.height - height) // 2

        # Draw parchment background and ornate border
        MenuRenderer.draw_parchment_background(console, x, y, width, height)
        MenuRenderer.draw_ornate_border(console, x, y, width, height, self.TITLE)

        # Content positioning
        content_x = x + 2
        content_y = y + 2

        console.print(x=content_x, y=content_y, string="You have grown stronger.", fg=(255, 223, 127))
        console.print(x=content_x, y=content_y + 1, string="Pick an attribute to increase:", fg=(200, 180, 140))

        # Option list
        console.print(
            x=content_x + 2,
            y=content_y + 4,
            string=f"a) Constitution (+20 HP from {self.engine.player.fighter.max_hp})",
            fg=(220, 200, 160)
        )
        console.print(
            x=content_x + 2,
            y=content_y + 6,
            string=f"b) Strength (+1 attack, from {self.engine.player.fighter.power})",
            fg=(220, 200, 160)
        )
        console.print(
            x=content_x + 2,
            y=content_y + 8,
            string=f"c) Agility (+1 defense, from {self.engine.player.fighter.defense})",
            fg=(220, 200, 160)
        )

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        sounds.play_ui_move_sound()
        player = self.engine.player
        key = event.sym
        index = key - tcod.event.KeySym.A

        if 0 <= index <= 2:
            if index == 0:
                player.level.increase_max_hp()
            elif index == 1:
                player.level.increase_power()
            else:
                player.level.increase_defense()

        else:
            self.engine.message_log.add_message("Invalid Entry.", color.invalid)

            return None
        return super().ev_keydown(event)
    
    def ev_mousebuttondown(
            self, event: tcod.event.MouseButtonDown
    ) -> Optional[ActionOrHandler]:
        # Don't allow player to click to exit
        return None
class ContainerEventHandler(AskUserEventHandler):
    # Handler displays both inventories and allows transferring items
    def __init__(self, engine: Engine, container: Container):
        super().__init__(engine)
        # Innit container being interacted with
        self.container = container
        # Skip filter, not needed

        # Selected index for arrow navigation
        self.selected_index: int = 0
        # Which inventory is active: "Player" or "Container"
        self.menu: str = "Player"

    def on_render(self, console: tcod.Console) -> None:
        # Renders inventory menu displaying items in both inventories with fantasy styling
        super().on_render(console)
        player_groups = self.engine.player.inventory.get_display_groups()
        container_items = list(self.container.items)
        number_of_player_items = len(player_groups)
        number_of_container_items = len(container_items)

        # Enhanced window sizing for beautiful layout
        total_width = 70
        height = max(number_of_player_items, number_of_container_items) + 12
        if height < 18:
            height = 18
        
        # Position window
        x = (console.width - total_width) // 2
        y = 1

        # Draw main fantasy parchment background
        self._draw_parchment_background(console, x, y, total_width, height)
        
        # Draw ornate main border
        container_name = getattr(self.container.parent, 'name', 'Container')
        is_corpse = getattr(self.container.parent, 'type', None) == 'Dead'
        title = f"Corpse" if is_corpse else f"Container: {container_name}"
        self._draw_ornate_border(console, x, y, total_width, height, title)

        # Calculate panel dimensions
        panel_width = (total_width - 6) // 2  # Leave space for divider and margins
        panel_height = height - 6
        
        # Left panel (Player inventory)
        left_x = x + 3
        left_y = y + 3
        
        # Right panel (Container inventory) 
        right_x = x + 3 + panel_width + 2
        right_y = y + 3
        
        # Draw panel backgrounds
        panel_bg = (40, 30, 22)
        for px in range(panel_width):
            for py in range(panel_height):
                console.print(left_x + px, left_y + py, " ", bg=panel_bg)
                console.print(right_x + px, right_y + py, " ", bg=panel_bg)
        
        # Draw decorative divider between panels
        divider_x = left_x + panel_width + 1
        self._draw_decorative_divider(console, divider_x, left_y, panel_height)
        
        # Panel headers
        player_header = "✦ Your Inventory ✦"
        container_header = f"✦ Corpse ✦" if is_corpse else f"✦ {container_name} ✦"
        
        # Center headers in panels
        player_header_x = left_x + (panel_width - len(player_header)) // 2
        container_header_x = right_x + (panel_width - len(container_header)) // 2
        
        console.print(player_header_x, left_y + 1, player_header, fg=(255, 215, 0), bg=panel_bg)
        console.print(container_header_x, right_y + 1, container_header, fg=(255, 215, 0), bg=panel_bg)
        
        # Active panel indicator
        if self.menu == "Player":
            console.print(left_x + 1, left_y + 1, "◆", fg=(255, 215, 0), bg=panel_bg)
        else:
            console.print(right_x + 1, right_y + 1, "◆", fg=(255, 215, 0), bg=panel_bg)

        # Ensure index is selected
        if not hasattr(self, "selected_index"):
            self.selected_index = 0
        # Clamp selected index based on active menu
        if number_of_player_items > 0 and self.menu == "Player":
            if self.selected_index >= number_of_player_items:
                self.selected_index = max(0, number_of_player_items - 1)

        if number_of_container_items > 0 and self.menu == "Container":
            if self.selected_index >= number_of_container_items:
                self.selected_index = max(0, number_of_container_items - 1)

        # Draw player inventory items
        item_start_y = left_y + 3
        if number_of_player_items > 0:
            for i, group in enumerate(player_groups):
                if item_start_y + i >= left_y + panel_height - 1:
                    break  # Don't draw outside panel
                    
                item_key = chr(ord("a") + i)
                item = group['item']
                display_name = group['display_name']
                is_equipped = self.engine.player.equipment.item_is_equipped(item)
                is_selected = i == self.selected_index and self.menu == "Player"

                item_string = f"{item_key}) {display_name}"
                if is_equipped:
                    item_string = f"{item_string} (e)"

                # Draw with selection highlighting
                if is_selected:
                    # Selection background
                    for hx in range(panel_width - 4):
                        console.print(left_x + 2 + hx, item_start_y + i, " ", bg=(80, 60, 30))
                    console.print(left_x + 2, item_start_y + i, "✦", fg=(255, 223, 127), bg=(80, 60, 30))
                    console.print(left_x + 4, item_start_y + i, item_string, fg=item.rarity_color, bg=(80, 60, 30))
                else:
                    console.print(left_x + 4, item_start_y + i, item_string, fg=item.rarity_color, bg=panel_bg)
        else:
            console.print(left_x + 4, item_start_y, "~ Empty ~", fg=(120, 100, 80), bg=panel_bg)

        # Draw container inventory items  
        if number_of_container_items > 0:
            for i, item in enumerate(container_items):
                if item_start_y + i >= right_y + panel_height - 1:
                    break  # Don't draw outside panel
                    
                item_key = chr(ord("a") + i)
                is_selected = i == self.selected_index and self.menu == "Container"
                item_string = f"{item_key}) {item.name}"

                # Draw with selection highlighting
                if is_selected:
                    # Selection background
                    for hx in range(panel_width - 4):
                        console.print(right_x + 2 + hx, item_start_y + i, " ", bg=(80, 60, 30))
                    console.print(right_x + 2, item_start_y + i, "✦", fg=(255, 223, 127), bg=(80, 60, 30))
                    console.print(right_x + 4, item_start_y + i, item_string, fg=item.rarity_color, bg=(80, 60, 30))
                else:
                    console.print(right_x + 4, item_start_y + i, item_string, fg=item.rarity_color, bg=panel_bg)
        else:
            console.print(right_x + 4, item_start_y, "~ Empty ~", fg=(120, 100, 80), bg=panel_bg)
        
        # Instructions footer
        instructions = "✦ [Tab] Switch Panel · [↑↓] Navigate · [Enter] Transfer · [Esc] Close ✦"
        inst_x = x + (total_width - len(instructions)) // 2
        console.print(inst_x, y + height - 2, instructions, fg=(180, 140, 100))

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        player = self.engine.player
        key = event.sym
        modifier = event.mod

        # Get display groups for selection
        player_groups = self.engine.player.inventory.get_display_groups()

        # Skip filter

        # Tab shifts active menu
        if key == tcod.event.K_TAB:
            self.menu = "Container" if self.menu == "Player" else "Player"
            return None

        # Arrow-key navigation: up/down to move selection, Enter to confirm
        if key == tcod.event.K_UP:
            # Check if selection is in bounds, then play UI sound
            if self.selected_index > 0:
                sounds.play_ui_move_sound()
            self.selected_index = max(0, self.selected_index - 1)
            return None
        elif key == tcod.event.K_DOWN:
            
            if self.menu == "Player":
                max_index = max(0, len(player_groups) - 1)
            else:
                max_index = max(0, len(self.container.items) - 1)
            # Check if selection is in bounds, then play UI sound
            if self.selected_index < max_index:
                sounds.play_ui_move_sound()
            self.selected_index = min(max_index, self.selected_index + 1)
            return None
        elif key in CONFIRM_KEYS:
            # Confirm selection from the active menu
            if self.menu == "Player":
                if not player_groups:
                    return None
                selected_group = player_groups[self.selected_index]
                return self.on_item_selected(selected_group['item'])
            else:
                if not self.container.items:
                    return None
                return self.on_item_selected(self.container.items[self.selected_index])
    
        # Letter selection still supported but operates on the filtered list
        index = key - tcod.event.KeySym.A

        if 0 <= index <= 26:
            try:
                if self.menu == "Player":
                    selected_group = player_groups[index]
                    selected_item = selected_group['item']
                else:
                    selected_item = self.container.items[index]
            except IndexError:
                self.engine.message_log.add_message("Invalid entry.", color.invalid)
                return None
            return self.on_item_selected(selected_item)
        return super().ev_keydown(event)
    
    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        # Transfer this item between inventories
        if self.menu == "Player":
            # Transfer from player to container
            try:
                # Check if equipped
                if self.engine.player.equipment.item_is_equipped(item):
                    # Get slot item is in
                    slot = self.engine.player.equipment.get_slot(item)
                    self.engine.player.equipment.unequip_item(item, add_message=True)
                    

                # Check container capacity
                if len(self.container.items) >= self.container.capacity:
                    self.engine.message_log.add_message("Container is full.", color.error)
                    return self

                self.engine.player.inventory.items.remove(item)
                # Move item into the container and update its parent so
                # later logic (consumption, transfers) sees the correct owner.
                self.container.items.append(item)
                print(f"DEBUG: Inventory = {[item.name for item in self.engine.player.inventory.items]}")
                try:
                    item.parent = self.container
                except Exception:
                    pass

                if hasattr(item, "drop_sound") and item.drop_sound is not None:
                    try:
                        item.drop_sound()
                    except Exception as e:
                        print(f"DEBUG: Error calling drop sound: {e}")
                
                self.engine.message_log.add_message(f"You transfer the {item.name}.")
            except Exception as e:
                print(f"DEBUG: Transfer failed with exception: {e}")
                print(traceback.format_exc())
                self.engine.message_log.add_message(f"Could not transfer {item.name}.", color.error)
        else:
            # Transfer from container to player
            try:
                self.container.items.remove(item)
                if len(self.engine.player.inventory.items) > self.engine.player.inventory.capacity:
                    self.engine.message_log.add_message("Your inventory is full.", color.error)
                    # Return item to container
                    self.container.items.append(item)
                else:
                    if "coin" in item.name.lower():
                        # Auto-convert coins to player gold
                        self.engine.player.gold += item.value
                        self.engine.message_log.add_message(f"You pick up some coins.")

                        # Play coin pickup sound if it exists
                        if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                            try:
                                item.pickup_sound()
                            except Exception as e:
                                print(f"DEBUG: Error calling pickup sound: {e}")
                        return self
                    # Add to player inventory and update parent link.
                    self.engine.player.inventory.items.append(item)
                    try:
                        item.parent = self.engine.player.inventory
                    except Exception:
                        pass
                    
                    # Play item pickup sound if it exists
                    if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                        #print(f"DEBUG: About to call pickup sound for {item.name}")
                        try:
                            item.pickup_sound()
                            #print(f"DEBUG: Successfully called pickup sound for {item.name}")
                        except Exception as e:
                            print(f"DEBUG: Error calling pickup sound: {e}")
                    else:
                        print(f"DEBUG: No pickup sound for {item}")

                    self.engine.message_log.add_message(f"You take the {item.name}.")
            except Exception:
                print(traceback.format_exc(), color.error)
                self.engine.message_log.add_message(f"Could not transfer {item.name} to {self.container.name}.", color.error)
        # Return back to container handler
        return self

    def _draw_parchment_background(self, console, x: int, y: int, width: int, height: int):
        """Draw a beautiful parchment-like background."""
        # Rich parchment color gradient
        base_bg = (45, 35, 25)      # Base parchment
        light_bg = (50, 38, 28)     # Slightly lighter
        
        for py in range(height):
            for px in range(width):
                # Create subtle texture variation
                bg_color = light_bg if (px + py) % 3 == 0 else base_bg
                console.print(x + px, y + py, " ", bg=bg_color)

    def _draw_ornate_border(self, console, x: int, y: int, width: int, height: int, title: str):
        """Draw a smooth fantasy border with decorative elements."""
        # Elegant color scheme
        border_fg = (139, 105, 60)     # Rich bronze
        accent_fg = (205, 164, 87)     # Bright gold
        title_fg = (255, 215, 0)       # Pure gold
        bg = (35, 25, 18)              # Dark background for border
        
        # Simple, smooth corners and borders
        # Top border
        console.print(x, y, "╔", fg=accent_fg, bg=bg)
        for i in range(1, width - 1):
            console.print(x + i, y, "═", fg=border_fg, bg=bg)
        console.print(x + width - 1, y, "╗", fg=accent_fg, bg=bg)
        
        # Bottom border
        console.print(x, y + height - 1, "╚", fg=accent_fg, bg=bg)
        for i in range(1, width - 1):
            console.print(x + i, y + height - 1, "═", fg=border_fg, bg=bg)
        console.print(x + width - 1, y + height - 1, "╝", fg=accent_fg, bg=bg)
        
        # Side borders - smooth
        for i in range(1, height - 1):
            console.print(x, y + i, "║", fg=border_fg, bg=bg)
            console.print(x + width - 1, y + i, "║", fg=border_fg, bg=bg)
        
        # Clean title
        title_decorated = f"✦ {title} ✦"
        title_start = x + (width - len(title_decorated)) // 2
        # Clear title area
        for tx in range(len(title_decorated)):
            console.print(title_start + tx, y, " ", bg=bg)
        console.print(title_start, y, title_decorated, fg=title_fg, bg=bg)

    def _draw_decorative_divider(self, console, x: int, y: int, height: int):
        """Draw a smooth decorative vertical divider."""
        divider_fg = (139, 105, 60)  # Bronze
        accent_fg = (205, 164, 87)   # Gold accent
        bg = (40, 30, 22)            # Slightly lighter than parchment
        
        for dy in range(height):
            console.print(x, y + dy, " ", bg=bg)
            
            if dy == 0:
                console.print(x, y + dy, "╦", fg=accent_fg, bg=bg)
            elif dy == height - 1:
                console.print(x, y + dy, "╩", fg=accent_fg, bg=bg)
            else:
                console.print(x, y + dy, "│", fg=divider_fg, bg=bg)

class InventoryEventHandler(AskUserEventHandler):
    """This handler lets the user select an item.

    What happens then depends on the subclass.
    """

    TITLE = "<missing title>"

    def __init__(self, engine: Engine, item_filter: Optional[Callable] = None):
        super().__init__(engine)
        # item_filter should accept an Item and return True if it should be shown
        self.item_filter: Callable = item_filter if item_filter is not None else (lambda i: True)
        # selected index for arrow navigation
        self.selected_index: int = 0
        # category tabs
        self.current_category: int = 0
        self.categories = [
            ("All", self._filter_all),
            ("Equipment", self._filter_equipment), 
            ("Consumables", self._filter_consumables),
            ("Misc", self._filter_misc)
        ]

    def on_render(self, console: tcod.Console) -> None:
        """Render a beautiful fantasy-themed inventory with atmospheric styling."""
        super().on_render(console)
        
        # Build filtered list according to filter function and current category
        item_groups = self.engine.player.inventory.get_display_groups()
        category_filter = self.categories[self.current_category][1]
        filtered_groups = []
        for group in item_groups:
            if self.item_filter(group['item']) and category_filter(group['item']):
                filtered_groups.append(group)
        
        number_of_items_in_inventory = len(filtered_groups)

        # Enhanced window sizing for beautiful layout
        sidebar_width = 14  # Category sidebar
        items_width = 32    # Item list area  
        preview_width = 22  # Preview area
        total_width = sidebar_width + items_width + preview_width + 4  # +4 for decorative spacing
        height = max(18, number_of_items_in_inventory + 8)  # More generous spacing

        # Position based on player location
        if self.engine.player.x <= 30:
            x = 3
        else:
            x = max(0, console.width - total_width - 3)
        y = 1

        # Draw main fantasy parchment background
        MenuRenderer.draw_parchment_background(console, x, y, total_width, height)
        
        # Draw ornate main border
        MenuRenderer.draw_ornate_border(console, x, y, total_width, height, self.TITLE)
        
        # Draw illuminated category sidebar
        self._draw_illuminated_sidebar(console, x+1, y + 3, sidebar_width - 2, height - 6)
        
        # Draw decorative dividers
        items_x = x + sidebar_width + 1
        preview_x = x + sidebar_width + items_width + 2
        self._draw_decorative_divider(console, items_x - 1, y + 2, height - 4)
        self._draw_decorative_divider(console, preview_x - 1, y + 2, height - 4)

        # Ensure we have a selected index for arrow-key navigation
        if not hasattr(self, "selected_index"):
            self.selected_index = 0

        current_y = y + 4  # Start with more spacing
        
        # Render inventory items with elegant styling
        if number_of_items_in_inventory > 0:
            # Clamp selected index to the filtered list
            if self.selected_index >= number_of_items_in_inventory:
                self.selected_index = max(0, number_of_items_in_inventory - 1)

            for i, group in enumerate(filtered_groups):
                if current_y >= y + height - 3:
                    break  # Don't draw outside the frame
                    
                item_key = chr(ord("a") + i)
                item = group['item']
                display_name = group['display_name']
                is_equipped = self.engine.player.equipment.item_is_equipped(item)
                is_selected = i == self.selected_index

                # Create elegant item string 
                item_type_char = self._get_item_type_char(item)
                item_string = f"{item_key}]{item_type_char}{display_name}"
                
                if is_equipped:
                    item_string = f"{item_string} (e)"  # (e) for equipped

                # Draw with beautiful highlighting
                if is_selected:
                    # Elegant selection background with gradient effect
                    self._draw_selection_highlight(console, items_x, current_y, items_width - 2)
                    console.print(items_x + 1, current_y, "✦", fg=(255, 223, 127), bg=(80, 60, 30))  # Beautiful star
                    console.print(items_x + 2, current_y, item_string, fg=item.rarity_color, bg=(80, 60, 30))
                else:
                    console.print(items_x + 1, current_y, item_string, fg=item.rarity_color)
                
                current_y += 1

            # Draw selected item preview with ornate styling
            selected_group = filtered_groups[self.selected_index]
            selected_item = selected_group['item']
            self._draw_ornate_preview(console, preview_x, y + 3, preview_width - 1, height - 6, selected_item)
            
        else:
            console.print(items_x + 2, current_y, "~ Your pack is empty ~", fg=(120, 100, 80))
            # Draw empty preview panel with mystical styling
            console.print(preview_x + 4, y + 8, "~ No item selected ~", fg=(120, 100, 80))
        
        # Draw elegant instruction footer
        instructions = "✦ [↑↓] Navigate · [←→] Category · [Enter] Select · [Esc] Return ✦"
        inst_x = x + (total_width - len(instructions)) // 2
        console.print(inst_x, y + height - 2, instructions, fg=(180, 140, 100))
    
    def _draw_illuminated_sidebar(self, console, x: int, y: int, width: int, height: int):
        """Draw an illuminated manuscript-style category sidebar."""
        category_icons = {
            'All': '',      # 8-pointed star
            'Equipment': '', # Crossed swords  
            'Consumables': '', # Hot beverage (potion-like)
            'Misc': ''      # Diamond with dot
        }
        
        active_colors = {
            'bg': (65, 35, 20),
            'fg': (255, 223, 127),
            'icon': (255, 215, 0)
        }
        
        inactive_colors = {
            'bg': (45, 30, 20),
            'fg': (160, 130, 90),
            'icon': (140, 110, 70)
        }
        
        cat_y = y
        for i, (name, _) in enumerate(self.categories):
            if cat_y >= y + height - 1:
                break
                
            is_active = i == self.current_category
            colors = active_colors if is_active else inactive_colors
            icon = category_icons.get(name, '•')
            
            # Draw illuminated background
            for bx in range(width):
                console.print(x + bx, cat_y, " ", bg=colors['bg'])
            
            if is_active:
                # Elegant active indicator at far left
                console.print(x, cat_y, ">", fg=colors['icon'], bg=colors['bg'])
                console.print(x , cat_y, f"{name}", fg=colors['fg'], bg=colors['bg'])
            else:
                # Left-aligned inactive categories
                console.print(x, cat_y, f"{icon} {name}", fg=colors['fg'], bg=colors['bg'])
            
            cat_y += 1  # Tighter spacing
    
    def _draw_decorative_divider(self, console, x: int, y: int, height: int):
        """Draw a smooth decorative vertical divider."""
        divider_fg = (139, 105, 60)  # Bronze
        accent_fg = (205, 164, 87)   # Gold accent
        bg = (40, 30, 22)            # Slightly lighter than parchment
        
        for dy in range(height):
            console.print(x, y + dy, " ", bg=bg)
            
            if dy == 0:
                console.print(x, y + dy, "╤", fg=accent_fg, bg=bg)
            elif dy == height - 1:
                console.print(x, y + dy, "╧", fg=accent_fg, bg=bg)
            else:
                console.print(x, y + dy, "│", fg=divider_fg, bg=bg)
    
    def _draw_selection_highlight(self, console, x: int, y: int, width: int):
        """Draw beautiful selection highlighting with gradient effect."""
        # Warm golden selection gradient
        for hx in range(width):
            # Create subtle gradient from center outward
            center = width // 2
            distance = abs(hx - center)
            intensity = max(0.3, 1.0 - (distance / center * 0.4))
            
            bg_color = (
                int(80 * intensity),
                int(60 * intensity), 
                int(30 * intensity)
            )
            console.print(x + hx, y, " ", bg=bg_color)
    
    def _draw_ornate_preview(self, console, x: int, y: int, width: int, height: int, item):
        """Draw an ornate item preview panel with illuminated manuscript styling."""
        # Elegant preview background
        preview_bg = (40, 30, 22)
        border_fg = (139, 105, 60)
        
        # Fill preview area
        for py in range(height):
            for px in range(width):
                console.print(x + px, y + py, " ", bg=preview_bg)
        
        # Decorative border
        for py in range(height):
            if py == 0 or py == height - 1:
                for px in range(width):
                    char = '═' if px % 3 != 1 else '╬'
                    console.print(x + px, y + py, char, fg=border_fg, bg=preview_bg)
            else:
                console.print(x, y + py, '║', fg=border_fg, bg=preview_bg)
                console.print(x + width - 1, y + py, '║', fg=border_fg, bg=preview_bg)
        
        # Draw the existing item preview content with enhanced styling
        self._draw_enhanced_item_preview(console, x, y, width, height, item)
    
    def _draw_enhanced_item_preview(self, console, x: int, y: int, width: int, height: int, item):
        """Draw a compact fantasy-themed item preview with more space for stats."""
        preview_bg = (40, 30, 22)
        
        # Fill entire preview area with background
        for py in range(height):
            for px in range(width):
                console.print(x + px, y + py, " ", bg=preview_bg)
        
        # Compact title
        title_y = y + 1
        title_text = "✦ Item ✦"
        title_x = x + (width - len(title_text)) // 2
        console.print(title_x, title_y, title_text, fg=(255, 215, 0), bg=preview_bg)
        
        # Compact 3x3 item display
        grid_x = x + (width - 3) // 2
        grid_y = title_y + 2
        
        # Simple 3x3 smooth border
        border_fg = (205, 164, 87)   # Gold
        item_bg = (60, 40, 25)       # Rich item background
        
        # Draw completely smooth 3x3 border
        console.print(grid_x, grid_y, "┌", fg=border_fg, bg=preview_bg)
        console.print(grid_x + 1, grid_y, "─", fg=border_fg, bg=preview_bg)
        console.print(grid_x + 2, grid_y, "┐", fg=border_fg, bg=preview_bg)
        
        console.print(grid_x, grid_y + 1, "│", fg=border_fg, bg=preview_bg)
        console.print(grid_x + 1, grid_y + 1, " ", bg=item_bg)
        console.print(grid_x + 2, grid_y + 1, "│", fg=border_fg, bg=preview_bg)
        
        console.print(grid_x, grid_y + 2, "└", fg=border_fg, bg=preview_bg)
        console.print(grid_x + 1, grid_y + 2, "─", fg=border_fg, bg=preview_bg)
        console.print(grid_x + 2, grid_y + 2, "┘", fg=border_fg, bg=preview_bg)
        
        # Item character in center
        item_char = self._get_item_display_char(item)
        item_color = self._get_item_color(item)
        console.print(grid_x + 1, grid_y + 1, item_char, fg=item_color, bg=item_bg)
        
        # Compact item name
        name_y = grid_y + 4
        item_name = item.name
        if len(item_name) > width - 6:
            item_name = item_name[:width - 9] + "..."
        console.print(x + 3, name_y, item_name, fg=(255, 223, 127), bg=preview_bg)
        
        # Stats section with better spacing
        stats_y = name_y + 1
        stat_lines = self._get_stat_comparison(item)
        
        # Always show at least basic info if no stats
        if not stat_lines:
            stat_lines = [
                f"Item: {item.name[:width-9]}" if len(item.name) > width-6 else f"Item: {item.name}",
                "Select to interact"
            ]
        
        # Display stat lines with proper spacing and ensure they fit
        for i, stat_line in enumerate(stat_lines[:6]):  # Show 6 lines max
            if stats_y + i >= y + height - 2:
                break
            # Ensure text fits within borders with proper margin
            if len(stat_line) > width - 6:
                stat_line = stat_line[:width - 9] + "..."
            
            # Use green color for equipped status
            if stat_line.strip() == "Equipped":
                console.print(x + 3, stats_y + i, stat_line, fg=(0, 255, 0), bg=preview_bg)  # Bright green
            else:
                console.print(x + 3, stats_y + i, stat_line, fg=(200, 170, 120), bg=preview_bg)
    
    def _filter_all(self, item) -> bool:
        """Show all items."""
        return True
        
    def _filter_equipment(self, item) -> bool:
        """Show only equippable items."""
        return getattr(item, "equippable", None) is not None
        
    def _filter_consumables(self, item) -> bool:
        """Show only consumable items."""
        return getattr(item, "consumable", None) is not None
        
    def _filter_misc(self, item) -> bool:
        """Show items that are neither equipment nor consumables."""
        return not self._filter_equipment(item) and not self._filter_consumables(item)
    
    def _draw_fantasy_frame(self, console, x: int, y: int, width: int, height: int, title: str):
        """Draw a fantasy-themed frame with decorative corners."""
        # Color scheme: stone/metal fantasy theme
        frame_fg = (180, 140, 100)  # Bronze/brass color
        frame_bg = (25, 20, 15)     # Dark brown/black
        title_fg = (255, 215, 0)    # Gold
        
        # Clear the area first
        for fy in range(height):
            for fx in range(width):
                console.print(x + fx, y + fy, " ", bg=frame_bg)
        
        # Draw border with fantasy characters
        # Top border
        console.print(x, y, "╔", fg=frame_fg, bg=frame_bg)
        for i in range(1, width - 1):
            console.print(x + i, y, "═", fg=frame_fg, bg=frame_bg)
        console.print(x + width - 1, y, "╗", fg=frame_fg, bg=frame_bg)
        
        # Bottom border  
        console.print(x, y + height - 1, "╚", fg=frame_fg, bg=frame_bg)
        for i in range(1, width - 1):
            console.print(x + i, y + height - 1, "═", fg=frame_fg, bg=frame_bg)
        console.print(x + width - 1, y + height - 1, "╝", fg=frame_fg, bg=frame_bg)
        
        # Side borders
        for i in range(1, height - 1):
            console.print(x, y + i, "║", fg=frame_fg, bg=frame_bg)
            console.print(x + width - 1, y + i, "║", fg=frame_fg, bg=frame_bg)
        
        # Title with decorative elements
        title_text = f"═══ {title} ═══"
        title_start = x + (width - len(title_text)) // 2
        console.print(title_start, y, title_text, fg=title_fg, bg=frame_bg)
    
    def _get_item_type_char(self, item) -> str:
        """Get a beautiful fantasy character representing the item type."""
        if getattr(item, "equippable", None):
            eq_type = getattr(item.equippable, "equipment_type", None)
            if eq_type:
                eq_name = eq_type.name.lower()
                if "weapon" in eq_name or "sword" in eq_name or "dagger" in eq_name:
                    return "⚔"  # Crossed swords
                elif "armor" in eq_name or "mail" in eq_name or "leather" in eq_name:
                    return "🛡"  # Shield
                elif "shield" in eq_name:
                    return "⛨"  # Shield variant
                else:
                    return "✦"  # Equipment star
            return "✦"  # Equipment star
        elif getattr(item, "consumable", None):
            if "potion" in item.name.lower():
                return "⚗"  # Alchemical symbol (potion)
            elif "scroll" in item.name.lower():
                return "📜"  # Scroll
            else:
                return "✿"  # Star-like symbol for consumables
        return "◉"  # Circle for misc items
    
    def _draw_item_preview(self, console, x: int, y: int, width: int, height: int, item):
        """Draw the 3x3 item preview and stat comparison."""
        preview_start_y = y + 3
        
        # Draw 3x3 item display in center
        item_char = self._get_item_display_char(item)
        
        # 3x3 grid centered
        grid_x = x + (width - 3) // 2
        grid_y = preview_start_y + 2
        
        # Draw fancy border around the item with same style as main borders
        border_fg = (180, 140, 100)  # Bronze/brass color
        border_bg = (25, 20, 15)     # Dark brown/black
        center_bg = (60, 40, 20)     # Item background
        
        # Draw 3x3 border frame (actual 3x3 as requested)
        # Top border
        console.print(grid_x, grid_y, "╔", fg=border_fg, bg=border_bg)
        console.print(grid_x + 1, grid_y, "═", fg=border_fg, bg=border_bg)
        console.print(grid_x + 2, grid_y, "╗", fg=border_fg, bg=border_bg)
        
        # Middle row with item - use direct color assignment  
        console.print(grid_x, grid_y + 1, "║", fg=border_fg, bg=border_bg)
        
        # Get item color directly
        item_color = self._get_item_color(item)
        
        # Print item with proper color
        console.print(grid_x + 1, grid_y + 1, item_char, fg=item_color, bg=center_bg)
        
        console.print(grid_x + 2, grid_y + 1, "║", fg=border_fg, bg=border_bg)
        
        # Bottom border
        console.print(grid_x, grid_y + 2, "╚", fg=border_fg, bg=border_bg)
        console.print(grid_x + 1, grid_y + 2, "═", fg=border_fg, bg=border_bg)
        console.print(grid_x + 2, grid_y + 2, "╝", fg=border_fg, bg=border_bg)
        
        # Item name (position adjusted for new border)
        name_y = grid_y + 4
        item_name = item.name
        if len(item_name) > width - 2:
            item_name = item_name[:width - 5] + "..."
        console.print(x + 1, name_y, item_name, fg=(255, 215, 0))
        
        # Stat comparison
        stats_y = name_y + 2
        stat_lines = self._get_stat_comparison(item)
        
        from text_utils import print_colored_markup
        for i, stat_line in enumerate(stat_lines):
            if stats_y + i >= y + height - 2:
                break
            print_colored_markup(console, x + 1, stats_y + i, stat_line, default_color=(192, 192, 192))
    
    def _get_item_display_char(self, item) -> str:
        """Get the character to display in the 3x3 preview."""
        return item.char
    
    def _get_item_color(self, item):
        """Get the actual color object for item display based on type and status."""
        import color
        
        # More robust equipment check - avoid false positives
        is_equipped = False
        try:
            if hasattr(self.engine.player, 'equipment') and hasattr(item, 'equippable'):
                is_equipped = self.engine.player.equipment.item_is_equipped(item)
        except Exception as e:
            # If there's any error, assume not equipped
            is_equipped = False
            
        if is_equipped:
            return color.green  # Bright green for equipped items only
        elif getattr(item, "equippable", None):
            return color.light_gray  # Light gray for unequipped equipment
        elif getattr(item, "consumable", None):
            if "potion" in item.name.lower():
                return color.magenta  # Magenta for potions
            elif "scroll" in item.name.lower():
                return color.yellow  # Yellow for scrolls
            return color.cyan  # Cyan for other consumables
        return color.white  # White for unknown items

    def _get_item_color_name(self, item) -> str:
        """Get the color name for text markup based on item type and status."""
        # More robust equipment check - avoid false positives
        is_equipped = False
        try:
            if hasattr(self.engine.player, 'equipment') and hasattr(item, 'equippable'):
                is_equipped = self.engine.player.equipment.item_is_equipped(item)
        except Exception as e:
            # If there's any error, assume not equipped
            is_equipped = False
            
        if is_equipped:
            return "green"  # Bright green for equipped items only
        elif getattr(item, "equippable", None):
            return "light_gray"  # Light gray for unequipped equipment
        elif getattr(item, "consumable", None):
            if "potion" in item.name.lower():
                return "magenta"  # Magenta for potions
            elif "scroll" in item.name.lower():
                return "yellow"  # Yellow for scrolls
            return "cyan"  # Cyan for other consumables
        return "white"  # White for unknown items
    
    def _get_stat_comparison(self, item) -> list:
        """Generate stat comparison text for the item."""
        lines = []
        player = self.engine.player
        
        # Type information
        if getattr(item, "equippable", None):
            is_equipped = player.equipment.item_is_equipped(item)
            
            # Get equipment type
            eq_type = getattr(item.equippable, "equipment_type", None)
            if eq_type:
                type_name = eq_type.name.replace("_", " ").title()
                lines.append(f"Type: {type_name}")
                
                # Show appropriate stat based on equipment type
                eq_name = eq_type.name.lower()
                
                if "weapon" in eq_name or "sword" in eq_name or "dagger" in eq_name:
                    # Weapons show power
                    if hasattr(item.equippable, "power_bonus"):
                        power = item.equippable.power_bonus
                        if is_equipped:
                            current_power = player.fighter.power
                            lines.append(f"Power: {current_power}({-power:+d})")
                        else:
                            current_power = player.fighter.power
                            lines.append(f"Power: {current_power} (+{power})")
                            
                elif "armor" in eq_name or "mail" in eq_name or "leather" in eq_name or "shield" in eq_name:
                    # Armor shows defense
                    if hasattr(item.equippable, "defense_bonus"):
                        defense = item.equippable.defense_bonus
                        if is_equipped:
                            current_defense = player.fighter.defense
                            lines.append(f"Defense: {current_defense}({-defense:+d})")
                        else:
                            current_defense = player.fighter.defense
                            lines.append(f"Defense: {current_defense} (+{defense})")
                            
                else:
                    # Generic equipment - show both if available
                    if hasattr(item.equippable, "power_bonus"):
                        power = item.equippable.power_bonus
                        if power != 0:
                            if is_equipped:
                                current_power = player.fighter.power
                                lines.append(f"Power: {current_power}({-power:+d})")
                            else:
                                current_power = player.fighter.power
                                lines.append(f"Power: {current_power} (+{power})")
                                
                    if hasattr(item.equippable, "defense_bonus"):
                        defense = item.equippable.defense_bonus
                        if defense != 0:
                            if is_equipped:
                                current_defense = player.fighter.defense
                                lines.append(f"Defense: {current_defense}({-defense:+d})")
                            else:
                                current_defense = player.fighter.defense
                                lines.append(f"Defense: {current_defense} (+{defense})")
            
            # Equipment status
            if is_equipped:
                lines.append("Equipped")  # Will be colored green in display
            else:
                lines.append("Status: Not equipped")
                
        elif getattr(item, "consumable", None):
            lines.append("Type: Consumable")
            
            # Healing items
            if hasattr(item.consumable, "amount") and "heal" in item.name.lower():
                heal_amount = item.consumable.amount
                current_hp = player.fighter.hp
                max_hp = player.fighter.max_hp
                potential_hp = min(max_hp, current_hp + heal_amount)
                lines.append(f"Healing: {heal_amount}")
                lines.append(f"HP: {current_hp}→{potential_hp}")
            
            # Usage info
            if "potion" in item.name.lower():
                lines.append("Use: Q to quaff")
            elif "scroll" in item.name.lower():
                lines.append("Use: R to read")
            else:
                lines.append("Use: I to activate")
        
        else:
            lines.append("Type: Miscellaneous")
            lines.append("Use: D to drop")
        
        # Limit to available space
        return lines[:6]

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        sounds.play_ui_move_sound()
        player = self.engine.player
        key = event.sym
        modifier = event.mod

        # Build filtered list for selection mapping
        item_groups = player.inventory.get_display_groups()
        category_filter = self.categories[self.current_category][1]
        filtered_groups = []
        for group in item_groups:
            if self.item_filter(group['item']) and category_filter(group['item']):
                filtered_groups.append(group)

        # Arrow-key navigation: up/down to move selection, left/right for tabs, Enter to confirm
        if key == tcod.event.K_UP:
            self.selected_index = max(0, self.selected_index - 1)
            return None
        if key == tcod.event.K_DOWN:
            self.selected_index = min(len(filtered_groups) - 1 if filtered_groups else 0, self.selected_index + 1)
            return None
        if key == tcod.event.K_LEFT:
            self.current_category = max(0, self.current_category - 1)
            self.selected_index = 0  # Reset selection when changing tabs
            return None
        if key == tcod.event.K_RIGHT:
            self.current_category = min(len(self.categories) - 1, self.current_category + 1)
            self.selected_index = 0  # Reset selection when changing tabs
            return None
        # Number keys 1-4 for quick tab switching
        if tcod.event.KeySym.N1 <= key <= tcod.event.KeySym.N4:
            tab_index = key - tcod.event.KeySym.N1
            if tab_index < len(self.categories):
                self.current_category = tab_index
                self.selected_index = 0  # Reset selection when changing tabs
                return None
        
        if key in CONFIRM_KEYS:
            # If inventory empty, do nothing
            if len(filtered_groups) == 0:
                return None
            try:
                selected_group = filtered_groups[getattr(self, "selected_index", 0)]
                selected_item = selected_group['item']
            except Exception:
                self.engine.message_log.add_message("Invalid selection.", color.invalid)
                return None
            return self.on_item_selected(selected_item)

        # Letter selection still supported but operates on the filtered list
        index = key - tcod.event.KeySym.A

        if 0 <= index <= 26:
            try:
                selected_group = filtered_groups[index]
                selected_item = selected_group['item']
            except IndexError:
                self.engine.message_log.add_message("Invalid entry.", color.invalid)
                return None
            return self.on_item_selected(selected_item)

        return super().ev_keydown(event)

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        if item.consumable:
            # Execute consumable action and stay in inventory
            action_or_handler = item.consumable.get_action(self.engine.player)
            if action_or_handler:
                # Check if it's a handler (needs input) or action (can perform immediately)
                if hasattr(action_or_handler, 'perform'):
                    action_or_handler.perform()
                    return None  # Stay in inventory
                else:
                    # It's a handler that needs input, return it
                    return action_or_handler
            return None  # Stay in inventory
        elif item.equippable:
            # Execute equip action and stay in inventory
            action = actions.EquipAction(self.engine.player, item)
            action.perform()
            return None  # Stay in inventory
        else:
            return None

class ScrollActivateHandler(InventoryEventHandler):
    # Handles using magic/scroll item
    TITLE = "Select a scroll to read"

    def __init__(self, engine, item_filter = None):
        super().__init__(engine, item_filter=lambda it: getattr(it, "consumable", None) is not None and "Scroll" in getattr(it, "name", ""))

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        # Execute scroll action and stay in inventory
        if "Scroll" in item.name and item.consumable:
            action_or_handler = item.consumable.get_action(self.engine.player)
            if action_or_handler:
                # Check if it's a handler (needs input) or action (can perform immediately)
                if hasattr(action_or_handler, 'perform'):
                    action_or_handler.perform()
                    return None  # Stay in inventory
                else:
                    # It's a handler that needs input, return it
                    return action_or_handler
            return None  # Stay in inventory
        else:
            self.engine.message_log.add_message(f"You cannot read the {item.name}.", color.invalid)
            return None  # Stay in inventory



            


class InventoryActivateHandler(InventoryEventHandler):
    # Handles using inventory item
    TITLE = "Select an item to use"

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        # Returns the action for the selected item
        return None
        
class ThrowSelectionHandler(InventoryEventHandler):
    # Handles selecting an item to throw
    TITLE = "Select an item to throw"

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        # Returns the action for throwing the selected item
        return ThrowTargetHandler(self.engine, item)
    


class QuaffActivateHandler(InventoryEventHandler):
    # Handles using inventory item
    TITLE = "Select potion to quaff"

    def __init__(self, engine: Engine):
        super().__init__(engine, item_filter=lambda it: getattr(it, "consumable", None) is not None and "Potion" in getattr(it, "name", ""))

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        # Execute potion action and stay in inventory
        if "Potion" in item.name and item.consumable:
            sounds.play_quaff_sound()
            action_or_handler = item.consumable.get_action(self.engine.player)
            if action_or_handler:
                # Check if it's a handler (needs input) or action (can perform immediately)
                if hasattr(action_or_handler, 'perform'):
                    action_or_handler.perform()
                    return None  # Stay in inventory
                else:
                    # It's a handler that needs input, return it
                    return action_or_handler
            return None  # Stay in inventory
        else:
            self.engine.message_log.add_message(f"You cannot drink the {item.name}.", color.invalid)
            return None  # Stay in inventory
    
class InventoryDropHandler(InventoryEventHandler):
    #Handles dropping inventory item
    
    TITLE = "Select an item to drop"

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        # Remember the current filtered list to adjust selection index
        all_items = list(self.engine.player.inventory.items)
        filtered_items = [it for it in all_items if self.item_filter(it)]
        
        # Get current item index in filtered list
        try:
            current_filtered_index = filtered_items.index(item)
        except ValueError:
            current_filtered_index = 0
        
        # Execute drop action
        action = actions.DropItem(self.engine.player, item)
        action.perform()
        
        # Adjust selected index after dropping item
        # Get the new filtered list after dropping
        all_items = list(self.engine.player.inventory.items)
        new_filtered_items = [it for it in all_items if self.item_filter(it)]
        
        # Adjust selection to stay reasonable
        if len(new_filtered_items) == 0:
            self.selected_index = 0
        else:
            # Keep same index if possible, otherwise move to previous item
            self.selected_index = min(current_filtered_index, len(new_filtered_items) - 1)
        
        return None  # Stay in inventory


# class InventoryEquipHandler(InventoryEventHandler):
#     """Shows only equippable items and equips the selected one."""
#     TITLE = "Select an item to equip"
# 
#     def __init__(self, engine: Engine):
#         # Filter for items that have an equippable component
#         super().__init__(engine, item_filter=lambda it: getattr(it, "equippable", None) is not None)
# 
#     def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
#         if getattr(item, "equippable", None):
#             # Execute equip action and stay in inventory
#             action = actions.EquipAction(self.engine.player, item)
#             action.perform()
#             return None  # Stay in inventory
#         else:
#             self.engine.message_log.add_message(f"{item.name} cannot be equipped.", color.invalid)
#             return None

class SelectIndexHandler(AskUserEventHandler):
    # Handles asking the user for a location on the map

    def __init__(self, engine: Engine):
        #sets cursor to player when handler is made
        super().__init__(engine)
        player = self.engine.player
        engine.mouse_location = player.x, player.y

    def on_render(self, console: tcod.Console) -> None:
        # Highlights tile underneath cursor
        super().on_render(console)

        x, y = self.engine.mouse_location
        x, y = int(x), int(y)
        console.rgb["bg"][x, y] = color.white
        console.rgb["fg"][x, y] = color.black
        # Draw a small framed box next to the cursor showing the name(s)
        try:
            from render_functions import get_names_at_location


            names = get_names_at_location(x, y, self.engine.game_map)
            if names:
                # Decide where to place the box: prefer to the right of cursor
                width = max(10, len(names) + 2)
                box_x = x + 1
                box_y = y
                # If box would overflow to the right, place it to the left
                if box_x + width > console.width:
                    box_x = x - width - 1
                if box_x < 0:
                    box_x = 0

                # Draw frame and text
                console.draw_frame(x=box_x, y=box_y, width=width, height=3, title=None, clear=True, fg=(255,255,255), bg=(0,0,0))
                console.print(x=box_x + 1, y=box_y + 1, string=names)
        except Exception:
            # If anything goes wrong, skip drawing the look box
            pass
    
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        # check for key motion or confimration keys
        key = event.sym

        if key in MOVE_KEYS:
            modifier = 1 #speeds up movement
            if event.mod & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT):
                modifier *= 5
            if event.mod & (tcod.event.KMOD_LCTRL | tcod.event.KMOD_RCTRL):
                modifier *= 10
            if event.mod & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
                modifier *= 20
            
            x, y = self.engine.mouse_location
            dx, dy = MOVE_KEYS[key]
            x += dx * modifier
            y += dy * modifier
            # clamp index to map size
            x = max(0, min(x, self.engine.game_map.width - 1))
            y = max(0, min(y, self.engine.game_map.height -1))
            self.engine.mouse_location = x,y 
            return None
        elif key in CONFIRM_KEYS:
            return self.on_index_selected(*self.engine.mouse_location)
        return super().ev_keydown(event)
    
    def ev_mousebuttondown(
            self, event: tcod.event.MouseButtonDown
            ) -> Optional[ActionOrHandler]:
        #left click confirms selection
        if self.engine.game_map.in_bounds(*event.tile):
            if event.button == 1:
                return self.on_index_selected(*event.tile)
        return super().ev_mousebuttondown(event)
    
    def on_index_selected(self, x: int, y: int) -> Optional[ActionOrHandler]:
        # called when index selected
        raise NotImplementedError()

class ThrowTargetHandler(SelectIndexHandler):
    # After item selected, this handles where the object should be thrown
    def __init__(self, engine: Engine, item):
        super().__init__(engine)
        self.item = item
        self.radius = 2

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)
        # Draw range on top of player location
        x, y = self.engine.player.x, self.engine.player.y
        console.draw_frame(
        x=x - self.radius - 1,
        y=y - self.radius - 1,
        width=(self.radius * 2) + 3,
        height=(self.radius * 2) + 3,
        fg=color.red,
        clear=False,
    )
    
    def on_index_selected(self, x: int, y: int) -> Optional[ActionOrHandler]:
        # Check if walkable
        if not self.engine.game_map.tiles["walkable"][x, y]:
            self.engine.message_log.add_message("You cannot throw there.", color.invalid)
            return None

        # Check if within throw range
        if self.engine.player.distance(x, y) > 5:
            self.engine.message_log.add_message("Target is out of range.", color.invalid)
            return None

        # Finally, check if tile is in player view 
        if not self.engine.game_map.visible[x, y]:
            self.engine.message_log.add_message("You cannot see that.", color.invalid)
            return None
        #Play throw sound
        sounds.play_throw_sound()
        # Wait a few milliseconds to let the throw sound play before dropping the item
        import time
        time.sleep(0.1) 
        # Play Item drop sound

        return actions.ThrowItem(self.engine.player, self.item, x, y)
    
class TargetingHandler(SelectIndexHandler):
    """Base targeting handler for area/ranged attacks."""
    
    def __init__(self, engine: Engine, callback: Callable[[int, int], Optional[ActionOrHandler]]):
        super().__init__(engine)
        self.callback = callback
    
    def on_index_selected(self, x: int, y: int) -> Optional[ActionOrHandler]:
        return self.callback(x, y)


class AttackModeHandler(AskUserEventHandler):
    """Handler for setting the player's preferred attack targeting mode."""
    
    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.selected_index = 0
        
        # Available targeting modes
        self.attack_modes = [
            (None, "Random Target", "Hit any available body part (default)"),
            ('cranium', "Target Head", "Always aim for head/neck - Very Hard, 2x Damage"),
            ('core', "Target Torso", "Always aim for torso/chest - Easy Target, Normal Damage"),
            ('upper_limbs', "Target Arms", "Always aim for arms/hands - Hard, Reduced Damage"),
            ('lower_limbs', "Target Legs", "Always aim for legs/feet - Medium, Reduced Damage"),
        ]
        
        # Quick selection keys
        self.quick_keys = {
            tcod.event.KeySym.N0: None,  # Random
            tcod.event.KeySym.N1: 'cranium',
            tcod.event.KeySym.N2: 'core', 
            tcod.event.KeySym.N3: 'upper_limbs',
            tcod.event.KeySym.N4: 'lower_limbs',
        }
    
    def _get_current_mode_index(self) -> int:
        """Get the index of the currently selected attack mode."""
        current_mode = getattr(self.engine.player, 'current_attack_type', None)
        for i, (mode, _, _) in enumerate(self.attack_modes):
            if mode == current_mode:
                return i
        return 0  # Default to random
    
    def _draw_parchment_background(self, console, x: int, y: int, width: int, height: int):
        """Draw parchment-style background."""
        # Rich brown parchment colors with fantasy feel
        for py in range(height):
            for px in range(width):
                # Create subtle variation in the parchment color
                base_color = (45, 35, 25)  # Rich brown
                console.print(x + px, y + py, " ", bg=base_color)
    
    def _draw_ornate_border(self, console, x: int, y: int, width: int, height: int, title: str):
        """Draw ornate border with fantasy styling."""
        border_fg = (139, 105, 60)  # Bronze
        title_fg = (255, 215, 0)    # Gold
        bg = (45, 35, 25)           # Parchment background
        
        # Draw border corners and edges
        console.print(x, y, "╔", fg=border_fg, bg=bg)
        console.print(x + width - 1, y, "╗", fg=border_fg, bg=bg)
        console.print(x, y + height - 1, "╚", fg=border_fg, bg=bg)
        console.print(x + width - 1, y + height - 1, "╝", fg=border_fg, bg=bg)
        
        # Top and bottom borders
        for i in range(1, width - 1):
            console.print(x + i, y, "═", fg=border_fg, bg=bg)
            console.print(x + i, y + height - 1, "═", fg=border_fg, bg=bg)
        
        # Left and right borders
        for i in range(1, height - 1):
            console.print(x, y + i, "║", fg=border_fg, bg=bg)
            console.print(x + width - 1, y + i, "║", fg=border_fg, bg=bg)
        
        # Ornate title with decorative flourishes
        title_decorated = f"✦ {title} ✦"
        title_start = x + (width - len(title_decorated)) // 2
        # Clear title area
        for tx in range(len(title_decorated)):
            console.print(title_start + tx, y, " ", bg=bg)
        console.print(title_start, y, title_decorated, fg=title_fg, bg=bg)
    
    def _draw_parchment_background(self, console, x: int, y: int, width: int, height: int):
        """Draw parchment-style background."""
        # Rich brown parchment colors with fantasy feel
        for py in range(height):
            for px in range(width):
                # Create subtle variation in the parchment color
                base_color = (45, 35, 25)  # Rich brown
                console.print(x + px, y + py, " ", bg=base_color)
    
    def _draw_ornate_border(self, console, x: int, y: int, width: int, height: int, title: str):
        """Draw ornate border with fantasy styling."""
        border_fg = (139, 105, 60)  # Bronze
        title_fg = (255, 215, 0)    # Gold
        bg = (45, 35, 25)           # Parchment background
        
        # Draw border corners and edges
        console.print(x, y, "╔", fg=border_fg, bg=bg)
        console.print(x + width - 1, y, "╗", fg=border_fg, bg=bg)
        console.print(x, y + height - 1, "╚", fg=border_fg, bg=bg)
        console.print(x + width - 1, y + height - 1, "╝", fg=border_fg, bg=bg)
        
        # Top and bottom borders
        for i in range(1, width - 1):
            console.print(x + i, y, "═", fg=border_fg, bg=bg)
            console.print(x + i, y + height - 1, "═", fg=border_fg, bg=bg)
        
        # Left and right borders
        for i in range(1, height - 1):
            console.print(x, y + i, "║", fg=border_fg, bg=bg)
            console.print(x + width - 1, y + i, "║", fg=border_fg, bg=bg)
        
        # Ornate title with decorative flourishes
        title_decorated = f"✦ {title} ✦"
        title_start = x + (width - len(title_decorated)) // 2
        # Clear title area
        for tx in range(len(title_decorated)):
            console.print(title_start + tx, y, " ", bg=bg)
        console.print(title_start, y, title_decorated, fg=title_fg, bg=bg)
    
    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)
        
        # Calculate window size
        window_width = 65
        window_height = min(25, len(self.attack_modes) + 12)
        
        # Center the window
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2
        
        # Draw ornate fantasy-themed window
        self._draw_parchment_background(console, x, y, window_width, window_height)
        self._draw_ornate_border(console, x, y, window_width, window_height, "Set Attack Mode")
        
        # Instructions header
        console.print(
            x=x + 2, y=y + 2,
            string="Choose your preferred attack targeting:",
            fg=(255, 215, 0), bg=(45, 35, 25)
        )
        
        # Current mode indicator
        current_mode_index = self._get_current_mode_index()
        current_mode_name = self.attack_modes[current_mode_index][1]
        console.print(
            x=x + 2, y=y + 3,
            string=f"Current: {current_mode_name}",
            fg=(0, 255, 0), bg=(45, 35, 25)
        )
        
        # Attack modes list
        start_y = y + 5
        for i, (mode_key, mode_name, description) in enumerate(self.attack_modes):
            item_y = start_y + i
            if item_y >= y + window_height - 4:
                break
                
            # Highlight selected item with ornate selection
            if i == self.selected_index:
                # Draw rich selection background with golden glow
                for sx in range(window_width - 4):
                    console.print(x + 2 + sx, item_y, " ", bg=(80, 60, 30))
            
            # Number key indicator
            number_key = ""
            for key, target in self.quick_keys.items():
                if target == mode_key:
                    if mode_key is None:
                        key_num = "0"
                    else:
                        key_num = str(key - tcod.event.KeySym.N1 + 1)
                    number_key = f"[{key_num}] "
                    break
            
            # Current mode indicator
            current_indicator = "★ " if i == current_mode_index else "  "
            
            # Color coding
            if i == current_mode_index:
                mode_color = color.green
            elif i == self.selected_index:
                mode_color = color.yellow
            else:
                mode_color = color.white
            
            # Main mode line
            main_line = f"{current_indicator}{number_key}{mode_name}"
            console.print(x + 3, item_y, main_line, fg=mode_color, bg=(45, 35, 25) if i != self.selected_index else (80, 60, 30))
            
            # Description
            description_x = x + 3
            description_y = item_y
            if len(main_line) < 25:  # If there's space on the same line
                description_x += len(main_line) + 2
            else:  # Move to next line if too long
                description_y += 1
                item_y += 1  # Adjust for the extra line
            
            # Truncate description to fit
            max_desc_width = window_width - (description_x - x) - 3
            if len(description) > max_desc_width:
                description = description[:max_desc_width-3] + "..."
                
            console.print(description_x, description_y, description, fg=color.light_gray, bg=(45, 35, 25) if i != self.selected_index else (80, 60, 30))
        
        # Instructions footer
        instructions = [
            "[↑↓] Navigate  [0-6] Quick Select  [Enter] Set Mode  [Esc] Cancel",
            "This affects all future attacks until changed."
        ]
        
        for i, instruction in enumerate(instructions):
            console.print(
                x + (window_width - len(instruction)) // 2,
                y + window_height - 3 + i,
                instruction,
                fg=color.light_gray, bg=(45, 35, 25)
            )
    
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        key = event.sym
        
        # Navigation
        if key == tcod.event.KeySym.UP:
            self.selected_index = max(0, self.selected_index - 1)
            return None
        elif key == tcod.event.KeySym.DOWN:
            self.selected_index = min(len(self.attack_modes) - 1, self.selected_index + 1)
            return None
        
        # Quick selection with number keys
        elif key in self.quick_keys:
            target_mode = self.quick_keys[key]
            for i, (mode_key, _, _) in enumerate(self.attack_modes):
                if mode_key == target_mode:
                    self.selected_index = i
                    # Auto-set mode when using number keys
                    return self._set_attack_mode()
        
        # Confirm selection
        elif key in CONFIRM_KEYS:
            return self._set_attack_mode()
        
        # Cancel
        elif key == tcod.event.KeySym.ESCAPE:
            return MainGameEventHandler(self.engine)
        
        return super().ev_keydown(event)
    
    def _set_attack_mode(self) -> Optional[ActionOrHandler]:
        """Set the attack mode and return to main game."""
        selected_mode, mode_name, _ = self.attack_modes[self.selected_index]
        
        # Store the preferred attack type on the player
        self.engine.player.current_attack_type = selected_mode
        #print(self.engine.player.current_attack_type)
        
        # Show confirmation message
        if selected_mode is None:
            message = "Attack mode: Random targeting"
        else:
            part_name = selected_mode.replace('_', ' ').title()
            message = f"Attack mode: Always target {part_name}"
            
        #self.engine.message_log.add_message(message, color.green)
        
        return MainGameEventHandler(self.engine)


class LimbTargetingHandler(AskUserEventHandler):
    """Handler for selecting which body part to target in combat."""
    
    def __init__(self, engine: Engine, attacker: Actor, target: Actor):
        super().__init__(engine)
        self.attacker = attacker
        self.target = target
        self.selected_index = 0
        
        # Get available body parts (not destroyed)
        self.available_parts = []
        if hasattr(target, 'body_parts') and target.body_parts:
            for part_type, part in target.body_parts.body_parts.items():
                if not part.is_destroyed:
                    self.available_parts.append((part_type, part))
        
        # Sort parts in logical order for display
        self._sort_body_parts()
        
        # Quick selection keys for common parts
        self.quick_keys = {
            tcod.event.KeySym.N1: 'HEAD',
            tcod.event.KeySym.N2: 'TORSO', 
            tcod.event.KeySym.N3: 'LEFT_ARM',
            tcod.event.KeySym.N4: 'RIGHT_ARM',
            tcod.event.KeySym.N5: 'LEFT_LEG',
            tcod.event.KeySym.N6: 'RIGHT_LEG',
        }
    
    def _sort_body_parts(self):
        """Sort body parts in logical display order."""
        order_priority = {
            'HEAD': 0,
            'NECK': 1, 
            'TORSO': 2,
            'LEFT_ARM': 3,
            'RIGHT_ARM': 4,
            'LEFT_HAND': 5,
            'RIGHT_HAND': 6,
            'LEFT_LEG': 7,
            'RIGHT_LEG': 8,
            'LEFT_FOOT': 9,
            'RIGHT_FOOT': 10,
        }
        
        self.available_parts.sort(key=lambda x: order_priority.get(x[0].name, 99))
    
    def _get_difficulty_description(self, part_type) -> str:
        """Get difficulty and damage description for a body part."""
        if part_type.name == "HEAD":
            return "Very Hard, 2x Damage"
        elif part_type.name == "TORSO":
            return "Easy Target, Normal Damage"
        elif "LEG" in part_type.name:
            return "Medium, Reduced Damage"
        elif "ARM" in part_type.name:
            return "Hard, Reduced Damage"
        elif "HAND" in part_type.name or "FOOT" in part_type.name:
            return "Very Hard, Low Damage"
        else:
            return "Medium, Normal Damage"
    
    def _draw_parchment_background(self, console, x: int, y: int, width: int, height: int):
        """Draw parchment-style background."""
        # Rich brown parchment colors with fantasy feel
        for py in range(height):
            for px in range(width):
                # Create subtle variation in the parchment color
                base_color = (45, 35, 25)  # Rich brown
                console.print(x + px, y + py, " ", bg=base_color)
    
    def _draw_ornate_border(self, console, x: int, y: int, width: int, height: int, title: str):
        """Draw ornate border with fantasy styling."""
        border_fg = (139, 105, 60)  # Bronze
        title_fg = (255, 215, 0)    # Gold
        bg = (45, 35, 25)           # Parchment background
        
        # Draw border corners and edges
        console.print(x, y, "╔", fg=border_fg, bg=bg)
        console.print(x + width - 1, y, "╗", fg=border_fg, bg=bg)
        console.print(x, y + height - 1, "╚", fg=border_fg, bg=bg)
        console.print(x + width - 1, y + height - 1, "╝", fg=border_fg, bg=bg)
        
        # Top and bottom borders
        for i in range(1, width - 1):
            console.print(x + i, y, "═", fg=border_fg, bg=bg)
            console.print(x + i, y + height - 1, "═", fg=border_fg, bg=bg)
        
        # Left and right borders
        for i in range(1, height - 1):
            console.print(x, y + i, "║", fg=border_fg, bg=bg)
            console.print(x + width - 1, y + i, "║", fg=border_fg, bg=bg)
        
        # Ornate title with decorative flourishes
        title_decorated = f"✦ {title} ✦"
        title_start = x + (width - len(title_decorated)) // 2
        # Clear title area
        for tx in range(len(title_decorated)):
            console.print(title_start + tx, y, " ", bg=bg)
        console.print(title_start, y, title_decorated, fg=title_fg, bg=bg)
    
    def _get_health_bar(self, part, width=8) -> str:
        """Create a text health bar for the body part."""
        if part.max_hp <= 0:
            return "░" * width
        
        ratio = part.current_hp / part.max_hp
        filled = int(ratio * width)
        return "█" * filled + "░" * (width - filled)
    
    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)
        
        # Calculate window size
        window_width = 60
        window_height = min(25, len(self.available_parts) + 10)
        
        # Center the window
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2
        
        # Draw ornate fantasy-themed window
        self._draw_parchment_background(console, x, y, window_width, window_height)
        self._draw_ornate_border(console, x, y, window_width, window_height, f"Target {self.target.name}'s Body Parts")
        
        # Instructions header
        console.print(
            x=x + 2, y=y + 2,
            string="Select a body part to attack:",
            fg=(255, 215, 0), bg=(45, 35, 25)
        )
        
        # Body parts list
        start_y = y + 4
        for i, (part_type, part) in enumerate(self.available_parts):
            item_y = start_y + i
            if item_y >= y + window_height - 4:
                break
                
            # Highlight selected item with ornate selection
            if i == self.selected_index:
                # Draw rich selection background with golden glow
                for sx in range(window_width - 4):
                    console.print(x + 2 + sx, item_y, " ", bg=(80, 60, 30))
            
            # Number key indicator (if available)
            number_key = ""
            for key, part_name in self.quick_keys.items():
                if part_name == part_type.name:
                    key_num = str(key - tcod.event.KeySym.N1 + 1)
                    number_key = f"[{key_num}] "
                    break
            
            # Part name
            part_display_name = part.name.replace("_", " ").title()
            
            # Health bar
            health_bar = self._get_health_bar(part)
            health_text = f"({part.current_hp}/{part.max_hp})"
            
            # Difficulty/damage info
            difficulty = self._get_difficulty_description(part_type)
            
            # Color coding based on health
            if part.current_hp <= 0:
                part_color = color.dark_red
            elif part.current_hp < part.max_hp * 0.3:
                part_color = color.red
            elif part.current_hp < part.max_hp * 0.7:
                part_color = color.yellow
            else:
                part_color = color.green
            
            # Main part line
            main_line = f"{number_key}{part_display_name:<12} {health_bar} {health_text}"
            console.print(x + 3, item_y, main_line, fg=part_color, bg=(45, 35, 25) if i != self.selected_index else (80, 60, 30))
            
            # Difficulty info on the right
            console.print(x + window_width - len(difficulty) - 3, item_y, difficulty, fg=color.light_gray, bg=(45, 35, 25) if i != self.selected_index else (80, 60, 30))
        
        # Instructions footer
        instructions = [
            "[↑↓] Navigate  [1-6] Quick Select  [Enter] Attack  [Esc] Cancel",
            "Targeting: Head=2x dmg, Torso=easy hit, Limbs=harder but disable"
        ]
        
        for i, instruction in enumerate(instructions):
            console.print(
                x + (window_width - len(instruction)) // 2,
                y + window_height - 3 + i,
                instruction,
                fg=color.light_gray, bg=(45, 35, 25)
            )
    
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        key = event.sym
        
        # Navigation
        if key == tcod.event.KeySym.UP:
            self.selected_index = max(0, self.selected_index - 1)
            return None
        elif key == tcod.event.KeySym.DOWN:
            self.selected_index = min(len(self.available_parts) - 1, self.selected_index + 1)
            return None
        
        # Quick selection with number keys
        elif key in self.quick_keys:
            target_part_name = self.quick_keys[key]
            for i, (part_type, part) in enumerate(self.available_parts):
                if part_type.name == target_part_name:
                    self.selected_index = i
                    # Auto-attack when using number keys
                    return self._execute_targeted_attack()
        
        # Confirm selection
        elif key in CONFIRM_KEYS:
            return self._execute_targeted_attack()
        
        # Cancel
        elif key == tcod.event.KeySym.ESCAPE:
            from input_handlers import MainGameEventHandler
            return MainGameEventHandler(self.engine)
        
        return super().ev_keydown(event)
    
    def _execute_targeted_attack(self) -> Optional[ActionOrHandler]:
        """Execute the targeted attack and return to main game."""
        if not self.available_parts:
            return MainGameEventHandler(self.engine)
            
        selected_part_type, selected_part = self.available_parts[self.selected_index]
        
        # Calculate direction to target
        dx = self.target.x - self.attacker.x
        dy = self.target.y - self.attacker.y
        
        # Create and perform the targeted attack
        from actions import MeleeAction
        action = MeleeAction(self.attacker, dx, dy, selected_part_type)
        
        try:
            action.perform()
        except Exception as e:
            self.engine.message_log.add_message(str(e), color.impossible)
        
        return MainGameEventHandler(self.engine)

class LookHandler(SelectIndexHandler):
    """Enhanced look handler with detailed inspection sidebar and tabbed interface."""
    
    # Class variable to remember last selected tab across instances
    last_selected_tab = 0

    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.detail_index = 0  # Index for cycling through items at location
        self.scroll_offset = 0  # For scrolling through text
        self.current_tab = LookHandler.last_selected_tab  # Start with remembered tab
        self.tab_names = ["Overview", "Damage", "Coatings"]

    def on_index_selected(self, x: int, y: int) -> Optional[ActionOrHandler]:
        """Return to main handler when location is selected."""
        return MainGameEventHandler(self.engine)

    def on_render(self, console: tcod.Console) -> None:
        # Highlight tile underneath cursor
        super(SelectIndexHandler, self).on_render(console)

        x, y = self.engine.mouse_location
        x, y = int(x), int(y)
        console.rgb["bg"][x, y] = color.white
        console.rgb["fg"][x, y] = color.black
        
        self.render_detailed_sidebar(console)

    def render_detailed_sidebar(self, console: tcod.Console) -> None:
        """Render detailed information sidebar."""
        x, y = self.engine.mouse_location
        x, y = int(x), int(y)
        
        # Get all items and entities at location
        items_and_entities = self.get_items_and_entities_at(x, y)
        
        if not items_and_entities:
            return
            
        # Clamp detail_index to valid range
        self.detail_index = max(0, min(self.detail_index, len(items_and_entities) - 1))
        current_item = items_and_entities[self.detail_index]
        
        # Determine sidebar position based on cursor location to avoid blocking it
        cursor_x, cursor_y = self.engine.mouse_location
        sidebar_width = 35  # Increased width to accommodate both text and preview
        sidebar_height = 30
        
        # Position sidebar to avoid cursor - prefer right side, but use left if cursor is on right
        if cursor_x < console.width // 2:
            # Cursor on left side, put sidebar on right
            sidebar_x = console.width - sidebar_width
        else:
            # Cursor on right side, put sidebar on left
            sidebar_x = 0
            
        # Position vertically to avoid cursor as well
        if cursor_y < console.height // 2:
            # Cursor in top half, prefer bottom positioning
            sidebar_y = max(2, console.height - sidebar_height - 2)
        else:
            # Cursor in bottom half, prefer top positioning
            sidebar_y = 2
        
        # Draw sidebar frame with parchment styling
        MenuRenderer.draw_parchment_background(console, sidebar_x, sidebar_y, sidebar_width, sidebar_height)
        tab_title = f"Inspect - {self.tab_names[self.current_tab]}"
        MenuRenderer.draw_ornate_border(console, sidebar_x, sidebar_y, sidebar_width, sidebar_height, tab_title)
        
        # Draw binder-style tabs sticking out from the appropriate side
        for i, tab_name in enumerate(self.tab_names):
            tab_y_pos = sidebar_y + 5 + i * 3  # Spacing between tabs
            
            # Position tabs consistently based on sidebar location
            if sidebar_x == 0:  # Sidebar on left side
                tab_x_pos = sidebar_x + sidebar_width  # Right edge of sidebar
            else:  # Sidebar on right side  
                tab_x_pos = sidebar_x - 9  # Left side, ensure they fit onscreen
            
            if i == self.current_tab:
                # Active tab - draw a small bordered box
                console.draw_frame(
                    x=tab_x_pos, y=tab_y_pos, 
                    width=9, height=3,
                    clear=True, fg=color.yellow, bg=(60, 50, 30)
                )
                # Centered text in active tab
                console.print(tab_x_pos + 1, tab_y_pos + 1, tab_name[:7], fg=color.yellow, bg=(60, 50, 30))
            else:
                # Inactive tab - same size as active tab
                console.draw_frame(
                    x=tab_x_pos, y=tab_y_pos, 
                    width=9, height=3,
                    clear=True, fg=color.grey, bg=(30, 25, 15)
                )
                # Centered text in inactive tab
                console.print(tab_x_pos + 1, tab_y_pos + 1, tab_name[:7], fg=color.grey, bg=(30, 25, 15))
        
        # Show current item info at the top
        info_y = sidebar_y + 2
        
        if len(items_and_entities) > 1:
            # Center the item counter without adding extra line spacing
            counter_text = f"{self.detail_index + 1} of {len(items_and_entities)}"
            counter_x = sidebar_x + (sidebar_width - len(counter_text)) // 2
            console.print(counter_x, info_y, counter_text, fg=color.grey, bg=(45, 35, 25))
            # Don't increment info_y here to avoid extra spacing
            
        # Center the visual preview horizontally in the sidebar
        preview_size = 7  # Size of the preview area
        preview_x = sidebar_x + (sidebar_width - preview_size) // 2
        preview_y = info_y + 1
        self.render_visual_preview(console, current_item, x, y, preview_x, preview_y)
        
        # Build scrollable text content below the preview
        text_details_y = preview_y + preview_size + 2  # Leave some space after preview
        text_area_width = sidebar_width - 4  # Use full width minus margins
        
        # Reserve space for compact controls (only 2 lines needed now)
        controls_height = 2
        text_area_height = sidebar_height - (text_details_y - sidebar_y) - controls_height - 1  # Leave space for instructions + margin
        
        # Build complete text content based on current tab
        full_text = self.build_tabbed_content(current_item, text_area_width)
        
        # Render scrollable text with strict height limit
        self.render_scrollable_text(console, full_text, sidebar_x, text_details_y, text_area_width, text_area_height)
            
        # Show compact navigation instructions
        instructions_y = sidebar_y + sidebar_height - controls_height - 1
        console.print(sidebar_x + 2, instructions_y, "Alt+↑↓: Tabs  Alt+←→: Items", fg=color.grey, bg=(45, 35, 25))
        console.print(sidebar_x + 2, instructions_y + 1, "Shift+↑↓: Scroll  Enter: Exit", fg=color.grey, bg=(45, 35, 25))

    def render_visual_preview(self, console: tcod.Console, current_item: dict, look_x: int, look_y: int, preview_x: int, preview_y: int) -> None:
        """Render a visual preview of the object being inspected."""
        # Create a 5x5 preview area
        preview_size = 5
        # Position the frame at the specified location
        frame_x = preview_x
        frame_y = preview_y
        
        # Draw frame around preview
        console.draw_frame(
            x=frame_x, y=frame_y,
            width=preview_size + 2, height=preview_size + 2,
            title="", clear=True,
            fg=color.white, bg=color.black
        )
        
        # Center position in the preview frame (inside the frame borders)
        center_x = frame_x + 1 + preview_size // 2
        center_y = frame_y + 1 + preview_size // 2
        
        # Draw the surrounding area first (for context)
        for dy in range(-preview_size//2, preview_size//2 + 1):
            for dx in range(-preview_size//2, preview_size//2 + 1):
                world_x = look_x + dx
                world_y = look_y + dy
                preview_x = center_x + dx
                preview_y = center_y + dy
                
                # Only draw within the frame boundaries
                if (preview_x > frame_x and preview_x < frame_x + preview_size + 1 and
                    preview_y > frame_y and preview_y < frame_y + preview_size + 1):
                    
                    # Draw tile background
                    if self.engine.game_map.in_bounds(world_x, world_y):
                        tile = self.engine.game_map.tiles[world_x, world_y]
                        
                        # Get tile character and color
                        if self.engine.game_map.visible[world_x, world_y]:
                            # Use light colors for visible tiles
                            char = int(tile['light'][0]) if 'light' in tile.dtype.names else ord('.')
                            fg = tuple(tile['light'][1]) if 'light' in tile.dtype.names else (255, 255, 255)
                            bg = tuple(tile['light'][2]) if 'light' in tile.dtype.names else (0, 0, 0)
                        else:
                            # Use dark colors for non-visible tiles
                            char = int(tile['dark'][0]) if 'dark' in tile.dtype.names else ord('.')
                            fg = tuple(tile['dark'][1]) if 'dark' in tile.dtype.names else (128, 128, 128)
                            bg = tuple(tile['dark'][2]) if 'dark' in tile.dtype.names else (0, 0, 0)
                        
                        # If this is the center tile (the one being looked at), highlight it
                        # But only if there's no entity at this position (entities get their own highlighting)
                        if preview_x == center_x and preview_y == center_y and current_item['type'] == 'tile':
                            # For floor tiles (space or period), highlight the background
                            if char == ord(' ') or char == ord('.') or char == ord('+') or char == ord('/'):
                                bg = color.white
                            else:
                                # For tiles with visible characters, highlight the foreground
                                fg = color.white
                        
                        console.print(preview_x, preview_y, chr(char), fg=fg, bg=bg)
        
        # Draw entities and items at their positions
        for dy in range(-preview_size//2, preview_size//2 + 1):
            for dx in range(-preview_size//2, preview_size//2 + 1):
                world_x = look_x + dx
                world_y = look_y + dy
                preview_x = center_x + dx
                preview_y = center_y + dy
                
                # Only draw within the frame boundaries
                if (preview_x > frame_x and preview_x < frame_x + preview_size + 1 and
                    preview_y > frame_y and preview_y < frame_y + preview_size + 1):
                    
                    # Draw entities
                    for entity in self.engine.game_map.entities:
                        if entity.x == world_x and entity.y == world_y:
                            if hasattr(entity, 'char') and hasattr(entity, 'color'):
                                console.print(preview_x, preview_y, entity.char, fg=entity.color)
                    
                    # Draw items
                    if hasattr(self.engine.game_map, 'items'):
                        for item in self.engine.game_map.items:
                            if item.x == world_x and item.y == world_y:
                                if hasattr(item, 'char') and hasattr(item, 'color'):
                                    console.print(preview_x, preview_y, item.char, fg=item.color)
        
        # Highlight the current object being inspected with a subtle border instead of background
        obj = current_item['object']
        if current_item['type'] == 'entity' and hasattr(obj, 'char') and hasattr(obj, 'color'):
            # Draw with brighter color to make it stand out
            console.print(center_x, center_y, obj.char, fg=color.white)
            # Add subtle corner markers around it
            console.print(center_x - 1, center_y - 1, "┌", fg=color.cyan)
            console.print(center_x + 1, center_y - 1, "┐", fg=color.cyan) 
            console.print(center_x - 1, center_y + 1, "└", fg=color.cyan)
            console.print(center_x + 1, center_y + 1, "┘", fg=color.cyan)
        elif current_item['type'] == 'item' and hasattr(obj, 'char') and hasattr(obj, 'color'):
            # Draw with brighter color
            console.print(center_x, center_y, obj.char, fg=color.white)
            # Add subtle corner markers
            console.print(center_x - 1, center_y - 1, "┌", fg=color.cyan)
            console.print(center_x + 1, center_y - 1, "┐", fg=color.cyan)
            console.print(center_x - 1, center_y + 1, "└", fg=color.cyan)
            console.print(center_x + 1, center_y + 1, "┘", fg=color.cyan)
        elif current_item['type'] == 'tile':
            # Just add corner markers for tiles
            console.print(center_x - 1, center_y - 1, "┌", fg=color.cyan)
            console.print(center_x + 1, center_y - 1, "┐", fg=color.cyan)
            console.print(center_x - 1, center_y + 1, "└", fg=color.cyan)
            console.print(center_x + 1, center_y + 1, "┘", fg=color.cyan)

    def build_tabbed_content(self, current_item: dict, max_width: int) -> list:
        """Build content for the current tab."""
        if self.current_tab == 0:  # Overview
            return self.build_overview_content(current_item, max_width)
        elif self.current_tab == 1:  # Damage
            return self.build_damage_content(current_item, max_width)
        elif self.current_tab == 2:  # Coatings
            return self.build_coatings_content(current_item, max_width)
        return []
    
    def build_overview_content(self, current_item: dict, max_width: int) -> list:
        """Build overview content - general information."""
        lines = []
        
        # Entity handling
        if current_item['type'] == 'entity':
            entity = current_item['object']

            # Get alive or dead status
            if hasattr(entity, 'is_alive') and not entity.is_alive:
                if hasattr(entity, 'sentient') and entity.sentient:
                    lines.append([(entity.name, color.red)])

            # Get name, if known
            if hasattr(entity, 'sentient') and entity.sentient:
                if hasattr(entity, 'name'):
                    if hasattr(entity, 'is_known') and not entity.is_known:
                        # Only print knowledge for entities that have it (NPCs, not chests)
                        if hasattr(entity, 'knowledge'):
                            objective_pronoun = entity.knowledge["pronouns"]["object"].lower()
                            name_text = f"You do not know {objective_pronoun}."
                        else:
                            # For entities without knowledge (like chests), show generic message
                            name_text = f"You don't know what this is."
                        lines.append([(name_text, color.white)])
                    else:
                        lines.append([(entity.name, color.white)])
            else:
                if hasattr(entity, 'name'):
                    lines.append([(entity.name, color.white)])
                    
            # Add entity description
            if hasattr(entity, 'description') and entity.description:
                # Wrap long descriptions to multiple lines
                description_text = entity.description
                words = description_text.split()
                current_line = []
                current_length = 0
                
                for word in words:
                    word_length = len(word)
                    space_length = 1 if current_line else 0
                    
                    if current_length + space_length + word_length <= max_width:
                        current_line.append(word)
                        current_length += space_length + word_length
                    else:
                        # Add completed line and start new line
                        if current_line:
                            lines.append([(' '.join(current_line), color.white)])
                        current_line = [word]
                        current_length = word_length
                
                # Add the last line if it has content
                if current_line:
                    lines.append([(' '.join(current_line), color.white)])

            # Build comprehensive equipment description
            if hasattr(entity, 'equipment') and entity.equipment:
                equipment = entity.equipment
                equipment_parts = []

                # Use body_part_coverage to get actual body part names instead of equipment slot names
                for body_part_name, item in equipment.body_part_coverage.items():
                    if item:
                        if hasattr(item, 'name'):
                            # Format body part name to be more readable
                            formatted_body_part = body_part_name.replace('_', ' ').lower()
                            if equipment_parts:  # Add separator if there's already equipment
                                equipment_parts.append((", ", color.white))
                            equipment_parts.extend([
                                ("wears ", color.white),
                                (item.name, item.rarity_color),
                                (" on its ", color.white),
                                (formatted_body_part, color.white)
                            ])
                
                # Also check grasped items (weapons and shields)
                for body_part_name, item in equipment.grasped_items.items():
                    if item:
                        if hasattr(item, 'name'):
                            # Format body part name to be more readable
                            formatted_body_part = body_part_name.replace('_', ' ').lower()
                            if equipment_parts:  # Add separator if there's already equipment
                                equipment_parts.append((", ", color.white))
                            equipment_parts.extend([
                                ("grasps ", color.white),
                                (item.name, item.rarity_color),
                                (" with its ", color.white),
                                (formatted_body_part, color.light_gray)
                            ])
                
                # Combine all equipment into one line
                if equipment_parts:
                    full_equipment_line = [("It ", color.white)] + equipment_parts + [(".", color.white)]
                    lines.append(full_equipment_line)
            
            # Show container contents if available (e.g., corpse loot) - simple list format
            if hasattr(entity, 'container') and entity.container and entity.container.items:
                container_items = entity.container.items
                if container_items:
                    container_parts = []
                    for i, item in enumerate(container_items):
                        if i > 0:  # Add comma separator between items
                            container_parts.append((", ", color.white))
                        container_parts.append((item.name, item.rarity_color))
                    
                    # Combine into one line with appropriate colors
                    if container_parts:
                        lines.append(container_parts)
                        lines.append([("", color.white)])
                        
            # Add lock status if applicable
            if hasattr(entity, "container") and entity.container.locked:
                lines.append([("It has a lock.", color.red)])
                lines.append([("", color.white)])  # Empty line for spacing

            # Add opinion if sentient
            if hasattr(entity, 'sentient') and entity.sentient:
                if hasattr(entity, "opinion"):
                    if entity.opinion >= 66:
                        opinion_parts = [(f"{(entity.knowledge['pronouns']['subject']).capitalize()} smiles at you", color.green)]
                    elif entity.opinion >= 33:
                        opinion_parts = [(f"{(entity.knowledge['pronouns']['subject']).capitalize()} looks at you unfeelingly.", color.yellow)]
                    else:
                        opinion_parts = [(f"{(entity.knowledge['pronouns']['subject']).capitalize()} frowns at you", color.red)]
                    lines.append(opinion_parts)
                    lines.append([("", color.white)])  # Empty line for spacing
            
            # Add value if applicable
            if hasattr(entity, 'value'):
                if entity.value > 0:
                    value_parts = [("Estimated value: ", color.white), (f"{entity.value} gold.", color.yellow)]
                    lines.append(value_parts)
                    
        # Tile handling
        elif current_item['type'] == 'tile':
            tile_info = current_item['object']
            
            # Add tile information
            lines.append([("This is a ", color.white), (f"{tile_info['name']}.", color.white)])
            
            walkable_text = "You can walk here." if tile_info['walkable'] else "You cannot walk here."
            lines.append([(walkable_text, color.white)])
            
            transparent_text = "You can see through this." if tile_info['transparent'] else "You cannot see through this."
            lines.append([(transparent_text, color.white)])
            
            if tile_info.get('interactable', False):
                interact_text = f"You can interact with this {(tile_info['name']).lower()}."
                lines.append([(interact_text, color.cyan)])
        
        return lines
    
    def build_damage_content(self, current_item: dict, max_width: int) -> list:
        """Build damage-specific content."""
        lines = []
        
        if current_item['type'] == 'entity':
            entity = current_item['object']
            
            # Show body part damage information
            if hasattr(entity, 'body_parts') and entity.body_parts:
                body_parts = entity.body_parts
                damaged_parts = body_parts.get_damaged_parts()
                
                if not damaged_parts:
                    # Wrap "No visible damage" message
                    message = "No visible damage."
                    words = message.split()
                    current_line = []
                    current_length = 0
                    
                    for word in words:
                        word_length = len(word)
                        space_length = 1 if current_line else 0
                        
                        if current_length + space_length + word_length <= max_width:
                            current_line.append(word)
                            current_length += space_length + word_length
                        else:
                            if current_line:
                                lines.append([(' '.join(current_line), color.green)])
                            current_line = [word]
                            current_length = word_length
                    
                    if current_line:
                        lines.append([(' '.join(current_line), color.green)])
                else:
                    lines.append([("Damage Assessment:", color.white)])
                    lines.append([("", color.white)])  # Empty line
                    
                    for part in damaged_parts:
                        injury_text = ""
                        injury_color = color.white
                        
                        if part.damage_level_text == "damaged":
                            injury_text = f"Its {part.name} is damaged."
                            injury_color = color.light_red
                        elif part.damage_level_text == "wounded":
                            injury_text = f"Its {part.name} is wounded."
                            injury_color = color.yellow
                        elif part.damage_level_text == "badly wounded":
                            injury_text = f"Its {part.name} is badly wounded."
                            injury_color = color.orange
                        elif part.damage_level_text == "severely wounded":
                            injury_text = f"Its {part.name} is severely wounded."
                            injury_color = color.orange
                        elif part.damage_level_text == "destroyed":
                            injury_text = f"Its {part.name} is maimed."
                            injury_color = color.red

                        if injury_text:
                            # Wrap the injury text properly
                            words = injury_text.split()
                            current_line = []
                            current_length = 0
                            
                            for word in words:
                                word_length = len(word)
                                space_length = 1 if current_line else 0
                                
                                if current_length + space_length + word_length <= max_width:
                                    current_line.append(word)
                                    current_length += space_length + word_length
                                else:
                                    # Add completed line and start new line
                                    if current_line:
                                        lines.append([(' '.join(current_line), injury_color)])
                                    current_line = [word]
                                    current_length = word_length
                            
                            # Add the last line if it has content
                            if current_line:
                                lines.append([(' '.join(current_line), injury_color)])
                    
                    # Movement impairment with proper wrapping
                    movement_penalty = body_parts.get_movement_penalty()
                    if movement_penalty > 0.7:
                        lines.append([("", color.white)])
                        impairment_text = "It can barely move due to its injuries."
                        # Wrap movement text if needed
                        words = impairment_text.split()
                        current_line = []
                        current_length = 0
                        
                        for word in words:
                            word_length = len(word)
                            space_length = 1 if current_line else 0
                            
                            if current_length + space_length + word_length <= max_width:
                                current_line.append(word)
                                current_length += space_length + word_length
                            else:
                                if current_line:
                                    lines.append([(' '.join(current_line), color.red)])
                                current_line = [word]
                                current_length = word_length
                        
                        if current_line:
                            lines.append([(' '.join(current_line), color.red)])
                    elif movement_penalty > 0.3:
                        lines.append([("", color.white)])
                        impairment_text = "Its movement appears impaired."
                        # Wrap movement text if needed
                        words = impairment_text.split()
                        current_line = []
                        current_length = 0
                        
                        for word in words:
                            word_length = len(word)
                            space_length = 1 if current_line else 0
                            
                            if current_length + space_length + word_length <= max_width:
                                current_line.append(word)
                                current_length += space_length + word_length
                            else:
                                if current_line:
                                    lines.append([(' '.join(current_line), color.yellow)])
                                current_line = [word]
                                current_length = word_length
                        
                        if current_line:
                            lines.append([(' '.join(current_line), color.yellow)])
            else:
                # Wrap "No body part information available" message
                message = "No body part information available."
                words = message.split()
                current_line = []
                current_length = 0
                
                for word in words:
                    word_length = len(word)
                    space_length = 1 if current_line else 0
                    
                    if current_length + space_length + word_length <= max_width:
                        current_line.append(word)
                        current_length += space_length + word_length
                    else:
                        if current_line:
                            lines.append([(' '.join(current_line), color.gray)])
                        current_line = [word]
                        current_length = word_length
                
                if current_line:
                    lines.append([(' '.join(current_line), color.gray)])
        else:
            # Wrap "Damage information not applicable" message
            message = "Damage information not applicable."
            words = message.split()
            current_line = []
            current_length = 0
            
            for word in words:
                word_length = len(word)
                space_length = 1 if current_line else 0
                
                if current_length + space_length + word_length <= max_width:
                    current_line.append(word)
                    current_length += space_length + word_length
                else:
                    if current_line:
                        lines.append([(' '.join(current_line), color.gray)])
                    current_line = [word]
                    current_length = word_length
            
            if current_line:
                lines.append([(' '.join(current_line), color.gray)])
            
        return lines
    
    def build_coatings_content(self, current_item: dict, max_width: int) -> list:
        """Build coating-specific content."""
        lines = []
        
        if current_item['type'] == 'entity':
            entity = current_item['object']
            
            # Show coating information for all body parts
            if hasattr(entity, 'body_parts') and entity.body_parts:
                from liquid_system import LiquidType
                coated_parts = [part for part in entity.body_parts.body_parts.values() if part.coating != LiquidType.NONE]
                
                if not coated_parts:
                    # Wrap "No coatings detected" message
                    message = "No coatings detected."
                    words = message.split()
                    current_line = []
                    current_length = 0
                    
                    for word in words:
                        word_length = len(word)
                        space_length = 1 if current_line else 0
                        
                        if current_length + space_length + word_length <= max_width:
                            current_line.append(word)
                            current_length += space_length + word_length
                        else:
                            if current_line:
                                lines.append([(' '.join(current_line), color.white)])
                            current_line = [word]
                            current_length = word_length
                    
                    if current_line:
                        lines.append([(' '.join(current_line), color.white)])
                else:
                    lines.append([("Coating Analysis:", color.white)])
                    lines.append([("", color.white)])  # Empty line
                    
                    for part in coated_parts:
                        coating_color = part.coating.get_display_color()
                        coating_name = part.coating.get_display_name()
                        
                        # Build the coating text with proper wrapping
                        coating_text = f"Its {part.name} is coated in {coating_name}."
                        words = coating_text.split()
                        current_line = []
                        current_length = 0
                        
                        for word in words:
                            word_length = len(word)
                            space_length = 1 if current_line else 0
                            
                            if current_length + space_length + word_length <= max_width:
                                current_line.append(word)
                                current_length += space_length + word_length
                            else:
                                # Add completed line and start new line
                                if current_line:
                                    lines.append([(' '.join(current_line), coating_color)])
                                current_line = [word]
                                current_length = word_length
                        
                        # Add the last line if it has content
                        if current_line:
                            lines.append([(' '.join(current_line), coating_color)])
            else:
                # Wrap "No body part information available" message
                message = "No body part information available."
                words = message.split()
                current_line = []
                current_length = 0
                
                for word in words:
                    word_length = len(word)
                    space_length = 1 if current_line else 0
                    
                    if current_length + space_length + word_length <= max_width:
                        current_line.append(word)
                        current_length += space_length + word_length
                    else:
                        if current_line:
                            lines.append([(' '.join(current_line), color.gray)])
                        current_line = [word]
                        current_length = word_length
                
                if current_line:
                    lines.append([(' '.join(current_line), color.gray)])
                
        elif current_item['type'] == 'tile':
            # Add liquid coating information if present
            if hasattr(self.engine.game_map, 'liquid_system'):
                # Get the tile coordinates from the mouse location
                x, y = self.engine.mouse_location
                coating = self.engine.game_map.liquid_system.get_coating(int(x), int(y))
                if coating:
                    liquid_name = coating.liquid_type.get_display_name()
                    liquid_color = coating.liquid_type.get_display_color()
                    
                    # Build and wrap ground coating text properly
                    coating_text = f"Coated with {liquid_name}."
                    words = coating_text.split()
                    current_line = []
                    current_length = 0
                    
                    for word in words:
                        word_length = len(word)
                        space_length = 1 if current_line else 0
                        
                        if current_length + space_length + word_length <= max_width:
                            current_line.append(word)
                            current_length += space_length + word_length
                        else:
                            if current_line:
                                lines.append([(' '.join(current_line), liquid_color)])
                            current_line = [word]
                            current_length = word_length
                    
                    if current_line:
                        lines.append([(' '.join(current_line), liquid_color)])
                else:
                    # Wrap "No ground coating present" message
                    message = "No ground coating present."
                    words = message.split()
                    current_line = []
                    current_length = 0
                    
                    for word in words:
                        word_length = len(word)
                        space_length = 1 if current_line else 0
                        
                        if current_length + space_length + word_length <= max_width:
                            current_line.append(word)
                            current_length += space_length + word_length
                        else:
                            if current_line:
                                lines.append([(' '.join(current_line), color.white)])
                            current_line = [word]
                            current_length = word_length
                    
                    if current_line:
                        lines.append([(' '.join(current_line), color.white)])
            else:
                # Wrap "No coating system available" message
                message = "No coating system available."
                words = message.split()
                current_line = []
                current_length = 0
                
                for word in words:
                    word_length = len(word)
                    space_length = 1 if current_line else 0
                    
                    if current_length + space_length + word_length <= max_width:
                        current_line.append(word)
                        current_length += space_length + word_length
                    else:
                        if current_line:
                            lines.append([(' '.join(current_line), color.gray)])
                        current_line = [word]
                        current_length = word_length
                
                if current_line:
                    lines.append([(' '.join(current_line), color.gray)])
        
        return lines
    
    def render_scrollable_text(self, console: tcod.Console, text_lines: list, x: int, y: int, width: int, height: int) -> None:
        """Render text with scrolling support and strict height capping."""
        if not text_lines or height <= 0:
            return
            
        # Limit scroll offset to valid range
        max_scroll = max(0, len(text_lines) - height)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))
        
        # Calculate which lines to display based on scroll offset
        start_line = self.scroll_offset
        end_line = min(len(text_lines), start_line + height)
        
        # Display the visible lines with strict height bounds checking
        current_y = y
        max_y = y + height  # Absolute maximum Y coordinate
        
        for i, line_idx in enumerate(range(start_line, end_line)):
            if line_idx < len(text_lines) and current_y < max_y:
                lines_to_wrap = text_lines[line_idx]
                # Calculate remaining height for this line
                remaining_height = max_y - current_y
                if remaining_height <= 0:
                    break
                    
                # Update current_y with the returned y position from print_wrapped_colored_text
                new_y = print_wrapped_colored_text(console=console, x=x+1, y=current_y, text=lines_to_wrap, max_width=width)
                
                # Ensure we don't exceed the height boundary
                if new_y >= max_y:
                    break
                    
                current_y = new_y + 1  # Add spacing between logical lines
                
                # Double-check height boundary
                if current_y >= max_y:
                    break
        
        # Show scroll indicators if there's more content
        if start_line > 0:
            console.print(x + width - 3, y, "↑", fg=color.yellow)
        if end_line < len(text_lines):
            console.print(x + width - 3, y + height - 1, "↓", fg=color.yellow)
        if end_line < len(text_lines):
            console.print(x + width - 3, y + height - 1, "↓", fg=color.yellow)



    def get_items_and_entities_at(self, x: int, y: int) -> list:
        """Get all items and entities at the specified location (only if visible)."""
        results = []
        
        # Only return information for tiles that are currently visible
        if not self.engine.game_map.in_bounds(x, y) or not self.engine.game_map.visible[x, y]:
            return results
        
        # Add entities (actors and items) at location
        for entity in self.engine.game_map.entities:
            if entity.x == x and entity.y == y:
                # Use unknown_name for actors if not known, but real name for items
                display_name = entity.name
                if hasattr(entity, 'unknown_name') and hasattr(entity, 'ai'):
                    # This is an actor (has AI), check if known
                    if hasattr(entity, 'is_known') and entity.is_known:
                        display_name = entity.name
                    else:
                        display_name = entity.unknown_name

                if hasattr(entity, "is_alive") and not entity.is_alive:
                    display_name = f"Corpse of {display_name}"

                
                results.append({
                    'name': display_name,
                    'type': 'entity',
                    'object': entity
                })

        
                

                    
        # Add tile information
        if self.engine.game_map.in_bounds(x, y):
            tile = self.engine.game_map.tiles[x, y]
            tile_info = {
                'name': tile['name'] if 'name' in tile.dtype.names else 'Unknown Tile',
                'walkable': tile['walkable'] if 'walkable' in tile.dtype.names else False,
                'transparent': tile['transparent'] if 'transparent' in tile.dtype.names else False,
                'interactable': tile['interactable'] if 'interactable' in tile.dtype.names else False,
            }
            results.append({
                'name': tile_info['name'],
                'type': 'tile',
                'object': tile_info
            })
            
        return results

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        """Handle keyboard input for inspection interface."""
        key = event.sym
        modifier = event.mod
        
        # Handle tab switching with Alt + up/down first
        if key == tcod.event.KeySym.UP and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            # Switch to previous tab and reset scroll
            self.current_tab = (self.current_tab - 1) % len(self.tab_names)
            LookHandler.last_selected_tab = self.current_tab  # Remember for next time
            self.scroll_offset = 0
            sounds.play_ui_move_sound()  # Play menu navigation sound
            return None
        elif key == tcod.event.KeySym.DOWN and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            # Switch to next tab and reset scroll
            self.current_tab = (self.current_tab + 1) % len(self.tab_names)
            LookHandler.last_selected_tab = self.current_tab  # Remember for next time
            self.scroll_offset = 0
            sounds.play_ui_move_sound()  # Play menu navigation sound
            return None
        # Handle item cycling with Alt + left/right
        elif key == tcod.event.KeySym.LEFT and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            # Cycle to previous item and reset scroll
            x, y = self.engine.mouse_location
            items_and_entities = self.get_items_and_entities_at(x, y)
            if items_and_entities:
                self.detail_index = (self.detail_index - 1) % len(items_and_entities)
                self.scroll_offset = 0  # Reset scroll when changing items
            return None
        elif key == tcod.event.KeySym.RIGHT and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            # Cycle to next item and reset scroll
            x, y = self.engine.mouse_location
            items_and_entities = self.get_items_and_entities_at(x, y)
            if items_and_entities:
                self.detail_index = (self.detail_index + 1) % len(items_and_entities)
                self.scroll_offset = 0  # Reset scroll when changing items
            return None
        # Handle scrolling with Shift + up/down
        elif key == tcod.event.KeySym.UP and modifier & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT):
            # Scroll text up
            self.scroll_offset = max(0, self.scroll_offset - 1)
            return None
        elif key == tcod.event.KeySym.DOWN and modifier & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT):
            # Scroll text down (limit will be handled in render)
            self.scroll_offset += 1
            return None
        elif key == tcod.event.KeySym.ESCAPE:
            # Exit inspection mode
            return MainGameEventHandler(self.engine)
        elif key == tcod.event.KeySym.RETURN or key == tcod.event.KeySym.KP_ENTER or key == tcod.event.KeySym.SPACE:
            # Exit inspection mode on confirm keys
            return MainGameEventHandler(self.engine)
        
        # Use parent handler for normal movement (arrow keys without modifiers)
        return super().ev_keydown(event)

    def ev_mousewheel(self, event: tcod.event.MouseWheel) -> Optional[ActionOrHandler]:
        """Handle mouse wheel for tab switching with Ctrl."""
        modifier = event.mod
        
        # Handle tab switching with Alt + scroll wheel
        if modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            if event.y > 0:  # Scroll up
                self.current_tab = (self.current_tab - 1) % len(self.tab_names)
                LookHandler.last_selected_tab = self.current_tab  # Remember for next time
                self.scroll_offset = 0
                sounds.play_ui_move_sound()  # Play menu navigation sound
            elif event.y < 0:  # Scroll down
                self.current_tab = (self.current_tab + 1) % len(self.tab_names)
                LookHandler.last_selected_tab = self.current_tab  # Remember for next time
                self.scroll_offset = 0
                sounds.play_ui_move_sound()  # Play menu navigation sound
            return None
        
        # Pass to parent for normal wheel handling
        return super().ev_mousewheel(event)

class SingleRangedAttackHandler(SelectIndexHandler):
    # Handles targeting single enemy

    def __init__(
            self, engine: Engine, callback: Callable[[Tuple[int, int]], Optional[Action]]
    ):
        super().__init__(engine)

        self.callback = callback

    def on_index_selected(self, x: int, y: int) -> Optional[Action]:
        return self.callback((x,y))

class AreaRangedAttackHandler(SelectIndexHandler):
    #Handles targeting an area with a radius, any entity inside is damaged

    def __init__(
            self,
            engine: Engine,
            radius: int,
            callback: Callable[[Tuple[int, int]], Optional[Action]],
    ):
        super().__init__(engine)

        self.radius = radius
        self.callback = callback

    def on_render(self, console: tcod.Console) -> None:
        # Highlights tile under cursor
        super().on_render(console)

        x, y = self.engine.mouse_location

        #draw rectangle around area
        console.draw_frame(
            x=x - self.radius - 1,
            y=y - self.radius - 1,
            width=(self.radius * 2) + 3,
            height=(self.radius * 2) + 3,
            fg=color.red,
            clear=False,
        )

    def on_index_selected(self, x: int, y: int) -> Optional[Action]:
        return self.callback((x,y))



class MainGameEventHandler(EventHandler):

    def ev_keydown(
            self, event: tcod.event.KeyDown
            ) -> Optional[ActionOrHandler]:
        
        action: Optional[Action] = None

        key = event.sym
        modifier = event.mod

        player = self.engine.player

        if key == tcod.event.K_PERIOD and modifier & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT
        ):
            return actions.TakeStairsAction(player)
        elif key == tcod.event.K_SLASH and modifier & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT
        ):            
            # TODO HELP MENU
            return HelpMenuHandler(self.engine)
        # F2 toggles debug mode
        elif key == tcod.event.K_F2:
            self.engine.message_log.add_message("Debug mode toggled.", color.green)


        # KEYBINDS

            self.engine.debug = not self.engine.debug
        
        # F3 shows limb stats debug
        elif key == tcod.event.K_F3:
            return EntityDebugHandler(self.engine)
        
        # Directional attack (Shift + movement key, including diagonals)
        elif key in MOVE_KEYS and modifier & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT):
            dx, dy = MOVE_KEYS[key]
            preferred_target = getattr(player, 'current_attack_type', None)

            # Convert preferred target tag to specific body part for ranged attacks
            if preferred_target:
                # Find all body parts with the preferred target tag  
                import random
                matching_parts = []
                if hasattr(target_actor, 'body_parts') and target_actor.body_parts:
                    for part_type, body_part in target_actor.body_parts.body_parts.items():
                        if preferred_target in body_part.tags:
                            matching_parts.append(part_type)
                
                # Randomly select one matching part if any found
                if matching_parts:
                    target_part = random.choice(matching_parts)
            else:
                if hasattr(target_actor, 'body_parts') and target_actor.body_parts:
                    # Target random part
                    target_part = random.choice(list(target_actor.body_parts.body_parts.keys()))

            equipment = getattr(player, 'equipment', None)
            held_items = []
            if equipment:
                held_items = list(equipment.grasped_items.values()) + list(equipment.equipped_items.values())

            has_bow = False
            has_arrow = False
            has_melee_weapon = False

            for item in held_items:
                if not item or not hasattr(item, 'equippable') or not item.equippable:
                    continue

                eq_type_name = item.equippable.equipment_type.name
                item_tags = {tag.lower() for tag in getattr(item, 'tags', [])}

                if eq_type_name == 'RANGED' or 'bow' in item_tags:
                    has_bow = True
                if eq_type_name == 'PROJECTILE' or 'arrow' in item_tags or 'ammunition' in item_tags:
                    has_arrow = True
                if eq_type_name == 'WEAPON':
                    has_melee_weapon = True

            if has_bow and has_arrow:
                action = actions.RangedAction(player, dx, dy, target_part)
            elif has_melee_weapon:
                action = actions.MeleeAction(player, dx, dy, target_part)
            else:
                self.engine.message_log.add_message(
                    "No suitable weapon readied for directional attack.", color.impossible
                )

        # Dodge change direction (Ctrl + arrow key direction OR numpad direction)
        elif key == tcod.event.K_LEFT and modifier & (tcod.event.KMOD_LCTRL | tcod.event.KMOD_RCTRL):
            player.preferred_dodge_direction = ("west")
        elif key == tcod.event.K_RIGHT and modifier & (tcod.event.KMOD_LCTRL | tcod.event.KMOD_RCTRL):
            player.preferred_dodge_direction = ("east")
        elif key == tcod.event.K_UP and modifier & (tcod.event.KMOD_LCTRL | tcod.event.KMOD_RCTRL):
            player.preferred_dodge_direction = ("north")
        elif key == tcod.event.K_DOWN and modifier & (tcod.event.KMOD_LCTRL | tcod.event.KMOD_RCTRL):
            player.preferred_dodge_direction = ("south")
        
        # Interact action (ALT + arrow key direction OR numpad direction)
        elif key == tcod.event.K_LEFT and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, -1, 0)
        elif key == tcod.event.K_RIGHT and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, 1, 0)
        elif key == tcod.event.K_UP and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, 0, -1)
        elif key == tcod.event.K_DOWN and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, 0, 1)
        elif key == tcod.event.K_KP_1 and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, -1, 1)
        elif key == tcod.event.K_KP_2 and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, 0, 1)
        elif key == tcod.event.K_KP_3 and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, 1, 1)
        elif key == tcod.event.K_KP_4 and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, -1, 0)
        elif key == tcod.event.K_KP_6 and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, 1, 0)
        elif key == tcod.event.K_KP_7 and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, -1, -1)
        elif key == tcod.event.K_KP_8 and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, 0, -1)
        elif key == tcod.event.K_KP_9 and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
            action = InteractAction(player, 1, -1)


#       Dev key, press K to kill all enemies on the map
#        elif key == tcod.event.KeySym.K:
#            for entity in self.engine.game_map.entities:
#                try:
#                    if entity.fighter and entity is not self.engine.player:
#                        entity.fighter.hp = 0
#                except Exception:
#                    pass
#                self.engine.message_log.add_message("You feel a sudden surge of power!", color.red)
            
        elif key in MOVE_KEYS:
            dx, dy = MOVE_KEYS[key]
            
            # Check if player has a preferred attack target and if there's an enemy to attack
            preferred_target = getattr(player, 'current_attack_type', None)
            target_x = player.x + dx
            target_y = player.y + dy
            target_actor = self.engine.game_map.get_actor_at_location(target_x, target_y)
            
            if preferred_target and target_actor and target_actor != player:
                # Use targeted attack if we have a preference and there's an enemy
                if hasattr(target_actor, 'body_parts') and target_actor.body_parts:
                    # Convert preferred target tag to specific body part
                    target_part = None
                    if preferred_target:
                        # Find all body parts with the preferred target tag
                        import random
                        matching_parts = []
                        for part_type, body_part in target_actor.body_parts.body_parts.items():
                            if preferred_target in body_part.tags:
                                matching_parts.append(part_type)
                        
                        # Randomly select one matching part if any found
                        if matching_parts:
                            target_part = random.choice(matching_parts)
                    
                    if target_part:
                        from actions import MeleeAction
                        action = MeleeAction(player, dx, dy, target_part)
                    else:
                        # Fallback to normal attack if body part not found
                        action = BumpAction(player, dx, dy)
                else:
                    # Enemy has no body parts, use normal attack
                    action = BumpAction(player, dx, dy)
            else:
                # No preference set or no enemy, use normal movement/attack
                action = BumpAction(player, dx, dy)
        elif key in WAIT_KEYS:
            action = WaitAction(player)
        elif key ==tcod.event.K_ESCAPE:
            raise SystemExit()
        elif key == tcod.event.KeySym.V:
            return HistoryViewer(self.engine)
        elif key == tcod.event.KeySym.G:
            action = PickupAction(player)
        elif key == tcod.event.KeySym.R:
            return ScrollActivateHandler(self.engine)
        elif key == tcod.event.KeySym.I:
            return InventoryActivateHandler(self.engine)
        # Throw Handler
        elif key == tcod.event.KeySym.T:
            return ThrowSelectionHandler(self.engine)
        elif key == tcod.event.KeySym.E:
            # Visual equipment interface
            from equipment_ui import EquipmentUI
            return EquipmentUI(self.engine)
        # elif key == tcod.event.KeySym.U:
        #     return InventoryEquipHandler(self.engine)
        elif key == tcod.event.KeySym.Q:
            return QuaffActivateHandler(self.engine)
        elif key == tcod.event.KeySym.D:
            return InventoryDropHandler(self.engine)
        elif key == tcod.event.KeySym.C:
            from character_sheet_ui import CharacterScreen
            return CharacterScreen(self.engine)
        # t key for targeting mode
        elif key == tcod.event.KeySym.A:
            return AttackModeHandler(self.engine)
        elif key == tcod.event.KeySym.S:
            return LookHandler(self.engine)


        
        # No valid key was pressed
        # print(action)
        return action
    
class GameOverEventHandler(EventHandler):
    def on_quit(self) -> None:
        """Handle exiting out of a finished game."""
        if os.path.exists("savegame.sav"):
            os.remove("savegame.sav")  # Deletes the active save file.
        raise exceptions.QuitWithoutSaving()  # Avoid saving a finished game.

    def ev_quit(self, event: tcod.event.Quit) -> None:
        self.on_quit()

    def ev_keydown(self, event: tcod.event.KeyDown) -> None:
        if event.sym == tcod.event.K_ESCAPE:
            self.on_quit()
    
CURSOR_Y_KEYS = {
    tcod.event.KeySym.UP: -1,
    tcod.event.KeySym.DOWN: 1,
    tcod.event.KeySym.PAGEUP: -10,
    tcod.event.KeySym.PAGEDOWN: 10,
}


class HistoryViewer(EventHandler):
    """Print the history on a larger window which can be navigated."""

    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.log_length = len(engine.message_log.messages)
        self.cursor = self.log_length - 1

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)  # Draw the main state as the background.

        log_console = tcod.Console(console.width - 6, console.height - 6)
        
        from render_functions import MenuRenderer
        
        # Draw parchment background
        MenuRenderer.draw_parchment_background(log_console, 0, 0, log_console.width, log_console.height)

        # Draw a frame with a custom banner title.
        log_console.draw_frame(0, 0, log_console.width, log_console.height)
        log_console.print_box(
            0, 0, log_console.width, 1, "┤Message history├", alignment=tcod.CENTER
        )

        # Render the message log using the cursor parameter.
        # Use height - 5 to account for the +2 offset in render_messages and avoid clipping into border
        self.engine.message_log.render_messages(
            log_console,
            1,
            1,
            log_console.width - 2,
            log_console.height - 5,
            self.engine.message_log.messages[: self.cursor + 1],
        )
        log_console.blit(console, 3, 3)

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[MainGameEventHandler]:
        # Smooth scrolling that clamps at edges instead of wrapping around
        if event.sym in CURSOR_Y_KEYS:
            adjust = CURSOR_Y_KEYS[event.sym]
            new_cursor = self.cursor + adjust
            # Only update cursor if it's within valid bounds
            if 0 <= new_cursor < self.log_length:
                self.cursor = new_cursor
        elif event.sym == tcod.event.K_HOME:
            self.cursor = 0  # Move directly to the top message.
        elif event.sym == tcod.event.K_END:
            self.cursor = self.log_length - 1  # Move directly to the last message.
        else:  # Any other key moves back to the main game state.
            return MainGameEventHandler(self.engine)
        return None

class EntityDebugHandler(SelectIndexHandler):
    """Debug handler with cursor movement for inspecting any entity's body parts."""
    
    def __init__(self, engine: Engine):
        super().__init__(engine)  # This sets cursor to player position
        
    def on_index_selected(self, x: int, y: int) -> Optional[ActionOrHandler]:
        """Return to main handler when location is selected."""
        return MainGameEventHandler(self.engine)
    
    def on_render(self, console: tcod.Console) -> None:
        # First render the game world and highlight cursor position
        super().on_render(console)
        
        # Get cursor position and find entity to debug
        cursor_x, cursor_y = self.engine.mouse_location
        cursor_x, cursor_y = int(cursor_x), int(cursor_y)
        
        # Highlight cursor position
        console.rgb["bg"][cursor_x, cursor_y] = color.white
        console.rgb["fg"][cursor_x, cursor_y] = color.black
        
        # Find entity to inspect at cursor location
        target_entity = None
        if self.engine.game_map.in_bounds(cursor_x, cursor_y):
            # Look for actors first, then items
            for entity in self.engine.game_map.entities:
                if entity.x == cursor_x and entity.y == cursor_y:
                    if (hasattr(entity, 'fighter') and entity.fighter) or (hasattr(entity, 'body_parts') and entity.body_parts):
                        target_entity = entity
                        break
        
        # Determine debug window position to avoid cursor
        window_width = 55
        window_height = 30
        
        # Position window to avoid cursor
        if cursor_x < console.width // 2:
            # Cursor on left, put window on right
            debug_x = console.width - window_width - 1
        else:
            # Cursor on right, put window on left  
            debug_x = 1
            
        if cursor_y < console.height // 2:
            # Cursor in top half, put window in bottom
            debug_y = console.height - window_height - 1
        else:
            # Cursor in bottom half, put window in top
            debug_y = 1
        
        # Draw debug window frame
        title = "DEBUG: Entity Inspector" if target_entity else "DEBUG: Tile Inspector"
        console.draw_frame(
            x=debug_x, y=debug_y, width=window_width, height=window_height,
            title=title, clear=True,
            fg=color.yellow, bg=color.black
        )
        
        # Show info
        info_y = debug_y + 2
        
        if target_entity:
            # Entity name and basic info
            entity_name = getattr(target_entity, 'name', 'Unknown')
            if target_entity == self.engine.player:
                console.print(debug_x + 2, info_y, f"PLAYER: {entity_name}", fg=color.green)
            else:
                console.print(debug_x + 2, info_y, f"ENTITY: {entity_name}", fg=color.white)
            info_y += 1
            
            console.print(debug_x + 2, info_y, f"Position: ({cursor_x}, {cursor_y})", fg=color.gray)
            info_y += 2
            
            # Show body parts if available
            if hasattr(target_entity, 'body_parts') and target_entity.body_parts:
                console.print(debug_x + 2, info_y, "BODY PARTS:", fg=color.yellow)
                info_y += 1
                
                body_parts = target_entity.body_parts
                
                for part_type, part in body_parts.body_parts.items():
                    # Part name and HP
                    hp_text = f"{part.current_hp}/{part.max_hp}"
                    hp_ratio = body_parts.get_part_health_ratio(part)
                    
                    # Color based on health
                    if hp_ratio <= 0:
                        hp_color = color.red
                    elif hp_ratio <= 0.25:
                        hp_color = color.orange
                    elif hp_ratio <= 0.5:
                        hp_color = color.yellow
                    elif hp_ratio <= 0.75:
                        hp_color = color.light_gray
                    else:
                        hp_color = color.green
                    
                    # Part info line
                    part_line = f"{part.name:<14} {hp_text:>6} ({hp_ratio*100:.0f}%)"
                    console.print(debug_x + 2, info_y, part_line, fg=hp_color)
                    
                    # Additional status info
                    status_info = []
                    if part.is_vital:
                        status_info.append("VITAL")
                    if part.can_grasp:
                        status_info.append("GRASP")
                    if part.is_destroyed:
                        status_info.append("DESTROYED")
                    elif hp_ratio <= 0.25:
                        status_info.append("DISABLED")
                    
                    if status_info:
                        console.print(debug_x + 35, info_y, " ".join(status_info), fg=color.cyan)
                    
                    info_y += 1
                    
                    # Don't overflow window
                    if info_y >= debug_y + window_height - 8:
                        console.print(debug_x + 2, info_y, "...(more parts)", fg=color.gray)
                        break
                
                # Show movement penalty if applicable
                if hasattr(body_parts, 'get_movement_penalty'):
                    movement_penalty = body_parts.get_movement_penalty()
                    if movement_penalty > 0:
                        info_y += 1
                        penalty_text = f"Movement Penalty: {movement_penalty*100:.0f}%"
                        penalty_color = color.red if movement_penalty > 0.5 else color.yellow
                        console.print(debug_x + 2, info_y, penalty_text, fg=penalty_color)
                        info_y += 1
            else:
                console.print(debug_x + 2, info_y, "No body parts system", fg=color.red)
                info_y += 2
            
            # Show fighter stats if available
            if hasattr(target_entity, 'fighter') and target_entity.fighter:
                console.print(debug_x + 2, info_y, "FIGHTER STATS:", fg=color.yellow)
                info_y += 1
                console.print(debug_x + 2, info_y, f"HP: {target_entity.fighter.hp}/{target_entity.fighter.max_hp}", fg=color.white)
                info_y += 1
                console.print(debug_x + 2, info_y, f"Defense: {target_entity.fighter.defense}", fg=color.white)
                info_y += 1
                console.print(debug_x + 2, info_y, f"Power: {target_entity.fighter.power}", fg=color.white)
                info_y += 1
            
            # Show AI info if available
            if hasattr(target_entity, 'ai') and target_entity.ai:
                console.print(debug_x + 2, info_y, f"AI: {type(target_entity.ai).__name__}", fg=color.cyan)
                info_y += 1
        else:
            # Show tile information instead
            console.print(debug_x + 2, info_y, "TILE INFORMATION:", fg=color.cyan)
            info_y += 1
            console.print(debug_x + 2, info_y, f"Position: ({cursor_x}, {cursor_y})", fg=color.gray)
            info_y += 2
            
            # Get tile information
            if self.engine.game_map.in_bounds(cursor_x, cursor_y):
                tile = self.engine.game_map.tiles[cursor_x, cursor_y]
                
                # Show visibility
                if self.engine.game_map.visible[cursor_x, cursor_y]:
                    console.print(debug_x + 2, info_y, "Visibility: VISIBLE", fg=color.green)
                else:
                    console.print(debug_x + 2, info_y, "Visibility: NOT VISIBLE", fg=color.red)
                info_y += 1
                
                # Show tile properties
                if tile['walkable']:
                    console.print(debug_x + 2, info_y, "Walkable: YES", fg=color.green)
                else:
                    console.print(debug_x + 2, info_y, "Walkable: NO", fg=color.red)
                info_y += 1
                
                if tile['transparent']:
                    console.print(debug_x + 2, info_y, "Transparent: YES", fg=color.green)
                else:
                    console.print(debug_x + 2, info_y, "Transparent: NO", fg=color.red)
                info_y += 1
                
                # Show tile character and color
                if self.engine.game_map.visible[cursor_x, cursor_y]:
                    char = int(tile['light'][0])
                    fg_color = tuple(tile['light'][1])
                    bg_color = tuple(tile['light'][2])
                    console.print(debug_x + 2, info_y, f"Char: '{chr(char)}' ({char})", fg=color.white)
                    info_y += 1
                    console.print(debug_x + 2, info_y, f"FG Color: {fg_color}", fg=color.white)
                    info_y += 1
                    console.print(debug_x + 2, info_y, f"BG Color: {bg_color}", fg=color.white)
                    info_y += 1
                info_y += 1
                
                # Show items at this location 
                items_here = [e for e in self.engine.game_map.entities 
                             if e.x == cursor_x and e.y == cursor_y and not (hasattr(e, 'fighter') or hasattr(e, 'ai'))]
                
                if items_here:
                    console.print(debug_x + 2, info_y, "ITEMS HERE:", fg=color.yellow)
                    info_y += 1
                    for item in items_here[:5]:  # Show max 5 items
                        console.print(debug_x + 4, info_y, f"- {item.name}", fg=color.white)
                        info_y += 1
                    if len(items_here) > 5:
                        console.print(debug_x + 4, info_y, f"...and {len(items_here)-5} more", fg=color.gray)
                        info_y += 1
                    info_y += 1
                
                # Show liquid coating if present
                if hasattr(self.engine.game_map, 'liquid_system'):
                    coating = self.engine.game_map.liquid_system.get_coating(cursor_x, cursor_y)
                    if coating:
                        liquid_name = coating.liquid_type.get_display_name().title()
                        console.print(debug_x + 2, info_y, f"Coating: {liquid_name}", fg=color.cyan)
                        info_y += 1
            else:
                console.print(debug_x + 2, info_y, "OUT OF BOUNDS", fg=color.red)
        
        # Instructions
        instructions_y = debug_y + window_height - 4
        console.print(debug_x + 2, instructions_y, "Arrow Keys: Move cursor", fg=color.light_gray)
        console.print(debug_x + 2, instructions_y + 1, "Shift+Arrow: Move faster", fg=color.light_gray)
        if target_entity:
            console.print(debug_x + 2, instructions_y + 2, "Mode: Entity inspection", fg=color.green)
        else:
            console.print(debug_x + 2, instructions_y + 2, "Mode: Tile inspection", fg=color.cyan)
        console.print(debug_x + 2, instructions_y + 3, "Enter/ESC: Exit debug", fg=color.light_gray)
    
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        """Handle key input for debug mode with cursor movement."""
        key = event.sym
        
        if key == tcod.event.KeySym.ESCAPE:
            return MainGameEventHandler(self.engine)
        
        # Use parent's key handling for movement and other functionality
        return super().ev_keydown(event)


class HelpMenuHandler(AskUserEventHandler):
    # CONTROL MENU
    TITLE = "Controls"

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)

        if self.engine.player.x <= 30:
            x = 40
        else:
            x = 0

        y = 0

        text = f"\nESC: Escape / Save and Quit \n?: Control Menu \nV: Message Log \nG: Pick Up Object \nI: Use/Equip Items \nE: Equipment UI \nD: Drop Items \nC: Character Menu \n/: Look Around \nB: Inspect Body Parts \nT: Set Attack Mode \nShift+Move: Attack (Bow+Arrow = Ranged, else Melee)"
        width = max(
            max(len(line) for line in self.TITLE.splitlines()),
            max(len(line) for line in text.splitlines())
        ) + 2

        height = text.count("\n") + 3

        console.draw_frame(
            x=x,
            y=y,
            width = width,
            height = height,
            title=self.TITLE,
            clear=True,
            fg=(255,255,255),
            bg=(0,0,0)
        )

        console.print(
            x=x + 1, y=y + 1, string=text
        )


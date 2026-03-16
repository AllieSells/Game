from __future__ import annotations

import os
import json
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
from components.dialogue_generator import ConversationNode
from components.effect import BurningEffect
import engine
import exceptions
from render_functions import MenuRenderer

from text_utils import *
import sounds


if TYPE_CHECKING:
    from engine import Engine
    from entity import Item, Actor
    from components.container import Container







MOVE_KEYS = {
    # Arrow keys.
    tcod.event.KeySym.W: (0, -1),
    tcod.event.KeySym.S: (0, 1),
    tcod.event.KeySym.A: (-1, 0),
    tcod.event.KeySym.D: (1, 0),
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
    
    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> Optional[ActionOrHandler]:
        """Handle mouse movement - update engine mouse location."""

        mouse_pos_x = event.tile.x
        mouse_pos_y = event.tile.y
        self.engine.mouse_x = int(mouse_pos_x)
        self.engine.mouse_y = int(mouse_pos_y)
        #print(self.engine.mouse_x, self.engine.mouse_y)
        
        return None

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[ActionOrHandler]:
        """Handle mouse clicks during main game - just print for now."""
        if event.button == tcod.event.BUTTON_LEFT:
            self.engine.mouse_held = True
        
    
        return None

    def ev_mousebuttonup(self, event: tcod.event.MouseButtonUp):
        if event.button == tcod.event.BUTTON_LEFT:
            self.engine.mouse_held = False

        return None
    
    def on_render(self, console: tcod.Console) -> None:
        raise NotImplementedError()
    
    def ev_quit(self, event: tcod.event.Quit) -> Optional[Action]:
        raise SystemExit()


    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[BaseEventHandler]:
        """Any key returns to the parent handler."""
        return self.parent


class EventHandler(BaseEventHandler):
    def __init__(self, engine: Engine):
        self.alt_held = False
        self.engine = engine
        # Initialize turn manager if not already set
        if not hasattr(engine, 'turn_manager') or engine.turn_manager is None:
            from turn_manager import TurnManager
            engine.turn_manager = TurnManager(engine)
        self.mouse_pos = (0, 0)

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
        
        # If we received an event handler instead of an action, return it directly
        if isinstance(action, BaseEventHandler):
            return action
            
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

    def on_render(self, console: tcod.Console) -> None:
        self.engine.render(console)

    def render_faded(self, console: tcod.Console, menu_x: int = None, menu_y: int = None, menu_width: int = None, menu_height: int = None) -> None:
        # Fades the current console to create a dimmed background effect for menus
        # Excludes the menu area from fading if menu bounds are provided
        fade_alpha = 0.4  # Fade strength (0.0 = no fade, 1.0 = completely faded)
        fade_color = (20, 20, 30)  # Dark blue-gray tint
        
        for x in range(console.width):
            for y in range(console.height):
                # Skip fading pixels that are within the menu bounds
                if (menu_x is not None and menu_y is not None and 
                    menu_width is not None and menu_height is not None):
                    if (menu_x <= x < menu_x + menu_width and 
                        menu_y <= y < menu_y + menu_height):
                        continue
                
                existing_color = console.bg[x, y]
                # Safe color blending using floating point math
                blended_color = (
                    int(existing_color[0] * (1 - fade_alpha) + fade_color[0] * fade_alpha),
                    int(existing_color[1] * (1 - fade_alpha) + fade_color[1] * fade_alpha),
                    int(existing_color[2] * (1 - fade_alpha) + fade_color[2] * fade_alpha),
                )
                console.bg[x, y] = blended_color
    
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
        self.engine.cursor_hint = None
        return MainGameEventHandler(self.engine)


class CharacterScreenEventHandler(EventHandler):
    TITLE = "Character Sheet"

    def __init__(self, engine):
        super().__init__(engine)
        # Collapsible sections state (kept for future use). Sections removed per request.
        self.collapsed_sections = set()
        


class TradeEventHandler(AskUserEventHandler):
    # Container UI recycled for trading. Modified.
    def __init__(self, engine: Engine, container: Container):
        super().__init__(engine)
        # Innit NPC being interacted with
        self.container = container
        # Skip filter, not needed

        # Selected index for arrow navigation
        self.selected_index: int = 0
        # Which inventory is active: "Player" or NPC name
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
        y = 10
        
        # Fade the background except for the container menu
        super().render_faded(console, x, y, total_width, height)

        # Draw main fantasy parchment background
        MenuRenderer.draw_parchment_background(console, x, y, total_width, height)
        
        # Draw ornate main border
        npc_color = getattr(self.container.parent, 'color', 'Container')
        container_name = getattr(self.container.parent, 'name', 'Container')
        is_corpse = getattr(self.container.parent, 'type', None) == 'Dead'
        title = f"Corpse" if is_corpse else f"Trading with {container_name}"
        MenuRenderer.draw_ornate_border(console, x, y, total_width, height, title)

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
        
        # Panel headers
        player_header = "You"
        container_header = f"{container_name}"
        
        # Center headers in panels
        player_header_x = left_x + (panel_width - len(player_header)) // 2
        container_header_x = right_x + (panel_width - len(container_header)) // 2
        
        console.print(player_header_x, left_y + 1, player_header, fg=(255, 215, 0), bg=panel_bg)
        console.print(container_header_x, right_y + 1, container_header, fg=(color.teal), bg=panel_bg)
        
        # Active panel indicator
        if self.menu == "Player":
            console.print(left_x + 1, left_y + 1, "☺", fg=(255, 215, 0), bg=panel_bg)
        else:
            console.print(right_x + 1, right_y + 1, "☺", fg=(npc_color), bg=panel_bg)

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
                    
                item = group['item']
                display_name = group['display_name']
                is_equipped = self.engine.player.equipment.item_is_equipped(item)
                is_selected = i == self.selected_index and self.menu == "Player"

                item_value = int(item.value * .75)
                item_string = f"• {display_name} ({item_value}gp)"
                if len(item_string) > panel_width - 2:
                    item_string = f"• {display_name[:panel_width - 12]}... ({item_value}gp)"
                if is_equipped:
                    item_string = f"{item_string} (e)"

                # Draw with selection highlighting
                if is_selected:
                    # Selection background
                    for hx in range(panel_width - 4):
                        console.print(left_x + 2 + hx, item_start_y + i, " ", bg=(80, 60, 30))
                    console.print(left_x + 1, item_start_y + i, item_string, fg=item.rarity_color, bg=(80, 60, 30))
                else:
                    console.print(left_x + 1, item_start_y + i, item_string, fg=item.rarity_color, bg=panel_bg)
        else:
            console.print(left_x + 1, item_start_y, "~ Empty ~", fg=(120, 100, 80), bg=panel_bg)

        # Draw container inventory items  
        if number_of_container_items > 0:
            for i, item in enumerate(container_items):
                if item_start_y + i >= right_y + panel_height - 1:
                    break  # Don't draw outside panel
                    
                is_selected = i == self.selected_index and self.menu == "Container"

                item_value = int(item.value * 1.5)
                item_string = f"• {item.name} ({item_value}gp)"
                if len(item_string) > panel_width - 2:
                    item_string = f"• {item.name[:panel_width - 12]}... ({item_value}gp)"

                # Draw with selection highlighting
                if is_selected:
                    # Selection background
                    for hx in range(panel_width - 4):
                        console.print(right_x + 2 + hx, item_start_y + i, " ", bg=(80, 60, 30))
                    console.print(right_x + 1, item_start_y + i, item_string, fg=item.rarity_color, bg=(80, 60, 30))
                else:
                    console.print(right_x + 1, item_start_y + i, item_string, fg=item.rarity_color, bg=panel_bg)
        else:
            console.print(right_x + 4, item_start_y, "~ Empty ~", fg=(120, 100, 80), bg=panel_bg)
        
        # Instructions footer
        if self.menu == "Player":
            instructions = "[Tab] Switch Panel · [↑↓] Navigate ·  [Space] Sell · [Esc] Close"
        else:
            instructions = "[Tab] Switch Panel · [↑↓] Navigate ·  [Space] Buy · [Esc] Close"
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
                    self.engine.message_log.add_message("Trade failed.", color.error)
                    return self

                self.engine.player.inventory.items.remove(item)
                # Move item into the container and update its parent so
                # later logic (consumption, transfers) sees the correct owner.
                self.container.items.append(item)
                try:
                    item.parent = self.container
                except Exception:
                    pass

                if hasattr(item, "drop_sound") and item.drop_sound is not None:
                    try:
                        item.drop_sound()
                    except Exception as e:
                        self.engine.debug_log(f"Error calling drop sound: {e}", handler=type(self).__name__, event="trade")
                sounds.play_equip_manycoins_sound()
                self.engine.player.gold += int(item.value * .75)
                
                self.engine.message_log.add_message(f"You sell the {item.name}.")
            except Exception as e:
                self.engine.debug_log(f"Transfer failed with exception: {e}", handler=type(self).__name__, event="trade")
                self.engine.debug_log(traceback.format_exc(), handler=type(self).__name__, event="trade")
                self.engine.message_log.add_message(f"Could not transfer {item.name}.", color.error)
        else:
            # Transfer from container to player
            try:
                if self.engine.player.gold < int(item.value * 1.5):
                    self.engine.message_log.add_message("You don't have enough gold.", color.error)
                    return self
                else:
                    self.container.items.remove(item)
                    if len(self.engine.player.inventory.items) > self.engine.player.inventory.capacity:
                        self.engine.message_log.add_message("Your inventory is full.", color.error)
                        # Return item to container
                        self.container.items.append(item)
                    else:   
                        # Add to player inventory and update parent link.
                        self.engine.player.inventory.items.append(item)
                        try:
                            item.parent = self.engine.player.inventory
                        except Exception:
                            pass
                        
                        # Play item pickup sound if it exists
                        if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                            
                            try:
                                item.pickup_sound()
                                
                            except Exception as e:
                                self.engine.debug_log(f"Error calling pickup sound: {e}", handler=type(self).__name__, event="trade")
                        else:
                            self.engine.debug_log(f"No pickup sound for {item}", handler=type(self).__name__, event="trade")
                        sounds.play_equip_manycoins_sound()
                        self.engine.player.gold -= int(item.value * 1.5)

                        self.engine.message_log.add_message(f"You buy the {item.name}.")
            except Exception:
                self.engine.debug_log(traceback.format_exc(), handler=type(self).__name__, event="trade")
                self.engine.message_log.add_message(f"Could not transfer {item.name} to {self.container.name}.", color.error)
        # Return back to container handler
        return self
    



class DialogueEventHandler(AskUserEventHandler):
    """Handles dialogue interactions with NPCs with hierarchical menu system."""
    
    def __init__(self, engine: Engine, npc: Actor):
        super().__init__(engine)
        self.npc = npc
        # Initialize dialogue system
        from components.dialogue_generator import ConversationNode
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
                    {"text": "Trade", "action": "trade", "target": "trade"},
                    {"text": "Farewell", "action": "exit"}
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

        if self.npc.dialogue_context and "Identity" in self.npc.dialogue_context:
            self.engine.debug_log(f"NPC identity revealed: {self.npc.name}", handler=type(self).__name__, event="dialogue")
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
        width = 40
        height = 20
        x = (self.engine.game_map.width - width) // 2
        y = (self.engine.game_map.height - height) // 2
        
        # Fade the background except for the dialogue area
        super().render_faded(console, x, y, width, height)

        current_menu_data = self.menu_structure[self.current_menu]
        
        # Draw parchment background and ornate border
        MenuRenderer.draw_parchment_background(console, x, y, width, height)
        MenuRenderer.draw_ornate_border(console, x, y, width, height, current_menu_data["title"])
        
        # Display current dialogue if available
        if hasattr(self, 'current_dialogue') and self.current_dialogue:
            dialogue_text = self.current_dialogue[0]
            # Use wrap_colored_text to get properly wrapped lines, then print each line
            from text_utils import wrap_colored_text, print_colored_text
            max_dialogue_width = width - 4  # Account for dialogue box margins
            wrapped_lines = wrap_colored_text(dialogue_text, max_dialogue_width, default_color=color.teal)
            
            current_y = y + 2
            for line_parts in wrapped_lines:
                if current_y >= y + height - 3:  # Don't overflow the dialogue box
                    break
                print_colored_text(console, x + 2, current_y, line_parts)
                current_y += 1
        
        # Display menu options in inventory-style format
        start_y = y + 5
        options = current_menu_data["options"]
        
        for i, option in enumerate(options):
            option_y = start_y + i
            if option_y >= y + height - 3:  # Leave room for instructions
                break
            
            # Generate letter key for this option
            option_text = f"• {option['text']}"
            
            # Draw selection marker for arrow navigation (like inventory)
            marker = ">" if i == self.selected_index else " "
            
            # Highlight selected option with white background and black text
            if i == self.selected_index:
                # Draw white background for the entire line
                line_width = len(marker + option_text) + 2  # Extra space for padding
                for j in range(line_width):
                    console.print(x + 1 + j, option_y, " ", fg=color.white, bg=color.selected_bronze)
                # Draw the text on top with black text
                console.print(x + 1, option_y, marker, fg=color.white, bg=color.selected_bronze)
                console.print(x + 2, option_y, option_text, fg=color.white, bg=color.selected_bronze)
            else:
                console.print(x + 1, option_y, marker)
                console.print(x + 2, option_y, option_text, fg=color.white)
        
        # Instructions
        instructions_y = y + height - 3
        console.print(x + 1, instructions_y+1, "↑↓: Navigate  Enter: Select  Esc: Exit", fg=color.grey)

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

        if action == "trade":
            if self.npc.tradable == True:
                return TradeEventHandler(self.engine, self.npc.inventory)
            else:
                context = ["RefuseTrade"]
                self.npc.dialogue_context = context
                self.current_dialogue = self.dialogue.generate_dialogue(
                    character=self.npc, context=context
                )
                
                display_name = self.npc.name if self.npc.is_known else self.npc.unknown_name
                self.engine.message_log.add_message(f"{display_name}: {self.current_dialogue[0]}", color.blue)
                
        
        elif action == "exit":
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
        
        # Fade the background except for the level up menu
        super().render_faded(console, x, y, width, height)

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
        self.menu: str = "Container"
        # Scroll offsets for each panel
        self.player_scroll: int = 0
        self.container_scroll: int = 0

    def on_render(self, console: tcod.Console) -> None:
        # Renders inventory menu displaying items in both inventories with fantasy styling
        super().on_render(console)
        player_groups = self.engine.player.inventory.get_display_groups()
        container_items = list(self.container.items)
        number_of_player_items = len(player_groups)
        number_of_container_items = len(container_items)

        # Enhanced window sizing for beautiful layout
        total_width = 70
        height = 25
        
        # Position window
        x = (console.width - total_width) // 2
        y = 10
        self.x = x
        self.y = y
        
        # Fade the background except for the container menu
        super().render_faded(console, x, y, total_width, height)

        # Draw main fantasy parchment background
        MenuRenderer.draw_parchment_background(console, x, y, total_width, height)
        
        # Draw ornate main border
        container_name = getattr(self.container.parent, 'name', 'Container')
        is_corpse = getattr(self.container.parent, 'type', None) == 'Dead'
        title = f"Corpse" if is_corpse else f"Container: {container_name}"
        MenuRenderer.draw_ornate_border(console, x, y, total_width, height, title)

        # Calculate panel dimensions
        panel_width = (total_width - 6) // 2  # Leave space for divider and margins
        panel_height = height - 6
        
        # Left panel (Player inventory)
        left_x = x + 2
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
        divider_x = left_x + panel_width
        #self._draw_decorative_divider(console, divider_x, left_y, panel_height)
        
        # Panel headers
        player_header = "Your Inventory"
        container_header = f"Corpse" if is_corpse else f"{container_name}"
        
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
        max_visible = panel_height - 4  # rows available for items

        # Clamp scroll offsets
        self.player_scroll = max(0, min(self.player_scroll, max(0, number_of_player_items - max_visible)))
        self.container_scroll = max(0, min(self.container_scroll, max(0, number_of_container_items - max_visible)))

        if number_of_player_items > 0:
            visible_player_groups = player_groups[self.player_scroll : self.player_scroll + max_visible]
            for i, group in enumerate(visible_player_groups):
                real_index = i + self.player_scroll
                item_key = chr(ord("a") + real_index)
                item = group['item']
                display_name = group['display_name']
                is_equipped = self.engine.player.equipment.item_is_equipped(item)
                is_selected = real_index == self.selected_index and self.menu == "Player"

                item_string = f"{item_key}) {display_name}"
                if is_equipped:
                    item_string = f"{item_string} (e)"

                # Draw with selection highlighting
                if is_selected:
                    for hx in range(panel_width - 4):
                        console.print(left_x + 2 + hx, item_start_y + i, " ", bg=(80, 60, 30))
                    console.print(left_x + 2, item_start_y + i, "✦", fg=(255, 223, 127), bg=(80, 60, 30))
                    console.print(left_x + 4, item_start_y + i, item_string, fg=item.rarity_color, bg=(80, 60, 30))
                else:
                    console.print(left_x + 4, item_start_y + i, item_string, fg=item.rarity_color, bg=panel_bg)
            # Scroll indicators
            if self.player_scroll > 0:
                console.print(left_x + panel_width - 2, item_start_y, "↑", fg=(255, 215, 0), bg=panel_bg)
            if self.player_scroll + max_visible < number_of_player_items:
                console.print(left_x + panel_width - 2, item_start_y + len(visible_player_groups) - 1, "↓", fg=(255, 215, 0), bg=panel_bg)
        else:
            console.print(left_x + 4, item_start_y, "~ Empty ~", fg=(120, 100, 80), bg=panel_bg)

        # Draw container inventory items  
        if number_of_container_items > 0:
            visible_container_items = container_items[self.container_scroll : self.container_scroll + max_visible]
            for i, item in enumerate(visible_container_items):
                real_index = i + self.container_scroll
                item_key = chr(ord("a") + real_index)
                is_selected = real_index == self.selected_index and self.menu == "Container"
                item_string = f"{item_key}) {item.name}"

                # Draw with selection highlighting
                if is_selected:
                    for hx in range(panel_width - 4):
                        console.print(right_x + 2 + hx, item_start_y + i, " ", bg=(80, 60, 30))
                    console.print(right_x + 2, item_start_y + i, "✦", fg=(255, 223, 127), bg=(80, 60, 30))
                    console.print(right_x + 4, item_start_y + i, item_string, fg=item.rarity_color, bg=(80, 60, 30))
                else:
                    console.print(right_x + 4, item_start_y + i, item_string, fg=item.rarity_color, bg=panel_bg)
            # Scroll indicators
            if self.container_scroll > 0:
                console.print(right_x + panel_width - 2, item_start_y, "↑", fg=(255, 215, 0), bg=panel_bg)
            if self.container_scroll + max_visible < number_of_container_items:
                console.print(right_x + panel_width - 2, item_start_y + len(visible_container_items) - 1, "↓", fg=(255, 215, 0), bg=panel_bg)
        else:
            console.print(right_x + 4, item_start_y, "~ Empty ~", fg=(120, 100, 80), bg=panel_bg)
        
        # Instructions footer
        instructions = "[Tab] Switch Panel · [↑↓] Navigate ·  [Enter] Transfer · [Esc] Close"
        inst_x = x + (total_width - len(instructions)) // 2
        console.print(inst_x, y + height - 2, instructions, fg=(180, 140, 100))

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> None:
        """Allow mouse hover to change selection."""
        super().ev_mousemotion(event)
        if not hasattr(self, 'x') or not hasattr(self, 'y'):
            return None

        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)

        panel_width = (70 - 6) // 2  # 32
        left_x = self.x + 2
        right_x = self.x + 3 + panel_width + 2
        item_start_y = self.y + 6

        player_groups = self.engine.player.inventory.get_display_groups()
        container_items = list(self.container.items)

        # Check if mouse is over the left (player) panel item area
        max_visible = 15
        if left_x <= mouse_x < left_x + panel_width and item_start_y <= mouse_y < item_start_y + min(len(player_groups), max_visible):
            hovered_index = (mouse_y - item_start_y) + self.player_scroll
            if hovered_index != self.selected_index or self.menu != "Player":
                sounds.play_ui_move_sound()
            self.menu = "Player"
            self.selected_index = hovered_index
            self.engine.cursor_hint = None

        # Check if mouse is over the right (container) panel item area
        elif right_x <= mouse_x < right_x + panel_width and item_start_y <= mouse_y < item_start_y + min(len(container_items), max_visible):
            hovered_index = (mouse_y - item_start_y) + self.container_scroll
            if hovered_index != self.selected_index or self.menu != "Container":
                sounds.play_ui_move_sound()
            self.menu = "Container"
            self.selected_index = hovered_index
            self.engine.cursor_hint = "bag"
        else:
            self.engine.cursor_hint = None


    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[ActionOrHandler]:
        if event.button != tcod.event.BUTTON_LEFT:
            return None
        self.engine.mouse_held = True
        if not hasattr(self, 'x') or not hasattr(self, 'y'):
            return None

        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        panel_width = (70 - 6) // 2  # 32
        left_x = self.x + 2
        right_x = self.x + 3 + panel_width + 2
        item_start_y = self.y + 6

        player_groups = self.engine.player.inventory.get_display_groups()
        container_items = list(self.container.items)

        max_visible = 15
        if left_x <= mouse_x < left_x + panel_width and item_start_y <= mouse_y < item_start_y + min(len(player_groups), max_visible):
            clicked_index = (mouse_y - item_start_y) + self.player_scroll
            self.menu = "Player"
            self.selected_index = clicked_index
            return self.on_item_selected(player_groups[clicked_index]['item'])
        elif right_x <= mouse_x < right_x + panel_width and item_start_y <= mouse_y < item_start_y + min(len(container_items), max_visible):
            clicked_index = (mouse_y - item_start_y) + self.container_scroll
            self.menu = "Container"
            self.selected_index = clicked_index
            return self.on_item_selected(container_items[clicked_index])
        return None

    def ev_mousewheel(self, event: tcod.event.MouseWheel) -> Optional[ActionOrHandler]:
        max_visible = 15  # matches panel_height - 4
        if self.menu == "Player":
            total = len(self.engine.player.inventory.get_display_groups())
            max_scroll = max(0, total - max_visible)
            if event.y < 0:  # wheel down → scroll list down
                self.player_scroll = min(max_scroll, self.player_scroll + 1)
            elif event.y > 0:  # wheel up → scroll list up
                self.player_scroll = max(0, self.player_scroll - 1)
        else:
            total = len(self.container.items)
            max_scroll = max(0, total - max_visible)
            if event.y < 0:
                self.container_scroll = min(max_scroll, self.container_scroll + 1)
            elif event.y > 0:
                self.container_scroll = max(0, self.container_scroll - 1)
        return None

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        player = self.engine.player
        key = event.sym
        modifier = event.mod

        # Get display groups for selection
        player_groups = self.engine.player.inventory.get_display_groups()

        # Tab shifts active menu
        if key == tcod.event.K_TAB:
            self.engine.cursor_hint = None
            return MainGameEventHandler(self.engine)
        # Arrow-key navigation
        if key == tcod.event.K_UP:
            if self.selected_index > 0:
                sounds.play_ui_move_sound()
            self.selected_index = max(0, self.selected_index - 1)
            # Auto-scroll to keep selection visible
            _mv = 15
            if self.menu == "Player" and self.selected_index < self.player_scroll:
                self.player_scroll = self.selected_index
            elif self.menu == "Container" and self.selected_index < self.container_scroll:
                self.container_scroll = self.selected_index
            return None
        elif key == tcod.event.K_DOWN:
            if self.menu == "Player":
                max_index = max(0, len(player_groups) - 1)
            else:
                max_index = max(0, len(self.container.items) - 1)
            if self.selected_index < max_index:
                sounds.play_ui_move_sound()
            self.selected_index = min(max_index, self.selected_index + 1)
            # Auto-scroll to keep selection visible
            _mv = 15
            if self.menu == "Player" and self.selected_index >= self.player_scroll + _mv:
                self.player_scroll = self.selected_index - _mv + 1
            elif self.menu == "Container" and self.selected_index >= self.container_scroll + _mv:
                self.container_scroll = self.selected_index - _mv + 1
            return None
        elif key in CONFIRM_KEYS:
            if self.menu == "Player":
                if not player_groups:
                    return None
                return self.on_item_selected(player_groups[self.selected_index]['item'])
            else:
                if not self.container.items:
                    return None
                return self.on_item_selected(self.container.items[self.selected_index])

        # Letter selection
        index = key - tcod.event.KeySym.A
        if 0 <= index <= 26:
            try:
                if self.menu == "Player":
                    selected_item = player_groups[index]['item']
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
                self.engine.debug_log(f"Inventory = {[item.name for item in self.engine.player.inventory.items]}", handler=type(self).__name__, event="trade")
                try:
                    item.parent = self.container
                except Exception:
                    pass

                if hasattr(item, "drop_sound") and item.drop_sound is not None:
                    try:
                        item.drop_sound()
                    except Exception as e:
                        self.engine.debug_log(f"Error calling drop sound: {e}", handler=type(self).__name__, event="trade")
                
                self.engine.message_log.add_message(f"You transfer the {item.name}.")
            except Exception as e:
                self.engine.debug_log(f"Transfer failed with exception: {e}", handler=type(self).__name__, event="trade")
                self.engine.debug_log(traceback.format_exc(), handler=type(self).__name__, event="trade")
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
                                self.engine.debug_log(f"Error calling pickup sound: {e}", handler=type(self).__name__, event="trade")
                        return self
                    # Add to player inventory and update parent link.
                    self.engine.player.inventory.items.append(item)
                    try:
                        item.parent = self.engine.player.inventory
                    except Exception:
                        pass
                    
                    # Play item pickup sound if it exists
                    if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                      
                        try:
                            item.pickup_sound()
                   
                        except Exception as e:
                            self.engine.debug_log(f"Error calling pickup sound: {e}", handler=type(self).__name__, event="trade")
                    else:
                        self.engine.debug_log(f"No pickup sound for {item}", handler=type(self).__name__, event="trade")

                    self.engine.message_log.add_message(f"You take the {item.name}.")
            except Exception:
                self.engine.debug_log(traceback.format_exc(), handler=type(self).__name__, event="trade")
                self.engine.message_log.add_message(f"Could not transfer {item.name} to {self.container.name}.", color.error)
        # Return back to container handler
        return self

    def _draw_decorative_divider(self, console, x: int, y: int, height: int):
        """Draw a smooth decorative vertical divider."""
        divider_fg = (139, 105, 60)  # Bronze
        accent_fg = (205, 164, 87)   # Gold accent
        bg = (color.parchment_dark)            # Slightly lighter than parchment
        
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
        height = max(24, number_of_items_in_inventory + 10)  # Taller for descriptions

        # Position based on player location
        if self.engine.player.x <= 30:
            x = 3
        else:
            x = max(0, console.width - total_width - 3)
        y = 1

        # Cache render coordinates for mouse hover
        self._render_x = x
        self._render_y = y
        self._render_items_x = x + sidebar_width + 1
        
        # Fade the background except for the inventory menu
        super().render_faded(console, x, y, total_width, height)

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
            console.print(preview_x + 2, y + 8, "~ No item selected ~", fg=(120, 100, 80))
        
        # Draw elegant instruction footer
        instructions = "✦ [↑↓] Navigate · [←→] Category · [Space] Use · [Esc] Return ✦"
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
        title_text = "Item"
        title_x = x + (width - len(title_text)) // 2
        console.print(title_x, title_y-1, title_text, fg=(255, 215, 0), bg=preview_bg)
        
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
        
        # Item name with better positioning - use full available width and rarity color
        name_y = grid_y + 4
        item_name = item.name
        # Use almost full width (width-2 for borders, width-3 for safety margin)
        max_name_length = width - 3
        if len(item_name) > max_name_length:
            item_name = item_name[:max_name_length - 3] + "..."
        console.print(x + 2, name_y, item_name, fg=item.rarity_color, bg=preview_bg)
        
        # Stats section with better spacing
        stats_y = name_y + 1
        stat_lines = self._get_stat_comparison(item)
        
        # Always show at least basic info if no stats
        if not stat_lines:
            max_item_name_length = width - 8  # Account for "Item: " prefix
            item_display = item.name[:max_item_name_length] if len(item.name) > max_item_name_length else item.name
            stat_lines = [
                f"Item: {item_display}",
                "Select to interact"
            ]
        
        # Display stat lines with full width utilization
        current_stat_y = stats_y
        for i, stat_line in enumerate(stat_lines[:6]):  # Show 6 stat lines max to leave room for description
            if current_stat_y >= y + height - 8:  # Leave room for description
                break
            # Use almost full available width (accounting for borders and small margin)
            max_stat_length = width - 3
            if len(stat_line) > max_stat_length:
                stat_line = stat_line[:max_stat_length - 3] + "..."
            
            # Use appropriate colors for equipment status
            if stat_line.strip() == "Equipped":
                console.print(x + 2, current_stat_y, stat_line, fg=(0, 255, 0), bg=preview_bg)  # Bright green
            elif stat_line.strip() == "Not equipped":
                console.print(x + 2, current_stat_y, stat_line, fg=(255, 150, 150), bg=preview_bg)  # Light red
            else:
                console.print(x + 2, current_stat_y, stat_line, fg=(200, 170, 120), bg=preview_bg)
            current_stat_y += 1
        
        # Add description section
        desc_y = current_stat_y + 1
        if desc_y < y + height - 3:  # Make sure we have room
            # Get item description with skill-based viewing
            description = item.get_description(self.engine.player)
            if description and description.strip():
                # Add separator line
                console.print(x + 2, desc_y, "─" * (width - 4), fg=(139, 105, 60), bg=preview_bg)
                desc_y += 1
                
                # Wrap and display description
                wrapped_lines = self._wrap_text(description, width - 4)
                for desc_line in wrapped_lines[:4]:  # Show up to 4 lines of description
                    if desc_y >= y + height - 2:
                        break
                    console.print(x + 2, desc_y, desc_line, fg=(180, 160, 130), bg=preview_bg)
                    desc_y += 1
    
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
        return " "  # Circle for misc items
    
    def _wrap_text(self, text: str, width: int) -> list:
        """Wrap text to fit within the specified width."""
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            # If adding this word would exceed width, start a new line
            if current_line and len(current_line) + 1 + len(word) > width:
                lines.append(current_line)
                current_line = word
            else:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
        
        # Add the last line if it exists
        if current_line:
            lines.append(current_line)
        
        return lines
    
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
            print_colored_markup(console, x, stats_y + i, stat_line, default_color=(192, 192, 192))
    
    def _get_item_display_char(self, item) -> str:
        """Get the character to display in the 3x3 preview."""
        return item.char
    
    def _get_item_color(self, item):
        """Get the actual color object for item display based on type and status."""
        import color
        
        # More robust equipment check - avoid false positives
        is_equipped = False
        if hasattr(self.engine.player, 'equipment') and hasattr(item, 'equippable'):
            is_equipped = self.engine.player.equipment.item_is_equipped(item)
            
        # Use the item's actual color if available, otherwise fall back to type-based colors
        if hasattr(item, 'color') and item.color:
            return item.color
        elif is_equipped:
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
        if hasattr(self.engine.player, 'equipment') and hasattr(item, 'equippable'):
            is_equipped = self.engine.player.equipment.item_is_equipped(item)
            
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
                # Abbreviate type names to save space
                type_abbreviations = {
                    "Main Hand": "Weapon",
                    "Off Hand": "Shield", 
                    "Chest": "Armor",
                    "Head": "Helmet",
                    "Legs": "Leggings",
                    "Feet": "Boots"
                }
                type_display = type_abbreviations.get(type_name, type_name)
                lines.append(type_display)
                
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
                        defense = item.equippable.get_defense()
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
                        defense = item.equippable.get_defense()
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
                lines.append("Not equipped")
                
        elif getattr(item, "consumable", None):
            lines.append("Consumable")
            
            # Healing items
            if hasattr(item.consumable, "amount") and "heal" in item.name.lower():
                heal_amount = item.consumable.amount
                current_hp = player.fighter.hp
                max_hp = player.fighter.max_hp
                potential_hp = min(max_hp, current_hp + heal_amount)
                lines.append(f"Heals: {heal_amount}")
                lines.append(f"HP: {current_hp}→{potential_hp}")
            

        
        else:
            lines.append("Miscellaneous")
            lines.append("Press D to drop")
        
        # Limit to available space
        return lines[:6]

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> None:
        """Allow mouse hover to change selection."""
        super().ev_mousemotion(event)
        if not hasattr(self, '_render_items_x') or not hasattr(self, '_render_y'):
            return None

        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        items_x = self._render_items_x
        items_start_y = self._render_y + 4
        items_width = 32

        item_groups = self.engine.player.inventory.get_display_groups()
        category_filter = self.categories[self.current_category][1]
        filtered_groups = [g for g in item_groups if self.item_filter(g['item']) and category_filter(g['item'])]

        if (items_x <= mouse_x < items_x + items_width and
                items_start_y <= mouse_y < items_start_y + len(filtered_groups)):
            hovered_index = mouse_y - items_start_y
            if hovered_index != self.selected_index:
                sounds.play_ui_move_sound()
            self.selected_index = hovered_index

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[ActionOrHandler]:
        if event.button != tcod.event.BUTTON_LEFT:
            return None
        self.engine.mouse_held = True
        if not hasattr(self, '_render_items_x') or not hasattr(self, '_render_y'):
            return self.on_exit()

        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        items_x = self._render_items_x
        items_start_y = self._render_y + 4
        items_width = 32

        item_groups = self.engine.player.inventory.get_display_groups()
        category_filter = self.categories[self.current_category][1]
        filtered_groups = [g for g in item_groups if self.item_filter(g['item']) and category_filter(g['item'])]

        if (items_x <= mouse_x < items_x + items_width and
                items_start_y <= mouse_y < items_start_y + len(filtered_groups)):
            clicked_index = mouse_y - items_start_y
            self.selected_index = clicked_index
            return self.on_item_selected(filtered_groups[clicked_index]['item'])

        return self.on_exit()

    def ev_mousewheel(self, event: tcod.event.MouseWheel) -> Optional[ActionOrHandler]:
        if event.y < 0:
            self.current_category = min(len(self.categories) - 1, self.current_category + 1)
        elif event.y > 0:
            self.current_category = max(0, self.current_category - 1)
        else:
            return None
        self.selected_index = 0
        sounds.play_ui_move_sound()
        return None

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
            selected_group = filtered_groups[getattr(self, "selected_index", 0)]
            selected_item = selected_group['item']
            return self.on_item_selected(selected_item)

        # Letter selection still supported but operates on the filtered list

        return super().ev_keydown(event)

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        if item.consumable:
            action_or_handler = item.consumable.get_action(self.engine.player)
            if action_or_handler:
                if hasattr(action_or_handler, 'perform'):
                    action_or_handler.perform()
                    return None
                else:
                    return action_or_handler
            return None
        elif item.equippable:
            action = actions.EquipAction(self.engine.player, item)
            action.perform()
            return None
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
        if item.consumable:
            action_or_handler = item.consumable.get_action(self.engine.player)
            if action_or_handler:
                if hasattr(action_or_handler, 'perform'):
                    try:
                        action_or_handler.perform()
                    except exceptions.Impossible as exc:
                        self.engine.message_log.add_message(exc.args[0], color.impossible)
                    return None
                else:
                    return action_or_handler
            return None
        else:
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

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> None:
        AskUserEventHandler.ev_mousemotion(self, event)
        self.engine.mouse_location = int(self.engine.mouse_x), int(self.engine.mouse_y)

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
        tile_x, tile_y = int(event.tile.x), int(event.tile.y)
        if self.engine.game_map.in_bounds(tile_x, tile_y):
            if event.button == 1:
                return self.on_index_selected(tile_x, tile_y)
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
        self.engine.debug_log(f"Player attack mode set to: {selected_mode}", handler=type(self).__name__, event="combat")
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


class SpellCastingHandler(AskUserEventHandler):
    """Handle spell selection and casting with hotkey support."""
    
    TITLE = "Cast Spell"
    
    # Spell registry for easy spell management
    SPELL_REGISTRY = {}
    
    @classmethod
    def _initialize_spell_registry(cls):
        """Initialize the spell registry with available spells."""
        if not cls.SPELL_REGISTRY:  # Only initialize once
            from components.spells import DarkvisionSpell, TeleportSpell, PoisonSpraySpell
            
            cls.SPELL_REGISTRY = {
                "Darkvision": DarkvisionSpell,
                "Teleport": TeleportSpell,
                "Poison Spray": PoisonSpraySpell,
                # Add new spells here: "SpellName": SpellClass,
            }
    
    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.selected_index = 0
        self.scroll_offset = 0
        
        # Initialize spell registry
        self._initialize_spell_registry()
        
        # Get available spells from player
        self.available_spells = self._get_available_spells()
        
        # Initialize quick cast slots if not present
        if not hasattr(self.engine.player, 'quickcast_slots'):
            self.engine.player.quickcast_slots = [None] * 9
        
        # Create assignment keys (1-9 for assigning to slots)
        self.assignment_keys = {
            tcod.event.KeySym.N1: 0,
            tcod.event.KeySym.N2: 1,
            tcod.event.KeySym.N3: 2,
            tcod.event.KeySym.N4: 3,
            tcod.event.KeySym.N5: 4,
            tcod.event.KeySym.N6: 5,
            tcod.event.KeySym.N7: 6,
            tcod.event.KeySym.N8: 7,
            tcod.event.KeySym.N9: 8,
        }
    
    def _get_available_spells(self) -> list:
        """Get list of spells the player can cast."""
        player = self.engine.player
        if not hasattr(player, 'known_spells') or not player.known_spells:
            return []
        
        # known_spells now contains spell objects directly
        return player.known_spells
    
    def _can_cast_spell(self, spell) -> bool:
        """Check if player has enough mana to cast the spell."""
        return self.engine.player.mana >= spell.mana_cost
    
    def _get_spell_school_color(self, school) -> Tuple[int, int, int]:
        """Get color based on spell school/type."""
        if school == "evocation":
            return (255, 150, 150) 
        elif school == "conjuration":
            return (150, 150, 255)  
        elif school == "divination":
            return (255, 255, 150)
        elif school == "abjuration":
            return (255, 255, 255)
        elif school == "enchantment":
             return (150, 255, 150)
        elif school == "transmutation":
            return (255, 150, 150)
        elif school == "illusion":
            return (255, 150, 255)
        else:
             return (200, 200, 200) 
    def on_render(self, console: tcod.Console) -> None:
        """Render the spell casting interface."""
        # First render the underlying game
        super().on_render(console)
        
        if not self.available_spells:
            # Fade the entire background
            super().render_faded(console)
            # Show "no spells known" message
            window_width = 40
            window_height = 8
            x = (console.width - window_width) // 2
            y = (console.height - window_height) // 2
            
            MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
            MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "Spellcasting")
            
            console.print(x + 2, y + 3, "You know no spells.", fg=color.impossible)
            console.print(x + 2, y + 6, "[Esc] Cancel", fg=color.grey)
            return
        
        # Calculate window dimensions
        window_width = 70  # Wider for quick cast display
        spell_list_height = len(self.available_spells)
        window_height = min(40, max(20, spell_list_height + 15))  # Taller menu
        
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2
        
        # Fade the background except for the spell menu
        super().render_faded(console, x, y, window_width, window_height)
        
        # Draw main window
        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "Spellcasting")
        
        # Show player's current mana
        mana_text = f"Mana: {self.engine.player.mana}/{self.engine.player.mana_max}"
        console.print(x + 2, y + 1, mana_text, fg=(100, 149, 237))  # Cornflower blue

        
        # Calculate visible spell range for scrolling
        visible_height = window_height - 12  # More space for headers and footers
        start_index = self.scroll_offset
        end_index = min(len(self.available_spells), start_index + visible_height)
        
        # Clamp selected index to valid range
        self.selected_index = max(0, min(self.selected_index, len(self.available_spells) - 1))
        
        # Update scroll offset to keep selected spell visible
        if self.selected_index < start_index:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= end_index:
            self.scroll_offset = self.selected_index - visible_height + 1
            self.scroll_offset = max(0, self.scroll_offset)
        
        # Recalculate visible range after scroll adjustment
        start_index = self.scroll_offset
        end_index = min(len(self.available_spells), start_index + visible_height)
        
        # Render spell list
        list_start_y = y + 2  # Start lower due to quick cast display
        for i, spell_index in enumerate(range(start_index, end_index)):
            spell = self.available_spells[spell_index]
            render_y = list_start_y + i
            
            # Determine colors and selection
            is_selected = (spell_index == self.selected_index)
            can_cast = self._can_cast_spell(spell)
            
            if is_selected:
                # Highlight selected spell
                for highlight_x in range(x + 1, x + window_width - 1):
                    console.print(highlight_x, render_y, " ", bg=(80, 60, 40))
            
            # Spell number and quick cast indicator
            number_text = f"{spell_index + 1}. "
            
            # Check if this spell is in any quick cast slot
            quickcast_indicator = ""
            for slot_idx, slot_spell in enumerate(self.engine.player.quickcast_slots):
                if slot_spell == spell.name:
                    quickcast_indicator = f" [QC{slot_idx+1}]"
                    break
            if spell.arcana_level > self.engine.player.level.traits['arcana']['level']:
                spell_name = '???'
            else:
                spell_name = spell.name
            # Spell name with different colors based on castability
            spell_color = self._get_spell_school_color(spell.school) if can_cast else (90, 90, 90)  # Dark gray
            name_text = f"{number_text}{spell_name}{quickcast_indicator}"
            
            console.print(x + 2, render_y, name_text, fg=spell_color, bg=(80, 60, 40) if is_selected else None)
            
            # Mana cost
            mana_text = f"({spell.mana_cost} mana)"
            mana_x = x + window_width - len(mana_text) - 2
            console.print(mana_x, render_y, mana_text, fg=(100, 149, 237) if can_cast else (128, 128, 128), 
                         bg=(80, 60, 40) if is_selected else None)
            

        
        # Show selected spell description if available
        if self.available_spells:
            selected_spell = self.available_spells[self.selected_index]
            desc_start_y = y + window_height - 4
            
            if selected_spell.arcana_level > self.engine.player.level.traits['arcana']['level']:
                description = "???"
            else:
            
                description = selected_spell.get_description(self.engine.player)
            # Word wrap the description
            
            desc_width = window_width - 4
            words = description.split()
            lines = []
            current_line = []
            current_length = 0
            
            for word in words:
                word_length = len(word)
                if current_length + len(current_line) + word_length <= desc_width:
                    current_line.append(word)
                    current_length += word_length
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
                    current_length = word_length
            
            if current_line:
                lines.append(' '.join(current_line))
            
            # Render description lines (limit to available space)
            max_desc_lines = 2
            for i, line in enumerate(lines[:max_desc_lines]):
                console.print(x + 2, desc_start_y + i, line, fg=color.white)
        
        # Show scroll indicators
        if start_index > 0:
            console.print(x + window_width - 2, list_start_y, "↑", fg=color.yellow)
        if end_index < len(self.available_spells):
            console.print(x + window_width - 2, y + window_height - 5, "↓", fg=color.yellow)
        
        # Instructions
        instructions = [
            "[↑↓] Navigate  [1-9] Assign/Unbind  [Enter] Cast  [Esc] Exit"
        ]
        
        # Cache render coords for mouse interaction
        self._spell_render_x = x
        self._spell_render_y = y
        self._spell_window_width = window_width
        self._spell_list_start_y = list_start_y
        self._spell_scroll_offset = self.scroll_offset
        self._spell_visible_height = visible_height

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> None:
        AskUserEventHandler.ev_mousemotion(self, event)
        if not hasattr(self, '_spell_list_start_y') or not self.available_spells:
            return
        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        x = self._spell_render_x
        w = self._spell_window_width
        list_y = self._spell_list_start_y
        visible = self._spell_visible_height
        if x + 1 <= mouse_x < x + w - 1 and list_y <= mouse_y < list_y + visible:
            spell_index = (mouse_y - list_y) + self._spell_scroll_offset
            if 0 <= spell_index < len(self.available_spells):
                if spell_index != self.selected_index:
                    sounds.play_ui_move_sound()
                self.selected_index = spell_index

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[ActionOrHandler]:
        self.engine.mouse_held = True
        if event.button != tcod.event.BUTTON_LEFT:
            return None
        if not hasattr(self, '_spell_list_start_y') or not self.available_spells:
            return None
        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        x = self._spell_render_x
        w = self._spell_window_width
        list_y = self._spell_list_start_y
        visible = self._spell_visible_height
        if x + 1 <= mouse_x < x + w - 1 and list_y <= mouse_y < list_y + visible:
            spell_index = (mouse_y - list_y) + self._spell_scroll_offset
            if 0 <= spell_index < len(self.available_spells):
                self.selected_index = spell_index
                return self._cast_spell(self.available_spells[spell_index])
        return None

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        """Handle keyboard input for spell casting."""
        if not self.available_spells:
            # No spells known - only allow escape
            if event.sym == tcod.event.KeySym.ESCAPE:
                return MainGameEventHandler(self.engine)
            return None
        
        key = event.sym
        
        # Navigation
        if key == tcod.event.KeySym.UP:
            if self.selected_index > 0:
                self.selected_index -= 1
                sounds.play_ui_move_sound()
            return None
        elif key == tcod.event.KeySym.DOWN:
            if self.selected_index < len(self.available_spells) - 1:
                self.selected_index += 1
                sounds.play_ui_move_sound()
            return None
        
        # Assign/unbind spell to quick cast slot with number keys
        elif key in self.assignment_keys:
            slot_index = self.assignment_keys[key]
            if self.available_spells:
                selected_spell = self.available_spells[self.selected_index]
                current_slot_spell = self.engine.player.quickcast_slots[slot_index]
                
                # If same spell is already in this slot, unbind it
                if current_slot_spell == selected_spell.name:
                    self.engine.player.quickcast_slots[slot_index] = None
                    self.engine.message_log.add_message(
                        f"Unbound {selected_spell.name} from quick cast slot {slot_index + 1}", 
                        (255, 165, 0)  # Orange
                    )
                else:
                    # Assign spell to slot
                    self.engine.player.quickcast_slots[slot_index] = selected_spell.name
                    self.engine.message_log.add_message(
                        f"Assigned {selected_spell.name} to quick cast slot {slot_index + 1}", 
                        (255, 215, 0)  # Gold
                    )
                sounds.play_ui_move_sound()
            return None
        
        # Clear selected slot with Delete key
        elif key == tcod.event.KeySym.DELETE:
            # Clear the slot that matches the currently selected spell
            if self.available_spells:
                selected_spell = self.available_spells[self.selected_index]
                for slot_idx, slot_spell in enumerate(self.engine.player.quickcast_slots):
                    if slot_spell == selected_spell.name:
                        self.engine.player.quickcast_slots[slot_idx] = None
                        self.engine.message_log.add_message(
                            f"Cleared {selected_spell.name} from quick cast slot {slot_idx + 1}", 
                            (255, 165, 0)  # Orange
                        )
                        sounds.play_ui_move_sound()
                        break
                else:
                    self.engine.message_log.add_message(
                        f"{selected_spell.name} is not assigned to any quick cast slot", 
                        (128, 128, 128)  # Gray
                    )
            return None
        
        # Cast from quick cast slot with Shift+number keys
        elif (key in self.assignment_keys and 
              event.mod & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT)):
            slot_index = self.assignment_keys[key]
            spell_name = self.engine.player.quickcast_slots[slot_index]
            if spell_name:
                # Find the spell object by name
                spell_obj = None
                for spell in self.available_spells:
                    if spell.name == spell_name:
                        spell_obj = spell
                        break
                if spell_obj:
                    return self._cast_spell(spell_obj)
                else:
                    self.engine.message_log.add_message(
                        f"Spell {spell_name} no longer available", 
                        color.impossible
                    )
            else:
                self.engine.message_log.add_message(
                    f"Quick cast slot {slot_index + 1} is empty", 
                    color.impossible
                )
            return None
        
        # Cast selected spell
        elif key in CONFIRM_KEYS:
            if self.available_spells:
                selected_spell = self.available_spells[self.selected_index]
                return self._cast_spell(selected_spell)
            return None
        
        # Cancel
        elif key == tcod.event.KeySym.ESCAPE:
            return MainGameEventHandler(self.engine)
        
        return super().ev_keydown(event)
    
    def _cast_spell(self, spell) -> Optional[ActionOrHandler]:
        """Attempt to cast the selected spell."""
        player = self.engine.player
        
        # Check mana cost
        if not self._can_cast_spell(spell):
            self.engine.message_log.add_message(
                f"Not enough mana {spell.mana_cost} required.", 
                color.impossible
            )
            return None
        
        # Check if spell requires targeting
        if hasattr(spell, 'get_targeting_handler') and callable(spell.get_targeting_handler):
            targeting_handler = spell.get_targeting_handler(self.engine, player)
            if targeting_handler is not None:
                # Pre-seed cursor to current physical mouse position
                self.engine.mouse_location = self.engine.mouse_x, self.engine.mouse_y
                return targeting_handler
        
        # Cast spells that don't require targeting directly on the player
        try:
            from actions import SpellAction
            spell_action = SpellAction(player, spell, (player.x, player.y))
            spell_action.perform()
            
            self.engine.message_log.add_message(
                f"You cast {spell.name}!", 
                self._get_spell_school_color(spell)
            )
            
            # Play spell sound if available
            if hasattr(spell, 'cast_sound') and spell.cast_sound:
                spell.cast_sound()
            
        except Exception as e:
            # Don't restore mana since it wasn't consumed yet
            self.engine.message_log.add_message(
                f"Failed to cast {spell.name}: {str(e)}", 
                color.impossible
            )
            return None
        
        # Return to main game after successful cast
        return MainGameEventHandler(self.engine)
    
    @classmethod
    def _create_spell_by_name_static(cls, spell_name):
        """Create a spell object by its name (static version for use by other handlers)."""
        # Ensure registry is initialized
        cls._initialize_spell_registry()
        
        if spell_name in cls.SPELL_REGISTRY:
            spell_class = cls.SPELL_REGISTRY[spell_name]
            return spell_class()
        
        return None


class LookHandler(SelectIndexHandler):
    """Enhanced look handler with detailed inspection sidebar and tabbed interface."""
    
    # Class variable to remember last selected tab across instances
    last_selected_tab = 0

    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.alt_held = False
        self.detail_index = 0  # Index for cycling through items at location
        self.scroll_offset = 0  # For scrolling through text
        self.current_tab = LookHandler.last_selected_tab  # Start with remembered tab
        self.tab_names = ["Glance", "Damages", "Coatings","Inspect"]

    def on_index_selected(self, x: int, y: int) -> Optional[ActionOrHandler]:
        """Return to main handler when location is selected."""
        return MainGameEventHandler(self.engine)

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> Optional[ActionOrHandler]:
        """Sync mouse_location with physical mouse so the cursor follows both mouse and keyboard."""
        result = super().ev_mousemotion(event)
        self.engine.mouse_location = self.engine.mouse_x, self.engine.mouse_y
        return result

    def on_render(self, console: tcod.Console) -> None:
        # Highlight tile underneath cursor
        super(SelectIndexHandler, self).on_render(console)
        
        # Fade the entire background for the look interface
        super().render_faded(console)

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
        text_area_width = sidebar_width - 2  # Use full width minus margins
        
        # Reserve space for compact controls (only 2 lines needed now)
        controls_height = 2
        text_area_height = sidebar_height - (text_details_y - sidebar_y) - controls_height - 1  # Leave space for instructions + margin
        
        # Build complete text content based on current tab
        full_text = self.build_tabbed_content(current_item, text_area_width, x, y)
        
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

    def build_tabbed_content(self, current_item: dict, max_width: int, tile_x: int = 0, tile_y: int = 0) -> list:
        """Build content for the current tab."""
        if self.current_tab == 0:  # Overview
            return self.build_overview_content(current_item, max_width)
        elif self.current_tab == 1:  # Damage
            return self.build_damage_content(current_item, max_width)
        elif self.current_tab == 2:  # Coatings
            return self.build_coatings_content(current_item, max_width, tile_x, tile_y)
        elif self.current_tab == 3:  # Inspect
            return self.build_inspect_content(current_item, max_width)
        return []

    def build_inspect_content(self, current_item: dict, max_width: int) -> list:
        lines = []

        if current_item['type'] == 'entity':
            entity = current_item['object']
        else:
            return
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
        return lines

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

            entity_name_color = color.light_blue
            if hasattr(entity, 'effects'):
                if any(isinstance(e, BurningEffect) for e in entity.effects):
                    entity_name_color = random.choice([color.orange, color.red, color.yellow])
                    

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
                        lines.append([(entity.name, entity_name_color)])
            else:
                if hasattr(entity, 'name'):
                    lines.append([(entity.name, entity_name_color)])

                    
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

            if hasattr(entity, 'tradable') and entity.tradable:
                lines.append([(f"{(entity.knowledge['pronouns']['subject']).capitalize()} seems willing to trade.", color.light_green)])

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
            
            # Word-wrap tile name so long names produce multiple logical lines, enabling scroll
            name_text = f"This is a {tile_info['name']}."
            lines.extend(wrap_colored_text(name_text, max_width))
            
            walkable_text = "You can walk here." if tile_info['walkable'] else "You cannot walk here."
            lines.append([(walkable_text, color.white)])
            
            transparent_text = "You can see through this." if tile_info['transparent'] else "You cannot see through this."
            lines.append([(transparent_text, color.white)])
            
            if tile_info.get('interactable', False):
                interact_text = f"You can interact with this {tile_info['name'].lower()}."
                lines.extend(wrap_colored_text(interact_text, max_width, default_color=color.cyan))
        
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
                    message = "Healthy."
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
                    pass
                    
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
                message = "Undamaged."
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
            message = "Undamaged."
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
    
    def build_coatings_content(self, current_item: dict, max_width: int, tile_x: int = 0, tile_y: int = 0) -> list:
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
                    message = "Clean."
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
                    pass
                    
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
                message = "Clean."
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
                coating = self.engine.game_map.liquid_system.get_coating(tile_x, tile_y)
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
                    message = "Clean."
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
    
    def ev_mousewheel(self, event: tcod.event.MouseWheel) -> Optional[ActionOrHandler]:
        if event.y > 0:
            print("scroll up")
            # Scroll text up
            self.scroll_offset = max(0, self.scroll_offset - 1)
            return None
        elif event.y < 0:
            # Scroll text down (limit will be handled in render)
            self.scroll_offset += 1
            return None

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        """Handle keyboard input for inspection interface."""
        key = event.sym
        modifier = event.mod
        print(modifier)
        if key == tcod.event.KeySym.TAB and modifier & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT):
            print("T")
            self.current_tab = (self.current_tab - 1) % len(self.tab_names)
            LookHandler.last_selected_tab = self.current_tab
            self.scroll_offset = 0
            sounds.play_ui_move_sound()
            return None

        # Handle tab switching
        elif key == tcod.event.KeySym.TAB:
            # Switch to previous tab and reset scroll
            self.current_tab = (self.current_tab + 1) % len(self.tab_names)
            LookHandler.last_selected_tab = self.current_tab  # Remember for next time
            self.scroll_offset = 0
            sounds.play_ui_move_sound()  # Play menu navigation sound
            return None
        elif key == tcod.event.KeySym.ESCAPE:
            # Exit inspection mode
            return MainGameEventHandler(self.engine)

            

        
        # Use parent handler for normal movement (arrow keys without modifiers)
        return super().ev_keydown(event)




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


    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[ActionOrHandler]:
        if event.button == tcod.event.MouseButton.LEFT:

            preferred_target = getattr(self.engine.player, 'current_attack_type', None)
            dx = max(-1, min(1, self.engine.mouse_x - self.engine.player.x))
            dy = max(-1, min(1, self.engine.mouse_y - self.engine.player.y))
            # Get the target actor at the attack location
            target_x = self.engine.player.x + dx
            target_y = self.engine.player.y + dy

            target_actor = self.engine.game_map.get_actor_at_location(target_x, target_y)
            # Convert preferred target tag to specific body part for ranged attacks
            if preferred_target and target_actor:
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
                    target_part = None
            elif target_actor:
                if hasattr(target_actor, 'body_parts') and target_actor.body_parts:
                    # Target random part
                    target_part = random.choice(list(target_actor.body_parts.body_parts.keys()))
                else:
                    target_part = None
            else:
                target_part = None

            equipment = getattr(self.engine.player, 'equipment', None)
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
                return actions.RangedAction(self.engine.player, dx, dy, target_part)
            elif has_melee_weapon:
                return actions.MeleeAction(self.engine.player, dx, dy, target_part)
            else:
                self.engine.message_log.add_message(
                    "No suitable weapon readied for directional attack.", color.impossible
                    )
                return None
        if event.button == tcod.event.MouseButton.RIGHT:
            # Check if within reach of player
            mouse_x, mouse_y = self.engine.mouse_x, self.engine.mouse_y
            reach = max(abs(mouse_x - self.engine.player.x), abs(mouse_y - self.engine.player.y))
            # Get direction in tiles from player pos for X
            dx = mouse_x - self.engine.player.x
            dy = mouse_y - self.engine.player.y
            if reach <= 1:
                return actions.InteractAction(self.engine.player, dx, dy)
            else:
                self.engine.message_log.add_message("That is out of reach.", color.impossible)
    
    def ev_keyup(self, event: tcod.event.KeyUp) -> Optional[ActionOrHandler]:
        if event.sym in (tcod.event.KeySym.LALT, tcod.event.KeySym.RALT):
            self.alt_held = False
            print(self.alt_held)

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
            return HelpMenuHandler()
        # F2 toggles debug mode
        elif key == tcod.event.K_F2:
            self.engine.debug = not self.engine.debug
            self.engine.message_log.add_message("Debug mode toggled.", color.green)
        elif key == tcod.event.K_F11:
            from __main__ import toggle_fullscreen, _game_context
            toggle_fullscreen(context=_game_context)

        # F3 shows limb stats debug
        elif key == tcod.event.K_F3:
            return EntityDebugHandler(self.engine)


        # Dodge change direction (Ctrl + arrow key direction OR numpad direction)
        elif key == tcod.event.KeySym.A and modifier & (tcod.event.KMOD_LCTRL | tcod.event.KMOD_RCTRL):
            player.preferred_dodge_direction = ("west")
        elif key == tcod.event.KeySym.D and modifier & (tcod.event.KMOD_LCTRL | tcod.event.KMOD_RCTRL):
            player.preferred_dodge_direction = ("east")
        elif key == tcod.event.KeySym.W and modifier & (tcod.event.KMOD_LCTRL | tcod.event.KMOD_RCTRL):
            player.preferred_dodge_direction = ("north")
        elif key == tcod.event.KeySym.S and modifier & (tcod.event.KMOD_LCTRL | tcod.event.KMOD_RCTRL):
            player.preferred_dodge_direction = ("south")
        elif key == tcod.event.KeySym.LALT or key == tcod.event.KeySym.RALT:
            self.alt_held = True
            return LookHandler(self.engine)
            print(self.alt_held)
        
        # Interact action (Right click) checks if within reach of player
        #elif self.engine.mouse_held and self.engine.mouse_location:
        #    print("Mouse held at:", self.engine.mouse_location)

            
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


        ## KEY INPUTS
        elif key in WAIT_KEYS:
            action = WaitAction(player)
        elif key ==tcod.event.K_ESCAPE:
            self.engine.debug_log("Opening pause menu.", handler=type(self).__name__, event="input")
            return PauseHandler(self.engine)
        elif key == tcod.event.KeySym.V:
            return HistoryViewer(self.engine)
        elif key == tcod.event.KeySym.G:
            action = PickupAction(player)
        elif key == tcod.event.KeySym.R:
            return ScrollActivateHandler(self.engine)
        elif key == tcod.event.KeySym.TAB:
            return InventoryActivateHandler(self.engine)
        # Throw Handler
        elif key == tcod.event.KeySym.T:
            return ThrowSelectionHandler(self.engine)
        elif key == tcod.event.KeySym.F1:
            return CheatMaxLevel(self.engine)
        elif key == tcod.event.KeySym.E:
            # Visual equipment interface
            from equipment_ui import EquipmentUI
            return EquipmentUI(self.engine)
        # elif key == tcod.event.KeySym.U:
        #     return InventoryEquipHandler(self.engine)
        elif key == tcod.event.KeySym.Q:
            return QuaffActivateHandler(self.engine)
        elif key == tcod.event.KeySym.Z:
            return InventoryDropHandler(self.engine)
        elif key == tcod.event.KeySym.F:
            from character_sheet_ui import CharacterScreen
            return CharacterScreen(self.engine)
        # t key for targeting mode
        elif key == tcod.event.KeySym.A:
            return AttackModeHandler(self.engine)
        elif key == tcod.event.KeySym.S:
            return LookHandler(self.engine)
        elif key == tcod.event.KeySym.C:
            return SpellCastingHandler(self.engine)

        # Quick cast from slots (Shift+1-9)
        elif (key in [tcod.event.KeySym.N1, tcod.event.KeySym.N2, tcod.event.KeySym.N3, 
                      tcod.event.KeySym.N4, tcod.event.KeySym.N5, tcod.event.KeySym.N6,
                      tcod.event.KeySym.N7, tcod.event.KeySym.N8, tcod.event.KeySym.N9] and
              modifier & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT)):
            
            # Initialize quickcast slots if not present
            if not hasattr(player, 'quickcast_slots'):
                player.quickcast_slots = [None] * 9
            
            # Map key to slot index
            key_to_slot = {
                tcod.event.KeySym.N1: 0, tcod.event.KeySym.N2: 1, tcod.event.KeySym.N3: 2,
                tcod.event.KeySym.N4: 3, tcod.event.KeySym.N5: 4, tcod.event.KeySym.N6: 5,
                tcod.event.KeySym.N7: 6, tcod.event.KeySym.N8: 7, tcod.event.KeySym.N9: 8,
            }
            
            slot_index = key_to_slot[key]
            spell_name = player.quickcast_slots[slot_index]
            
            if spell_name:
                # Find spell object by name in known_spells
                spell_obj = None
                if hasattr(player, 'known_spells'):
                    for spell in player.known_spells:
                        if spell.name == spell_name:
                            spell_obj = spell
                            break
                
                if spell_obj:
                    # Check if spell requires targeting
                    if (hasattr(spell_obj, 'get_targeting_handler') and 
                        callable(spell_obj.get_targeting_handler)):
                        targeting_handler = spell_obj.get_targeting_handler(self.engine, player)
                        if targeting_handler is not None:
                            # Check mana before entering targeting mode
                            if player.mana >= spell_obj.mana_cost:
                                return targeting_handler
                            else:
                                self.engine.message_log.add_message(
                                    f"Not enough mana. (requires {spell_obj.mana_cost})",
                                    color.impossible
                                )
                                return None
                    
                    # Check mana and cast instant spells
                    if player.mana >= spell_obj.mana_cost:
                        try:
                            from actions import SpellAction
                            spell_action = SpellAction(player, spell_obj, (player.x, player.y))
                            spell_action.perform()
                            
                            self.engine.message_log.add_message(
                                f"Quick cast: {spell_obj.name}!", 
                                (138, 43, 226)  # Purple
                            )
                            
                            # This counts as an action
                            return WaitAction(player)
                        except Exception as e:
                            # Don't restore mana since spell handles consumption
                            self.engine.message_log.add_message(
                                f"Failed to cast {spell_name}: {str(e)}", 
                                color.impossible
                            )
                    else:
                        self.engine.message_log.add_message(
                            f"Not enough mana for {spell_name} (requires {spell_obj.mana_cost})", 
                            color.impossible
                        )
                else:
                    self.engine.message_log.add_message(
                        f"You don't know the spell: {spell_name}", 
                        color.impossible
                    )
            else:
                self.engine.message_log.add_message(
                    f"Quick cast slot {slot_index + 1} is empty", 
                    color.impossible
                )
            
            return None
        
        # No valid key was pressed
        self.engine.debug_log(f"Unbound key pressed: {key} (modifiers: {modifier})", handler=type(self).__name__, event="input")
        return action
    


    def ev_mousewheel(self, event: tcod.event.MouseWheel) -> Optional[ActionOrHandler]:
        """Handle mouse wheel during main game - just print for now."""
        if event.y > 0:
            print("Mouse wheel scrolled up")
            self.engine.message_log.add_message("Mouse wheel up", (150, 150, 255))
        elif event.y < 0:
            print("Mouse wheel scrolled down") 
            self.engine.message_log.add_message("Mouse wheel down", (255, 150, 150))
        return None
    
class TextInputHandler(BaseEventHandler):
    """Handler for text input with typing support."""
    
    def __init__(self, engine: Engine = None, title: str = "Enter Text", prompt: str = "", max_length: int = 50, callback=None, parent_handler=None):
        # Initialize base handler
        super().__init__()
        self.engine = engine
        self.title = title
        self.prompt = prompt
        self.max_length = max_length
        self.text = ""
        self.cursor_pos = 0
        self.callback = callback
        self.parent_handler = parent_handler
    def _insert_char(self, char: str) -> None:
        """Insert a character at the cursor position."""
        if len(self.text) < self.max_length and char:
            self.text = self.text[:self.cursor_pos] + char + self.text[self.cursor_pos:]
            self.cursor_pos += 1
            
    def _delete_char(self, forward: bool = False) -> None:
        """Delete a character (backspace or delete)."""
        if forward and self.cursor_pos < len(self.text):
            # Delete character at cursor
            self.text = self.text[:self.cursor_pos] + self.text[self.cursor_pos + 1:]
        elif not forward and self.cursor_pos > 0:
            # Backspace - delete character before cursor
            self.text = self.text[:self.cursor_pos - 1] + self.text[self.cursor_pos:]
            self.cursor_pos -= 1
            
    def _move_cursor(self, direction: str) -> None:
        """Move cursor in specified direction."""
        if direction == "left":
            self.cursor_pos = max(0, self.cursor_pos - 1)
        elif direction == "right":
            self.cursor_pos = min(len(self.text), self.cursor_pos + 1)
        elif direction == "home":
            self.cursor_pos = 0
        elif direction == "end":
            self.cursor_pos = len(self.text)
            
    def _key_to_char(self, event: tcod.event.KeyDown) -> str:
        """Convert a key event to a character."""
        key = event.sym
        shift_pressed = event.mod & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT)
        
        # Letters (a-z)
        if tcod.event.KeySym.A <= key <= tcod.event.KeySym.Z:
            char = chr(ord('a') + (key - tcod.event.KeySym.A))
            return char.upper() if shift_pressed else char
        
        # Numbers (0-9) 
        elif tcod.event.KeySym.N0 <= key <= tcod.event.KeySym.N9:
            if shift_pressed:
                shift_symbols = ")!@#$%^&*("
                return shift_symbols[key - tcod.event.KeySym.N0]
            else:
                return str(key - tcod.event.KeySym.N0)
        
        # Common keys
        key_map = {
            tcod.event.KeySym.SPACE: " ",
            tcod.event.KeySym.MINUS: "_" if shift_pressed else "-",
            tcod.event.KeySym.EQUALS: "+" if shift_pressed else "=",
            tcod.event.KeySym.PERIOD: ">" if shift_pressed else ".",
            tcod.event.KeySym.COMMA: "<" if shift_pressed else ",",
        }
        
        return key_map.get(key, "")
        
    def render_faded(self, console: tcod.Console, menu_x: int = None, menu_y: int = None, menu_width: int = None, menu_height: int = None) -> None:
        # Fades the current console to create a dimmed background effect for menus
        # Excludes the menu area from fading if menu bounds are provided
        fade_alpha = 0.4  # Fade strength (0.0 = no fade, 1.0 = completely faded)
        fade_color = (20, 20, 30)  # Dark blue-gray tint
        
        for x in range(console.width):
            for y in range(console.height):
                # Skip fading pixels that are within the menu bounds
                if (menu_x is not None and menu_y is not None and 
                    menu_width is not None and menu_height is not None):
                    if (menu_x <= x < menu_x + menu_width and 
                        menu_y <= y < menu_y + menu_height):
                        continue
                
                existing_color = console.bg[x, y]
                # Safe color blending using floating point math
                blended_color = (
                    int(existing_color[0] * (1 - fade_alpha) + fade_color[0] * fade_alpha),
                    int(existing_color[1] * (1 - fade_alpha) + fade_color[1] * fade_alpha),
                    int(existing_color[2] * (1 - fade_alpha) + fade_color[2] * fade_alpha),
                )
                console.bg[x, y] = blended_color
        
    def on_exit(self) -> Optional[ActionOrHandler]:
        """Handle exiting the text input - return to main game if we have engine."""
        if self.engine is not None:
            return MainGameEventHandler(self.engine)
        return None
        
    def on_render(self, console: tcod.Console) -> None:
        # Render background appropriately based on context
        if self.engine is not None:
            # In-game: render the game world
            self.engine.render(console)
        elif self.parent_handler is not None:
            # Setup screen: let parent render its background first
            self.parent_handler.on_render(console)
        # If neither engine nor parent, keep existing console content (overlay mode)
        
        # Calculate window dimensions
        window_width = max(40, len(self.prompt) + 10, self.max_length + 10)
        window_height = 8
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2
        
        # Fade the background except for the input window
        self.render_faded(console, x, y, window_width, window_height)
        
        # Draw input window
        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, self.title)
        
        # Draw prompt if provided
        if self.prompt:
            console.print(x + 2, y + 2, self.prompt, fg=(200, 180, 140))
        
        # Draw input field
        input_y = y + 4 if self.prompt else y + 3
        
        # Input field background
        field_width = window_width - 4
        for i in range(field_width):
            console.print(x + 2 + i, input_y, " ", bg=(60, 40, 25))
        
        # Draw input text
        display_text = self.text[:field_width - 2]  # Leave room for cursor
        console.print(x + 3, input_y, display_text, fg=(255, 255, 255), bg=(60, 40, 25))
        
        # Draw cursor (blinking effect)
        import time
        if int(time.time() * 2) % 2:  # Simple blinking
            cursor_x = x + 3 + min(len(display_text), self.cursor_pos)
            if cursor_x < x + 2 + field_width - 1:  # Make sure cursor is visible
                console.print(cursor_x, input_y, "|", fg=(255, 215, 0), bg=(60, 40, 25))
        
        # Instructions
        instructions_y = y + window_height - 2
        console.print(x + 1, instructions_y, "[Enter] Confirm  [Esc] Cancel", fg=(180, 140, 100))
        
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        key = event.sym
        
        # Handle escape - cancel input
        if key == tcod.event.KeySym.ESCAPE:
            return self._handle_cancel()
            
        # Handle enter - submit text
        elif key == tcod.event.KeySym.RETURN or key == tcod.event.KeySym.KP_ENTER:
            return self._handle_submit()
            
        # Handle deletion
        elif key == tcod.event.KeySym.BACKSPACE:
            self._delete_char(forward=False)
        elif key == tcod.event.KeySym.DELETE:
            self._delete_char(forward=True)
            
        # Handle cursor movement
        elif key == tcod.event.KeySym.LEFT:
            self._move_cursor("left")
        elif key == tcod.event.KeySym.RIGHT:
            self._move_cursor("right")
        elif key == tcod.event.KeySym.HOME:
            self._move_cursor("home")
        elif key == tcod.event.KeySym.END:
            self._move_cursor("end")
            
        # Handle character input
        else:
            char = self._key_to_char(event)
            if char:
                self._insert_char(char)
            # Fallback for unicode input
            elif hasattr(event, 'unicode') and event.unicode and event.unicode.isprintable():
                self._insert_char(event.unicode)
                
        return None
        
    def _handle_cancel(self) -> Optional[ActionOrHandler]:
        """Handle cancellation (ESC key)."""
        if self.engine is not None:
            return MainGameEventHandler(self.engine)
        elif self.parent_handler is not None:
            if self.callback:
                result = self.callback(None)
                return result if result is not None else self.parent_handler
            return self.parent_handler
        else:
            return self.callback(None) if self.callback else None
            
    def _handle_submit(self) -> Optional[ActionOrHandler]:
        """Handle text submission (Enter key)."""
        if self.callback:
            result = self.callback(self.text)
            if result is not None:
                return result
        
        # Fallback returns
        if self.engine is not None:
            return MainGameEventHandler(self.engine)
        return None

    def ev_textinput(self, event: tcod.event.TextInput) -> Optional[ActionOrHandler]:
        """Handle text input events for typing."""
        self._insert_char(event.text)
        return None




class GameOverEventHandler(EventHandler):

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)
        window_width = 30
        window_height = 6
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2
        
        # Fade the entire screen except for the game over message area
        super().render_faded(console, x, y, window_width, window_height)
        
        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "Death")
        
        console.print(x + 2, y + 2, "Your adventure ends here.", fg=(color.red))
        console.print(x + 2, y + 3, "You fade into obscurity...", fg=(color.light_gray))

    def on_quit(self) -> None:
        """Handle exiting out of a finished game."""
        import setup_game  # Local import to avoid circular dependency
        savegame_path = setup_game.get_save_path("savegame.sav")
        if os.path.exists(savegame_path):
            os.remove(savegame_path)  # Deletes the active save file.
        sounds.stop_all_music()
        sounds.stop_all_sounds()
        sounds.start_menu_ambience()
        sounds.start_menu_music()
        
        # Import MainMenu here to avoid circular imports
        from setup_game import MainMenu
        return MainMenu()

    def ev_quit(self, event: tcod.event.Quit) -> None:
        return self.on_quit()

    def ev_keydown(self, event: tcod.event.KeyDown) -> None:
        if event.sym == tcod.event.K_ESCAPE:
            return self.on_quit()
    
CURSOR_Y_KEYS = {
    tcod.event.KeySym.UP: -1,
    tcod.event.KeySym.DOWN: 1,
    tcod.event.KeySym.PAGEUP: -10,
    tcod.event.KeySym.PAGEDOWN: 10,
}





class PauseHandler(AskUserEventHandler):


    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.categories = ["Resume Game", "Save and Exit", "Exit without Saving", "Settings"]
        self.selected_option = 0
        self.scroll_offset = 0
        self.max_visible_lines = 10  # Max lines to show in options list before scrolling
        self.selected_option = 0  # Default to first option

    """Open pause menu, settings, save and exit, etc"""
    def on_render(self, console):
        self.engine.render(console)  # Draw the main state as the background.
        window_width = 34
        window_height = 11
        x = (console.width - window_width) // 2
        y = (console.height - window_height -4) // 2
        
        # Fade the entire screen except for the menu area
        self.render_faded(console, x, y, window_width, window_height)
        
        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "Game Paused")

        self.render_options(console, x-2, y-2)

        # Cache coords: options are at x+2, y+2 + i*2
        self._opt_x = x + 2
        self._opt_y = y + 2
        self._opt_count = len(self.categories)
    
    def handle_save_with_name(self, save_name: str):
        """Handle saving the game with a custom name."""
        import setup_game  # Local import to avoid circular dependency
        if save_name.strip():  # Only save if name is not empty
            save_path = setup_game.get_save_path(f"{save_name.strip()}.sav")
            self.engine.save_as(save_path)
        else:
            # Use default name if no name provided
            save_path = setup_game.get_save_path("savegame.sav")
            self.engine.save_as(save_path)
        
        # Stop game audio and start menu audio
        sounds.stop_all_sounds()
        sounds.start_menu_ambience()
        sounds.start_menu_music()
        
        # Return to main menu after saving
        from setup_game import MainMenu
        return MainMenu()
    
    def process_response(self, response: str):
        if response == "Resume Game":
            return MainGameEventHandler(self.engine)
        elif response == "Save and Exit":
            return TextInputHandler(self.engine, prompt="Enter save name:", callback=self.handle_save_with_name)
        elif response == "Exit without Saving":
            # Stop game audio and start menu audio
            sounds.stop_all_sounds()
            sounds.start_menu_ambience()
            sounds.start_menu_music()
            
            # Import MainMenu here to avoid circular imports
            from setup_game import MainMenu
            return MainMenu()
        elif response == "Settings":
            return Settings(parent_handler=PauseHandler(self.engine))
        else:
            return MainGameEventHandler(self.engine)

    def ev_keydown(self, event):
        
        if event.sym == tcod.event.KeySym.ESCAPE or event.sym == tcod.event.KeySym.F:
            # Return to main game handler to close character sheet
            from input_handlers import MainGameEventHandler
            return MainGameEventHandler(self.engine)
        elif event.sym == tcod.event.KeySym.UP:
            if event.mod & (tcod.event.Modifier.LSHIFT | tcod.event.Modifier.RSHIFT):
                # Shift+Up: Scroll up
                self.scroll_offset = max(0, self.scroll_offset - 1)
                self._play_ui_sound()
            else:
                # Move to previous category
                self.selected_option = (self.selected_option - 1) % len(self.categories)
                self._play_ui_sound()
        elif event.sym == tcod.event.KeySym.DOWN:
            if event.mod & (tcod.event.Modifier.LSHIFT | tcod.event.Modifier.RSHIFT):
                # Shift+Down: Scroll down
                max_scroll = max(0, self._calculate_total_lines() - self.max_visible_lines)
                self.scroll_offset = min(max_scroll, self.scroll_offset + 1)
                self._play_ui_sound()
            else:
                # Move to next category
                self.selected_option = (self.selected_option + 1) % len(self.categories)
                self._play_ui_sound()
        elif event.sym == tcod.event.KeySym.SPACE:
            self._play_ui_sound()
            self.engine.debug_log(f"Selected option: {self.categories[self.selected_option]}", handler=type(self).__name__, event="input")
            return self.process_response(self.categories[self.selected_option])
        # Always return self to stay in this handler (except for ESC/F above)
        return self

    def _play_ui_sound(self):
        import sounds
        sounds.play_ui_move_sound()

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> None:
        if not hasattr(self, '_opt_x'):
            return
        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        for i in range(self._opt_count):
            row_y = self._opt_y + i * 2
            if mouse_y == row_y and self._opt_x <= mouse_x < self._opt_x + 24:
                if i != self.selected_option:
                    self.selected_option = i
                    self._play_ui_sound()
                return

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[ActionOrHandler]:
        if event.button != tcod.event.BUTTON_LEFT:
            return self
        if not hasattr(self, '_opt_x'):
            return self
        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        for i in range(self._opt_count):
            row_y = self._opt_y + i * 2
            if mouse_y == row_y and self._opt_x <= mouse_x < self._opt_x + 24:
                self.selected_option = i
                self._play_ui_sound()
                return self.process_response(self.categories[i])
        return self

    def render_options(self, console: tcod.Console, x, y):
        for i, option in enumerate(self.categories):
            if i == self.selected_option:
                console.print(x + 4, y + 4 + i * 2, (">" + option), fg=color.yellow)
            else:
                console.print(x + 4, y + 4 + i * 2, (" " +option), fg=color.white)

class HistoryViewer(EventHandler):
    """Print the history on a larger window which can be navigated."""

    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.log_length = len(engine.message_log.messages)
        self.cursor = self.log_length - 1

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)  # Draw the main state as the background.

        log_console = tcod.Console(console.width - 6, console.height - 6)
        
        # Fade the entire background
        super().render_faded(console)
        
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


class HelpMenuHandler(BaseEventHandler):
    TITLE = "Controls"
    
    def __init__(self, parent_handler=None):
        # Load settings from JSON file
        self.parent_handler = parent_handler

    def _handle_back(self) -> Optional[ActionOrHandler]:
        """Handle returning to previous handler (main menu)."""
        if self.parent_handler is not None:
            return self.parent_handler
        else:
            return None  # Fallback - should not happen in practice

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        key = event.sym
        sounds.play_menu_move_sound()
        # Handle escape - go back
        if key == tcod.event.KeySym.ESCAPE:
            return self._handle_back()
    def on_render(self, console: tcod.Console) -> None:
        # If we have a parent handler, let it render the background
        if self.parent_handler is not None and hasattr(self.parent_handler, 'on_render'):
            self.parent_handler.on_render(console)



        text = f"""Movement:
    ↑↓←→: Move Cardinally
    Numpad: Move Ordinally

Inventory:
    E: Equipment Menu
    TAB: Inventory
    Q: Quaff
    R: Read
    D: Drop
    V: Message History

Interact:
    G: Pick up object
    ALT+Direction: Interact
    SHIFT+Direction: Attack
    CTRL+Direction: Dodge direction 

UI:
    ESCAPE: Exit Menu
    TAB: Switch focus

DEBUG:
    F2: Player Debug
    F3: Entity/Tile Debug
        """

        width = len(max(text.splitlines(), key=len)) + 4
        height = len(text.splitlines()) + 4
        x = console.width // 2 - width // 2
        y = console.height // 2 - height // 2
        
        MenuRenderer.draw_parchment_background(console, x, y, width, height)
        MenuRenderer.draw_ornate_border(console, x, y, width, height, self.TITLE)
        

        console.print(
            x=x + 1, y=y + 1, string=text, fg=color.fantasy_text
        )


class CheatMaxLevel(EventHandler):
    """Debug cheat handler - gives one level to all traits"""
    
    def __init__(self, engine: Engine):
        super().__init__(engine)
        self._execute_cheat()
    
    def _execute_cheat(self) -> None:
        """Give XP to level up all traits by one level"""
        player = self.engine.player
        
        # Calculate XP needed to level up each trait
        for trait_name in player.level.traits:
            current_level = player.level.traits[trait_name]['level']
            xp_needed = player.level.xp_to_next(trait_name)
            
            # Give enough XP to level up once
            player.level.add_xp({trait_name: xp_needed})
        
        # Show debug message
        self.engine.message_log.add_message(
            "DEBUG CHEAT: All traits leveled up!", 
            (255, 255, 0)  # Yellow
        )
    
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        """Return to main game on any key"""
        return MainGameEventHandler(self.engine)
    
    def on_render(self, console: tcod.Console) -> None:
        """Render the main game in the background"""
        self.engine.render(console)


class Settings(BaseEventHandler):
    """Settings menu handler - allows adjusting game settings."""
    
    TITLE = "Settings"
    
    def __init__(self, parent_handler=None):
        # Load settings from JSON file
        self.settings_file = "settings.json"
        self.settings_data = self._load_settings()
        
        self.categories = {
            "Controls": {
                "Options": [''],
                "SelectedIndex": 0,
                "json_key": None  # No JSON key since this opens a sub-menu
            },
            "Window:": {
                "Options": ["Windowed", "Fullscreen"],
                "SelectedIndex": 1 if self.settings_data.get("fullscreen", False) else 0,
                "json_key": "fullscreen"
            },
            "Audio:": {
                "Options": ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"],
                "SelectedIndex": self._get_audio_index(),
                "json_key": "audio"
            },
            "Graphics:": {
                "Options": ["High", "Medium", "Low"],
                "SelectedIndex": ["high", "medium", "low"].index(self.settings_data.get("graphics", "high").lower()),
                "json_key": "graphics"
            },
            "Light Flicker:": {
                "Options": ["On", "Off"],
                "SelectedIndex": 0 if self.settings_data.get("light_flicker", True) else 1,
                "json_key": "light_flicker"
            }
        }
        # Convert to list for easier navigation
        self.category_keys = list(self.categories.keys()) + ["Back"]
        self.selected_option = 0
        # Parent handler for returning to main menu when engine doesn't exist
        self.parent_handler = parent_handler

    def on_render(self, console: tcod.Console) -> None:
        # If we have a parent handler, let it render the background
        if self.parent_handler is not None and hasattr(self.parent_handler, 'on_render'):
            self.parent_handler.on_render(console)

        window_width = 42
        window_height = len(self.category_keys) * 2 + 9
        x = (console.width - window_width) // 2
        y = (console.height - window_height-5) // 2
        
        # Don't fade the background for main menu settings
        # self.render_faded(console, x, y, window_width, window_height)
        
        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, self.TITLE)

        for i, category_key in enumerate(self.category_keys):
            is_selected = i == self.selected_option
            
            if category_key == "Back":
                # Special handling for Back option
                if is_selected:
                    console.print(x+1, y + 2 + i * 2, f">{category_key}", fg=color.gold_accent)
                else:
                    console.print(x+1, y + 2 + i * 2, f" {category_key}", fg=color.fantasy_text)
            else:
                # Regular category with current setting
                category_data = self.categories[category_key]
                current_option = category_data["Options"][category_data["SelectedIndex"]]
                
                if is_selected:
                    console.print(x + 1, y + 2 + i * 2, f">{category_key} {current_option}", fg=color.gold_accent)
                else:
                    console.print(x + 1, y + 2 + i * 2, f" {category_key} {current_option}", fg=color.fantasy_text)

        # Cache render coords for mouse interaction
        self._opt_x = x + 1
        self._opt_y = y + 2
        self._opt_count = len(self.category_keys)
    
    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> None:
        if not hasattr(self, '_opt_x'):
            return
        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        for i in range(self._opt_count):
            row_y = self._opt_y + i * 2
            if mouse_y == row_y and self._opt_x <= mouse_x < self._opt_x + 30:
                if i != self.selected_option:
                    self.selected_option = i
                    sounds.play_ui_move_sound()
                return

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[ActionOrHandler]:
        if event.button not in (tcod.event.BUTTON_LEFT, tcod.event.BUTTON_RIGHT):
            return self
        if not hasattr(self, '_opt_x'):
            return self
        mouse_x, mouse_y = int(event.tile.x), int(event.tile.y)
        for i in range(self._opt_count):
            row_y = self._opt_y + i * 2
            if mouse_y == row_y and self._opt_x <= mouse_x < self._opt_x + 30:
                self.selected_option = i
                sounds.play_ui_move_sound()
                selected_key = self.category_keys[i]
                if selected_key == "Back":
                    return self._handle_back()
                elif selected_key == "Controls":
                    return HelpMenuHandler(parent_handler=self)
                elif selected_key in self.categories:
                    category_data = self.categories[selected_key]
                    num_options = len(category_data["Options"])
                    direction = -1 if event.button == tcod.event.BUTTON_RIGHT else 1
                    category_data["SelectedIndex"] = (category_data["SelectedIndex"] + direction) % num_options
                    self._save_settings()
                    if "Window:" in selected_key:
                        from __main__ import toggle_fullscreen, _game_context
                        toggle_fullscreen(context=_game_context)
                    if selected_key == "Audio:":
                        try:
                            from sounds import update_all_loop_volumes_from_settings
                            update_all_loop_volumes_from_settings()
                        except Exception:
                            pass
                return self
        return self

    def render_faded(self, console: tcod.Console, menu_x: int = None, menu_y: int = None, menu_width: int = None, menu_height: int = None) -> None:
        """Fade the console background except for the menu area."""
        fade_alpha = 0.4  # Fade strength (0.0 = no fade, 1.0 = completely faded)
        fade_color = (20, 20, 30)  # Dark blue-gray tint
        
        for x in range(console.width):
            for y in range(console.height):
                # Skip fading pixels that are within the menu bounds
                if (menu_x is not None and menu_y is not None and 
                    menu_width is not None and menu_height is not None):
                    if (menu_x <= x < menu_x + menu_width and 
                        menu_y <= y < menu_y + menu_height):
                        continue
                
                existing_color = console.bg[x, y]
                # Safe color blending using floating point math
                blended_color = (
                    int(existing_color[0] * (1 - fade_alpha) + fade_color[0] * fade_alpha),
                    int(existing_color[1] * (1 - fade_alpha) + fade_color[1] * fade_alpha),
                    int(existing_color[2] * (1 - fade_alpha) + fade_color[2] * fade_alpha),
                )
                console.bg[x, y] = blended_color

    def _load_settings(self) -> dict:
        """Load settings from JSON file."""
        try:
            with open(self.settings_file, 'r') as f:
                content = f.read()
                # Remove JSON comments (lines starting with //)
                lines = [line for line in content.split('\n') if not line.strip().startswith('//')]
                clean_content = '\n'.join(lines)
                return json.loads(clean_content)
        except (FileNotFoundError, json.JSONDecodeError):
            # Return default settings if file doesn't exist or is invalid
            return {"controls": None, "fullscreen": False, "audio": 50, "graphics": "high", "light_flicker": True}
    
    def _get_audio_index(self) -> int:
        """Get the correct index for audio volume setting."""
        audio_value = self.settings_data.get("audio", 50)
        
        # Handle legacy boolean format
        if isinstance(audio_value, bool):
            return 5 if audio_value else 0  # 50% if True, 0% if False
        
        # Handle numeric format (0-100)
        audio_options = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        
        # Find closest matching option
        closest_index = 0
        min_diff = abs(audio_value - audio_options[0])
        
        for i, option_value in enumerate(audio_options):
            diff = abs(audio_value - option_value)
            if diff < min_diff:
                min_diff = diff
                closest_index = i
        
        return closest_index
    
    def _save_settings(self) -> None:
        """Save current settings to JSON file."""
        try:
            # Update settings data based on current UI selections
            for category_key, category_data in self.categories.items():
                if "json_key" in category_data and category_data["json_key"] is not None:
                    json_key = category_data["json_key"]
                    selected_index = category_data["SelectedIndex"]
                    
                    if "Window:" in category_key:  # Handle "Window (restart required)"
                        self.settings_data[json_key] = (selected_index == 1)  # True for Fullscreen
                    elif category_key == "Audio:":
                        audio_options = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
                        self.settings_data[json_key] = audio_options[selected_index]  # 0-100 volume
                    elif category_key == "Graphics:":
                        options = ["high", "medium", "low"]
                        self.settings_data[json_key] = options[selected_index]
                    elif category_key == "Light Flicker:":
                        self.settings_data[json_key] = (selected_index == 0)  # True for On
            
            # Write to file with proper JSON format
            with open(self.settings_file, 'w') as f:
                f.write("{\n")
                f.write("    // Display settings\n")
                f.write(f'    "fullscreen": {json.dumps(self.settings_data.get("fullscreen", False))},\n')
                f.write(f'    "audio": {json.dumps(self.settings_data.get("audio", 50))},\n')
                f.write(f'    "graphics": {json.dumps(self.settings_data.get("graphics", "high"))},\n')
                f.write(f'    "light_flicker": {json.dumps(self.settings_data.get("light_flicker", True))}\n')
                f.write("}\n")
        except Exception as e:
            # If saving fails, just continue - don't crash the game
            self.engine.debug_log(f"Warning: Could not save settings: {e}", handler=type(self).__name__, event="settings")

    def _handle_back(self) -> Optional[ActionOrHandler]:
        """Handle returning to previous handler (main menu)."""
        if self.parent_handler is not None:
            return self.parent_handler
        else:
            return None  # Fallback - should not happen in practice

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        key = event.sym
        sounds.play_menu_move_sound()
        # Handle escape - go back
        if key == tcod.event.KeySym.ESCAPE:
            return self._handle_back()
            
        # Handle navigation
        elif key == tcod.event.KeySym.UP:
            self.selected_option = (self.selected_option - 1) % len(self.category_keys)
        elif key == tcod.event.KeySym.DOWN:
            self.selected_option = (self.selected_option + 1) % len(self.category_keys)
        
        # Handle left/right for toggling options
        elif key in (tcod.event.KeySym.LEFT, tcod.event.KeySym.RIGHT):
            selected_category_key = self.category_keys[self.selected_option]
            if selected_category_key != "Back" and selected_category_key in self.categories:
                category_data = self.categories[selected_category_key]
                num_options = len(category_data["Options"])
                
                if key == tcod.event.KeySym.LEFT:
                    category_data["SelectedIndex"] = (category_data["SelectedIndex"] - 1) % num_options
                else:  # RIGHT
                    category_data["SelectedIndex"] = (category_data["SelectedIndex"] + 1) % num_options
                
                # Save settings immediately when changed
                self._save_settings()
                
                # Handle immediate fullscreen toggle for Window setting
                if "Window:" in selected_category_key:
                    from __main__ import toggle_fullscreen, _game_context
                    #self.engine.debug_log("Toggled fullscreen mode immediately.", handler=type(self).__name__, event="settings")
                    toggle_fullscreen(context=_game_context)
                
                # Update loop volumes for Audio setting
                if selected_category_key == "Audio:":
                    try:
                        # Import and call the global loop volume update function
                        from sounds import update_all_loop_volumes_from_settings
                        update_all_loop_volumes_from_settings()
                    except Exception:
                        pass  # Silently handle any import/call errors
            
        # Handle selection (Enter/Space)
        elif key == tcod.event.KeySym.RETURN or key == tcod.event.KeySym.SPACE:
            selected_category_key = self.category_keys[self.selected_option]
            
            
            if selected_category_key == "Back":
                return self._handle_back()
            elif selected_category_key == "Controls":
                # Open help/controls window
                return HelpMenuHandler(parent_handler=self)
            elif selected_category_key in self.categories:
                # Toggle to next option
                category_data = self.categories[selected_category_key]
                num_options = len(category_data["Options"])
                category_data["SelectedIndex"] = (category_data["SelectedIndex"] + 1) % num_options
                
                # Save settings immediately when changed
                self._save_settings()
                
                # Handle immediate fullscreen toggle for Window setting
                if "Window:" in selected_category_key:
                    from __main__ import toggle_fullscreen, _game_context
                    self.engine.debug_log("Toggled fullscreen mode immediately.", handler=type(self).__name__, event="settings")
                    toggle_fullscreen(context=_game_context)
                    
                
                # Update loop volumes for Audio setting
                if selected_category_key == "Audio:":
                    try:
                        # Import and call the global loop volume update function
                        from sounds import update_all_loop_volumes_from_settings
                        update_all_loop_volumes_from_settings()
                    except Exception:
                        pass  # Silently handle any import/call errors
                
        return None  # Stay in settings menu




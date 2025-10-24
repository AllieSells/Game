from __future__ import annotations

from math import e
from optparse import Option

import os

from typing import Callable, Tuple, Optional, TYPE_CHECKING, Union
from unittest.mock import Base

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

from text_utils import *


if TYPE_CHECKING:
    from engine import Engine
    from entity import Item, Actor
    from components.container import Container


MOVE_KEYS = {
    # Arrow keys.
    tcod.event.K_UP: (0, -1),
    tcod.event.K_DOWN: (0, 1),
    tcod.event.K_LEFT: (-1, 0),
    tcod.event.K_RIGHT: (1, 0),
    tcod.event.K_HOME: (-1, -1),
    tcod.event.K_END: (-1, 1),
    tcod.event.K_PAGEUP: (1, -1),
    tcod.event.K_PAGEDOWN: (1, 1),
    # Numpad keys.
    tcod.event.K_KP_1: (-1, 1),
    tcod.event.K_KP_2: (0, 1),
    tcod.event.K_KP_3: (1, 1),
    tcod.event.K_KP_4: (-1, 0),
    tcod.event.K_KP_6: (1, 0),
    tcod.event.K_KP_7: (-1, -1),
    tcod.event.K_KP_8: (0, -1),
    tcod.event.K_KP_9: (1, -1),
}

WAIT_KEYS = {
    tcod.event.K_PERIOD,
    tcod.event.K_KP_5,
    tcod.event.K_CLEAR,
}

CONFIRM_KEYS = {
    tcod.event.K_RETURN,
    tcod.event.K_KP_ENTER,
    tcod.event.K_SPACE,
    tcod.event.K_RIGHT,
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

    def handle_events(self, event: tcod.event.Event) -> BaseEventHandler:
        # handles events for input handlers with an engine
        action_or_state = self.dispatch(event)
        if isinstance(action_or_state, BaseEventHandler):
            return action_or_state
        handled = self.handle_action(action_or_state)
        # If an action returned a handler, switch to it directly.
        if isinstance(handled, BaseEventHandler):
            return handled
        if handled:
            # Valid action
            if not self.engine.player.is_alive:
                # Player was killed
                return GameOverEventHandler(self.engine)
            elif self.engine.player.level.requires_level_up:
                return LevelUpEventHandler(self.engine)
            
            # After a player turn, decrement burn durations on equipped items (e.g., torches)
            try:
                player = self.engine.player
                for slot in ("weapon", "offhand"):
                    item = getattr(player.equipment, slot)
                    if item is not None and getattr(item, "burn_duration", None) is not None:
                        try:
                            item.burn_duration -= 1
                            if item.burn_duration <= 0:
                                # Remove the burned-out item: unequip and drop/consume
                                player.equipment.unequip_from_slot(slot, add_message=False)
                                try:
                                    # Remove from inventory if present
                                    if item in player.inventory.items:
                                        player.inventory.items.remove(item)
                                except Exception:
                                    pass
                                self.engine.message_log.add_message(f"Your {item.name} burns out.", color.error)
                        except Exception:
                            pass
            except Exception:
                pass

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
        
        self.engine.handle_enemy_turns()
        self.engine.update_fov()

                # Check for darkness effect
        if "Darkness" in [getattr(e, "name", "") for e in getattr(self.engine.player, "effects", [])]:
            # Player is in darkness; try spawning enemies occasionally
            if random.random() < 0.33:  # 10% chance per tick
                self.engine.player.lucidity = max(0, self.engine.player.lucidity - 1)  # Lose 1 lucidity per tick in darkness
        elif "Darkness" not in [getattr(e, "name", "") for e in getattr(self.engine.player, "effects", [])]:
            self.engine.player.lucidity = min(self.engine.player.max_lucidity, self.engine.player.lucidity + 1)  # Regain 1 lucidity per tick in light
        if self.engine.player.lucidity == 66:
            self.engine.message_log.add_message("You feel your mind slipping...", color.purple)
        elif self.engine.player.lucidity == 33:
            self.engine.message_log.add_message("Your mind is deteriorating!", color.purple)
        elif self.engine.player.lucidity == 10:
            self.engine.message_log.add_message("Your mind is on the brink of collapse!", color.red)
        elif self.engine.player.lucidity == 0:
            self.engine.message_log.add_message("Your mind has collapsed into madness!", color.red)
            # Trigger a sanity event here, e.g., spawn a powerful enemy
        if self.engine.player.lucidity <= 66:
            self.engine._maybe_spawn_enemy_in_dark()
        
        # Try spawning enemies when the player is in Darkness (non-blocking)
        try:
            self._maybe_spawn_enemy_in_dark()
        except Exception:
            pass

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


class CharacterScreenEventHandler(AskUserEventHandler):
    TITLE = "Character Information"

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)

        if self.engine.player.x <= 30:
            x = 40
        else:
            x = 0

        y = 0

        width = len(self.TITLE) + 4

        console.draw_frame(
            x=x,
            y=y,
            width = width,
            height = 7,
            title=self.TITLE,
            clear=True,
            fg=(255,255,255),
            bg=(0,0,0)
        )
        console.print(
            x=x + 1, y=y + 1, string=f"Level: {self.engine.player.level.current_level}"
        )
        console.print(
            x=x + 1, y=y + 2, string=f"XP: {self.engine.player.level.current_xp}"
        )
        console.print(
            x=x + 1,
            y=y + 3,
            string=f"XP for next Level: {self.engine.player.level.experience_to_next_level}",
        )

        console.print(
            x=x + 1, y=y + 4, string=f"Attack: {self.engine.player.fighter.power}"
        )
        console.print(
            x=x + 1, y=y + 5, string=f"Defense: {self.engine.player.fighter.defense}"
        )


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
        
        console.draw_frame(x, y, width, height, current_menu_data["title"], fg=color.white, bg=color.black)
        
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

        if self.engine.player.x <= 30:
            x = 40
        else:
            x = 0

        console.draw_frame(
            x=x,
            y=0,
            width=35,
            height=8,
            title=self.TITLE,
            clear=True,
            fg=(255, 255, 255),
            bg=(0, 0, 0),
        )

        console.print(x=x+1, y=1, string="You Level Up!")
        console.print(x=x+1, y=2, string="Select an attribute to increase")

        console.print(
            x=x + 1,
            y=4,
            string=f"a) Constitution (+20 HP from {self.engine.player.fighter.max_hp})"

        )
        console.print(
            x=x + 1,
            y=5,
            string=f"b) Strength (+1 attack, from {self.engine.player.fighter.power})",
        )
        console.print(
            x=x + 1,
            y=6,
            string=f"c) Agility (+1 defense, from {self.engine.player.fighter.defense})",
        )

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
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
        # Renders inventory menu displaying items in both inventories
        super().on_render(console)
        player_items = list(self.engine.player.inventory.items)
        container_items = list(self.container.items)
        number_of_player_items = len(player_items)
        number_of_container_items = len(container_items)

        height = max(number_of_player_items, number_of_container_items) + 4
        # Fall back to 3 if both inventories empty
        if height <= 3:
            height = 3
        width = 47
        x = (console.width - width) // 2
        y = 1

        # Draw player inventory frame
        console.draw_frame(
            x=x,
            y=y,
            width=width // 2,
            height=height,
            title="Your Inventory",
            clear=True,
            fg=(255, 255, 255),
            bg=(0, 0, 0),
        )

        # Draw container inventory frame
        console.draw_frame(
            x=x + width // 2,
            y=y,
            width=width // 2,
            height=height,
            title=f"{(self.container.parent.name)} Inventory",
            clear=True,
            fg=(255, 255, 255),
            bg=(0, 0, 0),
        )

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
        if number_of_player_items > 0:
            for i, item in enumerate(player_items):
                item_key = chr(ord("a") + i)
                is_equipped = self.engine.player.equipment.item_is_equipped(item)

                item_string = f"({item_key}) {item.name}"

                if is_equipped:
                    item_string = f"{item_string} (E)"

                # Draw selection marker for keyboard navigation
                marker = ">" if i == getattr(self, "selected_index", 0) and self.menu == "Player" else " "
                console.print(x, y + i + 1, marker)
                console.print(x + 1, y + i + 1, item_string)
        else:
            console.print(x + 1, y + 1, "(Empty)")

        # Draw container inventory items
        if number_of_container_items > 0:
            for i, item in enumerate(container_items):
                item_key = chr(ord("a") + i)
                item_string = f"({item_key}) {item.name}"

                # Draw selection marker for keyboard navigation
                marker = ">" if i == getattr(self, "selected_index", 0) and self.menu == "Container" else " "
                console.print(x + width // 2, y + i + 1, marker)
                console.print(x + width // 2 + 1, y + i + 1, item_string)
        else:
            console.print(x + width // 2 + 1, y + 1, "(Empty)")

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        player = self.engine.player
        key = event.sym
        modifier = event.mod

        # Skip filter

        # Tab shifts active menu
        if key == tcod.event.K_TAB:
            self.menu = "Container" if self.menu == "Player" else "Player"
            return None

        # Arrow-key navigation: up/down to move selection, Enter to confirm
        if key == tcod.event.K_UP:
            self.selected_index = max(0, self.selected_index - 1)
            return None
        elif key == tcod.event.K_DOWN:
            if self.menu == "Player":
                max_index = max(0, len(self.engine.player.inventory.items) - 1)
            else:
                max_index = max(0, len(self.container.items) - 1)
            self.selected_index = min(max_index, self.selected_index + 1)
            return None
        elif key in CONFIRM_KEYS:
            # Confirm selection from the active menu
            if self.menu == "Player":
                if not self.engine.player.inventory.items:
                    return None
                return self.on_item_selected(self.engine.player.inventory.items[self.selected_index])
            else:
                if not self.container.items:
                    return None
                return self.on_item_selected(self.container.items[self.selected_index])
    
        # Letter selection still supported but operates on the filtered list
        index = key - tcod.event.KeySym.A

        if 0 <= index <= 26:
            try:
                if self.menu == "Player":
                    selected_item = player.inventory.items[index]
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
                    self.engine.player.equipment.unequip_from_slot(slot, add_message=True)

                self.engine.player.inventory.items.remove(item)
                self.container.items.append(item)
                self.engine.message_log.add_message(f"You transfer the {item.name}.")
            except Exception:
                print(traceback.format_exc(), color.error)
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
                        return self
                    self.engine.player.inventory.items.append(item)
                    self.engine.message_log.add_message(f"You take the {item.name}.")
            except Exception:
                
                self.engine.message_log.add_message(f"Could not transfer {item.name}.", color.error)
        # Return back to container handler
        return self

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

    def on_render(self, console: tcod.Console) -> None:
        """Render an inventory menu, which displays the items in the inventory, and the letter to select them.
        Will move to a different position based on where the player is located, so the player can always see where
        they are.
        """
        super().on_render(console)
        # Build filtered list according to filter function (modular)
        all_items = list(self.engine.player.inventory.items)
        filtered_items = [it for it in all_items if self.item_filter(it)]

        number_of_items_in_inventory = len(filtered_items)

        height = number_of_items_in_inventory + 2

        if height <= 3:
            height = 3

        if self.engine.player.x <= 30:
            x = 40
        else:
            x = 0

        y = 0

        width = len(self.TITLE) + 4

        console.draw_frame(
            x=x,
            y=y,
            width=width,
            height=height,
            title=self.TITLE,
            clear=True,
            fg=(255, 255, 255),
            bg=(0, 0, 0),
        )

        # Ensure we have a selected index for arrow-key navigation
        if not hasattr(self, "selected_index"):
            self.selected_index = 0

        if number_of_items_in_inventory > 0:
            # Clamp selected index to the filtered list
            if self.selected_index >= number_of_items_in_inventory:
                self.selected_index = max(0, number_of_items_in_inventory - 1)

            for i, item in enumerate(filtered_items):
                item_key = chr(ord("a") + i)

                is_equipped = self.engine.player.equipment.item_is_equipped(item)

                item_string = f"({item_key}) {item.name}"

                if is_equipped:
                    item_string = f"{item_string} (E)"

                # Draw selection marker for keyboard navigation
                marker = ">" if i == getattr(self, "selected_index", 0) else " "
                console.print(x, y + i + 1, marker)
                console.print(x + 1, y + i + 1, item_string)
        else:
            console.print(x + 1, y + 1, "(Empty)")

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        player = self.engine.player
        key = event.sym
        modifier = event.mod

        # Build filtered list for selection mapping
        all_items = list(player.inventory.items)
        filtered_items = [it for it in all_items if self.item_filter(it)]

        # Arrow-key navigation: up/down to move selection, Enter to confirm
        if key == tcod.event.K_UP:
            self.selected_index = max(0, self.selected_index - 1)
            return None
        if key == tcod.event.K_DOWN:
            self.selected_index = min(len(filtered_items) - 1 if filtered_items else 0, self.selected_index + 1)
            return None
        if key in CONFIRM_KEYS:
            # If inventory empty, do nothing
            if len(filtered_items) == 0:
                return None
            try:
                selected_item = filtered_items[getattr(self, "selected_index", 0)]
            except Exception:
                self.engine.message_log.add_message("Invalid selection.", color.invalid)
                return None
            return self.on_item_selected(selected_item)

        # Letter selection still supported but operates on the filtered list
        index = key - tcod.event.KeySym.A

        if 0 <= index <= 26:
            try:
                selected_item = filtered_items[index]
            except IndexError:
                self.engine.message_log.add_message("Invalid entry.", color.invalid)
                return None
            return self.on_item_selected(selected_item)

        return super().ev_keydown(event)

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        if item.consumable:
            # Return action for the item
            return item.consumable.get_action(self.engine.player)
        elif item.equippable:
            return actions.EquipAction(self.engine.player, item)
        
        else:
            return None

class ScrollActivateHandler(InventoryEventHandler):
    # Handles using magic/scroll item
    TITLE = "Select a scroll to read"

    def __init__(self, engine, item_filter = None):
        super().__init__(engine, item_filter=lambda it: getattr(it, "consumable", None) is not None and "Scroll" in getattr(it, "name", ""))

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        # Returns the action for the selected item
        if "Scroll" in item.name and item.consumable:
            return item.consumable.get_action(self.engine.player)
        else:
            self.engine.message_log.add_message(f"You cannot read the {item.name}.", color.invalid)



            


class InventoryActivateHandler(InventoryEventHandler):
    # Handles using inventory item
    TITLE = "Select an item to use"

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        # Returns the action for the selected item
        return None
        
class QuaffActivateHandler(InventoryEventHandler):
    # Handles using inventory item
    TITLE = "Select potion to quaff"

    def __init__(self, engine: Engine):
        super().__init__(engine, item_filter=lambda it: getattr(it, "consumable", None) is not None and "Potion" in getattr(it, "name", ""))

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        # Returns the action for the selected item
        if "Potion" in item.name and item.consumable:
            return item.consumable.get_action(self.engine.player)
        else:
            self.engine.message_log.add_message(f"You cannot drink the {item.name}.", color.invalid)
    
class InventoryDropHandler(InventoryEventHandler):
    #Handles dropping inventory item
    
    TITLE = "Select an item to drop"

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        # Drop this item
        return actions.DropItem(self.engine.player, item)


class InventoryEquipHandler(InventoryEventHandler):
    """Shows only equippable items and equips the selected one."""
    TITLE = "Select an item to equip"

    def __init__(self, engine: Engine):
        # Filter for items that have an equippable component
        super().__init__(engine, item_filter=lambda it: getattr(it, "equippable", None) is not None)

    def on_item_selected(self, item: Item) -> Optional[ActionOrHandler]:
        if getattr(item, "equippable", None):
            return actions.EquipAction(self.engine.player, item)
        else:
            self.engine.message_log.add_message(f"{item.name} cannot be equipped.", color.invalid)
            return None

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
    
class LookHandler(SelectIndexHandler):
    """Enhanced look handler with detailed inspection sidebar."""

    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.show_details = True  # Always show details now
        self.detail_index = 0  # Index for cycling through items at location
        self.scroll_offset = 0  # For scrolling through text

    def on_index_selected(self, x: int, y: int) -> Optional[ActionOrHandler]:
        """Return to main handler when location is selected."""
        return MainGameEventHandler(self.engine)

    def on_render(self, console: tcod.Console) -> None:
        # Call parent render for cursor highlighting but skip the basic name box
        # Highlights tile underneath cursor
        super(SelectIndexHandler, self).on_render(console)

        x, y = self.engine.mouse_location
        x, y = int(x), int(y)
        console.rgb["bg"][x, y] = color.white
        console.rgb["fg"][x, y] = color.black
        
        # Always show detailed sidebar
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
        
        # Draw sidebar frame
        console.draw_frame(
            x=sidebar_x, y=sidebar_y, 
            width=sidebar_width, height=sidebar_height,
            title="Inspect", clear=True,
            fg=color.white, bg=color.black
        )
        
        # Show current item info at the top
        info_y = sidebar_y + 2
        
        if len(items_and_entities) > 1:
            # Center the item counter
            counter_text = f"{self.detail_index + 1} of {len(items_and_entities)}"
            counter_x = sidebar_x + (sidebar_width - len(counter_text)) // 2
            console.print(counter_x, info_y, counter_text, fg=color.grey)
            info_y += 1
            
        # Center the visual preview horizontally in the sidebar
        preview_size = 5  # Size of the preview area (3x3 + 2 for frame = 5x5)
        preview_x = sidebar_x + (sidebar_width - preview_size) // 2
        preview_y = info_y + 1
        self.render_visual_preview(console, current_item, x, y, preview_x, preview_y)
        
        # Build scrollable text content below the preview
        text_details_y = preview_y + preview_size + 2  # Leave some space after preview
        text_area_width = sidebar_width - 4  # Use full width minus margins
        text_area_height = sidebar_height - (text_details_y - sidebar_y) - 3  # Leave space for instructions
        
        # Build complete text content
        full_text = self.build_item_description(current_item, text_area_width)
        
        # Render scrollable text
        self.render_scrollable_text(console, full_text, sidebar_x, text_details_y, text_area_width, text_area_height)
            
        # Show navigation instructions
        instructions_y = sidebar_y + sidebar_height - 4
        console.print(sidebar_x + 2, instructions_y, "Alt+←→: Cycle items", fg=color.grey)
        console.print(sidebar_x + 2, instructions_y + 1, "Shift+↑↓: Scroll text", fg=color.grey)
        console.print(sidebar_x + 2, instructions_y + 2, "Enter: Exit details", fg=color.grey)

    def render_visual_preview(self, console: tcod.Console, current_item: dict, look_x: int, look_y: int, preview_x: int, preview_y: int) -> None:
        """Render a visual preview of the object being inspected."""
        # Create a small framed preview area (3x3 for now, can adjust)
        preview_size = 3
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

    def wrap_text(self, text: str, max_width: int) -> list:
        """Wrap text to fit within max_width, returning list of lines."""
        if not text:
            return []
        
        words = text.split()
        lines = []
        current_line = []
        current_length = 0
        
        for word in words:
            # Check if adding this word would exceed the width
            word_length = len(word)
            space_length = 1 if current_line else 0
            
            if current_length + space_length + word_length <= max_width:
                current_line.append(word)
                current_length += space_length + word_length
            else:
                # Start a new line
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_length = word_length
        
        # Add the last line if it has content
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines

    def build_item_description(self, current_item: dict, max_width: int) -> list:
        """Build complete description text as list of lines for scrolling."""
        lines = []
        # Entity handling
        if current_item['type'] == 'entity':
            entity = current_item['object']

            # Get alive or dead status
            if hasattr(entity, 'is_alive') and not entity.is_alive:
                if hasattr(entity, 'sentient') and entity.sentient:
                    status_text = red(entity.name)
                    wrapped_status = wrap_colored_text_to_strings(status_text, max_width)
                    lines.extend(wrapped_status)
                    lines.append("")  # Empty line for spacing

            # Get name, if known
            if hasattr(entity, 'sentient') and entity.sentient:
                if hasattr(entity, 'name'):
                    if hasattr(entity, 'is_known') and not entity.is_known:
                        # Only print knowledge for entities that have it (NPCs, not chests)
                        if hasattr(entity, 'knowledge'):
                            print(entity.knowledge)
                            objective_pronoun = entity.knowledge["pronouns"]["object"].lower()
                            name_text = f"You do not know {objective_pronoun}."
                        else:
                            # For entities without knowledge (like chests), show generic message
                            name_text = f"You don't know what this is."
                        lines.extend(self.wrap_text(name_text, max_width))
                        lines.append("")  # Empty line for spacing
                    else:
                        name_text = f"{entity.name}"
                        lines.extend(self.wrap_text(name_text, max_width))
                        lines.append("")  # Empty line for spacing
            else:
                if hasattr(entity, 'name'):
                    name_text = f"{entity.name}"
                    lines.extend(wrap_colored_text_to_strings(name_text, max_width))
                    lines.append("")  # Empty line for spacing
                    
            # Add entity description
            if hasattr(entity, 'description') and entity.description:
                wrapped_desc = self.wrap_text(entity.description, max_width)
                lines.extend(wrapped_desc)
                lines.append("")  # Empty line for spacing
            
            # Add lock status if applicable
            if hasattr(entity, "container") and entity.container.locked:
                lock_text = red("It has a lock.")
                # Use proper colored text wrapping
                wrapped_lock = wrap_colored_text_to_strings(lock_text, max_width)
                lines.extend(wrapped_lock)
                lines.append("")  # Empty line for spacing

            # Add opinion if sentient
            if hasattr(entity, 'sentient') and entity.sentient:
                if hasattr(entity, "opinion"):
                    if entity.opinion >= 66:
                        opinion_text = green(f"{(entity.knowledge['pronouns']['subject']).capitalize()} smiles at you")
                    elif entity.opinion >= 33:
                        opinion_text = yellow(f"{(entity.knowledge['pronouns']['subject']).capitalize()} looks at you unfeelingly.")
                    else:
                        opinion_text = red(f"{(entity.knowledge['pronouns']['subject']).capitalize()} frowns at you")
                    # Use proper colored text wrapping
                    wrapped_opinion = wrap_colored_text_to_strings(opinion_text, max_width)
                    lines.extend(wrapped_opinion)
                    lines.append("")  # Empty line for spacing
            
            # Add value if applicable
            if hasattr(entity, 'value'):
                if entity.value > 0:
                    value_text = f"Estimated value: <yellow>{entity.value} gold.</yellow>"
                    lines.extend(wrap_colored_text_to_strings(value_text, max_width))      
        # Tile handling
        elif current_item['type'] == 'tile':
            tile_info = current_item['object']
            
            # Add tile information
            # Preserve the name verbatim (don't lower-case markup tags)
            type_text = f"This is a {tile_info['name']}."
            lines.extend(wrap_colored_text_to_strings(type_text, max_width))
            
            walkable_text = f" {'You can walk here.' if tile_info['walkable'] else 'You cannot walk here.'}"
            lines.extend(wrap_colored_text_to_strings(walkable_text, max_width))
            
            transparent_text = f"{'You can see through this.' if tile_info['transparent'] else 'You cannot see through this.'}"
            lines.extend(wrap_colored_text_to_strings(transparent_text, max_width))
            
            if tile_info.get('interactable', False):
                interact_text = cyan(f"You can interact with this {(tile_info['name']).lower()}.")
                # Use proper colored text wrapping
                wrapped_interact = wrap_colored_text_to_strings(interact_text, max_width)
                lines.extend(wrapped_interact)
        
        return lines

    def render_scrollable_text(self, console: tcod.Console, text_lines: list, x: int, y: int, width: int, height: int) -> None:
        """Render text with scrolling support."""
        if not text_lines:
            return
            
        # Limit scroll offset to valid range
        max_scroll = max(0, len(text_lines) - height)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))
        
        # Calculate which lines to display based on scroll offset
        start_line = self.scroll_offset
        end_line = min(len(text_lines), start_line + height)
        
        # Display the visible lines
        for i, line_idx in enumerate(range(start_line, end_line)):
            if line_idx < len(text_lines):
                print_colored_markup(console, x + 2, y + i, text_lines[line_idx], default_color=color.white)
        
        # Show scroll indicators if there's more content
        if start_line > 0:
            console.print(x + width - 3, y, "↑", fg=color.yellow)
        if end_line < len(text_lines):
            console.print(x + width - 3, y + height - 1, "↓", fg=color.yellow)

    def render_entity_details(self, console: tcod.Console, entity, sidebar_x: int, info_y: int, sidebar_width: int) -> None:
        """Render details for an entity (actor/NPC)."""
        max_text_width = sidebar_width - 4  # Leave space for indentation and borders
        if hasattr(entity, 'description') and entity.description:
            
            # Wrap description text
            wrapped_lines = self.wrap_text(entity.description, max_text_width)
            for line in wrapped_lines:
                console.print(sidebar_x + 2, info_y, line, fg=color.green)
                info_y += 1



    def render_tile_details(self, console: tcod.Console, tile_info, sidebar_x: int, info_y: int, sidebar_width: int) -> None:
        """Render details for a tile."""
        max_text_width = sidebar_width - 4  # Leave space for indentation and borders
        
        # Wrap each piece of tile information
        type_text = f"Type: {tile_info['name']}"
        wrapped_type = self.wrap_text(type_text, max_text_width)
        for line in wrapped_type:
            console.print(sidebar_x + 2, info_y, line, fg=color.green)
            info_y += 1
            
        walkable_text = f"Walkable: {'Yes' if tile_info['walkable'] else 'No'}"
        wrapped_walkable = self.wrap_text(walkable_text, max_text_width)
        for line in wrapped_walkable:
            console.print(sidebar_x + 2, info_y, line, fg=color.white)
            info_y += 1
            
        transparent_text = f"Transparent: {'Yes' if tile_info['transparent'] else 'No'}"
        wrapped_transparent = self.wrap_text(transparent_text, max_text_width)
        for line in wrapped_transparent:
            console.print(sidebar_x + 2, info_y, line, fg=color.white)
            info_y += 1
            
        if tile_info.get('interactable', False):
            interact_text = "Interactable: Yes"
            wrapped_interact = self.wrap_text(interact_text, max_text_width)
            for line in wrapped_interact:
                console.print(sidebar_x + 2, info_y, line, fg=color.yellow)
                info_y += 1

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
                    display_name = red(f"Corpse of {display_name}")

                
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
        
        # Handle item cycling with Alt + left/right FIRST (before parent class intercepts)
        if key == tcod.event.KeySym.LEFT and modifier & (tcod.event.KMOD_LALT | tcod.event.KMOD_RALT):
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
            width=self.radius ** 2,
            height = self.radius ** 2,
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
            self.engine.debug = not self.engine.debug
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
        elif key == tcod.event.KeySym.E:
            return InventoryEquipHandler(self.engine)
        elif key == tcod.event.KeySym.Q:
            return QuaffActivateHandler(self.engine)
        elif key == tcod.event.KeySym.D:
            return InventoryDropHandler(self.engine)
        elif key == tcod.event.KeySym.C:
            return CharacterScreenEventHandler(self.engine)
        elif key == tcod.event.K_SLASH:
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
    tcod.event.K_UP: -1,
    tcod.event.K_DOWN: 1,
    tcod.event.K_PAGEUP: -10,
    tcod.event.K_PAGEDOWN: 10,
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

        # Draw a frame with a custom banner title.
        log_console.draw_frame(0, 0, log_console.width, log_console.height)
        log_console.print_box(
            0, 0, log_console.width, 1, "┤Message history├", alignment=tcod.CENTER
        )

        # Render the message log using the cursor parameter.
        self.engine.message_log.render_messages(
            log_console,
            1,
            1,
            log_console.width - 2,
            log_console.height - 2,
            self.engine.message_log.messages[: self.cursor + 1],
        )
        log_console.blit(console, 3, 3)

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[MainGameEventHandler]:
        # Fancy conditional movement to make it feel right.
        if event.sym in CURSOR_Y_KEYS:
            adjust = CURSOR_Y_KEYS[event.sym]
            if adjust < 0 and self.cursor == 0:
                # Only move from the top to the bottom when you're on the edge.
                self.cursor = self.log_length - 1
            elif adjust > 0 and self.cursor == self.log_length - 1:
                # Same with bottom to top movement.
                self.cursor = 0
            else:
                # Otherwise move while staying clamped to the bounds of the history log.
                self.cursor = max(0, min(self.cursor + adjust, self.log_length - 1))
        elif event.sym == tcod.event.K_HOME:
            self.cursor = 0  # Move directly to the top message.
        elif event.sym == tcod.event.K_END:
            self.cursor = self.log_length - 1  # Move directly to the last message.
        else:  # Any other key moves back to the main game state.
            return MainGameEventHandler(self.engine)
        return None

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

        text = f"\nESC: Escape / Save and Quit \n?: Control Menu \nV: Message Log \nG: Pick Up Object \nI: Use/Equip Items \nD: Drop Items \nC: Character Menu \n/: Look Around"
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


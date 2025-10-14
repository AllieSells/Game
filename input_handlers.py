from __future__ import annotations

from optparse import Option

import os

from typing import Callable, Tuple, Optional, TYPE_CHECKING, Union
from unittest.mock import Base

import tcod.event

import traceback

import actions
from actions import (
    Action,
    BumpAction,
    PickupAction,
    WaitAction,
    OpenAction,
)

import color
import engine
import exceptions


if TYPE_CHECKING:
    from engine import Engine
    from entity import Item
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
    # lets player look using keyboard

    def on_index_selected(self, X: int, y: int) -> MainGameEventHandler:
        # Return to main handler
        return MainGameEventHandler(self.engine)

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
        elif key in MOVE_KEYS:
            dx, dy = MOVE_KEYS[key]
            action = BumpAction(player, dx, dy)
        elif key in WAIT_KEYS:
            action = WaitAction(player)
        elif key ==tcod.event.K_ESCAPE:
            raise SystemExit()
        elif key == tcod.event.KeySym.O:
            action = OpenAction(player)
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


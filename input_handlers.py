from __future__ import annotations

import os
import json
import textwrap
import time
from typing import Callable, Tuple, Optional, TYPE_CHECKING, Union

import numpy as np
import tcod.event
import random
import traceback


import actions
import balance_config
import proficiency_system as profsys
import identify as identify_system
from actions import (
    Action,
    PickupAction,
    WaitAction,
)

import color
from components.dialogue_generator import ConversationNode
from components.effect import BurningEffect
import exceptions
from render_functions import MenuRenderer

from text_utils import print_wrapped_colored_text, wrap_colored_text
import sounds


if TYPE_CHECKING:
    from engine import Engine
    from entity import Item, Actor
    from components.container import Container


def _fade_console_background(
    console: tcod.Console,
    menu_x: int = None,
    menu_y: int = None,
    menu_width: int = None,
    menu_height: int = None,
) -> None:
    """Fade the console background except for an optional menu rectangle."""
    fade_alpha = 0.4
    fade_color = np.array((20, 20, 30), dtype=np.float32)

    original_bg = console.bg.copy()
    blended_bg = (
        original_bg.astype(np.float32) * (1.0 - fade_alpha)
        + fade_color * fade_alpha
    ).astype(np.uint8)

    console.bg[:] = blended_bg

    if (
        menu_x is not None
        and menu_y is not None
        and menu_width is not None
        and menu_height is not None
    ):
        menu_x2 = min(console.width, menu_x + menu_width)
        menu_y2 = min(console.height, menu_y + menu_height)
        if menu_x < menu_x2 and menu_y < menu_y2:
            console.bg[menu_x:menu_x2, menu_y:menu_y2] = original_bg[menu_x:menu_x2, menu_y:menu_y2]







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

        def _as_tile(position):
            if position is None:
                return None
            if hasattr(position, "x") and hasattr(position, "y"):
                return int(position.x), int(position.y)
            return int(position[0]), int(position[1])

        ui_tile = _as_tile(getattr(event, "ui_tile", getattr(event, "tile", None)))
        world_tile = _as_tile(getattr(event, "world_tile", ui_tile))
        use_world_space = isinstance(self, (MainGameEventHandler, SelectIndexHandler))

        if ui_tile is not None:
            try:
                self.engine.mouse_ui_x = int(ui_tile[0])
                self.engine.mouse_ui_y = int(ui_tile[1])
            except Exception:
                pass


        active_tile = world_tile if use_world_space and world_tile is not None else ui_tile

        if active_tile is not None:
            try:
                self.engine.mouse_x = int(active_tile[0])
                self.engine.mouse_y = int(active_tile[1])
            except Exception:
                pass

        return None

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[ActionOrHandler]:
        """Handle mouse clicks during main game - just print for now."""
        try:
            if event.button == tcod.event.BUTTON_LEFT:
                self.engine.mouse_held = True
        except Exception:
            pass
    
        return None

    def ev_mousebuttonup(self, event: tcod.event.MouseButtonUp):
        try:
            if event.button == tcod.event.BUTTON_LEFT:
                self.engine.mouse_held = False
        except Exception:
            pass
        return None
    
    def on_render(self, console: tcod.Console) -> None:
        raise NotImplementedError()
    
    def ev_quit(self, event: tcod.event.Quit) -> Optional[Action]:
        raise SystemExit()


    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[BaseEventHandler]:
        """Any key returns to the parent handler."""
        return self.parent




class CRTTransition(BaseEventHandler):
    """Triggers CRT power-off/on animation

    To use,
        return CRTTransition(MainGameEventHandler(engine),
                             pre_fn=lambda: (sounds.stop_menu_ambience(),
                                             sounds.stop_all_music()),
                             post_fn=sounds.start_dungeon_music)
    """
    def __init__(self, target, *, pre_fn=None, post_fn=None):
        if callable(target) and not isinstance(target, BaseEventHandler):
            self._factory = target
            self._target = None
        else:
            self._factory = None
            self._target = target
        self._pre_fn = pre_fn # called during black screen phase
        self._post_fn = post_fn # called before new handler is returned
        # Protocol fields expected by main.py CRT state
        self.game_load = False
        self.generation_started = False

    def start_generation(self) -> None:
        if self._pre_fn is not None:
            self._pre_fn()
        if self._factory is not None:
            self._target = self._factory()
        self.game_load = True
    
    def handle_events(self, event) -> "BaseEventHandler":
        if getattr(event, '_crt_transition', False):
            if self._post_fn is not None:
                self._post_fn()
            return self._target if self._target is not None else self
        return self

    def on_render(self, console) -> None:
        pass # main renders black during prograss, so this is never called

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
        # Defer immediate handler switch until one final frame update has been rendered.
        pending = getattr(self.engine, '_pending_handler', None)
        pending_ready = getattr(self.engine, '_pending_handler_ready', False)
        if pending is not None:
            if pending_ready:
                self.engine._pending_handler = None
                self.engine._pending_handler_ready = False
                return pending
            return self

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
            result = self.engine.execute_action(action, is_player_action=False)
        except exceptions.Impossible as exc:
            self.engine.message_log.add_message(exc.args[0], color.impossible)
            return False #skip enemy turn
        # If an action returns a handler, switch without advancing the turn.
        if isinstance(result, BaseEventHandler):
            return result
        
        # Turn advancement is now handled by the turn manager
        return True

    def on_render(self, console: tcod.Console) -> None:
        game_map = getattr(self.engine, "game_map", None)
        if (
            game_map is not None
            and console.width == game_map.width
            and console.height == game_map.height
        ):
            self.engine.render_game(console)
        else:
            self.engine.render_ui(console)

    def render_faded(self, console: tcod.Console, menu_x: int = None, menu_y: int = None, menu_width: int = None, menu_height: int = None) -> None:
        # In the GPU popup overlay path main.py already applies dim_tex on the GPU.
        # Skip the expensive numpy fade to avoid redundant CPU work every dirty frame.
        if getattr(self.engine, '_popup_overlay_active', False):
            return
        _fade_console_background(console, menu_x, menu_y, menu_width, menu_height)
    
class AskUserEventHandler(EventHandler):
    # Handles user input for actions with special input
    def __init__(self, engine: Engine):
        super().__init__(engine)
        # Auto-minimize the minimap while this menu is open, restore on exit
        engine._pre_menu_minimap = getattr(engine, 'show_minimap', 0)
        engine.show_minimap = 2

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


class PopupEventHandler(AskUserEventHandler):

    def __init__(self, engine: "Engine", _anim_duration: float = 0.1) -> None:
        super().__init__(engine)
        self._px: Optional[int] = None
        self._py: Optional[int] = None
        self._pw: Optional[int] = None
        self._ph: Optional[int] = None
        self._opened_at = time.monotonic()
        self._anim_duration = 0.1  # Duration of the popup animation in seconds

    # ------------------------------------------------------------------
    # Bounds helpers
    # ------------------------------------------------------------------

    def _set_popup_bounds(self, x: int, y: int, w: int, h: int) -> None:
        """Register the screen-space bounds of this popup.

        Call this in ``on_render`` once the window position is finalized so
        the base-class mouse handler knows which area belongs to the popup.
        """
        self._px, self._py, self._pw, self._ph = x, y, w, h

    def _in_popup(self, mx: int, my: int) -> bool:
        """Return *True* if ``(mx, my)`` is inside the popup's registered bounds."""
        if self._px is None:
            return True  # bounds not set yet – assume inside to avoid accidental close
        return (self._px <= mx < self._px + self._pw and
                self._py <= my < self._py + self._ph)

    def get_popup_scale(self):
        t = (time.monotonic() - self._opened_at) / self._anim_duration
        t = min(1.0, max(0.0, t))

        return 1.0 - (1.0 - t) ** 3 # linear ease in


    # ------------------------------------------------------------------
    # Mouse dispatch
    # ------------------------------------------------------------------

    def ev_mousebuttondown(
        self, event: tcod.event.MouseButtonDown
    ) -> Optional[ActionOrHandler]:
        if event.button not in (tcod.event.BUTTON_LEFT, tcod.event.BUTTON_RIGHT):
            return None
        if event.button == tcod.event.BUTTON_LEFT:
            self.engine.mouse_held = True

        mx, my = int(event.tile.x), int(event.tile.y)

        # Click outside the popup → close
        if not self._in_popup(mx, my):
            return self.on_exit()

        if event.button == tcod.event.BUTTON_RIGHT:
            return self.on_right_click(mx, my)
        return self.on_left_click(mx, my)

    # ------------------------------------------------------------------
    # Hooks for subclasses
    # ------------------------------------------------------------------

    def on_left_click(self, mx: int, my: int) -> Optional[ActionOrHandler]:
        """Left-click inside the popup.  Override in subclasses."""
        return None

    def on_right_click(self, mx: int, my: int) -> Optional[ActionOrHandler]:
        """Right-click inside the popup.  Override in subclasses."""
        return None

class TestPopupHandler(PopupEventHandler):

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)

        scale = self.get_popup_scale()
        total_width = 30
        total_height = 10

        x = (console.width - 30) // 2
        y = (console.height - 10) // 2
        draw_w = max(4, int(total_width * scale))
        draw_h = max(4, int(total_height * scale))
        draw_x = x + (total_width - draw_w) // 2
        draw_y = y + (total_height - draw_h) // 2


        self._set_popup_bounds(draw_x, draw_y, draw_w, draw_h)
        MenuRenderer.draw_parchment_background(console, draw_x, draw_y, draw_w, draw_h)
        MenuRenderer.draw_ornate_border(console, draw_x, draw_y, draw_w, draw_h, "Test Popup")
        print(scale)
        if scale < 1.0:
            return

        console.print(draw_x + 2, draw_y + 2, "This is a test popup.", fg=(255, 255, 255))


class CharacterScreenEventHandler(EventHandler):
    TITLE = "Character Sheet"

    def __init__(self, engine):
        super().__init__(engine)
        # Collapsible sections state (kept for future use). Sections removed per request.
        self.collapsed_sections = set()
        


class TradeEventHandler(PopupEventHandler):
    # Container UI recycled for trading. Modified.
    def __init__(self, engine: Engine, container: Container):
        super().__init__(engine)
        self.engine.context_hints = [
            ("Enter", "Trade"),
            ("\u2191\u2193", "Navigate"),
            ("Tab", "Switch Side"),
            ("Esc", "Close"),
        ]
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

        scale = self.get_popup_scale()


        x = (console.width - 30) // 2
        y = (console.height - 10) // 2
        draw_w = max(4, int(total_width * scale))
        draw_h = max(4, int(height * scale))
        draw_x = x + (total_width - draw_w) // 2
        draw_y = y + (height - draw_h) // 2
        
        self._set_popup_bounds(draw_x, draw_y, draw_w, draw_h)
        super().render_faded(console, draw_x, draw_y, draw_w, draw_h)
        MenuRenderer.draw_parchment_background(console, draw_x, draw_y, draw_w, draw_h)
        # Draw ornate main border
        npc_color = getattr(self.container.parent, 'color', 'Container')
        container_name = getattr(self.container.parent, 'name', 'Container')
        is_corpse = getattr(self.container.parent, 'type', None) == 'Dead'
        title = "Corpse" if is_corpse else f"Trading with {container_name}"
        MenuRenderer.draw_ornate_border(console, draw_x, draw_y, draw_w, draw_h, title)
        

        if scale < 1.0:
            return

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
                display_name = identify_system.get_display_name(self.engine.player, item)
                qty = int(group.get('quantity', 1) or 1)
                if qty > 1:
                    display_name = f"{display_name} (x{qty})"
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
                shown_name = identify_system.get_display_name(self.engine.player, item)
                item_string = f"• {shown_name} ({item_value}gp)"
                if len(item_string) > panel_width - 2:
                    item_string = f"• {shown_name[:panel_width - 12]}... ({item_value}gp)"

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
            instructions = ""
        else:
            instructions = ""
        inst_x = x + (total_width - len(instructions)) // 2
        console.print(inst_x, y + height - 2, instructions, fg=(180, 140, 100))

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        key = event.sym

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
                    self.engine.player.equipment.unequip_item(item, add_message=True)
                    

                # Check container capacity
                if len(self.container.items) >= self.container.capacity:
                    self.engine.message_log.add_message("Trade failed.", color.error)
                    return self

                self.engine.player.inventory.items.remove(item)
                identify_system.cancel_identification_for_item(self.engine.player, item, engine=self.engine, quiet=True)
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
                
                shown_name = identify_system.get_display_name(self.engine.player, item)
                self.engine.message_log.add_message(f"You sell the {shown_name}.")
            except Exception as e:
                self.engine.debug_log(f"Transfer failed with exception: {e}", handler=type(self).__name__, event="trade")
                self.engine.debug_log(traceback.format_exc(), handler=type(self).__name__, event="trade")
                shown_name = identify_system.get_display_name(self.engine.player, item)
                self.engine.message_log.add_message(f"Could not transfer {shown_name}.", color.error)
        else:
            # Transfer from container to player
            try:
                if self.engine.player.gold < int(item.value * 1.5):
                    self.engine.message_log.add_message("You don't have enough gold.", color.error)
                    return self
                else:
                    self.container.items.remove(item)
                    if not self.engine.player.inventory.can_carry(item):
                        self.engine.message_log.add_message("You are carrying too much.", color.error)
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

                        shown_name = identify_system.get_display_name(self.engine.player, item)
                        self.engine.message_log.add_message(f"You buy the {shown_name}.")
            except Exception:
                self.engine.debug_log(traceback.format_exc(), handler=type(self).__name__, event="trade")
                shown_name = identify_system.get_display_name(self.engine.player, item)
                self.engine.message_log.add_message(f"Could not transfer {shown_name} to {self.container.name}.", color.error)
        # Return back to container handler
        return self
    



class DialogueEventHandler(PopupEventHandler):
    """Handles dialogue interactions with NPCs with hierarchical menu system."""
    _TEXT_REVEAL_RATE = 42.0
    
    def __init__(self, engine: Engine, npc: Actor):
        super().__init__(engine)
        self.engine.context_hints = [
            ("\u2191\u2193", "Navigate"),
            ("Enter", "Select"),
            ("Esc", "Exit"),
        ]
        self.npc = npc
        # Initialize dialogue system
        self.dialogue = ConversationNode()
        self._dialogue_started_at = None
        self._last_visible_chars = 0
        
        # Menu system
        self.current_menu = "main"
        if npc.is_known:
            knows_name = npc.name
        else:
            knows_name = npc.unknown_name
        self.selected_index = 0
        self.talked_to_guide = False
        self.menu_structure = self._build_menu(npc, knows_name)
        
        # Generate initial dialogue text
        self.current_dialogue = self.dialogue.generate_dialogue(character=self.npc, context=self.npc.dialogue_context)
        self._dialogue_started_at = None
        self._last_visible_chars = 0

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
        if display_name is None:
            display_name = "???"
        self.engine.message_log.add_message(f"{display_name}: {self.current_dialogue[0]}", color.blue)
        if isinstance(self.current_dialogue[1], str):
            self.npc.dialogue_context = [self.current_dialogue[1]]
        else:
            self.npc.dialogue_context = self.current_dialogue[1]

        # Portrait: prefer composited _portrait_path, then .portrait, then default
        import os as _os
        _npc_portrait = getattr(self.npc, '_portrait_path', None) or getattr(self.npc, 'portrait', None)
        if _npc_portrait and _os.path.isfile(_npc_portrait):
            _portrait_default = _npc_portrait
        else:
            _portrait_default = _os.path.join("chargen", "processed", "white_male_base.png")
        self._portrait_path = _portrait_default if _os.path.isfile(_portrait_default) else None
        self._portrait_dest_tiles = None  # (col, row, w, h) tile coords — set in on_render
        self._dlg_opt_y = None  # first option row — set in on_render, read by mouse handlers
        self._dlg_box_y = None
        self._dlg_box_h = None

    # ------------------------------------------------------------------
    # Standard reusable menu pages (mix and match in _build_menu below)
    # ------------------------------------------------------------------

    def _page_questions(self) -> dict:
        return {
            "title": "Questions",
            "options": [
                {"text": "Where are we?",        "action": "dialogue", "context": ["Location"]},
                {"text": "What are you called?", "action": "dialogue", "context": ["Identity"]},
                {"text": "What do you know?",    "action": "dialogue", "context": ["Knowledge"]},
                {"text": "[Back]",               "action": "submenu",  "target": "main"},
            ],
        }

    # ------------------------------------------------------------------
    # Menu builder — add a new elif branch for each entity type.
    # npc.type is set on the entity (e.g. "Merchant", "Quest Giver", etc.)
    # Each branch returns a complete menu_structure dict.
    # ------------------------------------------------------------------

    def _build_menu(self, npc, display_name: str) -> dict:
        if npc.type == "villager":
            return {
                "main": {
                    "title": f"Talking to {display_name}",
                    "options": [
                        {"text": "Hello",     "action": "dialogue", "context": ["Greeting"]},
                        {"text": "Questions", "action": "submenu",  "target": "questions"},
                        {"text": "Trade",     "action": "trade",    "target": "trade"},
                        {"text": "Farewell",  "action": "exit"},
                    ],
                },
                "questions": self._page_questions(),
            }

        elif npc.type == "guide":
            if not npc.is_known:
                return {
                    "main": {
                        "title": f"Talking to the old man",
                        "options": [
                            {"text": "Where am I? Who are you?", "action": "dialogue", "context": ["guide_greeting"]}
                        ]
                    }
                }
            else:
                return {
                    "main": {
                        "title": f"Talking to {display_name}",
                        "options": [
                            {"text": "Tell me about combat", "action": "dialogue", "context": ["guide_combat"]},
                            {"text": "Tell me about magic", "action": "dialogue", "context": ["guide_magic"]},
                            {"text": "Tell me about items", "action": "dialogue", "context": ["guide_items"]},
                            {"text": "Tell me about this place", "action": "dialogue", "context": ["guide_world"]}
                        ]
                    }
                }

    def update_menu_title(self):
        """Update the main menu title when NPC becomes known."""
        knows_name = self.npc.name if self.npc.is_known else self.npc.unknown_name
        self.menu_structure["main"]["title"] = f"Talking to {knows_name}"
    
    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)
        scale = self.get_popup_scale()

        BOX_W  = 50
        PORT_W = 6   # portrait area width  in tiles (square: keep == PORT_H)
        PORT_H = 6   # portrait area height in tiles
        # layout rows: top_border(1) + portrait(PORT_H) + divider(1) + blank(1)
        #              + options(_max_opts) + blank(1) + instructions(1) + bot_border(1)
        _max_opts = max(len(m["options"]) for m in self.menu_structure.values())
        BOX_H  = PORT_H + _max_opts + 6

        # Centre in 80-wide console; keep inside the 40-row game area
        x = (80 - BOX_W) // 2
        y = max(1, (40 - BOX_H) // 2)

        
        

        draw_w = max(4, int(BOX_W * scale))
        draw_h = max(4, int(BOX_H * scale))
        draw_x = x + (BOX_W - draw_w) // 2
        draw_y = y + (BOX_H - draw_h) // 2




        current_menu_data = self.menu_structure[self.current_menu]

        # ── Background & outer border ─────────────────────────────────────────
        self._set_popup_bounds(draw_x, draw_y, draw_w, draw_h)
        super().render_faded(console, draw_x, draw_y, draw_w, draw_h)
        MenuRenderer.draw_parchment_background(console, draw_x, draw_y, draw_w, draw_h)
        MenuRenderer.draw_ornate_border(console, draw_x, draw_y, draw_w, draw_h, current_menu_data["title"])


        if scale < 1.0:
            return
        
        if self._dialogue_started_at is None:
            self._dialogue_started_at = time.monotonic()

        # ── Portrait zone: black bg so the GPU PNG sits cleanly on top ────────
        PORT_X = x + 1
        PORT_Y = y + 1
        console.draw_rect(PORT_X, PORT_Y, PORT_W, PORT_H, ch=ord(' '), bg=color.parchment_dark)
        # Expose tile rect so main.py knows where to blit the portrait texture
        self._portrait_dest_tiles = (PORT_X, PORT_Y, PORT_W, PORT_H)

        # ── Vertical separator between portrait zone and text zone ────────────
        VSEP_X = x + PORT_W + 1
        for _row in range(PORT_Y, PORT_Y + PORT_H):
            console.print(VSEP_X, _row, '│', fg=color.bronze_border, bg=color.parchment_dark)
        # Connect separator to top border
        console.print(VSEP_X, y, '┬', fg=color.bronze_border, bg=color.parchment_dark)

        # ── Dialogue text (right of the separator) ────────────────────────────
        TEXT_X = VSEP_X + 1
        TEXT_W = BOX_W - PORT_W - 3   # from TEXT_X to right border (exclusive)
        if hasattr(self, 'current_dialogue') and self.current_dialogue:
            from text_utils import wrap_colored_text, print_colored_text
            full_text = self.current_dialogue[0]
            
            # Dialogue reveal counter
            visible_chars = min(
                len(full_text),
                max(1, int((time.monotonic() - self._dialogue_started_at) * self._TEXT_REVEAL_RATE)),
            )
            wrapped = wrap_colored_text(
                full_text[:visible_chars], TEXT_W, default_color=color.teal
            )
            if visible_chars > self._last_visible_chars:
                for c in range(self._last_visible_chars + 1, visible_chars + 1):
                    if c != len(full_text) and c % 2 == 0:
                        #print(visible_chars)
                        if self.npc.knowledge.get("gender") and self.npc.knowledge.get("pitch"):
                            sounds.play_voice(self.npc.knowledge["gender"], self.npc.knowledge["pitch"])
                        else:
                            continue

            self._last_visible_chars = visible_chars

            curr_y = PORT_Y
            for line_parts in wrapped:
                if curr_y >= PORT_Y + PORT_H:
                    break
                print_colored_text(console, TEXT_X, curr_y, line_parts)
                curr_y += 1

        # ── Horizontal divider below portrait / text ──────────────────────────
        DIV_Y = y + PORT_H + 1
        console.print(x,           DIV_Y, '├', fg=color.bronze_border, bg=color.parchment_dark)
        console.print(VSEP_X,      DIV_Y, '┴', fg=color.bronze_border, bg=color.parchment_dark)
        console.print(x + BOX_W - 1, DIV_Y, '┤', fg=color.bronze_border, bg=color.parchment_dark)
        for _dx in range(1, BOX_W - 1):
            if x + _dx != VSEP_X:
                console.print(x + _dx, DIV_Y, '─', fg=color.bronze_border, bg=color.parchment_dark)

        # ── Options ───────────────────────────────────────────────────────────
        OPT_Y   = DIV_Y + 2   # blank row between divider and first option
        # Store for mouse handlers
        self._dlg_opt_y = OPT_Y
        self._dlg_box_y = y
        self._dlg_box_h = BOX_H
        options = current_menu_data["options"]
        for i, option in enumerate(options):
            option_y = OPT_Y + i
            if option_y >= y + BOX_H - 3:   # leave blank row before instructions
                break
            marker      = ">" if i == self.selected_index else " "
            option_text = f"• {option['text']}"
            if i == self.selected_index:
                line_width = min(len(marker + option_text) + 2, BOX_W - 2)
                for j in range(line_width):
                    console.print(x + 1 + j, option_y, " ", fg=color.white, bg=color.selected_bronze)
                console.print(x + 1, option_y, marker,      fg=color.white, bg=color.selected_bronze)
                console.print(x + 2, option_y, option_text, fg=color.white, bg=color.selected_bronze)
            else:
                console.print(x + 1, option_y, marker)
                console.print(x + 2, option_y, option_text, fg=color.white)

        # ── Instructions ──────────────────────────────────────────────────────
        console.print(x + 1, y + BOX_H - 2, "↑↓: Navigate  Enter: Select  Esc: Exit", fg=color.grey)

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        current_menu_data = self.menu_structure[self.current_menu]
        options = current_menu_data["options"]
        key = event.sym
        
        # Arrow key navigation (like inventory)
        if key == tcod.event.KeySym.UP:
            prev_index = self.selected_index
            self.selected_index = max(0, self.selected_index - 1)
            if self.selected_index != prev_index:
                sounds.play_ui_move_sound()
            return None
        elif key == tcod.event.KeySym.DOWN:
            prev_index = self.selected_index
            self.selected_index = min(len(options) - 1 if options else 0, self.selected_index + 1)
            if self.selected_index != prev_index:
                sounds.play_ui_move_sound()
            return None
            
        # Enter key to select option (Return, enter, space, or right key)
        elif key == tcod.event.KeySym.RETURN or key == tcod.event.KeySym.KP_ENTER or key == tcod.event.KeySym.SPACE or key == tcod.event.KeySym.RIGHT:
            if len(options) == 0:
                return None
            return self.handle_menu_selection()
            
        # Letter selection (like inventory system)
        index = key - tcod.event.KeySym.A
        if 0 <= index < len(options):
            if self.selected_index != index:
                sounds.play_ui_move_sound()
            self.selected_index = index
            return self.handle_menu_selection()
    
                
        # Escape to exits current menu, or back to main event
        elif key == tcod.event.KeySym.ESCAPE:
            return MainGameEventHandler(self.engine)
        
        return None
        
        return None

    def on_left_click(self, mx: int, my: int) -> Optional[ActionOrHandler]:
        """Handle left-clicks: hover selects, click activates the option."""
        current_menu_data = self.menu_structure[self.current_menu]
        options = current_menu_data["options"]

        OPT_Y = getattr(self, '_dlg_opt_y', None)
        y     = getattr(self, '_dlg_box_y', None)
        BOX_H = getattr(self, '_dlg_box_h', None)
        if OPT_Y is None:
            return None

        clicked_index = my - OPT_Y
        if 0 <= clicked_index < len(options):
            opt_row = OPT_Y + clicked_index
            if opt_row < y + BOX_H - 2:
                self.selected_index = clicked_index
                sounds.play_ui_move_sound()
                return self.handle_menu_selection()
        return None

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> Optional[ActionOrHandler]:
        """Hover over options to highlight them."""
        current_menu_data = self.menu_structure[self.current_menu]
        options = current_menu_data["options"]

        OPT_Y = getattr(self, '_dlg_opt_y', None)
        y     = getattr(self, '_dlg_box_y', None)
        BOX_H = getattr(self, '_dlg_box_h', None)
        if OPT_Y is None:
            return None

        _, my = int(event.tile.x), int(event.tile.y)
        hovered = my - OPT_Y
        if 0 <= hovered < len(options):
            opt_row = OPT_Y + hovered
            if opt_row < y + BOX_H - 2 and hovered != self.selected_index:
                self.selected_index = hovered
                sounds.play_ui_move_sound()
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
            if self.npc.tradable:
                from inventory_ui import TradeGridUI
                return TradeGridUI(self.engine, self.npc.inventory)
            else:
                context = ["RefuseTrade"]
                self.npc.dialogue_context = context
                self.current_dialogue = self.dialogue.generate_dialogue(
                    character=self.npc, context=context
                )
                self._dialogue_started_at = time.monotonic()
                self._last_visible_chars = 0
                
                display_name = self.npc.name if self.npc.is_known else self.npc.unknown_name
                if display_name is None:
                    display_name = "???"
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
            self._dialogue_started_at = time.monotonic()
            self._last_visible_chars = 0
            
            # Safety check
            if self.current_dialogue is None:
                self.current_dialogue = ("I have nothing to say about that.", ["Default"])
            if len(self.current_dialogue) < 2:
                self.current_dialogue = ("I have nothing to say about that.", ["Default"])
                
            display_name = self.npc.name if self.npc.is_known else self.npc.unknown_name
            if display_name is None:
                display_name = "???"
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
            if "guide_greeting" in context:
                self.talked_to_guide = True
                self.npc.is_known = True
                self.update_menu_title()
                knows_name = self.npc.name if self.npc.is_known else self.npc.unknown_name
                self.menu_structure = self._build_menu(self.npc, knows_name)
            
            return None
        
        return None





class LevelUpEventHandler(PopupEventHandler):
    TITLE = "Level Up!"

    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.engine.context_hints = [
            ("A", "Constitution"),
            ("B", "Strength"),
            ("C", "Agility"),
        ]

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)

        # Center the menu on the screen
        width = 50
        height = 12
        x = (console.width - width) // 2
        y = (console.height - height) // 2
        self._set_popup_bounds(x, y, width, height)
        
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
        # Cant click out
        return None

class ItemContextMenu(EventHandler):
    """A floating right-click context menu for an inventory item.

    Renders on top of the parent inventory handler with a small popup listing
    the actions available for the item.  Arrow keys / mouse hover navigate,
    Enter / left-click activates, Esc closes.
    """

    def __init__(
        self,
        parent_handler: "None",
        item,
        click_x: int,
        click_y: int,
    ):
        super().__init__(parent_handler.engine)
        self.parent_handler = parent_handler
        self.item = item
        self.click_x = click_x
        self.click_y = click_y
        self.selected_option = 0
        self._options: list[tuple[str, str]] = self._build_options()
        # Will be filled on first render
        self._menu_x: int = 0
        self._menu_y: int = 0
        self._option_width: int = 0

    # ------------------------------------------------------------------
    # Build the option list based on item capabilities
    # ------------------------------------------------------------------
    def _build_options(self) -> list[tuple[str, str]]:
        """Return (label, action_key) pairs for available actions."""
        item   = self.item
        player = self.engine.player
        options: list[tuple[str, str]] = []

        # Only offer use/equip/drop if the item is in the player's own inventory.
        in_player_inv = item in player.inventory.items

        if in_player_inv and getattr(item, "consumable", None) is not None:
            tags = {str(tag).lower() for tag in getattr(item, "tags", [])}
            if "potion" in tags:
                options.append(("Quaff", "quaff"))
            elif "scroll" in tags:
                options.append(("Read", "read"))
            else:
                options.append(("Use", "use"))

        if in_player_inv and identify_system.is_identifiable(item):
            if not identify_system.is_identified(player, item):
                if identify_system.get_progress(player, item):
                    options.append(("Identifying...", "noop"))
                else:
                    options.append(("Identify", "identify"))

        if in_player_inv and getattr(item, "equippable", None) is not None:
            is_equipped = player.equipment.item_is_equipped(item)
            if is_equipped:
                options.append(("Unequip", "equip"))
            else:
                options.append(("Equip", "equip"))

        # Quiver ammo selection belongs in the item's right-click context menu.
        if in_player_inv and self._is_quiver_item(item):
            for ammo_type, qty in self._get_quiver_ammo_options(item):
                marker = "*" if ammo_type == self._get_selected_quiver_ammo(item) else " "
                options.append((f"{marker} Use {ammo_type} ({qty})", f"ammo:{ammo_type}"))

        # Arrow items get a "Load into Quiver" option when a quiver is equipped.
        if in_player_inv and self._is_arrow_item(item):
            quiver = self._get_player_quiver(player)
            if quiver is not None:
                options.append(("Load into Quiver", "load_quiver"))

        if in_player_inv:
            options.append(("Throw", "throw"))
            options.append(("Drop", "drop"))
        else:
            options.append(("Take", "take"))
        return options

    @staticmethod
    def _is_arrow_item(item) -> bool:
        """Return True if item is ammo (not a quiver itself)."""
        if item is None:
            return False
        item_tags = {str(tag).strip().lower() for tag in getattr(item, "tags", []) or []}
        eq_type_name = None
        if hasattr(item, "equippable") and item.equippable:
            eq_type_name = item.equippable.equipment_type.name
        if eq_type_name == "BACKPACK" or "quiver" in item_tags:
            return False
        return (
            eq_type_name == "PROJECTILE"
            or "arrow" in item_tags
            or "ammunition" in item_tags
            or "ammo" in item_tags
        )

    @staticmethod
    def _get_player_quiver(player) -> Optional["Item"]:
        equipment = getattr(player, "equipment", None)
        if equipment and hasattr(equipment, "get_equipped_quiver"):
            return equipment.get_equipped_quiver()
        return None

    @staticmethod
    def _is_quiver_item(item) -> bool:
        if item is None:
            return False
        tags = {str(tag).strip().lower() for tag in getattr(item, "tags", []) or []}
        if "quiver" in tags:
            return True
        return int(getattr(item, "arrow_capacity", 0) or 0) > 0

    @staticmethod
    def _get_selected_quiver_ammo(quiver) -> str:
        return str(getattr(quiver, "selected_ammo_type", "") or "").strip().lower()

    @staticmethod
    def _get_quiver_ammo_options(quiver) -> list[tuple[str, int]]:
        counts = getattr(quiver, "ammo_counts", None)
        if not isinstance(counts, dict):
            legacy = int(getattr(quiver, "arrow_count", 0) or 0)
            counts = {"arrow": legacy} if legacy > 0 else {}
            quiver.ammo_counts = counts

        norm: dict[str, int] = {}
        for key, value in counts.items():
            ammo_type = str(key or "").strip().lower()
            if not ammo_type:
                continue
            qty = max(0, int(value or 0))
            if qty > 0:
                norm[ammo_type] = norm.get(ammo_type, 0) + qty

        # Keep selected ammo valid.
        selected = ItemContextMenu._get_selected_quiver_ammo(quiver)
        if selected not in norm:
            selected = next(iter(norm.keys()), "")
            if selected:
                quiver.selected_ammo_type = selected

        return sorted(norm.items(), key=lambda kv: (-kv[1], kv[0]))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def on_render(self, console: tcod.Console) -> None:
        # Draw parent inventory behind us
        self.parent_handler.on_render(console)

        if not self._options:
            return

        # Measure popup
        max_label_len = max(len(label) for label, _ in self._options)
        menu_w = max_label_len + 4   # 2 padding + 2 marker chars
        menu_h = len(self._options) + 2  # top + bottom border

        # Position: try to the right of the click, clamp to screen
        mx = self.click_x + 1
        my = self.click_y
        if mx + menu_w > console.width:
            mx = self.click_x - menu_w
        if my + menu_h > console.height:
            my = console.height - menu_h
        mx = max(0, mx)
        my = max(0, my)

        self._menu_x = mx
        self._menu_y = my
        self._option_width = menu_w

        MenuRenderer.draw_parchment_background(console, mx, my, menu_w, menu_h)
        MenuRenderer.draw_ornate_border(console, mx, my, menu_w, menu_h, "")

        for i, (label, _) in enumerate(self._options):
            is_sel = i == self.selected_option
            fg = color.gold_accent if is_sel else color.fantasy_text
            bg = (80, 60, 30) if is_sel else (45, 35, 25)
            row_y = my + 1 + i

            # Fill row background
            for dx in range(menu_w - 2):
                console.print(mx + 1 + dx, row_y, " ", bg=bg)

            marker = ">" if is_sel else " "
            console.print(mx + 1, row_y, f"{marker} {label}", fg=fg, bg=bg)

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        key = event.sym
        if key == tcod.event.K_ESCAPE:
            return self.parent_handler
        if key == tcod.event.K_UP:
            sounds.play_ui_move_sound()
            self.selected_option = (self.selected_option - 1) % len(self._options)
            return None
        if key == tcod.event.K_DOWN:
            sounds.play_ui_move_sound()
            self.selected_option = (self.selected_option + 1) % len(self._options)
            return None
        if key in CONFIRM_KEYS:
            return self._activate_selected()
        return None

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> None:
        mx, my = int(event.tile.x), int(event.tile.y)
        for i in range(len(self._options)):
            row_y = self._menu_y + 1 + i
            if (self._menu_x < mx < self._menu_x + self._option_width
                    and my == row_y):
                if self.selected_option != i:
                    sounds.play_ui_move_sound()
                self.selected_option = i
                break

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[ActionOrHandler]:
        mx, my = int(event.tile.x), int(event.tile.y)
        # Click outside the popup → close
        if not (self._menu_x <= mx < self._menu_x + self._option_width
                and self._menu_y <= my < self._menu_y + len(self._options) + 2):
            return self.parent_handler

        if event.button == tcod.event.BUTTON_LEFT:
            row_y = my - self._menu_y - 1
            if 0 <= row_y < len(self._options):
                self.selected_option = row_y
                return self._activate_selected()
        return None

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------
    def _activate_selected(self) -> Optional[ActionOrHandler]:
        if not self._options:
            return self.parent_handler
        _, action_key = self._options[self.selected_option]
        item = self.item

        if action_key == "noop":
            return self.parent_handler

        if action_key == "identify":
            try:
                self.engine.execute_action(
                    actions.IdentifyItemAction(self.engine.player, item),
                    is_player_action=True,
                )
            except exceptions.Impossible as exc:
                self.engine.message_log.add_message(exc.args[0], color.impossible)
            return self.parent_handler

        if action_key.startswith("ammo:"):
            ammo_type = action_key.split(":", 1)[1].strip().lower()
            options = dict(self._get_quiver_ammo_options(item))
            if ammo_type in options and options[ammo_type] > 0:
                item.selected_ammo_type = ammo_type
                self.engine.message_log.add_message(
                    f"Quiver set to {ammo_type} arrows.",
                    color.light_blue,
                )
            return self.parent_handler

        if action_key == "load_quiver":
            from actions import (
                _ensure_quiver_ammo_state, _get_quiver_total_count,
                _resolve_ammo_type, _ensure_quiver_ammo_templates,
            )
            import copy as _copy
            quiver = self._get_player_quiver(self.engine.player)
            if quiver is None:
                self.engine.message_log.add_message("No quiver equipped.", color.impossible)
                return self.parent_handler
            ammo_counts, _sel = _ensure_quiver_ammo_state(quiver)
            current = _get_quiver_total_count(quiver)
            capacity = int(getattr(quiver, "arrow_capacity", 0) or 0)
            if current >= capacity:
                self.engine.message_log.add_message("Your quiver is full.", color.impossible)
                return self.parent_handler
            ammo_type = _resolve_ammo_type(item)
            ammo_counts[ammo_type] = int(ammo_counts.get(ammo_type, 0) or 0) + 1
            quiver.arrow_count = current + 1
            ammo_templates = _ensure_quiver_ammo_templates(quiver)
            if ammo_type not in ammo_templates:
                try:
                    ammo_templates[ammo_type] = _copy.deepcopy(item)
                except Exception:
                    pass
            try:
                self.engine.player.inventory.items.remove(item)
                identify_system.cancel_identification_for_item(self.engine.player, item, engine=self.engine, quiet=True)
            except ValueError:
                pass
            shown_name = identify_system.get_display_name(self.engine.player, item)
            self.engine.message_log.add_message(
                f"You load {shown_name} into your quiver ({current + 1}/{capacity}).",
                color.light_blue,
            )
            return self.parent_handler

        if action_key in ("quaff", "read", "use"):
            if item.consumable:
                if action_key == "quaff":
                    sounds.play_quaff_sound()
                action_or_handler = item.consumable.get_action(self.engine.player)
                if action_or_handler:
                    if hasattr(action_or_handler, "perform"):
                        try:
                            self.engine.execute_action(action_or_handler, is_player_action=False)
                        except exceptions.Impossible as exc:
                            self.engine.message_log.add_message(exc.args[0], color.impossible)
                        return self.parent_handler
                    else:
                        return action_or_handler
            return self.parent_handler

        elif action_key == "equip":
            try:
                self.engine.execute_action(actions.EquipAction(self.engine.player, item), is_player_action=False)
            except exceptions.Impossible as exc:
                self.engine.message_log.add_message(exc.args[0], color.impossible)
            # Move item to first free slot so unequip/equip doesn't snap back to origin
            if hasattr(self.parent_handler, '_clear_from_item_slots'):
                self.parent_handler._clear_from_item_slots(item)
            return self.parent_handler

        elif action_key == "throw":
            return ThrowTargetHandler(self.engine, item)

        elif action_key == "drop":
            try:
                self.engine.execute_action(actions.DropItem(self.engine.player, item), is_player_action=False)
                if hasattr(self.parent_handler, 'refresh_item_groups'):
                    self.parent_handler.refresh_item_groups()
            except exceptions.Impossible as exc:
                self.engine.message_log.add_message(exc.args[0], color.impossible)
            return self.parent_handler

        elif action_key == "take":
            # Item is in a container; transfer it to the player.
            if hasattr(self.parent_handler, '_transfer_to_player'):
                self.parent_handler._transfer_to_player(item)
            return self.parent_handler

        return self.parent_handler


class SelectIndexHandler(AskUserEventHandler):
    # Handles asking the user for a location on the map

    def __init__(self, engine: Engine):
        #sets cursor to player when handler is made
        super().__init__(engine)
        self.engine.context_hints = [
            ("Mouse/WASD", "Aim"),
            ("Enter", "Confirm"),
            ("Esc", "Cancel"),
        ]
        player = self.engine.player
        engine.mouse_location = player.x, player.y

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> None:
        AskUserEventHandler.ev_mousemotion(self, event)
        self.engine.mouse_location = int(self.engine.mouse_x), int(self.engine.mouse_y)

    # Cursor overlay state — read by main.py to draw the sprite as a BLEND SDL texture
    # after the game console + lightmap have been composited to the screen.
    _cursor_screen_pos: tuple = None  # (screen_x, screen_y) in game-console space
    _cursor_cp: int = 0xE0F6          # active cursor codepoint (alternates each frame)

    def render_game_overlay(self, console: tcod.Console) -> None:
        """Store cursor position/frame for main.py's GPU BLEND overlay pass."""
        import time
        x, y = self.engine.mouse_location
        x, y = int(x), int(y)
        screen_position = self.engine.world_to_screen(x, y, console.width, console.height)
        self._cursor_screen_pos = screen_position
        self._cursor_cp = 0xE0F6 if int(time.time() * 4) % 2 == 0 else 0xE0F7

    def render_ui_overlay(self, console: tcod.Console) -> None:
        return None

    def on_render(self, console: tcod.Console) -> None:
        # In hybrid rendering this handler is drawn on the game console.
        # Render the game layer explicitly, then draw targeting overlays.
        self.engine.render_game(console)

        self.render_game_overlay(console)
        self.render_ui_overlay(console)
    
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
        # Left click confirms selection. Accept tuple or object tile formats.
        def _as_tile(position):
            if position is None:
                return None
            if hasattr(position, "x") and hasattr(position, "y"):
                return int(position.x), int(position.y)
            return int(position[0]), int(position[1])

        if event.button == 1:
            tile = _as_tile(getattr(event, "world_tile", None))
            if tile is None:
                tile = _as_tile(getattr(event, "tile", None))
            if tile is None:
                tile = (int(self.engine.mouse_x), int(self.engine.mouse_y))

            tile_x, tile_y = tile
            if self.engine.game_map.in_bounds(tile_x, tile_y):
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
        screen_position = self.engine.world_to_screen(
            self.engine.player.x, self.engine.player.y, console.width, console.height
        )
        if screen_position is None:
            return
        x, y = screen_position
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
        self.engine.context_hints = [
            ("\u2191\u2193", "Select Mode"),
            ("Enter", "Confirm"),
            ("Esc", "Cancel"),
        ]
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
            #"[↑↓] Navigate  [0-6] Quick Select  [Enter] Set Mode  [Esc] Cancel",
            #"This affects all future attacks until changed."
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
        #self.engine.message_log.add_message(message, color.green)
        
        return MainGameEventHandler(self.engine)


class LimbTargetingHandler(AskUserEventHandler):
    """Handler for selecting which body part to target in combat."""
    
    def __init__(self, engine: Engine, attacker: Actor, target: Actor):
        super().__init__(engine)
        self.engine.context_hints = [
            ("\u2191\u2193", "Navigate"),
            ("Enter/Click", "Target"),
            ("1-6", "Quick Select"),
            ("Esc", "Cancel"),
        ]
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
            self.engine.execute_action(action, is_player_action=False)
        except Exception as e:
            self.engine.message_log.add_message(str(e), color.impossible)
        
        return MainGameEventHandler(self.engine)



class SpellCastingHandler(PopupEventHandler):
    """Handle spell selection and casting with hotkey support."""
    
    TITLE = "Cast Spell"
    
    # Spell registry for easy spell management
    SPELL_REGISTRY = {}
    
    @classmethod
    def _initialize_spell_registry(cls):
        """Initialize the spell registry with available spells."""
        if not cls.SPELL_REGISTRY:  # Only initialize once
            from components.spells import DarkvisionSpell, TeleportSpell, PoisonSpraySpell, InvisibilitySpell, MirrorImageSpell, MageArmorSpell
            # Spell registry
            cls.SPELL_REGISTRY = {
                "Darkvision": DarkvisionSpell,
                "Teleport": TeleportSpell,
                "Poison Spray": PoisonSpraySpell,
                "Invisibility": InvisibilitySpell,
                "Mirror Image": MirrorImageSpell,
                "Mage Armor": MageArmorSpell,

                # Add new spells here: "SpellName": SpellClass,
            }
    
    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.selected_index = 0
        self.scroll_offset = 0
        self.engine.context_hints = [
            ("1-9", "Quick Cast Bind"),
            ("Esc", "Close"),
        ]
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
        scale = self.get_popup_scale()
        if not self.available_spells:
            # Show "no spells known" message
            total_width = 40
            total_height = 8
            x = (console.width - total_width) // 2
            y = (console.height - total_height) // 2

            


            x = (console.width - 40) // 2
            y = (console.height - 8) // 2
            draw_w = max(4, int(total_width * scale))
            draw_h = max(4, int(total_height * scale))
            draw_x = x + (total_width - draw_w) // 2
            draw_y = y + (total_height - draw_h) // 2
            
            self._set_popup_bounds(draw_x, draw_y, draw_w, draw_h)
            MenuRenderer.draw_parchment_background(console, draw_x, draw_y, draw_w, draw_h)
            MenuRenderer.draw_ornate_border(console, draw_x, draw_y, draw_w, draw_h, "Spellcasting")

            if scale < 1.0:
                return
            
            console.print(x + 2, y + 3, "You know no spells.", fg=color.impossible)
            console.print(x + 2, y + 6, "[Esc] Cancel", fg=color.grey)
            return
        
        # Calculate window dimensions
        total_width = 70  # Wider for quick cast display
        spell_list_height = len(self.available_spells)
        total_height = min(40, max(20, spell_list_height + 15))  # Taller menu
        
        x = (console.width - total_width) // 2
        y = (console.height - total_height) // 2
        
        draw_w = max(4, int(total_width * scale))
        draw_h = max(4, int(total_height * scale))
        draw_x = x + (total_width - draw_w) // 2
        draw_y = y + (total_height - draw_h) // 2

        self._set_popup_bounds(draw_x, draw_y, draw_w, draw_h)
        super().render_faded(console, draw_x, draw_y, draw_w, draw_h)
        MenuRenderer.draw_parchment_background(console, draw_x, draw_y, draw_w, draw_h)
        MenuRenderer.draw_ornate_border(console, draw_x, draw_y, draw_w, draw_h, "Spellcasting")

        if scale < 1.0:
            return
        
        # Show player's current mana
        mana_text = f"Mana: {self.engine.player.mana}/{self.engine.player.mana_max}"
        console.print(x + 2, y + 1, mana_text, fg=(100, 149, 237))  # Cornflower blue

        
        # Calculate visible spell range for scrolling
        visible_height = total_height - 12  # More space for headers and footers
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
                for highlight_x in range(x + 1, x + total_width - 1):
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
            mana_x = x + total_width - len(mana_text) - 2
            console.print(mana_x, render_y, mana_text, fg=(100, 149, 237) if can_cast else (128, 128, 128), 
                         bg=(80, 60, 40) if is_selected else None)
            

        
        # Show selected spell description if available
        if self.available_spells:
            selected_spell = self.available_spells[self.selected_index]
            desc_start_y = y + total_height - 4
            
            if selected_spell.arcana_level > self.engine.player.level.traits['arcana']['level']:
                description = "???"
            else:
            
                description = selected_spell.get_description(self.engine.player)
            # Word wrap the description
            
            desc_width = total_width - 4
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

        # Show associated school
        console.print(x + 2, desc_start_y + 2, selected_spell.school.title(), fg=self._get_spell_school_color(selected_spell.school))
        
        # Show scroll indicators
        if start_index > 0:
            console.print(x + total_width - 2, list_start_y, "↑", fg=color.yellow)
        if end_index < len(self.available_spells):
            console.print(x + total_width - 2, y + total_height - 5, "↓", fg=color.yellow)
        
        
        # Cache render coords for mouse interaction
        self._spell_render_x = x
        self._spell_render_y = y
        self._spell_window_width = total_width
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

    def on_left_click(self, mx: int, my: int) -> Optional[ActionOrHandler]:
        """Left-click inside the spell menu — select and cast the clicked spell."""
        if not hasattr(self, '_spell_list_start_y') or not self.available_spells:
            return None
        list_y = self._spell_list_start_y
        visible = self._spell_visible_height
        if self._spell_render_x + 1 <= mx < self._spell_render_x + self._spell_window_width - 1 and list_y <= my < list_y + visible:
            spell_index = (my - list_y) + self._spell_scroll_offset
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

                # If same spell is already in this slot, unbind it (toggle off)
                if current_slot_spell == selected_spell.name:
                    self.engine.player.quickcast_slots[slot_index] = None
                    self.engine.message_log.add_message(
                        f"Unbound {selected_spell.name} from quick cast slot {slot_index + 1}",
                        (255, 165, 0)
                    )
                else:
                    # Clear this spell from any other slot it currently occupies
                    for i, s in enumerate(self.engine.player.quickcast_slots):
                        if s == selected_spell.name:
                            self.engine.player.quickcast_slots[i] = None
                            break
                    # Assign spell to the new slot
                    self.engine.player.quickcast_slots[slot_index] = selected_spell.name
                    self.engine.message_log.add_message(
                        f"Assigned {selected_spell.name} to quick cast slot {slot_index + 1}",
                        (255, 215, 0)
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
                # Restore minimap before entering targeting mode (SpellCastingHandler minimized it)
                if hasattr(self.engine, '_pre_menu_minimap'):
                    self.engine.show_minimap = self.engine._pre_menu_minimap
                    del self.engine._pre_menu_minimap
                # Pre-seed cursor to current physical mouse position
                self.engine.mouse_location = self.engine.mouse_x, self.engine.mouse_y
                return targeting_handler
        
        # Cast spells that don't require targeting directly on the player
        try:
            from actions import SpellAction
            spell_action = SpellAction(player, spell, (player.x, player.y))
            self.engine.execute_action(spell_action, is_player_action=False)
            
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
        self.engine.context_hints = [
            ("Mouse/Arrows", "Look"),
            ("Tab", "Switch Tabs"),
            ("Scroll", "Switch Items"),
            ("Shift+Scroll", "Scroll Text"),
            ("Esc", "Exit"),
        ]
        self.alt_held = False
        self._shift_held = False
        self.detail_index = 0  # Index for cycling through items at location
        self.scroll_offset = 0  # For scrolling through text
        self.current_tab = LookHandler.last_selected_tab  # Start with remembered tab
        self.tab_names = ["Glance", "Damages", "Coatings","Inspect"]
        # Render caches — avoid expensive recomputation every frame
        self._cache_location: tuple = (-1, -1)
        self._cache_items_entities: list = []
        self._cache_tab: int = -1
        self._cache_detail_index: int = -1
        self._cache_tab_content: list = []
        # Entity pos map built once on first render; entities don't change in look mode.
        self._entity_pos_map: dict = {}
        # 7×7 sub-console for the minimap preview — only redrawn when cursor tile changes.
        self._preview_console: tcod.Console = tcod.Console(7, 7, order="F")
        self._preview_dirty: bool = True
        # Sidebar screen position — set each render so main.py can extract a sub-console.
        self._sidebar_x: int = 0
        self._sidebar_y: int = 0
        self._sidebar_w: int = 35
        self._sidebar_h: int = 30

    def on_index_selected(self, x: int, y: int) -> Optional[ActionOrHandler]:
        """Return to main handler when location is selected."""
        return MainGameEventHandler(self.engine)

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> Optional[ActionOrHandler]:
        """Sync mouse_location with physical mouse so the cursor follows both mouse and keyboard."""
        result = super().ev_mousemotion(event)
        self.engine.mouse_location = self.engine.mouse_x, self.engine.mouse_y
        return result

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)

    def render_game_overlay(self, console: tcod.Console) -> None:
        super().render_game_overlay(console)

    def render_ui_overlay(self, console: tcod.Console) -> None:
        self.render_detailed_sidebar(console)

    def get_displayed_cursor_position(self, console: tcod.Console) -> tuple[int, int]:
        """Return the cursor position in UI-layer tile space for the zoomed game view."""
        cursor_x, cursor_y = self.engine.mouse_location
        screen_position = self.engine.world_to_screen(cursor_x, cursor_y, 40, 20)
        if screen_position is None:
            return 0, 0
        screen_x, screen_y = screen_position
        display_x = min(console.width - 1, max(0, screen_x * 2))
        display_y = min(console.height - 1, max(0, screen_y * 2))
        return display_x, display_y

    def render_detailed_sidebar(self, console: tcod.Console) -> None:
        """Render detailed information sidebar."""
        _BG         = color.parchment_bg
        _BORDER_FG  = color.bronze_border
        _TAB_ACT_BG = color.selected_bronze
        _TAB_IN_BG  = color.parchment_very_dark

        x, y = self.engine.mouse_location
        x, y = int(x), int(y)

        # Re-query items/entities only when the cursor has actually moved
        if (x, y) != self._cache_location:
            self._cache_location = (x, y)
            self._cache_items_entities = self.get_items_and_entities_at(x, y)
            # Build entity pos map once — entities don't change during look mode.
            if not self._entity_pos_map:
                pos_map: dict = {}
                for entity in self.engine.game_map.entities:
                    key = (entity.x, entity.y)
                    if key not in pos_map:
                        pos_map[key] = []
                    pos_map[key].append(entity)
                self._entity_pos_map = pos_map
            # Invalidate preview and tab content caches.
            self._preview_dirty = True
            self._cache_tab = -1

        items_and_entities = self._cache_items_entities
        if not items_and_entities:
            return

        # Clamp detail_index to valid range
        self.detail_index = max(0, min(self.detail_index, len(items_and_entities) - 1))
        current_item = items_and_entities[self.detail_index]

        # Cursor position in UI-layer tile space
        cursor_x, cursor_y = self.get_displayed_cursor_position(console)
        sidebar_width  = 35
        sidebar_height = 30
        self._sidebar_w = sidebar_width
        self._sidebar_h = sidebar_height

        # Place on the opposite horizontal half from the cursor (no external overflow)
        if cursor_x < console.width // 2:
            sidebar_x = console.width - sidebar_width   # right side
        else:
            sidebar_x = 0                               # left side

        # Vertical: prefer below cursor, then above, then clamp
        below_cursor_y = cursor_y + 2
        above_cursor_y = cursor_y - sidebar_height - 2
        max_sidebar_y  = max(1, console.height - sidebar_height - 1)
        if below_cursor_y <= max_sidebar_y:
            sidebar_y = below_cursor_y
        elif above_cursor_y >= 1:
            sidebar_y = above_cursor_y
        else:
            sidebar_y = max(1, min(max_sidebar_y, cursor_y - sidebar_height // 2))

        # ── Parchment background + ornate border (matches other menus) ────────
        self._sidebar_x = sidebar_x
        self._sidebar_y = sidebar_y
        MenuRenderer.draw_parchment_background(console, sidebar_x, sidebar_y, sidebar_width, sidebar_height)
        item_name = current_item['name'][:sidebar_width - 6]
        MenuRenderer.draw_ornate_border(console, sidebar_x, sidebar_y, sidebar_width, sidebar_height, item_name)

        # ── Inline tab row (row +2, below the ornate title row) ──────────────
        tab_display = ["Glance", "Damage", "Coating", "Inspect"]
        tab_row_y = sidebar_y + 2
        tx = sidebar_x + 1
        for i, dname in enumerate(tab_display):
            if i > 0:
                console.print(tx, tab_row_y, "|", fg=_BORDER_FG, bg=_BG)
                tx += 1
            if i == self.current_tab:
                console.print(tx, tab_row_y, dname, fg=color.gold_accent, bg=_TAB_ACT_BG)
            else:
                console.print(tx, tab_row_y, dname, fg=color.fantasy_text, bg=_TAB_IN_BG)
            tx += len(dname)
        # Item counter at far right of tab row
        if len(items_and_entities) > 1:
            counter = f"{self.detail_index + 1}/{len(items_and_entities)}"
            console.print(
                sidebar_x + sidebar_width - len(counter) - 2,
                tab_row_y, counter, fg=color.grey, bg=_BG,
            )

        # ── Separator (row +3) ────────────────────────────────────────────────
        sep_y = sidebar_y + 3
        console.ch[sidebar_x + 1 : sidebar_x + sidebar_width - 1, sep_y] = ord('─')
        console.fg[sidebar_x + 1 : sidebar_x + sidebar_width - 1, sep_y] = _BORDER_FG
        console.bg[sidebar_x + 1 : sidebar_x + sidebar_width - 1, sep_y] = _BG

        # ── Minimap preview (7×7) ──────────────────────────────────────────
        preview_size = self._preview_console.width
        preview_x = sidebar_x + (sidebar_width - preview_size) // 2
        preview_y = sidebar_y + 4
        if self._preview_dirty:
            self._preview_console.clear()
            self.render_visual_preview(self._preview_console, current_item, x, y, 0, 0)
            self._preview_dirty = False
        self._preview_console.blit(console, dest_x=preview_x, dest_y=preview_y)

        # ── Scrollable text content ───────────────────────────────────────────
        text_details_y  = preview_y + preview_size + 1
        text_area_width = sidebar_width - 2
        controls_height = 2
        text_area_height = sidebar_height - (text_details_y - sidebar_y) - controls_height - 1

        if (self._cache_tab != self.current_tab or
                self._cache_detail_index != self.detail_index):
            self._cache_tab          = self.current_tab
            self._cache_detail_index = self.detail_index
            self._cache_tab_content  = self.build_tabbed_content(current_item, text_area_width, x, y)

        self.render_scrollable_text(
            console, self._cache_tab_content,
            sidebar_x, text_details_y, text_area_width, text_area_height,
        )

        # ── Instructions (bottom) ─────────────────────────────────────────────
        instructions_y = sidebar_y + sidebar_height - controls_height - 1
        console.print(sidebar_x + 2, instructions_y,     "Tab:next tab  Shift+A/D:item",      fg=color.fantasy_text, bg=_BG)
        console.print(sidebar_x + 2, instructions_y + 1, "Shift+↑↓:scroll    Esc:exit",          fg=color.fantasy_text, bg=_BG)

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
            fg=(139, 105, 60), bg=(30, 22, 14),
        )
        
        # Center position in the preview frame (inside the frame borders)
        center_x = frame_x + 1 + preview_size // 2
        center_y = frame_y + 1 + preview_size // 2

        gm = self.engine.game_map
        # Use the pre-built position map (avoids O(n) scan per minimap cell)
        pos_map = self._entity_pos_map
        
        # Draw the surrounding area first (for context)
        for dy in range(-preview_size//2, preview_size//2 + 1):
            for dx in range(-preview_size//2, preview_size//2 + 1):
                world_x = look_x + dx
                world_y = look_y + dy
                px = center_x + dx
                py = center_y + dy
                
                # Only draw within the frame boundaries
                if (px > frame_x and px < frame_x + preview_size + 1 and
                    py > frame_y and py < frame_y + preview_size + 1):
                    
                    # Draw tile background
                    if gm.in_bounds(world_x, world_y):
                        tile = gm.tiles[world_x, world_y]
                        
                        # Get tile character and color
                        if gm.visible[world_x, world_y]:
                            char = int(tile['light'][0]) if 'light' in tile.dtype.names else ord('.')
                            fg = tuple(tile['light'][1]) if 'light' in tile.dtype.names else (255, 255, 255)
                            bg = tuple(tile['light'][2]) if 'light' in tile.dtype.names else (0, 0, 0)
                        else:
                            char = int(tile['dark'][0]) if 'dark' in tile.dtype.names else ord('.')
                            fg = tuple(tile['dark'][1]) if 'dark' in tile.dtype.names else (128, 128, 128)
                            bg = tuple(tile['dark'][2]) if 'dark' in tile.dtype.names else (0, 0, 0)
                        
                        # Highlight center tile when inspecting a tile type
                        if px == center_x and py == center_y and current_item['type'] == 'tile':
                            if char == ord(' ') or char == ord('.') or char == ord('+') or char == ord('/'):
                                bg = color.white
                            else:
                                fg = color.white
                        
                        console.print(px, py, chr(char), fg=fg, bg=bg)
        
        # Draw entities at their positions using pre-built position map
        for dy in range(-preview_size//2, preview_size//2 + 1):
            for dx in range(-preview_size//2, preview_size//2 + 1):
                world_x = look_x + dx
                world_y = look_y + dy
                px = center_x + dx
                py = center_y + dy
                
                if (px > frame_x and px < frame_x + preview_size + 1 and
                    py > frame_y and py < frame_y + preview_size + 1):
                    
                    for entity in pos_map.get((world_x, world_y), ()):
                        if hasattr(entity, 'char') and hasattr(entity, 'color'):
                            console.print(px, py, entity.char, fg=entity.color)
        
        # Highlight the current object with the same sprite-based target effect used in map targeting.
        # This composites the animated blue-corner overlay directly into the preview tile.
        try:
            import time
            import sprite_manager

            target_cp = 0xE0F6 if int(time.time() * 4) % 2 == 0 else 0xE0F7
            base_cp = int(console.ch[center_x, center_y])
            base_fg = tuple(int(v) for v in console.rgb["fg"][center_x, center_y])
            composed = sprite_manager.compose_sprite([base_cp, target_cp], layer_tints=[base_fg, None])
            console.ch[center_x, center_y] = ord(composed)
            console.rgb["fg"][center_x, center_y] = color.white
        except Exception:
            # Fallback: if sprite composition fails, keep a visible center highlight.
            console.rgb["fg"][center_x, center_y] = color.white

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

        description_text = ""
        if hasattr(entity, 'consumable') and hasattr(entity, 'equippable'):
            description_text = identify_system.get_display_description(self.engine.player, entity)
        elif hasattr(entity, 'description'):
            description_text = str(entity.description or "")

        if description_text:
            # Wrap long descriptions to multiple lines
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
                            name_text = "You don't know what this is."
                        lines.append([(name_text, color.white)])
                    else:
                        lines.append([(entity.name, entity_name_color)])
            else:
                if hasattr(entity, 'consumable') and hasattr(entity, 'equippable'):
                    shown_name = identify_system.get_display_name(self.engine.player, entity)
                    lines.append([(shown_name, entity_name_color)])
                elif hasattr(entity, 'name'):
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
                                (identify_system.get_display_name(self.engine.player, item), item.rarity_color),
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
                                (identify_system.get_display_name(self.engine.player, item), item.rarity_color),
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
                        container_parts.append((identify_system.get_display_name(self.engine.player, item), item.rarity_color))
                    
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
            
            # Add damage resistances if applicable
            if hasattr(entity, 'damage_resistances') and entity.damage_resistances:
                lines.append([("", color.white)])  # Empty line for spacing
                lines.append([("Resistances:", color.cyan)])
                for res_type, res_value in entity.damage_resistances:
                    # Format resistance based on value
                    if res_value == 0.0:
                        status_text = "Immune"
                        status_color = color.green
                    elif res_value < 1.0:
                        percent = int((1.0 - res_value) * 100)
                        status_text = f"{percent}% Resistant"
                        status_color = color.light_blue
                    elif res_value > 1.0:
                        percent = int((res_value - 1.0) * 100)
                        status_text = f"{percent}% Vulnerable"
                        status_color = color.red
                    else:
                        continue  # Skip normal (1.0) resistances
                    
                    # Display damage type and status
                    damage_type_name = res_type.value.replace('_', ' ').title()
                    lines.append([(f"  {damage_type_name}: ", color.white), (status_text, status_color)])
                    
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
                elif hasattr(entity, 'consumable') and hasattr(entity, 'equippable'):
                    display_name = identify_system.get_display_name(self.engine.player, entity)

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
        if self._shift_held:
            # Shift+scroll: scroll the text content
            if event.y > 0:
                self.scroll_offset = max(0, self.scroll_offset - 1)
            elif event.y < 0:
                self.scroll_offset += 1
        else:
            # Plain scroll: cycle through items at the current tile
            items = self._cache_items_entities
            if items:
                if event.y > 0:
                    self.detail_index = (self.detail_index - 1) % len(items)
                else:
                    self.detail_index = (self.detail_index + 1) % len(items)
                self.scroll_offset = 0
                sounds.play_ui_move_sound()
        return None

    def ev_keyup(self, event: tcod.event.KeyUp) -> Optional[ActionOrHandler]:
        if event.sym in (tcod.event.KeySym.LSHIFT, tcod.event.KeySym.RSHIFT):
            self._shift_held = False
        return None

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        """Handle keyboard input for inspection interface."""
        key = event.sym
        modifier = event.mod

        if key in (tcod.event.KeySym.LSHIFT, tcod.event.KeySym.RSHIFT):
            self._shift_held = True

        # Shift+A / Shift+D: cycle through items at the current tile
        if (
            modifier & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT)
            and key in (tcod.event.KeySym.A, tcod.event.KeySym.D)
        ):
            items = self._cache_items_entities
            if items:
                if key == tcod.event.KeySym.A:
                    self.detail_index = (self.detail_index - 1) % len(items)
                else:
                    self.detail_index = (self.detail_index + 1) % len(items)
                self.scroll_offset = 0
                sounds.play_ui_move_sound()
            return None

        # Tab: cycle through info tabs
        elif key == tcod.event.KeySym.TAB:
            self.current_tab = (self.current_tab + 1) % len(self.tab_names)
            LookHandler.last_selected_tab = self.current_tab
            self.scroll_offset = 0
            sounds.play_ui_move_sound()
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
        screen_position = self.engine.world_to_screen(x, y, console.width, console.height)
        if screen_position is None:
            return
        x, y = screen_position

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

    _RESET_HOLD_DURATION = 1.5  # seconds R must be held to trigger reset

    def __init__(self, engine: Engine):
        super().__init__(engine)
        # Restore minimap mode saved before any popup menu was opened
        if hasattr(engine, '_pre_menu_minimap'):
            engine.show_minimap = engine._pre_menu_minimap
            del engine._pre_menu_minimap
        self._r_press_time: Optional[float] = None  # time.monotonic() when R was first pressed
        self.engine.context_hints = [
            ("G", "Get"),
            ("RClick", "Interact"),
            ("RClick", "Path"),
            ("TAB", "Inventory"),
            ("E", "Equipment"),
            ("F", "Character Sheet"),
            ("C", "Spells"),
            (">", "Take Stairs"),
            ("Alt", "Look"),
            ("M", "Map/Keys"),
            ("V", "History"),
            ("LClick", "Attack"),
            ("SHIFT+WASD", "Dodge")
        ]   

    def handle_events(self, event: tcod.event.Event) -> BaseEventHandler:
        # Return any handler change that was queued by auto-move in engine.tick(),
        # but only once we've shown one final pre-transition frame.
        pending = getattr(self.engine, '_pending_handler', None)
        pending_ready = getattr(self.engine, '_pending_handler_ready', False)
        if pending is not None:
            if pending_ready:
                self.engine._pending_handler = None
                self.engine._pending_handler_ready = False
                return pending
            # During the deferred frame, ignore extra input and keep this handler active.
            return self

        # Cancel auto-move on any deliberate keyboard or mouse input
        if isinstance(event, (tcod.event.KeyDown, tcod.event.MouseButtonDown)):
            if getattr(self.engine, 'auto_move_path', None):
                self.engine.auto_move_path = []
                self.engine.cursor_hint = None

        return super().handle_events(event)

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[ActionOrHandler]:
        if event.button == tcod.event.MouseButton.LEFT:

            if self.engine.mouse_ui_y == 40 and 36 <= self.engine.mouse_ui_x <= 50:
                from inventory_ui import InventoryGridUI
                return InventoryGridUI(self.engine)
            elif self.engine.mouse_ui_y == 40 and 52 <= self.engine.mouse_ui_x <= 64:
                from inventory_ui import InventoryGridUI
                return InventoryGridUI(self.engine)

            preferred_target = getattr(self.engine.player, 'current_attack_type', None)
            dx = max(-1, min(1, self.engine.mouse_x - self.engine.player.x))
            dy = max(-1, min(1, self.engine.mouse_y - self.engine.player.y))

            if self.engine.mouse_ui_y > 38:
                return None

            # Compute sub-tile cursor position (0.0–1.0 within the clicked tile).
            # The game viewport is rendered at 2× zoom, so each tile = base_tile * 2 px.
            _btw = getattr(self.engine, 'base_tile_w', 0)
            _bth = getattr(self.engine, 'base_tile_h', 0)
            tile_rel_pos = None
            if _btw and _bth:
                _gtw = _btw * 2.0
                _gth = _bth * 2.0
                _px, _py = float(event.position[0]), float(event.position[1])
                tile_rel_pos = (
                    (_px % _gtw) / _gtw,
                    (_py % _gth) / _gth,
                )

            # Get the target actor at the attack location
            target_x = self.engine.player.x + dx
            target_y = self.engine.player.y + dy

            target_actor = self.engine.game_map.get_actor_at_location(target_x, target_y)

            # When a preferred attack type is set (keyboard targeting mode), honour it.
            # Otherwise tile_rel_pos inside the action will pick the part.
            if preferred_target and target_actor:
                import random
                matching_parts = []
                if hasattr(target_actor, 'body_parts') and target_actor.body_parts:
                    for part_type, body_part in target_actor.body_parts.body_parts.items():
                        if preferred_target in body_part.tags:
                            matching_parts.append(part_type)
                target_part = random.choice(matching_parts) if matching_parts else None
            else:
                # Let tile_rel_pos inside the action determine the targeted part
                target_part = None

            equipment = getattr(self.engine.player, 'equipment', None)
            held_items = []
            if equipment:
                held_items = list(equipment.grasped_items.values()) + list(equipment.equipped_items.values())

            has_bow = False
            has_arrow = False

            for item in held_items:
                if not item or not hasattr(item, 'equippable') or not item.equippable:
                    continue

                eq_type_name = item.equippable.equipment_type.name
                item_tags = {tag.lower() for tag in getattr(item, 'tags', [])}

                if eq_type_name == 'RANGED' or 'bow' in item_tags:
                    has_bow = True
                if eq_type_name == 'PROJECTILE' or 'arrow' in item_tags or 'ammunition' in item_tags:
                    has_arrow = True

            # Allow ranged attacks with arrows in inventory even if none is explicitly readied.
            if not has_arrow:
                inventory = getattr(self.engine.player, 'inventory', None)
                if inventory:
                    for item in inventory.items:
                        if not item or not hasattr(item, 'equippable') or not item.equippable:
                            continue
                        eq_type_name = item.equippable.equipment_type.name
                        item_tags = {tag.lower() for tag in getattr(item, 'tags', [])}
                        if eq_type_name == 'PROJECTILE' or 'arrow' in item_tags or 'ammunition' in item_tags:
                            has_arrow = True
                            break

            if has_bow and has_arrow:
                return actions.RangedAction(
                    self.engine.player,
                    dx,
                    dy,
                    target_part,
                    tile_rel_pos=tile_rel_pos,
                    target_xy=(self.engine.mouse_x, self.engine.mouse_y),
                )
            else:
                return actions.MeleeAction(self.engine.player, dx, dy, target_part, tile_rel_pos=tile_rel_pos)
        if event.button == tcod.event.MouseButton.RIGHT:
            _ks = tcod.event.get_keyboard_state()
            _shift_held = bool(_ks[225] or _ks[229])  # SDL_SCANCODE_LSHIFT/RSHIFT

            if _shift_held and self.engine.mouse_ui_y <= 38:
                mouse_x, mouse_y = self.engine.mouse_x, self.engine.mouse_y
                target_actor = self.engine.game_map.get_actor_at_location(mouse_x, mouse_y)
                if (
                    target_actor is not None
                    and target_actor is not self.engine.player
                    and hasattr(target_actor, "ai")
                    and target_actor.can_speak
                ):
                    reach = max(abs(mouse_x - self.engine.player.x), abs(mouse_y - self.engine.player.y))
                    if reach <= 3:
                        return DialogueEventHandler(self.engine, target_actor)
                    self.engine.message_log.add_message("Too far away to talk!", color.impossible)
                    return None

            # --- Minimap right-click: navigate to clicked map location ---
            import render_functions as _rf
            _mm_ox = _rf.get_minimap_origin_x(self.engine)
            _btw = getattr(self.engine, 'base_tile_w', None)
            _bth = getattr(self.engine, 'base_tile_h', None)
            if (_btw and _bth
                    and getattr(self.engine, 'show_minimap', 0) == 0
                    and self.engine.game_map is not None):
                # Interior pixel bounds on screen
                _ix0 = (_mm_ox + 1) * _btw
                _iy0 = (_rf._MM_Y + 1) * _bth
                _ipw = (_rf._MM_W - 2) * _btw
                _iph = (_rf._MM_H - 2) * _bth
                # Raw pixel coords of the click
                _cpx, _cpy = float(event.position[0]), float(event.position[1])
                if _ix0 <= _cpx < _ix0 + _ipw and _iy0 <= _cpy < _iy0 + _iph:
                    gm = self.engine.game_map
                    dest_x = int((_cpx - _ix0) / _ipw * gm.width)
                    dest_y = int((_cpy - _iy0) / _iph * gm.height)
                    dest_x = max(0, min(gm.width  - 1, dest_x))
                    dest_y = max(0, min(gm.height - 1, dest_y))
                    if gm.explored[dest_x, dest_y]:
                        return actions.MoveToAction(self.engine.player, dest_x, dest_y)
                    else:
                        self.engine.message_log.add_message("That area is unexplored.", color.impossible)
                        return None

            # First check if interactable under mouse
            if self.engine.cursor_hint == "interact":
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
            # If no interact, walk to tile clicked
            else:
                return actions.MoveToAction(self.engine.player, self.engine.mouse_x, self.engine.mouse_y)
    
    def ev_keyup(self, event: tcod.event.KeyUp) -> Optional[ActionOrHandler]:
        if event.sym in (tcod.event.KeySym.LALT, tcod.event.KeySym.RALT):
            self.alt_held = False
            print(self.alt_held)
        if event.sym == tcod.event.KeySym.R:
            self._r_press_time = None

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
            return None #HelpMenuHandler(parent_handler=self)
        elif key == tcod.event.KeySym.T:
            active_ability = getattr(player, "active_ability", None)
            if active_ability is None:
                self.engine.message_log.add_message("You have no active ability.", color.invalid)
                return None

            if getattr(active_ability, "requires_target", False):
                def _ability_target_callback(target_xy: Tuple[int, int]) -> Optional[ActionOrHandler]:
                    tx, ty = target_xy
                    if not self.engine.game_map.in_bounds(tx, ty):
                        self.engine.message_log.add_message("That target is out of bounds.", color.invalid)
                        return None
                    if not self.engine.game_map.visible[tx, ty]:
                        self.engine.message_log.add_message("You cannot see that target.", color.invalid)
                        return None

                    target = self.engine.game_map.get_actor_at_location(tx, ty)
                    if target is None or target is player:
                        self.engine.message_log.add_message("Select an enemy target.", color.invalid)
                        return None
                    if getattr(getattr(target, "ai", None), "type", None) == "Friendly":
                        self.engine.message_log.add_message("That target is not hostile.", color.invalid)
                        return None

                    # Triggered ability: execute immediately without consuming a turn.
                    actions.AbilityAction(player, target_xy=(tx, ty)).perform()
                    return MainGameEventHandler(self.engine)

                return SingleRangedAttackHandler(self.engine, _ability_target_callback)

            # Triggered ability: execute immediately without consuming a turn.
            actions.AbilityAction(player).perform()
            return None
        elif key == tcod.event.K_F4:
            self.engine.player.fighter.hp = 99999999999
            self.engine.player.fighter.power = 99999999999
            self.engine.player.fighter.defense = 99999999999

            for entity in list(self.engine.game_map.entities):
                if entity is not self.engine.player and hasattr(entity, 'fighter') and entity.fighter and hasattr(entity.fighter, 'hp') and hasattr(entity.fighter, 'is_alive'):
                    entity.fighter.hp = 0

            self.engine.message_log.add_message("GOD MODE BABY!!!!!!!!", color.purple)
        # F1 toggles lag profiler overlay
        elif key == tcod.event.K_F1:
            self.engine.show_lag_profiler = not getattr(self.engine, "show_lag_profiler", False)
            self.engine.message_log.add_message("Lag profiler toggled.", color.green)
        # F2 toggles debug overlay
        elif key == tcod.event.K_F2:
            self.engine.debug = not self.engine.debug
            self.engine.message_log.add_message("Debug mode toggled.", color.green)
        elif key == tcod.event.K_F11:
            from __main__ import toggle_fullscreen, _game_context
            toggle_fullscreen(context=_game_context)
        elif key == tcod.event.K_F10:
            return DebugConsoleHandler(self.engine)
        # F3 shows limb stats debug
        elif key == tcod.event.K_F3:
            return EntityDebugHandler(self.engine)
        # F12 dumps full tileset atlas to RP/full_atlas.png
        elif key == tcod.event.K_F12:
            import sprite_manager as _sm
            _sm.save_full_atlas()
            self.engine.message_log.add_message("Atlas saved → RP/full_atlas.png", (200, 200, 80))


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
        
        # Interact action (Right click) checks if within reach of player
        elif key in MOVE_KEYS and modifier & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT):
            dx, dy = MOVE_KEYS[key]
            return actions.DodgeAction(player, dx*2, dy*2)
        
        elif key in MOVE_KEYS:
            dx, dy = MOVE_KEYS[key]
            # Movement keys always move — never auto-attack on bump.
            action = actions.MovementAction(player, dx, dy)


        ## KEY INPUTS
        elif key in WAIT_KEYS:
            action = WaitAction(player)
        elif key ==tcod.event.K_ESCAPE:
            self.engine.debug_log("Opening pause menu.", handler=type(self).__name__, event="input")
            return PauseHandler(self.engine)
        elif key == tcod.event.KeySym.V:
            return HistoryViewer(self.engine)
        elif key == tcod.event.KeySym.M:
            if getattr(self.engine.game_map, 'type', None) != 'overworld':
                self.engine.show_minimap = (getattr(self.engine, 'show_minimap', 0) + 1) % 3
            return None
        elif key == tcod.event.KeySym.G:
            action = PickupAction(player)
        elif key == tcod.event.KeySym.R:
            import time as _time
            if not event.repeat:
                # First press — start the hold timer.
                self._r_press_time = _time.monotonic()
            elif self._r_press_time is not None:
                elapsed = _time.monotonic() - self._r_press_time
                if elapsed >= self._RESET_HOLD_DURATION:
                    # Hold threshold reached — reset to a fresh game and re-run chargen.
                    self._r_press_time = None
                    import setup_game
                    import sounds as _sounds
                    from chargen_ui import CharacterCreationHandler
                    _sounds.stop_all_sounds()
                    _sounds.stop_all_music()
                    new_engine = setup_game.new_game()
                    return CRTTransition(
                        CharacterCreationHandler(new_engine),
                    )
        elif key == tcod.event.KeySym.TAB:
            from inventory_ui import InventoryGridUI
            return InventoryGridUI(self.engine)
        # Throw Handler
        elif key == tcod.event.KeySym.T:
            pass
            #return ThrowSelectionHandler(self.engine)
        elif key == tcod.event.KeySym.F1:
            self.engine.show_lag_profiler = not getattr(self.engine, "show_lag_profiler", False)
            self.engine.message_log.add_message("Lag profiler toggled.", color.green)
        elif key == tcod.event.KeySym.E:
            # Combined inventory + equipment grid
            from inventory_ui import InventoryGridUI
            return InventoryGridUI(self.engine)
        elif key == tcod.event.KeySym.P:
            return TestPopupHandler(self.engine)
        # elif key == tcod.event.KeySym.U:
        #     return InventoryEquipHandler(self.engine)
        elif key == tcod.event.KeySym.Q:
            pass
            #return QuaffActivateHandler(self.engine)
        elif key == tcod.event.KeySym.Z:
            pass
            #return InventoryDropHandler(self.engine)
        elif key == tcod.event.KeySym.F:
            from character_sheet_ui import CharacterScreen
            return CharacterScreen(self.engine)
        # t key for targeting mode
        #elif key == tcod.event.KeySym.A:
        #    return AttackModeHandler(self.engine)
        #elif key == tcod.event.KeySym.S:
        #    return LookHandler(self.engine)
        elif key == tcod.event.KeySym.C:
            return SpellCastingHandler(self.engine)

        # Quick cast from slots (Shift+1-9)
        elif (key in [tcod.event.KeySym.N1, tcod.event.KeySym.N2, tcod.event.KeySym.N3, 
                      tcod.event.KeySym.N4, tcod.event.KeySym.N5, tcod.event.KeySym.N6,
                      tcod.event.KeySym.N7, tcod.event.KeySym.N8, tcod.event.KeySym.N9]):
            
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
                            self.engine.execute_action(spell_action, is_player_action=False)
                            
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
        #self.engine.debug_log(f"Unbound key pressed: {key} (modifiers: {modifier})", handler=type(self).__name__, event="input")
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
        _fade_console_background(console, menu_x, menu_y, menu_width, menu_height)
        
    def on_exit(self) -> Optional[ActionOrHandler]:
        """Handle exiting the text input - return to main game if we have engine."""
        if self.engine is not None:
            return MainGameEventHandler(self.engine)
        return None
        
    def on_render(self, console: tcod.Console) -> None:
        # Render background appropriately based on context
        if self.engine is not None:
            # In-game: render the HUD and overlays above the scaled game texture.
            self.engine.render_ui(console)
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


class DebugConsoleHandler(TextInputHandler):
    """Debug console opened with F10. Type commands and press Enter."""

    def __init__(self, engine: Engine):
        super().__init__(
            engine=engine,
            title="Debug Console",
            prompt=">>>",
            max_length=180,
            callback=None,
        )
        self.output_lines: list[str] = []
        self.history: list[str] = []
        self.history_index: int = 0

    def _set_buffer(self, value: str) -> None:
        self.text = value
        self.cursor_pos = len(self.text)

    def push_output(self, message: str) -> None:
        """Add a string (may contain \\n) to the output panel."""
        for line in str(message).splitlines():
            self.output_lines.append(line)
        self.output_lines = self.output_lines[-200:]

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        key = event.sym

        if key == tcod.event.KeySym.ESCAPE:
            return MainGameEventHandler(self.engine)

        if key == tcod.event.KeySym.UP:
            if self.history and self.history_index > 0:
                self.history_index -= 1
                self._set_buffer(self.history[self.history_index])
            return None

        if key == tcod.event.KeySym.DOWN:
            if self.history_index < len(self.history) - 1:
                self.history_index += 1
                self._set_buffer(self.history[self.history_index])
            else:
                self.history_index = len(self.history)
                self._set_buffer("")
            return None

        if key == tcod.event.KeySym.RETURN or key == tcod.event.KeySym.KP_ENTER:
            command = self.text.strip()
            self._set_buffer("")
            if not command:
                return None
            if command in {"exit", "quit"}:
                return MainGameEventHandler(self.engine)
            self.history.append(command)
            self.history_index = len(self.history)
            self.push_output(f">>> {command}")
            command = command.lower()

            if command == "help":
                from components.effect import list_available_effects
                effects_list = ", ".join(list_available_effects())
                self.push_output(f"""
Debug Console Commands:

effect <name> [duration]      - Apply effect. Examples: effect sleep, effect darkvision 100
Available effects: {effects_list}

give(ITEM)                    - Ex. give(sigil_stone)
give(spells)                  - Unlock every spell
spawn(ENTITY)                 - Ex. spawn giant_spider                 
chest [basic|advanced]        - Spawn a chest with generated loot

level <TRAIT>                 - Force levelup trait
descend                       - Go to next dungeon level
noclip                        - Toggle noclip mode (phase through walls)
                
""")
            elif command.startswith("seed"):
                from setup_game import _current_seed
                self.push_output(f"Current game seed: {_current_seed}")
            elif command.startswith("effect "):
                from components.effect import get_effect_by_name
                
                parts = command[len("effect "):].strip().split()
                if not parts:
                    self.push_output("Usage: effect <name> [duration]")
                    return None
                
                effect_name = parts[0]
                duration = 100  # Default duration
                
                # Parse optional duration parameter
                if len(parts) > 1:
                    try:
                        duration = int(parts[1])
                    except ValueError:
                        self.push_output(f"Invalid duration '{parts[1]}'. Using default duration 100.")
                
                effect = get_effect_by_name(effect_name, duration=duration)
                if effect:
                    if not hasattr(self.engine.player, 'effects'):
                        self.engine.player.effects = []
                    self.engine.player.effects.append(effect)
                    self.push_output(f"Applied {effect.name} for {duration} turns")
                else:
                    from components.effect import list_available_effects
                    self.push_output(f"Unknown effect: '{effect_name}'")
                    self.push_output(f"Available: {', '.join(list_available_effects())}")
            elif command == "give(spellbook)":
                import entity_factories
                self.engine.player.inventory.items.append(entity_factories.generate_spellbook())
                self.push_output("Generated spellbook added to inventory")

            elif command == "give(spells)":
                import inspect
                import components.spells as _spells
                player = self.engine.player
                if not hasattr(player, "known_spells") or player.known_spells is None:
                    player.known_spells = []
                already = {type(s) for s in player.known_spells}
                added = []
                for name, cls in inspect.getmembers(_spells, inspect.isclass):
                    if name.endswith("Spell") and name != "Spell" and cls not in already:
                        try:
                            player.known_spells.append(cls())
                            added.append(name.replace("Spell", ""))
                        except Exception:
                            pass
                if added:
                    self.push_output(f"Unlocked {len(added)} spell(s): {', '.join(added)}")
                else:
                    self.push_output("All spells already known.")

            elif command == "chest" or command.startswith("chest "):
                import entity_factories as _ef
                import loot_tables as _lt

                parts = command.split(maxsplit=1)
                chest_tier = parts[1].strip().lower() if len(parts) > 1 else "basic"
                if chest_tier not in {"basic", "advanced"}:
                    self.push_output(f"Unknown chest tier: '{chest_tier}'")
                    self.push_output("Use: chest [basic|advanced]")
                else:
                    loot = _lt.generate_tiered_chest_loot(chest_tier)
                    chest = _ef.make_chest_with_loot(loot, capacity=max(6, len(loot)))

                    px, py = self.engine.player.x, self.engine.player.y
                    import random as _rand

                    offsets = [(dx, dy) for dx in range(-2, 3) for dy in range(-2, 3) if (dx, dy) != (0, 0)]
                    _rand.shuffle(offsets)
                    spawned = False
                    gm = self.engine.game_map
                    for dx, dy in offsets:
                        tx, ty = px + dx, py + dy
                        if gm.in_bounds(tx, ty) and gm.tiles["walkable"][tx, ty] and not any(e.x == tx and e.y == ty for e in gm.entities):
                            chest.spawn(gm, tx, ty)
                            self.push_output(f"Spawned {chest_tier} chest with {len(loot)} loot item(s) at ({tx}, {ty})")
                            spawned = True
                            break
                    if not spawned:
                        self.push_output("No free tile found near player to spawn chest")

            elif command.startswith("descend"):
                # Check if floor number attached
                parts = command.split(maxsplit=1)
                if len(parts) > 1:
                    try:
                        floor_number = int(parts[1])
                        for _ in range(floor_number):
                            self.engine.game_world.descend()
                    except ValueError:
                        self.push_output(f"Invalid floor number: '{parts[1]}'")
                else:
                    self.engine.game_world.descend()

            elif command.startswith("level "):
                # Force levelup for trait
                trait_name = command[len("level "):].strip()
                trait = None
                for t in self.engine.player.level.traits:
                    if t.lower() == trait_name:
                        trait = t
                        break
                if trait:
                    level = self.engine.player.level
                    xp_required = level.xp_to_next(trait)
                    level.traits[trait]["xp"] += xp_required
                    previous_level = level.traits[trait]["level"]
                    level.level_up(trait, play_sound=False)
                    new_level = level.traits[trait]["level"]
                    self.push_output(
                        f"{trait} leveled: {previous_level} -> {new_level} (xp +{xp_required})"
                    )
                else:
                    self.push_output(f"Unknown trait: '{trait_name}'")

            elif command.startswith("spawn "):
                entity_name = command[len("spawn "):].strip()
                import entity_factories as _ef
                template = None

                scroll_name = None
                lowered_name = entity_name.lower()
                if lowered_name.startswith("scroll "):
                    scroll_name = entity_name[len("scroll "):].strip()
                elif lowered_name.endswith("_scroll"):
                    scroll_name = entity_name[:-len("_scroll")].strip()

                if scroll_name:
                    try:
                        template = _ef.get_scroll(scroll_name)
                        entity_name = f"Scroll of {scroll_name.title()}"
                    except Exception as exc:
                        self.push_output(f"Failed to build scroll '{scroll_name}': {exc}")
                        template = None

                if template is None:
                    template = getattr(_ef, entity_name, None)
                if template is None:
                    self.push_output(f"Unknown entity: '{entity_name}'")
                    if entity_name.lower() == "help":
                        self.push_output("Try: NAME_scroll " + ", ".join(
                            k for k in dir(_ef)
                            if not k.startswith("_") and hasattr(getattr(_ef, k, None), "spawn")

                        ))
                else:
                    px, py = self.engine.player.x, self.engine.player.y
                    # Try adjacent tiles to avoid overlap with the player
                    import random as _rand
                    offsets = [(dx, dy) for dx in range(-2, 3) for dy in range(-2, 3) if (dx, dy) != (0, 0)]
                    _rand.shuffle(offsets)
                    spawned = False
                    gm = self.engine.game_map
                    for dx, dy in offsets:
                        tx, ty = px + dx, py + dy
                        if gm.in_bounds(tx, ty) and gm.tiles["walkable"][tx, ty] and not any(e.x == tx and e.y == ty for e in gm.entities):
                            template.spawn(gm, tx, ty)
                            self.push_output(f"Spawned {entity_name} at ({tx}, {ty})")
                            spawned = True
                            break
                    if not spawned:
                        self.push_output(f"No free tile found near player to spawn {entity_name}")

            elif command == "noclip":
                # Toggle noclip mode - allows player to phase through walls and entities
                noclip_enabled = getattr(self.engine.player, "noclip", False)
                self.engine.player.noclip = not noclip_enabled
                status = "ENABLED" if self.engine.player.noclip else "DISABLED"
                self.push_output(f"Noclip {status}")
            
            elif command == "reveal":
                # Reveals the whole map
                if self.engine.game_map:
                    self.engine.game_map.visible[:] = True
                    self.engine.game_map.explored[:] = True
                    self.push_output("Map revealed!")

            # ----------------------------------------------------------------
            # ADD YOUR COMMAND HANDLING CODE HERE
            # Use self.push_output("some text") to write to the console panel.
            # self.engine, self.engine.player, self.engine.game_map available.
            # Example:
            #   if command == "heal":
            #       self.engine.player.fighter.hp = self.engine.player.fighter.max_hp
            #       self.push_output("Player fully healed.")
            #   else:
            #       self.push_output(f"Unknown command: {command}")
            # ----------------------------------------------------------------

            return None

        return super().ev_keydown(event)

    def on_render(self, console: tcod.Console) -> None:
        self.engine.render_ui(console)

        width = max(56, console.width - 6)
        height = max(16, console.height - 8)
        x = (console.width - width) // 2
        y = (console.height - height) // 2

        self.render_faded(console, x, y, width, height)
        MenuRenderer.draw_parchment_background(console, x, y, width, height)
        MenuRenderer.draw_ornate_border(console, x, y, width, height, "Debug Console")

        hint = "F10 open  |  ESC close  |  Enter run  |  Up/Down history"
        console.print(x + 2, y + 2, hint, fg=color.bronze_text)

        body_top = y + 4
        body_bottom = y + height - 4
        max_lines = max(1, body_bottom - body_top + 1)
        max_width = width - 4
        display_lines: list[str] = []
        for line in self.output_lines:
            wrapped = textwrap.wrap(line, max_width) if line.strip() else [""]
            display_lines.extend(wrapped)
        for i, line in enumerate(display_lines[-max_lines:]):
            console.print(x + 2, body_top + i, line, fg=color.fantasy_text)

        prompt_line = f">>> {self.text}"
        console.print(x + 2, y + height - 2, prompt_line[: width - 5], fg=color.white, bg=(60, 40, 25))

        import time
        if int(time.time() * 2) % 2:
            cursor_x = min(x + 2 + len(">>> ") + self.cursor_pos, x + width - 3)
            console.print(cursor_x, y + height - 2, "_", fg=color.gold_accent, bg=(60, 40, 25))


class GameWonEventHandler(EventHandler):
   
    FADE_DURATION = 3.0
   
    def __init__(self, engine: Engine, boss_name: str = ""):
        super().__init__(engine)
        import time as _time

        self._spawn_time = _time.monotonic()
        self.boss_name = str(boss_name)

    def _get_fade_alpha(self) -> float:
        """Return 0.0 → 1.0 over FADE_DURATION seconds."""
        import time as _time
        elapsed = _time.monotonic() - self._spawn_time
        return min(1.0, elapsed / self.FADE_DURATION)

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)
        alpha = self._get_fade_alpha()
        if alpha <= 0.0:
            return

        window_width = 30
        window_height = 6
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2
        
        # Fade the entire screen except for the game over message area
        super().render_faded(console, x, y, window_width, window_height)
        
        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height, bg_color=(color.dark_red))
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "VICTORY", border_fg=(color.red))
        
        console.print(x + 1, y + 2, "Thanks for playing!", fg=(color.yellow))
        console.print(x + 1, y + 3, "Feel free to keep exploring.", fg=(color.light_green))

        # Blend the popup region toward the underlying game image based on alpha
        if alpha < 1.0:
            inv = 1.0 - alpha
            # Dim fg toward black and bg toward the game background
            x2 = min(console.width, x + window_width)
            y2 = min(console.height, y + window_height)
            region_fg = console.fg[x:x2, y:y2].astype(np.float32)
            region_bg = console.bg[x:x2, y:y2].astype(np.float32)
            # Lerp toward the faded background colour (the area outside the popup)
            fade_bg = np.array((20, 20, 30), dtype=np.float32)
            console.fg[x:x2, y:y2] = (region_fg * alpha + fade_bg * inv).astype(np.uint8)
            console.bg[x:x2, y:y2] = (region_bg * alpha + fade_bg * inv).astype(np.uint8)
    


    def ev_quit(self, event: tcod.event.Quit) -> None:
        return MainGameEventHandler(self.engine)

    def ev_keydown(self, event: tcod.event.KeyDown) -> None:
        if event.sym == tcod.event.K_ESCAPE:
            return MainGameEventHandler(self.engine)
    

class GameOverEventHandler(EventHandler):

    FADE_DURATION = 3.0  # seconds for the popup to fully fade in

    def __init__(self, engine: Engine):
        super().__init__(engine)
        import time as _time

        self._spawn_time = _time.monotonic()

    def _get_fade_alpha(self) -> float:
        """Return 0.0 → 1.0 over FADE_DURATION seconds."""
        import time as _time
        elapsed = _time.monotonic() - self._spawn_time
        return min(1.0, elapsed / self.FADE_DURATION)

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)
        alpha = self._get_fade_alpha()
        if alpha <= 0.0:
            return

        window_width = 30
        window_height = 6
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2
        
        # Fade the entire screen except for the game over message area
        super().render_faded(console, x, y, window_width, window_height)
        
        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height, bg_color=(color.dark_red))
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "DEATH", border_fg=(color.red))
        
        console.print(x + 2, y + 2, "Your adventure ends here.", fg=(color.light_red))
        console.print(x + 2, y + 3, "You fade into obscurity...", fg=(color.light_gray))

        # Blend the popup region toward the underlying game image based on alpha
        if alpha < 1.0:
            inv = 1.0 - alpha
            # Dim fg toward black and bg toward the game background
            x2 = min(console.width, x + window_width)
            y2 = min(console.height, y + window_height)
            region_fg = console.fg[x:x2, y:y2].astype(np.float32)
            region_bg = console.bg[x:x2, y:y2].astype(np.float32)
            # Lerp toward the faded background colour (the area outside the popup)
            fade_bg = np.array((20, 20, 30), dtype=np.float32)
            console.fg[x:x2, y:y2] = (region_fg * alpha + fade_bg * inv).astype(np.uint8)
            console.bg[x:x2, y:y2] = (region_bg * alpha + fade_bg * inv).astype(np.uint8)
    
    def on_quit(self) -> None:
        """Handle exiting out of a finished game."""
        import setup_game  # Local import to avoid circular dependency
        savegame_path = setup_game.get_save_path("savegame.sav")
        if os.path.exists(savegame_path):
            os.remove(savegame_path)  # Deletes the active save file.
        sounds.stop_all_music()
        sounds.stop_all_sounds()
        from setup_game import MainMenu
        return CRTTransition(
            MainMenu(_auto_music=False),
            post_fn=lambda: (sounds.start_menu_ambience(), sounds.start_menu_music()),
        )

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
        self.engine.context_hints = [
            ("\u2191\u2193", "Navigate"),
            ("Enter", "Select"),
            ("Esc", "Resume"),
        ]
        self.categories = ["Resume Game", "Save and Exit", "Exit without Saving", "Settings"]
        self.selected_option = 0
        self.scroll_offset = 0
        self.max_visible_lines = 10  # Max lines to show in options list before scrolling
        self.selected_option = 0  # Default to first option

    """Open pause menu, settings, save and exit, etc"""
    def on_render(self, console):
        self.engine.render_ui(console)  # Draw the HUD state above the scaled game.
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
        
        sounds.stop_all_sounds()
        sounds.stop_all_music()
        from setup_game import MainMenu
        return CRTTransition(
            MainMenu(_auto_music=False),
            post_fn=lambda: (sounds.start_menu_ambience(), sounds.start_menu_music()),
        )
    
    def process_response(self, response: str):
        if response == "Resume Game":
            return MainGameEventHandler(self.engine)
        elif response == "Save and Exit":
            return TextInputHandler(self.engine, prompt="Enter save name:", callback=self.handle_save_with_name)
        elif response == "Exit without Saving":
            sounds.stop_all_sounds()
            sounds.stop_all_music()
            from setup_game import MainMenu
            return CRTTransition(
                MainMenu(_auto_music=False),
                post_fn=lambda: (sounds.start_menu_ambience(), sounds.start_menu_music()),
            )
        
        elif response == "Settings":
            return Settings(parent_handler=self)
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

    def ev_mousewheel(self, event: tcod.event.MouseWheel) -> Optional[MainGameEventHandler]:
        if event.y > 0:
            self.cursor = max(0, self.cursor - 1)  # Scroll up
        elif event.y < 0:
            self.cursor = min(self.log_length - 1, self.cursor + 1)  # Scroll down
        return None

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
    """F3 — move cursor to inspect any entity or tile."""

    def __init__(self, engine: Engine):
        super().__init__(engine)
        self._scroll_offset = 0

    @staticmethod
    def _append_balance_lines(lines: list[tuple[str, tuple[int, int, int]]]) -> None:
        sections = [
            (
                "BALANCE CONFIG:",
                [
                    "BASE_TRAIT_LEVEL",
                    "STARTING_MANA_BASE",
                    "STARTING_MANA_PER_ARCANA_LEVEL",
                    "VIGOR_HP_PER_LEVEL",
                    "ARCANA_MANA_PER_LEVEL",
                ],
            ),
            (
                "HIT / DAMAGE:",
                [
                    "MELEE_BASE_HIT",
                    "RANGED_BASE_HIT",
                    "MIN_HIT_CHANCE",
                    "MAX_HIT_CHANCE",
                    "AGILITY_HIT_BONUS_PER_LEVEL",
                    "AGILITY_HIT_BONUS_CAP",
                    "STRENGTH_MELEE_DAMAGE_PER_LEVEL",
                    "AGILITY_RANGED_DAMAGE_PER_LEVEL",
                ],
            ),
            (
                "MANA / SPELLS:",
                [
                    "MANA_REGEN_CHANCE",
                    "MANA_REGEN_FRACTION",
                    "SPELL_BASE_SUCCESS_CHANCE",
                    "SPELL_SUCCESS_BONUS_PER_LEVEL",
                    "SPELL_MIN_SUCCESS_CHANCE",
                    "SPELL_MAX_SUCCESS_CHANCE",
                    "SPELL_FIZZLE_MANA_REFUND_FRACTION",
                ],
            ),
            (
                "WEAPON SKILL SCALING:",
                [
                    "WEAPON_SKILL_BASE_ACCURACY",
                    "WEAPON_SKILL_ACCURACY_PER_LEVEL",
                    "WEAPON_SKILL_BASE_DAMAGE",
                    "WEAPON_SKILL_DAMAGE_PER_LEVEL",
                ],
            ),
            (
                "ARMOR SKILL SCALING:",
                [
                    "ARMOR_SKILL_BASE_DEFENSE",
                    "ARMOR_SKILL_DEFENSE_PER_LEVEL",
                    "ARMOR_AFFINITY_MITIGATION_PER_LEVEL",
                    "ARMOR_AFFINITY_MITIGATION_CAP",
                    "ARMOR_DEFENSE_SKILL_PER_LEVEL",
                ],
            ),
            (
                "DODGE:",
                [
                    "AGILITY_DODGE_BONUS_PER_LEVEL",
                    "ARMOR_DODGE_BONUS_PER_LEVEL",
                    "LIGHT_ARMOR_DODGE_PENALTY",
                    "MEDIUM_ARMOR_DODGE_PENALTY",
                    "HEAVY_ARMOR_DODGE_PENALTY",
                ],
            ),
            (
                "MULTIPLIER CLAMPING:",
                [
                    "PROFICIENCY_MULTIPLIER_MIN",
                    "PROFICIENCY_MULTIPLIER_MAX",
                ],
            ),
        ]

        lines.append(("", color.white))
        for heading, names in sections:
            lines.append((heading, color.yellow))
            for name in names:
                value = getattr(balance_config, name, None)
                lines.append((f"{name}: {value}", color.light_gray))
            lines.append(("", color.white))

        lines.append((f"trait_delta(1): {balance_config.trait_delta(1)}", color.cyan))

    @staticmethod
    def _append_lag_chart_lines(engine: Engine, lines: list[tuple[str, tuple[int, int, int]]]) -> None:
        """Append a compact F3-style lag chart from engine profiling samples."""
        lines.append(("", color.white))
        lines.append(("LAG CHART (EMA):", color.yellow))

        profiler = getattr(engine, "lag_profiler", None)
        if not isinstance(profiler, dict):
            lines.append(("Profiler unavailable", color.dark_gray))
            return

        ema_ms = profiler.get("ema_ms", {}) or {}
        last_ms = profiler.get("last_frame_ms", {}) or {}
        if not ema_ms:
            lines.append(("Collecting frame samples...", color.dark_gray))
            return

        total_ms = float(ema_ms.get("total", 0.0) or 0.0)
        lines.append((f"Frame: {total_ms:5.2f} ms ({(1000.0 / total_ms) if total_ms > 0 else 0.0:5.1f} fps)", color.cyan))

        # Show the largest contributors dynamically so new/renamed profiler
        # sections are never hidden by a stale hardcoded list.
        label_alias = {
            "entity_updates": "entities",
            "light_shafts": "light",
            "auto_move": "autopath",
            "grass_waves": "grass",
            "global_anims": "globalfx",
            "cleanup": "cleanup",
            "tutorial": "tutorial",
        }
        section_items: list[tuple[str, float]] = []
        for key, value in ema_ms.items():
            if key == "total":
                continue
            ms = float(value or 0.0)
            if ms > 0.0:
                section_items.append((key, ms))
        section_items.sort(key=lambda kv: kv[1], reverse=True)
        section_sum_ms = sum(ms for _, ms in section_items)
        denom_ms = max(total_ms, section_sum_ms, 0.001)

        bar_width = 14
        shown_ms = 0.0
        max_rows = 8
        for key, ms in section_items[:max_rows]:
            shown_ms += ms
            pct = (ms / denom_ms * 100.0)
            fill = max(0, min(bar_width, int(round((pct / 100.0) * bar_width))))
            bar = ("#" * fill) + ("." * (bar_width - fill))

            if pct >= 40.0:
                fg = color.red
            elif pct >= 20.0:
                fg = color.orange
            else:
                fg = color.light_gray

            label = label_alias.get(key, key)
            lines.append((f"{label[:12]:<12} {ms:5.2f} {pct:4.0f}% {bar}", fg))

        other_ms = max(0.0, denom_ms - shown_ms)
        if other_ms > 0.25:
            pct = (other_ms / denom_ms * 100.0)
            fill = max(0, min(bar_width, int(round((pct / 100.0) * bar_width))))
            bar = ("#" * fill) + ("." * (bar_width - fill))
            lines.append((f"{'other':<12} {other_ms:5.2f} {pct:4.0f}% {bar}", color.gray))

        if last_ms:
            last_total = float(last_ms.get("total", 0.0) or 0.0)
            lines.append((f"Last frame total: {last_total:5.2f} ms", color.gray))

            # During spikes, show top offenders from the most recent frame,
            # not only EMA averages.
            spike_threshold = max(20.0, total_ms * 1.35)
            if last_total >= spike_threshold:
                lines.append(("SPIKE OFFENDERS (LAST):", color.orange))
                offenders: list[tuple[str, float]] = []
                for key, value in last_ms.items():
                    if key == "total":
                        continue
                    ms = float(value or 0.0)
                    if ms > 0.0:
                        offenders.append((key, ms))
                offenders.sort(key=lambda kv: kv[1], reverse=True)
                last_sum_ms = sum(ms for _, ms in offenders)
                last_denom_ms = max(last_total, last_sum_ms, 0.001)

                for key, ms in offenders[:6]:
                    pct = (ms / last_denom_ms * 100.0)
                    ema_val = float(ema_ms.get(key, 0.0) or 0.0)
                    delta = ms - ema_val

                    if pct >= 30.0:
                        fg = color.red
                    elif pct >= 15.0:
                        fg = color.orange
                    else:
                        fg = color.light_gray

                    label = label_alias.get(key, key)
                    lines.append((f"{label[:12]:<12} {ms:5.2f} {pct:4.0f}% d{delta:+5.1f}", fg))

    def _build_debug_lines(
        self,
        cursor_x: int,
        cursor_y: int,
        target_entity,
    ) -> list[tuple[str, tuple[int, int, int]]]:
        lines: list[tuple[str, tuple[int, int, int]]] = []

        if target_entity:
            entity_name = getattr(target_entity, 'name', 'Unknown')
            if target_entity == self.engine.player:
                lines.append((f"PLAYER: {entity_name}", color.green))
            else:
                lines.append((f"ENTITY: {entity_name}", color.white))
            lines.append((f"Position: ({cursor_x}, {cursor_y})", color.gray))
            lines.append(("", color.white))

            if hasattr(target_entity, 'body_parts') and target_entity.body_parts:
                lines.append(("BODY PARTS:", color.yellow))
                body_parts = target_entity.body_parts

                for part_type, part in body_parts.body_parts.items():
                    hp_text = f"{part.current_hp}/{part.max_hp}"
                    hp_ratio = body_parts.get_part_health_ratio(part)

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

                    part_line = f"{part.name:<14} {hp_text:>6} ({hp_ratio*100:.0f}%)"
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
                        part_line = f"{part_line} [{' '.join(status_info)}]"
                    lines.append((part_line, hp_color))

                if hasattr(body_parts, 'get_movement_penalty'):
                    movement_penalty = body_parts.get_movement_penalty()
                    if movement_penalty > 0:
                        lines.append(("", color.white))
                        penalty_text = f"Movement Penalty: {movement_penalty*100:.0f}%"
                        penalty_color = color.red if movement_penalty > 0.5 else color.yellow
                        lines.append((penalty_text, penalty_color))
            else:
                lines.append(("No body parts system", color.red))

            lines.append(("", color.white))
            if hasattr(target_entity, 'fighter') and target_entity.fighter:
                lines.append(("FIGHTER STATS:", color.yellow))
                lines.append((f"HP: {target_entity.fighter.hp}/{target_entity.fighter.max_hp}", color.white))
                lines.append((f"Defense: {target_entity.fighter.defense}", color.white))
                lines.append((f"Power: {target_entity.fighter.power}", color.white))
                mana_value = getattr(target_entity, 'mana', None)
                mana_max = getattr(target_entity, 'mana_max', None)
                if mana_value is not None or mana_max is not None:
                    lines.append((f"Mana: {mana_value}/{mana_max}", color.cyan))

            if hasattr(target_entity, 'ai') and target_entity.ai:
                lines.append((f"AI: {type(target_entity.ai).__name__}", color.cyan))

            self._append_derived_stat_lines(target_entity, lines)
        else:
            lines.append(("TILE INFORMATION:", color.cyan))
            lines.append((f"Position: ({cursor_x}, {cursor_y})", color.gray))
            lines.append(("", color.white))

            if self.engine.game_map.in_bounds(cursor_x, cursor_y):
                tile = self.engine.game_map.tiles[cursor_x, cursor_y]

                if self.engine.game_map.visible[cursor_x, cursor_y]:
                    lines.append(("Visibility: VISIBLE", color.green))
                else:
                    lines.append(("Visibility: NOT VISIBLE", color.red))

                if tile['walkable']:
                    lines.append(("Walkable: YES", color.green))
                else:
                    lines.append(("Walkable: NO", color.red))

                if tile['transparent']:
                    lines.append(("Transparent: YES", color.green))
                else:
                    lines.append(("Transparent: NO", color.red))

                if self.engine.game_map.visible[cursor_x, cursor_y]:
                    char = int(tile['light'][0])
                    fg_color = tuple(tile['light'][1])
                    bg_color = tuple(tile['light'][2])
                    lines.append((f"Char: '{chr(char)}' ({char})", color.white))
                    lines.append((f"FG Color: {fg_color}", color.white))
                    lines.append((f"BG Color: {bg_color}", color.white))
                lines.append(("", color.white))

                items_here = [
                    e for e in self.engine.game_map.entities
                    if e.x == cursor_x and e.y == cursor_y and not (hasattr(e, 'fighter') or hasattr(e, 'ai'))
                ]

                if items_here:
                    lines.append(("ITEMS HERE:", color.yellow))
                    for item in items_here:
                        shown_name = identify_system.get_display_name(self.engine.player, item)
                        lines.append((f"- {shown_name}", color.white))
                    lines.append(("", color.white))

                if hasattr(self.engine.game_map, 'liquid_system'):
                    coating = self.engine.game_map.liquid_system.get_coating(cursor_x, cursor_y)
                    if coating:
                        liquid_name = coating.liquid_type.get_display_name().title()
                        lines.append((f"Coating: {liquid_name}", color.cyan))
            else:
                lines.append(("OUT OF BOUNDS", color.red))

        self._append_balance_lines(lines)
        return lines

    @staticmethod
    def _append_derived_stat_lines(entity, lines: list[tuple[str, tuple[int, int, int]]]) -> None:
        if not hasattr(entity, 'level') or not getattr(entity.level, 'traits', None):
            return

        lines.append(("", color.white))
        lines.append(("DERIVED STATS:", color.yellow))

        strength_delta = balance_config.trait_delta(entity.level.traits.get("strength", {}).get("level", 1))
        agility_delta = balance_config.trait_delta(entity.level.traits.get("agility", {}).get("level", 1))
        arcana_delta = balance_config.trait_delta(entity.level.traits.get("arcana", {}).get("level", 1))

        melee_strength_mult = 1.0 + (strength_delta * balance_config.STRENGTH_MELEE_DAMAGE_PER_LEVEL)
        ranged_agility_mult = 1.0 + (agility_delta * balance_config.AGILITY_RANGED_DAMAGE_PER_LEVEL)

        equipped_weapons = actions._collect_equipped_weapons(entity)
        weapon_profile = actions._weapon_proficiency_profile(entity, equipped_weapons)
        weapon_tags: set[str] = set()
        for weapon in equipped_weapons:
            weapon_tags.update(actions._item_tags(weapon))

        armor_tags: set[str] = set()
        if getattr(entity, "equipment", None):
            try:
                armor_tags.update(entity.equipment.get_all_armor_tags())
            except Exception:
                pass

        armor_profile = profsys.armor_profile(entity, armor_tags)
        effective_dodge = actions._effective_dodge_chance(entity, list(armor_tags))

        lines.append((f"Strength delta: +{strength_delta}", color.light_gray))
        lines.append((f"Agility delta: +{agility_delta}", color.light_gray))
        lines.append((f"Arcana delta: +{arcana_delta}", color.light_gray))
        lines.append((f"Melee strength mult: x{melee_strength_mult:.2f}", color.white))
        lines.append((f"Ranged agility mult: x{ranged_agility_mult:.2f}", color.white))
        lines.append((f"Weapon hit mult: x{weapon_profile.accuracy_multiplier:.2f}", color.white))
        lines.append((f"Weapon damage mult: x{weapon_profile.damage_multiplier:.2f}", color.white))
        lines.append((f"Armor mitigation mult: x{armor_profile.mitigation_multiplier:.2f}", color.white))
        lines.append((f"Armor defense mult: x{armor_profile.defense_bonus_multiplier:.2f}", color.white))
        lines.append((f"Armor dodge delta: {armor_profile.dodge_delta:+.2f}", color.white))
        lines.append((f"Effective dodge chance: {effective_dodge * 100:.0f}%", color.cyan))
        #lines.append((f"Effective block chance: {effective_dodge * 100:.0f}%", color.cyan))
        if weapon_tags:
            lines.append((f"Weapon tags: {', '.join(sorted(weapon_tags))}", color.gray))
        if armor_tags:
            lines.append((f"Armor tags: {', '.join(sorted(armor_tags))}", color.gray))

        known_schools = {
            str(getattr(spell, "school", "")).lower().strip()
            for spell in (getattr(entity, "known_spells", None) or [])
            if getattr(spell, "school", None)
        }
        trained_schools = {
            school_name
            for school_name in profsys.SPELL_SCHOOL_TO_TRAITS.keys()
            if int(entity.level.traits.get(school_name, {}).get("level", 1) or 1) > 1
        }
        spell_schools = sorted(known_schools | trained_schools)
        if not spell_schools:
            spell_schools = ["arcana"]

        fizzled_mana_loss = 1.0 - balance_config.SPELL_FIZZLE_MANA_REFUND_FRACTION
        lines.append(("", color.white))
        lines.append(("SPELL PROFILES:", color.yellow))
        for school_name in spell_schools:
            profile = profsys.spell_profile(entity, school_name)
            lines.append((
                f"{school_name.title()}: success {profile.success_chance * 100:.0f}% | "
                f"fizzle loss {fizzled_mana_loss * 100:.0f}%",
                color.cyan,
            ))

        # Trait levels and XP progression
        lines.append(("", color.white))
        lines.append(("TRAIT LEVELS:", color.yellow))
        
        # Sort traits by level (descending) then by name
        sorted_traits = sorted(
            entity.level.traits.items(),
            key=lambda x: (-x[1].get('level', 0), x[0])
        )
        
        for trait_name, trait_data in sorted_traits:
            level = trait_data.get('level', 0)
            current_xp = trait_data.get('xp', 0)
            xp_needed = entity.level.xp_to_next(trait_name)
            
            # Format: trait_name(level): current_xp/xp_needed
            trait_display = f"{trait_name}({level}): {current_xp}/{xp_needed}xp"
            
            # Color based on progress (green if near level up, gray if low)
            if xp_needed > 0 and current_xp >= xp_needed * 0.75:
                trait_color = color.green  # Near level up
            elif current_xp >= xp_needed:
                trait_color = color.yellow  # Ready to level up
            else:
                trait_color = color.light_gray  # In progress
            
            lines.append((trait_display, trait_color))

    def _clamp_scroll(self, max_offset: int) -> None:
        self._scroll_offset = max(0, min(self._scroll_offset, max_offset))

    def on_index_selected(self, x: int, y: int) -> Optional[ActionOrHandler]:
        return MainGameEventHandler(self.engine)

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)
        self.render_ui_overlay(console)

    def render_game_overlay(self, console: tcod.Console) -> None:
        super().render_game_overlay(console)

    def render_ui_overlay(self, console: tcod.Console) -> None:
        """Draw the debug info panel on the UI layer (full-screen resolution)."""
        cursor_x, cursor_y = self.engine.mouse_location
        cursor_x, cursor_y = int(cursor_x), int(cursor_y)

        # Map world position to UI-console tile space (game view is zoomed 2×).
        screen_position = self.engine.world_to_screen(cursor_x, cursor_y, 40, 25)
        if screen_position is None:
            return
        screen_x, screen_y = screen_position
        ui_x = min(console.width  - 1, screen_x * 2)
        ui_y = min(console.height - 1, screen_y * 2)

        # Find entity to inspect at cursor location
        target_entity = None
        if self.engine.game_map.in_bounds(cursor_x, cursor_y):
            for entity in self.engine.game_map.entities:
                if entity.x == cursor_x and entity.y == cursor_y:
                    if (hasattr(entity, 'fighter') and entity.fighter) or (hasattr(entity, 'body_parts') and entity.body_parts):
                        target_entity = entity
                        break

        # Determine debug window position to avoid cursor
        window_width = 55
        window_height = 30

        if ui_x < console.width // 2:
            debug_x = console.width - window_width - 1
        else:
            debug_x = 1

        if ui_y < console.height // 2:
            debug_y = console.height - window_height - 1
        else:
            debug_y = 1

        # Tell main.py which sub-region to extract as the BLEND sidebar texture.
        self._sidebar_x = debug_x
        self._sidebar_y = debug_y
        self._sidebar_w = window_width
        self._sidebar_h = window_height

        # Draw debug window frame
        title = "DEBUG: Entity Inspector" if target_entity else "DEBUG: Tile Inspector"
        console.draw_frame(
            x=debug_x, y=debug_y, width=window_width, height=window_height,
            title=title, clear=True,
            fg=color.yellow, bg=color.black
        )

        info_y = debug_y + 2
        content_x = debug_x + 2
        content_width = window_width - 4
        visible_lines = window_height - 8

        lines = self._build_debug_lines(cursor_x, cursor_y, target_entity)
        max_offset = max(0, len(lines) - visible_lines)
        self._clamp_scroll(max_offset)

        if self._scroll_offset > 0:
            console.print(content_x, info_y, f"Scroll: {self._scroll_offset}/{max_offset}", fg=color.gray)
        else:
            console.print(content_x, info_y, f"Lines: {len(lines)}", fg=color.gray)
        info_y += 1

        visible_slice = lines[self._scroll_offset:self._scroll_offset + visible_lines - 1]
        for text, fg in visible_slice:
            console.print(content_x, info_y, text[:content_width], fg=fg)
            info_y += 1

        if max_offset > 0:
            footer = "More above/below" if 0 < self._scroll_offset < max_offset else (
                "More below" if self._scroll_offset == 0 else "More above"
            )
            console.print(content_x + 30, debug_y + window_height - 4, footer, fg=color.gray)

        instructions_y = debug_y + window_height - 4
        console.print(debug_x + 2, instructions_y,     "Arrow Keys: Move cursor",    fg=color.light_gray)
        console.print(debug_x + 2, instructions_y + 1, "Ctrl+Up/Down, PgUp/PgDn, Wheel", fg=color.light_gray)
        if target_entity:
            console.print(debug_x + 2, instructions_y + 2, "Mode: Entity inspection", fg=color.green)
        else:
            console.print(debug_x + 2, instructions_y + 2, "Mode: Tile inspection",   fg=color.cyan)
        console.print(debug_x + 2, instructions_y + 3, "Home/End top-bottom, Enter/ESC exit", fg=color.light_gray)

    def ev_mousewheel(self, event: tcod.event.MouseWheel) -> Optional[ActionOrHandler]:
        if event.y > 0:
            self._scroll_offset = max(0, self._scroll_offset - 3)
        elif event.y < 0:
            self._scroll_offset += 3
        return self

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        if event.sym == tcod.event.KeySym.ESCAPE:
            return MainGameEventHandler(self.engine)
        if event.mod & (tcod.event.Modifier.LCTRL | tcod.event.Modifier.RCTRL):
            if event.sym == tcod.event.KeySym.UP:
                self._scroll_offset = max(0, self._scroll_offset - 3)
                return self
            if event.sym == tcod.event.KeySym.DOWN:
                self._scroll_offset += 3
                return self
        if event.sym == tcod.event.KeySym.PAGEUP:
            self._scroll_offset = max(0, self._scroll_offset - 8)
            return self
        if event.sym == tcod.event.KeySym.PAGEDOWN:
            self._scroll_offset += 8
            return self
        if event.sym == tcod.event.KeySym.HOME:
            self._scroll_offset = 0
            return self
        if event.sym == tcod.event.KeySym.END:
            self._scroll_offset = 10_000
            return self
        return super().ev_keydown(event)


class MaterialInspectorHandler(SelectIndexHandler):
    """Debug handler to inspect material values (normals, emissive, specular) for any tile."""
    
    def __init__(self, engine: Engine):
        super().__init__(engine)
        self._scroll_offset = 0
        self._sidebar_x = 0
        self._sidebar_y = 0
        self._sidebar_w = 55
        self._sidebar_h = 30

    def _clamp_scroll(self, max_offset: int) -> None:
        self._scroll_offset = max(0, min(self._scroll_offset, max_offset))

    def on_index_selected(self, x: int, y: int) -> Optional[ActionOrHandler]:
        return MainGameEventHandler(self.engine)

    def _get_material_data(self, cp: int) -> dict:
        """Fetch all material channels for a codepoint."""
        import sprite_manager
        import numpy as np
        
        try:
            # Try to get packed material
            get_packed = getattr(sprite_manager, "get_packed_material", None)
            if callable(get_packed):
                normals, alpha, emission, specular, normal_detail, specular_mask = get_packed(cp, scale=1)
            else:
                # Fallback to individual functions
                normals, alpha = sprite_manager.get_normal_field(cp)
                emission = np.zeros((normals.shape[0], normals.shape[1], 3), dtype=np.float32)
                specular = np.zeros((normals.shape[0], normals.shape[1], 3), dtype=np.float32)
                normal_detail = np.zeros((normals.shape[0], normals.shape[1]), dtype=np.float32)
                specular_mask = np.zeros((normals.shape[0], normals.shape[1]), dtype=np.float32)
            
            # Sample center pixel
            h, w = normals.shape[:2]
            cx, cy = w // 2, h // 2
            
            return {
                'shape': (h, w),
                'normal': tuple(normals[cy, cx, :]),
                'alpha': float(alpha[cy, cx]),
                'emission': tuple(emission[cy, cx, :]),
                'specular': tuple(specular[cy, cx, :]),
                'normal_detail': float(normal_detail[cy, cx]),
                'specular_mask': float(specular_mask[cy, cx]),
                'emission_max': float(np.max(emission)),
                'emission_mean': float(np.mean(emission)),
                'specular_max': float(np.max(specular)),
                'specular_mean': float(np.mean(specular)),
                'has_emissive': bool(np.any(emission > 0.001)),
                'has_specular': bool(np.any(specular_mask > 0.5)),
            }
        except Exception as e:
            return {'error': str(e)}

    def _build_debug_lines(self, cursor_x: int, cursor_y: int) -> list:
        """Build list of (text, color) tuples for display."""
        lines = []
        
        if not self.engine.game_map.in_bounds(cursor_x, cursor_y):
            lines.append(("OUT OF BOUNDS", color.red))
            return lines
        
        tile = self.engine.game_map.tiles[cursor_x, cursor_y]
        
        # Get tile character/codepoint
        if self.engine.game_map.visible[cursor_x, cursor_y]:
            cp = int(tile['light'][0])
        else:
            cp = int(tile['dark'][0])
        
        lines.append(("TILE INFORMATION:", color.cyan))
        lines.append((f"Position: ({cursor_x}, {cursor_y})", color.gray))
        lines.append((f"Codepoint: {cp} (0x{cp:04X}) '{chr(cp)}'", color.white))
        lines.append(("", color.white))
        
        # Check visibility
        visible = self.engine.game_map.visible[cursor_x, cursor_y]
        lines.append((f"Visible: {visible}", color.green if visible else color.red))
        lines.append(("", color.white))
        
        # Get material data
        lines.append(("MATERIAL DATA:", color.yellow))
        mat_data = self._get_material_data(cp)
        
        if 'error' in mat_data:
            lines.append((f"ERROR: {mat_data['error']}", color.red))
        else:
            lines.append((f"Texture Size: {mat_data['shape']}", color.gray))
            lines.append(("", color.white))
            
            # Normal at center pixel
            lines.append(("NORMAL (center pixel):", color.cyan))
            nx, ny, nz = mat_data['normal']
            lines.append((f"  X: {nx:+.3f}", color.white))
            lines.append((f"  Y: {ny:+.3f}", color.white))
            lines.append((f"  Z: {nz:+.3f}", color.white))
            lines.append(("", color.white))
            
            # Alpha
            lines.append(("ALPHA (center pixel):", color.cyan))
            lines.append((f"  Value: {mat_data['alpha']:.3f}", color.white))
            lines.append(("", color.white))
            
            # Emissive
            lines.append(("EMISSIVE:", color.yellow if mat_data['has_emissive'] else color.gray))
            er, eg, eb = mat_data['emission']
            lines.append((f"  Center RGB: ({er:.3f}, {eg:.3f}, {eb:.3f})", 
                         color.yellow if (er + eg + eb) > 0.001 else color.gray))
            lines.append((f"  Max: {mat_data['emission_max']:.3f}", 
                         color.yellow if mat_data['emission_max'] > 0.001 else color.gray))
            lines.append((f"  Mean: {mat_data['emission_mean']:.4f}", color.gray))
            lines.append((f"  Has Emission: {mat_data['has_emissive']}", 
                         color.green if mat_data['has_emissive'] else color.red))
            lines.append(("", color.white))
            
            # Specular
            lines.append(("SPECULAR:", color.white))
            sr, sg, sb = mat_data['specular']
            lines.append((f"  Center RGB: ({sr:.3f}, {sg:.3f}, {sb:.3f})", color.white))
            lines.append((f"  Max: {mat_data['specular_max']:.3f}", color.white))
            lines.append((f"  Mean: {mat_data['specular_mean']:.4f}", color.gray))
            lines.append((f"  Detail Flag: {mat_data['normal_detail']:.3f}", color.white))
            lines.append((f"  Specular Mask: {mat_data['specular_mask']:.3f}", color.white))
            lines.append((f"  Has Specular: {mat_data['has_specular']}", 
                         color.green if mat_data['has_specular'] else color.red))
        
        return lines

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)

    def render_game_overlay(self, console: tcod.Console) -> None:
        super().render_game_overlay(console)

    def render_ui_overlay(self, console: tcod.Console) -> None:
        """Draw the material inspector panel on the UI layer (full-screen resolution)."""
        cursor_x, cursor_y = self.engine.mouse_location
        cursor_x, cursor_y = int(cursor_x), int(cursor_y)

        # Map world position to UI-console tile space (game view is zoomed 2×).
        screen_position = self.engine.world_to_screen(cursor_x, cursor_y, 40, 25)
        if screen_position is None:
            return
        screen_x, screen_y = screen_position
        ui_x = min(console.width  - 1, screen_x * 2)
        ui_y = min(console.height - 1, screen_y * 2)
        
        # Determine debug window position to avoid cursor
        window_width = 55
        window_height = 30
        
        if ui_x < console.width // 2:
            debug_x = console.width - window_width - 1
        else:
            debug_x = 1
        
        if ui_y < console.height // 2:
            debug_y = console.height - window_height - 1
        else:
            debug_y = 1
        
        # Tell main.py which sub-region to extract as the BLEND sidebar texture.
        self._sidebar_x = debug_x
        self._sidebar_y = debug_y
        self._sidebar_w = window_width
        self._sidebar_h = window_height
        
        # Draw debug window frame
        console.draw_frame(
            x=debug_x, y=debug_y, width=window_width, height=window_height,
            title="MATERIAL INSPECTOR", clear=True,
            fg=color.yellow, bg=color.black
        )
        
        info_y = debug_y + 2
        content_x = debug_x + 2
        content_width = window_width - 4
        visible_lines = window_height - 8
        
        lines = self._build_debug_lines(cursor_x, cursor_y)
        max_offset = max(0, len(lines) - visible_lines)
        self._clamp_scroll(max_offset)
        
        if self._scroll_offset > 0:
            console.print(content_x, info_y, f"Scroll: {self._scroll_offset}/{max_offset}", fg=color.gray)
        else:
            console.print(content_x, info_y, f"Lines: {len(lines)}", fg=color.gray)
        info_y += 1
        
        visible_slice = lines[self._scroll_offset:self._scroll_offset + visible_lines - 1]
        for text, fg in visible_slice:
            console.print(content_x, info_y, text[:content_width], fg=fg)
            info_y += 1
        
        if max_offset > 0:
            footer = "More above/below" if 0 < self._scroll_offset < max_offset else (
                "More below" if self._scroll_offset == 0 else "More above"
            )
            console.print(content_x + 30, debug_y + window_height - 4, footer, fg=color.gray)
        
        instructions_y = debug_y + window_height - 4
        console.print(debug_x + 2, instructions_y,     "Arrow Keys: Move cursor", fg=color.light_gray)
        console.print(debug_x + 2, instructions_y + 1, "Ctrl+Up/Down, PgUp/PgDn", fg=color.light_gray)
        console.print(debug_x + 2, instructions_y + 2, "Wheel: Scroll info", fg=color.cyan)
        console.print(debug_x + 2, instructions_y + 3, "F5/Enter/ESC: Exit", fg=color.light_gray)

    def ev_mousewheel(self, event: tcod.event.MouseWheel) -> Optional[ActionOrHandler]:
        if event.y > 0:
            self._scroll_offset = max(0, self._scroll_offset - 3)
        elif event.y < 0:
            self._scroll_offset += 3
        return self

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        if event.sym in (tcod.event.KeySym.ESCAPE, tcod.event.KeySym.RETURN, tcod.event.KeySym.F5):
            return MainGameEventHandler(self.engine)
        if event.mod & (tcod.event.Modifier.LCTRL | tcod.event.Modifier.RCTRL):
            if event.sym == tcod.event.KeySym.UP:
                self._scroll_offset = max(0, self._scroll_offset - 3)
                return self
            if event.sym == tcod.event.KeySym.DOWN:
                self._scroll_offset += 3
                return self
        if event.sym == tcod.event.KeySym.PAGEUP:
            self._scroll_offset = max(0, self._scroll_offset - 8)
            return self
        if event.sym == tcod.event.KeySym.PAGEDOWN:
            self._scroll_offset += 8
            return self
        if event.sym == tcod.event.KeySym.HOME:
            self._scroll_offset = 0
            return self
        if event.sym == tcod.event.KeySym.END:
            self._scroll_offset = 10_000
            return self
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
        sounds.play_ui_move_sound()
        # Handle escape - go back
        if key == tcod.event.KeySym.ESCAPE:
            return self._handle_back()
    def on_render(self, console: tcod.Console) -> None:
        # If we have a parent handler, let it render the background
        if self.parent_handler is not None and hasattr(self.parent_handler, 'on_render'):
            self.parent_handler.on_render(console)



        text = """Movement:
    WASD: Move Cardinally
    Numpad: Move Ordinally
    R Click: Auto-move to destination

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
    F1: Lag Profiler
    F2: Player Debug
    F3: Entity/Tile Debug
    F5: Material Inspector
    F10: Debug Console
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
        
        for trait_name in player.level.traits:
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
        self.engine.render_ui(console)


class Settings(BaseEventHandler):
    """Settings menu handler - allows adjusting game settings."""
    
    TITLE = "Settings"
    
    def __init__(self, parent_handler=None):
        self.engine = getattr(parent_handler, "engine", None)
        # Always read/write the user-writable copy (next to exe in prod, project folder in dev)
        try:
            import sys as _sys
            import os as _os
            _base = _os.path.dirname(_sys.executable) if getattr(_sys, "frozen", False) else _os.path.dirname(_os.path.abspath(__file__))
            self.settings_file = _os.path.join(_base, "json", "settings.json")
        except Exception:
            self.settings_file = "json/settings.json"
        self.settings_data = self._load_settings()
        
        self.categories = {
            #"Controls": {
            #    "Options": [''],
            #    "SelectedIndex": 0,
            #    "json_key": None  # No JSON key since this opens a sub-menu
            #},
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
            "Light Flicker:": {
                "Options": ["On", "Off"],
                "SelectedIndex": 0 if self.settings_data.get("light_flicker", True) else 1,
                "json_key": "light_flicker"
            },
            "Scanlines:": {
                "Options": ["On", "Off"],
                "SelectedIndex": 0 if self.settings_data.get("crt_scanlines", True) else 1,
                "json_key": "crt_scanlines"
            },
            "Vignette:": {
                "Options": ["On", "Off"],
                "SelectedIndex": 0 if self.settings_data.get("crt_vignette", True) else 1,
                "json_key": "crt_vignette"
            },
            "Bloom:": {
                "Options": ["On", "Off"],
                "SelectedIndex": 0 if self.settings_data.get("crt_bloom", True) else 1,
                "json_key": "crt_bloom"
            },
            "Chromatic Aberration:": {
                "Options": ["On", "Off"],
                "SelectedIndex": 0 if self.settings_data.get("crt_ca", True) else 1,
                "json_key": "crt_ca"
            },
            "Barrel Curvature:": {
                "Options": ["On", "Off"],
                "SelectedIndex": 0 if self.settings_data.get("crt_curvature", True) else 1,
                "json_key": "crt_curvature"
            },
            "Voice Blips:": {
                "Options": ["On", "Off"],
                "SelectedIndex": 0 if self.settings_data.get("voice_blips", True) else 1,
                "json_key": "voice_blips"
            },
            "Log Console:": {
                "Options": ["Off", "On"],
                "SelectedIndex": 1 if self.settings_data.get("show_console", False) else 0,
                "json_key": "show_console"
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
                    #print(self.selected_option)
                    sounds.play_ui_move_sound()
                return

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[ActionOrHandler]:
        key = event.button
        print(key)
        sounds.play_ui_move_sound()
        # Handle left/right for toggling options
        if key in (tcod.event.MouseButton.LEFT, tcod.event.MouseButton.RIGHT):
            selected_category_key = self.category_keys[self.selected_option]
            #print(selected_category_key)
            if selected_category_key == "Back":
                #print("HANDLING BACK")
                return self._handle_back()
            elif selected_category_key != "Back" and selected_category_key in self.categories:
                category_data = self.categories[selected_category_key]
                num_options = len(category_data["Options"])
                
                if key == tcod.event.MouseButton.LEFT:
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
                
                # Update CRT filter toggles live
                if category_data.get("json_key", "").startswith("crt_"):
                    try:
                        from __main__ import reload_crt_settings
                        reload_crt_settings()
                    except Exception:
                        pass

                # Toggle console visibility live
                if category_data.get("json_key") == "show_console":
                    try:
                        import ctypes
                        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                        if hwnd:
                            ctypes.windll.user32.ShowWindow(hwnd, 1 if category_data["SelectedIndex"] == 1 else 0)
                    except Exception:
                        pass

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
                
                # Update CRT filter toggles live
                if category_data.get("json_key", "").startswith("crt_"):
                    try:
                        from __main__ import reload_crt_settings
                        reload_crt_settings()
                    except Exception:
                        pass
                

    def render_faded(self, console: tcod.Console, menu_x: int = None, menu_y: int = None, menu_width: int = None, menu_height: int = None) -> None:
        _fade_console_background(console, menu_x, menu_y, menu_width, menu_height)

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
                    elif category_key == "Light Flicker:":
                        self.settings_data[json_key] = (selected_index == 0)  # True for On
                    elif json_key and json_key.startswith("crt_"):
                        self.settings_data[json_key] = (selected_index == 0)  # True for On
                    elif json_key == "voice_blips":
                        self.settings_data[json_key] = (selected_index == 0)  # True for On
                    elif json_key == "show_console":
                        self.settings_data[json_key] = (selected_index == 1)  # True for On
            
            # Write to file with proper JSON format, preserving lighting_mode and other non-UI settings
            import os as _os
            _os.makedirs(_os.path.dirname(_os.path.abspath(self.settings_file)), exist_ok=True)
            with open(self.settings_file, 'w') as f:
                f.write("{\n")
                f.write("    // Display settings\n")
                f.write(f'    "fullscreen": {json.dumps(self.settings_data.get("fullscreen", False))},\n')
                #f.write(f'    "ambient_audio": {json.dumps(self.settings_data.get("ambient_audio", 50))},\n')
                f.write(f'    "audio": {json.dumps(self.settings_data.get("audio", 50))},\n')
                f.write("    // Lighting settings\n")
                f.write(f'    "lighting_mode": {json.dumps(self.settings_data.get("lighting_mode", "gpu"))},\n')
                f.write("    // CRT filter settings\n")
                f.write(f'    "crt_scanlines": {json.dumps(self.settings_data.get("crt_scanlines", True))},\n')
                f.write(f'    "crt_vignette": {json.dumps(self.settings_data.get("crt_vignette", True))},\n')
                f.write(f'    "crt_bloom": {json.dumps(self.settings_data.get("crt_bloom", True))},\n')
                f.write(f'    "crt_ca": {json.dumps(self.settings_data.get("crt_ca", True))},\n')
                f.write(f'    "crt_curvature": {json.dumps(self.settings_data.get("crt_curvature", True))},\n')
                f.write(f'    "light_flicker": {json.dumps(self.settings_data.get("light_flicker", True))},\n')
                f.write("    // Lighting settings\n")
                f.write(f'    "shadow_softness": {json.dumps(self.settings_data.get("shadow_softness", 0.2))},\n')
                f.write(f'    "modern_gl_lightmap_unified": {json.dumps(self.settings_data.get("modern_gl_lightmap_unified", False))},\n')
                f.write("    // Audio settings\n")
                f.write(f'    "voice_blips": {json.dumps(self.settings_data.get("voice_blips", True))},\n')
                f.write("    // Debug settings\n")
                f.write(f'    "show_console": {json.dumps(self.settings_data.get("show_console", False))}\n')
                f.write("}\n")
        except Exception:
            # If saving fails, just continue - don't crash the game
            pass

    def _handle_back(self) -> Optional[ActionOrHandler]:
        """Handle returning to previous handler (main menu)."""
        if self.parent_handler is not None:
            return self.parent_handler
        else:
            return None  # Fallback - should not happen in practice

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[ActionOrHandler]:
        key = event.sym
        sounds.play_ui_move_sound()
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
                
                # Update CRT filter toggles live
                if category_data.get("json_key", "").startswith("crt_"):
                    try:
                        from __main__ import reload_crt_settings
                        reload_crt_settings()
                    except Exception:
                        pass

                # Toggle console visibility live
                if category_data.get("json_key") == "show_console":
                    try:
                        import ctypes
                        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                        if hwnd:
                            ctypes.windll.user32.ShowWindow(hwnd, 1 if category_data["SelectedIndex"] == 1 else 0)
                    except Exception:
                        pass

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
                
                # Update CRT filter toggles live
                if category_data.get("json_key", "").startswith("crt_"):
                    try:
                        from __main__ import reload_crt_settings
                        reload_crt_settings()
                    except Exception:
                        pass
                
        return None  # Stay in settings menu


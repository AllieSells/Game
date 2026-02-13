"""
ASCII Equipment Interface

A visual equipment interface that shows a body diagram with selectable slots.
"""

from __future__ import annotations
from typing import Optional, Dict, List, Tuple, TYPE_CHECKING

import tcod
import color
from equipment_types import EquipmentType
from input_handlers import AskUserEventHandler
from render_functions import MenuRenderer
import actions

if TYPE_CHECKING:
    from engine import Engine
    from entity import Item


class EquipmentSlot:
    """Represents a visual equipment slot on the body diagram."""
    
    def __init__(self, name: str, x: int, y: int, equipment_types: List[EquipmentType], 
                 char: str = "○", equipped_char: str = "●"):
        self.name = name
        self.x = x
        self.y = y
        self.equipment_types = equipment_types
        self.char = char  # Empty slot character
        self.equipped_char = equipped_char  # Equipped slot character
    
    def get_equipped_item(self, equipment) -> Optional[Item]:
        """Get the item equipped in this slot."""
        for eq_type in self.equipment_types:
            if eq_type == EquipmentType.WEAPON or eq_type == EquipmentType.SHIELD:
                # Map UI slot names to body part names
                if self.name == "R.Hand":
                    hand_name = "right hand"
                elif self.name == "L.Hand": 
                    hand_name = "left hand"
                else:
                    # For other slots that might handle weapons/shields, check all hands
                    for item in equipment.grasped_items.values():
                        if (hasattr(item, 'equippable') and item.equippable and 
                            item.equippable.equipment_type == eq_type):
                            return item
                    return None
                
                # Check specific hand for this slot
                if hand_name in equipment.grasped_items:
                    item = equipment.grasped_items[hand_name]
                    if (hasattr(item, 'equippable') and item.equippable and 
                        item.equippable.equipment_type == eq_type):
                        return item
                return None
            else:
                # Check equipped_items for other equipment types
                return equipment.equipped_items.get(eq_type.name)
        return None


class EquipmentUI(AskUserEventHandler):
    """Simple list-based equipment interface."""
    
    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.selected_slot = 0
        self.selected_item = 0  # For cycling through items
        self.slots = self._create_equipment_slots()
        
        # Available items for equipping
        self.available_items = [item for item in engine.player.inventory.items 
                              if hasattr(item, 'equippable') and item.equippable]
    
    def _create_equipment_slots(self) -> List[EquipmentSlot]:
        """Create equipment slots for list display."""
        return [
            EquipmentSlot("R.Hand", 0, 0, [EquipmentType.WEAPON, EquipmentType.SHIELD], "o", "•"),
            EquipmentSlot("L.Hand", 0, 1, [EquipmentType.WEAPON, EquipmentType.SHIELD], "o", "•"), 
            EquipmentSlot("Head", 0, 2, [EquipmentType.HELMET], "o", "•"),
            EquipmentSlot("Torso", 0, 3, [EquipmentType.ARMOR], "o", "•"),
            EquipmentSlot("L.Arm", 0, 4, [EquipmentType.GAUNTLETS], "o", "•"),
            EquipmentSlot("R.Arm", 0, 5, [EquipmentType.GAUNTLETS], "o", "•"),
            EquipmentSlot("L.Leg", 0, 6, [EquipmentType.LEGGINGS], "o", "•"),
            EquipmentSlot("R.Leg", 0, 7, [EquipmentType.LEGGINGS], "o", "•"),
            EquipmentSlot("L.Foot", 0, 8, [EquipmentType.BOOTS], "o", "•"),
            EquipmentSlot("R.Foot", 0, 9, [EquipmentType.BOOTS], "o", "•"),
            EquipmentSlot("Back", 0, 10, [EquipmentType.BACKPACK], "o", "•"),
        ]
    
    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)
        
        # Calculate smaller window size and position
        window_width = 65
        window_height = 20
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2
        
        # Draw window frame
        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "Equipment")
        
        # Draw equipment slots list
        self._draw_slots_list(console, x, y, window_width, window_height)
        
        # Draw available items list
        self._draw_items_list(console, x, y, window_width, window_height)
        
        # Instructions
        instructions = [
            "[↑↓] Navigate slots  [←→] Navigate items  [Space] Equip",
            "[Del] Unequip  [Esc] Exit"
        ]
        
        for i, instruction in enumerate(instructions):
            console.print(
                x + 2, y + window_height - 3 + i,
                instruction,
                fg=color.light_gray, bg=(45, 35, 25)
            )
    
    def _draw_slots_list(self, console: tcod.Console, base_x: int, base_y: int,
                        window_width: int, window_height: int) -> None:
        """Draw equipment slots as a simple list."""
        from text_utils import print_colored_text_with_bg
        
        list_x = base_x + 3
        list_y = base_y + 3
        
        for i, slot in enumerate(self.slots):
            equipped_item = slot.get_equipped_item(self.engine.player.equipment)
            is_disabled = self._is_slot_disabled(slot)
            
            # Choose colors based on selection, equipment status, and injury
            if is_disabled:
                fg_color = color.red
                bg_color = (45, 35, 25)
                marker = "  "
                if i == self.selected_slot:
                    fg_color = color.white
                    bg_color = (80, 60, 30)
                    marker = "> "
            elif i == self.selected_slot:
                fg_color = color.white
                bg_color = (80, 60, 30)
                marker = "> "
            elif equipped_item:
                fg_color = color.white
                bg_color = (45, 35, 25)
                marker = "  "
            else:
                fg_color = color.white
                bg_color = (45, 35, 25) 
                marker = "  "
            
            # Determine HP color
            slot_hp = self._get_slot_hp(slot)
            if slot_hp <= 0:
                part_color = color.dark_red
            elif slot_hp < 30:
                part_color = color.red
            elif slot_hp < 70:
                part_color = color.yellow
            else:
                part_color = color.green
            
            # Build text parts for colored printing
            slot_char = slot.equipped_char if equipped_item else slot.char
            text_parts = [
                (f"{marker}{slot_char}{slot.name:6} [", fg_color),
                (f"{slot_hp:>3}%", part_color),
                ("]", fg_color)
            ]
            
            if equipped_item:
                item_name = equipped_item.name[:20]  # Longer truncation for wider window
                text_parts.append((":", fg_color))
                text_parts.append((item_name, equipped_item.rarity_color))
            
            print_colored_text_with_bg(console, list_x, list_y + i, text_parts, bg_color)
    
    def _draw_items_list(self, console: tcod.Console, base_x: int, base_y: int,
                        window_width: int, window_height: int) -> None:
        """Draw list of available items for the selected slot."""
        from text_utils import print_colored_text_with_bg
        
        if not self.slots:
            return
            
        selected_slot = self.slots[self.selected_slot]
        compatible_items = self._get_compatible_items(selected_slot)
        
        # Items list area (right side of window, with more space)
        list_x = base_x + 40
        list_y = base_y + 2
        max_items_width = window_width - 42  # Leave room on the right
        
        console.print(list_x, list_y, "Available Items:", fg=color.yellow, bg=(45, 35, 25))
        list_y += 1
        
        # Show compatible items
        if not compatible_items:
            console.print(list_x, list_y, "None", fg=color.gray, bg=(45, 35, 25))
            return
        
        # Clamp selected item to valid range
        self.selected_item = max(0, min(self.selected_item, len(compatible_items) - 1))
        
        # Draw items without cap, scrolling if needed
        start_index = max(0, self.selected_item - 8)  # Keep selection visible, show ~9 items
        
        for display_i, i in enumerate(range(start_index, len(compatible_items))):
            if display_i >= window_height - 7:  # Respect window height
                break
            
            item = compatible_items[i]
            is_selected = i == self.selected_item
            bg_color = (80, 60, 30) if is_selected else (45, 35, 25)
            marker = "> " if is_selected else "  "
            
            # Check if item is equipped and add (e) marker
            equipped_marker = " (e)" if self._is_item_equipped(item) else ""
            item_name = item.name[:max_items_width - 4] + equipped_marker  # Leave room for marker
            
            # Build text parts with rarity color for item name
            text_parts = [
                (marker, color.white if not is_selected else color.white),
                (item_name, item.rarity_color)
            ]
            
            print_colored_text_with_bg(console, list_x, list_y + display_i, text_parts, bg_color)
    
    def _get_compatible_items(self, slot: EquipmentSlot) -> List[Item]:
        """Get items that can be equipped in the given slot, including item currently in THIS slot."""
        compatible = []
        currently_equipped_in_slot = slot.get_equipped_item(self.engine.player.equipment)
        
        for item in self.available_items:
            if item.equippable.equipment_type in slot.equipment_types:
                # Always include the item currently equipped in THIS specific slot
                if item == currently_equipped_in_slot:
                    compatible.append(item)
                    continue
                
                # Skip items that are equipped in OTHER slots
                if self._is_item_equipped(item):
                    continue
                    
                can_equip, _ = self.engine.player.equipment.can_equip_item(item)
                if can_equip:
                    compatible.append(item)
        
        # Sort items: unequipped items first, item currently in this slot last
        compatible.sort(key=lambda item: item == currently_equipped_in_slot)
        return compatible
    
    def _is_item_equipped(self, item: Item) -> bool:
        """Check if an item is currently equipped in any slot."""
        equipment = self.engine.player.equipment
        return (item in equipment.grasped_items.values() or
                item in equipment.equipped_items.values() or
                item in equipment.body_part_coverage.values())

    def _get_slot_hp(self, slot: EquipmentSlot) -> int:
        """"Returns the limb HP ratio associated with a slot, default 100."""
        if not hasattr(self.engine.player, 'body_parts') or not self.engine.player.body_parts:
            return 100
        
        # Map slot names to body part types
        slot_to_body_part = {
            "L.Hand": "LEFT_HAND",
            "R.Hand": "RIGHT_HAND", 
            "L.Arm": "LEFT_ARM",
            "R.Arm": "RIGHT_ARM",
            "L.Leg": "LEFT_LEG",
            "R.Leg": "RIGHT_LEG",
            "L.Foot": "LEFT_FOOT",
            "R.Foot": "RIGHT_FOOT",
            "Head": "HEAD",
            "Torso": "TORSO",
            "Back": "TORSO"  # Back slot uses torso for injury check
        }

        body_part_name = slot_to_body_part.get(slot.name)
        if not body_part_name:
            return 100

        # Find the body part
        from components.body_parts import BodyPartType
        try:
            part_type = BodyPartType[body_part_name]
            if part_type in self.engine.player.body_parts.body_parts:
                part = self.engine.player.body_parts.body_parts[part_type]
                hp_ratio = int(self.engine.player.body_parts.get_part_health_ratio(part) * 100)
                return hp_ratio
        except (KeyError, AttributeError):
            pass
        return 100

    
    def _is_slot_disabled(self, slot: EquipmentSlot) -> bool:
        """Check if a slot is disabled due to injury."""
        if not hasattr(self.engine.player, 'body_parts') or not self.engine.player.body_parts:
            return False
        
        # Map slot names to body part types
        slot_to_body_part = {
            "L.Hand": "LEFT_HAND",
            "R.Hand": "RIGHT_HAND", 
            "L.Arm": "LEFT_ARM",
            "R.Arm": "RIGHT_ARM",
            "L.Leg": "LEFT_LEG",
            "R.Leg": "RIGHT_LEG",
            "L.Foot": "LEFT_FOOT",
            "R.Foot": "RIGHT_FOOT",
            "Head": "HEAD",
            "Torso": "TORSO",
            "Back": "TORSO"  # Back slot uses torso for injury check
        }
        
        body_part_name = slot_to_body_part.get(slot.name)
        if not body_part_name:
            return False
        
        # Find the body part
        from components.body_parts import BodyPartType
        try:
            part_type = BodyPartType[body_part_name]
            if part_type in self.engine.player.body_parts.body_parts:
                part = self.engine.player.body_parts.body_parts[part_type]
                # Slot is disabled if body part is destroyed or severely wounded (≤ 25% HP)
                damage_ratio = part.current_hp / part.max_hp
                return damage_ratio <= 0.0
        except (KeyError, AttributeError):
            pass
        
        return False
    
    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[AskUserEventHandler]:
        key = event.sym
        
        # Slot navigation
        if key == tcod.event.KeySym.UP:
            self.selected_slot = max(0, self.selected_slot - 1)
            self.selected_item = 0  # Reset item selection when changing slots
            return None
        elif key == tcod.event.KeySym.DOWN:
            self.selected_slot = min(len(self.slots) - 1, self.selected_slot + 1)
            self.selected_item = 0  # Reset item selection when changing slots
            return None
        
        # Item navigation
        elif key == tcod.event.KeySym.LEFT:
            if self.slots:
                compatible_items = self._get_compatible_items(self.slots[self.selected_slot])
                if compatible_items:
                    self.selected_item = (self.selected_item - 1) % len(compatible_items)
            return None
        elif key == tcod.event.KeySym.RIGHT:
            if self.slots:
                compatible_items = self._get_compatible_items(self.slots[self.selected_slot])
                if compatible_items:
                    self.selected_item = (self.selected_item + 1) % len(compatible_items)
            return None
        
        # Equip/Unequip selected item
        elif key == tcod.event.KeySym.RETURN or key == tcod.event.KeySym.KP_ENTER or key == tcod.event.KeySym.SPACE:
            return self._handle_equip_selected()
        
        # Exit
        elif key == tcod.event.KeySym.ESCAPE:
            from input_handlers import MainGameEventHandler
            return MainGameEventHandler(self.engine)
        
        return super().ev_keydown(event)
    
    def _handle_equip_selected(self) -> Optional[AskUserEventHandler]:
        """Equip or unequip the currently selected item."""
        if not self.slots:
            return None
            
        selected_slot = self.slots[self.selected_slot]
        
        # Check if slot is disabled due to injury
        if self._is_slot_disabled(selected_slot):
            try:
                self.engine.player.gamemap.engine.message_log.add_message(
                    f"Cannot use {selected_slot.name} - too injured!",
                    color.impossible
                )
            except:
                pass
            return None  # Stay in equipment UI
        
        compatible_items = self._get_compatible_items(selected_slot)
        currently_equipped_in_slot = selected_slot.get_equipped_item(self.engine.player.equipment)
        
        if compatible_items and self.selected_item < len(compatible_items):
            selected_item = compatible_items[self.selected_item]
            
            # Check if selected item is currently equipped in THIS slot
            if selected_item == currently_equipped_in_slot:
                # Unequip the item
                if selected_slot.name == "L.Hand":
                    self.engine.player.equipment.unequip_from_specific_hand("left hand")
                elif selected_slot.name == "R.Hand":
                    self.engine.player.equipment.unequip_from_specific_hand("right hand")
                else:
                    self.engine.player.equipment.unequip_item(selected_item, add_message=True)
            else:
                # Equip the item
                if selected_slot.name == "L.Hand":
                    self.engine.player.equipment.equip_to_specific_hand(selected_item, "left hand")
                elif selected_slot.name == "R.Hand":
                    self.engine.player.equipment.equip_to_specific_hand(selected_item, "right hand")
                else:
                    action = actions.EquipAction(self.engine.player, selected_item)
                    action.perform()
        
        return None  # Stay in equipment UI
    
    def _handle_unequip(self) -> Optional[AskUserEventHandler]:
        """Unequip the item in the selected slot."""
        if not self.slots:
            return None
            
        selected_slot = self.slots[self.selected_slot]
        
        # Check if slot is disabled due to injury
        if self._is_slot_disabled(selected_slot):
            try:
                self.engine.player.gamemap.engine.message_log.add_message(
                    f"Cannot access {selected_slot.name} - too injured!",
                    color.impossible
                )
            except:
                pass
            return None  # Stay in equipment UI
            
        equipped_item = selected_slot.get_equipped_item(self.engine.player.equipment)
        
        if equipped_item:
            # Handle specific slot targeting for hands
            if selected_slot.name == "L.Hand":
                self.engine.player.equipment.unequip_from_specific_hand("left hand")
            elif selected_slot.name == "R.Hand":
                self.engine.player.equipment.unequip_from_specific_hand("right hand")
            else:
                # Use standard unequip for other slots
                self.engine.player.equipment.unequip_item(equipped_item, add_message=True)
        
        return None  # Stay in equipment UI
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
            if eq_type == EquipmentType.WEAPON:
                # For weapon slots, distinguish between left and right hand strictly
                if self.name == "L.Hand":
                    # Left hand ONLY shows offhand slot, nothing else
                    return equipment.offhand if equipment.offhand else None
                elif self.name == "R.Hand":
                    # Right hand ONLY shows main weapon slot
                    return equipment.weapon
                else:
                    # Generic weapon slot (shouldn't happen with current setup)
                    return equipment.weapon
            elif eq_type == EquipmentType.SHIELD:
                # Shields always go to left hand (offhand)
                if (equipment.offhand and hasattr(equipment.offhand, 'equippable') and 
                    hasattr(equipment.offhand.equippable, 'equipment_type') and 
                    equipment.offhand.equippable.equipment_type == EquipmentType.SHIELD):
                    if self.name == "L.Hand":
                        return equipment.offhand
                return None
            elif eq_type == EquipmentType.ARMOR:
                return equipment.armor
            elif eq_type == EquipmentType.HELMET:
                return equipment.equipped_items.get("HELMET")
            elif eq_type == EquipmentType.BOOTS:
                return equipment.equipped_items.get("BOOTS")
            elif eq_type == EquipmentType.GAUNTLETS:
                return equipment.equipped_items.get("GAUNTLETS")
            elif eq_type == EquipmentType.LEGGINGS:
                return equipment.equipped_items.get("LEGGINGS")
            elif eq_type == EquipmentType.BACKPACK:
                return equipment.backpack
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
            EquipmentSlot("R.Hand", 0, 0, [EquipmentType.WEAPON, EquipmentType.SHIELD], "○", "●"),
            EquipmentSlot("L.Hand", 0, 1, [EquipmentType.WEAPON, EquipmentType.SHIELD], "○", "●"), 
            EquipmentSlot("Head", 0, 2, [EquipmentType.HELMET], "○", "●"),
            EquipmentSlot("Torso", 0, 3, [EquipmentType.ARMOR], "○", "●"),
            EquipmentSlot("L.Arm", 0, 4, [EquipmentType.GAUNTLETS], "○", "●"),
            EquipmentSlot("R.Arm", 0, 5, [EquipmentType.GAUNTLETS], "○", "●"),
            EquipmentSlot("L.Leg", 0, 6, [EquipmentType.LEGGINGS], "○", "●"),
            EquipmentSlot("R.Leg", 0, 7, [EquipmentType.LEGGINGS], "○", "●"),
            EquipmentSlot("L.Foot", 0, 8, [EquipmentType.BOOTS], "○", "●"),
            EquipmentSlot("R.Foot", 0, 9, [EquipmentType.BOOTS], "○", "●"),
            EquipmentSlot("Back", 0, 10, [EquipmentType.BACKPACK], "○", "●"),
        ]
    
    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)
        
        # Calculate smaller window size and position
        window_width = 65
        window_height = 20
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2
        
        # Draw window frame
        self._draw_parchment_background(console, x, y, window_width, window_height)
        self._draw_ornate_border(console, x, y, window_width, window_height, "Equipment")
        
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
                    bg_color = (80, 60, 30)
                    marker = "> "
            elif i == self.selected_slot:
                fg_color = color.cyan
                bg_color = (80, 60, 30)
                marker = "> "
            elif equipped_item:
                fg_color = color.green 
                bg_color = (45, 35, 25)
                marker = "  "
            else:
                fg_color = color.white
                bg_color = (45, 35, 25) 
                marker = "  "
            
            # Draw slot entry
            slot_char = slot.equipped_char if equipped_item else slot.char
            slot_text = f"{marker}{slot_char} {slot.name:<8}"
            
            # Add equipped item name or injury status
            if is_disabled:
                slot_text += ": Too injured to use"
            elif equipped_item:
                item_name = equipped_item.name[:20]  # Longer truncation for wider window
                slot_text += f": {item_name}"
            
            console.print(list_x, list_y + i, slot_text, fg=fg_color, bg=bg_color)
    
    def _draw_items_list(self, console: tcod.Console, base_x: int, base_y: int,
                        window_width: int, window_height: int) -> None:
        """Draw list of available items for the selected slot."""
        if not self.slots:
            return
            
        selected_slot = self.slots[self.selected_slot]
        compatible_items = self._get_compatible_items(selected_slot)
        
        # Items list area (right side of window)
        list_x = base_x + 35
        list_y = base_y + 3
        
        console.print(list_x, list_y, "Available Items:", fg=color.yellow, bg=(45, 35, 25))
        list_y += 2
        
        # Show compatible items
        if not compatible_items:
            console.print(list_x, list_y, "No items available", fg=color.gray, bg=(45, 35, 25))
            return
        
        # Clamp selected item to valid range
        self.selected_item = max(0, min(self.selected_item, len(compatible_items) - 1))
        
        for i, item in enumerate(compatible_items):
            if i >= 8:  # Limit items shown
                break
                
            item_color = color.cyan if i == self.selected_item else color.white
            marker = "> " if i == self.selected_item else "  "
            
            # Check if item is equipped and add (e) marker
            equipped_marker = " (e)" if self._is_item_equipped(item) else ""
            item_name = item.name[:22] + equipped_marker  # Shorter truncation to fit (e) marker
            
            console.print(list_x, list_y + i, f"{marker}{item_name}", 
                        fg=item_color, bg=(45, 35, 25))
    
    def _get_compatible_items(self, slot: EquipmentSlot) -> List[Item]:
        """Get items that can be equipped in the given slot, with equipped items sorted to bottom."""
        compatible = []
        for item in self.available_items:
            if item.equippable.equipment_type in slot.equipment_types:
                can_equip, _ = self.engine.player.equipment.can_equip_item(item)
                if can_equip or slot.get_equipped_item(self.engine.player.equipment) == item:
                    compatible.append(item)
        
        # Sort items: unequipped first, equipped last
        compatible.sort(key=lambda item: self._is_item_equipped(item))
        return compatible
    
    def _is_item_equipped(self, item: Item) -> bool:
        """Check if an item is currently equipped in any slot."""
        equipment = self.engine.player.equipment
        return (equipment.weapon == item or 
                equipment.offhand == item or
                equipment.armor == item or
                equipment.backpack == item or
                item in equipment.equipped_items.values())
    
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
                return damage_ratio <= 0.25
        except (KeyError, AttributeError):
            pass
        
        return False
    
    def _draw_parchment_background(self, console: tcod.Console, x: int, y: int, 
                                 width: int, height: int) -> None:
        """Draw parchment-style background."""
        for py in range(height):
            for px in range(width):
                console.rgb["bg"][x + px, y + py] = (45, 35, 25)
    
    def _draw_ornate_border(self, console: tcod.Console, x: int, y: int, 
                          width: int, height: int, title: str) -> None:
        """Draw ornate border with fantasy styling."""
        border_fg = (139, 105, 60)  # Bronze
        title_fg = (255, 215, 0)    # Gold
        bg = (45, 35, 25)           # Parchment background
        
        # Draw border
        console.draw_frame(x, y, width, height, fg=border_fg, bg=bg)
        
        # Ornate title
        title_decorated = f"✦ {title} ✦"
        title_start = x + (width - len(title_decorated)) // 2
        console.print(title_start, y, title_decorated, fg=title_fg, bg=bg)
    
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
                    self.selected_item = max(0, self.selected_item - 1)
            return None
        elif key == tcod.event.KeySym.RIGHT:
            if self.slots:
                compatible_items = self._get_compatible_items(self.slots[self.selected_slot])
                if compatible_items:
                    self.selected_item = min(len(compatible_items) - 1, self.selected_item + 1)
            return None
        
        # Equip selected item
        elif key == tcod.event.KeySym.RETURN or key == tcod.event.KeySym.KP_ENTER or key == tcod.event.KeySym.SPACE:
            return self._handle_equip_selected()
        
        # Unequip current item
        elif key == tcod.event.KeySym.DELETE:
            return self._handle_unequip()
        
        # Exit
        elif key == tcod.event.KeySym.ESCAPE:
            from input_handlers import MainGameEventHandler
            return MainGameEventHandler(self.engine)
        
        return super().ev_keydown(event)
    
    def _handle_equip_selected(self) -> Optional[AskUserEventHandler]:
        """Equip the currently selected item."""
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
        
        if compatible_items and self.selected_item < len(compatible_items):
            item_to_equip = compatible_items[self.selected_item]
            
            # Handle specific slot targeting for hands
            if selected_slot.name == "L.Hand" and item_to_equip.equippable.equipment_type == EquipmentType.WEAPON:
                # Force equip to offhand for left hand slot
                if self.engine.player.equipment.offhand != item_to_equip:
                    # If something is in offhand, swap it
                    if self.engine.player.equipment.offhand:
                        self.engine.player.equipment.unequip_item(self.engine.player.equipment.offhand, add_message=False)
                    # If item is in weapon slot, move it to offhand
                    if self.engine.player.equipment.weapon == item_to_equip:
                        self.engine.player.equipment.weapon = None
                        self.engine.player.equipment.grasped_items.discard(item_to_equip)
                    self.engine.player.equipment.offhand = item_to_equip
                    self.engine.player.equipment.grasped_items.add(item_to_equip)
                    self.engine.player.equipment._play_equip_sound(item_to_equip)
                    self.engine.player.equipment.equip_message(item_to_equip.name)
            elif selected_slot.name == "R.Hand" and item_to_equip.equippable.equipment_type == EquipmentType.WEAPON:
                # Force equip to weapon for right hand slot
                if self.engine.player.equipment.weapon != item_to_equip:
                    # If something is in weapon, swap it
                    if self.engine.player.equipment.weapon:
                        self.engine.player.equipment.unequip_item(self.engine.player.equipment.weapon, add_message=False)
                    # If item is in offhand slot, move it to weapon
                    if self.engine.player.equipment.offhand == item_to_equip:
                        self.engine.player.equipment.offhand = None
                        self.engine.player.equipment.grasped_items.discard(item_to_equip)
                    self.engine.player.equipment.weapon = item_to_equip
                    self.engine.player.equipment.grasped_items.add(item_to_equip)
                    self.engine.player.equipment._play_equip_sound(item_to_equip)
                    self.engine.player.equipment.equip_message(item_to_equip.name)
            else:
                # Standard equipping for other slots
                action = actions.EquipAction(self.engine.player, item_to_equip)
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
            # Handle specific hand slot unequipping
            if selected_slot.name == "L.Hand":
                if self.engine.player.equipment.offhand == equipped_item:
                    self.engine.player.equipment.unequip_item(equipped_item, add_message=True)
                elif self.engine.player.equipment.weapon == equipped_item and not self.engine.player.equipment.offhand:
                    self.engine.player.equipment.unequip_item(equipped_item, add_message=True)
            elif selected_slot.name == "R.Hand":
                if self.engine.player.equipment.weapon == equipped_item:
                    self.engine.player.equipment.unequip_item(equipped_item, add_message=True)
            else:
                # Standard unequipping for other slots
                self.engine.player.equipment.unequip_item(equipped_item, add_message=True)
        
        return None  # Stay in equipment UI
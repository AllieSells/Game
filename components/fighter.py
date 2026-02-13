from __future__ import annotations

from email.mime import base
from random import random as random_float
from typing import TYPE_CHECKING

import color
from components.base_component import BaseComponent
from render_order import RenderOrder

if TYPE_CHECKING:
    from entity import Actor

import sounds


class Fighter(BaseComponent):

    parent: Actor

    def __init__(self, hp: int, base_defense: int, base_power: int, leave_corpse: bool = True):
        self.max_hp = hp
        self._hp = hp
        self.base_defense = base_defense
        self.base_power = base_power
        # Whether this entity should leave a corpse when it dies.
        # Set to False for ephemeral creatures like Shades.
        self.leave_corpse = leave_corpse

    @property
    def hp(self) -> int:
        return self._hp
    
    @hp.setter
    def hp(self, value: int) -> None:
        self._hp = max(0, min(value, self.max_hp))  # Clamp the value between 0 and max_hp
        if self._hp == 0 and self.parent.ai:
            print("why not die")
            self.die()

    @property
    def defense(self) -> int:
        return self.base_defense + self.defense_bonus
    
    @property
    def power(self) -> int:
        return self.base_power + self.power_bonus

    @property
    def defense_bonus(self) -> int:
        if self.parent.equipment:
            return self.parent.equipment.defense_bonus
        else:
            return 0

    @property
    def power_bonus(self) -> int:
        if self.parent.equipment:
            return self.parent.equipment.power_bonus
        else:
            return 0
    
    def die(self) -> None:
        sounds.play_death_sound()
        
        # Create large blood pool when entity dies
        if hasattr(self.parent, 'gamemap') and hasattr(self.parent.gamemap, 'liquid_system'):
            from liquid_system import LiquidType
            # Create larger blood pool on death
            self.parent.gamemap.liquid_system.create_splash(
                self.parent.x, self.parent.y,
                LiquidType.BLOOD,
                radius=1,  # Larger radius for death
                max_depth=1  # Maximum blood depth
            )
        
        if self.engine.player is self.parent:
            death_message = "YOU DIED IDIOT"
            death_message_color = color.player_die
        else:
            death_message = f"{self.parent.name} is dead! Not big surpise."
            death_message_color = color.enemy_die
        # If configured not to leave a corpse (ephemeral creatures), remove
        # the entity from the map and award XP without creating a corpse.
        if not getattr(self, "leave_corpse", True):
            try:
                self.engine.message_log.add_message(death_message, death_message_color)
            except Exception:
                pass

            try:
                gm = self.parent.gamemap
                if hasattr(gm, "entities") and self.parent in gm.entities:
                    try:
                        gm.entities.remove(self.parent)
                    except Exception:
                        try:
                            gm.entities.discard(self.parent)
                        except Exception:
                            pass
            except Exception:
                pass

            try:
                self.parent.ai = None
            except Exception:
                pass

            try:
                self.parent.blocks_movement = False
            except Exception:
                pass

            try:
                self.engine.player.level.add_xp(self.parent.level.xp_given)
            except Exception:
                pass

            return

        # Default death behavior: leave a corpse
        self.parent.char = "%"
        self.parent.color = (191, 0, 0)
        self.parent.blocks_movement = False
        self.parent.ai = None
        import text_utils
        self.parent.name = text_utils.red(f"This is the lifeless remains of {self.parent.name}")
        self.parent.render_order = RenderOrder.CORPSE
        self.parent.type = "Dead"

        # Make corpse lootable by creating a container with all their items
        from components.container import Container
        container = Container(capacity=26)  # Standard corpse capacity
        
        # Add all grasped items to the container
        if hasattr(self.parent, 'equipment') and self.parent.equipment:
            equipment = self.parent.equipment
            
            # Add all grasped items (weapons, shields, etc.)
            if hasattr(equipment, 'grasped_items'):
                for item in list(equipment.grasped_items.values()):
                    equipment.unequip_item(item, add_message=False)
                    container.add(item)
            
            # Add all equipped items (armor, boots, etc.)
            if hasattr(equipment, 'equipped_items'):
                for item in list(equipment.equipped_items.values()):
                    equipment.unequip_item(item, add_message=False)
                    container.add(item)
        
        # Add all inventory items to the container
        if hasattr(self.parent, 'inventory') and self.parent.inventory:
            for item in list(self.parent.inventory.items):
                self.parent.inventory.items.remove(item)
                container.add(item)
        
        # Attach container to corpse
        container.parent = self.parent
        self.parent.container = container
        
        # If another entity is already on this tile, find a nearby walkable tile for the corpse
        corpse_x = self.parent.x
        corpse_y = self.parent.y
        gamemap = self.parent.gamemap
        
        # Check if tile is crowded (has other entities besides the corpse)
        other_entities_here = [e for e in gamemap.entities if e.x == corpse_x and e.y == corpse_y and e != self.parent]
        if other_entities_here:
            # Find nearby walkable and transparent tile
            found_tile = False
            for radius in range(1, 6):  # Search up to 5 tiles away
                for dx in range(-radius, radius + 1):
                    for dy in range(-radius, radius + 1):
                        if abs(dx) != radius and abs(dy) != radius:
                            continue  # Only check perimeter of current radius
                        
                        check_x = corpse_x + dx
                        check_y = corpse_y + dy
                        
                        if gamemap.in_bounds(check_x, check_y):
                            tile = gamemap.tiles[check_x, check_y]
                            # Check if tile is walkable and transparent
                            if tile["walkable"] and tile["transparent"]:
                                # Check if no blocking entities are there
                                blocking = None
                                for entity in gamemap.entities:
                                    if entity.blocks_movement and entity.x == check_x and entity.y == check_y:
                                        blocking = entity
                                        break
                                
                                if not blocking:
                                    # Move corpse to this tile
                                    self.parent.place(check_x, check_y, gamemap)
                                    found_tile = True
                                    break
                    if found_tile:
                        break
                if found_tile:
                    break

        try:
            self.engine.message_log.add_message(death_message, death_message_color)
        except Exception:
            pass

        try:
            self.engine.player.level.add_xp(self.parent.level.xp_given)
        except Exception:
            pass

    def heal(self, amount: int) -> int:
        if self.hp == self.max_hp:
            return 0
        
        new_hp_value = self.hp + amount

        if new_hp_value > self.max_hp:
            new_hp_value = self.max_hp

        amount_recovered = new_hp_value - self.hp

        self.hp = new_hp_value
        
        # Also heal damaged body parts if entity has them (use actual amount recovered)
        body_parts_healed = self._heal_body_parts(amount_recovered)
        
        # Add body part healing message if any parts were healed
        if body_parts_healed and hasattr(self.parent, 'gamemap') and hasattr(self.parent.gamemap, 'engine'):
            try:
                self.parent.gamemap.engine.message_log.add_message(
                    f"Your injuries begin to mend.",
                    color.health_recovered
                )
            except:
                pass

        return amount_recovered
    
    def take_damage(self, amount: int, targeted_part=None) -> None:
        # Capture the entity name before it potentially dies/changes
        entity_name = self.parent.name
        
        # Always reduce overall HP first
        self.hp -= amount
        
        # If entity has body parts, damage them as well for tactical effects
        if hasattr(self.parent, 'body_parts') and self.parent.body_parts:
            if targeted_part:
                # Target specific body part
                damaged_part = self.parent.body_parts.damage_specific_part(targeted_part, amount)
            else:
                # Damage random part
                damaged_part = self.parent.body_parts.damage_random_part(amount)
            
            # Check if entity dies from body part destruction (in addition to HP loss)
            if not self.parent.body_parts.is_alive():
                self.hp = 0  # Force death from vital part destruction
            
            # Add detailed damage message for body parts (using original name)
            if (damaged_part and hasattr(self.parent, 'gamemap') and 
                hasattr(self.parent.gamemap, 'engine') and self.hp > 0):  # Only show if still alive
                part_name = damaged_part.name
                if damaged_part.is_destroyed:
                    message = f"{entity_name}'s {part_name} is destroyed!"
                    message_color = color.enemy_die
                else:
                    message = f"{entity_name}'s {part_name} is {damaged_part.damage_level_text}!"
                    message_color = color.health_recovered

                # Check if damaged limb should cause weapon dropping
                self._check_weapon_drop(damaged_part)
        
        # Add blood spilling when taking damage
        if hasattr(self.parent, 'gamemap') and hasattr(self.parent.gamemap, 'liquid_system'):
            from liquid_system import LiquidType
            # Create small blood splash for damage
            blood_amount = min(2, max(1, amount // 4))  # Less blood than melee
            self.parent.gamemap.liquid_system.create_splash(
                self.parent.x, self.parent.y,
                LiquidType.BLOOD,
                radius=1,  # Small radius
                max_depth=blood_amount
            )
        
        # Trigger damage indicator if this is the player
        if (hasattr(self.parent, 'gamemap') and 
            hasattr(self.parent.gamemap, 'engine') and
            self.parent is self.parent.gamemap.engine.player):
            self.parent.gamemap.engine.trigger_damage_indicator()
    
    def _check_weapon_drop(self, damaged_part) -> None:
        """Drop weapons if grasping limbs are severely wounded."""
        if not damaged_part.can_grasp or not hasattr(self.parent, 'equipment'):
            return
        
        # Drop weapons if hand/arm is severely wounded (≤ 25% HP) or destroyed
        damage_ratio = damaged_part.current_hp / damaged_part.max_hp

        check_drop = False
        if damage_ratio <= 0.5:
            if random_float() < 0.5:  # 50% chance to drop weapon if 50% or less
                check_drop = True
        if damage_ratio <= 0.25:
            check_drop = True
        
        if check_drop:
            # Drop any grasped items (tag-based system)
            self._drop_grasped_items(damaged_part)

    def _drop_grasped_items(self, damaged_part) -> None:
        """Drop items being grasped by a damaged body part."""
        equipment = self.parent.equipment
        
        # Check if the damaged part can actually grasp items
        if not damaged_part.can_grasp and "grasp" not in damaged_part.tags:
            return
        
        # Find items being held by this specific body part
        item_to_drop = equipment.grasped_items.get(damaged_part.name)
        
        # Only proceed if this part actually has an item
        if item_to_drop:
            # Unequip and drop to ground
            equipment.unequip_item(item_to_drop, add_message=False)
            
            # Remove from inventory to prevent duplication
            if hasattr(self.parent, 'inventory') and item_to_drop in self.parent.inventory.items:
                self.parent.inventory.items.remove(item_to_drop)
            
            item_to_drop.place(self.parent.x, self.parent.y, self.parent.gamemap)
            
            # Add message
            try:
                self.parent.gamemap.engine.message_log.add_message(
                    f"{self.parent.name} drops {item_to_drop.name} from their {damaged_part.name}!",
                    color.health_recovered
                )
            except:
                pass
    
    def _heal_body_parts(self, amount_recovered: int) -> bool:
        """Heal damaged body parts proportionally to the player's HP recovery."""
        if not hasattr(self.parent, 'body_parts') or not self.parent.body_parts:
            return False
        
        # Calculate healing ratio: portion of missing HP actually restored
        old_hp = self.hp - amount_recovered
        missing_hp = self.max_hp - old_hp
        healing_ratio = (amount_recovered / missing_hp) if missing_hp > 0 else 0
        
        parts_healed = False
        for part in self.parent.body_parts.body_parts.values():
            part_missing = part.max_hp - part.current_hp
            part_heal = int(part_missing * healing_ratio)
            if part_heal > 0:
                actual_healing = part.heal(part_heal)
                if actual_healing > 0:
                    parts_healed = True
        return parts_healed


from __future__ import annotations

from random import random as random_float
from typing import TYPE_CHECKING

import color
from components.base_component import BaseComponent
from render_order import RenderOrder

if TYPE_CHECKING:
    from entity import Actor

import sounds
import random
import gpu_stack


class Fighter(BaseComponent):

    parent: Actor

    def __init__(self, hp: int, base_defense: int, base_power: int, leave_corpse: bool = True, can_bleed: bool = True):
        self.max_hp = hp
        self._hp = hp
        self.base_defense = base_defense
        self.base_power = base_power
        # Whether this entity should leave a corpse when it dies.
        # Set to False for ephemeral creatures like Shades.
        self.leave_corpse = leave_corpse
        self.strength = 1
        self.dexterity = 1
        self.constitution = 1
        self.can_bleed = can_bleed  # By default, entities can bleed unless specified otherwise


    @property
    def hp(self) -> int:
        return self._hp
    
    @property
    def power(self) -> int:
        return self.base_power + self.power_bonus
    
    @property
    def defense(self) -> int:
        return self.base_defense

    @power.setter
    def power(self, value: int) -> None:
        self.base_power = max(0, value)  # Ensure power doesn't go negative
    
    @defense.setter
    def defense(self, value: int) -> None:
        self.base_defense = max(0, value)  # Ensure defense doesn't go negative
    
    @hp.setter
    def hp(self, value: int) -> None:
        self._hp = max(0, min(value, self.max_hp))  # Clamp the value between 0 and max_hp
        if self._hp == 0 and self.parent.ai:
            self.engine.debug_log(f"{self.parent.name} has 0 HP. Triggering death.", handler=self.__class__.__name__, event="DeathTrigger")
            self.die()

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
        
        if self.engine.player is self.parent:
            death_message = ""
            death_message_color = color.player_die
        else:
            death_message = f"The {self.parent.name.lower()} is dead."
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

            # Overall XP system phased out - traits provide progression now
            # try:
            #     self.engine.player.level.add_xp(self.parent.level.xp_given)
            # except Exception:
            #     pass

            return

        # Default death behavior: leave a corpse
        # Check if inventory has items
        if self.parent.inventory and self.parent.inventory.items:
            
            self.parent.char = random.choice([chr(0xE013), chr(0xE014), chr(0xE015)])
        else:
            self.parent.char = random.choice([chr(0xE010), chr(0xE011), chr(0xE012)])
        self.parent.color = (255, 255, 255)
        self.parent.blocks_movement = False
        self.parent.ai = None
        self.parent.name = f"Corpse of {self.parent.name}"
        self.parent.render_order = RenderOrder.CORPSE
        self.parent.type = "Dead"
        self.can_bleed = False

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

        # Overall XP system phased out - traits provide progression now
        # try:
        #     self.engine.player.level.add_xp(self.parent.level.xp_given)
        # except Exception:
        #     pass

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
        
        # Show particle and message whenever any HP was actually recovered
        if amount_recovered > 0 and hasattr(self.parent, 'gamemap') and hasattr(self.parent.gamemap, 'engine'):
            try:
                self.parent.gamemap.engine.animation_queue.append(gpu_stack.HealthParticle((self.parent.x, self.parent.y), self.parent))
            except Exception:
                pass
        if body_parts_healed and hasattr(self.parent, 'gamemap') and hasattr(self.parent.gamemap, 'engine'):
            try:
                self.parent.gamemap.engine.message_log.add_message(
                    "Your injuries begin to mend.",
                    color.light_green
                )
            except Exception:
                pass

        return amount_recovered
    
    def _guide_retaliate(self) -> None:
        """Fire a volley of Inflict Wounds spells at the player for daring to attack the Guide."""
        if getattr(self, '_retaliating', False):
            return
        self._retaliating = True
        try:
            guide = self.parent
            try:
                engine = self.engine
                player = engine.player
            except Exception:
                return

            engine.message_log.add_message(
                "The Guide regards you with infinite patience... then unleashes divine retribution!",
                color.dark_purple
            )
            from actions import SpellAction
            from components.spells import FireballSpell
            engine.execute_action(SpellAction(guide, FireballSpell(), target_xy=(player.x, player.y)), is_player_action=False)
        finally:
            self._retaliating = False

        
        

    def take_damage(self, amount: int, targeted_part=None, causes_bleeding: bool = True) -> None:
        # The Guide is invulnerable — retaliate against the player instead
        if getattr(self.parent, 'type', None) == 'Guide':
            self._guide_retaliate()
            return

        # Capture the entity name before it potentially dies/changes
        entity_name = self.parent.name


        if (entity_name == "Goblin" or entity_name == "Troll"):
            if random.random() < 0.1:
                self.parent.ai.say("hurt")

        
        # Reduce overall HP — body part damage is applied by actions.py before this call
        self.hp -= amount

        # Any real damage wakes sleeping actors.
        if amount > 0 and hasattr(self.parent, "effects"):
            removed_sleep = False
            remaining_effects = []
            for effect in self.parent.effects:
                effect_name = str(getattr(effect, "name", "")).strip().lower()
                if effect_name == "sleep":
                    removed_sleep = True
                    continue
                remaining_effects.append(effect)
            self.parent.effects = remaining_effects
            if removed_sleep and hasattr(self.parent, 'gamemap') and hasattr(self.parent.gamemap, 'engine'):
                engine = self.parent.gamemap.engine
                if self.parent is engine.player:
                    engine.message_log.add_message("You wake up!", color.light_gray)
                else:
                    engine.message_log.add_message(f"{self.parent.name} wakes up!", color.light_gray)

        # If a vital part was destroyed by the caller (actions.py), force death
        if hasattr(self.parent, 'body_parts') and self.parent.body_parts:
            if not self.parent.body_parts.is_alive():
                self.hp = 0
        
        # Add blood spilling when taking damage (only if causes_bleeding is True)
        if self.can_bleed:
            if (causes_bleeding and hasattr(self.parent, 'gamemap') and 
                hasattr(self.parent.gamemap, 'liquid_system')):
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
            if amount > 0:
                try:
                    from gpu_stack import DamageNumberParticle
                    self.parent.gamemap.engine.animation_queue.append(
                        DamageNumberParticle((self.parent.x, self.parent.y), amount, color=(220, 220, 0))
                    )
                except Exception:
                    pass
        elif amount > 0 and hasattr(self.parent, 'gamemap') and hasattr(self.parent.gamemap, 'engine'):
            # Spawn a floating damage number above the hit enemy
            try:
                from gpu_stack import DamageNumberParticle
                self.parent.gamemap.engine.animation_queue.append(
                    DamageNumberParticle((self.parent.x, self.parent.y), amount)
                )
            except Exception:
                pass

    def mitigate_incoming_damage(
        self,
        raw_damage: int,
        damage_multiplier: float = 1.0,
        targeted_part=None,
        armor_tags: list[str] | None = None,
    ) -> tuple[int, int]:
        """Apply target-side mitigation and return the final damage plus armor defense."""
        armor_defense = 0

        # Get defense for specific part
        if targeted_part:
            base_defense = targeted_part.protection + self.base_defense
            if self.parent.equipment:
                armor_defense = self.parent.equipment.get_defense_for_part(targeted_part.name)
        # Fallback to base defense
        else:
            base_defense = self.defense

        # Aggregate mitigation multipliers from effects that apply to this attack
        defense_multiplier = 1.0
        if hasattr(self.parent, 'effects'):
            for effect in self.parent.effects:
                if hasattr(effect, 'get_defense_multiplier'):
                    defense_multiplier *= effect.get_defense_multiplier()


        # Combine for total defense
        total_defense = (base_defense*defense_multiplier) + armor_defense

        print(total_defense)

        base_damage = raw_damage - total_defense
        mitigation_multiplier = 1.0

        if armor_tags:
            from proficiency_system import armor_profile

            mitigation_multiplier = armor_profile(self.parent, armor_tags).mitigation_multiplier

        

        mitigated_damage = max(0, int(base_damage * damage_multiplier * mitigation_multiplier))

        return mitigated_damage, armor_defense
        
    
    def _check_weapon_drop(self, damaged_part) -> None: # TODO
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
                    color.blue
                )
            except Exception:
                pass
    
    def _heal_body_parts(self, amount_recovered: int) -> bool:
        """Heal damaged body parts so they track the player's overall HP ratio.

        After any heal the player's current/max ratio is used as a floor:
        body parts can be more damaged than average (from a targeted hit) but
        cannot be less healthy than the player's overall condition.
        """
        if not hasattr(self.parent, 'body_parts') or not self.parent.body_parts:
            return False
        if amount_recovered <= 0:
            return False

        # Overall health ratio after this heal (e.g. 0.67 when at 20/30 HP)
        player_ratio = (self.hp / self.max_hp) if self.max_hp > 0 else 1.0

        parts_healed = False
        for part in self.parent.body_parts.body_parts.values():
            if part.current_hp >= part.max_hp:
                continue
            # Floor: part should be at least as healthy as the player overall
            target_hp = round(player_ratio * part.max_hp)
            if target_hp > part.current_hp:
                actual = part.heal(target_hp - part.current_hp)
                if actual > 0:
                    parts_healed = True
        return parts_healed


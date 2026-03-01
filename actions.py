from __future__ import annotations

from typing import Optional, Tuple, TYPE_CHECKING
import random

import color
import engine
import exceptions
import copy 

if TYPE_CHECKING:
    from engine import Engine
    from entity import Actor, Entity, Item
    from components.container import Container
    from components.body_parts import BodyPartType
else:
    # Runtime import for BodyPartType if needed
    try:
        from components.body_parts import BodyPartType
    except ImportError:
        BodyPartType = None


import sounds
import animations
import components.level
# Body part targeting modifiers (damage_modifier, hit_difficulty_modifier)
# hit_difficulty_modifier: Positive = easier to hit, negative = harder to hit


# Second value adds to base 85% hit chance, so a -20 would make it 65% base hit chance, while a +30 would make it 115% (capped at 100% in code)
BODY_PART_MODIFIERS = {
    "HEAD": (1.5, -50),    # 50% more damage to head, much harder to hit (35% base hit chance)
    "NECK": (1.5, -70),    # 30% more damage to neck, very hard to hit (15% base hit chance)
    "TORSO": (1.0, 15),    # Normal damage, easier to hit (large target) (100% base hit chance)
    "LEG": (0.9, -10),      # Slightly less damage, slightly harder to hit (75% base hit chance)
    "ARM": (0.9, -10),     # Slightly less damage, harder to hit (75% base hit chance)
    "HAND": (0.75, -35),    # Reduced damage, very hard to hit (50% base hit chance)
    "FOOT": (0.75, -35),    # Reduced damage, very hard to hit (50% base hit chance)
}

class Action:
    def __init__(self, entity: Actor) -> None:
        super().__init__()
        self.entity = entity

    @property
    def engine(self) -> Engine:
        return self.entity.gamemap.engine
    
    def perform(self) -> None:
        """Perform this action with the objects needed to determine its scope.
        
        `self.engine` is the scope this action is being performed in.

        `self.entity` is the object performing the action.

        This method must be overridden by Action subclasses.
        """
        raise NotImplementedError()

class InteractAction(Action):
    # Handles 
    def __init__(self, entity: Actor, dx: int = 0, dy: int = 0):
        super().__init__(entity)
        self.dx = dx
        self.dy = dy

    def perform(self):
        actor_location_x = self.entity.x
        actor_location_y = self.entity.y

        target_x = actor_location_x + self.dx
        target_y = actor_location_y + self.dy

        # Check for chest entity at the target location
        for ent in self.engine.game_map.entities:
            if hasattr(ent, "container") and ent.container and (
                ent.x == target_x and ent.y == target_y
            ):
                # Container found at target location
                container = ent.container
                is_corpse = getattr(ent, "type", None) == "Dead"
                
                if len(container.items) == 0 and is_corpse:
                    empty_msg = "There is nothing left to loot."
                    raise exceptions.Impossible(empty_msg)
                else:
                    # Send to input handler to display contents
                    if not is_corpse:
                        sounds.play_chest_open_sound()
                    from input_handlers import ContainerEventHandler
                    return ContainerEventHandler(self.engine, container)

        # Read tile tuple for 'true' interactable property
        tile = self.engine.game_map.tiles["interactable"][target_x, target_y]    
        if tile:
            # Get name for that tile
            name = self.engine.game_map.tiles["name"][target_x, target_y]

            # If it's a door, toggle open/closed state
            if name == "Door":
                # Convert "Door" tile to "Open Door" tile
                import tile_types
                self.engine.game_map.tiles[target_x, target_y] = tile_types.open_door
                sounds.play_door_open_sound_at(target_x, target_y, self.engine.player, self.engine.game_map)
                self.engine.message_log.add_message("You open the door.")

            elif name == "Open Door":
                # Convert "Open Door" tile to "Door" tile
                import tile_types
                self.engine.game_map.tiles[target_x, target_y] = tile_types.closed_door
                sounds.play_door_close_sound_at(target_x, target_y, self.engine.player, self.engine.game_map)
                self.engine.message_log.add_message("You close the door.")

            else:
                self.engine.message_log.add_message("There is nothing to interact with.")
        elif self.engine.game_map.get_actor_at_location(target_x, target_y):
            print(f"Interacting with actor at {target_x}, {target_y}")
            npc = self.engine.game_map.get_actor_at_location(target_x, target_y)
            if npc and hasattr(npc, "ai") and getattr(npc.ai, "type", None) == "Friendly":
                # Import here to avoid circular imports
                from input_handlers import DialogueEventHandler
                return DialogueEventHandler(self.engine, npc)
            else:
                self.engine.message_log.add_message("They don't seem interested in talking.")
        else:
            self.engine.message_log.add_message("There is nothing to interact with.")


class PickupAction(Action):
    #pick up item and put in inventory IF ROOM

    def __init__(self, entity: Actor):
        super().__init__(entity)

    def perform(self) -> None:
        actor_location_x = self.entity.x
        actor_location_y = self.entity.y
        inventory = self.entity.inventory

        for item in self.engine.game_map.items:
            if actor_location_x == item.x and actor_location_y == item.y:
                if len(inventory.items) >= inventory.capacity:
                    raise exceptions.Impossible("Your inventory is full IDIOT")
            
                # Bonfires cannot be picked up
                if item.name == "Bonfire":
                    raise exceptions.Impossible("The bonfire is too hot to handle!")

                if "coin" in item.name.lower():
                    self.engine.player.gold += item.value
                    self.engine.game_map.entities.remove(item)
                    self.engine.message_log.add_message("You pick up some coins.", color.yellow)
                    
                    # Coin pick up sound 
                    if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                        try:
                            item.pickup_sound()
                        except Exception as e:
                            print(f"DEBUG: Error calling pickup sound: {e}")
                    return
                else:
                    self.engine.game_map.entities.remove(item)
                    item.parent = self.entity.inventory
                    inventory.items.append(item)
                # Special-case picking up a campfire: convert to a Torch with a flavor message
                try:
                    from entity_factories import torch 
                except Exception:
                    _torch_template = None

                if item.name == "Campfire" and torch is not None:
                    inventory.items.pop()
                    new_torch = copy.deepcopy(torch)
                    new_torch.parent = self.entity.inventory
                    inventory.items.append(new_torch)
                    sounds.play_torch_pull_sound()
                    self.engine.message_log.add_message("You pull a burning log from the fire")
                    return
                # Play pickup sound if it exists
                if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                    try:
                        item.pickup_sound()
                    except Exception as e:
                        print(f"DEBUG: Error calling pickup sound: {e}")

                self.engine.message_log.add_message(f"You picked up the {item.name}!")
                
                # Grant trait XP for picking up items (strength training)
                return
        raise exceptions.Impossible("There is nothing here to pick up.")

class ItemAction(Action):
    def __init__(
            self, entity: Actor, item: Item, target_xy: Optional[Tuple[int, int]] = None
    ):
        super().__init__(entity)
        self.item = item
        if not target_xy:
            target_xy = entity.x, entity.y
        self.target_xy = target_xy

    @property
    def target_actor(self) -> Optional[Actor]:
        # Returns actor at this actions destination
        return self.engine.game_map.get_actor_at_location(*self.target_xy)
    
    def perform(self) -> None:
        # Invoke item, action will be given context
        if self.item.consumable:
            self.item.consumable.activate(self)


class DropItem(ItemAction):
    def perform(self) -> None:
        if self.entity.equipment.item_is_equipped(self.item):
            self.entity.equipment.toggle_equip(self.item)
        
        self.entity.inventory.drop(self.item) 
class OpenAction(Action):
    def perform(self) -> None:
        # Open a container (chest) on the map and present its contents to the player.
        actor_location_x = self.entity.x
        actor_location_y = self.entity.y
        # Check for chest entity adjacent to player
        for ent in self.engine.game_map.entities:
            if hasattr(ent, "container") and ent.container and (
                abs(ent.x - actor_location_x) <= 1 and abs(ent.y - actor_location_y) <= 1
            ):
                # Container found
                container = ent.container
                is_corpse = getattr(ent, "type", None) == "Dead"
                
                if len(container.items) == 0:
                    empty_msg = "There is nothing left to loot." if is_corpse else "The chest is empty."
                    raise exceptions.Impossible(empty_msg)
                else:
                    # Send to input handler to display contents
                    if not is_corpse:
                        sounds.play_chest_open_sound()
                    from input_handlers import ContainerEventHandler
                    return ContainerEventHandler(self.engine, container)
        raise exceptions.Impossible("Nothing nearby to open.")
class EquipAction(Action):
    def __init__(self, entity: Actor, item: Item):
        super().__init__(entity)

        self.item = item

    def perform(self) -> None:
        self.entity.equipment.toggle_equip(self.item)

class WaitAction(Action):
    def perform(self) -> None:
        pass

class TakeStairsAction(Action):
    def perform(self) -> None:
        # Take the stairs, if they exist at its location
        pos = (self.entity.x, self.entity.y)

        # Descend if on the downstairs tile
        if pos == self.engine.game_map.downstairs_location:
            # Use GameWorld.descend helper if available, otherwise fall back
            try:
                self.engine.game_world.descend()
            except Exception:
                # Fallback to previous behavior
                self.engine.game_world.generate_floor()
            sounds.stairs_sound.play()
            self.engine.message_log.add_message("You descend the staircase.", color.descend)
            return

        # Ascend if on an upstairs tile
        if hasattr(self.engine.game_map, "upstairs_location") and pos == self.engine.game_map.upstairs_location:
            # Call ascend on the GameWorld if available; if not, try map-level ascend
            try:
                self.engine.game_world.ascend()
                sounds.stairs_sound.play()
                self.engine.message_log.add_message("You ascend the staircase.", color.ascend)
                return
            except Exception:
                try:
                    # Some older code may expect engine.game_map.ascend
                    self.engine.game_map.ascend()
                    self.engine.message_log.add_message("You ascend the staircase.", color.ascend)
                    return
                except Exception:
                    pass

        raise exceptions.Impossible("There are no stairs here.")

class ActionWithDirection(Action):
    def __init__(self, entity: Actor, dx: int, dy: int):
        super().__init__(entity)
        
        self.dx = dx
        self.dy = dy

    @property # destination
    def dest_xy(self) -> Tuple[int, int]:
        """Return the destination coordinates after this action."""
        return self.entity.x + self.dx, self.entity.y + self.dy

    @property # is blocking?
    def blocking_entity(self) -> Optional[Entity]:
        """Return the blocking entity at this action's destination."""
        return self.engine.game_map.get_blocking_entity_at_location(*self.dest_xy)
    
    @property
    def target_location(self) -> Tuple[int, int]:
        """Return the target location coordinates for this action."""
        return self.dest_xy

    @property
    def target_actor(self) -> Optional[Actor]:
        #Return the actor at actions dest.
        return self.engine.game_map.get_actor_at_location(*self.dest_xy)

    def perform(self) -> None:
        raise NotImplementedError()
    
class RangedAction(ActionWithDirection):
    """Directional ranged attack that can target a specific body part."""

    def __init__(self, entity: Actor, dx: int, dy: int, target_part: Optional['BodyPartType'] = None):
        super().__init__(entity, dx, dy)
        self.target_part = target_part

    def _get_ready_ranged_items(self):
        """Return currently readied bow and projectile items, if any."""
        bow_item = None
        projectile_item = None

        equipment = getattr(self.entity, "equipment", None)
        if not equipment:
            return None, None

        held_items = list(equipment.grasped_items.values()) + list(equipment.equipped_items.values())

        for item in held_items:
            if not item or not hasattr(item, "equippable") or not item.equippable:
                continue

            eq_type_name = item.equippable.equipment_type.name
            item_tags = {tag.lower() for tag in getattr(item, "tags", [])}

            if bow_item is None and (eq_type_name == "RANGED" or "bow" in item_tags):
                bow_item = item

            if projectile_item is None and (
                eq_type_name == "PROJECTILE" or "arrow" in item_tags or "ammunition" in item_tags
            ):
                projectile_item = item

            if bow_item and projectile_item:
                break

        return bow_item, projectile_item

    def _find_target_in_line(self, max_range: int = 8) -> tuple[Optional[Actor], Optional[tuple[int, int]], str]:
        """Find the first actor hit by a shot in this direction or what stops the projectile.
        
        Returns:
            (target_actor, collision_pos, collision_type)
            - target_actor: The actor hit, or None if no actor hit
            - collision_pos: Position where projectile stopped (x, y) - last walkable tile before obstacle
            - collision_type: 'actor', 'obstacle', 'out_of_bounds', or 'max_range'
        """
        x, y = self.entity.x, self.entity.y
        last_walkable_x, last_walkable_y = x, y

        for step in range(max_range):
            x += self.dx
            y += self.dy

            # Check bounds first
            if not self.engine.game_map.in_bounds(x, y):
                return None, (last_walkable_x, last_walkable_y), 'out_of_bounds'

            # Check for actor at this position
            target = self.engine.game_map.get_actor_at_location(x, y)
            if target and target is not self.entity:
                return target, (x, y), 'actor'

            # Check if the tile is walkable - if not, projectile stops at last walkable position
            if not self.engine.game_map.tiles["walkable"][x, y]:
                return None, (last_walkable_x, last_walkable_y), 'obstacle'
            
            # Update last walkable position
            last_walkable_x, last_walkable_y = x, y

        # Reached max range without hitting anything
        return None, (x, y), 'max_range'

    def _consume_projectile(self, projectile_item) -> None:
        equipment = getattr(self.entity, "equipment", None)
        inventory = getattr(self.entity, "inventory", None)

        original_hand_slot = None
        original_equipped_slot = None

        if equipment:
            for hand_name, held_item in equipment.grasped_items.items():
                if held_item == projectile_item:
                    original_hand_slot = hand_name
                    break

            if (
                original_hand_slot is None
                and hasattr(projectile_item, "equippable")
                and projectile_item.equippable
            ):
                eq_slot_name = projectile_item.equippable.equipment_type.name
                if equipment.equipped_items.get(eq_slot_name) == projectile_item:
                    original_equipped_slot = eq_slot_name

        if equipment:
            equipment.unequip_item(projectile_item, add_message=False)

        if inventory:
            inventory.delete(projectile_item)

        if not equipment or not inventory:
            return

        replacement_arrow = None
        for item in inventory.items:
            if item == projectile_item:
                continue
            if not hasattr(item, "equippable") or not item.equippable:
                continue

            eq_type_name = item.equippable.equipment_type.name
            item_tags = {tag.lower() for tag in getattr(item, "tags", [])}
            is_arrow = (
                eq_type_name == "PROJECTILE"
                or "arrow" in item_tags
                or "ammunition" in item_tags
            )

            if is_arrow and not equipment.item_is_equipped(item):
                replacement_arrow = item
                break

        if not replacement_arrow:
            if self.entity is self.engine.player:
                self.engine.message_log.add_message("You are out of arrows.", color.yellow)
            return

        if original_hand_slot:
            equipment.grasped_items[original_hand_slot] = replacement_arrow
        elif original_equipped_slot:
            equipment.equipped_items[original_equipped_slot] = replacement_arrow
        else:
            equipment.equip_item(replacement_arrow, add_message=False)

        if self.entity is self.engine.player:
            self.engine.message_log.add_message("You ready another arrow.", color.light_gray)

    def perform(self) -> None:
        bow_item, projectile_item = self._get_ready_ranged_items()
        if not bow_item or not projectile_item:
            raise exceptions.Impossible("You need a bow and an arrow readied to fire.")

        # Store projectile info before consuming it
        projectile_char = projectile_item.char
        projectile_color = projectile_item.color

        # Always consume projectile when firing (regardless of hit/miss)
        self._consume_projectile(projectile_item)

        # Play shooting sound
        sounds.play_throw_sound()  # Use throw sound for bow firing

        target, collision_pos, collision_type = self._find_target_in_line(max_range=8)

        # Use bow verb if available
        shot_verb = "shoots"
        if hasattr(bow_item, "verb_present") and bow_item.verb_present:
            shot_verb = bow_item.verb_present
        elif hasattr(bow_item, "verb_base") and bow_item.verb_base:
            shot_verb = bow_item.verb_base + "s"

        # Handle different collision types
        if collision_type == 'actor' and target:
            # Hit an actor - proceed with normal combat
            self._handle_actor_hit(target, shot_verb)
            # Add projectile animation
            import tcod.los
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), collision_pos).tolist())
            from animations import ThrowAnimation
            self.engine.animation_queue.append(ThrowAnimation(path, projectile_char, projectile_color))
        elif collision_type == 'obstacle':
            # Hit an obstacle - 50/50 chance to break or fall
            break_chance = random.random() < 0.5
            
            # Add projectile animation to collision point
            import tcod.los
            obstacle_x = collision_pos[0] + self.dx
            obstacle_y = collision_pos[1] + self.dy
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), (obstacle_x, obstacle_y)).tolist())
            from animations import ThrowAnimation
            self.engine.animation_queue.append(ThrowAnimation(path, projectile_char, projectile_color))
            
            sounds.play_throw_sound()  # Use throw sound for projectile hitting obstacle
            if break_chance:
                self.engine.message_log.add_message(f"Your arrow hits an obstacle and breaks!", color.gray)
            else:
                self.engine.message_log.add_message(f"Your arrow hits an obstacle and falls to the ground.", color.gray)
                self._drop_projectile_at(collision_pos, None)
        elif collision_type == 'out_of_bounds':
            # Add projectile animation to edge of map
            import tcod.los
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), collision_pos).tolist())
            from animations import ThrowAnimation
            self.engine.animation_queue.append(ThrowAnimation(path, projectile_char, projectile_color))
            self.engine.message_log.add_message(f"Your arrow flies out of sight.", color.gray)
        elif collision_type == 'max_range':
            # Add projectile animation to max range
            import tcod.los
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), collision_pos).tolist())
            from animations import ThrowAnimation
            self.engine.animation_queue.append(ThrowAnimation(path, projectile_char, projectile_color))
            self.engine.message_log.add_message(f"Your arrow lands in the distance.", color.gray)
            self._drop_projectile_at(collision_pos, None)
        else:
            # No target found in range
            self.engine.message_log.add_message(f"Your arrow flies through empty air.", color.gray)

    def _drop_projectile_at(self, pos: tuple[int, int], original_projectile) -> None:
        """Drop a copy of the projectile at the specified position."""
        try:
            import copy
            from entity_factories import arrow  # Assuming there's a basic arrow template
            
            # Create a new arrow at the collision position
            new_arrow = copy.deepcopy(arrow)
            new_arrow.x, new_arrow.y = pos
            
            # Add to game map
            self.engine.game_map.entities.add(new_arrow)
            
        except Exception as e:
            print(f"Could not drop projectile: {e}")
            # Silently fail if we can't create the arrow
    
    def _handle_actor_hit(self, target: Actor, shot_verb: str) -> None:
        """Handle hitting an actor with the projectile."""
        # Manipulation check
        for part in self.entity.body_parts.get_all_parts().values():
            if "manipulate" in part.tags:
                if part.damage_level_float > 0.5:
                    if random.random() < 0.5:
                        self.entity.fighter._drop_grasped_items(part)
                    #print("DEBUG: Manipulation partially impaired by damage to part:", part.name)
                elif part.damage_level_float >= 1.0:
                    self.entity.fighter._drop_grasped_items(part)
                else:
                    #print("DEBUG: Manipulation possible with part:", part.name)
                    pass
        
        hit_part = None
        damage_modifier = 1.0
        hit_difficulty_modifier = 0.0

        if not self.target_part:
            if hasattr(target, 'body_parts') and target.body_parts:
                random_part = target.body_parts.get_random_part()
                self.target_part = random_part.part_type if random_part else None

        if self.target_part and hasattr(target, 'body_parts') and target.body_parts:
            hit_part = target.body_parts.body_parts.get(self.target_part)
            if hit_part and not hit_part.is_destroyed:
                part_type_name = hit_part.part_type.name
                if part_type_name in BODY_PART_MODIFIERS:
                    damage_modifier, hit_difficulty_modifier = BODY_PART_MODIFIERS[part_type_name]
                else:
                    for key in BODY_PART_MODIFIERS:
                        if key in part_type_name:
                            damage_modifier, hit_difficulty_modifier = BODY_PART_MODIFIERS[key]
                            break
            else:
                # If targeted part is destroyed, hit a random available part instead
                random_part = target.body_parts.get_random_part()
                if random_part:
                    self.target_part = random_part.part_type
                    hit_part = random_part
                    if hit_part and not hit_part.is_destroyed:
                        part_type_name = hit_part.part_type.name
                        if part_type_name in BODY_PART_MODIFIERS:
                            damage_modifier, hit_difficulty_modifier = BODY_PART_MODIFIERS[part_type_name]
                        else:
                            for key in BODY_PART_MODIFIERS:
                                if key in part_type_name:
                                    damage_modifier, hit_difficulty_modifier = BODY_PART_MODIFIERS[key]
                                    break

        # Calculate defense and damage
        base_defense = 0
        armor_defense = 0
        
        if hit_part:
            base_defense = hit_part.protection + target.fighter.base_defense
            if hasattr(target, "equipment") and target.equipment:
                armor_defense = target.equipment.get_defense_for_part(hit_part.name)
        else:
            base_defense = target.fighter.defense

        total_defense = base_defense + armor_defense
        base_damage = self.entity.fighter.power - total_defense
        final_damage = max(0, int(base_damage * damage_modifier))

        # Hit chance calculation
        hit_chance = 50 + hit_difficulty_modifier
        hit_roll = random.randint(1, 100)
        hit_success = hit_roll <= hit_chance

        # Dodge calculation
        dodge_success = False
        if hit_success:
            if random.random() < target.dodge_chance:
                hit_success = False
                dodge_success = True
            
        if dodge_success:
            adjacent_positions = [
                (target.x + 1, target.y), (target.x - 1, target.y),
                (target.x, target.y + 1), (target.x, target.y - 1)
            ]
            if target.preferred_dodge_direction:
                preferred_order = {
                    "north": [(target.x, target.y - 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y + 1)],
                    "south": [(target.x, target.y + 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y - 1)],
                    "east": [(target.x + 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x - 1, target.y)],
                    "west": [(target.x - 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x + 1, target.y)]
                }
                adjacent_positions = preferred_order.get(target.preferred_dodge_direction.lower(), adjacent_positions)
            for new_x, new_y in adjacent_positions:
                if self.engine.game_map.in_bounds(new_x, new_y) and self.engine.game_map.tiles["walkable"][new_x, new_y] and not self.engine.game_map.get_blocking_entity_at_location(new_x, new_y):
                    target.x = new_x
                    target.y = new_y
                    self.engine.message_log.add_message(f"{target.name} dodges to the side!", color.teal)
                    break

        # Create attack description
        if hit_part:
            attack_desc = f"{self.entity.name.capitalize()} {shot_verb} {target.name}'s {hit_part.name}"
        else:
            attack_desc = f"{self.entity.name.capitalize()} {shot_verb} {target.name}"

        # Play sounds
        if hit_success and final_damage > 0:
            if target.fighter.hp <= final_damage:
                sounds.play_attack_sound_finishing_blow()
            elif target.equipment and target.equipment.equipped_items.get('ARMOR'):
                sounds.play_attack_sound_weapon_to_armor()
            else:
                sounds.play_attack_sound_weapon_to_no_armor()
        elif hit_success and final_damage == 0:
            sounds.play_block_sound()
        else:
            sounds.play_miss_sound()

        # Set attack color
        if self.entity is self.engine.player:
            attack_color = color.player_atk
        else:
            attack_color = color.enemy_atk

        # Display results
        if not hit_success:
            if dodge_success:
                self.engine.message_log.add_message(
                    f"{attack_desc}, but {target.name} dodges!", color.teal
                )
            else:
                self.engine.message_log.add_message(
                    f"{attack_desc}, but misses!", color.dark_gray
                )
            # Arrow always drops when missing/dodged - drop at target location
            self._drop_projectile_at((target.x, target.y), None)
        elif final_damage > 0:
            if hit_part:
                part_damage = hit_part.take_damage(final_damage)
                if hit_part.is_destroyed:
                    self.engine.message_log.add_message(
                        f"{attack_desc} and destroys it for {part_damage} damage!", color.red
                    )
                else:
                    self.engine.message_log.add_message(
                        f"{attack_desc} for {part_damage} damage.", attack_color
                    )
                

                target.fighter.take_damage(part_damage, targeted_part=self.target_part)
            else:
                self.engine.message_log.add_message(
                    f"{attack_desc} for {final_damage} hit points.", attack_color
                )
                target.fighter.take_damage(final_damage)
            item_for_attack = self._get_ready_ranged_items()[0]  # Get the bow used for the attack

            # 50/50 chance to add arrow to target's inventory when hit
            if hasattr(target, 'inventory') and target.inventory and random.random() < 0.5:
                try:
                    import copy
                    from entity_factories import arrow  # Get arrow template
                    
                    # Create a copy of the arrow
                    recovered_arrow = copy.deepcopy(arrow)
                    
                    # Add to target's inventory if there's space
                    if len(target.inventory.items) < target.inventory.capacity:
                        recovered_arrow.parent = target.inventory
                        target.inventory.items.append(recovered_arrow)
                except Exception as e:
                    # Silently fail if arrow recovery doesn't work
                    pass

            if target is self.engine.player:
                self.engine.trigger_damage_indicator()
        else:
            self.engine.message_log.add_message(
                f"{attack_desc}, but does no damage.", attack_color
            )
            # Arrow bounced off armor/blocked - drops to ground
            self._drop_projectile_at((target.x, target.y), None)

        # Grant trait XP for ranged combat
        if final_damage > 0:
            # Award XP to attacker for bow usage
            self.entity.level.add_xp({'agility': int(final_damage)})
            
            # Award XP to target for taking damage and armor defense
            target.level.add_xp({'vigor': int(final_damage)})
            
            # Award armor XP if target has armor that blocked damage
            armor_tags = target.equipment.get_armor_tags_for_part(hit_part.name) if hit_part and hasattr(target, "equipment") and target.equipment else []
            if armor_defense > 0 and armor_tags:
                target.level.add_xp({'armor': int(armor_defense/2)})
                if "light armor" in armor_tags:
                    target.level.add_xp({'light armor': int(armor_defense)})
                    print("DEBUG: Gained light armor XP from ranged:", int(armor_defense))

class MeleeAction(ActionWithDirection):
    """Melee action that targets a specific body part."""
    
    def __init__(self, entity: Actor, dx: int, dy: int, target_part: Optional['BodyPartType'] = None):
        super().__init__(entity, dx, dy)
        self.target_part = target_part
    
    def perform(self) -> None:
        target = self.target_actor
        part_damage = 0  # Initialize to handle cases where no damage is dealt

        # Check for target
        if not target:
            x = self.target_location[0]
            y = self.target_location[1]
            self.engine.animation_queue.append(animations.SlashAnimation(x, y))
            sounds.play_miss_sound()
            raise exceptions.Impossible("Nothing to attack.")
        
        # Manipulation check
        for part in self.entity.body_parts.get_all_parts().values():
            if "manipulate" in part.tags:
                if part.damage_level_float > 0.5:
                    if random.random() < 0.5:
                        self.entity.fighter._drop_grasped_items(part)
                    #print("DEBUG: Manipulation partially impaired by damage to part:", part.name)
                elif part.damage_level_float >= 1.0:
                    self.entity.fighter._drop_grasped_items(part)
                else:
                    #print("DEBUG: Manipulation possible with part:", part.name)
                    pass
        # Get target body part and apply targeting effects
        hit_part = None
        damage_modifier = 1.0
        hit_difficulty_modifier = 0.0  # Positive = easier to hit, negative = harder

        # Check if any part is targeted
        #print("DEBUG: target_part:", self.target_part)
        if not self.target_part:
            # If no part targeted, use the existing random part selection
            if hasattr(target, 'body_parts') and target.body_parts:
                random_part = target.body_parts.get_random_part()
                self.target_part = random_part.part_type if random_part else None

        #print(f"DEBUG: Targeting {target.name}'s {self.target_part.name if self.target_part else 'random part'}")
        
        if self.target_part and hasattr(target, 'body_parts') and target.body_parts:
            # Get the actual BodyPart object using the enum as key
            hit_part = target.body_parts.body_parts.get(self.target_part)
            
            if hit_part and not hit_part.is_destroyed:
                # Apply targeting modifiers based on body part type
                part_type_name = hit_part.part_type.name
                
                # Look up modifiers in dictionary
                if part_type_name in BODY_PART_MODIFIERS:
                    damage_modifier, hit_difficulty_modifier = BODY_PART_MODIFIERS[part_type_name]
                else:
                    # Check for partial matches (for complex body part names)
                    for key in BODY_PART_MODIFIERS:
                        if key in part_type_name:
                            damage_modifier, hit_difficulty_modifier = BODY_PART_MODIFIERS[key]
                            break
            else:
                # If targeted part is destroyed, hit a random available part instead
                random_part = target.body_parts.get_random_part()
                if random_part:
                    self.target_part = random_part.part_type
                    hit_part = random_part
                    if hit_part and not hit_part.is_destroyed:
                        part_type_name = hit_part.part_type.name
                        
                        # Apply modifiers for the new random part
                        if part_type_name in BODY_PART_MODIFIERS:
                            damage_modifier, hit_difficulty_modifier = BODY_PART_MODIFIERS[part_type_name]
                        else:
                            for key in BODY_PART_MODIFIERS:
                                if key in part_type_name:
                                    damage_modifier, hit_difficulty_modifier = BODY_PART_MODIFIERS[key]
                                    break
        
        # Calculate localized defense
        base_defense = 0
        armor_defense = 0
        
        if hit_part:
            base_defense = hit_part.protection + target.fighter.base_defense
            if hasattr(target, "equipment") and target.equipment:
                armor_defense = target.equipment.get_defense_for_part(hit_part.name)
                #print("DEBUG: Calculating defense for hit part:", hit_part.name, "base defense:", target.fighter.base_defense)
        else:
             base_defense = target.fighter.defense

        total_defense = base_defense + armor_defense
        
        # Calculate base damage
        base_damage = self.entity.fighter.power - total_defense

        # Calculate final damage
        final_damage = max(0, int(base_damage * damage_modifier))
        #print(f"DEBUG: hit_part={hit_part.name if hit_part else None}, final_damage={final_damage}")
        
        # Determine hit success based on difficulty
        hit_chance = 85 + hit_difficulty_modifier  # Base 85% hit chance
        hit_roll = random.randint(1, 100)
        hit_success = hit_roll <= hit_chance

        # Dodge calculation for entity 
        dodge_success = False
        if hit_success:
            if random.random() < target.dodge_chance:
                hit_success = False
                dodge_success = True

        # Dodge moves entity to adjacent tile if successful
        if dodge_success:
            adjacent_positions = [
                (target.x + 1, target.y), (target.x - 1, target.y),
                (target.x, target.y + 1), (target.x, target.y - 1)
            ]
            # attempts to choose preferred dodge direction first, then randomizes the rest
            if target.preferred_dodge_direction:
                preferred_order = {
                    "north": [(target.x, target.y - 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y + 1)],
                    "south": [(target.x, target.y + 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y - 1)],
                    "east": [(target.x + 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x - 1, target.y)],
                    "west": [(target.x - 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x + 1, target.y)]
                }
                adjacent_positions = preferred_order.get(target.preferred_dodge_direction.lower(), adjacent_positions)
            for new_x, new_y in adjacent_positions:
                if self.engine.game_map.in_bounds(new_x, new_y) and self.engine.game_map.tiles["walkable"][new_x, new_y] and not self.engine.game_map.get_blocking_entity_at_location(new_x, new_y):
                    target.x = new_x
                    target.y = new_y
                    self.engine.message_log.add_message(f"{target.name} dodges to the side!", color.teal)
                    break
        
        # Create attack description

        ## Add verb from item verb tags 
        # Check for equipped weapon and use its verb if available
        weapon_verb = None
        weapon = None
        equipped_weapons = None
        if self.entity.equipment:
            equipped_weapons = [item for item in self.entity.equipment.grasped_items.values() if item and hasattr(item, 'equippable') and item.equippable and item.equippable.equipment_type.name == 'WEAPON']
        if self.entity.equipment:
            # Find the first weapon in grasped items
            for item in self.entity.equipment.grasped_items.values():
                if (hasattr(item, 'equippable') and item.equippable and 
                    item.equippable.equipment_type.name == 'WEAPON'):
                    weapon = item
                    break
            
            if weapon:
                # Check for verb attributes on weapon (present tense for combat)
                if hasattr(weapon, 'verb_present') and weapon.verb_present:
                    weapon_verb = weapon.verb_present
                elif hasattr(weapon, 'verb_base') and weapon.verb_base:
                    weapon_verb = weapon.verb_base + "s"  # Convert base to present tense
        
        # Fallback to entity verb if no weapon verb found
        if not weapon_verb:
            if hasattr(self.entity, 'verb_present') and self.entity.verb_present:
                weapon_verb = self.entity.verb_present
            elif hasattr(self.entity, 'verb_base') and self.entity.verb_base:
                weapon_verb = self.entity.verb_base + "s"
        
        # Final fallback to "attacks"
        if not weapon_verb:
            weapon_verb = "attacks"

        # Description assembly
        if hit_part:
            attack_desc = f"{self.entity.name.capitalize()} {weapon_verb} {target.name}'s {hit_part.name}"
        else:
            attack_desc = f"{self.entity.name.capitalize()} {weapon_verb} {target.name}"

        
        # Play hit sound if hit
        if hit_success and final_damage > 0:
            # If final blow, play different sound
            if target.fighter.hp <=  final_damage:
                sounds.play_attack_sound_finishing_blow()
            elif self.entity.equipment:
                if target.equipment and target.equipment.equipped_items.get('ARMOR'):
                    sounds.play_attack_sound_weapon_to_armor()
                else:
                    sounds.play_attack_sound_weapon_to_no_armor()
        # Play block sound if attack hits but does no damage
        elif hit_success and final_damage == 0:
            sounds.play_block_sound()
        
        # Play miss sound if attack misses
        elif not hit_success:
            sounds.play_miss_sound()

        
        # Add animation
        if hit_success:
            self.engine.animation_queue.append(animations.SlashAnimation(target.x, target.y))

        if self.entity is self.engine.player:
            attack_color = color.player_atk
        else:
            attack_color = color.enemy_atk

        if not hit_success:
            if dodge_success:
                self.engine.message_log.add_message(
                    f"{attack_desc}, but {target.name} dodges!", color.teal
                )
            else:
                self.engine.message_log.add_message(
                    f"{attack_desc}, but misses!", color.dark_gray
                )
        elif final_damage > 0:
            # Apply damage to specific body part (should always have a valid part)
            if hit_part:
                part_damage = hit_part.take_damage(final_damage)
                
                # Special messages for different damage levels
                if hit_part.is_destroyed:
                    self.engine.message_log.add_message(
                        f"{attack_desc} and destroys it for {part_damage} damage!", color.red
                    )
                else:
                    self.engine.message_log.add_message(
                        f"{attack_desc} for {part_damage} damage.", attack_color
                    )

                target.fighter.take_damage(part_damage, targeted_part=self.target_part)

            else:
                # This should never happen - but adding for debugging
                print(f"ERROR: No valid body part found! target_part={self.target_part}, has_body_parts={hasattr(target, 'body_parts')}")
                self.engine.message_log.add_message(
                    f"{attack_desc} for {final_damage} hit points. [NO BODY PART ERROR]", color.red
                )
                target.fighter.take_damage(final_damage)
            
            # Trigger damage indicator if player takes damage
            if target is self.engine.player:
                self.engine.trigger_damage_indicator()
        else:
            self.engine.message_log.add_message(
                f"{attack_desc}, but does no damage.", attack_color
            )

        # Grant trait XP for melee combat
        armor_tags = target.equipment.get_armor_tags_for_part(hit_part.name)
        xp = int(part_damage)
        #print("DEBUG: Gained constitution XP:", int(part_damage))
        #print(equipped_weapons)

        # Add users XP
        if equipped_weapons:
            for weapon in equipped_weapons:
                print(weapon.tags)
                if "blade" in weapon.tags:
                    self.entity.level.add_xp({'blades': xp})
                    print("DEBUG: Gained blade XP:", int(part_damage/2))
                if "dagger" in weapon.tags:
                    self.entity.level.add_xp({'daggers': xp})
                print("DEBUG: Gained dagger XP:", int(part_damage*1.5))

        # Add targets XP
        target.level.add_xp({'vigor': int(part_damage*2)})
        if armor_tags and armor_defense > 0:
            if "light armor" in armor_tags:
                target.level.add_xp({'light armor': int(armor_defense*1.5)})
                print("DEBUG: Gained light armor XP:", int(armor_defense*1.5))
class MovementAction(ActionWithDirection):

    def perform(self) -> None:
        dest_x, dest_y = self.dest_xy

        # Check if entity can move (has working legs/locomotion)
        if hasattr(self.entity, 'body_parts') and self.entity.body_parts:
            if not self.entity.body_parts.can_move():
                if self.entity == self.engine.player:
                    raise exceptions.Impossible("You can't move with your legs destroyed!")
                else:
                    raise exceptions.Impossible("The creature can't move!")
            
            # Warn player about movement penalties from leg injuries
            if self.entity == self.engine.player:
                penalty = self.entity.body_parts.get_movement_penalty()
                if penalty > 0.5:  # Significant penalty (> 50%)
                    if not hasattr(self, '_shown_movement_warning'):
                        self.engine.message_log.add_message("Your damaged legs make movement difficult!", color.yellow)
                        self._shown_movement_warning = True

        if not self.engine.game_map.in_bounds(dest_x, dest_y):
            raise exceptions.Impossible("That way is blocked.")  # Destination is out of bounds.
        
        if not self.engine.game_map.tiles["walkable"][dest_x, dest_y]:
            raise exceptions.Impossible("That way is blocked.")  # Destination is not walkable.
        if self.engine.game_map.get_blocking_entity_at_location(dest_x, dest_y):
            raise exceptions.Impossible("That way is blocked.")  # Destination is blocked by an entity.
        
        self.entity.move(self.dx, self.dy)

        # Always play footstep sounds for non-player entities (enemies)
        if self.entity != self.engine.player:
            # Play footstep sound with positional muffling
            dx = dest_x - self.engine.player.x
            dy = dest_y - self.engine.player.y
            distance = (dx * dx + dy * dy) ** 0.5
            
            if distance <= 10:  # Within hearing range
                # Check for liquid coating first, then tile type
                liquid_coating = None
                if hasattr(self.engine.game_map, 'liquid_system'):
                    liquid_coating = self.engine.game_map.liquid_system.get_coating(dest_x, dest_y)
                
                if liquid_coating and liquid_coating.depth >= 1:
                    sounds.play_movement_sound_at(sounds.play_liquid_walk_sound, dest_x, dest_y, self.engine.player, self.engine.game_map)
                else:
                    # Check tile type for sound variation
                    tile_name = self.engine.game_map.tiles["name"][dest_x, dest_y]
                    if tile_name == "Grass":
                        sounds.play_movement_sound_at(sounds.play_grass_walk_sound, dest_x, dest_y, self.engine.player, self.engine.game_map)
                    else:
                        sounds.play_movement_sound_at(sounds.play_walk_sound, dest_x, dest_y, self.engine.player, self.engine.game_map)

        # If not in view, display sound tile animation (for all entities)
        from animations import HeardSoundAnimation
        if not self.engine.game_map.visible[dest_x, dest_y]:
            # Use different color for enemy footsteps vs other sounds
            if self.entity != self.engine.player:
                color = (150, 150, 150)  # Gray for footsteps
            else:
                color = (255, 255, 0)  # Yellow for other sounds
            self.engine.animation_queue.append(HeardSoundAnimation((dest_x, dest_y), self.engine.player, color))
        
        # Only play walk sound for player if not moving rapidly or holding key
        if self.entity == self.engine.player and self.engine.should_play_movement_sound():
            # Check if near player 
            dx = dest_x - self.engine.player.x
            dy = dest_y - self.engine.player.y
            distance = (dx * dx + dy * dy) ** 0.5

            if distance <= 8:
                # Check for liquid coating first, then tile type
                liquid_coating = None
                if hasattr(self.engine.game_map, 'liquid_system'):
                    liquid_coating = self.engine.game_map.liquid_system.get_coating(dest_x, dest_y)
                
                if liquid_coating and liquid_coating.depth >= 1:
                    sounds.play_liquid_walk_sound(dest_x, dest_y)
                else:
                    # Check tile type for sound variation
                    tile_name = self.engine.game_map.tiles["name"][dest_x, dest_y]
                    if tile_name == "Grass":
                        sounds.play_grass_walk_sound()
                    elif tile_name == "Floor":
                        sounds.play_walk_sound()


class ThrowItem(ItemAction):
    def __init__(self, entity: Actor, item: Item, target_x: int, target_y: int):
        super().__init__(entity, item, target_xy=(target_x, target_y))

    def check_throw_hit(self, x, y) -> None:
        # Check for actor at target location
        target = self.engine.game_map.get_actor_at_location(x, y)
        if target:
            item_weight = getattr(self.item, 'weight', 1.0)  # Default weight if not specified
            damage = int(item_weight)

            # Pick random body part to hit
            if hasattr(target, 'body_parts') and target.body_parts:
                random_part = target.body_parts.get_random_part()
                targeted_part = random_part.part_type if random_part else None
            else:
                targeted_part = None
                random_part = None

            # Inflict damage on part
            if targeted_part and random_part:
                target.fighter.take_damage(damage, targeted_part=targeted_part)
                self.engine.message_log.add_message(f"You throw the {self.item.name} and hit {target.name}'s {random_part.name} for {damage} damage!", color.orange)
            else:
                target.fighter.take_damage(damage)
                self.engine.message_log.add_message(f"You throw the {self.item.name} and hit {target.name} for {damage} damage!", color.orange)

    def perform(self) -> None:
        # Remove item from inventory
        if self.entity.equipment.item_is_equipped(self.item):
            self.entity.equipment.toggle_equip(self.item)

        # Also check if contained liquid
        if self.item.liquid_type:
            x = self.target_xy[0]
            y = self.target_xy[1]
            self.engine.game_map.liquid_system.spill_volume(x=x, y=y, liquid_type=self.item.liquid_type, volume=self.item.liquid_amount)
        

        if self.item.tags and "fragile" in self.item.tags:
            # Handle fragile item breakage
            self.engine.message_log.add_message(f"You throw the {self.item.name}, and it shatters on impact!", color.purple)
            sounds.play_glass_break_sound()
            # Delete item
            self.entity.inventory.delete(self.item)
            return
        
        else:
            self.entity.inventory.drop(self.item)
            self.item.drop_sound()
            # Place item on the ground at target location
            self.check_throw_hit(*self.target_xy)
            self.item.x, self.item.y = self.target_xy
            
            # Queue a projectile animation from entity to target location
            import tcod.los
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), self.target_xy).tolist())
            from animations import ThrowAnimation
            self.engine.animation_queue.append(ThrowAnimation(path, self.item.char, self.item.color))


class BumpAction(ActionWithDirection):
    def perform(self) -> None:
        if self.target_actor:
            return MeleeAction(self.entity, self.dx, self.dy).perform()
        else:
            return MovementAction(self.entity, self.dx, self.dy).perform()
        

from __future__ import annotations

from typing import Optional, Tuple, TYPE_CHECKING
import random

import color
import exceptions
import copy 

if TYPE_CHECKING:
    from engine import Engine
    from entity import Actor, Entity, Item
    from components.body_parts import BodyPartType
    from components.spells import Spell
else:
    # Runtime import for BodyPartType if needed
    try:
        from components.body_parts import BodyPartType
    except ImportError:
        BodyPartType = None


import sounds
import animations
import sprite_manager
import gpu_stack
# Body part targeting modifiers (damage_modifier, hit_difficulty_modifier)
# hit_difficulty_modifier: Positive = easier to hit, negative = harder to hit


# Body parts affect damage only; hit chance is resolved separately.
BODY_PART_MODIFIERS = {
    "HEAD":  (1.5,  0),
    "NECK":  (1.5,  0),
    "TORSO": (1.0,  0),
    "LEG":   (0.9,  0),
    "ARM":   (0.9,  0),
    "HAND":  (0.75, 0),
    "FOOT":  (0.75, 0),
    "TAIL":  (0.8,  0),
}

# Base hit chances (0.0–1.0)
BASE_HIT        = 0.90  # Melee
BASE_HIT_RANGED = 0.75  # Ranged

# Weighted likelihood of hitting each zone (higher = hit more often)
BODY_PART_WEIGHTS = {
    "TORSO": 50,
    "LEG":   15,
    "ARM":   15,
    "HEAD":  10,
    "TAIL":   5,
    "HAND":   3,
    "FOOT":   3,
    "NECK":   2,
}


def get_weighted_part_selection(body_parts):
    """Select a random, non-destroyed body part using BODY_PART_WEIGHTS."""
    parts, weights = [], []
    for part in body_parts.body_parts.values():
        if not part.is_destroyed:
            parts.append(part)
            weights.append(BODY_PART_WEIGHTS.get(part.part_type.name, 10))
    if not parts:
        return None
    return random.choices(parts, weights=weights, k=1)[0]


def get_part_from_tile_position(body_parts, tile_rel_x: float, tile_rel_y: float):
    """Map a normalised cursor position within a tile (0.0–1.0) to a body part.

    tile_rel_y=0.0 is the top of the tile (head); 1.0 is the bottom (feet).
    Returns a BodyPart instance, or None if nothing is available.
    """
    available = {
        pt: part for pt, part in body_parts.body_parts.items()
        if not part.is_destroyed
    }
    if not available:
        return None

    if tile_rel_y < 0.2:
        preferred = ["NECK", "HEAD"]
    elif tile_rel_y < 0.4:
        preferred = ["HEAD", "ARM"]
    elif tile_rel_y < 0.6:
        preferred = ["TORSO", "ARM"]
    elif tile_rel_y < 0.8:
        preferred = ["LEG", "HAND"]
    else:
        preferred = ["FOOT", "LEG"]

    for pref in preferred:
        for pt, part in available.items():
            if pref in pt.name:
                return part

    return get_weighted_part_selection(body_parts)


def _get_part_modifiers(part_type_name: str) -> tuple:
    """Return (damage_modifier, 0) for a body part type name."""
    if part_type_name in BODY_PART_MODIFIERS:
        return BODY_PART_MODIFIERS[part_type_name]
    for key, val in BODY_PART_MODIFIERS.items():
        if key in part_type_name:
            return val
    return (1.0, 0)


def _resolve_hit_part(target, target_part):
    """Return (hit_part, target_part, damage_mod) after resolving body part targeting.

    Body part selection uses BODY_PART_WEIGHTS when no explicit target_part is given.
    """
    damage_modifier = 1.0
    hit_part = None

    body_parts = getattr(target, 'body_parts', None)
    if not body_parts:
        return None, target_part, damage_modifier

    if not target_part:
        rp = get_weighted_part_selection(body_parts)
        target_part = rp.part_type if rp else None

    if target_part:
        hit_part = body_parts.body_parts.get(target_part)
        if hit_part and not hit_part.is_destroyed:
            damage_modifier, _ = _get_part_modifiers(hit_part.part_type.name)
        else:
            # Requested part is gone – fall back to weighted random
            rp = get_weighted_part_selection(body_parts)
            if rp:
                target_part = rp.part_type
                hit_part = rp
                if hit_part and not hit_part.is_destroyed:
                    damage_modifier, _ = _get_part_modifiers(hit_part.part_type.name)

    return hit_part, target_part, damage_modifier

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
            self.engine.debug_log(f"Interacting with actor at {target_x}, {target_y}", handler=type(self).__name__, event="perform")
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
                            self.engine.debug_log(f"Error calling coin pickup sound: {e}", handler=type(self).__name__, event="perform")
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
                        self.engine.debug_log(f"Error calling pickup sound: {e}", handler=type(self).__name__, event="perform")

                self.engine.message_log.add_message(f"You picked up the {item.name}!")
                
                # Grant trait XP for picking up items (strength training)
                return
        raise exceptions.Impossible("There is nothing here to pick up.")

class SpellAction(Action):
    def __init__(self, entity: Actor, spell: Spell, target_xy: Optional[Tuple[int, int]] = None):
        super().__init__(entity)
        self.spell = spell
        if not target_xy:
            target_xy = entity.x, entity.y
        self.target_xy = target_xy


    @property
    def target_actor(self) -> Optional[Actor]:
        # Returns actor at this actions destination
        return self.engine.game_map.get_actor_at_location(*self.target_xy)
    
    def perform(self) -> None:
        # Activate the spell (mana cost should be handled by caller)
        self.spell.activate(self)

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
            self.engine.game_world.descend()
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

    def __init__(self, entity: Actor, dx: int, dy: int, target_part: Optional['BodyPartType'] = None, tile_rel_pos: Optional[Tuple[float, float]] = None):
        super().__init__(entity, dx, dy)
        self.target_part = target_part
        self.tile_rel_pos = tile_rel_pos  # normalised (x, y) within target tile, 0.0–1.0

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
                self.engine.message_log.add_message("Your arrow hits an obstacle and breaks!", color.gray)
            else:
                self.engine.message_log.add_message("Your arrow hits an obstacle and falls to the ground.", color.gray)
                self._drop_projectile_at(collision_pos, None)
        elif collision_type == 'out_of_bounds':
            # Add projectile animation to edge of map
            import tcod.los
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), collision_pos).tolist())
            from animations import ThrowAnimation
            self.engine.animation_queue.append(ThrowAnimation(path, projectile_char, projectile_color))
            self.engine.message_log.add_message("Your arrow flies out of sight.", color.gray)
        elif collision_type == 'max_range':
            # Add projectile animation to max range
            import tcod.los
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), collision_pos).tolist())
            from animations import ThrowAnimation
            self.engine.animation_queue.append(ThrowAnimation(path, projectile_char, projectile_color))
            self.engine.message_log.add_message("Your arrow lands in the distance.", color.gray)
            self._drop_projectile_at(collision_pos, None)
        else:
            # No target found in range
            self.engine.message_log.add_message("Your arrow flies through empty air.", color.gray)

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
            self.engine.debug_log(f"Error creating dropped arrow: {e}", handler=type(self).__name__, event="_drop_projectile_at")
            # Silently fail if we can't create the arrow
    
    def _handle_actor_hit(self, target: Actor, shot_verb: str) -> None:
        """Handle hitting an actor with the projectile."""
        # Manipulation check
        for part in self.entity.body_parts.get_all_parts().values():
            if "manipulate" in part.tags:
                if part.damage_level_float >= 1.0:
                    self.entity.fighter._drop_grasped_items(part)
                elif part.damage_level_float > 0.5 and random.random() < 0.5:
                    self.entity.fighter._drop_grasped_items(part)

        # Apply mouse precision targeting if available
        if self.tile_rel_pos and not self.target_part:
            body_parts_comp = getattr(target, 'body_parts', None)
            if body_parts_comp:
                aimed = get_part_from_tile_position(body_parts_comp, *self.tile_rel_pos)
                if aimed:
                    dist_from_center = ((self.tile_rel_pos[0] - 0.5) ** 2 + (self.tile_rel_pos[1] - 0.5) ** 2) ** 0.5
                    accuracy_bonus = max(0.0, 1.0 - (dist_from_center / 0.5))
                    if accuracy_bonus > 0.6:
                        self.target_part = aimed.part_type

        hit_part, self.target_part, damage_modifier = _resolve_hit_part(target, self.target_part)

        # Calculate defense and damage
        armor_defense = 0
        if hit_part:
            base_defense = hit_part.protection + target.fighter.base_defense
            if target.equipment:
                armor_defense = target.equipment.get_defense_for_part(hit_part.name)
        else:
            base_defense = target.fighter.defense

        total_defense = base_defense + armor_defense
        base_damage = self.entity.fighter.power - total_defense
        final_damage = max(0, int(base_damage * damage_modifier))

        # Hit chance: BASE_HIT_RANGED (75 %), optionally scaled by mouse precision
        if self.tile_rel_pos:
            dist_from_center = ((self.tile_rel_pos[0] - 0.5) ** 2 + (self.tile_rel_pos[1] - 0.5) ** 2) ** 0.5
            accuracy_bonus = max(0.0, 1.0 - (dist_from_center / 0.5))
            hit_chance = BASE_HIT_RANGED * (0.8 + 0.4 * accuracy_bonus)
            hit_chance = min(hit_chance, 0.95)
        else:
            hit_chance = max(0.75, BASE_HIT_RANGED)
        hit_success = random.random() < hit_chance

        # Dodge calculation
        dodge_success = False
        if hit_success and random.random() < target.dodge_chance:
            if target.dodge_cooldown == 0:
                hit_success = False
                dodge_success = True
                target.dodge_cooldown = target.dodge_cooldown_max


        old_dodge_x, old_dodge_y = target.x, target.y
        dodge_dir = (0, 0)
        if dodge_success:
            adjacent_positions = [
                (target.x + 1, target.y), (target.x - 1, target.y),
                (target.x, target.y + 1), (target.x, target.y - 1),
            ]
            if target.preferred_dodge_direction:
                preferred_order = {
                    "north": [(target.x, target.y - 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y + 1)],
                    "south": [(target.x, target.y + 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y - 1)],
                    "east":  [(target.x + 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x - 1, target.y)],
                    "west":  [(target.x - 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x + 1, target.y)],
                }
                adjacent_positions = preferred_order.get(target.preferred_dodge_direction.lower(), adjacent_positions)
            gm = self.engine.game_map
            for new_x, new_y in adjacent_positions:
                if (gm.in_bounds(new_x, new_y)
                        and gm.tiles["walkable"][new_x, new_y]
                        and not gm.get_blocking_entity_at_location(new_x, new_y)):
                    DodgeAction(target, new_x - target.x, new_y - target.y).perform()
                    self.engine.message_log.add_message(f"{target.name} dodges to the side!", color.teal)
                    break
            self.engine.animation_queue.append(
                gpu_stack.DodgeParticle((old_dodge_x, old_dodge_y),
                                        character=target.char,
                                        direction=dodge_dir))

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
            #item_for_attack = self._get_ready_ranged_items()[0]  # Get the bow used for the attack

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
                except Exception:
                    # Silently fail if arrow recovery doesn't work
                    pass

            if target is self.engine.player:
                existing_bleed = next(
                    (a for a in self.engine.animation_queue
                     if isinstance(a, gpu_stack.CRTBleedAnim)), None
                )
                if existing_bleed is not None:
                    existing_bleed.frames = existing_bleed.total_frames
                else:
                    self.engine.animation_queue.append(gpu_stack.CRTBleedAnim())
                
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
                    self.engine.debug_log(f"Gained light armor XP from ranged: {int(armor_defense)}", handler=type(self).__name__, event="perform")

class DodgeAction(ActionWithDirection):
    """Dodge in a direction to attempt to avoid attacks, moving to an adjacent tile if successful."""

    def perform(self) -> None:
        
        if self.entity.dodge_cooldown > 0:
            raise exceptions.Impossible("Too tired to dodge!")
        else:
            target_x, target_y = self.dest_xy
            gm = self.engine.game_map

            if not gm.in_bounds(target_x, target_y):
                raise exceptions.Impossible("You can't dodge out of bounds!")
            if not gm.tiles["walkable"][target_x, target_y]:
                raise exceptions.Impossible("You can't dodge into a wall!")
            if gm.get_blocking_entity_at_location(target_x, target_y):
                raise exceptions.Impossible("You can't dodge into an obstacle!")
            sounds.play_miss_sound()
            self.entity.x = target_x
            self.entity.y = target_y
            import components.effect
            self.entity.effects.append(components.effect.TiredEffect(duration=self.entity.dodge_cooldown_max+1))
            self.engine.animation_queue.append(gpu_stack.DodgeParticle((target_x, target_y), character=self.entity.char, direction=(self.dx, self.dy)))
            self.entity.dodge_cooldown = self.entity.dodge_cooldown_max

class MeleeAction(ActionWithDirection):
    """Melee action that targets a specific body part."""

    def __init__(self, entity: Actor, dx: int, dy: int, target_part: Optional['BodyPartType'] = None, tile_rel_pos: Optional[Tuple[float, float]] = None):
        super().__init__(entity, dx, dy)
        self.target_part = target_part
        self.tile_rel_pos = tile_rel_pos  # normalised (x, y) within target tile, 0.0–1.0
    
    def perform(self) -> None:
        target = self.target_actor
        part_damage = 0

        # Direction: actual attacker→target vector when target exists, else tile dx/dy
        if target:
            slash_angle = (target.x - self.entity.x, target.y - self.entity.y)
        else:
            slash_angle = (self.dx, self.dy)

        if not target:
            x, y = self.target_location
            self.engine.animation_queue.append(gpu_stack.SlashParticle((x, y), enchanted=False, angle=slash_angle, type="miss"))
            sounds.play_miss_sound()
            raise exceptions.Impossible("Nothing to attack.")

        # Manipulation check – may drop held items if arms are damaged
        for part in self.entity.body_parts.get_all_parts().values():
            if "manipulate" in part.tags:
                if part.damage_level_float >= 1.0:
                    self.entity.fighter._drop_grasped_items(part)
                elif part.damage_level_float > 0.5 and random.random() < 0.5:
                    self.entity.fighter._drop_grasped_items(part)

        # Apply mouse precision targeting when the caller supplies a tile-relative cursor position
        if self.tile_rel_pos and not self.target_part:
            body_parts_comp = getattr(target, 'body_parts', None)
            if body_parts_comp:
                aimed = get_part_from_tile_position(body_parts_comp, *self.tile_rel_pos)
                if aimed:
                    dist_from_center = ((self.tile_rel_pos[0] - 0.5) ** 2 + (self.tile_rel_pos[1] - 0.5) ** 2) ** 0.5
                    accuracy_bonus = max(0.0, 1.0 - (dist_from_center / 0.5))
                    if accuracy_bonus > 0.6:
                        self.target_part = aimed.part_type

        # Resolve which body part is hit and its modifiers
        hit_part, self.target_part, damage_modifier = _resolve_hit_part(target, self.target_part)

        # Calculate localized defense
        armor_defense = 0
        if hit_part:
            base_defense = hit_part.protection + target.fighter.base_defense
            if target.equipment:
                armor_defense = target.equipment.get_defense_for_part(hit_part.name)
        else:
            base_defense = target.fighter.defense

        total_defense = base_defense + armor_defense
        base_damage = self.entity.fighter.power - total_defense
        final_damage = max(0, int(base_damage * damage_modifier))

        # Hit chance: BASE_HIT (90 %), optionally scaled by mouse‑precision accuracy bonus
        if self.tile_rel_pos:
            dist_from_center = ((self.tile_rel_pos[0] - 0.5) ** 2 + (self.tile_rel_pos[1] - 0.5) ** 2) ** 0.5
            accuracy_bonus = max(0.0, 1.0 - (dist_from_center / 0.5))
            hit_chance = BASE_HIT * (0.8 + 0.4 * accuracy_bonus)
            hit_chance = min(hit_chance, 0.95)
        else:
            hit_chance = max(0.75, BASE_HIT)
        hit_success = random.random() < hit_chance

        # Dodge check
        dodge_success = False
        if hit_success and random.random() < target.dodge_chance:
            hit_success = False
            dodge_success = True

        # Dodge – move target to an adjacent free tile
        old_dodge_x, old_dodge_y = target.x, target.y
        dodge_dir = (0, 0)
        if dodge_success:
            adjacent_positions = [
                (target.x + 1, target.y), (target.x - 1, target.y),
                (target.x, target.y + 1), (target.x, target.y - 1),
            ]
            if target.preferred_dodge_direction:
                preferred_order = {
                    "north": [(target.x, target.y - 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y + 1)],
                    "south": [(target.x, target.y + 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y - 1)],
                    "east":  [(target.x + 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x - 1, target.y)],
                    "west":  [(target.x - 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x + 1, target.y)],
                }
                adjacent_positions = preferred_order.get(target.preferred_dodge_direction.lower(), adjacent_positions)
            gm = self.engine.game_map
            for new_x, new_y in adjacent_positions:
                if (gm.in_bounds(new_x, new_y)
                        and gm.tiles["walkable"][new_x, new_y]
                        and not gm.get_blocking_entity_at_location(new_x, new_y)):
                    DodgeAction(target, new_x - target.x, new_y - target.y).perform()
                    self.engine.animation_queue.append(
                        gpu_stack.DodgeParticle((old_dodge_x, old_dodge_y),
                                                character=target.char,
                                                direction=dodge_dir))
                    self.engine.message_log.add_message(f"{target.name} dodges to the side!", color.teal)
                    break

        # --- Weapon / verb resolution ---
        weapon_verb = None
        weapon = None
        equipped_weapons: list = []

        if self.entity.equipment:
            eq = self.entity.equipment
            # Collect all weapons from body_part_coverage (primary system)
            for item in eq.body_part_coverage.values():
                if item and getattr(item, 'equippable', None) and item.equippable.equipment_type.name == 'WEAPON':
                    equipped_weapons.append(item)

            # Prefer enchanted; otherwise first found
            weapon = next((w for w in equipped_weapons if getattr(w, 'enchantments', None)), None)
            if weapon is None and equipped_weapons:
                weapon = equipped_weapons[0]

            # Legacy fallback
            if weapon is None:
                for eq_type, item in eq.equipped_items.items():
                    if item and eq_type == 'WEAPON':
                        weapon = item
                        break

            # Extract verb from the chosen weapon
            if weapon:
                if getattr(weapon, 'verb_present', None):
                    weapon_verb = weapon.verb_present
                elif getattr(weapon, 'verb_base', None):
                    weapon_verb = weapon.verb_base + "s"

        # Fall back to entity verb
        if not weapon_verb:
            if getattr(self.entity, 'verb_present', None):
                weapon_verb = self.entity.verb_present
            elif getattr(self.entity, 'verb_base', None):
                weapon_verb = self.entity.verb_base + "s"
        if not weapon_verb:
            weapon_verb = "attacks"

        # Build attack description
        if hit_part:
            attack_desc = f"{self.entity.name.capitalize()} {weapon_verb} {target.name}'s {hit_part.name}"
        else:
            attack_desc = f"{self.entity.name.capitalize()} {weapon_verb} {target.name}"

        # Sounds
        if hit_success:
            if final_damage > 0:
                if target.fighter.hp <= final_damage:
                    sounds.play_attack_sound_finishing_blow()
                elif self.entity.equipment and target.equipment and target.equipment.equipped_items.get('ARMOR'):
                    sounds.play_attack_sound_weapon_to_armor()
                else:
                    sounds.play_attack_sound_weapon_to_no_armor()
            else:
                sounds.play_block_sound()
        else:
            sounds.play_miss_sound()

        # Animation
        if hit_success:
            self.engine.animation_queue.append(gpu_stack.SlashParticle((target.x, target.y), enchanted=False, angle=slash_angle, type=weapon_verb))

        attack_color = color.player_atk if self.entity is self.engine.player else color.enemy_atk

        # --- Outcome messages and damage ---
        if not hit_success:
            msg = (f"{attack_desc}, but {target.name} dodges!" if dodge_success
                   else f"{attack_desc}, but misses!")
            if dodge_success:
                self.engine.animation_queue.append(
                    gpu_stack.DodgeParticle((old_dodge_x, old_dodge_y),
                                            character=target.char,
                                            direction=dodge_dir))
            self.engine.animation_queue.append(gpu_stack.SlashParticle((target.x, target.y), enchanted=False, angle=slash_angle, type="miss"))
            self.engine.message_log.add_message(msg, color.teal if dodge_success else color.dark_gray)

        elif final_damage > 0:
            # Enchantment on-hit effects
            if weapon and getattr(weapon, 'enchantments', None):
                for enchantment in weapon.enchantments:
                    enchantment.on_hit(self.engine, target, hit_part)
                    self.engine.animation_queue.append(
                        gpu_stack.SlashParticle((target.x, target.y), enchanted=True, color=enchantment.get_color(), angle=slash_angle, type=weapon_verb)
                    )

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

            if target is self.engine.player:
                existing_bleed = next(
                    (a for a in self.engine.animation_queue
                     if isinstance(a, gpu_stack.CRTBleedAnim)), None
                )
                if existing_bleed is not None:
                    existing_bleed.frames = existing_bleed.total_frames
                else:
                    self.engine.animation_queue.append(gpu_stack.CRTBleedAnim())
        else:
            self.engine.message_log.add_message(
                f"{attack_desc}, but does no damage.", attack_color
            )

        # --- XP (batched into single calls) ---
        if part_damage > 0:
            # Attacker weapon XP
            attacker_xp: dict = {}
            for w in equipped_weapons:
                w_tags = getattr(w, 'tags', ())
                if "blade" in w_tags:
                    attacker_xp['blades'] = attacker_xp.get('blades', 0) + part_damage
                if "dagger" in w_tags:
                    attacker_xp['daggers'] = attacker_xp.get('daggers', 0) + part_damage
            if attacker_xp:
                self.entity.level.add_xp(attacker_xp)

            # Defender XP
            defender_xp = {'vigor': part_damage * 2}
            if armor_defense > 0 and hit_part:
                armor_tags = target.equipment.get_armor_tags_for_part(hit_part.name) if target.equipment else []
                if armor_tags is not None:
                    if "light armor" in armor_tags:
                        defender_xp['light armor'] = int(armor_defense * 1.5)
            if target.level is not None:
                target.level.add_xp(defender_xp)

class MovementAction(ActionWithDirection):

    def _update_swim_state(self, dest_x: int, dest_y: int) -> None:
        """Switch swimming state only on transition, not every frame."""
        tile_name = self.engine.game_map.tiles["name"][dest_x, dest_y]
        is_water = tile_name == "Water"
        was_swimming = getattr(self.entity, "is_swimming", False)

        if is_water and not was_swimming:
            self.entity.is_swimming = True
            if hasattr(self.entity, "ai") and self.entity.ai is not None:
                self.entity.ai.swim()

        elif not is_water and was_swimming:
            self.entity.is_swimming = False
            # Restore the normal sprite once when leaving water.
            sprite_manager.refresh_actor_sprite(self.entity)

        else:
            self.entity.is_swimming = is_water

    def perform(self) -> None:
        self.entity.dodge_cooldown = max(0, self.entity.dodge_cooldown - 1)
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
                self.engine.turn_count += 1
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
                    elif tile_name == "Mossy Floor":
                        sounds.play_movement_sound_at(sounds.play_moss_walk_sound, dest_x, dest_y, self.engine.player, self.engine.game_map)
                    elif tile_name == "Water":
                        self._update_swim_state(dest_x, dest_y)
                        sounds.play_movement_sound_at(sounds.play_swim_sound, dest_x, dest_y, self.engine.player, self.engine.game_map)
                    else:
                        self._update_swim_state(dest_x, dest_y)
                        sounds.play_movement_sound_at(sounds.play_walk_sound, dest_x, dest_y, self.engine.player, self.engine.game_map)

        # Track swimming state transitions based on tile content. This avoids per-frame sprite resets.
        self._update_swim_state(dest_x, dest_y)

        # If not in view, display sound tile animation (for all entities)
        from animations import HeardSoundAnimation
        if not self.engine.game_map.visible[dest_x, dest_y]:
            # Use different color for enemy footsteps vs other sounds
            if self.entity != self.engine.player:
                color = (255, 255, 255)  # Gray for footsteps
            else:
                color = (255, 255, 0)  # Yellow for other sounds
            self.engine.animation_queue.append(HeardSoundAnimation((dest_x, dest_y), self.engine.player, color, (self.dx, self.dy)))
        
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
                    elif tile_name == "Mossy Floor":
                        sounds.play_moss_walk_sound()
                    elif tile_name == "Water":
                        self._update_swim_state(dest_x, dest_y)
                        sounds.play_swim_sound()
                    elif tile_name == "Floor":
                        self._update_swim_state(dest_x, dest_y)
                        sounds.play_walk_sound()


class MoveToAction(Action):
    """Pathfinds to a destination and auto-moves the player one step per turn."""

    def __init__(self, entity: Actor, dest_x: int, dest_y: int):
        super().__init__(entity)
        self.dest_x = dest_x
        self.dest_y = dest_y

    def perform(self) -> None:
        import numpy as np
        import tcod.path

        dest_x, dest_y = self.dest_x, self.dest_y
        game_map = self.engine.game_map

        if not game_map.in_bounds(dest_x, dest_y):
            raise exceptions.Impossible("That location is out of bounds.")

        if not game_map.explored[dest_x, dest_y]:
            raise exceptions.Impossible("You haven't explored that area.")

        # Build cost array restricted to walkable + explored tiles
        cost = np.array(game_map.tiles["walkable"], dtype=np.int8)
        cost &= game_map.explored.astype(np.int8)

        graph = tcod.path.SimpleGraph(cost=cost, cardinal=2, diagonal=3)
        pathfinder = tcod.path.Pathfinder(graph)
        pathfinder.add_root((self.entity.x, self.entity.y))
        raw_path = pathfinder.path_to((dest_x, dest_y))[1:].tolist()

        if not raw_path:
            raise exceptions.Impossible("No path to that location.")

        # Store remaining steps on the engine for subsequent turns
        self.engine.auto_move_path = [tuple(p) for p in raw_path[1:]]

        # Take the first step immediately (this turn)
        first = raw_path[0]
        MovementAction(self.entity, first[0] - self.entity.x, first[1] - self.entity.y).perform()


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
        actor = self.target_actor
        if actor and getattr(actor, "blocks_movement", True):
            return MeleeAction(self.entity, self.dx, self.dy).perform()
        else:
            return MovementAction(self.entity, self.dx, self.dy).perform()
        

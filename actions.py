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
                
                if len(container.items) == 0:
                    empty_msg = "There is nothing left to loot." if is_corpse else "The chest is empty."
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
                sounds.play_door_open_sound()
                self.engine.message_log.add_message("You open the door.")

            elif name == "Open Door":
                # Convert "Open Door" tile to "Door" tile
                import tile_types
                self.engine.game_map.tiles[target_x, target_y] = tile_types.closed_door
                sounds.play_door_close_sound()
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
    def target_actor(self) -> Optional[Actor]:
        #Return the actor at actions dest.
        return self.engine.game_map.get_actor_at_location(*self.dest_xy)

    def perform(self) -> None:
        raise NotImplementedError()
    


class MeleeAction(ActionWithDirection):
    """Melee action that targets a specific body part."""
    
    def __init__(self, entity: Actor, dx: int, dy: int, target_part: Optional['BodyPartType'] = None):
        super().__init__(entity, dx, dy)
        self.target_part = target_part
    
    def perform(self) -> None:
        target = self.target_actor

        # Check for target
        if not target:
            raise exceptions.Impossible("Nothing to attack.")
        
        # Manipulation check
        for part in self.entity.body_parts.get_all_parts().values():
            if "manipulate" in part.tags:
                if part.damage_level_float > 0.5:
                    if random.random() < 0.5:
                        self.entity.fighter._drop_grasped_items(part)
                    print("DEBUG: Manipulation partially impaired by damage to part:", part.name)
                elif part.damage_level_float >= 1.0:
                    self.entity.fighter._drop_grasped_items(part)
                else:
                    print("DEBUG: Manipulation possible with part:", part.name)

        
        # Base damage calculation
        base_damage = self.entity.fighter.power - target.fighter.defense
        
        # Get target body part and apply targeting effects
        hit_part = None
        damage_modifier = 1.0
        hit_difficulty_modifier = 0.0  # Positive = easier to hit, negative = harder

        # Body part targeting modifiers (damage_modifier, hit_difficulty_modifier)
        BODY_PART_MODIFIERS = {
            "HEAD": (1.5, -30),    # 50% more damage to head, much harder to hit
            "TORSO": (1.0, 15),    # Normal damage, easier to hit (large target)
            "LEG": (0.9, -5),      # Slightly less damage, slightly harder to hit
            "ARM": (0.9, -10),     # Slightly less damage, harder to hit  
            "HAND": (0.8, -25),    # Reduced damage, very hard to hit
            "FOOT": (0.8, -25),    # Reduced damage, very hard to hit
        }

        # Check if any part is targeted
        #print("DEBUG: target_part:", self.target_part)
        if not self.target_part:
            # If no part targeted, use the existing random part selection
            if hasattr(target, 'body_parts'):
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
        
        # Calculate final damage
        final_damage = max(0, int(base_damage * damage_modifier))
        print(f"DEBUG: hit_part={hit_part.name if hit_part else None}, final_damage={final_damage}")
        
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
        if self.entity.equipment and self.entity.equipment.weapon:
            weapon = self.entity.equipment.weapon
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
            if target.fighter.hp - final_damage <= 0:
                sounds.play_attack_sound_finishing_blow()
            elif self.entity.equipment:
                if target.equipment and target.equipment.armor:
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
        from animations import SlashAnimation
        if hit_success:
            self.engine.animation_queue.append(SlashAnimation(target.x, target.y))

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
                target.fighter.take_damage(part_damage, targeted_part=self.target_part)
                
                # Special messages for different damage levels
                if hit_part.is_destroyed:
                    self.engine.message_log.add_message(
                        f"{attack_desc} and destroys it for {part_damage} damage!", color.red
                    )
                else:
                    self.engine.message_log.add_message(
                        f"{attack_desc} for {part_damage} damage.", attack_color
                    )
            else:
                # This should never happen - but adding for debugging
                print(f"ERROR: No valid body part found! target_part={self.target_part}, has_body_parts={hasattr(target, 'body_parts')}")
                target.fighter.take_damage(final_damage)
                self.engine.message_log.add_message(
                    f"{attack_desc} for {final_damage} hit points. [NO BODY PART ERROR]", color.red
                )
            
            # Trigger damage indicator if player takes damage
            if target is self.engine.player:
                self.engine.trigger_damage_indicator()
        else:
            self.engine.message_log.add_message(
                f"{attack_desc}, but does no damage.", attack_color
            )

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
        
        # Only play walk sound if not moving rapidly or holding key
        if self.engine.should_play_movement_sound():
            sounds.play_walk_sound()


class BumpAction(ActionWithDirection):
    def perform(self) -> None:
        if self.target_actor:
            return MeleeAction(self.entity, self.dx, self.dy).perform()
        else:
            return MovementAction(self.entity, self.dx, self.dy).perform()
        

from __future__ import annotations

import random
from typing import List, Tuple, Optional, TYPE_CHECKING

import numpy as np
import tcod

from actions import Action, MeleeAction, BumpAction, MovementAction, WaitAction, RangedAction

import color
import sounds
from components.effect import has_effect_name, is_invisible, InvisibilityEffect

from languages import generate_sentence


if TYPE_CHECKING:
    from entity import Actor


# ========================================
# PHASING / INVISIBILITY HELPERS
# ========================================

def apply_phasing_effect(actor: "Actor", duration: int = None) -> bool:
    """Apply invisibility effect to simulate phasing.
    
    Args:
        actor: The actor to apply phasing to
        duration: How long the phasing lasts (None = permanent until broken)
        
    Returns:
        True if effect was applied, False if already phasing
    """
    if has_phasing_effect(actor):
        return False  # Already phasing
    
    effects = getattr(actor, "effects", None) or []
    phasing = InvisibilityEffect(duration=duration)
    phasing.parent = actor
    effects.append(phasing)
    actor.effects = effects
    return True


def has_phasing_effect(actor: "Actor") -> bool:
    """Check if actor is currently phasing (has invisibility effect).
    
    Returns:
        True if actor has the invisibility/phasing effect
    """
    return is_invisible(actor)


def remove_phasing_effect(actor: "Actor") -> bool:
    """Remove phasing effect from actor.
    
    Returns:
        True if an effect was removed, False if no phasing effect existed
    """
    effects = getattr(actor, "effects", None) or []
    remaining = [
        e for e in effects
        if str(getattr(e, "name", "")).strip().lower() not in {"invisible", "invisibility"}
    ]
    if len(remaining) != len(effects):
        actor.effects = remaining
        return True
    return False

class BaseAI(Action):

    def __init__(self, entity: "Actor"):
        super().__init__(entity)
        # Track doors that this AI has opened and should close
        self.opened_doors: List[Tuple[int, int]] = []
        # Track the entity's last position to detect when they've moved through a door
        self.last_position: Optional[Tuple[int, int]] = None
        self.type: str = "BaseAI"
        # Movement speed system: higher values = slower movement
        # 1 = normal speed (moves every turn), 2 = half speed (moves every 2 turns)
        self.movement_speed: int = 2
        self.movement_counter: int = 0


    def say(self, context: Optional[str] = "idle", custom: Optional[str] = None) -> None:
        if (self.entity.name == "Goblin" or self.entity.name == "Troll"):
            say = generate_sentence(context , "goblin", known=False)
            from render_functions import SpeechBubble
            self.engine.speech_bubbles.append(SpeechBubble(self.entity, 90))
            self.engine.message_log.add_message(f"{self.entity.name}: '{say}'", color.green)
        if (self.entity.name == "The Guide"):
            from render_functions import SpeechBubble
            self.engine.speech_bubbles.append(SpeechBubble(self.entity, 90))
            if custom:
                self.engine.message_log.add_message(f"{self.entity.name}: '{custom}'", color.gold_accent)
            else:
                pass


    def perform(self) -> None:
        pass

    def swim(self):
        from render_functions import SwimmingAnimation
        self.engine.swimming_entities.append(SwimmingAnimation(self.entity))

    
    def should_move_this_turn(self) -> bool:
        """Check if this AI should move this turn based on movement speed."""
        self.movement_counter += 1
        if self.movement_counter >= self.movement_speed:
            self.movement_counter = 0
            return True
        return False
    
    def select_target(self) -> "Actor":
        """Select best target, preferring nearby decoys over the player.
        
        Returns the player by default, but if there are visible decoys/illusions
        that are closer or equally close, target them instead.
        """
        target = self.engine.player
        
        # Check for nearby illusions/decoys
        for actor in self.engine.game_map.actors:
            if actor != self.entity and getattr(actor, 'is_decoy', False):
                if self.can_see_actor(actor) and actor.is_alive:
                    # Calculate distances
                    decoy_distance = max(abs(actor.x - self.entity.x), abs(actor.y - self.entity.y))
                    player_distance = max(abs(target.x - self.entity.x), abs(target.y - self.entity.y))
                    # Prefer decoy if it's closer or same distance (50% chance for variety)
                    if decoy_distance < player_distance or (decoy_distance == player_distance and random.random() < 0.5):
                        target = actor
                        break
        
        return target
    
    def get_path_to(self, dest_x: int, dest_y: int) -> List[Tuple[int, int]]:
        
        # Create cost array where walkable tiles cost 1, non-walkable cost 0 (impassable)
        cost = np.array(self.entity.gamemap.tiles["walkable"], dtype=np.int8)
        
        # Make closed doors walkable for pathfinding purposes (AI will handle opening them)
        # This allows AI to plan paths through doors without making them expensive
        door_mask = self.entity.gamemap.tiles["name"] == "Door"
        cost[door_mask] = 1  # Treat doors as walkable for pathfinding

        for entity in self.entity.gamemap.entities:
            if entity.blocks_movement and cost[entity.x, entity.y]:
                cost[entity.x, entity.y] += 10

        graph = tcod.path.SimpleGraph(cost=cost, cardinal=2, diagonal=3)
        pathfinder = tcod.path.Pathfinder(graph)

        pathfinder.add_root((self.entity.x, self.entity.y))

        path: List[List[int]] = pathfinder.path_to((dest_x, dest_y))[1:].tolist()

        return [(index[0], index[1]) for index in path]

    def is_door_tile(self, x: int, y: int) -> bool:
        """Check if the tile at (x, y) is a closed/open door."""
        try:
            if not self.entity.gamemap.in_bounds(x, y):
                return False
            tile_name = self.entity.gamemap.tiles["name"][x, y]
            return tile_name in ["Door", "Open Door"]
        except Exception:
            return False

    def can_open_door(self, x: int, y: int) -> bool:
        """Check if this AI can open a door at the given position."""
        if not self.entity.gamemap.in_bounds(x, y):
            return False
            
        # Check if it's a door
        tile_name = self.entity.gamemap.tiles["name"][x, y]
        if tile_name not in ["Door", "Open Door"]:
            return False
            
        # Check if adjacent (including diagonals)
        dx = abs(self.entity.x - x)
        dy = abs(self.entity.y - y)
        return dx <= 1 and dy <= 1 and (dx + dy) > 0

    def toggle_door_at(self, x: int, y: int) -> bool:
        """Try to toggle a door at the given position. Returns True if successful."""
        if not self.can_open_door(x, y):
            return False
            
        tile_name = self.entity.gamemap.tiles["name"][x, y]
        
        # Use tile interaction system to toggle door
        import tile_functions
        result = tile_functions.toggle_door(self.entity.gamemap.engine, self.entity, x, y)
        
        if result is not None:
            # Play sound and track door state
            if tile_name == "Door":  # Was closed, now opened
                sounds.play_door_open_sound_at(x, y, self.entity.gamemap.engine.player, self.entity.gamemap)
                self.opened_doors.append((x, y))
            elif tile_name == "Open Door":  # Was open, now closed
                sounds.play_door_close_sound_at(x, y, self.entity.gamemap.engine.player, self.entity.gamemap)
                if (x, y) in self.opened_doors:
                    self.opened_doors.remove((x, y))
            return True
            
        return False

    def close_door_at(self, x: int, y: int) -> bool:
        """Try to close a door at the given position. Returns True if successful."""
        if not self.entity.gamemap.in_bounds(x, y):
            return False
            
        # Must be an open door
        if self.entity.gamemap.tiles["name"][x, y] != "Open Door":
            return False
            
        # Can't close if something is blocking it
        if self.entity.gamemap.get_blocking_entity_at_location(x, y):
            return False
            
        # Use tile interaction system to close door
        import tile_functions
        result = tile_functions.close_door(self.entity.gamemap.engine, self.entity, x, y)
        
        if result is not None:
            sounds.play_door_close_sound_at(x, y, self.entity.gamemap.engine.player, self.entity.gamemap)
            return True
            
        return False

    def check_and_close_doors(self) -> bool:
        """Close doors that AI has moved away from. Returns True if any doors were closed."""
        if not self.opened_doors:
            return False
            
        doors_closed = False
        current_pos = (self.entity.x, self.entity.y)
        
        # Check each opened door
        for door_pos in list(self.opened_doors):  # Copy list to avoid modification during iteration
            door_x, door_y = door_pos
            
            # Calculate distance (Chebyshev distance)
            distance = max(abs(current_pos[0] - door_x), abs(current_pos[1] - door_y))
            
            # Close door if we're more than 1 tile away
            if distance > 1:
                if self.close_door_at(door_x, door_y):
                    doors_closed = True
                # Remove from tracking regardless of success (might be blocked)
                self.opened_doors.remove(door_pos)
                
        return doors_closed

    def get_path_with_doors(self, dest_x: int, dest_y: int) -> List[Tuple[int, int]]:
        """Get path to destination, treating closed doors as walkable (AI can open them)."""
        try:
            # Create a modified walkable array that treats closed doors as walkable
            cost = np.array(self.entity.gamemap.tiles["walkable"], dtype=np.int8)
            
            # Mark closed doors as walkable (but with higher cost)
            door_mask = self.entity.gamemap.tiles["name"] == "Door"
            cost[door_mask] =  5  # Higher cost than normal movement but still walkable

            # Mark opened doors as normal walkable
            open_door_mask = self.entity.gamemap.tiles["name"] == "Open Door"
            cost[open_door_mask] = 1  # Normal walkable cost
            
            # Add entity blocking costs
            for entity in self.entity.gamemap.entities:
                if entity.blocks_movement and cost[entity.x, entity.y]:
                    cost[entity.x, entity.y] += 10

            graph = tcod.path.SimpleGraph(cost=cost, cardinal=2, diagonal=3)
            pathfinder = tcod.path.Pathfinder(graph)

            pathfinder.add_root((self.entity.x, self.entity.y))

            path: List[List[int]] = pathfinder.path_to((dest_x, dest_y))[1:].tolist()

            return [(index[0], index[1]) for index in path]
        except Exception:
            # Fallback to regular pathfinding
            return self.get_path_to(dest_x, dest_y)

    def can_see_actor(self, actor: "Actor", radius: Optional[int] = None) -> bool:
        """Compute an FOV from this entity and return True if it can see `actor`.

        Uses tcod.map.compute_fov on the game map's transparency mask. If the
        actor or map is unavailable, returns False. The radius defaults to the
        entity's `sight_radius` attribute if present, otherwise 6.
        """
        try:

            gm = self.entity.gamemap
            if radius is None:
                radius = getattr(self.entity, "sight_radius", 6)

            # Check if target actor is in darkness (harder to see)
            target_in_darkness = has_effect_name(actor, "Darkness")
            if is_invisible(actor):
                return False  # Can't see invisible actors at all
            if target_in_darkness:
                radius = max(1, radius - 4)  # Significantly reduced sight range in darkness
            
            
            # Check if this entity itself is in darkness (reduced sight) FUTURE IMPLEMENT
            #self_in_darkness = any(getattr(e, "name", "") == "Darkness" for e in getattr(self.entity, "effects", []))
            #if self_in_darkness:
            #    radius = max(1, radius - 2)  # Self in darkness also reduces sight

            fov = tcod.map.compute_fov(gm.tiles["transparent"], (self.entity.x, self.entity.y), radius)
            
            return bool(fov[actor.x, actor.y])
        except Exception:
            return False

class ConfusedEnemy(BaseAI):
    # Will stumble around for a number of turns, it will attack if it bumps into you

    def __init__(
            self, entity: Actor, previous_ai: Optional[BaseAI], turns_remaining: int
    ):
        super().__init__(entity)

        self.previous_ai = previous_ai
        self.turns_remaining = turns_remaining

    def perform(self) -> None:
        # Reverts ai to original state after course has run

        if self.turns_remaining <= 0:
            self.engine.message_log.add_message(
                f"The {self.entity.name} is no longer confused!"
            )
            self.entity.ai = self.previous_ai

        else:
            direction_X, direction_y = random.choice(
                [
                    (-1, -1),  # Northwest
                    (0, -1),  # North
                    (1, -1),  # Northeast
                    (-1, 0),  # West
                    (1, 0),  # East
                    (-1, 1),  # Southwest
                    (0, 1),  # South
                    (1, 1),  # Southeast
                ]
            )

            self.turns_remaining -= 1

            return BumpAction(self.entity, direction_X, direction_y).perform()



class HostileEnemy(BaseAI):
    def __init__(self, entity: Actor):
        super().__init__(entity)
        self.path: List[Tuple[int, int]] = []
        # Simple wandering behavior
        self.wander_wait_turns = random.randint(0, 2)
        self.wander_range = 10
        # Initialize home position as None - will be set on first use to actual spawn position
        self.home_x = None
        self.home_y = None
        # Normal speed
        self.movement_speed = 1
        self.movement_counter = 0
        self.last_saw_player = -99999999999999 # Tracks turns since last saw player


    

    def perform(self) -> None:
        # Move every turn
        if not self.should_move_this_turn():
            return WaitAction(self.entity).perform()
            
        self.check_and_close_doors()
        
        # Initialize home position on first move to capture actual spawn location
        if self.home_x is None or self.home_y is None:
            self.home_x = self.entity.x
            self.home_y = self.entity.y
        
        # Select target (player or nearby decoy/illusion)
        target = self.select_target()
        
        dx = target.x - self.entity.x
        dy = target.y - self.entity.y
        distance = max(abs(dx), abs(dy))
        
        # Chase player if visible
        if self.can_see_actor(target):
            if self.last_saw_player < 0:
                if self.last_saw_player < -99999:
                    if random.random() < 0.5:
                        self.say("observe")

 
            self.wander_wait_turns = 0
            self.path = []
            self.last_saw_player = 0
            
            if distance <= 1:
                return MeleeAction(self.entity, dx, dy).perform()
            
            self.path = self.get_path_with_doors(target.x, target.y)
        else:
            # Lost line-of-sight (including invisibility): drop stale chase path.
            if self.last_saw_player == 0:
                self.path = []
            self.last_saw_player += 1
            # Wander when player not visible
            if self.wander_wait_turns > 0:
                self.wander_wait_turns -= 1
                return WaitAction(self.entity).perform()
            
            if not self.path:
                # Simple wandering: pick random destination near home
                dest_x = self.home_x + random.randint(-self.wander_range, self.wander_range)
                dest_y = self.home_y + random.randint(-self.wander_range, self.wander_range)
                
                if (0 <= dest_x < self.engine.game_map.width and
                    0 <= dest_y < self.engine.game_map.height and
                    self.engine.game_map.tiles["walkable"][dest_x, dest_y]):
                    
                    self.path = self.get_path_with_doors(dest_x, dest_y)
                
                if not self.path:
                    self.wander_wait_turns = random.randint(1, 3)
                    return WaitAction(self.entity).perform()
        
        # Move along path
        if self.path:
            dest_x, dest_y = self.path.pop(0)
            
            # Handle door opening with sound
            if self.entity.gamemap.tiles["name"][dest_x, dest_y] == "Door":
                if self.toggle_door_at(dest_x, dest_y):
                    return WaitAction(self.entity).perform()
                else:
                    self.path = []
                    self.wander_wait_turns = random.randint(1, 2)
                    return WaitAction(self.entity).perform()
            
            # Move
            result = MovementAction(
                self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
            ).perform()
            
            # Set wait time after reaching destination
            if not self.path:
                self.wander_wait_turns = random.randint(1, 3)
            
            return result
        
        return WaitAction(self.entity).perform()

class SplittingEnemyAI(HostileEnemy):
    """AI that splits into smaller enemies when below half health."""
    def __init__(self, entity: "Actor"):
        super().__init__(entity)
        self.has_split = False
        self.type = "SplittingEnemyAI"

    def perform(self) -> None:
        # Check health and split FIRST, before any other logic
        if not self.has_split and self.entity.fighter and self.entity.fighter.hp < self.entity.fighter.max_hp / 2:
            self.has_split = True
            print(f"[AI] {self.entity.name} is splitting into smaller enemies!")
            # Create two smaller enemies at the current location
            for foo in range(2):
                # check if is slime
                if self.entity.name == "Gelatinous Cube":
                    from entity import Actor
                    from components.fighter import Fighter
                    from components.body_parts import BodyParts, AnatomyType
                    template = Actor(
                        char=chr(0xE045),
                        color=(color.sprite_sheet),
                        name="Gelatinous Fragment",
                        ai_cls=HostileEnemy,
                        equipment=self.entity.equipment,
                        fighter=Fighter(hp=(self.entity.fighter.hp / 2), base_defense=1, base_power=4, can_bleed=False, leave_corpse=False),
                        inventory=None,
                        level=None,
                        speed=50,
                        body_parts=BodyParts(AnatomyType.SIMPLE, max_hp=(self.entity.fighter.hp / 2)),
                        verb_base="ooze",
                        verb_present="oozes",
                        verb_past="oozed",
                        verb_participial="oozing",
                        dodge_chance=0.05,
                        equipment_table={},
                    )
                    import copy
                    push = copy.deepcopy(template)
                    
                    if foo == 0:
                        # First spawn: at mother's position
                        dest_x = self.entity.x
                        dest_y = self.entity.y
                        if (0 <= dest_x < self.engine.game_map.width and
                            0 <= dest_y < self.engine.game_map.height and
                            self.engine.game_map.tiles["walkable"][dest_x, dest_y]):
                            push.x = dest_x
                            push.y = dest_y
                            push.spawn(self.engine.game_map, dest_x, dest_y)
                    else:
                        # Second spawn: find adjacent tile
                        spawned = False
                        for dx in range(-1, 2):
                            for dy in range(-1, 2):
                                if (dx == 0 and dy == 0):
                                    continue
                                dest_x = self.entity.x + dx
                                dest_y = self.entity.y + dy
                                if (0 <= dest_x < self.engine.game_map.width and
                                    0 <= dest_y < self.engine.game_map.height and
                                    self.engine.game_map.tiles["walkable"][dest_x, dest_y] and
                                    not self.engine.game_map.get_blocking_entity_at_location(dest_x, dest_y)):
                                    push.x = dest_x
                                    push.y = dest_y
                                    push.spawn(self.engine.game_map, dest_x, dest_y)
                                    spawned = True
                                    break
                            if spawned:
                                break
            
            # Delete original entity after both spawns are complete
            self.engine.message_log.add_message(f"The {self.entity.name} splits into smaller fragments!", color.orange)
            self.engine.game_map.entities.remove(self.entity)
            # Don't continue with normal behavior after splitting - entity is dead
            return
        
        # Only continue with normal hostile behavior if we haven't split
        return super().perform()

class PhasingAI(HostileEnemy):
    """Strategic AI for creatures that can phase/become invisible.
    
    Behavior:
    - Maintains invisibility while approaching the player stealthily
    - Attacks when adjacent (which breaks invisibility via action system)
    - Attempts to re-phase after attacking to retreat and reposition
    - Falls back to regular hostile behavior if can't phase
    
    This AI is modular and works with the existing invisibility effect system.
    """
    
    def __init__(self, entity: "Actor"):
        super().__init__(entity)
        self.phasing_cooldown = 0  # Turns until phasing can be reapplied
        self.phasing_cooldown_max = 3  # How many turns before can phase again
        self.type = "PhasingAI"
    
    def perform(self) -> None:
        """Override to add phasing logic before parent behavior."""
        # Decrement cooldown each turn
        if self.phasing_cooldown > 0:
            self.phasing_cooldown -= 1
        
        # Move every turn (inherited speed control)
        if not self.should_move_this_turn():
            return WaitAction(self.entity).perform()
        
        self.check_and_close_doors()
        
        # Initialize home position on first move
        if self.home_x is None or self.home_y is None:
            self.home_x = self.entity.x
            self.home_y = self.entity.y
        
        # Select target (player or nearby decoy/illusion)
        target = self.select_target()
        dx = target.x - self.entity.x
        dy = target.y - self.entity.y
        distance = max(abs(dx), abs(dy))
        
        # If not currently phasing and cooldown expired, try to phase
        if not has_phasing_effect(self.entity) and self.phasing_cooldown == 0:
            # Re-apply phasing to retreat/reposition (lasts multiple turns)
            if apply_phasing_effect(self.entity, duration=5):
                # Phasing was successful; use it as ambush tactics
                pass  # Will continue moving while invisible below
        
        # Chase player if visible
        if self.can_see_actor(target):
            # Player detected - maintain approach (phasing keeps us undetectable)
            self.wander_wait_turns = 0
            self.path = []
            self.last_saw_player = 0
            
            if distance <= 1:
                # Adjacent to player - attack!
                # Explicitly break invisibility before attacking to ensure it's visible
                remove_phasing_effect(self.entity)
                
                result = MeleeAction(self.entity, dx, dy).perform()
                
                # After attack, trigger cooldown so we can't immediately re-phase
                self.phasing_cooldown = self.phasing_cooldown_max
                
                return result
            
            # Not adjacent yet - keep approaching (invisibly, if phasing active)
            self.path = self.get_path_with_doors(target.x, target.y)
        else:
            # Lost line-of-sight: drop stale path
            if self.last_saw_player == 0:
                self.path = []
            self.last_saw_player += 1
            
            # Wander when player not visible (while phasing if active)
            if self.wander_wait_turns > 0:
                self.wander_wait_turns -= 1
                return WaitAction(self.entity).perform()
        
        # Wander if no path (similar to parent, but maintains phasing)
        if not self.path:
            dest_x = self.home_x + random.randint(-self.wander_range, self.wander_range)
            dest_y = self.home_y + random.randint(-self.wander_range, self.wander_range)
            
            if (0 <= dest_x < self.engine.game_map.width and
                0 <= dest_y < self.engine.game_map.height and
                self.engine.game_map.tiles["walkable"][dest_x, dest_y]):
                
                self.path = self.get_path_with_doors(dest_x, dest_y)
            
            if not self.path:
                self.wander_wait_turns = random.randint(1, 3)
                return WaitAction(self.entity).perform()
        
        # Move along path (invisibly if phasing active)
        if self.path:
            dest_x, dest_y = self.path.pop(0)
            
            # Handle doors
            if self.entity.gamemap.tiles["name"][dest_x, dest_y] == "Door":
                if self.toggle_door_at(dest_x, dest_y):
                    return WaitAction(self.entity).perform()
                else:
                    self.path = []
                    self.wander_wait_turns = random.randint(1, 2)
                    return WaitAction(self.entity).perform()
            
            # Move (phasing allows silent approach)
            result = MovementAction(
                self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
            ).perform()
            
            if not self.path:
                self.wander_wait_turns = random.randint(1, 3)
            
            return result
        
        return WaitAction(self.entity).perform()


class RetreatingPhasingAI(PhasingAI):
    """Advanced phasing AI that attacks then retreats invisibly.
    
    Behavior cycle:
    1. Approach player (invisible)
    2. Attack when adjacent (materializes for attack)
    3. Retreat away from player (re-applies invisibility)
    4. Reposition while invisible
    5. Repeat
    
    Inherits from PhasingAI and overrides attack/retreat behavior.
    Easy to customize: adjust retreat_distance for different tactics.
    """
    
    def __init__(self, entity: "Actor"):
        super().__init__(entity)
        self.retreat_distance = 4  # How far to path away after attacking.
        self.is_retreating = False
        self.type = "RetreatingPhasingAI"

    def _get_retreat_path(self, target: "Actor") -> List[Tuple[int, int]]:
        """Return a TCOD path that moves away from the target several tiles."""
        gm = self.engine.game_map
        dx = target.x - self.entity.x
        dy = target.y - self.entity.y

        away_dx = 0 if dx == 0 else (-1 if dx > 0 else 1)
        away_dy = 0 if dy == 0 else (-1 if dy > 0 else 1)

        if away_dx == 0 and away_dy == 0:
            return []

        candidates: List[Tuple[int, int]] = []

        # Prefer farther retreat points first, then fall back to shorter points.
        for step in range(self.retreat_distance, 0, -1):
            primary_x = self.entity.x + away_dx * step
            primary_y = self.entity.y + away_dy * step

            if (
                0 <= primary_x < gm.width
                and 0 <= primary_y < gm.height
                and gm.tiles["walkable"][primary_x, primary_y]
            ):
                candidates.append((primary_x, primary_y))

            # If diagonal retreat is blocked, also try axis-aligned fallback points.
            if away_dx != 0 and away_dy != 0:
                x_only = (self.entity.x + away_dx * step, self.entity.y)
                y_only = (self.entity.x, self.entity.y + away_dy * step)

                if (
                    0 <= x_only[0] < gm.width
                    and 0 <= x_only[1] < gm.height
                    and gm.tiles["walkable"][x_only[0], x_only[1]]
                ):
                    candidates.append(x_only)

                if (
                    0 <= y_only[0] < gm.width
                    and 0 <= y_only[1] < gm.height
                    and gm.tiles["walkable"][y_only[0], y_only[1]]
                ):
                    candidates.append(y_only)

        for dest_x, dest_y in candidates:
            retreat_path = self.get_path_with_doors(dest_x, dest_y)
            if retreat_path:
                return retreat_path

        return []
    
    def perform(self) -> None:
        """Override to add retreat logic after attacks."""
        # Decrement cooldown each turn
        if self.phasing_cooldown > 0:
            self.phasing_cooldown -= 1
        
        # Move every turn (inherited speed control)
        if not self.should_move_this_turn():
            return WaitAction(self.entity).perform()
        
        self.check_and_close_doors()
        
        # Initialize home position on first move
        if self.home_x is None or self.home_y is None:
            self.home_x = self.entity.x
            self.home_y = self.entity.y
        
        # Select target (player or nearby decoy/illusion)
        target = self.select_target()
        dx = target.x - self.entity.x
        dy = target.y - self.entity.y
        distance = max(abs(dx), abs(dy))

        # **RETREAT MODE**: Move away from player after attack
        if self.is_retreating:
            # Stay phased while retreating.
            if not has_phasing_effect(self.entity):
                apply_phasing_effect(self.entity, duration=5)

            if not self.path:
                self.path = self._get_retreat_path(target)

            if not self.path:
                self.is_retreating = False
                self.wander_wait_turns = random.randint(1, 2)
                return WaitAction(self.entity).perform()

            dest_x, dest_y = self.path.pop(0)

            if self.entity.gamemap.tiles["name"][dest_x, dest_y] == "Door":
                if self.toggle_door_at(dest_x, dest_y):
                    return WaitAction(self.entity).perform()
                self.path = []
                self.is_retreating = False
                return WaitAction(self.entity).perform()

            result = MovementAction(
                self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
            ).perform()

            if not self.path:
                self.is_retreating = False
                self.wander_wait_turns = random.randint(1, 2)

            return result

        # Apply invisibility while approaching (if not on cooldown).
        if not has_phasing_effect(self.entity) and self.phasing_cooldown == 0:
            apply_phasing_effect(self.entity, duration=5)
        
        # **NORMAL MODE**: Chase or wander
        if self.can_see_actor(target):
            self.wander_wait_turns = 0
            self.path = []
            self.last_saw_player = 0
            
            if distance <= 1:
                # Adjacent - attack and enter retreat mode
                remove_phasing_effect(self.entity)  # Materialize for attack
                
                result = MeleeAction(self.entity, dx, dy).perform()

                # Trigger cooldown + retreat pathing.
                self.phasing_cooldown = self.phasing_cooldown_max
                self.is_retreating = True
                self.path = []

                return result
            
            # Chase player (invisibly)
            self.path = self.get_path_with_doors(target.x, target.y)
        else:
            if self.last_saw_player == 0:
                self.path = []
            self.last_saw_player += 1
            
            if self.wander_wait_turns > 0:
                self.wander_wait_turns -= 1
                return WaitAction(self.entity).perform()
        
        # Wander if no path
        if not self.path:
            dest_x = self.home_x + random.randint(-self.wander_range, self.wander_range)
            dest_y = self.home_y + random.randint(-self.wander_range, self.wander_range)
            
            if (0 <= dest_x < self.engine.game_map.width and
                0 <= dest_y < self.engine.game_map.height and
                self.engine.game_map.tiles["walkable"][dest_x, dest_y]):
                
                self.path = self.get_path_with_doors(dest_x, dest_y)
            
            if not self.path:
                self.wander_wait_turns = random.randint(1, 3)
                return WaitAction(self.entity).perform()
        
        # Move along path
        if self.path:
            dest_x, dest_y = self.path.pop(0)
            
            if self.entity.gamemap.tiles["name"][dest_x, dest_y] == "Door":
                if self.toggle_door_at(dest_x, dest_y):
                    return WaitAction(self.entity).perform()
                else:
                    self.path = []
                    self.wander_wait_turns = random.randint(1, 2)
                    return WaitAction(self.entity).perform()
            
            result = MovementAction(
                self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
            ).perform()
            
            if not self.path:
                self.wander_wait_turns = random.randint(1, 3)
            
            return result
        
        return WaitAction(self.entity).perform()


class HostileCasterAI(HostileEnemy):
    def __init__(self, entity: Actor):
        super().__init__(entity)
        self.cast_cooldown = 0
        self.cast_cooldown_turns = 2

    def perform(self) -> None:
        if self.cast_cooldown > 0:
            self.cast_cooldown -= 1

        # Select target (player or nearby decoy/illusion)
        target = self.select_target()
        dx = target.x - self.entity.x
        dy = target.y - self.entity.y
        distance = max(abs(dx), abs(dy))

        if self.can_see_actor(target):
            from actions import CastSpellAction

            known_spells = list(getattr(self.entity, "known_spells", []) or [])
            current_mana = int(getattr(self.entity, "mana", 0) or 0)
            has_castable_spell = any(
                current_mana >= int(getattr(spell, "mana_cost", 0) or 0)
                for spell in known_spells
            )

            # Keep distance from melee range when possible.
            if distance <= 2:
                step_x = 0 if dx == 0 else (-1 if dx > 0 else 1)
                step_y = 0 if dy == 0 else (-1 if dy > 0 else 1)
                new_x = self.entity.x + step_x
                new_y = self.entity.y + step_y
                gm = self.entity.gamemap
                if (
                    gm.in_bounds(new_x, new_y)
                    and gm.tiles["walkable"][new_x, new_y]
                    and not gm.get_blocking_entity_at_location(new_x, new_y)
                ):
                    return MovementAction(self.entity, step_x, step_y).perform()
                return WaitAction(self.entity).perform()

            # Prefer spellcasting at safer mid-range and not every turn.
            if distance <= 5 and has_castable_spell and self.cast_cooldown == 0:
                self.cast_cooldown = self.cast_cooldown_turns
                return CastSpellAction(self.entity, target).perform()

            # If waiting on cooldown with player in range, keep some movement pressure
            # without making spell damage unavoidable every action.
            if distance <= 5 and self.cast_cooldown > 0:
                if random.random() < 0.5:
                    return WaitAction(self.entity).perform()

        # Fall back to hostile movement/chasing behavior when not casting.
        return super().perform()
        

class Friendly(BaseAI):
    # Friendly entity that paths around occasionally
    def __init__(self, entity: Actor):
        super().__init__(entity)
        self.path: List[Tuple[int, int]] = []
        self.wait_turns = random.randint(0, 20)  # Initial wait before first move
        self.type = "Friendly"
        # Set NPCs to move at half speed compared to player
        self.movement_speed = 2

    def perform(self) -> None:
        # Check if this AI should move this turn
        if not self.should_move_this_turn():
            return WaitAction(self.entity).perform()
        
        # Check and close any doors we've moved away from
        self.check_and_close_doors()
        
        if self.wait_turns > 0:
            self.wait_turns -= 1
            return WaitAction(self.entity).perform()
        
        if not self.path:
            # Pick a random location within 5 tiles to walk to
            dest_x = self.entity.x + random.randint(-5, 5)
            dest_y = self.entity.y + random.randint(-5, 5)

            # Ensure destination is in bounds and walkable (or a door that can be opened)
            if (0 <= dest_x < self.engine.game_map.width and
                0 <= dest_y < self.engine.game_map.height and
                (self.engine.game_map.tiles["walkable"][dest_x, dest_y] or 
                 self.is_door_tile(dest_x, dest_y)) and
                # Prefer to stay in radius of campfires, else will wander
                (not hasattr(self.engine.game_map, "items") or any(
                    item.name in ("Campfire", "Bonfire") and
                    (item.x - dest_x) ** 2 + (item.y - dest_y) ** 2 <= 10 * 10
                    for item in self.engine.game_map.items)
                )):
                self.path = self.get_path_with_doors(dest_x, dest_y)
            # If no campfire, just wander anywhere walkable
            elif (0 <= dest_x < self.engine.game_map.width and
                  0 <= dest_y < self.engine.game_map.height and
                  (self.engine.game_map.tiles["walkable"][dest_x, dest_y] or 
                   self.is_door_tile(dest_x, dest_y))):
                self.path = self.get_path_with_doors(dest_x, dest_y)
            else:

                # Invalid destination; wait instead
                self.wait_turns = random.randint(5,20)
                return WaitAction(self.entity).perform()
        
        if self.path:
            dest_x, dest_y = self.path.pop(0)
            
            # Check if the destination is a closed door that needs to be opened
            if self.entity.gamemap.tiles["name"][dest_x, dest_y] == "Door":
                # Try to open the closed door
                if self.toggle_door_at(dest_x, dest_y):
                    # Door opened successfully, wait this turn and move next turn
                    return WaitAction(self.entity).perform()
                else:
                    # Couldn't open door, clear path and wait
                    self.path = []
                    self.wait_turns = random.randint(5, 20)
                    return WaitAction(self.entity).perform()
            
            # Store current position before moving
            self.last_position = (self.entity.x, self.entity.y)
            
            # Perform the movement
            result = MovementAction(
                self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
            ).perform()
            
            return result
        
        # If no path found or path exhausted, wait a few turns before next move
        self.wait_turns = random.randint(5, 20)
        return WaitAction(self.entity).perform()


class DarkHostileEnemy(BaseAI):
    # Enemy that avoids light, only moves in darkness
    def __init__(self, entity: Actor):
        super().__init__(entity)
        self.path: List[Tuple[int, int]] = []
    
    def perform(self) -> None:
        # Select target (player or nearby decoy/illusion)
        target = self.select_target()
        dx = target.x - self.entity.x
        dy = target.y - self.entity.y
        distance = max(abs(dx), abs(dy))
        gm = self.engine.game_map
        if self.can_see_actor(target):
            # Build a walkable cost map similar to get_path_to but mark lit tiles as impassable
            try:
                import numpy as _np

                cost = _np.array(gm.tiles["walkable"], dtype=_np.int8)

                # mark lit tiles as non-walkable so pathfinder avoids them
                # Determine lit mask using same rules as GameMap.render
                lit_mask = _np.zeros((gm.width, gm.height), dtype=bool, order="F")

                # Check player-held torch
                has_torch = False
                try:
                    if self.engine.player.equipment:
                        # Check grasped items for torches
                        for item in self.engine.player.equipment.grasped_items.values():
                            if hasattr(item, 'name') and item.name == "Torch":
                                has_torch = True
                                break
                except Exception:
                    has_torch = False
                if has_torch:
                    rr = 7
                    px, py = self.engine.player.x, self.engine.player.y
                    xs = _np.arange(0, gm.width)
                    ys = _np.arange(0, gm.height)
                    dxs = xs[:, None] - px
                    dys = ys[None, :] - py
                    dist2 = dxs * dxs + dys * dys
                    lit_mask |= dist2 <= (rr * rr)

                # campfires and bonfires
                for item in getattr(gm, "items", []):
                    try:
                        if item.name == "Campfire" or item.name == "Bonfire":
                            cx, cy = item.x, item.y
                            xs = _np.arange(0, gm.width)
                            ys = _np.arange(0, gm.height)
                            dxs = xs[:, None] - cx
                            dys = ys[None, :] - cy
                            dist2 = dxs * dxs + dys * dys
                            if item.name == "Campfire":
                                lit_mask |= dist2 <= (3 * 3)  # radius 3 for campfires (matches game_map.py)
                            elif item.name == "Bonfire":
                                lit_mask |= dist2 <= (15 * 15)  # radius 15 for bonfires (matches game_map.py)
                    except Exception:
                        continue

                # treat lit tiles as non-walkable by setting cost to 0 where lit
                try:
                    cost[lit_mask] = 0
                except Exception:
                    # fallback: iterate
                    for lx, ly in zip(*_np.where(lit_mask)):
                        cost[lx, ly] = 0

                # increase cost for occupied tiles so pathfinder avoids them
                for entity in gm.entities:
                    try:
                        if entity.blocks_movement and cost[entity.x, entity.y]:
                            cost[entity.x, entity.y] += 10
                    except Exception:
                        continue

                graph = tcod.path.SimpleGraph(cost=cost, cardinal=2, diagonal=3)
                pathfinder = tcod.path.Pathfinder(graph)
                pathfinder.add_root((self.entity.x, self.entity.y))

                raw_path = pathfinder.path_to((target.x, target.y))[1:]
                # raw_path may be empty or contain coordinates in chained lists; coerce
                path = raw_path.tolist() if hasattr(raw_path, "tolist") else list(raw_path)
                self.path = [(p[0], p[1]) for p in path]
            except Exception:
                # If anything goes wrong, don't move into light; clear path so we wait
                self.path = []
            
            # attack if adjacent and not lit
            # ensure current tile is not lit
            try:
                current_lit = False
                if has_torch:
                    ddx = self.entity.x - self.engine.player.x
                    ddy = self.entity.y - self.engine.player.y
                    if ddx * ddx + ddy * ddy <= 7 * 7:
                        current_lit = True
                if not current_lit:
                    for item in getattr(gm, "items", []):
                        try:
                            if item.name == "Campfire":
                                cx = item.x - self.entity.x
                                cy = item.y - self.entity.y
                                if cx * cx + cy * cy <= 3 * 3:  # radius 3 for campfires
                                    current_lit = True
                                    break
                            elif item.name == "Bonfire":
                                bx = item.x - self.entity.x
                                by = item.y - self.entity.y
                                if bx * bx + by * by <= 15 * 15:  # radius 15 for bonfires
                                    current_lit = True
                                    break
                        except Exception:
                            continue
                # If the enemy is currently lit, it vanishes
                if current_lit:
                    try:
                        # optional message
                        if hasattr(self.engine, "message_log"):
                            self.engine.message_log.add_message(f"The {self.entity.name} dissolves in the light.", color.purple)
                    except Exception:
                        pass

                    try:
                        # Remove entity safely from map
                        if hasattr(gm, "entities") and self.entity in gm.entities:
                            try:
                                gm.entities.remove(self.entity)
                            except Exception:
                                try:
                                    gm.entities.discard(self.entity)
                                except Exception:
                                    pass
                        # clear ai to mark dead
                        try:
                            self.entity.ai = None
                        except Exception:
                            pass
                    except Exception:
                        pass

                    return

                if not current_lit and distance <= 1:
                    return MeleeAction(self.entity, dx, dy).perform()
            except Exception:
                pass
        
        if self.path:
            dest_x, dest_y = self.path.pop(0)
            return MovementAction(
                self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
            ).perform()
        
        return WaitAction(self.entity).perform()



class FollowerAI(BaseAI):
    def __init__(self, entity: "Actor", target: Actor = None):
        super().__init__(entity)
        self.target = target
        self.path: List[Tuple[int, int]] = []

    def perform(self) -> None:
        if not self.target:
            return WaitAction(self.entity).perform()

        if self.can_see_actor(self.target):
            tx, ty = self.target.x, self.target.y
            ex, ey = self.entity.x, self.entity.y
            # Chebyshev distance — already adjacent, stay put
            if max(abs(tx - ex), abs(ty - ey)) <= 1:
                self.path = []
            else:
                # Path to the walkable neighbour of the target closest to us
                gm = self.entity.gamemap
                
                # Helper to check if tile has another illusion on it
                def has_other_illusion(x, y):
                    for actor in gm.actors:
                        if actor != self.entity and actor.x == x and actor.y == y:
                            if getattr(actor, 'is_decoy', False):
                                return True
                    return False
                
                adj_tiles = [
                    (tx + dx, ty + dy)
                    for dx in range(-1, 2) for dy in range(-1, 2)
                    if (dx, dy) != (0, 0)
                    and gm.in_bounds(tx + dx, ty + dy)
                    and gm.tiles[tx + dx, ty + dy]['walkable']
                    and not has_other_illusion(tx + dx, ty + dy)  # Don't path into other illusions
                ]
                if adj_tiles:
                    goal = min(adj_tiles, key=lambda p: abs(p[0] - ex) + abs(p[1] - ey))
                    self.path = self.get_path_to(*goal)
                else:
                    self.path = self.get_path_to(tx, ty)

        if self.path:
            dest_x, dest_y = self.path.pop(0)
            
            # Check if destination now has another illusion
            for actor in self.entity.gamemap.actors:
                if actor != self.entity and actor.x == dest_x and actor.y == dest_y:
                    if getattr(actor, 'is_decoy', False):
                        self.path = []  # Clear path if another illusion is there
                        return WaitAction(self.entity).perform()
            
            return MovementAction(
                self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
            ).perform()

        return WaitAction(self.entity).perform()


class NoneAI(BaseAI):
    """Used for environmental objects"""
    def perform(self) -> None:
        pass # Do nothing
    


class AnimalAI(BaseAI):
    """Simple AI for non-hostile animals that wander around and flee when the player gets too close."""

    def __init__(self, entity: "Actor", flee_distance: int = 5):
        super().__init__(entity)
        self.flee_distance = flee_distance
        self.path: List[Tuple[int, int]] = []

    def perform(self) -> None:
        target = self.engine.player
        dx = target.x - self.entity.x
        dy = target.y - self.entity.y
        distance = max(abs(dx), abs(dy))

        if distance <= self.flee_distance:
            # Flee from player: move in opposite direction
            flee_x = self.entity.x - dx
            flee_y = self.entity.y - dy

            # Get path to flee location, treating doors as walkable so animals can flee through them
            self.path = self.get_path_with_doors(flee_x, flee_y)

            if self.path:
                dest_x, dest_y = self.path.pop(0)
                return MovementAction(
                    self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
                ).perform()

        # Otherwise, wander randomly
        if not self.path and random.random() < 0.5:  # pick a new destination when idle
            wander_x = self.entity.x + random.randint(-4, 4)
            wander_y = self.entity.y + random.randint(-4, 4)

            if (0 <= wander_x < self.engine.game_map.width and
                0 <= wander_y < self.engine.game_map.height and
                (self.engine.game_map.tiles["walkable"][wander_x, wander_y] or
                 self.is_door_tile(wander_x, wander_y))):
                self.path = self.get_path_with_doors(wander_x, wander_y)

        if self.path:
            dest_x, dest_y = self.path.pop(0)
            return MovementAction(
                self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
            ).perform()

        return WaitAction(self.entity).perform()



class StatueAI(BaseAI):
    """Dormant AI attached to statues.

    The statue does nothing until the player enters its sight radius.  On
    activation it transforms into an Animated Armor: stats, sprite, and AI are
    all swapped in-place so the entity reference stays valid on the game map.
    """

    def __init__(self, entity: "Actor", animate_chance: float = 0.5):
        super().__init__(entity)
        self.activated = False
        # Decided at spawn time: only this fraction of statues will ever animate
        self.will_animate: bool = random.random() < animate_chance

    def perform(self) -> None:
        if not self.will_animate or self.activated:
            return WaitAction(self.entity).perform()

        target = self.engine.player
        dx = target.x - self.entity.x
        dy = target.y - self.entity.y
        distance = (dx * dx + dy * dy) ** 0.5

        if distance > 2 or not self.can_see_actor(target):
            return WaitAction(self.entity).perform()

        # Lock immediately — prevents replaying if anything below raises
        self.activated = True

        # --- Transform in place ---
        try:
            import copy
            import sounds
            import color as _color
            import entity_factories

            template = entity_factories.animated_armor
            e = self.entity

            # Copy visual / identity from the template
            e.char = template.char
            e.base_char = template.base_char
            e.name = template.name
            e.description = template.description
            e.type = template.type
            e.sentient = getattr(template, 'sentient', False)
            e.is_known = getattr(template, 'is_known', True)
            e.speed = template.speed
            e.dodge_chance = template.dodge_chance
            e.verb_base = template.verb_base
            e.verb_present = template.verb_present
            e.verb_past = template.verb_past
            e.verb_participial = template.verb_participial

            # Deep-copy fighter and body_parts from the template
            fighter = copy.deepcopy(template.fighter)
            fighter.parent = e
            e.fighter = fighter

            bp = copy.deepcopy(template.body_parts)
            bp.parent = e
            e.body_parts = bp

            # Ensure equipment / inventory are present
            if e.equipment is None:
                from components.equipment import Equipment
                eq = Equipment()
                eq.parent = e
                e.equipment = eq
            if e.inventory is None:
                from components.inventory import Inventory
                inv = Inventory(capacity=0)
                inv.parent = e
                e.inventory = inv

            # Sound + message
            sounds.play_stone_sound()
            self.engine.message_log.add_message(
                "The statue shudders and springs to life!", _color.white
            )

            # Swap to HostileEnemy AI
            new_ai = HostileEnemy(e)
            e.ai = new_ai

        except Exception as _ex:
            import traceback
            try:
                from gpu_stack import get_data_path
                with open(get_data_path('logs/log.txt'), 'a') as _lf:
                    _lf.write(f"[StatueAI] Transform failed: {_ex}\n")
                    _lf.write(traceback.format_exc())
            except Exception:
                pass

class RangedEnemyAI(HostileEnemy):
    """Hostile enemy that prefers to fire projectiles from a distance rather than melee."""
    def __init__(self, entity: Actor):
        super().__init__(entity)
        self.type = "RangedEnemyAI"
        self.ranged_cooldown = 0
        self.ranged_cooldown_turns = 3

    def perform(self) -> None:
        """Fire projectiles at player when in range, melee if player gets too close, and otherwise chase."""
        if self.ranged_cooldown > 0:
            self.ranged_cooldown -= 1

        target = self.select_target()
        dx = target.x - self.entity.x
        dy = target.y - self.entity.y
        distance = (dx * dx + dy * dy) ** 0.5

        if self.can_see_actor(target):
            if distance <= 1:
                # Player is adjacent - use melee attack
                return MeleeAction(self.entity, dx, dy).perform()
            elif distance <= 5 and self.ranged_cooldown == 0:
                # Player is in mid-range and we can shoot - fire projectile
                self.ranged_cooldown = self.ranged_cooldown_turns
                return RangedAction(self.entity, dx, dy).perform(innate=True, break_chance = True)
            
        # Keep distance from melee range when possible.
        if distance <= 5:
            step_x = 0 if dx == 0 else (-1 if dx > 0 else 1)
            step_y = 0 if dy == 0 else (-1 if dy > 0 else 1)
            new_x = self.entity.x + step_x
            new_y = self.entity.y + step_y
            gm = self.entity.gamemap
            if (
                gm.in_bounds(new_x, new_y)
                and gm.tiles["walkable"][new_x, new_y]
                and not gm.get_blocking_entity_at_location(new_x, new_y)
            ):
                return MovementAction(self.entity, step_x, step_y).perform()
            return WaitAction(self.entity).perform()


        # Default to chasing behavior when we can't shoot
        return super().perform()


class DragonHeadAI(BaseAI):
    """AI for dragon head that periodically casts dragon's breath.
    
    This AI is attached to the top part of a multi-tile dragon boss.
    It doesn't move (the parent entity handles movement), but it can
    independently cast spells when the player is in range.
    """
    
    def __init__(self, entity: "Actor"):
        super().__init__(entity)
        self.cast_cooldown = 0
        self.cast_cooldown_max = 4  # Cast every 4 turns
        self.type = "DragonHeadAI"
    
    def perform(self) -> None:
        """Cast dragon's breath periodically when player is in sight."""
        # Don't move - parent entity handles positioning
        
        # Decrement cooldown
        if self.cast_cooldown > 0:
            self.cast_cooldown -= 1
            return WaitAction(self.entity).perform()
        
        # Check if we can see the player
        target = self.engine.player
        if not self.can_see_actor(target, radius=8):
            return WaitAction(self.entity).perform()
        
        # Check if we have the spell and enough mana
        from components.spells import DragonsBreathSpell
        spell = DragonsBreathSpell()
        
        # Ensure entity has mana (give infinite mana to boss if not set)
        if not hasattr(self.entity, 'mana') or self.entity.mana < spell.mana_cost:
            self.entity.mana = 100
            self.entity.mana_max = 100
        
        # Cast dragon's breath at player - this is an innate ability, so activate directly
        # without proficiency checks
        try:
            from actions import Action
            
            # Create a simple action wrapper to provide context for spell activation
            class InnateSpellAction(Action):
                def __init__(self, entity, spell, target_xy):
                    super().__init__(entity)
                    self.spell = spell
                    self.target_xy = target_xy
                
                @property
                def target_actor(self):
                    return self.engine.game_map.get_actor_at_location(*self.target_xy)
            
            # Target the player's position
            target_xy = (target.x, target.y)
            
            # Create action and activate spell directly (bypassing proficiency checks)
            action = InnateSpellAction(self.entity, spell, target_xy)
            
            # Spend mana
            self.entity.mana -= spell.mana_cost
            
            # Activate the spell directly (innate ability - no fizzle chance)
            spell.activate(action, _range = 10)
            
            # Reset cooldown after casting
            self.cast_cooldown = self.cast_cooldown_max
            
            return WaitAction(self.entity).perform()
        except Exception:
            # If casting fails for any reason, reset cooldown and wait
            self.cast_cooldown = 2
            return WaitAction(self.entity).perform()

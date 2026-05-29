"""
Turn Management System

🎯 **THIS IS WHERE POST-PLAYER-ACTION LOGIC LIVES** 🎯

This module centralizes all turn-based logic that happens after a player action.
This makes it easy to find and modify game tick behavior.

Key Functions:
- process_player_turn_end(): Main entry point for all post-action processing
- _handle_enemy_turns(): Processes all AI enemy actions
- _handle_status_effects(): Manages darkness, lucidity, and environmental effects
- _handle_equipment_durability(): Handles torch burning and item degradation
- _handle_game_state_checks(): Checks for level up, death, and game state changes

If you want to add something that happens after every player action,
add it to the process_player_turn_end() method or create a new helper method.
"""
from __future__ import annotations

import random
import heapq
import time
from balance_config import MANA_REGEN_CHANCE, MANA_REGEN_FRACTION
from typing import TYPE_CHECKING

import color
import identify as identify_system
from liquid_system import LiquidType
import sounds
import sprite_manager

if TYPE_CHECKING:
    from engine import Engine
    from input_handlers import BaseEventHandler

from animations import DripParticle


class TurnManager:
    """Supreme Turn Manager - Manages initiative-based turn order for all actors."""
    
    def __init__(self, engine: Engine):
        self.engine = engine
        self.total_player_moves = 0  # Track total player moves for hunger system
        self.turn_queue = []  # List of (initiative, actor) tuples
        self.current_turn_actor = None
        # Pruning budget controls. Full sprite prune can be expensive because it
        # traverses cached floors and entities; avoid running it every turn.
        self._prune_check_interval_turns = 40
        self._last_prune_turn = -10_000

    def _is_sleeping(self, actor) -> bool:
        from components.effect import has_effect_name
        return has_effect_name(actor, "Sleep")
    
    def process_pre_player_turn(self) -> BaseEventHandler | None:
        """Process all actors who should act before the player based on initiative."""
        return self._process_turn_queue_until_player()
    
    def _process_turn_queue_until_player(self) -> BaseEventHandler | None:
        """Process turns until it's the player's turn or queue is empty."""
        self._rebuild_turn_queue()
        ai_elapsed = 0.0
        
        while self.turn_queue:
            # Get the next actor to act (highest initiative)
            initiative, actor = self.turn_queue.pop()
            
            # If it's the player's turn, stop here
            if actor == self.engine.player:
                return None
                
            # Process enemy turn
            if actor.ai and not self.engine.is_actor_asleep(actor):
                try:
                    _ai_start = time.perf_counter()
                    actor.ai.perform()
                    ai_elapsed += time.perf_counter() - _ai_start
                    actor.initiative_counter -= 100  # Consume action
                except Exception as e:
                    print(f"ERROR: Actor {actor.name} failed to perform action: {e}")
                    actor.initiative_counter -= 100  # Still consume turn
            elif actor.ai:
                actor.initiative_counter -= 100  # Sleep still burns the turn
                    

        
        if ai_elapsed > 0.0:
            self.engine.profile_external_ms("ai_preturn", ai_elapsed * 1000.0)
        return None
    
    def _rebuild_turn_queue(self) -> None:
        """Rebuild the turn queue based on current initiative values."""
        self.turn_queue = []
        
        # Add all living actors with their current initiative
        for actor in self.engine.game_map.actors:
            if actor.is_alive:
                # Update initiative for this round
                actor.initiative_counter += actor.get_effective_speed()
                
                # Only add to queue if they have enough initiative to act
                if actor.initiative_counter >= 100:
                    self.turn_queue.append((actor.initiative_counter, actor))
        
        # Sort ascending and pop() from the end for O(1) retrieval of highest initiative.
        self.turn_queue.sort(key=lambda x: x[0])
    
    def process_player_turn_end(self) -> BaseEventHandler | None:
        """
        Called after a valid player action to process all turn-end effects.
        
        Returns:
            BaseEventHandler if we need to switch handlers (like GameOver), None otherwise.
        """
        # Refresh passive ring effects first so expiring buffs are extended
        # before their tick/message phase runs.
        self._handle_equipped_ring_effects()

        # Tick active ability cooldowns for all actors once per world tick.
        for actor in list(self.engine.game_map.actors):
            ability = getattr(actor, "active_ability", None)
            if ability is None:
                continue
            tick_fn = getattr(ability, "tick_cooldown", None)
            if callable(tick_fn):
                tick_fn(1)

        # Handle all effects on entities

        for actor in list(self.engine.game_map.actors):
            if not hasattr(actor, "effects") or not actor.effects:
                continue
            for effect in list(actor.effects):
                try:
                    expired = effect.tick(actor)
                    message = None
                    get_message = getattr(effect, "get_message", None)
                    if callable(get_message):
                        message = get_message()
                    # Effect UI messages are player-facing; suppress NPC/enemy spam.
                    if message and actor.is_player:
                        message_text = message[0]
                        message_color = message[1]
                        self.engine.message_log.add_message(message_text, message_color)
                    if expired:
                        try:
                            actor.effects.remove(effect)
                        except ValueError:
                            pass
                except Exception:
                    # Don't let a broken effect crash the engine tick
                    pass


        # 1. Handle equipment durability (torches burning out, etc.)
        handler_change = self._handle_equipment_durability()
        if handler_change:
            return handler_change
        # Hunger / saturation handling:
        # - Saturation decreases faster each tick (represents recent food buffering).
        # - While saturation is high, hunger decreases slowly. As saturation depletes
        #   the hunger decrease ramps up to the full rate when saturation == 0.
        player = self.engine.player
        base_hunger_decrease = 0.05   # hunger drain once saturation is gone
        saturation_decay = 0.25        # saturation consumed per player turn; stew (+100) lasts ~100 turns

        # Identification jobs progress with each completed player turn.
        identify_system.tick_identification(player, self.engine)

        # Drain saturation first (can't go below 0)
        player.saturation = max(0.0, player.saturation - saturation_decay)

        # Compute hunger multiplier based on remaining saturation.
        # If saturation > 50 -> slow drain (25% of base).
        # If 0 < saturation <= 50 -> linearly interpolate between 25% and 100%.
        if player.saturation > 50:
            hunger_mult = 0.25
        elif player.saturation > 0:
            # at saturation==50 -> 0.25, at saturation==0 -> 1.0
            hunger_mult = 0.25 + ((50.0 - player.saturation) / 50.0) * 0.75
        else:
            hunger_mult = 1.0

        player.hunger = max(0.0, player.hunger - (base_hunger_decrease * hunger_mult))
        self.total_player_moves += 1


        self.engine.debug_log(f"TOTAL PLAYER MOVES: {self.total_player_moves}", handler=self.__class__.__name__, event="PlayerTurnEnd")


        # Process any remaining actor turns after player acted
        self._process_remaining_turns()
        
        # 3. Update field of view
        self._update_fov()
        
        # 4. Handle status effects and environmental effects
        self._handle_status_effects()

        # 5. Update player state (e.g., check for starvation)
        self._update_player_state()
        
        # 6. Handle special game state checks (level up, death, etc.)
        handler_change = self._handle_game_state_checks()
        if handler_change:
            return handler_change
        
        # 7. Process liquid system aging and evaporation
        if hasattr(self.engine.game_map, 'liquid_system'):
            self.engine.game_map.liquid_system.tick_liquid()

        # 8. Process liquid coating entities
        self._process_body_part_coating_evaporation()
        self._process_body_part_liquid_coating()
        self._process_body_part_liquid_effects()

        # Keep composite sprite pressure bounded by reclaiming entries that are
        # no longer reachable from the current engine state.
        try:
            # Check pressure cheaply every turn, but only run the expensive prune
            # pass periodically while pressure remains high.
            slot_info = sprite_manager.get_composite_slot_usage()
            slots_allocated = int(slot_info.get("slots_allocated", 0) or 0)
            compose_entries = int(slot_info.get("compose_cache_entries", 0) or 0)

            should_prune = (
                slots_allocated >= 512
                and compose_entries > 32
                and (self.total_player_moves - self._last_prune_turn) >= self._prune_check_interval_turns
            )

            if should_prune:
                _prune_start = time.perf_counter()
                # Fast path for turn-time pruning: scan active runtime state only.
                # Cached floor maps can regenerate composites when revisited.
                sprite_manager.prune_unused_composites(
                    self.engine,
                    include_cached_world_maps=False,
                )
                self._last_prune_turn = self.total_player_moves
                self.engine.profile_external_ms("sprite_prune", (time.perf_counter() - _prune_start) * 1000.0)
        except Exception:
            pass


        
        return None
    
    def _process_body_part_liquid_coating(self) -> None:
        """Apply or remove liquid coatings on body parts based on current tile."""
        try:
            for entity in list(self.engine.game_map.entities):
                # Check if entity has body parts and is in a liquid tile
                if hasattr(entity, 'body_parts') and entity.body_parts and hasattr(self.engine.game_map, 'liquid_system'):
                    # Get the liquid at the entity's position
                    liquid_coating = self.engine.game_map.liquid_system.get_coating(entity.x, entity.y)

                    # Swimming: entity is on a Water tile — coat every body part with water
                    if getattr(entity, 'is_swimming', False):
                        for body_part in entity.body_parts.body_parts.values():
                            if body_part.coating != LiquidType.WATER:
                                body_part.coating = LiquidType.WATER
                                body_part.coating_age = 0
                                if entity == self.engine.player:
                                    self.engine.debug_log(
                                        f"SWIMMING COATED: {body_part.name} with water",
                                        handler=self.__class__.__name__, event="BodyPartCoating"
                                    )
                        continue  # skip foot-only logic below while swimming

                    # Find all limbs tagged with "foot"
                    for body_part in entity.body_parts.body_parts.values():
                        if "foot" in body_part.tags:
                            if liquid_coating and liquid_coating.depth >= 1:
                                # Only coat feet if liquid is deep enough (depth >= 1)
                                was_coated_before = body_part.coating != LiquidType.NONE
                                if body_part.coating != liquid_coating.liquid_type:
                                    body_part.coating = liquid_coating.liquid_type
                                    body_part.coating_age = 0  # Reset age when newly coated
                                    
                                    # Apply immediate stepping effect for harmful liquids.
                                    if not was_coated_before and liquid_coating.liquid_type in {LiquidType.POISON, LiquidType.FIRE}:
                                        self.engine.game_map.liquid_system._apply_liquid_effect(
                                            entity, liquid_coating.liquid_type, 
                                            max(1, liquid_coating.depth - 1),  # Reduced effect for stepping vs splashing
                                            body_part
                                        )
                                    
                                    # Debug: Print coating info if this is the player
                                    if entity == self.engine.player:
                                        self.engine.debug_log(f"COATED: {body_part.name} with {liquid_coating.liquid_type.get_display_name()}", handler=self.__class__.__name__, event="BodyPartCoating")
                            else:
                                # Clear coating if not in deep liquid (but only occasionally to simulate gradual removal)
                                if body_part.coating != LiquidType.NONE:
                                    self.engine.animation_queue.append(DripParticle((entity.x, entity.y), body_part.coating.get_display_color()))
                                    # Only clear coating with some delay (not instantly when stepping out)
                                    if body_part.coating_age > 5:  # Wait at least 5 turns before clearing
                                        body_part.coating = LiquidType.NONE
                                        body_part.coating_age = 0
                                        # Debug: Print clearing info if this is the player
                                        if entity == self.engine.player:
                                            self.engine.debug_log(f"CLEARED: {body_part.name} coating cleared after being away from liquid", handler=self.__class__.__name__, event="BodyPartCoating")
        except Exception:
            import traceback
            traceback.print_exc()
    
    def _process_body_part_coating_evaporation(self) -> None:
        """Process evaporation of liquid coatings on body parts."""
        try:
            for entity in list(self.engine.game_map.entities):
                if hasattr(entity, 'body_parts') and entity.body_parts:
                    for body_part in entity.body_parts.body_parts.values():
                        if body_part.coating != LiquidType.NONE:
                            body_part.coating_age += 1
                            
                            # Check for evaporation using liquid type's built-in chance
                            evap_chance = body_part.coating.get_evaporation_chance()
                            if random.random() < evap_chance:
                                coating_name = body_part.coating.get_display_name()
                                # Debug: Print evaporation if this is the player
                                #if entity == self.engine.player:
                                self.engine.debug_log(f"EVAPORATED: {body_part.name} coating ({coating_name}) evaporated after {body_part.coating_age} turns (chance: {evap_chance})", handler=self.__class__.__name__, event="BodyPartCoating")
                                body_part.coating = LiquidType.NONE
                                body_part.coating_age = 0
        except Exception:
            import traceback
            traceback.print_exc()
    
    def _process_body_part_liquid_effects(self) -> None:
        """Apply effects from liquid coatings on body parts (e.g., poison damage)."""
        try:
            for entity in list(self.engine.game_map.entities):
                if hasattr(entity, 'body_parts') and entity.body_parts:
                    # Aggregate by liquid type so each coating type applies once per entity per tick.
                    coated_liquids = {}
                    for body_part in entity.body_parts.body_parts.values():
                        if body_part.coating != LiquidType.NONE and body_part.coating not in coated_liquids:
                            coated_liquids[body_part.coating] = body_part

                    for liquid_type, representative_part in coated_liquids.items():
                        self.engine.game_map.liquid_system.tick_liquid_effects(
                            target=entity,
                            coating=liquid_type,
                            affected_body_part=representative_part,
                        )
        except Exception:
            import traceback
            traceback.print_exc()
    def _update_player_state(self) -> None:
        """Update player state"""
        from components.effect import HungryEffect, StarvingEffect
        player = self.engine.player
        player_saturation = getattr(player, 'saturation', 0.0)

        # Remove SaturatedEffect when saturation drops below the well-fed threshold.
        if player_saturation < 75.0:
            has_saturated = any(getattr(e, 'type', '') == 'Saturated' for e in player.effects)
            if has_saturated:
                player.remove_effect('Saturated')

        # Suppress hunger/starving while saturation is still providing a buffer.
        if player_saturation > 0.0:
            return

        if player.hunger <= 25.0:
            has_hunger_or_starving = any(
                getattr(e, "type", "") in ("Hungry", "Starving")
                for e in player.effects
            )
            if not has_hunger_or_starving:
                self.engine.message_log.add_message("You feel hungry.", color.yellow)
                player.add_effect(HungryEffect())
        if player.hunger <= 10.0:
            has_starving = any(getattr(e, "type", "") == "Starving" for e in player.effects)
            if not has_starving:
                self.engine.message_log.add_message("You are starving!", color.red)
                player.add_effect(StarvingEffect())
            player.remove_effect("Hungry")
    def _handle_equipment_durability(self) -> BaseEventHandler | None:
        """Handle equipment that degrades over time (like torches)."""
        try:
            player = self.engine.player
            # Check all grasped items for burn duration (new modular system)
            items_to_remove = []
            for item in list(player.equipment.grasped_items.values()):
                if getattr(item, "burn_duration", None) is not None:
                    try:
                        item.burn_duration -= 1
                        if item.burn_duration <= 0:
                            items_to_remove.append(item)
                    except Exception:
                        pass
            
            # Remove burned-out items
            for item in items_to_remove:
                player.equipment.unequip_item(item, add_message=False)
                try:
                    # Remove from inventory if present
                    if item in player.inventory.items:
                        player.inventory.items.remove(item)
                except Exception:
                    pass
                sounds.torch_burns_out_sound.play()
                shown_name = identify_system.get_display_name(self.engine.player, item)
                self.engine.message_log.add_message(f"Your {shown_name} burns out.", color.error)
            
        except Exception:
            pass
        return None
    

    
    def _process_remaining_turns(self) -> None:
        """Process any actors who still have initiative to act after the player.
        
        Actors may act multiple times in a single turn if they have speed >= 100
        and still have >= 100 initiative remaining after each action.
        """
        # Consume player's action
        self.engine.player.initiative_counter -= 100

        # Build a max-heap once, then requeue actors as they keep initiative.
        # This avoids repeated full scans of all actors on deep, crowded floors.
        ai_elapsed = 0.0
        action_heap: list[tuple[int, int, object]] = []
        tie_breaker = 0
        for actor in self.engine.game_map.actors:
            if actor.is_alive and actor != self.engine.player and actor.initiative_counter >= 100:
                heapq.heappush(action_heap, (-int(actor.initiative_counter), tie_breaker, actor))
                tie_breaker += 1

        while action_heap:
            _neg_init, _seq, next_actor = heapq.heappop(action_heap)

            if (not getattr(next_actor, "is_alive", False)
                    or next_actor == self.engine.player
                    or int(getattr(next_actor, "initiative_counter", 0)) < 100):
                continue

            try:
                if not self.engine.is_actor_asleep(next_actor):
                    _ai_start = time.perf_counter()
                    next_actor.ai.perform()
                    ai_elapsed += time.perf_counter() - _ai_start
            except Exception:
                pass
            finally:
                next_actor.initiative_counter -= 100

            if next_actor.is_alive and next_actor != self.engine.player and next_actor.initiative_counter >= 100:
                heapq.heappush(
                    action_heap,
                    (-int(next_actor.initiative_counter), tie_breaker, next_actor),
                )
                tie_breaker += 1

        self.turn_queue = []  # Clear – next round will be built fresh
        if ai_elapsed > 0.0:
            self.engine.profile_external_ms("ai_postturn", ai_elapsed * 1000.0)
    
    def _update_fov(self) -> None:
        """Update the player's field of view."""
        self.engine.update_fov()
    
    def _handle_status_effects(self) -> None:
        """Handle darkness, lucidity, and other environmental effects."""
        from components.effect import Darkness

        # Handle darkness and lucidity system
        player_effects = getattr(self.engine.player, "effects", [])
        has_darkness = any(isinstance(e, Darkness) for e in player_effects)



        if random.random() < max(0.0, min(1.0, MANA_REGEN_CHANCE + self.engine.player.equipment.mana_regen)):
            # Frequent but smaller mana ticks smooth out caster pacing.
            mana_recovered = max(1, int(self.engine.player.mana_max * (MANA_REGEN_FRACTION + self.engine.player.equipment.mana_regen)))
            self.engine.debug_log(f"DEBUG: Recovered {mana_recovered} mana due to natural regeneration.", handler=self.__class__.__name__, event="ManaRecovery")
            self.engine.player.mana = min(self.engine.player.mana + mana_recovered, self.engine.player.mana_max)

        # Non-player mana regen (casters and any AI with mana pools).
        for actor in self.engine.game_map.actors:
            if actor == self.engine.player:
                continue
            actor_mana_max = int(getattr(actor, "mana_max", 0) or 0)
            actor_mana = int(getattr(actor, "mana", 0) or 0)
            if actor_mana_max <= 0 or actor_mana >= actor_mana_max:
                continue
            if random.random() < MANA_REGEN_CHANCE:
                mana_recovered = max(1, int(actor_mana_max * MANA_REGEN_FRACTION))
                actor.mana = min(actor_mana + mana_recovered, actor_mana_max)
        
        if random.random() < self.engine.player.passive_healing * 2:
            player_effects = getattr(self.engine.player, 'effects', [])
            effect_types = {getattr(e, 'type', '') for e in player_effects}
            player_saturation = getattr(self.engine.player, 'saturation', 0.0)
            if 'Starving' in effect_types:
                pass  # Starvation negates passive healing
            elif 'Hungry' in effect_types:
                # Half healing while hungry
                heal_amount = max(1, int(self.engine.player.fighter.max_hp * self.engine.player.passive_healing * 0.5))
                self.engine.debug_log(f"DEBUG: Healed {heal_amount} HP (halved, hungry).", handler=self.__class__.__name__, event="PassiveHealing")
                self.engine.player.fighter.heal(heal_amount)
            elif player_saturation >= 75.0:
                # Well-fed: enhanced regen (5× amount, 2× chance already implicit via roll)
                heal_amount = max(1, int(self.engine.player.fighter.max_hp * self.engine.player.passive_healing * 5))
                self.engine.debug_log(f"DEBUG: Healed {heal_amount} HP (well-fed bonus).", handler=self.__class__.__name__, event="PassiveHealing")
                self.engine.player.fighter.heal(heal_amount)
            else:
                heal_amount = max(1, int(self.engine.player.fighter.max_hp * self.engine.player.passive_healing))
                self.engine.debug_log(f"DEBUG: Healed {heal_amount} HP due to passive healing.", handler=self.__class__.__name__, event="PassiveHealing")
                self.engine.player.fighter.heal(heal_amount)
        
        if has_darkness:
            # Player is in darkness; lose lucidity
            if random.random() < 0.33:  # 33% chance per tick
                self.engine.player.lucidity = max(0, self.engine.player.lucidity - 1)
        else:
            # Player is in light; regain lucidity
            self.engine.player.lucidity = min(
                self.engine.player.max_lucidity, 
                self.engine.player.lucidity + 1
            )
        
        # Handle lucidity messages
        self._handle_lucidity_messages()
        
        # Handle darkness-based enemy spawning
        if self.engine.player.lucidity <= 66:
            self.engine._maybe_spawn_enemy_in_dark()
    
    def _handle_lucidity_messages(self) -> None:
        """Handle messages related to lucidity levels."""
        lucidity = self.engine.player.lucidity
        
        if lucidity == 66:
            self.engine.message_log.add_message("You feel your mind slipping...", color.purple)
        elif lucidity == 33:
            self.engine.message_log.add_message("Your mind is deteriorating!", color.purple)
        elif lucidity == 10:
            self.engine.message_log.add_message("Your mind is on the brink of collapse!", color.red)
        elif lucidity == 0:
            self.engine.message_log.add_message("Your mind has collapsed into madness!", color.red)
            # Could trigger special events here
    
    def _handle_game_state_checks(self) -> BaseEventHandler | None:
        """Check for game state changes that require handler switches."""
        # Import here to avoid circular imports
        from input_handlers import GameOverEventHandler
        
        if not self.engine.player.is_alive:
            sounds.stop_all_music()
            sounds.stop_all_sounds()
            sounds.play_gameover_sound()
            # Defer game-over overlay until one more engine sprite-update cycle has run.
            if getattr(self.engine, '_pending_handler', None) is None:
                
                self.engine._pending_handler = GameOverEventHandler(self.engine)
                self.engine._pending_handler_ready = False
            return None

        return None

    def _handle_equipped_ring_effects(self) -> None:
        """Apply effects from equipped rings, honoring per-ring cooldowns."""
        for actor in list(self.engine.game_map.actors):
            equipment = getattr(actor, "equipment", None)
            if not equipment:
                continue

            for item in list(getattr(equipment, "equipped_items", {}).values()):
                if not item:
                    continue
                equippable = getattr(item, "equippable", None)
                if not equippable:
                    continue
                eq_type = getattr(equippable, "equipment_type", None)
                if not eq_type or getattr(eq_type, "name", "") != "RING":
                    continue

                try:
                    equippable.apply_effect(actor)
                except Exception:
                    # Ring effects are optional; never crash turn flow.
                    pass
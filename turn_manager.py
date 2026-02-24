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
from typing import TYPE_CHECKING

import color
from components.effect import Effect
from liquid_system import LiquidType
from text_utils import orange, red
import sounds

if TYPE_CHECKING:
    from engine import Engine
    from input_handlers import BaseEventHandler


class TurnManager:
    """Supreme Turn Manager - Manages initiative-based turn order for all actors."""
    
    def __init__(self, engine: Engine):
        self.engine = engine
        self.total_player_moves = 0  # Track total player moves for hunger system
        self.turn_queue = []  # List of (initiative, actor) tuples
        self.current_turn_actor = None
    
    def process_pre_player_turn(self) -> BaseEventHandler | None:
        """Process all actors who should act before the player based on initiative."""
        return self._process_turn_queue_until_player()
    
    def _process_turn_queue_until_player(self) -> BaseEventHandler | None:
        """Process turns until it's the player's turn or queue is empty."""
        self._rebuild_turn_queue()
        
        while self.turn_queue:
            # Get the next actor to act (highest initiative)
            initiative, actor = self.turn_queue.pop(0)
            
            # If it's the player's turn, stop here
            if actor == self.engine.player:
                return None
                
            # Process enemy turn
            if actor.ai:
                try:
                    actor.ai.perform()
                    actor.initiative_counter -= 100  # Consume action
                except Exception:
                    actor.initiative_counter -= 100  # Still consume turn
                    
                # Check if player died
                if not self.engine.player.is_alive:
                    from input_handlers import GameOverEventHandler
                    return GameOverEventHandler(self.engine)
        
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
        
        # Sort by initiative (highest first)
        self.turn_queue.sort(key=lambda x: x[0], reverse=True)
    
    def process_player_turn_end(self) -> BaseEventHandler | None:
        """
        Called after a valid player action to process all turn-end effects.
        
        Returns:
            BaseEventHandler if we need to switch handlers (like GameOver), None otherwise.
        """
        # 1. Handle equipment durability (torches burning out, etc.)
        handler_change = self._handle_equipment_durability()
        if handler_change:
            return handler_change
        # Hunger / saturation handling:
        # - Saturation decreases faster each tick (represents recent food buffering).
        # - While saturation is high, hunger decreases slowly. As saturation depletes
        #   the hunger decrease ramps up to the full rate when saturation == 0.
        player = self.engine.player
        base_hunger_decrease = 0.13
        saturation_decay = 0.22  # how quickly saturation is consumed per tick

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


        #print(f"Hunger: {player.hunger:.2f}, Saturation: {player.saturation:.2f}, Mult: {hunger_mult:.2f}, TotalMoves: {self.total_player_moves}")
        
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
            self.engine.game_map.liquid_system.process_aging()

        # 8. Process liquid coating entities
        self._process_body_part_liquid_coating()
        self._process_body_part_coating_evaporation()

        
        return None
    
    def _process_body_part_liquid_coating(self) -> None:
        """Apply or remove liquid coatings on body parts based on current tile."""
        try:
            for entity in list(self.engine.game_map.entities):
                # Check if entity has body parts and is in a liquid tile
                if hasattr(entity, 'body_parts') and entity.body_parts and hasattr(self.engine.game_map, 'liquid_system'):
                    # Get the liquid at the entity's position
                    liquid_coating = self.engine.game_map.liquid_system.get_coating(entity.x, entity.y)
                    
                    # Find all limbs tagged with "foot"
                    for body_part in entity.body_parts.body_parts.values():
                        if "foot" in body_part.tags:
                            if liquid_coating and liquid_coating.depth >= 1:
                                # Only coat feet if liquid is deep enough (depth >= 1)
                                if body_part.coating != liquid_coating.liquid_type:
                                    body_part.coating = liquid_coating.liquid_type
                                    body_part.coating_age = 0  # Reset age when newly coated
                                    # Debug: Print coating info if this is the player
                                    if entity == self.engine.player:
                                        print(f"COATED: {body_part.name} with {liquid_coating.liquid_type.get_display_name()}")
                            else:
                                # Clear coating if not in deep liquid (but only occasionally to simulate gradual removal)
                                if body_part.coating != LiquidType.NONE:
                                    # Only clear coating with some delay (not instantly when stepping out)
                                    if body_part.coating_age > 5:  # Wait at least 5 turns before clearing
                                        body_part.coating = LiquidType.NONE
                                        body_part.coating_age = 0
                                        # Debug: Print clearing info if this is the player
                                        if entity == self.engine.player:
                                            print(f"CLEARED: {body_part.name} coating cleared after being away from liquid")
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
                                if entity == self.engine.player:
                                    print(f"EVAPORATED: {body_part.name} coating ({coating_name}) evaporated after {body_part.coating_age} turns (chance: {evap_chance})")
                                body_part.coating = LiquidType.NONE
                                body_part.coating_age = 0
        except Exception:
            import traceback
            traceback.print_exc()
    
    def _update_player_state(self) -> None:
        """Update player state"""
        if self.engine.player.hunger <= 25.0:
            # Check if already has hunger effect
            has_hunger = any(getattr(e, "type", "") == ("Hungry") or getattr(e, "type", "") == ("Starving") for e in self.engine.player.effects)
            if not has_hunger:
                self.engine.message_log.add_message("You feel hungry.", color.yellow)
                
                self.engine.player.add_effect(
                    effect = Effect(
                                name=orange("Hungry"),
                                duration=None,
                                description="Causes periodic damage due to starvation.",
                                type="Hungry"
                    )
                )
        if self.engine.player.hunger <= 10.0:
            # Already starving?
            has_starving = any(getattr(e, "type", "") == ("Starving") for e in self.engine.player.effects)
            if not has_starving:
                self.engine.message_log.add_message("You are starving!", color.red)
                self.engine.player.add_effect(
                    effect=Effect(
                        name=red("Starving"),
                        duration=None,
                        description="Causes severe damage due to starvation.",
                        type="Starving"
                ))
            # Remove hungry effect if present
            has_hunger = any(getattr(e, "type", "") == "Hungry" for e in self.engine.player.effects)
            if has_hunger:
                self.engine.player.remove_effect("Hungry")
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
                self.engine.message_log.add_message(f"Your {item.name} burns out.", color.error)
            
            # Also check legacy slots for backward compatibility
            for slot in ("weapon", "offhand"):
                item = getattr(player.equipment, slot)
                if item is not None and getattr(item, "burn_duration", None) is not None:
                    try:
                        item.burn_duration -= 1
                        if item.burn_duration <= 0:
                            # Use new unequip method which handles both systems
                            player.equipment.unequip_item(item, add_message=False)
                            try:
                                # Remove from inventory if present
                                if item in player.inventory.items:
                                    player.inventory.items.remove(item)
                            except Exception:
                                pass
                            sounds.torch_burns_out_sound.play()
                            self.engine.message_log.add_message(f"Your {item.name} burns out.", color.error)
                    except Exception:
                        pass
        except Exception:
            pass
        return None
    

    
    def _process_remaining_turns(self) -> None:
        """Process any actors who still have initiative to act after the player."""
        # Consume player's action
        self.engine.player.initiative_counter -= 100
        
        # Rebuild queue and process remaining turns
        self._rebuild_turn_queue()
        
        for initiative, actor in self.turn_queue:
            if actor != self.engine.player and actor.ai:
                try:
                    actor.ai.perform()
                    actor.initiative_counter -= 100
                except Exception:
                    actor.initiative_counter -= 100
    
    def _update_fov(self) -> None:
        """Update the player's field of view."""
        self.engine.update_fov()
    
    def _handle_status_effects(self) -> None:
        """Handle darkness, lucidity, and other environmental effects."""
        # Handle darkness and lucidity system
        player_effects = getattr(self.engine.player, "effects", [])
        has_darkness = "Darkness" in [getattr(e, "name", "") for e in player_effects]
        
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
        from input_handlers import GameOverEventHandler, LevelUpEventHandler
        
        if not self.engine.player.is_alive:
            return GameOverEventHandler(self.engine)
        elif self.engine.player.level.requires_level_up:
            return LevelUpEventHandler(self.engine)
        
        return None
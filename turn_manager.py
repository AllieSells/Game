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
from text_utils import orange, red
import sounds

if TYPE_CHECKING:
    from engine import Engine
    from input_handlers import BaseEventHandler


class TurnManager:
    """Manages all turn-based logic and systems that run after player actions."""
    
    def __init__(self, engine: Engine):
        self.engine = engine
        self.total_player_moves = 0  # Track total player moves for hunger system
    
    def process_pre_player_turn(self) -> BaseEventHandler | None:
        """
        Called before the player acts to handle fast enemy actions.
        Fast enemies can act before the player if their speed allows it.
        
        Returns:
            BaseEventHandler if we need to switch handlers (like GameOver), None otherwise.
        """
        # Process fast enemy turns that can act before the player
        handler_change = self._handle_fast_enemy_turns()
        if handler_change:
            return handler_change
        return None
    
    def process_player_turn_end(self) -> BaseEventHandler | None:
        """
        Called after a valid player action to process all turn-end effects.
        
        Returns:
            BaseEventHandler if we need to switch handlers (like GameOver), None otherwise.
        """
        # Increment player's initiative counter
        self.engine.player.initiative_counter += self.engine.player.get_effective_speed()
        
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
        
        # 2. Process enemy turns
        self._handle_enemy_turns()
        
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
        
        return None
    
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
    
    def _handle_fast_enemy_turns(self) -> BaseEventHandler | None:
        """Process turns for enemies that are fast enough to act before the player."""
        player_threshold = self.engine.player.initiative_counter + self.engine.player.get_effective_speed()
        fast_actions_taken = False
        
        # Track which entities acted in fast phase to prevent double actions
        if not hasattr(self, '_entities_acted_fast'):
            self._entities_acted_fast = set()
        self._entities_acted_fast.clear()  # Reset for new turn
        
        for entity in set(self.engine.game_map.actors) - {self.engine.player}:
            if entity.ai and entity.get_effective_speed() > 100:  # Only fast enemies (effective speed > 100)
                # Increment entity's initiative
                entity.initiative_counter += entity.get_effective_speed()
                
                # Check if this entity can act before the player's next turn
                if entity.initiative_counter >= player_threshold:
                    try:
                        if not fast_actions_taken:
                            # Only show this message once per turn cycle
                            self.engine.message_log.add_message("You sense movement in the shadows...", color.gray)
                            fast_actions_taken = True
                        
                        entity.ai.perform()
                        entity.initiative_counter -= 100  # Reduce by base action cost
                        self._entities_acted_fast.add(entity)  # Mark as acted in fast phase
                        
                        # Check if player died
                        if not self.engine.player.is_alive:
                            from input_handlers import GameOverEventHandler
                            return GameOverEventHandler(self.engine)
                            
                    except Exception:  # Changed from exceptions.Impossible to catch all
                        entity.initiative_counter -= 100  # Still consume the turn
        return None
    
    def _handle_enemy_turns(self) -> None:
        """Process all enemy AI turns, but skip those that already acted in fast phase."""
        # Ensure the fast entities tracker exists
        if not hasattr(self, '_entities_acted_fast'):
            self._entities_acted_fast = set()
        
        for entity in set(self.engine.game_map.actors) - {self.engine.player}:
            if entity.ai:
                # Skip entities that already acted in the fast phase this turn
                if entity in self._entities_acted_fast:
                    continue
                    
                # Increment entity's initiative
                entity.initiative_counter += entity.get_effective_speed()
                
                # Check if this entity should act this turn
                while entity.initiative_counter >= 100:  # 100 is the base action threshold
                    try:
                        entity.ai.perform()
                        entity.initiative_counter -= 100  # Reduce by base action cost
                    except Exception:  # Changed from exceptions.Impossible to catch all
                        entity.initiative_counter -= 100  # Still consume the turn
                        break  # Stop this entity from acting more this round
    
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
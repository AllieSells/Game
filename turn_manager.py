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

if TYPE_CHECKING:
    from engine import Engine
    from input_handlers import BaseEventHandler


class TurnManager:
    """Manages all turn-based logic and systems that run after player actions."""
    
    def __init__(self, engine: Engine):
        self.engine = engine
    
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
        
        # 2. Process enemy turns
        self._handle_enemy_turns()
        
        # 3. Update field of view
        self._update_fov()
        
        # 4. Handle status effects and environmental effects
        self._handle_status_effects()
        
        # 5. Handle special game state checks (level up, death, etc.)
        handler_change = self._handle_game_state_checks()
        if handler_change:
            return handler_change
        
        return None
    
    def _handle_equipment_durability(self) -> BaseEventHandler | None:
        """Handle equipment that degrades over time (like torches)."""
        try:
            player = self.engine.player
            for slot in ("weapon", "offhand"):
                item = getattr(player.equipment, slot)
                if item is not None and getattr(item, "burn_duration", None) is not None:
                    try:
                        item.burn_duration -= 1
                        if item.burn_duration <= 0:
                            # Remove the burned-out item: unequip and drop/consume
                            player.equipment.unequip_from_slot(slot, add_message=False)
                            try:
                                # Remove from inventory if present
                                if item in player.inventory.items:
                                    player.inventory.items.remove(item)
                            except Exception:
                                pass
                            self.engine.message_log.add_message(f"Your {item.name} burns out.", color.error)
                    except Exception:
                        pass
        except Exception:
            pass
        return None
    
    def _handle_enemy_turns(self) -> None:
        """Process all enemy AI turns."""
        for entity in set(self.engine.game_map.actors) - {self.engine.player}:
            if entity.ai:
                try:
                    entity.ai.perform()
                except Exception:  # Changed from exceptions.Impossible to catch all
                    pass  # Ignore failed enemy actions
    
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
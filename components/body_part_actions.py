"""
Body Part Actions

Actions for interacting with the body parts system.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from actions import Action
import color

if TYPE_CHECKING:
    from entity import Actor


class InspectBodyAction(Action):
    """Action to inspect the player's body parts."""
    
    def __init__(self, entity: Actor):
        super().__init__(entity)
    
    def perform(self) -> None:
        """Show detailed body part status."""
        if not hasattr(self.entity, 'body_parts') or not self.entity.body_parts:
            self.engine.message_log.add_message(
                "You have no body parts to examine.",
                color.impossible
            )
            return
        
        body_parts = self.entity.body_parts
        
        # Overall status
        if body_parts.is_alive():
            if len(body_parts.get_damaged_parts()) == 0:
                self.engine.message_log.add_message(
                    "Your body is in perfect condition.",
                    color.health_recovered
                )
            else:
                self.engine.message_log.add_message(
                    "You examine your body for injuries...",
                    color.gray
                )
        else:
            self.engine.message_log.add_message(
                "Your body is failing! Vital organs are destroyed!",
                color.player_die
            )
        
        # Detailed status for each part
        status_descriptions = body_parts.get_status_description()
        for description in status_descriptions[:3]:  # Limit to 3 lines to avoid spam
            if "destroyed" in description:
                desc_color = color.enemy_die
            elif "severely wounded" in description or "badly wounded" in description:
                desc_color = color.health_recovered  
            elif "wounded" in description:
                desc_color = color.yellow
            else:
                desc_color = color.gray
            
            self.engine.message_log.add_message(description.capitalize(), desc_color)
        
        # Movement status
        if not body_parts.can_move():
            self.engine.message_log.add_message(
                "You cannot move with your current injuries!",
                color.impossible
            )
        elif body_parts.get_movement_penalty() > 0.5:
            self.engine.message_log.add_message(
                "Your movement is severely impaired.",
                color.health_recovered
            )
        elif body_parts.get_movement_penalty() > 0.2:
            self.engine.message_log.add_message(
                "Your movement is somewhat impaired.",
                color.yellow
            )
        
        # Hands status
        if not body_parts.can_use_hands():
            self.engine.message_log.add_message(
                "You cannot use your hands!",
                color.impossible
            )


class HealBodyPartAction(Action):
    """Action to heal a specific body part (for testing/magic)."""
    
    def __init__(self, entity: Actor, part_name: str, amount: int = 5):
        super().__init__(entity)
        self.part_name = part_name
        self.amount = amount
    
    def perform(self) -> None:
        """Heal a specific body part."""
        if not hasattr(self.entity, 'body_parts') or not self.entity.body_parts:
            self.engine.message_log.add_message(
                "No body parts to heal.",
                color.impossible
            )
            return
        
        body_parts = self.entity.body_parts
        
        # Try to find the part by name
        target_part = None
        for part in body_parts.get_all_parts().values():
            if self.part_name.lower() in part.name.lower():
                target_part = part
                break
        
        if not target_part:
            self.engine.message_log.add_message(
                f"Cannot find body part: {self.part_name}",
                color.impossible
            )
            return
        
        if not target_part.is_damaged:
            self.engine.message_log.add_message(
                f"Your {target_part.name} is already healthy.",
                color.gray
            )
            return
        
        healing = target_part.heal(self.amount)
        if healing > 0:
            self.engine.message_log.add_message(
                f"Your {target_part.name} heals for {healing} points.",
                color.health_recovered
            )
        else:
            self.engine.message_log.add_message(
                f"Your {target_part.name} cannot be healed further.",
                color.gray
            )
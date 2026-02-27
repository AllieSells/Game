"""
Modular Trait XP System

This system maps specific actions to trait improvements, allowing for flexible
and extensible character progression based on action usage.

Traits supported:
- Strength: Improved by melee combat, heavy lifting, etc.
- Dexterity: Improved by ranged combat, movement, dodging, etc.
- Constitution: Improved by taking damage, healing, endurance activities, etc.

The system is designed to be easily extensible for future traits and actions.
"""

from __future__ import annotations
from typing import Dict, List, Tuple, TYPE_CHECKING, Union, Any
from enum import Enum
import random

if TYPE_CHECKING:
    from entity import Actor
    from actions import Action

class TraitType(Enum):
    """Available character traits that can gain XP."""
    STRENGTH = "strength"
    DEXTERITY = "dexterity" 
    CONSTITUTION = "constitution"

class ActionCategory(Enum):
    """Categories of actions that can grant trait XP."""
    MELEE_ATTACK = "melee_attack"
    RANGED_ATTACK = "ranged_attack"
    MOVEMENT = "movement"
    TAKE_DAMAGE = "take_damage"
    HEALING = "healing"
    BLOCK_ATTACK = "block_attack"
    DODGE = "dodge"
    HEAVY_LIFTING = "heavy_lifting"
    STEALTH = "stealth"
    ENDURANCE = "endurance"

# Mapping of action categories to traits and base XP amounts
# Format: ActionCategory: [(TraitType, base_xp), ...]
ACTION_TRAIT_MAPPING = {
    ActionCategory.MELEE_ATTACK: [
        (TraitType.STRENGTH, 1),  # Primary trait gets more XP
        (TraitType.CONSTITUTION, 1)  # Secondary traits get less XP
    ],
    ActionCategory.RANGED_ATTACK: [
        (TraitType.DEXTERITY, 1),
        (TraitType.STRENGTH, 1)  # Drawing bow requires some strength
    ],
    ActionCategory.MOVEMENT: [
        (TraitType.DEXTERITY, 1),
        (TraitType.CONSTITUTION, 1)
    ],
    ActionCategory.TAKE_DAMAGE: [
        (TraitType.CONSTITUTION, 1)
    ],
    ActionCategory.HEALING: [
        (TraitType.CONSTITUTION, 1)
    ],
    ActionCategory.BLOCK_ATTACK: [
        (TraitType.STRENGTH, 1),
        (TraitType.CONSTITUTION, 1)
    ],
    ActionCategory.DODGE: [
        (TraitType.DEXTERITY, 1)
    ],
    ActionCategory.HEAVY_LIFTING: [
        (TraitType.STRENGTH, 1)  # High XP for strength-focused actions
    ],
    ActionCategory.STEALTH: [
        (TraitType.DEXTERITY, 1)
    ],
    ActionCategory.ENDURANCE: [
        (TraitType.CONSTITUTION, 1)
    ]
}

class TraitXPModifier:
    """Represents a modifier that can affect trait XP gain."""
    def __init__(self, name: str, multiplier: float = 1.0, bonus: int = 0):
        self.name = name
        self.multiplier = multiplier  # Multiply base XP by this amount
        self.bonus = bonus  # Add this flat amount to XP

class TraitXPManager:
    """Manages trait XP calculations and distribution."""
    
    def __init__(self):
        self.active_modifiers: Dict[str, TraitXPModifier] = {}
    
    def add_modifier(self, modifier: TraitXPModifier):
        """Add a temporary modifier to XP calculations."""
        self.active_modifiers[modifier.name] = modifier
    
    def remove_modifier(self, name: str):
        """Remove a modifier by name."""
        self.active_modifiers.pop(name, None)
    
    def calculate_trait_xp(self, action_category: ActionCategory, actor: Actor) -> Dict[TraitType, int]:
        """
        Calculate how much XP each trait should receive for a given action category.
        
        Args:
            action_category: The category of action performed
            actor: The actor performing the action
            
        Returns:
            Dictionary mapping TraitType to XP amount
        """
        if action_category not in ACTION_TRAIT_MAPPING:
            return {}
        
        trait_xp = {}
        base_mappings = ACTION_TRAIT_MAPPING[action_category]
        
        for trait_type, base_xp in base_mappings:
            # Start with base XP
            final_xp = base_xp
            
            # Apply modifiers
            for modifier in self.active_modifiers.values():
                final_xp = int(final_xp * modifier.multiplier) + modifier.bonus
            
            
            # Ensure minimum of 1 XP
            final_xp = max(1, final_xp)
            
            trait_xp[trait_type] = final_xp
        
        return trait_xp
    
    def grant_trait_xp(self, actor: Actor, action_category: ActionCategory, multiplier: float = 1.0):
        """
        Grant trait XP to an actor based on an action category.
        
        Args:
            actor: The actor to grant XP to
            action_category: The category of action performed
            multiplier: Additional multiplier for this specific action
        """
        if not hasattr(actor, 'level') or not actor.level:
            return
        
        trait_xp = self.calculate_trait_xp(action_category, actor)
        
        for trait_type, xp_amount in trait_xp.items():
            adjusted_xp = max(1, int(xp_amount * multiplier))
            actor.level.add_trait_xp(trait_type, adjusted_xp)

# Global instance for easy access
trait_xp_manager = TraitXPManager()

def categorize_action(action: 'Action') -> Union[ActionCategory, None]:
    """
    Categorize an action to determine what trait XP it should grant.
    
    This function can be extended to handle new action types.
    
    Args:
        action: The action to categorize
        
    Returns:
        ActionCategory if the action grants XP, None otherwise
    """
    action_name = action.__class__.__name__
    
    # Map specific action classes to categories
    action_mapping = {
        'MeleeAction': ActionCategory.MELEE_ATTACK,
        'RangedAction': ActionCategory.RANGED_ATTACK,
    }
    
    return action_mapping.get(action_name)

def grant_action_xp(actor: Actor, action: Action, multiplier: float = 1.0):
    """
    Convenience function to grant trait XP based on an action.
    
    Args:
        actor: The actor performing the action
        action: The action being performed
        multiplier: Additional multiplier for this action
    """
    category = categorize_action(action)
    if category:
        trait_xp_manager.grant_trait_xp(actor, category, multiplier)

# Utility functions for common scenarios
def grant_damage_taken_xp(actor: Actor, damage_amount: int):
    """Grant constitution XP when taking damage."""
    # More damage = more XP (up to a reasonable limit)
    multiplier = min(2.0, 1.0 + (damage_amount / 10.0))
    trait_xp_manager.grant_trait_xp(actor, ActionCategory.TAKE_DAMAGE, multiplier)

def grant_dodge_xp(actor: Actor):
    """Grant dexterity XP for successful dodges."""
    trait_xp_manager.grant_trait_xp(actor, ActionCategory.DODGE)

def grant_block_xp(actor: Actor):
    """Grant strength and constitution XP for blocking attacks."""
    trait_xp_manager.grant_trait_xp(actor, ActionCategory.BLOCK_ATTACK)

# Trait progression utility functions
def get_trait_xp_to_next_level(actor: Actor, trait_type: TraitType) -> int:
    """Get XP needed for the next trait level."""
    if not hasattr(actor, 'level') or not actor.level:
        return 0
        
    current_level = actor.level.get_trait_level(trait_type)
    
    if trait_type == TraitType.STRENGTH:
        return actor.level.strength_level_up_base + current_level * actor.level.strength_level_up_factor
    elif trait_type == TraitType.DEXTERITY:
        return actor.level.dexterity_level_up_base + current_level * actor.level.dexterity_level_up_factor
    elif trait_type == TraitType.CONSTITUTION:
        return actor.level.constitution_level_up_base + current_level * actor.level.constitution_level_up_factor
    return 0

def get_trait_xp_remaining(actor: Actor, trait_type: TraitType) -> int:
    """Get XP remaining until next trait level."""
    if not hasattr(actor, 'level') or not actor.level:
        return 0
        
    current_xp = actor.level.get_trait_xp(trait_type)
    xp_needed = get_trait_xp_to_next_level(actor, trait_type)
    return max(0, xp_needed - current_xp)

def get_trait_progress_percent(actor: Actor, trait_type: TraitType) -> float:
    """Get progress toward next trait level as a percentage (0.0 to 1.0)."""
    if not hasattr(actor, 'level') or not actor.level:
        return 0.0
        
    current_xp = actor.level.get_trait_xp(trait_type)
    xp_needed = get_trait_xp_to_next_level(actor, trait_type)
    
    if xp_needed == 0:
        return 1.0  # Max level or no progression
    
    return min(1.0, current_xp / xp_needed)

def trait_requires_level_up(actor: Actor, trait_type: TraitType) -> bool:
    """Check if a trait is ready to be leveled up."""
    if not hasattr(actor, 'level') or not actor.level:
        return False
        
    current_xp = actor.level.get_trait_xp(trait_type)
    xp_needed = get_trait_xp_to_next_level(actor, trait_type)
    return current_xp >= xp_needed and xp_needed > 0

def get_all_trait_info(actor: Actor) -> Dict[TraitType, Dict[str, Any]]:
    """Get comprehensive trait information for all traits."""
    if not hasattr(actor, 'level') or not actor.level:
        return {}
        
    trait_info = {}
    for trait in TraitType:
        trait_info[trait] = {
            'level': actor.level.get_trait_level(trait),
            'current_xp': actor.level.get_trait_xp(trait),
            'xp_to_next': get_trait_xp_to_next_level(actor, trait),
            'xp_remaining': get_trait_xp_remaining(actor, trait),
            'progress_percent': get_trait_progress_percent(actor, trait),
            'ready_to_level': trait_requires_level_up(actor, trait)
        }
    return trait_info
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Callable

from components.base_component import BaseComponent

if TYPE_CHECKING:
    from entity import Actor

import sounds

class Level(BaseComponent):
    parent: Actor

    # Add new traits here - just add the trait name to this list
    TRAITS = ['strength',
              'agility',
              'vigor',
              'armor',
              'light armor',
              'medium armor',
              'heavy armor',
              'shields',
              'blades',
              'daggers',
              'swords',
              ]
    
    # Define trait categories - traits that serve as category headers
    # Format: 'category_trait': ['subcategory1', 'subcategory2', ...]
    TRAIT_CATEGORIES = {
        'strength': ['agility', 'vigor'],
        'armor': ['light armor', 'medium armor', 'heavy armor', 'shields'],
        'blades': ['daggers', 'swords'],
    }
    
    # Trait abbreviations for compact display
    TRAIT_ABBREVIATIONS = {
        'strength': 'STR',
        'agility': 'AGI', 
        'vigor': 'VIG',
        'armor': 'ARM',
        'light armor': 'LARM',
        'medium armor': 'MARM',
        'heavy armor': 'HARM',
        'shields': 'SHD',
        'blades': 'BLD',
        'daggers': 'DAG',
        'swords': 'SWD',
    }
    
    # Special non-trait stats to include
    SPECIAL_STATS = ['level', 'gold', 'hp']
    
    # Default values for all traits
    DEFAULT_LEVEL_UP_BASE = 0
    DEFAULT_LEVEL_UP_FACTOR = 10

    def __init__(
        self,
        current_level: int = 1,
        current_xp: int = 0,
        level_up_base: int = 50,
        level_up_factor: int = 100,
        xp_given: int = 0,
        score: int = 0
    ):
        # Initialize trait data dynamically
        self.traits = {}
        for trait_name in self.TRAITS:
            self.traits[trait_name] = {
                'level': 1,
                'xp': 0
            }
            
        self.current_level = current_level
        self.current_xp = current_xp
        self.level_up_base = level_up_base
        self.level_up_factor = level_up_factor
        self.xp_given = xp_given
        self.score = score


    def xp_to_next(self, trait: str) -> int:
        if trait in self.traits:
            current_level = self.traits[trait]['level']
            return self.level_up_base + current_level * self.level_up_factor
        return 0

    def total_xp(self, trait: str) -> int:
        if trait in self.traits:
            return self.traits[trait]['xp']
        return 0

    def add_xp(self, trait_awards: Dict[str, int], multiplier: float = 1.0) -> None:
        for trait_name, xp in trait_awards.items():
            if trait_name in self.traits:
                self.traits[trait_name]['xp'] += int(xp * multiplier)

                # Check if trait levels up
                while self.traits[trait_name]['xp'] >= self.xp_to_next(trait_name):
                    self.level_up(trait_name)

    def level_up(self, trait_name: str) -> None:
        """Handles level up benefits for traits"""
        # Calculate XP required for this level up
        xp_required = self.xp_to_next(trait_name)
        
        # Subtract the required XP and increment level
        self.traits[trait_name]['xp'] -= xp_required
        self.traits[trait_name]['level'] += 1

        # Message to indicate level up
        if hasattr(self.parent, 'parent') and hasattr(self.parent.parent, 'engine'):
            self.parent.parent.engine.message_log.add_message(
                f"{trait_name.capitalize()} increased to level {self.traits[trait_name]['level']}!", 
                fg=(0, 255, 0)  # Green color as RGB tuple
            )
        import sounds
        sounds.play_level_up_sound()

        
        # Apply trait-specific benefits
        if trait_name == 'vigor':
            self._increase_max_health()
    
    def _increase_max_health(self, health_per_level: int = 5) -> None:
        """Increase max health and redistribute to body parts proportionally."""
        if not hasattr(self.parent, 'fighter') or not hasattr(self.parent, 'body_parts'):
            return
            
        # Calculate new max health
        old_max_hp = self.parent.fighter.max_hp
        new_max_hp = old_max_hp + health_per_level
        
        # Update fighter component
        self.parent.fighter.max_hp = new_max_hp
        self.parent.fighter.hp = min(self.parent.fighter.hp + health_per_level, new_max_hp)
        
        # Use the existing method to redistribute to body parts
        self.parent.body_parts.set_max_health(new_max_hp)
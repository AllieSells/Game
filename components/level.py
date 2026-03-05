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
              'arcana',
              'abjuration',
              'conjuration',
              'divination',
              'enchantment',
              'evocation',
              'illusion',
                'necromancy',
                'transmutation'

                
              ]
    
    # Define trait categories - traits that serve as category headers
    # Format: 'category_trait': ['subcategory1', 'subcategory2', ...]
    TRAIT_CATEGORIES = {
        'strength': ['agility', 'vigor'],
        'armor': ['light armor', 'medium armor', 'heavy armor', 'shields'],
        'blades': ['daggers', 'swords'],
        'arcana': ['abjuration', 'conjuration', 'divination', 'enchantment', 'evocation', 'illusion', 'necromancy', 'transmutation']
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
        'arcana': 'ARC',
        'abjuration': 'ABJ',
        'conjuration': 'CON',
        'divination': 'DIV',
        'enchantment': 'ENC',
        'evocation': 'EVO',
        'illusion': 'ILL',
        'necromancy': 'NEC',
        'transmutation': 'TRN'
    }
    
    # Special non-trait stats to include
    SPECIAL_STATS = ['level', 'gold', 'hp']
    
    # Default values for all traits
    DEFAULT_LEVEL_UP_BASE = 50

    def __init__(
        self,
        current_level: int = 1,
        current_xp: int = 0,
        level_up_base: int = 50,
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
        self.xp_given = xp_given
        self.score = score


    def xp_to_next(self, trait: str) -> int:
        if trait in self.traits:
            current_level = self.traits[trait]['level']
            return self.level_up_base * (current_level ** 2)  # Quadratic
        return 0

    def total_xp(self, trait: str) -> int:
        if trait in self.traits:
            return self.traits[trait]['xp']
        return 0

    def add_xp(self, trait_awards: Dict[str, int], multiplier: float = 1.0) -> None:
        print(trait_awards)
        any_level_ups = False  # Track if any level ups occurred
        
        for trait_name, xp in trait_awards.items():
            print(f"Adding {int(xp * multiplier)} XP to {trait_name} (Before: {self.total_xp(trait_name)} XP)")
            if trait_name in self.traits:
                self.traits[trait_name]['xp'] += int(xp * multiplier)
                print(f"Added {int(xp * multiplier)} XP to {trait_name} (Total: {self.traits[trait_name]['xp']} XP)")

                # Check if trait levels up
                while self.traits[trait_name]['xp'] >= self.xp_to_next(trait_name):
                    self.level_up(trait_name, play_sound=False)  # Don't play sound for individual level ups
                    any_level_ups = True
        
        # Play level up sound once if any traits leveled up
        if any_level_ups:
            sounds.play_level_up_sound()

    def level_up(self, trait_name: str, play_sound: bool = True) -> None:
        """Handles level up benefits for traits"""
        # Calculate XP required for this level up
        xp_required = self.xp_to_next(trait_name)
        
        # Safety check to prevent infinite loops
        if xp_required <= 0:
            return
        
        # Subtract the required XP and increment level
        self.traits[trait_name]['xp'] -= xp_required
        level_increased_to = self.traits[trait_name]['level'] + 1
        self.traits[trait_name]['level'] = level_increased_to

        if trait_name == 'vigor':
            # When vigor levels up, also increase max health and redistribute to body parts
            self._increase_max_health(health_per_level=5)
        elif trait_name == 'arcana':
            # When arcana levels up, increase mana and max mana
            if hasattr(self.parent, 'mana') and hasattr(self.parent, 'mana_max'):
                self.parent.mana_max += 10
                self.parent.mana = min(self.parent.mana + 10, self.parent.mana_max)
        elif trait_name in ['abjuration', 'conjuration', 'divination', 'enchantment', 'evocation', 'illusion', 'necromancy', 'transmutation']:
            for spell in self.parent.known_spells:
                if spell.school == trait_name:
                    spell.level_up_spell(level_increased_to, self.parent)
                    

        # Message to indicate level up
        if hasattr(self.parent, 'parent') and hasattr(self.parent.parent, 'engine'):
            self.parent.parent.engine.message_log.add_message(
                f"{trait_name.capitalize()} increased to level {self.traits[trait_name]['level']}!", 
                fg=(0, 255, 0)  # Green color as RGB tuple
            )
        
        # Only play sound if requested
        if play_sound:
            sounds.play_level_up_sound()
    
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
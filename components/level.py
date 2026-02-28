from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Callable

from components.base_component import BaseComponent

if TYPE_CHECKING:
    from entity import Actor
    from trait_xp_system import TraitType

import sounds
"""
Add trait name to TRAITS = ['strength', 'dexterity', 'constitution', 'blades', 'NEW_TRAIT']
Add NEW_TRAIT = "new_trait" to TraitType enum
Create _level_up_new_trait() method
Update trait mappings in the 3 methods
"""
class Level(BaseComponent):
    parent: Actor

    # Add new traits here - just add the trait name to this list
    TRAITS = ['strength', 'dexterity', 'constitution', 'blades', 'daggers', 'swords']
    
    # Default values for all traits
    DEFAULT_LEVEL_UP_BASE = 0
    DEFAULT_LEVEL_UP_FACTOR = 150

    def __init__(
        self,
        current_level: int = 1,
        current_xp: int = 0,
        level_up_base: int = 0,
        level_up_factor: int = 150,
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

    @property
    def experience_to_next_level(self) -> int:
        return self.level_up_base + self.current_level * self.level_up_factor

    @property
    def requires_level_up(self) -> bool:
        return self.current_xp >= self.experience_to_next_level

    def add_xp(self, xp: int) -> None:
        # Overall XP system is being phased out in favor of trait-based progression
        # Only score tracking remains active
        if xp == 0:
            return

        self.score += xp
        # No longer granting overall XP or level ups - traits handle progression now

    def increase_level(self) -> None:
        self.current_xp -= self.experience_to_next_level

        self.current_level += 1


    def increase_max_hp(self, amount: int = 20) -> None:
        old_max_hp = self.parent.fighter.max_hp
        self.parent.fighter.max_hp += amount
        self.parent.fighter.hp += amount

        # Recalculate body part max HP to maintain proportions
        # Each part gets its share of the new HP pool
        if hasattr(self.parent, 'body_parts') and self.parent.body_parts:
            hp_increase = amount
            for part in self.parent.body_parts.body_parts.values():
                # Increase part's max_hp proportionally
                old_part_max = part.max_hp
                new_part_max = int(part.max_hp_ratio * self.parent.fighter.max_hp)
                part_increase = new_part_max - old_part_max
                part.max_hp = new_part_max
                # Heal the part by the increase amount to maintain health ratio
                part.current_hp = min(part.max_hp, part.current_hp + part_increase)

        self.engine.message_log.add_message("Your health improves!")

        self.increase_level()

    def increase_power(self, amount: int = 1) -> None:
        self.parent.fighter.base_power += amount

        self.engine.message_log.add_message("You feel stronger!")

        self.increase_level()

    def increase_defense(self, amount: int = 1) -> None:
        self.parent.fighter.base_defense += amount

        self.engine.message_log.add_message("Your movements are getting swifter!")

        self.increase_level()

    # Trait-specific XP and leveling methods
    def add_trait_xp(self, trait_type: 'TraitType', xp: int) -> None:
        """Add XP to a specific trait and handle leveling up."""
        if xp <= 0:
            return
            
        from trait_xp_system import TraitType
        
        # Map TraitType enum to string names
        trait_name_map = {
            TraitType.STRENGTH: 'strength',
            TraitType.DEXTERITY: 'dexterity',
            TraitType.CONSTITUTION: 'constitution',
            TraitType.BLADES: 'blades'
        }
        
        trait_name = trait_name_map.get(trait_type)
        if not trait_name or trait_name not in self.traits:
            return
        
        # Add XP
        old_xp = self.traits[trait_name]['xp']
        current_xp = old_xp + xp
        self.traits[trait_name]['xp'] = current_xp
        
        # Check for level up(s)
        old_level = self.traits[trait_name]['level']
        current_level = old_level
        
        levels_gained = 0
        temp_xp = current_xp
        
        while temp_xp > 0:
            xp_needed = self.DEFAULT_LEVEL_UP_BASE + current_level * self.DEFAULT_LEVEL_UP_FACTOR
            
            if xp_needed <= 0 or temp_xp < xp_needed:
                break
                
            temp_xp -= xp_needed
            current_level += 1
            levels_gained += 1
        
        if levels_gained > 0:
            # Update the trait level and remaining XP
            self.traits[trait_name]['xp'] = temp_xp
            self.traits[trait_name]['level'] = current_level
            
            # Apply trait-specific benefits for each level gained
            for i in range(levels_gained):
                level_method = getattr(self, f'_level_up_{trait_name}', None)
                if level_method:
                    level_method()
            
            # Only show messages and play sounds for the player
            if self.parent == self.engine.player:
                if levels_gained == 1:
                    self.engine.message_log.add_message(
                        f"Your {trait_name} increases to {current_level}!"
                    )
                else:
                    self.engine.message_log.add_message(
                        f"Your {trait_name} increases by {levels_gained} levels to {current_level}!"
                    )
                sounds.play_level_up_sound()

    def _level_up_strength(self) -> None:
        """Handle strength level up benefits."""
        # Increase power and update fighter strength
        self.parent.fighter.base_power += 1
        self.parent.fighter.strength += 1

    def _level_up_dexterity(self) -> None:
        """Handle dexterity level up benefits.""" 
        # Could affect hit chance, dodge chance, etc.
        # For now, just update fighter dexterity
        self.parent.fighter.dexterity += 1

    def _level_up_constitution(self) -> None:
        """Handle constitution level up benefits."""
        # Increase max HP
        old_max_hp = self.parent.fighter.max_hp
        hp_increase = 5  # Constitution gives +5 HP per level
        self.parent.fighter.max_hp += hp_increase
        self.parent.fighter.hp += hp_increase  # Also heal
        
        # Update fighter constitution
        self.parent.fighter.constitution += 1
        
        # Update body parts max HP if they exist
        if hasattr(self.parent, 'body_parts') and self.parent.body_parts:
            for part in self.parent.body_parts.body_parts.values():
                old_part_max = part.max_hp
                new_part_max = int(part.max_hp_ratio * self.parent.fighter.max_hp)
                part_increase = new_part_max - old_part_max
                part.max_hp = new_part_max
                part.current_hp = min(part.max_hp, part.current_hp + part_increase)

    def _level_up_blades(self) -> None:
        """Handle blades level up benefits.""" 
        # Increase weapon skill with bladed weapons
        pass  # Add your blades-specific benefits here

    def get_trait_level(self, trait_type: 'TraitType') -> int:
        """Get the current level of a specific trait."""
        from trait_xp_system import TraitType
        
        trait_name_map = {
            TraitType.STRENGTH: 'strength',
            TraitType.DEXTERITY: 'dexterity', 
            TraitType.CONSTITUTION: 'constitution',
            TraitType.BLADES: 'blades'
        }
        
        trait_name = trait_name_map.get(trait_type)
        if trait_name and trait_name in self.traits:
            return self.traits[trait_name]['level']
        return 1

    def get_trait_xp(self, trait_type: 'TraitType') -> int:
        """Get the current XP of a specific trait."""
        from trait_xp_system import TraitType
        
        trait_name_map = {
            TraitType.STRENGTH: 'strength',
            TraitType.DEXTERITY: 'dexterity',
            TraitType.CONSTITUTION: 'constitution',
            TraitType.BLADES: 'blades'
        }
        
        trait_name = trait_name_map.get(trait_type)
        if trait_name and trait_name in self.traits:
            return self.traits[trait_name]['xp']
        return 0
from __future__ import annotations

from typing import TYPE_CHECKING

from components.base_component import BaseComponent

if TYPE_CHECKING:
    from entity import Actor
    from trait_xp_system import TraitType

import sounds

class Level(BaseComponent):
    parent: Actor

    def __init__(
        self,
        current_strength_level: int = 1,
        current_strength_xp: int = 0,
        strength_level_up_base: int = 0,
        strength_level_up_factor: int = 150,
        current_dexterity_level: int = 1,
        current_dexterity_xp: int = 0,
        dexterity_level_up_base: int = 0,
        dexterity_level_up_factor: int = 150,
        current_constitution_level: int = 1,
        current_constitution_xp: int = 0,
        constitution_level_up_base: int = 0,
        constitution_level_up_factor: int = 150,
        current_level: int = 1,
        current_xp: int = 0,
        level_up_base: int = 0,
        level_up_factor: int = 150,
        xp_given: int = 0,
        score: int = 0
    ):
        self.current_strength_level = current_strength_level
        self.current_strength_xp = current_strength_xp
        self.strength_level_up_base = strength_level_up_base
        self.strength_level_up_factor = strength_level_up_factor
        self.current_dexterity_level = current_dexterity_level
        self.current_dexterity_xp = current_dexterity_xp
        self.dexterity_level_up_base = dexterity_level_up_base
        self.dexterity_level_up_factor = dexterity_level_up_factor
        self.current_constitution_level = current_constitution_level
        self.current_constitution_xp = current_constitution_xp
        self.constitution_level_up_base = constitution_level_up_base
        self.constitution_level_up_factor = constitution_level_up_factor
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
        
        # Map trait types to their corresponding attributes
        trait_info = {
            TraitType.STRENGTH: {
                'current_xp': 'current_strength_xp',
                'current_level': 'current_strength_level', 
                'level_up_base': 'strength_level_up_base',
                'level_up_factor': 'strength_level_up_factor',
                'level_method': self._level_up_strength,
                'name': 'strength'
            },
            TraitType.DEXTERITY: {
                'current_xp': 'current_dexterity_xp',
                'current_level': 'current_dexterity_level',
                'level_up_base': 'dexterity_level_up_base', 
                'level_up_factor': 'dexterity_level_up_factor',
                'level_method': self._level_up_dexterity,
                'name': 'dexterity'
            },
            TraitType.CONSTITUTION: {
                'current_xp': 'current_constitution_xp',
                'current_level': 'current_constitution_level',
                'level_up_base': 'constitution_level_up_base',
                'level_up_factor': 'constitution_level_up_factor', 
                'level_method': self._level_up_constitution,
                'name': 'constitution'
            }
        }
        
        if trait_type not in trait_info:
            return
            
        info = trait_info[trait_type]
        
        # Add XP
        old_xp = getattr(self, info['current_xp'])
        current_xp = old_xp + xp
        setattr(self, info['current_xp'], current_xp)
        
        # Check for level up(s) - handle multiple levels and overflow XP
        old_level = getattr(self, info['current_level'])
        current_level = old_level
        level_up_base = getattr(self, info['level_up_base'])
        level_up_factor = getattr(self, info['level_up_factor'])
        
        levels_gained = 0
        temp_xp = current_xp
        
        while temp_xp > 0:
            xp_needed = level_up_base + current_level * level_up_factor
            
            if xp_needed <= 0 or temp_xp < xp_needed:
                break
                
            # Level up the trait
            temp_xp -= xp_needed
            current_level += 1
            levels_gained += 1
        
        if levels_gained > 0:
            # Update the trait level and remaining XP
            setattr(self, info['current_xp'], temp_xp)
            setattr(self, info['current_level'], current_level)
            
            # Apply trait-specific benefits for each level gained
            for i in range(levels_gained):
                info['level_method']()
            
            # Only show messages and play sounds for the player
            if self.parent == self.engine.player:
                # Show level up message
                if levels_gained == 1:
                    self.engine.message_log.add_message(
                        f"Your {info['name']} increases to {current_level}!"
                    )
                else:
                    self.engine.message_log.add_message(
                        f"Your {info['name']} increases by {levels_gained} levels to {current_level}!"
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

    def get_trait_level(self, trait_type: 'TraitType') -> int:
        """Get the current level of a specific trait."""
        from trait_xp_system import TraitType
        
        if trait_type == TraitType.STRENGTH:
            return self.current_strength_level
        elif trait_type == TraitType.DEXTERITY:
            return self.current_dexterity_level
        elif trait_type == TraitType.CONSTITUTION:
            return self.current_constitution_level
        return 1

    def get_trait_xp(self, trait_type: 'TraitType') -> int:
        """Get the current XP of a specific trait."""
        from trait_xp_system import TraitType
        
        if trait_type == TraitType.STRENGTH:
            return self.current_strength_xp
        elif trait_type == TraitType.DEXTERITY:
            return self.current_dexterity_xp
        elif trait_type == TraitType.CONSTITUTION:
            return self.current_constitution_xp
        return 0
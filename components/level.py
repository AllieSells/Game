from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional

from components.base_component import BaseComponent

if TYPE_CHECKING:
    from entity import Actor

import sounds
from balance_config import ARCANA_MANA_PER_LEVEL, VIGOR_HP_PER_LEVEL, trait_delta

class Level(BaseComponent):
    parent: Actor

    # Add new traits here - just add the trait name to this list
    # IMPORTANT: Any trait you add here will automatically be available in:
    # - Character generation (origins/professions aptitudes/skills)
    # - Character sheets and UI displays
    # - Experience and leveling systems
    # No other code changes needed — the trait system is fully modular!
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
    
    # (Optional) Define trait categories - traits that serve as category headers
    # Only used by character sheet UI for organizing display. Traits not here will display standalone.
    # Format: 'category_trait': ['subcategory1', 'subcategory2', ...]
    TRAIT_CATEGORIES = {
        'strength': ['agility', 'vigor'],
        'armor': ['light armor', 'medium armor', 'heavy armor', 'shields'],
        'blades': ['daggers', 'swords'],
        'arcana': ['abjuration', 'conjuration', 'divination', 'enchantment', 'evocation', 'illusion', 'necromancy', 'transmutation']
    }
    
    # (Optional) Trait abbreviations for compact display in UI
    # Traits without an abbreviation here will just use their full name.
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
        # Baselines/anchors let us recompute derived resources from trait levels
        # in an idempotent way (plug-and-play resync from chargen, hooks, or load).
        self.base_max_hp: Optional[int] = None
        self.base_mana_max: Optional[int] = None
        self.mana_anchor_level: int = 1
        self.mana_anchor_max: Optional[int] = None

    def _get_trait_level(self, trait_name: str, fallback: int = 1) -> int:
        try:
            return int(self.traits.get(trait_name, {}).get('level', fallback) or fallback)
        except Exception:
            return fallback

    def _ensure_derived_baselines(self) -> None:
        if self.base_max_hp is None and hasattr(self.parent, 'fighter') and self.parent.fighter:
            self.base_max_hp = max(1, int(getattr(self.parent.fighter, 'max_hp', 1) or 1))

        if self.base_mana_max is None and hasattr(self.parent, 'mana_max'):
            self.base_mana_max = max(0, int(getattr(self.parent, 'mana_max', 0) or 0))

        if self.mana_anchor_max is None and hasattr(self.parent, 'mana_max'):
            self.mana_anchor_max = max(0, int(getattr(self.parent, 'mana_max', 0) or 0))
            self.mana_anchor_level = self._get_trait_level('arcana', 1)

    def set_mana_scaling_anchor(self, current_mana_max: int, arcana_level: int) -> None:
        """Anchor runtime mana growth to the current state.

        Useful after chargen, so in-run arcana gains can use a different per-level
        slope without re-applying earlier chargen scaling.
        """
        self.mana_anchor_max = max(0, int(current_mana_max or 0))
        self.mana_anchor_level = max(1, int(arcana_level or 1))

    def resync_derived_stats(
        self,
        *,
        hp_per_vigor_level: int = VIGOR_HP_PER_LEVEL,
        mana_per_arcana_level: int = ARCANA_MANA_PER_LEVEL,
        heal_on_hp_increase: bool = True,
        refill_mana_on_increase: bool = True,
    ) -> None:
        """Recompute HP/mana derived from current trait levels.

        This keeps stat updates deterministic when traits are set directly,
        such as during chargen, profession hooks, or save migration.
        """
        self._ensure_derived_baselines()

        # Vigor -> max HP
        if hasattr(self.parent, 'fighter') and self.parent.fighter and self.base_max_hp is not None:
            old_max_hp = int(getattr(self.parent.fighter, 'max_hp', 1) or 1)
            old_hp = int(getattr(self.parent.fighter, 'hp', old_max_hp) or old_max_hp)
            vigor_level = self._get_trait_level('vigor', 1)
            target_max_hp = max(1, int(self.base_max_hp + trait_delta(vigor_level) * int(hp_per_vigor_level)))

            self.parent.fighter.max_hp = target_max_hp
            if heal_on_hp_increase and target_max_hp > old_max_hp:
                hp_gain = target_max_hp - old_max_hp
                self.parent.fighter.hp = min(target_max_hp, old_hp + hp_gain)
            else:
                self.parent.fighter.hp = min(old_hp, target_max_hp)

            if hasattr(self.parent, 'body_parts') and self.parent.body_parts:
                self.parent.body_parts.set_max_health(target_max_hp)

        # Arcana -> max Mana (anchored to avoid re-scaling earlier curves)
        if hasattr(self.parent, 'mana_max') and self.mana_anchor_max is not None:
            old_max_mana = int(getattr(self.parent, 'mana_max', 0) or 0)
            old_mana = int(getattr(self.parent, 'mana', old_max_mana) or old_max_mana)
            arcana_level = self._get_trait_level('arcana', 1)
            target_mana_max = self.mana_anchor_max + max(0, arcana_level - self.mana_anchor_level) * int(mana_per_arcana_level)
            target_mana_max = max(0, int(target_mana_max))

            self.parent.mana_max = target_mana_max
            if refill_mana_on_increase and target_mana_max > old_max_mana:
                mana_gain = target_mana_max - old_max_mana
                self.parent.mana = min(target_mana_max, old_mana + mana_gain)
            else:
                self.parent.mana = min(old_mana, target_mana_max)

        # Spell school traits -> spell levels
        _SPELL_SCHOOLS = ('abjuration', 'conjuration', 'divination', 'enchantment',
                          'evocation', 'illusion', 'necromancy', 'transmutation')
        if hasattr(self.parent, 'known_spells'):
            for school in _SPELL_SCHOOLS:
                school_level = self._get_trait_level(school, 1)
                if school_level >= 2:
                    for spell in self.parent.known_spells:
                        if spell.school == school:
                            spell.level_up_spell(school_level, self.parent)

    def xp_to_next(self, trait: str) -> int:
        if trait in self.traits:
            current_level = self.traits[trait]['level']
            return self.level_up_base * (current_level ** 2)  # Quadratic
        return 0

    def total_xp(self, trait: str) -> int:
        if trait in self.traits:
            return self.traits[trait]['xp']
        return 0

    def add_xp_all(self, xp: int) -> None:
        """Add XP to all traits equally."""
        for trait_name in self.traits:
            self.add_xp({trait_name: xp})

    def add_xp(self, trait_awards: Dict[str, int], multiplier: float = 1.0) -> None:

        any_level_ups = False  # Track if any level ups occurred
        
        for trait_name, xp in trait_awards.items():

            if trait_name in self.traits:
                self.traits[trait_name]['xp'] += int(xp * multiplier)


                # Check if trait levels up
                while self.traits[trait_name]['xp'] >= self.xp_to_next(trait_name):
                    self.level_up(trait_name, play_sound=False)  # Don't play sound for individual level ups
                    any_level_ups = True
        
        # Play level up sound once if any traits leveled up
        if any_level_ups and getattr(self.parent, 'is_player', False):
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

        if trait_name in ['vigor', 'arcana']:
            self.resync_derived_stats()
        elif trait_name in ['abjuration', 'conjuration', 'divination', 'enchantment', 'evocation', 'illusion', 'necromancy', 'transmutation']:
            for spell in self.parent.known_spells:
                if spell.school == trait_name:
                    spell.level_up_spell(level_increased_to, self.parent)
        if self.parent.is_player:
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
        """Backward-compatible wrapper around trait-derived resync."""
        self.resync_derived_stats(hp_per_vigor_level=health_per_level)
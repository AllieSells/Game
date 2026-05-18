"""
Enemy spawning system with budget-based procedural generation.

This system uses four key mechanics:
1. ENCOUNTER BUDGET - Scales with floor depth, determines overall danger
2. ENEMY THREAT - How much budget each enemy costs (stronger = more expensive)
3. RANK CAPS - Maximum count of each enemy type to prevent spam
4. EMPTY ROOMS - Uses legacy spawn logic to keep ~33% rooms empty

How it works:
- Each room rolls for enemy count (0 to max_for_floor)
- Budget is allocated based on roll (prevents over-spawning)
- System fills budget by randomly selecting enemies based on threat cost
- Enemies cost threat points (rat=0.5, goblin=2.0, troll=5.0, ogre=7.0)
- Rank caps prevent spawning 20 goblins (e.g., max 4 goblins per encounter)
- All enemies can appear on any floor - budget naturally limits what's affordable

Biome support:
  "any"      – applies to every biome
  "dungeon"  – standard dungeon rooms
  "caverns"  – cave systems
  "lush"     – vegetated areas
  "ruins"    – ancient structures
  "tutorial" – tutorial floor
  
Enemies can be registered for multiple biomes: ["caverns", "ruins"]
"""
from __future__ import annotations

import copy
import json
import os
import random
from typing import Callable, List, NamedTuple, Optional

from entity import Actor
import entity_factories

_SPAWN_TABLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json", "spawn_tables.json")


# ---------------------------------------------------------------------------
# Internal entry types
# ---------------------------------------------------------------------------

class EnemyEntry(NamedTuple):
    factory: Callable        # callable that returns a fresh Actor
    biomes: List[str]        # list of biomes ("any", "dungeon", "caverns", etc.)
    threat: float            # budget cost (difficulty rating)
    rank_cap: int            # max of this type per encounter
    weight: int              # base selection weight
    scale_traits: List[str]  # traits to scale with floor depth


# ---------------------------------------------------------------------------
# Main spawner class
# ---------------------------------------------------------------------------

class EnemySpawner:
    """Budget-based enemy spawning with depth curves and encounter templates."""

    def __init__(self) -> None:
        self._enemy_entries: List[EnemyEntry] = []
        self._register_defaults()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        factory: Callable,
        threat: float,
        biomes: str | List[str] = "any",
        rank_cap: int = 3,
        weight: int = 100,
        scale_traits: List[str] = None,
    ) -> None:
        """Register an enemy factory."""
        # Normalize biomes to list
        if isinstance(biomes, str):
            biomes = [biomes]
        
        # Default traits to scale if none specified
        if scale_traits is None:
            scale_traits = ["strength", "agility", "vigor"]
        
        self._enemy_entries.append(
            EnemyEntry(
                factory=factory,
                biomes=biomes,
                threat=threat,
                rank_cap=rank_cap,
                weight=weight,
                scale_traits=scale_traits,
            )
        )

    def _register_defaults(self) -> None:
        """Load spawn table from JSON."""
        with open(_SPAWN_TABLE_PATH, "r") as f:
            enemy_data = json.load(f)
        for entry in enemy_data:
            factory_obj = getattr(entity_factories, entry["factory"])
            self.register(
                factory=lambda obj=factory_obj: copy.deepcopy(obj),
                biomes=entry["biome"],  # Can be string or list
                scale_traits=entry.get("scale_traits", ["strength", "agility", "vigor"]),
                threat=entry["threat"],
                rank_cap=entry["rank_cap"],
                weight=entry["weight"],
            )

    # ------------------------------------------------------------------
    # Budget calculation
    # ------------------------------------------------------------------

    def get_encounter_budget(self, floor: int) -> float:
        """
        Calculate threat budget for this floor.
        
        Budget increases with depth but includes variance for unpredictability.
        """
        base_budget = 2.0
        floor_scaling = floor * 0.8
        variance = random.uniform(-1.0, 1.5)
        
        return max(0.5, base_budget + floor_scaling + variance)

    # ------------------------------------------------------------------
    # Enemy selection with budget
    # ------------------------------------------------------------------

    def _get_available_enemies(self, floor: int, biome: str) -> List[tuple[EnemyEntry, float]]:
        """
        Get all available enemies for this biome.
        
        Returns: List of (entry, weight) tuples
        """
        available = []
        
        for entry in self._enemy_entries:
            # Check biome match
            if "any" not in entry.biomes and biome not in entry.biomes:
                continue
            
            available.append((entry, entry.weight))
        
        return available

    # ------------------------------------------------------------------
    # Spawning with budget and rank caps
    # ------------------------------------------------------------------

    def spawn_enemies(
        self,
        floor: int,
        biome: str = "any",
        budget: Optional[float] = None,
    ) -> List[Actor]:
        """
        Spawn enemies using budget system with spawn chance.
        
        Fills budget with individual enemies based on threat/depth weights.
        Uses old spawn logic to determine if room should have enemies.
        """
        # Check if this room should spawn enemies (old logic)
        max_enemies = self.get_max_enemies_for_floor(floor)
        enemy_count_roll = random.randint(0, max_enemies)
        
        if enemy_count_roll == 0:
            return []  # Empty room
        
        if budget is None:
            budget = self.get_encounter_budget(floor)
        
        # Cap budget based on rolled count to prevent over-spawning
        # If roll says "2 enemies", don't spawn 5
        budget = min(budget, enemy_count_roll * 2.5)  # ~2.5 threat per expected enemy
        
        # Spawn individual enemies with budget
        enemies = self._spawn_with_budget(floor, biome, budget)
        
        # Debug output
        if enemies:
            from collections import Counter
            enemy_counts = Counter(e.name for e in enemies)
            count_strs = [f"{name} x{count}" for name, count in enemy_counts.items()]
            print(f"[GEN] Floor {floor}: Enemies spawned - {', '.join(count_strs)} (Budget: {budget:.1f})")
        #print(f"[GEN] Floor {floor}: Total enemies spawned - {len(enemies)} (Budget: {budget:.1f})")
        return enemies

    def _spawn_with_budget(
        self,
        floor: int,
        biome: str,
        budget: float,
    ) -> List[Actor]:
        """
        Fill budget by selecting enemies with rank caps.
        """
        available = self._get_available_enemies(floor, biome)
        if not available:
            return []
        
        spawned = []
        rank_counts = {}  # Track count of each enemy type
        remaining_budget = budget
        
        # Keep spawning until budget exhausted
        max_attempts = 50  # Prevent infinite loops
        attempt = 0
        
        while remaining_budget > 0.4 and attempt < max_attempts:
            attempt += 1
            
            # Filter by available budget and rank caps
            affordable = []
            for entry, weight in available:
                if entry.threat <= remaining_budget:
                    current_count = rank_counts.get(entry.factory, 0)
                    if current_count < entry.rank_cap:
                        # Prefer expensive enemies: multiply weight by threat
                        # This makes ogres (7.0) 14x more likely than rats (0.5)
                        threat_preference = weight * (entry.threat ** 1.5)
                        affordable.append((entry, threat_preference))
            
            if not affordable:
                break
            
            # Weighted random selection
            entries, weights = zip(*affordable)
            chosen_entry = random.choices(entries, weights=weights, k=1)[0]
            
            # Spawn enemy and scale with floor depth
            enemy = chosen_entry.factory()
            self._scale_enemy_to_floor(enemy, floor, chosen_entry.scale_traits)
            spawned.append(enemy)
            
            # Update tracking
            remaining_budget -= chosen_entry.threat
            rank_counts[chosen_entry.factory] = rank_counts.get(chosen_entry.factory, 0) + 1
        
        return spawned
    
    def _scale_enemy_to_floor(self, enemy: Actor, floor: int, scale_traits: List[str]) -> None:
        """Scale enemy traits based on floor depth with semi-random variance.
        
        Progression:
        - Floor 1: Base traits (level 1)
        - Floor 5: +1 trait level (±1 random)
        - Floor 10: +2 trait levels (±1 random)
        - Floor 15: +3 trait levels (±1 random)
        
        Each trait gets its own random variance for more variety.
        Only scales traits specified in scale_traits list from spawn table.
        Updates derived stats (HP, damage, etc.) based on trait changes.
        """
        if floor <= 1:
            return  # No scaling on floor 1
        
        level_comp = getattr(enemy, 'level', None)
        if not level_comp or not hasattr(level_comp, 'traits'):
            return
        
        # Calculate base trait bonus: +1 every 5 floors
        base_bonus = max(0, (floor - 1) // 5)
        
        if base_bonus == 0 and floor <= 3:
            return  # No scaling on early floors
        
        # Scale only the traits specified for this enemy type
        for trait_name in scale_traits:
            if trait_name not in level_comp.traits:
                continue
            
            # Each trait gets its own random variance
            # Variance increases with depth: ±0 on floor 1-4, ±1 on floor 5+, ±2 on floor 15+
            max_variance = min(2, base_bonus)
            trait_bonus = base_bonus + random.randint(-max_variance, max_variance)
            trait_bonus = max(0, trait_bonus)  # Never go negative
            
            if trait_bonus > 0:
                # Access the traits dictionary properly
                if isinstance(level_comp.traits[trait_name], dict):
                    level_comp.traits[trait_name]['level'] = level_comp.traits[trait_name].get('level', 1) + trait_bonus
                else:
                    # Fallback if structure is different
                    level_comp.traits[trait_name] = {'level': 1 + trait_bonus, 'xp': 0}
        
        # CRITICAL: Resync derived stats (HP, mana, damage bonuses, etc.)
        # This applies the trait level increases to actual combat stats
        level_comp.resync_derived_stats(
            heal_on_hp_increase=True,      # Heal to new max HP
            refill_mana_on_increase=True   # Refill mana to new max
        )

    def get_max_enemies_for_floor(self, floor: int) -> int:
        """Max enemies per room (used by some procgen code)."""
        return min(2 + floor // 5, 8)

    def get_enemy_count_for_floor(self, floor: int) -> int:
        """Random enemy count (legacy compatibility)."""
        # Budget system handles this now, but keep for compatibility
        return random.randint(0, self.get_max_enemies_for_floor(floor))


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

enemy_spawner = EnemySpawner()


# ---------------------------------------------------------------------------
# Public API (used by procgen and mods)
# ---------------------------------------------------------------------------

def add_enemy(
    factory: Callable,
    threat: float,
    biomes: str | List[str] = "any",
    rank_cap: int = 3,
    weight: int = 100,
) -> None:
    """Register an enemy with the global spawner."""
    enemy_spawner.register(
        factory=factory,
        threat=threat,
        biomes=biomes,
        rank_cap=rank_cap,
        weight=weight,
    )


# Legacy compatibility wrappers
def add_enemy_to_floor(floor: int, factory: Callable, weight: int) -> None:
    """Backward-compatible wrapper."""
    # Estimate threat based on weight (rough conversion)
    threat = weight / 20.0
    enemy_spawner.register(
        factory=factory,
        threat=threat,
        biomes="any",
        rank_cap=3,
        weight=weight,
    )


def get_enemies_for_floor(
    floor: int,
    count: int = 0,  # Ignored in budget system
    biome: str = "any",
    budget: Optional[float] = None,
) -> List[Actor]:
    """
    Spawn enemies for the given floor and biome.
    
    Note: 'count' parameter is ignored - budget system determines enemy count.
    """
    return enemy_spawner.spawn_enemies(floor, biome, budget)


def get_enemy_count_for_floor(floor: int) -> int:
    """Random enemy count for the given floor (legacy compatibility)."""
    return enemy_spawner.get_enemy_count_for_floor(floor)
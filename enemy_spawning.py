"""
Enemy spawning system with biome and depth support.

Spawn tables are keyed by (biome, min_floor) pairs. When spawning enemies,
the system collects all entries whose biome matches (or is "any") and whose
min_floor is <= the current floor, then merges their weights.

Biome names match GameMap.biome values:
  "any"      – applies to every biome (used for generic enemies)
  "dungeon"  – standard dungeon rooms / mixed
  "caverns"  – erosion-driven cave maps (biome_str "Caverns")
  "lush"     – vegetation > 4  (biome_str prefix "Lush …")
  "tutorial" – tutorial floor
  (add more as new biomes are introduced)

Usage:
    # Register an enemy for all biomes starting floor 0
    enemy_spawner.register(biome="any", min_floor=0,
                            factory=lambda: copy.deepcopy(entity_factories.goblin),
                            weight=70)

    # Register an enemy that only spawns in caves from floor 3 onward
    enemy_spawner.register(biome="caverns", min_floor=3,
                            factory=lambda: copy.deepcopy(entity_factories.troll),
                            weight=40)

    # Convenience wrapper used by mods
    add_enemy(biome="any", min_floor=5, factory=my_factory, weight=25)
"""
from __future__ import annotations

import copy
import json
import os
import random
from typing import Callable, Dict, List, NamedTuple

from entity import Actor
import entity_factories

_SPAWN_TABLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json", "spawn_tables.json")


# ---------------------------------------------------------------------------
# Internal entry type
# ---------------------------------------------------------------------------

class SpawnEntry(NamedTuple):
    biome: str           # "any" or a specific biome string
    min_floor: int       # first floor this entry can appear on
    max_floor: int       # last floor this entry can appear on (-1 = no limit)
    factory: Callable    # callable that returns a fresh Actor
    weight: int          # relative spawn weight


# ---------------------------------------------------------------------------
# Main spawner class
# ---------------------------------------------------------------------------

class EnemySpawner:
    """Biome-and-depth-aware enemy spawning manager."""

    def __init__(self) -> None:
        self._entries: List[SpawnEntry] = []
        self._register_defaults()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        factory: Callable,
        weight: int,
        biome: str = "any",
        min_floor: int = 0,
        max_floor: int = -1,
    ) -> None:
        """Register an enemy factory for a particular biome/depth."""
        self._entries.append(SpawnEntry(biome=biome, min_floor=min_floor,
                                        max_floor=max_floor,
                                        factory=factory, weight=weight))

    def _register_defaults(self) -> None:
        """Load built-in spawn table from json/spawn_tables.json."""
        with open(_SPAWN_TABLE_PATH, "r") as f:
            entries = json.load(f)
        for entry in entries:
            factory_obj = getattr(entity_factories, entry["factory"])
            self.register(
                biome=entry["biome"],
                min_floor=entry["min_floor"],
                max_floor=entry.get("max_floor", -1),
                factory=lambda obj=factory_obj: copy.deepcopy(obj),
                weight=entry["weight"],
            )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_weights(self, floor: int, biome: str = "any") -> Dict[Callable, int]:
        """
        Return a merged {factory: weight} dict for the given floor and biome.

        Rules (applied in order, later entries overwrite earlier ones):
          1. All "any" entries with min_floor <= floor
          2. All biome-specific entries with min_floor <= floor
        """
        combined: Dict[Callable, int] = {}

        def _floor_matches(entry: SpawnEntry) -> bool:
            return entry.min_floor <= floor and (entry.max_floor == -1 or floor <= entry.max_floor)

        # Pass 1 – generic entries
        for entry in self._entries:
            if entry.biome == "any" and _floor_matches(entry):
                combined[entry.factory] = entry.weight

        # Pass 2 – biome-specific entries (merged on top)
        if biome and biome != "any":
            for entry in self._entries:
                if entry.biome == biome and _floor_matches(entry):
                    combined[entry.factory] = entry.weight

        return combined

    # ------------------------------------------------------------------
    # Spawning
    # ------------------------------------------------------------------

    def spawn_enemies(
        self,
        floor: int,
        count: int,
        biome: str = "any",
    ) -> List[Actor]:
        """Return a list of freshly-created Actor instances."""
        if count <= 0:
            return []

        weights_dict = self.get_weights(floor, biome)
        if not weights_dict:
            return []

        factories = list(weights_dict.keys())
        weights = list(weights_dict.values())

        if sum(weights) == 0:
            return []

        chosen = random.choices(factories, weights=weights, k=count)
        return [f() for f in chosen]

    def get_max_enemies_for_floor(self, floor: int) -> int:
        """Max enemies per room/section, scaling with depth."""
        return min(2 + floor // 5, 8)

    def get_enemy_count_for_floor(self, floor: int) -> int:
        """Random enemy count for a room/section."""
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
    weight: int,
    biome: str = "any",
    min_floor: int = 0,
    max_floor: int = -1,
) -> None:
    """Register an enemy with the global spawner."""
    enemy_spawner.register(factory=factory, weight=weight,
                           biome=biome, min_floor=min_floor, max_floor=max_floor)


# Legacy alias kept for mods that use add_enemy_to_floor(floor, factory, weight)
def add_enemy_to_floor(floor: int, factory: Callable, weight: int) -> None:
    """Backward-compatible wrapper – registers for all biomes."""
    enemy_spawner.register(factory=factory, weight=weight,
                           biome="any", min_floor=floor)


def get_enemies_for_floor(
    floor: int,
    count: int,
    biome: str = "any",
) -> List[Actor]:
    """Spawn *count* enemies for *floor* in *biome*."""
    return enemy_spawner.spawn_enemies(floor, count, biome)


def get_enemy_count_for_floor(floor: int) -> int:
    """Random enemy count for the given floor."""
    return enemy_spawner.get_enemy_count_for_floor(floor)
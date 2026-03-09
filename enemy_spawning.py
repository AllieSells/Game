"""
Simple, modular enemy spawning system.
Clean version of the standard procgen approach with easy extensibility.
"""
from __future__ import annotations
from typing import List, Dict
import random
import copy
from entity import Actor
import entity_factories


class SimpleEnemySpawner:
    """Simple enemy spawning manager with easy extensibility."""
    
    def __init__(self):
        # Enemy spawn chances by floor (floor: {entity_factory: weight})
        self.enemy_spawn_table: Dict[int, Dict[callable, int]] = {
            0: {
                lambda: copy.deepcopy(entity_factories.goblin): 80,
                lambda: copy.deepcopy(entity_factories.spider): 20,
            },
            3: {
                lambda: copy.deepcopy(entity_factories.troll): 15,
            },
            5: {
                lambda: copy.deepcopy(entity_factories.troll): 30,
            },
            7: {
                lambda: copy.deepcopy(entity_factories.troll): 60,
            },
        }
    
    def add_enemy(self, floor: int, factory: callable, weight: int):
        """Add an enemy to spawn at a specific floor with given weight."""
        if floor not in self.enemy_spawn_table:
            self.enemy_spawn_table[floor] = {}
        self.enemy_spawn_table[floor][factory] = weight
    
    def get_enemy_weights_for_floor(self, floor: int) -> Dict[callable, int]:
        """Get all enemy spawn weights available at the given floor."""
        combined_weights = {}
        
        # Combine all spawn tables from floor 0 up to current floor
        for spawn_floor in sorted(self.enemy_spawn_table.keys()):
            if spawn_floor <= floor:
                for factory, weight in self.enemy_spawn_table[spawn_floor].items():
                    combined_weights[factory] = weight
        
        return combined_weights
    
    def spawn_enemies(self, floor: int, count: int) -> List[Actor]:
        """Spawn a number of enemies for the given floor."""
        if count <= 0:
            return []
        
        weights_dict = self.get_enemy_weights_for_floor(floor)
        if not weights_dict:
            return []
        
        # Convert to lists for random.choices
        factories = list(weights_dict.keys())
        weights = list(weights_dict.values())
        
        if sum(weights) == 0:
            return []
        
        # Choose enemy factories
        chosen_factories = random.choices(factories, weights=weights, k=count)
        
        # Create enemies
        return [factory() for factory in chosen_factories]
    
    def get_max_enemies_for_floor(self, floor: int) -> int:
        """Get max enemies per room for floor."""
        base_max = 2
        additional = floor // 5  # +1 every 5 floors
        return min(base_max + additional, 8)  # Cap at 8
    
    def get_enemy_count_for_floor(self, floor: int) -> int:
        """Get random enemy count for floor."""
        max_enemies = self.get_max_enemies_for_floor(floor)
        return random.randint(0, max_enemies)


# Global spawner instance
enemy_spawner = SimpleEnemySpawner()


# Convenience functions
def add_enemy_to_floor(floor: int, factory: callable, weight: int):
    """Add an enemy to spawn starting at a specific floor."""
    enemy_spawner.add_enemy(floor, factory, weight)


def get_enemies_for_floor(floor: int, count: int) -> List[Actor]:
    """Get enemies for floor (backward compatibility)."""
    return enemy_spawner.spawn_enemies(floor, count)


def get_enemy_count_for_floor(floor: int) -> int:
    """Get random enemy count for floor (backward compatibility)."""
    return enemy_spawner.get_enemy_count_for_floor(floor)
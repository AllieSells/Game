# Simple Modular Enemy Spawning

## Overview
A clean, simplified approach to enemy spawning that's easy to extend while staying close to the original procgen system.

## Key Features
- ✅ **Simple Floor-Based Spawning** - Enemies unlock at specific floors
- ✅ **Easy Addition** - Add enemies with one function call  
- ✅ **Infinite Floors** - Works at any depth with automatic scaling
- ✅ **Lightweight** - No complex systems, just clean spawning logic
- ✅ **Backward Compatible** - Existing code continues to work

## How It Works

### Basic Concept
1. **Floor Tables**: Each floor can have enemies with spawn weights
2. **Cumulative**: All previous floors' enemies remain available
3. **Weighted Selection**: Higher weight = more likely to spawn
4. **Automatic Scaling**: More enemies per room as you go deeper

### Adding New Enemies

#### Super Simple Method:
```python
from enemy_spawning import add_enemy_to_floor

def create_my_enemy():
    return Actor(char="X", name="My Enemy", ...)

# Add to floor 10 with weight 50
add_enemy_to_floor(10, lambda: copy.deepcopy(create_my_enemy()), 50)
```

#### Multiple Floors:
```python
# Start rare, become common
add_enemy_to_floor(5, lambda: copy.deepcopy(create_orc()), 10)   # Rare at floor 5
add_enemy_to_floor(10, lambda: copy.deepcopy(create_orc()), 40)  # Common at floor 10+
```

## Example Usage

See [example_enemy_mod.py](example_enemy_mod.py) for complete examples including:
- Orc (starts floor 5)
- Skeleton (starts floor 4)  
- Dragon Wyrmling (starts floor 15, rare)

## Files

- **enemy_spawning.py**: Core system with SimpleEnemySpawner
- **procgen.py**: Uses the new system and contains spawn data
- **example_enemy_mod.py**: Shows how to add enemies

## Configuration

Enemy count scaling is built in:
- Base: 2 enemies per room max
- +1 max enemy every 5 floors
- Cap: 8 enemies per room max

Modify in `SimpleEnemySpawner.get_max_enemies_for_floor()` if needed.

## Migration from Complex System

Old complex approach → New simple approach:
```python
# Before (complex)
enemy_spawner.register_enemy(
    factory=create_orc, 
    tier=EnemyTier.COMMON,
    unlock_floor=5,
    spawn_weight=SpawnWeight(base_weight=25, floor_scaling=2),
    hp_scaling=1.2, power_scaling=1.1  # etc...
)

# After (simple)
add_enemy_to_floor(5, lambda: copy.deepcopy(create_orc()), 25)
```

Much cleaner while keeping all the important functionality!

## Benefits

1. **Dead Simple**: One function call to add enemies
2. **No Overwrites**: Just adds to existing enemy pools 
3. **Infinite Ready**: Works at floor 1000+ automatically
4. **Performance**: Lightweight with no complex calculations
5. **Familiar**: Works like the original system but cleaner
6. **Extensible**: Easy to modify or expand later

Perfect balance of simplicity and functionality.
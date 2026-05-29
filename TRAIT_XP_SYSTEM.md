# Trait XP System Documentation

## Overview

The Trait XP System is a modular character progression feature that grants experience points to specific character traits (Strength, Dexterity, Constitution) based on the actions players perform. This creates a natural, use-based progression system where traits improve through practice.

## How It Works

### Core Components

1. **TraitXPManager** (`trait_xp_system.py`): Central manager for calculating and distributing trait XP
2. **Level Component** (`components/level.py`): Extended to handle individual trait progression
3. **Action Hooks**: Various actions now grant appropriate trait XP when performed

### Trait Progression

**Strength** - Improved by:
- Melee combat (2 XP primary)
- Heavy lifting/picking up items (3 XP)
- Blocking attacks (1 XP)
- Ranged combat (1 XP secondary - drawing bows)

**Dexterity** - Improved by:
- Ranged combat (2 XP primary) 
- Dodging attacks (2 XP)
- Movement (1 XP)
- Stealth actions (2 XP)

**Constitution** - Improved by:
- Taking damage (2 XP, scaled by damage amount)
- Healing (1 XP)
- Endurance activities like waiting (2 XP)
- Melee combat (1 XP secondary)
- Movement (1 XP)

### Trait Benefits

**Strength Levels**:
- +1 Base Power per level
- Affects melee damage output
- Carried weight capacity (future feature)

**Dexterity Levels**:
- Currently tracked for future features
- Could affect hit chance, dodge chance, ranged accuracy

**Constitution Levels**: 
- +5 Max HP per level
- +5 Current HP (healing) per level
- Updates body part HP proportionally
- Affects damage resistance (future feature)

## Usage Examples

### Current Implementation
The system is automatically active. Players gain trait XP by:

```python
# Melee combat grants Strength (2 XP) + Constitution (1 XP)
melee_action = MeleeAction(player, dx=1, dy=0)
melee_action.perform()

# Ranged combat grants Dexterity (2 XP) + Strength (1 XP)  
ranged_action = RangedAction(player, dx=1, dy=0)
ranged_action.perform()

# Movement grants Dexterity (1 XP) + Constitution (1 XP)
movement_action = MovementAction(player, dx=1, dy=0) 
movement_action.perform()

# Taking damage grants Constitution XP (scaled by damage)
player.fighter.take_damage(10)  # Grants ~2-4 Constitution XP
```

### Manual XP Granting
```python
import trait_xp_system
from trait_xp_system import TraitType

# Grant specific trait XP directly
player.level.add_trait_xp(TraitType.STRENGTH, 5)
player.level.add_trait_xp(TraitType.DEXTERITY, 3)
player.level.add_trait_xp(TraitType.CONSTITUTION, 2)

# Use convenience functions
trait_xp_system.grant_dodge_xp(player)  # Dexterity XP
trait_xp_system.grant_block_xp(player)  # Strength + Constitution XP
trait_xp_system.grant_damage_taken_xp(player, 15)  # Constitution XP (scaled)
```

## Extending the System

### Adding New Traits

1. **Add to TraitType enum**:
```python
class TraitType(Enum):
    STRENGTH = "strength"
    DEXTERITY = "dexterity" 
    CONSTITUTION = "constitution"
    INTELLIGENCE = "intelligence"  # New trait
    CHARISMA = "charisma"         # New trait
```

2. **Update Level component** (`components/level.py`):
```python
def __init__(self, ...):
    # Add new trait attributes
    self.current_intelligence_level = 1
    self.current_intelligence_xp = 0
    self.intelligence_level_up_base = 0
    self.intelligence_level_up_factor = 150
    # ... repeat for charisma

def _level_up_intelligence(self):
    """Handle intelligence level up benefits."""
    # Add intelligence-specific benefits
    # e.g., spell power, mana, learning speed
    pass
```

3. **Update trait_info dictionary** in `add_trait_xp()` method.

### Adding New Action Categories

1. **Add to ActionCategory enum**:
```python
class ActionCategory(Enum):
    # Existing categories...
    SPELLCASTING = "spellcasting"
    SOCIAL_INTERACTION = "social_interaction"
    CRAFTING = "crafting"
```

2. **Update ACTION_TRAIT_MAPPING**:
```python
ACTION_TRAIT_MAPPING = {
    # Existing mappings...
    ActionCategory.SPELLCASTING: [
        (TraitType.INTELLIGENCE, 2),
        (TraitType.CONSTITUTION, 1)  # Mental stamina
    ],
    ActionCategory.SOCIAL_INTERACTION: [
        (TraitType.CHARISMA, 2)
    ],
    ActionCategory.CRAFTING: [
        (TraitType.INTELLIGENCE, 1),
        (TraitType.DEXTERITY, 1)
    ]
}
```

3. **Update categorize_action() function**:
```python
def categorize_action(action: Action) -> ActionCategory | None:
    action_name = action.__class__.__name__
    
    action_mapping = {
        # Existing mappings...
        'CastSpellAction': ActionCategory.SPELLCASTING,
        'DialogueAction': ActionCategory.SOCIAL_INTERACTION,
        'CraftItemAction': ActionCategory.CRAFTING
    }
    
    return action_mapping.get(action_name)
```

### Adding New Actions

1. **Create action class**:
```python
class CraftItemAction(Action):
    def perform(self) -> None:
        # Crafting logic...
        
        # Grant trait XP at the end
        trait_xp_system.grant_action_xp(self.entity, self)
```

2. **No other changes needed** - the system will automatically map it if added to `categorize_action()`.

### Customizing XP Amounts

**Temporary modifiers**:
```python
# Add a temporary XP boost
boost_modifier = TraitXPModifier("training_boost", multiplier=2.0, bonus=1)
trait_xp_manager.add_modifier(boost_modifier)

# Perform actions (double XP + 1 bonus)
player.perform_action()

# Remove modifier
trait_xp_manager.remove_modifier("training_boost")
```

**Permanent changes**: Edit the base XP values in `ACTION_TRAIT_MAPPING`.

## Configuration

### XP Scaling
- Base XP per action is defined in `ACTION_TRAIT_MAPPING`
- Each trait has individual level up requirements (base + level * factor)
- Default factor is 150 XP per level
- Random variance of ±25% makes progression feel natural

### Message Frequency
- Trait XP gain messages show only 10% of the time to reduce spam
- Level up messages always show with sound effect
- Damage XP messages are handled separately

### Level Up Requirements
```python
# Default progression (can be customized per character)
xp_needed = level_up_base + current_level * level_up_factor
# Example: Level 2 = 0 + 1 * 150 = 150 XP
# Example: Level 3 = 0 + 2 * 150 = 300 XP  
```

## Integration Points

The system integrates at these key points:
- **Actions**: Melee, Ranged, Movement, Pickup actions grant XP
- **Combat**: Taking damage grants Constitution XP  
- **Equipment**: Fighter component updated when traits level up
- **UI**: Level component provides trait info for display
- **Body Parts**: Constitution affects body part HP scaling

This modular design makes it easy to add new traits, actions, and progression mechanics without disrupting existing gameplay.
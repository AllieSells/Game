# Game Turn System Documentation

## Overview
This game follows a classic turn-based roguelike pattern where:
1. Player performs an action
2. Game processes all turn-end effects
3. All enemies take their turns
4. Game state is updated (FOV, effects, etc.)

## Key Files for Turn Management

### 🎯 `turn_manager.py` - **MAIN TURN LOGIC**
**This is where you want to look for post-player-action code!**

- `process_player_turn_end()` - Main entry point for all post-action processing
- Contains all the centralized logic that runs after a player action

### `input_handlers.py`
- `EventHandler.handle_action()` - Triggers the turn manager after validating player actions
- `MainGameEventHandler.ev_keydown()` - Converts keypresses into actions

### `engine.py`
- `Engine.handle_enemy_turns()` - Legacy method, now redirects to turn manager
- `Engine.tick()` - Handles real-time animations and effects (separate from turn-based logic)
- `Engine.update_fov()` - Updates field of view and lighting effects

### `main.py`
- Contains the main game loop that processes events and renders

## Turn Flow

```
Player Input (input_handlers.py)
    ↓
Action Created (actions.py)
    ↓
Action Performed (action.perform())
    ↓
🎯 Turn Manager Called (turn_manager.py)
    ├── Equipment Durability (torches, etc.)
    ├── Enemy Turns (AI actions)
    ├── FOV Update (lighting, vision)
    ├── Status Effects (darkness, lucidity)
    └── Game State Checks (death, level up)
    ↓
Return to Main Game Loop
```

## Adding New Turn-Based Features

To add something that happens after every player action:

1. **Open `turn_manager.py`**
2. **Add your logic to `process_player_turn_end()`** or create a new helper method
3. **Call your helper method from `process_player_turn_end()`**

Example:
```python
def process_player_turn_end(self) -> BaseEventHandler | None:
    # ... existing code ...
    
    # 6. Your new feature
    self._handle_my_new_feature()
    
    return None

def _handle_my_new_feature(self) -> None:
    """Add description of what this does."""
    # Your code here
```

## Real-time vs Turn-based

- **Turn-based**: Player action → all systems update → enemy actions
  - Managed by `turn_manager.py`
  - Combat, movement, item use, etc.

- **Real-time**: Continuous updates independent of player actions  
  - Managed by `engine.tick()` 
  - Animations, visual effects, passive environment effects
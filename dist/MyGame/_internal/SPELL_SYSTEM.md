# Simplified Spell System

## How to Add New Spells

The spell system has been simplified to make adding new spells much easier. You only need to:

### 1. Create the Spell Class
Create your new spell class in `components/spells.py`:

```python
class FireballSpell(Spell):
    def __init__(self):
        super().__init__(
            name="Fireball",
            description="Launch a fiery projectile at your enemies.",
            damage=15,
            duration=0,
            mana_cost=15,
            components=['V', 'S'],
            spell_tags=["fire", "projectile"]
        )

    def activate(self, action: actions.SpellAction) -> None:
        # Your spell logic here
        action.engine.message_log.add_message(
            f"You cast Fireball!", 
            color.orange
        )
```

### 2. Register the Spell
Add your spell to the `SPELL_REGISTRY` in `input_handlers.py`:

```python
cls.SPELL_REGISTRY = {
    "Darkvision": DarkvisionSpell,
    "Teleport": TeleportSpell,
    "Fireball": FireballSpell,  # <-- Add this line
    # Add new spells here: "SpellName": SpellClass,
}
```

### 3. Import the Spell Class
Add the import in the `_initialize_spell_registry` method:

```python
from components.spells import DarkvisionSpell, TeleportSpell, FireballSpell
```

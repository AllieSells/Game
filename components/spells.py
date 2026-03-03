import actions
import color
from components import effect
import sounds
import animations
from input_handlers import (
    ActionOrHandler,
    AreaRangedAttackHandler, 
    SingleRangedAttackHandler,
)


class Spell():
    def __init__(self, name, duration, description, damage, mana_cost, components, spell_tags):
        self.name = name
        self.duration = duration
        self.description = description
        self.damage = damage
        self.mana_cost = mana_cost
        self.components = components
        self.spell_tags = spell_tags

    def activate(self, action: actions.SpellAction) -> None:
        pass
    
    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler if this spell requires targeting, None otherwise."""
        return None


class DarkvisionSpell(Spell):
    def __init__(self):
        duration = 300  # Define duration before using it
        super().__init__(
            name="Darkvision",
            description=f"Grants the ability to see in the dark for {duration} turns.",
            damage=0,
            duration=duration,
            mana_cost=10,
            components=['S', 'V'],
            spell_tags=["darkvision"]
        )

    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        
        # Consume mana for successful darkvision cast
        consumer.mana -= self.mana_cost
        
        darkvision = effect.DarkvisionEffect(duration=self.duration)
        sounds.play_darkvision_sound()
        action.engine.message_log.add_message(
            f"Your vision sharpens as darkness recedes!", color.dark_purple
        )
        consumer.add_effect(darkvision)

class TeleportSpell(Spell):
    def __init__(self):
        super().__init__(
            name="Teleport",
            description="Instantly move to a visible location within range.",
            damage=0,
            duration=0,
            mana_cost=10,
            components=['V'],
            spell_tags=["teleport"]
        )
    
    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler for selecting teleport destination."""
        def teleport_callback(target_xy):
            """Callback function for teleport targeting."""
            return actions.SpellAction(caster, self, target_xy)
        
        return SingleRangedAttackHandler(
            engine,
            callback=teleport_callback
        )

    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        target_x, target_y = action.target_xy
        
        # Check if target location is valid
        if not action.engine.game_map.in_bounds(target_x, target_y):
            action.engine.message_log.add_message(
                f"You can't teleport there - it's out of bounds!", color.impossible
            )
            return
        
        # Check if location is visible
        if not action.engine.game_map.visible[target_x, target_y]:
            action.engine.message_log.add_message(
                f"You can't teleport to a location you can't see!", color.impossible
            )
            return
        
        # Check if location is walkable
        if not action.engine.game_map.tiles[target_x, target_y]['walkable']:
            action.engine.message_log.add_message(
                f"You can't teleport into a solid object!", color.impossible
            )
            return
        
        # Check if location is blocked by an entity
        blocking_entity = action.engine.game_map.get_blocking_entity_at_location(target_x, target_y)
        if blocking_entity:
            action.engine.message_log.add_message(
                f"You can't teleport into {blocking_entity.name}!", color.impossible
            )
            return
        
        # All checks passed - consume mana and teleport!
        consumer.mana -= self.mana_cost
        
        action.engine.animation_queue.append(animations.TeleportAnimation((consumer.x, consumer.y)))
        action.engine.animation_queue.append(animations.TeleportAnimation((target_x, target_y)))
        
        consumer.x = target_x
        consumer.y = target_y
        
        sounds.play_teleport_sound()
        action.engine.message_log.add_message(
            f"Space distorts around you!", color.ascend
        )

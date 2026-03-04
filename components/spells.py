import actions
import color
from components import effect
from exceptions import Impossible
from liquid_system import LiquidType
import sounds
import animations
from input_handlers import (
    ActionOrHandler,
    AreaRangedAttackHandler, 
    SingleRangedAttackHandler,
)


class Spell():
    def __init__(self, name, duration, description, damage, mana_cost, components, spell_tags, school, arcana_level = 1, cast_xp = 5):
        self.name = name
        self.duration = duration
        self.description = description
        self.damage = damage
        self.mana_cost = mana_cost
        self.components = components
        self.spell_tags = spell_tags
        self.school = school
        self.arcana_level = arcana_level
        self.cast_xp = cast_xp


    def activate(self, action: actions.SpellAction) -> None:
        pass
    
    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler if this spell requires targeting, None otherwise."""
        return None

    def level_up_spell(self, level: int) -> None:
        if level == 2:
            self.damage = int(self.damage * 1.5)
            self.mana_cost += 1
            self.name += " II"


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
            spell_tags=["darkvision"],
            school="transmutation",
            arcana_level = 2,
            cast_xp=5
        )

    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        
        # Consume mana for successful darkvision cast
        consumer.mana -= self.mana_cost
        consumer.level.add_xp({self.school: self.cast_xp})
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
            spell_tags=["teleport"],
            school="conjuration",
            arcana_level = 3,
            cast_xp = 10

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
        consumer.level.add_xp({self.school: self.cast_xp})
        action.engine.animation_queue.append(animations.TeleportAnimation((consumer.x, consumer.y)))
        action.engine.animation_queue.append(animations.TeleportAnimation((target_x, target_y)))
        
        consumer.x = target_x
        consumer.y = target_y
        
        sounds.play_teleport_sound()
        action.engine.message_log.add_message(
            f"Space distorts around you!", color.ascend
        )

class PoisonSpraySpell(Spell):
    def __init__(self):
        super().__init__(
            name="Poison Spray",
            description="Hurl a glob of acid that damages a single target.",
            damage=5,
            duration=0,
            mana_cost=5,
            components=['V', 'S'],
            spell_tags=["poison", "ranged"],
            school="conjuration",
            arcana_level = 2,
            cast_xp = 5,
        )

    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler for selecting poison spray target."""
        def poison_spray_callback(target_xy):
            """Callback function for poison spray targeting."""
            return actions.SpellAction(caster, self, target_xy)
        
        return SingleRangedAttackHandler(
            engine,
            callback=poison_spray_callback
        )

    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        target_x, target_y = action.target_xy
        target = action.engine.game_map.get_blocking_entity_at_location(target_x, target_y)

        if not target or not target.fighter:
            consumer.mana -= self.mana_cost
            consumer.level.add_xp({self.school: self.cast_xp})
            action.engine.animation_queue.append(animations.SplashAnimation((target_x, target_y), color.green))
            action.engine.game_map.liquid_system.create_splash(target_x, target_y, LiquidType.POISON, radius=1, max_depth=2)
            action.engine.message_log.add_message(
                f"The poison sizzles as it hits the ground.", color.green
            )
            sounds.play_poison_burn_sound()
            return
        if target and target.fighter:
            target.fighter.take_damage(self.damage, causes_bleeding=False)
            consumer.mana -= self.mana_cost
            consumer.level.add_xp({self.school: self.cast_xp})
            action.engine.game_map.liquid_system._coat_entities_in_splash(target_x, target_y, LiquidType.POISON, distance=1.0, radius=1)
            action.engine.animation_queue.append(animations.SplashAnimation((target_x, target_y), color.green))
            action.engine.message_log.add_message(
                f"The poison hits the {target.name}!", color.green
            )
            sounds.play_poison_burn_sound()
            return

class FireballSpell(Spell):
    def __init__(self):
        super().__init__(
            name="Fireball",
            description="Launch a fiery explosion that damages all in the area.",
            damage=15,
            duration=0,
            mana_cost=10,
            components=['V', 'S', 'M'],
            spell_tags=["fire", "area"],
            school="evocation",
            arcana_level = 3,
            cast_xp = 10
        )

    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler for selecting fireball target area."""
        def fireball_callback(target_xy):
            """Callback function for fireball targeting."""
            return actions.SpellAction(caster, self, target_xy)
        
        return AreaRangedAttackHandler(
            engine,
            radius=1,
            callback=fireball_callback
        )
    
    def activate(self, action: actions.SpellAction) -> None:
        target_xy = action.target_xy
        consumer = action.entity

        if not action.engine.game_map.visible[target_xy]:
            raise Impossible("You cannot target an area you cannot see!")
        
        targets_hit = False
        for actor in action.engine.game_map.actors:
            if actor.distance(*target_xy) <= 1:
                actor.fighter.take_damage(self.damage, causes_bleeding=False)
                targets_hit = True
        consumer.mana -= self.mana_cost
        consumer.level.add_xp({self.school: self.cast_xp})
        action.engine.animation_queue.append(animations.ExplosionAnimation(target_xy))
        action.engine.game_map.liquid_system.create_splash(target_xy[0], target_xy[1], LiquidType.FIRE, radius=2, max_depth=2)
        action.engine.message_log.add_message(
            f"The area is engulfed in flames!", color.orange
        )
        sounds.play_explosion_sound()
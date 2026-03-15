import actions
import color
from components import effect
from exceptions import Impossible
from liquid_system import LiquidType
import sounds
import animations
import tcod
from input_handlers import (
    ActionOrHandler,
    AreaRangedAttackHandler, 
    SingleRangedAttackHandler,
)


class Spell():
    def __init__(self, name, duration, description, damage, mana_cost, components, spell_tags, school, arcana_level = 1, cast_xp = 5, radius = 0):
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
        self.radius = radius

    def calculate_arcana_modifiers(self, caster):
        """Calculate arcana level equipment modifiers."""
        arcana_level = caster.level.traits['arcana']['level']
        for item in caster.equipment:
            with open("logs/log.txt", "a") as log_file:
                log_file.write(f"DEBUG: Checking item '{item.name}' for arcana modifiers.\n")
            

    def give_xp(self, consumer):
        consumer.level.add_xp({self.school: self.cast_xp})
        consumer.level.add_xp({'arcana': (5+(consumer.level.traits['arcana']['level'] * 1.5))})
        with open("logs/log.txt", "a") as log_file:
            log_file.write(f'DEBUG: Gave {self.cast_xp} XP to {self.school} and {(5+(consumer.level.traits["arcana"]["level"] * 1.5))} XP to arcana for casting {self.name}.\n')
    
    def get_description(self, caster=None):
        return ""


    def activate(self, action: actions.SpellAction) -> None:
        pass
    
    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler if this spell requires targeting, None otherwise."""
        return None

    def level_up_spell(self, level: int, entity=None) -> None:
        if level == 2:
            # Store the old name to update quickcast slots
            old_name = self.name
            
            self.damage = int(self.damage * 1.5)
            self.mana_cost += 1
            self.name += " II"
            self.radius = min(self.radius, 5)
            self.duration *= 1.5
            
            # Update quickcast slots if entity is provided
            if entity and hasattr(entity, 'quickcast_slots'):
                for i, slot_spell in enumerate(entity.quickcast_slots):
                    if slot_spell == old_name:
                        entity.quickcast_slots[i] = self.name
                        with open("logs/log.txt", "a") as log_file:
                            log_file.write(f"DEBUG: Updated quickcast slot {i+1}: '{old_name}' -> '{self.name}'\n")



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

    def get_description(self, caster=None):
        return f'Grants the ability to see in the dark for {self.duration} turns.'

    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        
        # Consume mana for successful darkvision cast
        consumer.mana -= self.mana_cost
        self.give_xp(consumer)
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
    
    def get_description(self, caster=None):
        return f"Instantly move to a visible location within range."

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
        self.give_xp(consumer)
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
            damage=3,
            duration=0,
            mana_cost=5,
            components=['V', 'S'],
            spell_tags=["poison", "ranged"],
            school="conjuration",
            arcana_level = 2,
            cast_xp = 5,
            radius = 1
        )

    def get_description(self, caster=None):
        return f"Hurl a glob of acid that damages a single target ({self.damage} damage) and coats the area in poison."

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
            self.give_xp(consumer)
            action.engine.animation_queue.append(animations.SplashAnimation((target_x, target_y), color.green))
            action.engine.game_map.liquid_system.create_splash(target_x, target_y, LiquidType.POISON, radius=self.radius, max_depth=2)
            action.engine.message_log.add_message(
                f"The poison sizzles as it hits the ground.", color.green
            )
            sounds.play_poison_burn_sound()
            return
        if target and target.fighter:
            target.fighter.take_damage(self.damage, causes_bleeding=False)
            consumer.mana -= self.mana_cost
            self.give_xp(consumer)
            # Create poison splash around the target
            action.engine.game_map.liquid_system.create_splash(target_x, target_y, LiquidType.POISON, radius=self.radius, max_depth=2)
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
            cast_xp = 10,
            radius = 2
        )

    def get_description(self, caster=None):
        return f"Launch a fiery explosion that damages all in the area ({self.damage} damage) and coats the area in fire."

    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler for selecting fireball target area."""
        def fireball_callback(target_xy):
            """Callback function for fireball targeting."""
            return actions.SpellAction(caster, self, target_xy)
        
        return AreaRangedAttackHandler(
            engine,
            radius=self.radius,
            callback=fireball_callback
        )
    
    def activate(self, action: actions.SpellAction) -> None:
        target_xy = action.target_xy
        consumer = action.entity

        if not action.engine.game_map.visible[target_xy]:
            raise Impossible("You cannot target an area you cannot see!")
        
        targets_hit = False
        for actor in action.engine.game_map.actors:
            if actor.distance(*target_xy) <= self.radius:
                actor.fighter.take_damage(self.damage, causes_bleeding=False)
                targets_hit = True
        consumer.mana -= self.mana_cost
        self.give_xp(consumer)
        action.engine.animation_queue.append(animations.ExplosionAnimation(target_xy))
        action.engine.game_map.liquid_system.create_splash(target_xy[0], target_xy[1], LiquidType.FIRE, radius=self.radius, max_depth=2)
        action.engine.message_log.add_message(
            f"The area is engulfed in flames!", color.orange
        )
        sounds.play_explosion_sound()

class HealingWordSpell(Spell):
    def __init__(self):
        super().__init__(
            name="Healing Word",
            description="A soothing word that heals a single target.",
            damage=4,  # Negative damage means healing
            duration=0,
            mana_cost=5,
            components=['V'],
            spell_tags=["healing", "ranged"],
            school="evocation",
            arcana_level = 1,
            cast_xp = 5
        )


    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler for selecting healing word target."""
        def healing_word_callback(target_xy):
            """Callback function for healing word targeting."""
            return actions.SpellAction(caster, self, target_xy)
        
        return SingleRangedAttackHandler(
            engine,
            callback=healing_word_callback
        )
    def get_description(self, caster=None):
        if caster and hasattr(caster, 'level') and 'evocation' in caster.level.traits:
            heal_bonus = caster.level.traits['evocation']['level']
            return f"A soothing word that heals a single target ({self.damage}+{heal_bonus} HP)."
        else:
            return f"A soothing word that heals a single target ({self.damage}+EVO HP)."

    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        target_x, target_y = action.target_xy
        target = action.engine.game_map.get_blocking_entity_at_location(target_x, target_y)

        if not target or not target.fighter:
            return
        
        if target and target.fighter:
            if target.fighter.hp == target.fighter.max_hp:
                action.engine.message_log.add_message(
                    f"The {target.name} is already at full health!", color.light_red
                )
                return
            else:
                heal_level = target.level.traits['evocation']['level'] 
                
                consumer.mana -= self.mana_cost
                self.give_xp(consumer)
                action.engine.animation_queue.append(animations.HealAnimation((target_x, target_y)))
                action.engine.message_log.add_message(
                    f"The {target.name} is bathed in a soothing light! (4+{heal_level} HP)", color.light_green
                )
                target.fighter.heal(heal_level + self.damage) 
                sounds.play_heal_spell_sound()
class InflictWoundsSpell(Spell):
    def __init__(self):
        super().__init__(
            name="Inflict Wounds",
            description="A dark spell that damages a single target.",
            damage=5,
            duration=0,
            mana_cost=5,
            components=['V'],
            spell_tags=["necromancy", "ranged"],
            school="necromancy",
            arcana_level = 1,
            cast_xp = 5
        )

    def get_description(self, caster=None):
        return f"A dark spell that damages a single target ({self.damage} damage)."

    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler for selecting inflict wounds target."""
        def inflict_wounds_callback(target_xy):
            """Callback function for inflict wounds targeting."""
            return actions.SpellAction(caster, self, target_xy)
        
        return SingleRangedAttackHandler(
            engine,
            callback=inflict_wounds_callback
        )

    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        target_x, target_y = action.target_xy
        target = action.engine.game_map.get_blocking_entity_at_location(target_x, target_y)

        if not target or not target.fighter:
            consumer.mana -= self.mana_cost
            self.give_xp(consumer)
            path = list(tcod.los.bresenham((consumer.x, consumer.y), (target_x, target_y)).tolist())
            action.engine.animation_queue.append(animations.DarkBoltAnimation(path))
            sounds.play_dark_spell_sound()
            action.engine.message_log.add_message(
                f"Your dark energy lashes out but finds no target.", color.dark_red
            )
            return
        
        if target and target.fighter:
            action.engine.message_log.add_message(
                f"The {target.name} is struck by dark energy!", color.dark_purple
            )
            target.fighter.take_damage(self.damage, causes_bleeding=False)
            consumer.mana -= self.mana_cost
            self.give_xp(consumer)
            # Create path from caster to target for animation
            path = list(tcod.los.bresenham((consumer.x, consumer.y), (target_x, target_y)).tolist())
            action.engine.animation_queue.append(animations.DarkBoltAnimation(path))
            sounds.play_dark_spell_sound()
            
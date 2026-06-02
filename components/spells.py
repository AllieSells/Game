import actions
import color
from components import effect
from components.ai import FollowerAI
from exceptions import Impossible
from liquid_system import LiquidType
from components.damage_types import DamageType
import sounds
import animations
import tcod
from input_handlers import (
    AreaRangedAttackHandler, 
    SingleRangedAttackHandler,
)
import gpu_stack
import random
from roman import toRoman

class Spell():
    def __init__(self, name, duration, description, damage, mana_cost,
                 components, spell_tags, school, arcana_level = 1, cast_xp = 5, 
                 radius = 0, max_spell_level: int = 5, damage_type: DamageType = None):
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
        self.max_spell_level = max(1, int(max_spell_level))
        self.spell_level = 1  # tracks how many times spell has been upgraded
        self.damage_type = damage_type

    def calculate_arcana_modifiers(self, caster):
        """Calculate arcana level equipment modifiers."""
        for item in caster.equipment:
            with open("logs/log.txt", "a") as log_file:
                log_file.write(f"DEBUG: Checking item '{item.name}' for arcana modifiers.\n")
            

    def give_xp(self, consumer):
        consumer.level.add_xp({self.school: self.cast_xp * consumer.level.traits["arcana"]["level"] * 2})
        consumer.level.add_xp({'arcana': self.cast_xp + (10+(consumer.level.traits["arcana"]["level"] * 2))})
        with open("logs/log.txt", "a") as log_file:
            log_file.write(f'DEBUG: Gave {self.cast_xp * consumer.level.traits["arcana"]["level"]} XP to {self.school} and {(10+(consumer.level.traits["arcana"]["level"] * 2))} XP to arcana for casting {self.name}.\n')
    
    def get_description(self, caster=None):
        return ""

    def _cast_potency_multiplier(self, action: actions.SpellAction) -> float:
        return 1.0

    def _scaled_amount(self, action: actions.SpellAction, amount: int) -> int:
        return max(0, int(round(int(amount) * self._cast_potency_multiplier(action))))
    
    def _apply_spell_damage(self, action: actions.SpellAction, target, damage: int) -> tuple[int, bool]:
        """
        Apply spell damage using the centralized damage calculation system.
        
        Args:
            action: The spell action being performed
            target: The target actor
            damage: The scaled spell damage to apply
        
        Returns:
            tuple[int, bool]: (final_damage dealt, was_fully_resisted)
        """
        if not target or not hasattr(target, 'fighter'):
            return 0, False
        
        # Use the centralized damage calculation for spells
        final_damage, _, was_fully_resisted, deflected = actions.calculate_damage(
            attacker=action.entity,
            target=target,
            base_damage=damage,
            attack_type="spell",
            damage_type=self.damage_type if hasattr(self, 'damage_type') else None,
            damage_modifier=1.0,
            hit_part=None,
            proficiency_profile=None,
            armor_tags=None,
        )
        
        # Apply damage to target
        target.fighter.take_damage(final_damage, causes_bleeding=False)
        return final_damage, was_fully_resisted

    def _spend_mana_and_award_xp(self, caster) -> None:
        caster.mana -= self.mana_cost
        self.give_xp(caster)

    def _apply_effect(self, target, effect_instance, action: actions.SpellAction) -> None:
        engine = getattr(action, "engine", None)
        if engine is not None and hasattr(engine, "add_or_refresh_effect"):
            engine.add_or_refresh_effect(target, effect_instance)
            return
        target.add_effect(effect_instance)

    def _check_spell_hit(self, caster, target) -> bool:
        """Check if a targeted spell hits the target.
        
        Base hit chance of 70%, modified by caster's arcana level vs target's agility.
        Returns True if the spell hits, False if it misses.
        """
        base_hit_chance = 0.70
        
        # Get caster's arcana level
        caster_arcana = 1
        if hasattr(caster, 'level') and hasattr(caster.level, 'traits'):
            caster_arcana = caster.level.traits.get('arcana', {}).get('level', 1)
        
        # Get target's agility level (for dodging spells)
        target_agility = 1
        if hasattr(target, 'level') and hasattr(target.level, 'traits'):
            target_agility = target.level.traits.get('agility', {}).get('level', 1)
        
        # Modify hit chance based on arcana vs agility
        hit_modifier = (caster_arcana - target_agility) * 0.05
        hit_chance = max(0.30, min(0.95, base_hit_chance + hit_modifier))
        
        return random.random() < hit_chance

    def activate(self, action: actions.SpellAction) -> None:
        pass
    
    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler if this spell requires targeting, None otherwise."""
        return None

    def level_up_spell(self, level: int, entity=None) -> None:
        try:
            requested_level = max(1, int(level or 1))
        except Exception:
            return

        target_level = min(requested_level, self.max_spell_level)

        if target_level <= self.spell_level:
            return

        old_name = self.name
        base_name = old_name.rsplit(" ", 1)[0] if self.spell_level > 1 else old_name

        # Apply one upgrade step per level to keep scaling consistent for III+ sync.
        for _ in range(self.spell_level, target_level):
            self.damage = int(self.damage * 1.5)
            self.mana_cost += 1
            self.radius = min(self.radius, 5)
            self.duration *= 1.5

        self.spell_level = target_level
        self.name = f"{base_name} {toRoman(self.spell_level)}" if self.spell_level > 1 else base_name

        # Update quickcast slots if entity is provided
        if entity and hasattr(entity, 'quickcast_slots'):
            for i, slot_spell in enumerate(entity.quickcast_slots):
                if slot_spell == old_name:
                    entity.quickcast_slots[i] = self.name
                    with open("logs/log.txt", "a") as log_file:
                        log_file.write(f"DEBUG: Updated quickcast slot {i+1}: '{old_name}' -> '{self.name}'\n")

class IronskinSpell(Spell):
    def __init__(self):
        duration = 20
        super().__init__(
            name="Ironskin",
            description=f"Grants x1.5 defense for {duration} turns.",
            damage=0,
            duration=duration,
            mana_cost=10,
            components=['S', 'V'],
            spell_tags=["ironskin"],
            school='abjuration',
            arcana_level = 2,
            cast_xp = 5,
            max_spell_level=5,
            damage_type = None
        )
    def get_description(self, caster=None):
        return f"Grants x1.5 defense for {self.duration} turns."
    
    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity

        self._spend_mana_and_award_xp(consumer)
        self._apply_effect(consumer, effect.IronskinEffect(duration=self.duration, multiplier=(self.spell_level * 0.5)), action)
        sounds.play_confusion_sound()  # temp
        action.engine.message_log.add_message(
            "Your skin hardens like iron!", color.light_gray
        )

class InvisibilitySpell(Spell):
    def __init__(self):
        duration = 20
        super().__init__(
            name="Invisibility",
            description=f"Grants invisibility for {duration} turns.",
            damage=0,
            duration=duration,
            mana_cost=10,
            components=['S', 'V'],
            spell_tags=["invisibility"],
            school="illusion",
            arcana_level = 2,
            cast_xp=5,
            max_spell_level=5,
            damage_type = None
        )

    def get_description(self, caster=None):
        return f"Grants invisibility for {self.duration} turns."
    
    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity

        self._spend_mana_and_award_xp(consumer)
        invisibility = effect.InvisibilityEffect(duration=self.duration)
        sounds.play_confusion_sound() # temp
        action.engine.message_log.add_message(
            "You fade from view!", color.light_gray
        )
        self._apply_effect(consumer, invisibility, action)

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
            cast_xp=5,
            max_spell_level=5,
            damage_type = None
        )

    def get_description(self, caster=None):
        return f'Grants the ability to see in the dark for {self.duration} turns.'

    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        self._spend_mana_and_award_xp(consumer)
        darkvision = effect.DarkvisionEffect(duration=self.duration)
        sounds.play_darkvision_sound()
        action.engine.message_log.add_message(
            "Your vision sharpens as darkness recedes!", color.dark_purple
        )
        self._apply_effect(consumer, darkvision, action)

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
            cast_xp = 10,
            max_spell_level=1,
            damage_type = None


        )
    
    def get_description(self, caster=None):
        return "Instantly move to a visible location within range."

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
                "You can't teleport there - it's out of bounds!", color.impossible
            )
            return
        
        # Check if location is visible
        if not action.engine.game_map.visible[target_x, target_y]:
            action.engine.message_log.add_message(
                "You can't teleport to a location you can't see!", color.impossible
            )
            return
        
        # Check if location is walkable
        if not action.engine.game_map.tiles[target_x, target_y]['walkable']:
            action.engine.message_log.add_message(
                "You can't teleport into a solid object!", color.impossible
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
        action.engine.animation_queue.append(gpu_stack.SpaceDistortSpellParticle((target_x, target_y)))
        action.engine.animation_queue.append(gpu_stack.SpaceDistortSpellParticle((target_x, target_y)))
        
        consumer.x = target_x
        consumer.y = target_y
        
        sounds.play_teleport_sound()
        action.engine.message_log.add_message(
            "Space distorts around you!", color.ascend
        )
        try:
            import sys
            _main = sys.modules.get("__main__")
            if _main is not None and hasattr(_main, "_active_degauss"):
                _main._active_degauss = _main.DegaussAnimation(_main.renderer, mode="teleport")
        except Exception:
            pass

class PoisonSpraySpell(Spell):
    def __init__(self):
        super().__init__(
            name="Poison Spray",
            description="Hurl a glob of acid that damages a single target.",
            damage=1,
            duration=0,
            mana_cost=5,
            components=['V', 'S'],
            spell_tags=["poison", "ranged"],
            school="conjuration",
            arcana_level = 2,
            cast_xp = 5,
            radius = 1,
            max_spell_level=5,
            damage_type = DamageType.POISON
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
        scaled_damage = self._scaled_amount(action, self.damage)

        if not target or not target.fighter:
            consumer.mana -= self.mana_cost
            self.give_xp(consumer)
            #action.engine.animation_queue.append(animations.SplashAnimation((target_x, target_y), color.green))
            action.engine.animation_queue.append(gpu_stack.PoisonSprayParticle((target_x, target_y)))
            action.engine.game_map.liquid_system.create_splash(target_x, target_y, LiquidType.POISON, radius=self.radius, max_depth=2)
            action.engine.message_log.add_message(
                "The poison sizzles as it hits the ground.", color.green
            )
            sounds.play_poison_burn_sound()
            return
        
        if target and target.fighter:
            # Check if spell hits
            spell_hits = self._check_spell_hit(consumer, target)
            
            if not spell_hits:
                # Spell misses - target adjacent tile
                miss_x, miss_y = actions.get_adjacent_miss_position(target_x, target_y, action.engine.game_map)
                consumer.mana -= self.mana_cost
                self.give_xp(consumer)
                
                action.engine.animation_queue.append(gpu_stack.PoisonSprayParticle((miss_x, miss_y)))
                action.engine.game_map.liquid_system.create_splash(miss_x, miss_y, LiquidType.POISON, radius=self.radius, max_depth=2)
                action.engine.message_log.add_message(
                    f"The poison spray misses {target.name}!", color.dark_gray
                )
                sounds.play_poison_burn_sound()
                
                # Check for collateral target at miss position
                collateral_target = action.engine.game_map.get_actor_at_location(miss_x, miss_y)
                if collateral_target and collateral_target != consumer and collateral_target != target:
                    collateral_damage = max(1, scaled_damage // 2)
                    collateral_target.fighter.take_damage(collateral_damage, causes_bleeding=False)
                    action.engine.message_log.add_message(
                        f"The poison spray hits {collateral_target.name} instead for {collateral_damage} damage!",
                        color.orange
                    )
                return
            
            # Spell hits - use centralized damage application
            final_damage, was_fully_resisted = self._apply_spell_damage(action, target, scaled_damage)
            consumer.mana -= self.mana_cost
            self.give_xp(consumer)
            # Create poison splash around the target
            action.engine.game_map.liquid_system.create_splash(target_x, target_y, LiquidType.POISON, radius=self.radius, max_depth=2)
            #action.engine.animation_queue.append(animations.SplashAnimation((target_x, target_y), color.green))
            action.engine.animation_queue.append(gpu_stack.PoisonSprayParticle((target_x, target_y)))
            if was_fully_resisted:
                action.engine.message_log.add_message(
                    f"The poison hits the {target.name}, but the attack is completely resisted!", color.light_blue
                )
            else:
                action.engine.message_log.add_message(
                    f"The poison hits the {target.name}!", color.green
                )
            sounds.play_poison_burn_sound()
            return

class SleepSpell(Spell):
    def __init__(self):
        duration = 10
        super().__init__(
            name="Sleep",
            description=f"Put a single target to sleep for {duration} turns.",
            damage=0,
            duration=duration,
            mana_cost=5,
            components=['V', 'S'],
            spell_tags=["sleep", "ranged"],
            school="enchantment",
            arcana_level = 2,
            cast_xp = 5,
            max_spell_level=3,
            damage_type = DamageType.PSYCHIC
        )

    def get_description(self, caster=None):
        return f"Put a single target to sleep for {self.duration} turns."

    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler for selecting sleep spell target."""
        def sleep_callback(target_xy):
            """Callback function for sleep spell targeting."""
            return actions.SpellAction(caster, self, target_xy)
        
        return SingleRangedAttackHandler(
            engine,
            callback=sleep_callback
        )

    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        target_x, target_y = action.target_xy
        target = action.engine.game_map.get_blocking_entity_at_location(target_x, target_y)

        if not target or not target.fighter:
            consumer.mana -= self.mana_cost
            self.give_xp(consumer)
            action.engine.message_log.add_message(
                "Your spell has no effect.", color.light_gray
            )
            return
        
        # Check if target is immune to psychic damage
        if actions.is_immune_to_damage_type(target, self.damage_type):
            consumer.mana -= self.mana_cost
            self.give_xp(consumer)
            action.engine.message_log.add_message(
                f"The {target.name} is immune to psychic effects!", color.light_gray
            )
            return
        
        if target and target.fighter:
            sleep_effect = effect.SleepEffect(duration=self.duration)
            self._apply_effect(target, sleep_effect, action)
            consumer.mana -= self.mana_cost
            self.give_xp(consumer)
            action.engine.message_log.add_message(
                f"The {target.name} falls asleep!", color.light_gray
            )
            sounds.play_heal_spell_sound()
            return
        
class ClairvoyanceSpell(Spell):
    def __init__(self):
        super().__init__(
            name="Clairvoyance",
            description="Find the path to the nearest exit",
            damage=0,
            duration=0,
            mana_cost=15,
            components=['V', 'S'],
            spell_tags=["clairvoyance"],
            school="divination",
            arcana_level = 3,
            cast_xp = 10,
            max_spell_level=1,
            damage_type = None
        )
    def get_description(self, caster=None):
        return "Find the path to the nearest exit."
    
    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        gm = action.engine.game_map

        # Find nearest exit
        exit_locations = getattr(gm, "downstairs_location", None)
        if not exit_locations:
            action.engine.message_log.add_message(
                "There is no exit to find!", color.impossible
            )
            return

        # Support either a single (x, y) tuple or an iterable of (x, y) tuples.
        if (
            isinstance(exit_locations, tuple)
            and len(exit_locations) == 2
            and all(isinstance(v, int) for v in exit_locations)
        ):
            nearest_exit = exit_locations
        else:
            nearest_exit = min(exit_locations, key=lambda loc: consumer.distance(*loc))

        # Reveal path to exit - create custom walkability that includes doors
        walkable_with_doors = gm.tiles['walkable'].copy()
        # Mark all door tiles as walkable for pathfinding
        door_tiles = (gm.tiles['name'] == 'Door') | (gm.tiles['name'] == 'Open Door') | (gm.tiles['name'] == 'Locked Door')
        walkable_with_doors = walkable_with_doors | door_tiles
        
        path = tcod.path.AStar(walkable_with_doors, diagonal=0)
        path_result = path.get_path(consumer.x, consumer.y, nearest_exit[0], nearest_exit[1])
        if not path_result:
            action.engine.message_log.add_message(
                "No path to the exit could be found!", color.impossible
            )
            return
        # Reveal the path on the map
        #for x, y in path_result:
            #gm.visible[x, y] = True
            #gm.explored[x, y] = True
        action.engine.animation_queue.append(
            gpu_stack.RevealParticle(position=path_result[0], path=path_result, color=(0, 255, 255))
        )
        consumer.mana -= self.mana_cost
        self.give_xp(consumer)
        action.engine.message_log.add_message(
            "Your vision extends to reveal the path to the exit!", color.cyan)
        sounds.play_darkvision_sound()

class FireballSpell(Spell):
    def __init__(self):
        super().__init__(
            name="Fireball",
            description="Launch a fiery explosion that damages all in the area.",
            damage=5,
            duration=0,
            mana_cost=15,
            components=['V', 'S', 'M'],
            spell_tags=["fire", "area"],
            school="evocation",
            arcana_level = 3,
            cast_xp = 15,
            radius = 2,
            max_spell_level=3,
            damage_type = DamageType.FIRE
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
        scaled_damage = self._scaled_amount(action, self.damage)

        if not action.engine.game_map.visible[target_xy]:
            raise Impossible("You cannot target an area you cannot see!")
        
        for actor in action.engine.game_map.actors:
            if actor.distance(*target_xy) <= self.radius:
                # Use centralized damage application
                final_damage, was_fully_resisted = self._apply_spell_damage(action, actor, scaled_damage)
                if was_fully_resisted:
                    action.engine.message_log.add_message(
                        f"The {actor.name} completely resists the flames!", color.light_blue
                    )
        consumer.mana -= self.mana_cost
        self.give_xp(consumer)
        action.engine.animation_queue.append(animations.ExplosionAnimation(target_xy))
        action.engine.animation_queue.append(
            gpu_stack.FireballExplosionParticle(target_xy, radius=self.radius + 0.5)
        )
        action.engine.game_map.liquid_system.create_splash(target_xy[0], target_xy[1], LiquidType.FIRE, radius=self.radius, max_depth=2)
        action.engine.message_log.add_message(
            "The area is engulfed in flames!", color.orange
        )
        sounds.play_explosion_sound()


class LightSpell(Spell):
    def __init__(self):
        super().__init__(
            name="Light",
            description="Summon a floating orb of light that illuminates the area.",
            damage=0,
            duration=40,
            mana_cost=5,
            components=['V', 'S'],
            spell_tags=["light"],
            school="evocation",
            arcana_level = 1,
            cast_xp = 1,
            radius = 5,
            max_spell_level=5
        )
    def get_description(self, caster=None):
        return f"Summon a floating orb of light that illuminates the area for {self.duration} turns."
    
    def activate(self, action: actions.SpellAction) -> None:
        import entity_factories
        consumer = action.entity
        gm = action.engine.game_map

        # Try to spawn adjacent to the player first, then fall back to any visible walkable tile
        px, py = consumer.x, consumer.y
        candidates = [(px + dx, py + dy) for dx in range(-1, 2) for dy in range(-1, 2)
                      if not (dx == 0 and dy == 0)]
        candidates += list(zip(*gm.visible.nonzero()))

        for x, y in candidates:
            x, y = int(x), int(y)
            if not gm.in_bounds(x, y) or not gm.visible[x, y]:
                continue
            if not gm.tiles[x, y]['walkable']:
                continue
            if gm.get_blocking_entity_at_location(x, y):
                continue
            # Spawn a fresh clone so the template is never mutated
            light_orb = entity_factories.light_orb.spawn(gm, x, y)
            light_orb.ai = FollowerAI(light_orb, consumer)
            light_orb.add_effect(effect.LightEffect(duration=self.duration))
            self.give_xp(consumer)
            consumer.mana -= self.mana_cost
            action.engine.message_log.add_message(
                "You summon an orb of light!", color.yellow)
            return

        action.engine.message_log.add_message(
            "There is no room to summon the orb!", color.impossible)

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
            cast_xp = 5,
            max_spell_level=5
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
                scaled_base_heal = self._scaled_amount(action, self.damage)
                
                consumer.mana -= self.mana_cost
                self.give_xp(consumer)
                for _ in range(random.randint(3, 5)):
                    action.engine.animation_queue.append(gpu_stack.HealthParticle((target_x+random.uniform(-0.5, 0.5), target_y+random.uniform(-0.5, 0.5)), target))
                
                action.engine.message_log.add_message(
                    f"The {target.name} is bathed in a soothing light! ({scaled_base_heal}+{heal_level} HP)", color.light_green
                )
                target.fighter.heal(heal_level + scaled_base_heal) 
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
            cast_xp = 5,
            max_spell_level=4,
            damage_type = DamageType.NECROTIC
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
        scaled_damage = self._scaled_amount(action, self.damage)

        if not target or not target.fighter:
            consumer.mana -= self.mana_cost
            self.give_xp(consumer)
            path = list(tcod.los.bresenham((consumer.x, consumer.y), (target_x, target_y)).tolist())
            action.engine.animation_queue.append(gpu_stack.JaggedLineSpellParticle(path, color.dark_purple))
            sounds.play_dark_spell_sound()
            # Make sure is player
            if consumer.is_player:
                action.engine.message_log.add_message(
                    "Your dark energy lashes out but finds no target.", color.dark_red
                )
            return
        
        if target and target.fighter:
            # Check if spell hits
            spell_hits = self._check_spell_hit(consumer, target)
            
            if not spell_hits:
                # Spell misses - target adjacent tile
                miss_x, miss_y = actions.get_adjacent_miss_position(target_x, target_y, action.engine.game_map)
                consumer.mana -= self.mana_cost
                self.give_xp(consumer)
                
                path = list(tcod.los.bresenham((consumer.x, consumer.y), (miss_x, miss_y)).tolist())
                action.engine.animation_queue.append(gpu_stack.JaggedLineSpellParticle(path, color.dark_purple))
                action.engine.message_log.add_message(
                    f"The dark energy misses {target.name}!", color.dark_gray
                )
                sounds.play_dark_spell_sound()
                
                # Check for collateral target at miss position
                collateral_target = action.engine.game_map.get_actor_at_location(miss_x, miss_y)
                if collateral_target and collateral_target != consumer and collateral_target != target:
                    collateral_damage = max(1, scaled_damage // 2)
                    collateral_target.fighter.take_damage(collateral_damage, causes_bleeding=False)
                    action.engine.message_log.add_message(
                        f"The dark energy strikes {collateral_target.name} instead for {collateral_damage} damage!",
                        color.orange
                    )
                return
            
            # Use centralized damage application
            final_damage, was_fully_resisted = self._apply_spell_damage(action, target, scaled_damage)
            consumer.mana -= self.mana_cost
            self.give_xp(consumer)
            # Create path from caster to target for animation
            path = list(tcod.los.bresenham((consumer.x, consumer.y), (target_x, target_y)).tolist())
            action.engine.animation_queue.append(gpu_stack.JaggedLineSpellParticle(path, color.dark_purple))
            sounds.play_dark_spell_sound()
            if was_fully_resisted:
                action.engine.message_log.add_message(
                    f"The {target.name} is struck by dark energy, but the attack is completely resisted!", color.light_blue
                )
            else:
                action.engine.message_log.add_message(
                    f"The {target.name} is struck by dark energy for {final_damage} damage!", color.dark_purple
                )
            

class MirrorImageSpell(Spell):
    def __init__(self):
        duration = 20
        super().__init__(
            name="Mirror Image",
            description=f"Create a duplicate of yourself that confuses enemies for {duration} turns.",
            damage=0,
            duration=duration,
            mana_cost=10,
            components=['V', 'S'],
            spell_tags=["mirror_image"],
            school="illusion",
            arcana_level = 2,
            cast_xp = 5,
            max_spell_level=4,
            damage_type = None
        )

    def get_description(self, caster=None):
        return f"Create a duplicate of yourself that confuses enemies for {self.duration} turns."
    
    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        gm = action.engine.game_map
        print(f"CLONES: {len(consumer.entity_clones)}")
        if len(consumer.entity_clones) >= 1 + int(self.spell_level * 0.5):
            action.engine.message_log.add_message(
                "You cannot create more mirror images!", color.impossible
            )
            return
        # Spawn a mirror image adjacent to the consumer
        from entity_factories import create_illusion
        mirror_image = create_illusion(consumer)
        # Find an adjacent empty tile to spawn the illusion
        spawn_x, spawn_y = consumer.x, consumer.y
        for dx, dy in [(0, -1), (1, 0), (0, 1), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)]:
            nx, ny = consumer.x + dx, consumer.y + dy
            if (gm.in_bounds(nx, ny) and 
                gm.tiles["walkable"][nx, ny] and 
                not gm.get_blocking_entity_at_location(nx, ny)):
                spawn_x, spawn_y = nx, ny
                break
        
        # Capture the spawned clone (spawn returns a new deepcopy)
        spawned_illusion = mirror_image.spawn(gm, spawn_x, spawn_y)
        if spawned_illusion.ai and hasattr(spawned_illusion.ai, 'target'):
            spawned_illusion.ai.target = consumer
        
        spawned_illusion.effects.append(effect.ExpiryEffect(duration=self.duration))
        consumer.entity_clones.append(spawned_illusion)

        self.give_xp(consumer)
        consumer.mana -= self.mana_cost
        action.engine.message_log.add_message(
            "You create a mirror image of yourself!", color.cyan
        )
        sounds.play_confusion_sound()


class MageArmorSpell(Spell):
    def __init__(self):
        duration = 30
        base_armor_bonus = 2
        super().__init__(
            name="Mage Armor",
            description=f"A magical set of armor that gives {base_armor_bonus} armor for {duration} turns.",
            damage=0,
            duration=duration,
            mana_cost=10,
            components=['V', 'S', 'M'],
            spell_tags=["mage_armor"],
            school="abjuration",
            arcana_level = 1,
            cast_xp = 5,
            max_spell_level=5,
            damage_type = None
        )
    def get_description(self, caster=None):
        return f"A magical set of armor that gives {int(self.spell_level * 2)} armor for {self.duration} turns."
    def activate(self, action: actions.SpellAction) -> None:
        consumer = action.entity
        armor_effect = effect.MageArmorEffect(duration=self.duration, armor_bonus=int(self.spell_level * 2))
        self._spend_mana_and_award_xp(consumer)
        consumer.add_effect(armor_effect)
        action.engine.message_log.add_message(
            "You are surrounded by a magical armor!", color.light_blue
        )
        sounds.play_confusion_sound()

class DragonsBreathSpell(Spell):
    def __init__(self):
        super().__init__(
            name="Dragon's Breath",
            description="Exhale a cone of elemental energy that damages all in the area.",
            damage=4,
            duration=0,
            mana_cost=15,
            components=['V', 'S', 'M'],
            spell_tags=["dragon_breath", "area"],
            school="transmutation",
            arcana_level = 2,
            cast_xp = 10
        )

    def get_description(self, caster=None):
        return f"Exhale a cone of elemental energy that damages all in the area ({self.damage} damage)."

    def get_targeting_handler(self, engine, caster):
        """Return a targeting handler for selecting dragon's breath target area."""
        def dragon_breath_callback(target_xy):
            """Callback function for dragon's breath targeting."""
            return actions.SpellAction(caster, self, target_xy)
        
        return SingleRangedAttackHandler(
            engine,
            callback=dragon_breath_callback
        )

    def activate(self, action: actions.SpellAction, _range: int = 5) -> None:
        consumer = action.entity
        target_x, target_y = action.target_xy

        # Calculate direction vector from caster to target
        dx = target_x - consumer.x
        dy = target_y - consumer.y
        
        # Normalize direction to unit vector (or close to it)
        # Use Chebyshev distance normalization (makes diagonals work properly)
        distance = max(abs(dx), abs(dy))
        if distance > 0:
            # Normalize to create a proper directional vector
            norm_dx = dx / distance
            norm_dy = dy / distance
            # Round to nearest integer for clean spray line
            direction = (round(norm_dx), round(norm_dy))
        else:
            # Default direction if targeting self
            direction = (1, 0)

        if not action.engine.game_map.visible[target_x, target_y]:
            raise Impossible("You cannot target an area you cannot see!")
        
        # Create liquid spray with normalized direction
        action.engine.game_map.liquid_system.create_spray(
            consumer.x, consumer.y, direction, LiquidType.FIRE, length=_range
        )
        sounds.play_dragon_breath_sound()
        sounds.play_explosion_sound()


class RemoveCurseSpell(Spell):
    def __init__(self):
        super().__init__(
            name="Remove Curse",
            description="Sever your connection to a cursed item.",
            damage=0,
            duration=0,
            mana_cost=15,
            components=['V', 'S'],
            spell_tags=["remove_curse"],
            school="abjuration",
            arcana_level = 3,
            cast_xp = 10,
            max_spell_level=1,
            damage_type = None
        )

    def get_description(self, caster=None):
        return "Sever your connection to a cursed item."
    
    def get_targeting_handler(self, engine, caster):
        """Return a handler for selecting an equipped cursed item."""
        from inventory_ui import RemoveCurseEquipmentGridUI
        return RemoveCurseEquipmentGridUI(engine, caster, self)
    
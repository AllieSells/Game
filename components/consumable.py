from __future__ import annotations

import json
from typing import Optional, TYPE_CHECKING
from pathlib import Path

import actions
import color
from animations import LightningAnimation
import components.ai

import tcod


from components import effect
import components.inventory
from components.base_component import BaseComponent
from exceptions import Impossible
from input_handlers import (
    AreaRangedAttackHandler, 
    SingleRangedAttackHandler,
)
from components.spells import (
    ClairvoyanceSpell,
    DarkvisionSpell,
    FireballSpell,
    HealingWordSpell,
    InflictWoundsSpell,
    LightSpell,
    PoisonSpraySpell,
    SleepSpell,
    TeleportSpell,
    InvisibilitySpell,
    IronskinSpell,
    MirrorImageSpell,
    MageArmorSpell,
    RemoveCurseSpell,
)

if TYPE_CHECKING:
    from entity import Actor, Item

import sounds

# Spell registry (tome)

_SPELL_CLASS_BY_NAME = {
    "Teleport": TeleportSpell,
    "Darkvision": DarkvisionSpell,
    "Poison Spray": PoisonSpraySpell,
    "Fireball": FireballSpell,
    "Healing Word": HealingWordSpell,
    "Inflict Wounds": InflictWoundsSpell,
    "Light": LightSpell,
    "Invisibility": InvisibilitySpell,
    "Ironskin": IronskinSpell,
    "Sleep": SleepSpell,
    "Clairvoyance": ClairvoyanceSpell,
    "Mirror Image": MirrorImageSpell,
    "Mage Armor": MageArmorSpell,
    "Remove Curse": RemoveCurseSpell,
}

_SPELL_BOOK_CACHE = None


def get_spellbook_entries() -> list[dict]:
    global _SPELL_BOOK_CACHE
    if _SPELL_BOOK_CACHE is not None:
        return _SPELL_BOOK_CACHE
    """Read spell metadata rows from json/spells.json."""
    json_path = Path(__file__).resolve().parent.parent / "json" / "spells.json"
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    entries = raw.get("spells", raw) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []

    rows: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        spell_class = _SPELL_CLASS_BY_NAME.get(name) or _SPELL_CLASS_BY_NAME.get(name.title()) or _SPELL_CLASS_BY_NAME.get(name.lower().title())
        if spell_class is None:
            continue
        raw_color = entry.get("color", [255, 255, 255])
        if isinstance(raw_color, (list, tuple)) and len(raw_color) == 3:
            item_color = tuple(max(0, min(255, int(v))) for v in raw_color)
        else:
            item_color = (255, 255, 255)
        rows.append(
            {
                "name": name,
                "school": str(entry.get("school", "evocation")),
                "description": str(entry.get("description", "An ancient spell.")),
                "color": item_color,
                "spell_class": spell_class,
            }
        )
    _SPELL_BOOK_CACHE = rows
    return rows


class Consumable(BaseComponent):
    parent: Item

    def get_action(self, consumer: Actor) -> Optional[object]:
        # Try to return action for item
        return actions.ItemAction(consumer, self.parent)
    
    def activate(self, action:actions.ItemAction) -> None:
        #activate ability
        raise NotImplementedError()
    
    def consume(self) -> None:
        #removes consumed item from inventory
        entity = self.parent
        inventory = entity.parent
        if isinstance(inventory, components.inventory.Inventory):
            inventory.items.remove(entity)

class FoodConsumable(Consumable):
    """Food item that restores saturation and optionally hunger.

    saturation_restore: how much saturation (0-100) this item adds.
        Snacks / raw ingredients  → small (~15-25).
        Full cooked meals         → large (~80-100).
    hunger_restore: how much hunger (0-100) this item adds directly.
        Most snacks leave this at 0; meals should restore some.
    The regen buff (SaturatedEffect) is only granted when saturation
    reaches the WELL_FED threshold (≥ 75) after eating.
    """
    WELL_FED_THRESHOLD: float = 75.0

    def __init__(self, saturation_restore: float, hunger_restore: float = 0.0):
        self.saturation_restore = saturation_restore
        self.hunger_restore = hunger_restore

    def activate(self, action: actions.ItemAction) -> None:
        consumer = action.entity
        before_sat = getattr(consumer, 'saturation', 0.0)

        # Restore saturation and hunger directly.
        if hasattr(consumer, 'saturation'):
            consumer.saturation = min(100.0, consumer.saturation + self.saturation_restore)
        if self.hunger_restore > 0 and hasattr(consumer, 'hunger'):
            consumer.hunger = min(100.0, consumer.hunger + self.hunger_restore)

        after_sat = getattr(consumer, 'saturation', 0.0)

        # Determine feedback message.
        if after_sat >= self.WELL_FED_THRESHOLD:
            self.engine.message_log.add_message(
                f"You eat the {self.parent.name} and feel well-fed!",
                color.status_effect_applied,
            )
            # Remove hunger/starving debuffs and grant the regen buff.
            consumer.effects = [
                e for e in getattr(consumer, 'effects', [])
                if getattr(e, 'type', '') not in ('Hungry', 'Starving')
            ]
            # Replace any existing SaturatedEffect rather than stacking.
            consumer.effects = [
                e for e in getattr(consumer, 'effects', [])
                if getattr(e, 'name', '') != 'Saturated'
            ]
            consumer.add_effect(effect.SaturatedEffect())
        elif after_sat > before_sat:
            self.engine.message_log.add_message(
                f"You eat the {self.parent.name}.",
                color.white,
            )
        else:
            self.engine.message_log.add_message(
                f"You eat the {self.parent.name}, but you're already full.",
                color.white,
            )

        self.consume()
        sounds.play_bite_sound()
        
        

class ConfusionConsumable(Consumable):
    def __init__(self, duration: int):
        self.duration = duration

    def get_action(self, consumer: Actor) -> SingleRangedAttackHandler:
        self.engine.message_log.add_message(
            "Select a target location.", color.needs_target
        )

        return SingleRangedAttackHandler(
            self.engine,
            callback = lambda xy: actions.ItemAction(consumer, self.parent, xy)
        )
    
    def activate(self, action: actions.ItemAction) -> None:
        consumer = action.entity
        target = action.target_actor

        if not self.engine.game_map.visible[action.target_xy]:
            raise Impossible("You cannot target an area you cannot see")
        if not target:
            raise Impossible("You must select an enemy to target.")
        if target is consumer:
            raise Impossible("You cannot confuse yourself!")
        
        # Check if target is immune to psychic effects (confusion is psychic)
        from components.damage_types import DamageType
        if actions.is_immune_to_damage_type(target, DamageType.PSYCHIC):
            self.engine.message_log.add_message(
                f"The {target.name} is immune to psychic effects!", color.impossible
            )
            raise Impossible(f"The {target.name} is immune!")
        
        self.engine.message_log.add_message(
            f"You have confused the {target.name}!", color.status_effect_applied
        )
        
        target.ai = components.ai.ConfusedEnemy(
            entity=target, previous_ai=target.ai, turns_remaining=self.duration,
        )
        sounds.play_quaff_sound()
        self.consume()
        sounds.confusion_sound.play()
class PoisonConsumables(Consumable):
    def __init__(self, amount: int, duration: int):
        self.amount = amount
        self.duration = duration

    def activate(self, action: actions.ItemAction) -> None:
        consumer = action.entity
        sounds.play_quaff_sound()
        poison = effect.PoisonEffect(amount=self.amount, duration=self.duration)
        consumer.add_effect(poison)
        self.consume()

class HealingConsumables(Consumable):
    def __init__(self, amount: int):
        self.amount = amount

    def activate(self, action: actions.ItemAction) -> None:
        consumer = action.entity
        from components.effect import HealingEffect
        healing_effect = HealingEffect(total_amount=self.amount, duration=6)
        consumer.add_effect(healing_effect)

        if self.amount > 0:
            sounds.play_quaff_sound()
            self.engine.message_log.add_message(
                f"You consume the {self.parent.name}!",
                color.health_recovered
            )
            self.consume()
        else:
            raise Impossible("Your health is already full.")
        
class FireResistanceConsumable(Consumable):
    def __init__(self, duration: int):
        self.duration = duration

    def activate(self, action: actions.ItemAction) -> None:
        consumer = action.entity
        from components.effect import FireResistanceEffect
        fire_resistance = FireResistanceEffect(duration=self.duration)
        consumer.add_effect(fire_resistance)
        self.engine.message_log.add_message(
            "You feel resistant to fire!", color.orange
        )
        sounds.play_quaff_sound()
        self.consume()

class SpellbookConsumable(Consumable):
    def __init__(self, unlock_name: str):
        self.unlock_name = unlock_name

    def activate(self, action: actions.ItemAction) -> None:
        consumer = action.entity
        try:
            spell_lut = {
                row["name"].strip().lower(): (row["spell_class"], row["school"], None)
                for row in get_spellbook_entries()
            }
        except Exception as e:
            print(f"ERROR: Failed to load spellbook entries: {e}")
            spell_lut = {}

        unlock_key = str(self.unlock_name).strip().lower()

        if unlock_key not in spell_lut:
            raise Impossible(f"Unknown spell unlock: {self.unlock_name}")

        spell_class, school, _sound_func = spell_lut[unlock_key]
        spell_names = [spell.name for spell in consumer.known_spells]

        base_spell_known = any(
            known_spell_name == self.unlock_name
            or (
                known_spell_name.startswith(self.unlock_name + " ")
                and known_spell_name[len(self.unlock_name):].strip() in ["II", "III", "IV", "V"]
            )
            for known_spell_name in spell_names
        )

        if not base_spell_known:
            required_skill = getattr(self.parent, "school", "arcana")
            required_level = int(getattr(self.parent, "identification_level", 0) or 0)
            current_level = int(consumer.level.traits.get(required_skill, {}).get("level", 1) or 1)

            if current_level < required_level:
                self.engine.message_log.add_message(
                    f"You fail to understand the tome ({required_skill} {required_level})",
                    color.impossible,
                )
                return

            consumer.known_spells.append(spell_class())
            consumer.level.add_xp({'arcana': 50})
            consumer.level.add_xp({school: 25})

            self.engine.message_log.add_message(
                f"You read the tome, and understand the secrets of {self.unlock_name}!",
                color.status_effect_applied,
            )
            self.consume()
        else:
            consumer.mana = min(consumer.mana_max, consumer.mana + 10)
            consumer.level.add_xp({'arcana': 10})
            consumer.level.add_xp({school: 5})
            self.engine.message_log.add_message(
                f"You already understand the secrets of {self.unlock_name}. Your mana is replenished.",
                color.status_effect_applied,
            )
            self.consume()
        

class DarkvisionConsumable(Consumable):
    def __init__(self, duration: int):
        self.duration = duration

    def activate(self, action: actions.ItemAction) -> None:
        consumer = action.entity
        
        darkvision = effect.DarkvisionEffect(duration=self.duration)
        sounds.play_darkvision_sound()
        self.engine.message_log.add_message(
            "Your vision sharpens as darkness recedes!", color.dark_purple
        )
        consumer.add_effect(darkvision)
        self.consume()
        
class LightningConsumable(Consumable):
    def __init__(self, damage: int, maximum_range: int):
        self.damage = damage
        self.maximum_range = maximum_range

    def activate(self, action: actions.ItemAction) -> None:

        consumer = action.entity
        target = None
        closest_distance = self.maximum_range + 1.0

        for actor in self.engine.game_map.actors:
            if actor is not consumer and self.parent.gamemap.visible[actor.x, actor.y]:
                distance = consumer.distance(actor.x, actor.y)
                if distance < closest_distance:
                    target = actor
                    closest_distance = distance

        if target:

            # Animation queuer

            path = list(tcod.los.bresenham((consumer.x, consumer.y), (target.x, target.y)).tolist())

            self.engine.animation_queue.append(LightningAnimation(path))
            
            # Use centralized damage calculation for consumable items
            from components.damage_types import DamageType
            final_damage, _, was_fully_resisted = actions.calculate_damage(
                attacker=consumer,
                target=target,
                base_damage=self.damage,
                attack_type="spell",
                damage_type=DamageType.NONE,
                damage_modifier=1.0,
                hit_part=None,
                proficiency_profile=None,
                armor_tags=None,
            )

            if was_fully_resisted:
                self.engine.message_log.add_message(
                    f"A lightning bolt strikes the {target.name}, but the attack is completely resisted!",
                    color.light_blue
                )
            else:
                self.engine.message_log.add_message(
                    f"A lightning bolt strikes the {target.name} for {final_damage} damage!"
                )
            
            target.fighter.take_damage(final_damage)
            self.consume()
            sounds.lightning_sound.play()
        else:

            raise Impossible("No enemy is close enough to strike!") 
        
class FireballConsumable(Consumable):
    def __init__(self, damage: int, radius: int):
        self.damage = damage
        self.radius = radius

    def get_action(self, consumer: Actor) -> AreaRangedAttackHandler:
        self.engine.message_log.add_message(
            "Select target location.", color.needs_target
        )
        return AreaRangedAttackHandler(
            self.engine,
            radius=self.radius,
            callback=lambda xy: actions.ItemAction(consumer, self.parent, xy),
        )
    
    def activate(self, action: actions.ItemAction) -> None:
        target_xy = action.target_xy

        if not self.engine.game_map.visible[target_xy]:
            raise Impossible("You cannot target an area you cannot see!")
        
        targets_hit = False
        for actor in self.engine.game_map.actors:
            if actor.distance(*target_xy) <= self.radius:
                # Use centralized damage calculation for consumable items
                from components.damage_types import DamageType
                final_damage, _, was_fully_resisted = actions.calculate_damage(
                    attacker=action.entity,
                    target=actor,
                    base_damage=self.damage,
                    attack_type="spell",
                    damage_type=DamageType.FIRE,
                    damage_modifier=1.0,
                    hit_part=None,
                    proficiency_profile=None,
                    armor_tags=None,
                )
                
                if was_fully_resisted:
                    self.engine.message_log.add_message(
                        f"The {actor.name} completely resists the flames!",
                        color.light_blue
                    )
                else:
                    self.engine.message_log.add_message(
                        f"The {actor.name} is engulfed in an explosion, taking {final_damage} damage!"
                    )
                actor.fighter.take_damage(final_damage)
                targets_hit = True

        if not targets_hit:
            raise Impossible("There are no targets in the radius")
        
        self.consume()
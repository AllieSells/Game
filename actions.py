from __future__ import annotations

from typing import Optional, Tuple, TYPE_CHECKING
import random

import color
import exceptions
import copy 

if TYPE_CHECKING:
    from engine import Engine
    from entity import Actor, Entity, Item
    from components.body_parts import BodyPartType
    from components.spells import Spell
else:
    # Runtime import for BodyPartType if needed
    try:
        from components.body_parts import BodyPartType
    except ImportError:
        BodyPartType = None


import sounds
import sprite_manager
import gpu_stack
from balance_config import (
    AGILITY_HIT_BONUS_CAP,
    AGILITY_HIT_BONUS_PER_LEVEL,
    AGILITY_RANGED_DAMAGE_PER_LEVEL,
    ARROW_HIT_RECOVERY_CHANCE,
    ARROW_OBSTACLE_BREAK_CHANCE,
    BOW_DEFAULT_MAX_RANGE,
    MAX_HIT_CHANCE,
    MELEE_BASE_HIT,
    MIN_HIT_CHANCE,
    RANGED_BASE_HIT,
    SPELL_FIZZLE_MANA_REFUND_FRACTION,
    STRENGTH_MELEE_DAMAGE_PER_LEVEL,
    trait_delta,
)
import proficiency_system as profsys


def _resolve_ammo_type(item) -> str:
    """Return a stable ammo type key for a projectile item."""
    if item is None:
        return "arrow"

    explicit = str(getattr(item, "ammo_type", "") or "").strip().lower()
    if explicit:
        return explicit

    tags = {str(tag).strip().lower() for tag in getattr(item, "tags", []) or []}
    for tag in tags:
        if tag.startswith("ammo_type:"):
            return tag.split(":", 1)[1] or "arrow"
        if tag.startswith("arrow_type:"):
            return tag.split(":", 1)[1] or "arrow"

    name = str(getattr(item, "name", "") or "").strip().lower()
    if " " in name:
        return name.split(" ", 1)[0]
    return "arrow"


def _ensure_quiver_ammo_state(quiver_item) -> tuple[dict, str]:
    """Ensure quiver has multi-ammo state, preserving legacy arrow_count data."""
    counts = getattr(quiver_item, "ammo_counts", None)
    if not isinstance(counts, dict):
        legacy_count = int(getattr(quiver_item, "arrow_count", 0) or 0)
        counts = {"arrow": legacy_count} if legacy_count > 0 else {}
        quiver_item.ammo_counts = counts

    selected = str(getattr(quiver_item, "selected_ammo_type", "") or "").strip().lower()
    if not selected:
        selected = next((k for k, v in counts.items() if int(v or 0) > 0), "arrow")
        quiver_item.selected_ammo_type = selected

    total = sum(max(0, int(v or 0)) for v in counts.values())
    quiver_item.arrow_count = total  # Keep legacy field in sync for compatibility.

    return counts, selected


def _ensure_quiver_ammo_templates(quiver_item) -> dict:
    """Ensure quiver tracks projectile templates per ammo type."""
    templates = getattr(quiver_item, "ammo_templates", None)
    if not isinstance(templates, dict):
        templates = {}
        quiver_item.ammo_templates = templates
    return templates


def _get_factory_projectile_template(ammo_type: str):
    """Try to resolve an ammo template from entity_factories by ammo type."""
    ammo_type = str(ammo_type or "").strip().lower()
    if not ammo_type:
        return None

    try:
        import entity_factories as ef
    except Exception:
        return None

    candidates = [
        f"{ammo_type}_arrow",
        f"{ammo_type}_bolt",
        f"{ammo_type}_projectile",
    ]
    for attr in candidates:
        item = getattr(ef, attr, None)
        if item is not None:
            return item
    return None


def _get_quiver_total_count(quiver_item) -> int:
    if quiver_item is None:
        return 0
    counts = getattr(quiver_item, "ammo_counts", None)
    if isinstance(counts, dict):
        return sum(max(0, int(v or 0)) for v in counts.values())
    return int(getattr(quiver_item, "arrow_count", 0) or 0)
# Body part targeting modifiers (damage_modifier, hit_difficulty_modifier)
# hit_difficulty_modifier: Positive = easier to hit, negative = harder to hit


# Body parts affect damage only; hit chance is resolved separately.
BODY_PART_MODIFIERS = {
    "HEAD":  (1.5,  0),
    "NECK":  (1.5,  0),
    "TORSO": (1.0,  0),
    "LEG":   (0.9,  0),
    "ARM":   (0.9,  0),
    "HAND":  (0.75, 0),
    "FOOT":  (0.75, 0),
    "TAIL":  (0.8,  0),
}

# Base hit chances (0.0–1.0), centralized in balance_config.
BASE_HIT = MELEE_BASE_HIT
BASE_HIT_RANGED = RANGED_BASE_HIT

# Weighted likelihood of hitting each zone (higher = hit more often)
BODY_PART_WEIGHTS = {
    "TORSO": 50,
    "LEG":   15,
    "ARM":   15,
    "HEAD":  10,
    "TAIL":   5,
    "HAND":   3,
    "FOOT":   3,
    "NECK":   2,
}


def get_weighted_part_selection(body_parts):
    """Select a random, non-destroyed body part using BODY_PART_WEIGHTS."""
    parts, weights = [], []
    for part in body_parts.body_parts.values():
        if not part.is_destroyed:
            parts.append(part)
            weights.append(BODY_PART_WEIGHTS.get(part.part_type.name, 10))
    if not parts:
        return None
    return random.choices(parts, weights=weights, k=1)[0]


def get_part_from_tile_position(body_parts, tile_rel_x: float, tile_rel_y: float):
    """Map a normalised cursor position within a tile (0.0–1.0) to a body part.

    tile_rel_y=0.0 is the top of the tile (head); 1.0 is the bottom (feet).
    Returns a BodyPart instance, or None if nothing is available.
    """
    available = {
        pt: part for pt, part in body_parts.body_parts.items()
        if not part.is_destroyed
    }
    if not available:
        return None

    if tile_rel_y < 0.2:
        preferred = ["NECK", "HEAD"]
    elif tile_rel_y < 0.4:
        preferred = ["HEAD", "ARM"]
    elif tile_rel_y < 0.6:
        preferred = ["TORSO", "ARM"]
    elif tile_rel_y < 0.8:
        preferred = ["LEG", "HAND"]
    else:
        preferred = ["FOOT", "LEG"]

    for pref in preferred:
        for pt, part in available.items():
            if pref in pt.name:
                return part

    return get_weighted_part_selection(body_parts)


def _get_part_modifiers(part_type_name: str) -> tuple:
    """Return (damage_modifier, 0) for a body part type name."""
    if part_type_name in BODY_PART_MODIFIERS:
        return BODY_PART_MODIFIERS[part_type_name]
    for key, val in BODY_PART_MODIFIERS.items():
        if key in part_type_name:
            return val
    return (1.0, 0)


def _resolve_hit_part(target, target_part):
    """Return (hit_part, target_part, damage_mod) after resolving body part targeting.

    Body part selection uses BODY_PART_WEIGHTS when no explicit target_part is given.
    """
    damage_modifier = 1.0
    hit_part = None

    body_parts = getattr(target, 'body_parts', None)
    if not body_parts:
        return None, target_part, damage_modifier

    if not target_part:
        rp = get_weighted_part_selection(body_parts)
        target_part = rp.part_type if rp else None

    if target_part:
        hit_part = body_parts.body_parts.get(target_part)
        if hit_part and not hit_part.is_destroyed:
            damage_modifier, _ = _get_part_modifiers(hit_part.part_type.name)
        else:
            # Requested part is gone – fall back to weighted random
            rp = get_weighted_part_selection(body_parts)
            if rp:
                target_part = rp.part_type
                hit_part = rp
                if hit_part and not hit_part.is_destroyed:
                    damage_modifier, _ = _get_part_modifiers(hit_part.part_type.name)

    return hit_part, target_part, damage_modifier


def _get_trait_level(actor: Actor, trait_name: str) -> int:
    try:
        return int(actor.level.traits.get(trait_name, {}).get("level", 1) or 1)
    except Exception:
        return 1


def _get_agility_hit_modifier(attacker: Actor, defender: Actor) -> float:
    atk_agi = _get_trait_level(attacker, "agility")
    def_agi = _get_trait_level(defender, "agility")
    delta = atk_agi - def_agi
    return max(-AGILITY_HIT_BONUS_CAP, min(AGILITY_HIT_BONUS_CAP, delta * AGILITY_HIT_BONUS_PER_LEVEL))


def _collect_equipped_weapons(attacker: Actor) -> list:
    weapons = []
    eq = getattr(attacker, "equipment", None)
    if not eq:
        return weapons

    weapon_type_names = {"WEAPON", "RANGED"}

    for item in eq.body_part_coverage.values():
        if (
            item
            and getattr(item, "equippable", None)
            and getattr(item.equippable, "equipment_type", None)
            and item.equippable.equipment_type.name in weapon_type_names
        ):
            weapons.append(item)

    if not weapons:
        for eq_type, item in eq.equipped_items.items():
            if item and eq_type in weapon_type_names:
                weapons.append(item)

    return weapons


def _item_tags(item: Item) -> set[str]:
    tags = set(getattr(item, "tags", []) or [])

    # Legacy save compatibility: older shortsword definitions used the
    # "light weapon" tag, which maps partially to dagger XP.
    # Normalize sword-like items so melee profile/XP route to sword traits.
    item_name = str(getattr(item, "name", "") or "").lower()
    if "sword" in item_name:
        tags.add("sword")
        tags.discard("light weapon")

    eq = getattr(item, "equippable", None)
    if eq is not None:
        tags.update(set(getattr(eq, "required_tags", set()) or set()))
    return tags


def _weapon_proficiency_profile(attacker: Actor, equipped_weapons: list) -> profsys.ProficiencyResult:
    tags: set[str] = set()
    for weapon in equipped_weapons:
        tags.update(_item_tags(weapon))
    return profsys.weapon_profile(attacker, tags)


def _weapon_xp_traits_from_items(equipped_weapons: list) -> set[str]:
    tags: set[str] = set()
    for weapon in equipped_weapons:
        tags.update(_item_tags(weapon))
    return profsys.weapon_traits_for_tags(tags)


def _armor_xp_traits_from_tags(armor_tags: list) -> set[str]:
    return profsys.armor_traits_for_tags(armor_tags)


def _armor_affinity_multiplier(defender: Actor, armor_tags: list) -> float:
    return profsys.armor_profile(defender, armor_tags).mitigation_multiplier


def _effective_dodge_chance(defender: Actor, local_armor_tags: list | None = None) -> float:
    base_dodge = float(getattr(defender, "dodge_chance", 0.0) or 0.0)
    agility_bonus = profsys.agility_dodge_bonus(defender)

    armor_tags = set(local_armor_tags or [])
    if getattr(defender, "equipment", None):
        try:
            armor_tags.update(defender.equipment.get_all_armor_tags())
        except Exception:
            pass

    armor_profile = profsys.armor_profile(defender, armor_tags)
    return max(0.0, min(0.95, base_dodge + agility_bonus + armor_profile.dodge_delta))


def _break_invisibility(actor: Actor) -> None:
    """Remove active invisibility effects from an actor."""
    effects = list(getattr(actor, "effects", []) or [])
    if not effects:
        return

    remaining = [
        e for e in effects
        if str(getattr(e, "name", "")).strip().lower() not in {"invisible", "invisibility"}
    ]
    if len(remaining) != len(effects):
        actor.effects = remaining

class Action:
    def __init__(self, entity: Actor) -> None:
        super().__init__()
        self.entity = entity

    @property
    def engine(self) -> Engine:
        return self.entity.gamemap.engine
    
    def perform(self) -> None:
        """Perform this action with the objects needed to determine its scope.
        
        `self.engine` is the scope this action is being performed in.

        `self.entity` is the object performing the action.

        This method must be overridden by Action subclasses.
        """
        raise NotImplementedError()

class InteractAction(Action):
    # Handles 
    def __init__(self, entity: Actor, dx: int = 0, dy: int = 0):
        super().__init__(entity)
        self.dx = dx
        self.dy = dy

    def perform(self):
        actor_location_x = self.entity.x
        actor_location_y = self.entity.y

        target_x = actor_location_x + self.dx
        target_y = actor_location_y + self.dy

        # Check for chest entity at the target location
        for ent in self.engine.game_map.entities:
            if hasattr(ent, "container") and ent.container and (
                ent.x == target_x and ent.y == target_y
            ):
                # Container found at target location
                container = ent.container
                is_corpse = getattr(ent, "type", None) == "Dead"
                
                if len(container.items) == 0 and is_corpse:
                    empty_msg = "There is nothing left to loot."
                    raise exceptions.Impossible(empty_msg)
                else:
                    # Send to input handler to display contents
                    if not is_corpse:
                        sounds.play_chest_open_sound()
                    from inventory_ui import ContainerGridUI
                    return ContainerGridUI(self.engine, container)

        # Check for a campfire or bonfire item at the target location → cooking UI
        for ent in self.engine.game_map.entities:
            if (getattr(ent, "name", None) in ("Campfire", "Bonfire")
                    and ent.x == target_x and ent.y == target_y):
                from inventory_ui import CookingUI
                return CookingUI(self.engine)
        tile = self.engine.game_map.tiles["interactable"][target_x, target_y]    
        if tile:
            import tile_types
            # Get name for that tile
            name = self.engine.game_map.tiles["name"][target_x, target_y]

            # If it's a door, toggle open/closed state
            if name == "Door":
                # Convert "Door" tile to "Open Door" tile
                self.engine.game_map.tiles[target_x, target_y] = tile_types.open_door
                sounds.play_door_open_sound_at(target_x, target_y, self.engine.player, self.engine.game_map)
                self.engine.message_log.add_message("You open the door.")

            elif name == "Open Door":
                # Convert "Open Door" tile to "Door" tile
                self.engine.game_map.tiles[target_x, target_y] = tile_types.closed_door
                sounds.play_door_close_sound_at(target_x, target_y, self.engine.player, self.engine.game_map)
                self.engine.message_log.add_message("You close the door.")

            elif name == "Locked Door":
                key_item = next(
                    (item for item in self.entity.inventory.items if item.name == "Dungeon Key"),
                    None
                )
                if key_item:
                    self.engine.game_map.tiles[target_x, target_y] = tile_types.dungeon_exit
                    self.entity.inventory.items.remove(key_item)
                    sounds.play_door_open_sound_at(target_x, target_y, self.engine.player, self.engine.game_map)
                    self.engine.message_log.add_message("You unlock the door.")
                else:
                    self.engine.message_log.add_message("The door won't budge.")

            else:
                self.engine.message_log.add_message("There is nothing to interact with.")
        elif self.engine.game_map.get_actor_at_location(target_x, target_y):
            self.engine.debug_log(f"Interacting with actor at {target_x}, {target_y}", handler=type(self).__name__, event="perform")
            npc = self.engine.game_map.get_actor_at_location(target_x, target_y)
            if npc and hasattr(npc, "ai") and getattr(npc.ai, "type", None) == "Friendly":
                # Import here to avoid circular imports
                from input_handlers import DialogueEventHandler
                return DialogueEventHandler(self.engine, npc)
            else:
                self.engine.message_log.add_message("They don't seem interested in talking.")
        else:
            self.engine.message_log.add_message("There is nothing to interact with.")


class PickupAction(Action):
    #pick up item and put in inventory IF ROOM

    def __init__(self, entity: Actor):
        super().__init__(entity)

    @staticmethod
    def _is_arrow_item(item) -> bool:
        if not item:
            return False
        item_tags = {tag.lower() for tag in getattr(item, "tags", [])}
        eq_type_name = None
        if hasattr(item, "equippable") and item.equippable:
            eq_type_name = item.equippable.equipment_type.name
        if eq_type_name == "BACKPACK" or "quiver" in item_tags:
            return False
        return (
            eq_type_name == "PROJECTILE"
            or "arrow" in item_tags
            or "ammunition" in item_tags
            or "ammo" in item_tags
        )

    def _get_equipped_quiver(self):
        equipment = getattr(self.entity, "equipment", None)
        if not equipment:
            return None
        if hasattr(equipment, "get_equipped_quiver"):
            return equipment.get_equipped_quiver()
        return None

    def _collect_ammo_from_tile_items(self, tile_items: list) -> int:
        """Collect ammo-tagged items from tile, preferring quiver storage.

        Returns number of ammo items collected/absorbed.
        """
        inventory = self.entity.inventory
        quiver_item = self._get_equipped_quiver()
        ammo_items = [item for item in tile_items if self._is_arrow_item(item)]
        if not ammo_items:
            return 0

        absorbed_count = 0
        absorbed_by_type = {}
        moved_to_inventory = 0
        first_ammo_item = ammo_items[0]

        if quiver_item is not None:
            ammo_counts, selected_type = _ensure_quiver_ammo_state(quiver_item)
            ammo_templates = _ensure_quiver_ammo_templates(quiver_item)
            current = _get_quiver_total_count(quiver_item)
            capacity = int(getattr(quiver_item, "arrow_capacity", 0) or 0)
            remaining = []

            for item in ammo_items:
                if capacity > current:
                    ammo_type = _resolve_ammo_type(item)
                    try:
                        self.engine.game_map.entities.remove(item)
                    except Exception:
                        pass
                    ammo_counts[ammo_type] = int(ammo_counts.get(ammo_type, 0) or 0) + 1
                    # Keep a representative item template so firing preserves ammo variant.
                    if ammo_type not in ammo_templates:
                        try:
                            ammo_templates[ammo_type] = copy.deepcopy(item)
                        except Exception:
                            pass
                    absorbed_count += 1
                    absorbed_by_type[ammo_type] = absorbed_by_type.get(ammo_type, 0) + 1
                    current += 1
                else:
                    remaining.append(item)

            if selected_type not in ammo_counts or int(ammo_counts.get(selected_type, 0) or 0) <= 0:
                quiver_item.selected_ammo_type = next(
                    (k for k, v in ammo_counts.items() if int(v or 0) > 0),
                    selected_type,
                )
            quiver_item.arrow_count = current
            ammo_items = remaining

        for item in ammo_items:
            if not inventory.can_carry(item):
                break
            self.engine.game_map.entities.remove(item)
            item.parent = self.entity.inventory
            inventory.items.append(item)
            moved_to_inventory += 1

        moved_total = absorbed_count + moved_to_inventory
        if moved_total <= 0:
            return 0

        if first_ammo_item and hasattr(first_ammo_item, "pickup_sound") and first_ammo_item.pickup_sound is not None:
            try:
                first_ammo_item.pickup_sound()
            except Exception as e:
                self.engine.debug_log(
                    f"Error calling pickup sound: {e}",
                    handler=type(self).__name__,
                    event="perform",
                )

        if quiver_item is not None and absorbed_count > 0:
            current = _get_quiver_total_count(quiver_item)
            capacity = int(getattr(quiver_item, "arrow_capacity", 0) or 0)
            selected_type = str(getattr(quiver_item, "selected_ammo_type", "arrow") or "arrow")
            if moved_to_inventory > 0:
                self.engine.message_log.add_message(
                    f"You stash {absorbed_count} ammo in your quiver ({current}/{capacity}, using {selected_type}) and collect {moved_to_inventory} ammo item(s)."
                )
            else:
                self.engine.message_log.add_message(
                    f"You stash {absorbed_count} ammo in your quiver ({current}/{capacity}, using {selected_type})."
                )
        else:
            self.engine.message_log.add_message(f"You collect {moved_total} ammo item(s).")

        return moved_total

    def _collect_ammo_at_current_position(self) -> int:
        actor_location_x = self.entity.x
        actor_location_y = self.entity.y
        tile_items = [
            item
            for item in self.engine.game_map.items
            if actor_location_x == item.x and actor_location_y == item.y
        ]
        return self._collect_ammo_from_tile_items(tile_items)

    def perform(self) -> None:
        actor_location_x = self.entity.x
        actor_location_y = self.entity.y
        inventory = self.entity.inventory

        tile_items = [
            item
            for item in self.engine.game_map.items
            if actor_location_x == item.x and actor_location_y == item.y
        ]

        if not tile_items:
            raise exceptions.Impossible("There is nothing here to pick up.")

        moved_ammo = self._collect_ammo_from_tile_items(tile_items)
        if moved_ammo > 0:
            tile_items = [
                item
                for item in self.engine.game_map.items
                if actor_location_x == item.x and actor_location_y == item.y
            ]
            if not tile_items:
                return

        for item in tile_items:
            if not inventory.can_carry(item):
                raise exceptions.Impossible("You are carrying too much to pick that up.")

            if item.name == "Bonfire":
                raise exceptions.Impossible("The bonfire is too hot to handle!")

            if "coin" in item.name.lower():
                self.engine.player.gold += item.value
                self.engine.game_map.entities.remove(item)
                self.engine.message_log.add_message("You pick up some coins.", color.yellow)
                if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                    try:
                        item.pickup_sound()
                    except Exception as e:
                        self.engine.debug_log(
                            f"Error calling coin pickup sound: {e}",
                            handler=type(self).__name__,
                            event="perform",
                        )
                return

            self.engine.game_map.entities.remove(item)
            item.parent = self.entity.inventory
            inventory.items.append(item)

            try:
                from entity_factories import torch
            except Exception:
                torch = None

            if item.name == "Campfire" and torch is not None:
                inventory.items.pop()
                new_torch = copy.deepcopy(torch)
                new_torch.parent = self.entity.inventory
                inventory.items.append(new_torch)
                sounds.play_torch_pull_sound()
                self.engine.message_log.add_message("You pull a burning log from the fire")
                return

            if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                try:
                    item.pickup_sound()
                except Exception as e:
                    self.engine.debug_log(
                        f"Error calling pickup sound: {e}",
                        handler=type(self).__name__,
                        event="perform",
                    )

            self.engine.message_log.add_message(f"You picked up the {item.name}!")
            return

        raise exceptions.Impossible("There is nothing here to pick up.")

class CastSpellAction(Action):
    def __init__(self, entity: Actor, target: Optional[Actor] = None):
        super().__init__(entity)
        self.target = target

    def perform(self) -> None:
        known_spells = list(getattr(self.entity, "known_spells", []) or [])
        if not known_spells:
            return WaitAction(self.entity).perform()

        current_mana = int(getattr(self.entity, "mana", 0) or 0)
        castable_spells = [
            spell for spell in known_spells
            if current_mana >= int(getattr(spell, "mana_cost", 0) or 0)
        ]
        if not castable_spells:
            return WaitAction(self.entity).perform()

        # Prefer direct-damage spells for hostile casters.
        damage_spells = [
            spell for spell in castable_spells
            if int(getattr(spell, "damage", 0) or 0) > 0
        ]
        chosen_spell = random.choice(damage_spells or castable_spells)

        if self.target is not None:
            target_xy = (self.target.x, self.target.y)
        else:
            target_xy = (self.entity.x, self.entity.y)

        return SpellAction(self.entity, chosen_spell, target_xy).perform()


class SpellAction(Action):
    def __init__(self, entity: Actor, spell: Spell, target_xy: Optional[Tuple[int, int]] = None):
        super().__init__(entity)
        self.spell = spell
        if not target_xy:
            target_xy = entity.x, entity.y
        self.target_xy = target_xy


    @property
    def target_actor(self) -> Optional[Actor]:
        # Returns actor at this actions destination
        return self.engine.game_map.get_actor_at_location(*self.target_xy)
    
    def perform(self) -> None:
        _break_invisibility(self.entity)
        cast_profile = profsys.spell_profile(self.entity, getattr(self.spell, "school", ""))
        if random.random() > cast_profile.success_chance:
            mana_cost = int(getattr(self.spell, "mana_cost", 0) or 0)
            mana_spent = int(round(mana_cost * (1.0 - SPELL_FIZZLE_MANA_REFUND_FRACTION)))
            if mana_spent > 0 and hasattr(self.entity, "mana"):
                self.entity.mana = max(0, int(self.entity.mana) - mana_spent)
            sounds.play_fizzle_sound()
            self.engine.message_log.add_message(
                f"{self.entity.name.capitalize()} loses concentration and the spell fizzles!",
                color.dark_gray,
            )
            return

        # Activate the spell after proficiency checks.
        self.spell.activate(self)

class ItemAction(Action):
    def __init__(
            self, entity: Actor, item: Item, target_xy: Optional[Tuple[int, int]] = None
    ):
        super().__init__(entity)
        self.item = item
        if not target_xy:
            target_xy = entity.x, entity.y
        self.target_xy = target_xy

    @property
    def target_actor(self) -> Optional[Actor]:
        # Returns actor at this actions destination
        return self.engine.game_map.get_actor_at_location(*self.target_xy)
    
    def perform(self) -> None:
        # Invoke item, action will be given context
        if self.item.consumable:
            self.item.consumable.activate(self)


class DropItem(ItemAction):
    def perform(self) -> None:
        if self.entity.equipment.item_is_equipped(self.item):
            self.entity.equipment.toggle_equip(self.item)
        
        self.entity.inventory.drop(self.item) 
class OpenAction(Action):
    def perform(self) -> None:
        # Open a container (chest) on the map and present its contents to the player.
        actor_location_x = self.entity.x
        actor_location_y = self.entity.y
        # Check for chest entity adjacent to player
        for ent in self.engine.game_map.entities:
            if hasattr(ent, "container") and ent.container and (
                abs(ent.x - actor_location_x) <= 1 and abs(ent.y - actor_location_y) <= 1
            ):
                # Container found
                container = ent.container
                is_corpse = getattr(ent, "type", None) == "Dead"
                
                if len(container.items) == 0:
                    empty_msg = "There is nothing left to loot." if is_corpse else "The chest is empty."
                    raise exceptions.Impossible(empty_msg)
                else:
                    # Send to input handler to display contents
                    if not is_corpse:
                        sounds.play_chest_open_sound()
                    from inventory_ui import ContainerGridUI
                    return ContainerGridUI(self.engine, container)
        raise exceptions.Impossible("Nothing nearby to open.")
class EquipAction(Action):
    def __init__(self, entity: Actor, item: Item):
        super().__init__(entity)

        self.item = item

    def perform(self) -> None:
        self.entity.equipment.toggle_equip(self.item)

class WaitAction(Action):
    def perform(self) -> None:
        pass

class TakeStairsAction(Action):
    def perform(self) -> None:
        # Take the stairs, if they exist at its location
        pos = (self.entity.x, self.entity.y)
        gm = self.engine.game_map
        gw = self.engine.game_world
        print(f"[STAIRS] pos={pos} map_type={gm.type} floor={gw.current_floor} "
              f"down={getattr(gm,'downstairs_location',None)} "
              f"up={getattr(gm,'upstairs_location',None)} "
              f"up_stack={len(gw.up_stack)} down_stack={len(gw.down_stack)}")

        # Overworld dungeon entrance — descend into the linked dungeon
        if gm.type == "overworld":
            entrances = getattr(gm, "dungeon_entrances", {})
            if pos in entrances:
                # Restore last dungeon minimap state when entering a level
                self.engine.show_minimap = getattr(self.engine, '_dungeon_minimap_state', 2)
                gw.descend()
                sounds.stairs_sound.play()
                import sprite_manager as _sm

                _sm.refresh_actor_sprite(self.entity)
                self.engine.message_log.add_message("You descend into the dungeon.", color.descend)
                return
            raise exceptions.Impossible("There is no dungeon entrance here.")

        # Descend if on the downstairs tile
        if pos == gm.downstairs_location:
            print(f"[STAIRS] Descending from floor {gw.current_floor}")
            try:
                gw.descend()
                print(f"[STAIRS] Now on floor {gw.current_floor}, map={self.engine.game_map}")
            except Exception as _e:
                import traceback as _tb
                print(f"[STAIRS] descend() raised: {_e}")
                _tb.print_exc()
                raise
            sounds.stairs_sound.play()
            self.engine.message_log.add_message("You descend the staircase.", color.descend)
            return

        # Ascend if on an upstairs tile
        if hasattr(gm, "upstairs_location") and pos == gm.upstairs_location:
            print(f"[STAIRS] Ascending from floor {gw.current_floor}")
            # Call ascend on the GameWorld if available; if not, try map-level ascend
            try:
                gw.ascend()
                print(f"[STAIRS] Now on floor {gw.current_floor}, map={self.engine.game_map}")
                sounds.stairs_sound.play()
                # If we ascended back to the overworld, save dungeon state and hide minimap
                if getattr(self.engine.game_map, 'type', '') == 'overworld':
                    self.engine._dungeon_minimap_state = getattr(self.engine, 'show_minimap', 2)
                    self.engine.show_minimap = 3
                self.engine.message_log.add_message("You ascend the staircase.", color.ascend)
                return
            except Exception as _e:
                import traceback as _tb
                print(f"[STAIRS] ascend() raised: {_e}")
                _tb.print_exc()
                try:
                    # Some older code may expect engine.game_map.ascend
                    self.engine.game_map.ascend()
                    self.engine.message_log.add_message("You ascend the staircase.", color.ascend)
                    return
                except Exception as _e2:
                    print(f"[STAIRS] fallback ascend() raised: {_e2}")

        print(f"[STAIRS] No matching stair found at {pos}. tile_name={str(gm.tiles['name'][pos[0],pos[1]])}")
        raise exceptions.Impossible("There are no stairs here.")

class ActionWithDirection(Action):
    def __init__(self, entity: Actor, dx: int, dy: int):
        super().__init__(entity)
        
        self.dx = dx
        self.dy = dy

    @property # destination
    def dest_xy(self) -> Tuple[int, int]:
        """Return the destination coordinates after this action."""
        return self.entity.x + self.dx, self.entity.y + self.dy

    @property # is blocking?
    def blocking_entity(self) -> Optional[Entity]:
        """Return the blocking entity at this action's destination."""
        return self.engine.game_map.get_blocking_entity_at_location(*self.dest_xy)
    
    @property
    def target_location(self) -> Tuple[int, int]:
        """Return the target location coordinates for this action."""
        return self.dest_xy

    @property
    def target_actor(self) -> Optional[Actor]:
        #Return the actor at actions dest.
        return self.engine.game_map.get_actor_at_location(*self.dest_xy)

    def perform(self) -> None:
        raise NotImplementedError()
    
class RangedAction(ActionWithDirection):
    """Directional ranged attack that can target a specific body part."""

    def __init__(
        self,
        entity: Actor,
        dx: int,
        dy: int,
        target_part: Optional['BodyPartType'] = None,
        tile_rel_pos: Optional[Tuple[float, float]] = None,
        target_xy: Optional[Tuple[int, int]] = None,
    ):
        super().__init__(entity, dx, dy)
        self.target_part = target_part
        self.tile_rel_pos = tile_rel_pos  # normalised (x, y) within target tile, 0.0–1.0
        self.target_xy = target_xy

    @staticmethod
    def _is_projectile_ammo_item(item) -> bool:
        if not item or not hasattr(item, "equippable") or not item.equippable:
            return False
        eq_type_name = item.equippable.equipment_type.name
        item_tags = {tag.lower() for tag in getattr(item, "tags", [])}
        if eq_type_name == "BACKPACK" or "quiver" in item_tags:
            return False
        return eq_type_name == "PROJECTILE" or "arrow" in item_tags or "ammunition" in item_tags or "ammo" in item_tags

    def _get_quiver_projectile_template(self, quiver_item, preferred_type: str):
        """Get a representative projectile item for visuals/damage from inventory/equipment."""
        templates = _ensure_quiver_ammo_templates(quiver_item)
        preferred_type = str(preferred_type or "").strip().lower()

        tpl = templates.get(preferred_type)
        if tpl is not None:
            return tpl

        factory_tpl = _get_factory_projectile_template(preferred_type)
        if factory_tpl is not None:
            try:
                templates[preferred_type] = copy.deepcopy(factory_tpl)
                return templates[preferred_type]
            except Exception:
                return factory_tpl

        for key, value in templates.items():
            if int(getattr(quiver_item, "ammo_counts", {}).get(key, 0) or 0) > 0 and value is not None:
                return value

        candidates = []
        equipment = getattr(self.entity, "equipment", None)
        inventory = getattr(self.entity, "inventory", None)

        if equipment:
            candidates.extend([item for item in equipment.grasped_items.values() if item])
            candidates.extend([item for item in equipment.equipped_items.values() if item])
        if inventory:
            candidates.extend(list(inventory.items))

        fallback = None
        for item in candidates:
            if not self._is_projectile_ammo_item(item):
                continue
            ammo_type = _resolve_ammo_type(item)
            if ammo_type == preferred_type:
                return item
            if fallback is None:
                fallback = item

        if fallback is not None:
            return fallback

        try:
            import entity_factories as ef
            return ef.arrow
        except Exception:
            return None

    def _get_ready_ranged_items(self):
        """Return currently readied bow and projectile items, if any."""
        bow_item = None
        projectile_item = None

        equipment = getattr(self.entity, "equipment", None)
        if not equipment:
            return None, None

        held_items = list(equipment.grasped_items.values()) + list(equipment.equipped_items.values())

        for item in held_items:
            if not item or not hasattr(item, "equippable") or not item.equippable:
                continue

            eq_type_name = item.equippable.equipment_type.name
            item_tags = {tag.lower() for tag in getattr(item, "tags", [])}

            if bow_item is None and (eq_type_name == "RANGED" or "bow" in item_tags):
                bow_item = item

            if projectile_item is None and self._is_projectile_ammo_item(item):
                projectile_item = item

            if bow_item and projectile_item:
                break

        # If a bow is readied but no projectile is equipped, allow firing from inventory ammo.
        if bow_item is not None and projectile_item is None:
            inventory = getattr(self.entity, "inventory", None)
            if inventory:
                for item in inventory.items:
                    if not item or not hasattr(item, "equippable") or not item.equippable:
                        continue

                    if self._is_projectile_ammo_item(item):
                        projectile_item = item
                        break

        return bow_item, projectile_item

    def _get_equipped_quiver(self):
        equipment = getattr(self.entity, "equipment", None)
        if not equipment:
            return None
        if hasattr(equipment, "get_equipped_quiver"):
            return equipment.get_equipped_quiver()
        return None

    def _find_target_in_line(self, max_range: int = 8) -> tuple[Optional[Actor], Optional[tuple[int, int]], str]:
        """Find the first actor hit by a shot in this direction or what stops the projectile.
        
        Returns:
            (target_actor, collision_pos, collision_type)
            - target_actor: The actor hit, or None if no actor hit
            - collision_pos: Position where projectile stopped (x, y) - last walkable tile before obstacle
            - collision_type: 'actor', 'obstacle', 'out_of_bounds', or 'max_range'
        """
        import tcod.los

        start = (self.entity.x, self.entity.y)
        if self.target_xy is not None:
            end = self.target_xy
        else:
            end = (self.entity.x + (self.dx * max_range), self.entity.y + (self.dy * max_range))

        line_points = list(tcod.los.bresenham(start, end).tolist())
        if len(line_points) <= 1:
            return None, start, 'max_range'

        # Skip the origin tile and clamp travel distance to range.
        travel_points = line_points[1:max_range + 1]

        x, y = start
        last_walkable_x, last_walkable_y = start

        for x, y in travel_points:

            # Check bounds first
            if not self.engine.game_map.in_bounds(x, y):
                return None, (last_walkable_x, last_walkable_y), 'out_of_bounds'

            # Check for actor at this position
            target = self.engine.game_map.get_actor_at_location(x, y)
            if target and target is not self.entity:
                if getattr(target, 'type', None) == 'Guide':
                    continue  # Projectile passes through the Guide
                return target, (x, y), 'actor'

            # Check if the tile is walkable - if not, projectile stops at last walkable position
            if not self.engine.game_map.tiles["walkable"][x, y]:
                return None, (last_walkable_x, last_walkable_y), 'obstacle'
            
            # Update last walkable position
            last_walkable_x, last_walkable_y = x, y

        # Reached max range without hitting anything
        return None, (x, y), 'max_range'

    def _consume_projectile(self, projectile_item, *, using_quiver: bool = False, quiver_item=None, shot_ammo_type: Optional[str] = None) -> None:
        if using_quiver and quiver_item is not None:
            ammo_counts, selected_type = _ensure_quiver_ammo_state(quiver_item)
            current = _get_quiver_total_count(quiver_item)
            if current <= 0:
                if self.entity is self.engine.player:
                    self.engine.message_log.add_message("Your quiver is empty.", color.yellow)
                return

            explicit_type = str(shot_ammo_type or "").strip().lower()
            use_type = explicit_type if explicit_type and int(ammo_counts.get(explicit_type, 0) or 0) > 0 else None
            if use_type is None:
                use_type = selected_type if int(ammo_counts.get(selected_type, 0) or 0) > 0 else None
            if use_type is None:
                use_type = next((k for k, v in ammo_counts.items() if int(v or 0) > 0), None)
            if use_type is None:
                if self.entity is self.engine.player:
                    self.engine.message_log.add_message("Your quiver is empty.", color.yellow)
                return

            ammo_counts[use_type] = max(0, int(ammo_counts.get(use_type, 0) or 0) - 1)
            quiver_item.selected_ammo_type = use_type
            quiver_item.arrow_count = _get_quiver_total_count(quiver_item)

            if self.entity is self.engine.player and quiver_item.arrow_count == 0:
                self.engine.message_log.add_message("You are out of arrows.", color.yellow)
            return

        equipment = getattr(self.entity, "equipment", None)
        inventory = getattr(self.entity, "inventory", None)

        original_hand_slot = None
        original_coverage_slot = None
        original_equipped_slot = None
        projectile_was_equipped = False

        if equipment:
            for hand_name, held_item in equipment.grasped_items.items():
                if held_item == projectile_item:
                    original_hand_slot = hand_name
                    projectile_was_equipped = True
                    break

            for part_name, covered_item in equipment.body_part_coverage.items():
                if covered_item == projectile_item:
                    original_coverage_slot = part_name
                    projectile_was_equipped = True
                    break

            if (
                original_hand_slot is None
                and hasattr(projectile_item, "equippable")
                and projectile_item.equippable
            ):
                eq_slot_name = projectile_item.equippable.equipment_type.name
                if equipment.equipped_items.get(eq_slot_name) == projectile_item:
                    original_equipped_slot = eq_slot_name
                    projectile_was_equipped = True

        if equipment and projectile_was_equipped:
            equipment.unequip_item(projectile_item, add_message=False)

        if inventory:
            inventory.delete(projectile_item)

        if not inventory:
            return

        # If this shot consumed ammo directly from inventory (not from equipped/readied
        # projectile slot), do not auto-equip a replacement arrow into a hand.
        if not projectile_was_equipped:
            if self.entity is self.engine.player:
                has_more_arrows = False
                for item in inventory.items:
                    if not item or not hasattr(item, "equippable") or not item.equippable:
                        continue
                    if self._is_projectile_ammo_item(item):
                        has_more_arrows = True
                        break
                if not has_more_arrows:
                    self.engine.message_log.add_message("You are out of arrows.", color.yellow)
            return

        if not equipment:
            return

        replacement_arrow = None
        for item in inventory.items:
            if item == projectile_item:
                continue
            if not hasattr(item, "equippable") or not item.equippable:
                continue

            if self._is_projectile_ammo_item(item) and not equipment.item_is_equipped(item):
                replacement_arrow = item
                break

        if not replacement_arrow:
            if self.entity is self.engine.player:
                self.engine.message_log.add_message("You are out of arrows.", color.yellow)
            return

        replacement_eq_type = None
        if getattr(replacement_arrow, "equippable", None):
            replacement_eq_type = replacement_arrow.equippable.equipment_type.name

        if original_hand_slot:
            equipment.grasped_items[original_hand_slot] = replacement_arrow
            if replacement_eq_type:
                equipment.equipped_items[replacement_eq_type] = replacement_arrow
            if original_coverage_slot:
                equipment.body_part_coverage[original_coverage_slot] = replacement_arrow
        elif original_equipped_slot:
            equipment.equipped_items[original_equipped_slot] = replacement_arrow
            if original_coverage_slot:
                equipment.body_part_coverage[original_coverage_slot] = replacement_arrow
        else:
            equipment.equip_item(replacement_arrow, add_message=False)

        if self.entity is self.engine.player:
            self.engine.message_log.add_message("You ready another arrow.", color.light_gray)

    def perform(self) -> None:
        _break_invisibility(self.entity)
        bow_item, projectile_item = self._get_ready_ranged_items()
        quiver_item = self._get_equipped_quiver()
        using_quiver = False
        shot_ammo_type = None

        if bow_item and quiver_item and _get_quiver_total_count(quiver_item) > 0:
            ammo_counts, selected_type = _ensure_quiver_ammo_state(quiver_item)
            if int(ammo_counts.get(selected_type, 0) or 0) > 0:
                shot_ammo_type = selected_type
            else:
                shot_ammo_type = next((k for k, v in ammo_counts.items() if int(v or 0) > 0), None)
            projectile_item = self._get_quiver_projectile_template(quiver_item, shot_ammo_type)
            using_quiver = projectile_item is not None

        if not bow_item or not projectile_item:
            if bow_item and quiver_item and _get_quiver_total_count(quiver_item) <= 0:
                raise exceptions.Impossible("Your quiver is empty.")
            raise exceptions.Impossible("You need a bow and arrows to fire.")

        import tcod.los
        from animations import ThrowAnimation

        # Store projectile info before consuming it
        projectile_char = projectile_item.char
        projectile_color = projectile_item.color

        # Always consume projectile when firing (regardless of hit/miss)
        self._consume_projectile(
            projectile_item,
            using_quiver=using_quiver,
            quiver_item=quiver_item,
            shot_ammo_type=shot_ammo_type,
        )

        # Play shooting sound
        sounds.play_throw_sound()  # Use throw sound for bow firing

        bow_range = BOW_DEFAULT_MAX_RANGE
        if getattr(bow_item, "equippable", None):
            bow_range = int(getattr(bow_item.equippable, "max_range", BOW_DEFAULT_MAX_RANGE) or BOW_DEFAULT_MAX_RANGE)

        target, collision_pos, collision_type = self._find_target_in_line(max_range=bow_range)

        # Use bow verb if available
        shot_verb = "shoots"
        if hasattr(bow_item, "verb_present") and bow_item.verb_present:
            shot_verb = bow_item.verb_present
        elif hasattr(bow_item, "verb_base") and bow_item.verb_base:
            shot_verb = bow_item.verb_base + "s"

        # Handle different collision types
        if collision_type == 'actor' and target:
            # Hit an actor - proceed with normal combat
            self._handle_actor_hit(target, shot_verb, bow_item, projectile_item)
            # Add projectile animation
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), collision_pos).tolist())
            self.engine.animation_queue.append(ThrowAnimation(path, projectile_char, projectile_color))
        elif collision_type == 'obstacle':
            # Hit an obstacle - 50/50 chance to break or fall
            break_chance = random.random() < ARROW_OBSTACLE_BREAK_CHANCE
            
            # Add projectile animation to collision point
            obstacle_x = collision_pos[0] + self.dx
            obstacle_y = collision_pos[1] + self.dy
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), (obstacle_x, obstacle_y)).tolist())
            self.engine.animation_queue.append(ThrowAnimation(path, projectile_char, projectile_color))
            
            sounds.play_throw_sound()  # Use throw sound for projectile hitting obstacle
            if break_chance:
                self.engine.message_log.add_message("Your arrow hits an obstacle and breaks!", color.gray)
            else:
                self.engine.message_log.add_message("Your arrow hits an obstacle and falls to the ground.", color.gray)
                self._drop_projectile_at(collision_pos, projectile_item)
        elif collision_type == 'out_of_bounds':
            # Add projectile animation to edge of map
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), collision_pos).tolist())
            self.engine.animation_queue.append(ThrowAnimation(path, projectile_char, projectile_color))
            self.engine.message_log.add_message("Your arrow flies out of sight.", color.gray)
        elif collision_type == 'max_range':
            # Add projectile animation to max range
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), collision_pos).tolist())
            self.engine.animation_queue.append(ThrowAnimation(path, projectile_char, projectile_color))
            self.engine.message_log.add_message("Your arrow lands in the distance.", color.gray)
            self._drop_projectile_at(collision_pos, projectile_item)
        else:
            # No target found in range
            self.engine.message_log.add_message("Your arrow flies through empty air.", color.gray)

    def _drop_projectile_at(self, pos: tuple[int, int], original_projectile) -> None:
        """Drop a copy of the projectile at the specified position."""
        try:
            if original_projectile is not None:
                new_arrow = copy.deepcopy(original_projectile)
            else:
                from entity_factories import arrow  # Fallback template
                new_arrow = copy.deepcopy(arrow)
            new_arrow.x, new_arrow.y = pos
            
            # Add to game map
            self.engine.game_map.entities.add(new_arrow)
            
        except Exception as e:
            self.engine.debug_log(f"Error creating dropped arrow: {e}", handler=type(self).__name__, event="_drop_projectile_at")
            # Silently fail if we can't create the arrow
    
    def _handle_actor_hit(self, target: Actor, shot_verb: str, bow_item, projectile_item) -> None:
        """Handle hitting an actor with the projectile."""
        # Manipulation check
        for part in self.entity.body_parts.get_all_parts().values():
            if "manipulate" in part.tags:
                if part.damage_level_float >= 1.0:
                    self.entity.fighter._drop_grasped_items(part)
                elif part.damage_level_float > 0.5 and random.random() < 0.5:
                    self.entity.fighter._drop_grasped_items(part)

        # Apply mouse precision targeting if available
        if self.tile_rel_pos and not self.target_part:
            body_parts_comp = getattr(target, 'body_parts', None)
            if body_parts_comp:
                aimed = get_part_from_tile_position(body_parts_comp, *self.tile_rel_pos)
                if aimed:
                    dist_from_center = ((self.tile_rel_pos[0] - 0.5) ** 2 + (self.tile_rel_pos[1] - 0.5) ** 2) ** 0.5
                    accuracy_bonus = max(0.0, 1.0 - (dist_from_center / 0.5))
                    if accuracy_bonus > 0.6:
                        self.target_part = aimed.part_type

        hit_part, self.target_part, damage_modifier = _resolve_hit_part(target, self.target_part)
        bow_tags = set(getattr(bow_item, "tags", []) or [])
        arrow_tags = set(getattr(projectile_item, "tags", []) or [])
        bow_profile = profsys.weapon_profile(self.entity, bow_tags)
        arrow_profile = profsys.weapon_profile(self.entity, arrow_tags)

        # Calculate defense and damage
        projectile_power = 0
        if getattr(projectile_item, "equippable", None):
            projectile_power = int(getattr(projectile_item.equippable, "power_bonus", 0) or 0)

        armor_tags = target.equipment.get_armor_tags_for_part(hit_part.name) if hit_part and target.equipment else []
        agility_bonus = trait_delta(_get_trait_level(self.entity, "agility"))
        ranged_multiplier = 1.0 + (agility_bonus * AGILITY_RANGED_DAMAGE_PER_LEVEL)
        damage_multiplier = damage_modifier * ranged_multiplier * arrow_profile.damage_multiplier
        final_damage, armor_defense = target.fighter.mitigate_incoming_damage(
            projectile_power,
            damage_multiplier=damage_multiplier,
            targeted_part=hit_part,
            armor_tags=armor_tags,
        )

        # Hit chance is determined by the bow's base accuracy, optionally scaled by mouse precision.
        bow_base_hit = BASE_HIT_RANGED
        if getattr(bow_item, "equippable", None):
            bow_hit_override = getattr(bow_item.equippable, "base_hit_chance", None)
            if bow_hit_override is not None:
                bow_base_hit = float(bow_hit_override)

        if self.tile_rel_pos:
            dist_from_center = ((self.tile_rel_pos[0] - 0.5) ** 2 + (self.tile_rel_pos[1] - 0.5) ** 2) ** 0.5
            accuracy_bonus = max(0.0, 1.0 - (dist_from_center / 0.5))
            hit_chance = bow_base_hit * (0.8 + 0.4 * accuracy_bonus)
        else:
            hit_chance = bow_base_hit
        hit_chance += _get_agility_hit_modifier(self.entity, target)
        hit_chance *= bow_profile.accuracy_multiplier
        hit_chance = max(MIN_HIT_CHANCE, min(MAX_HIT_CHANCE, hit_chance))
        hit_success = random.random() < hit_chance

        # Dodge calculation
        dodge_success = False
        effective_dodge = _effective_dodge_chance(target, armor_tags)
        if hit_success and random.random() < effective_dodge:
            if target.dodge_cooldown == 0:
                hit_success = False
                dodge_success = True
                target.dodge_cooldown = target.dodge_cooldown_max


        old_dodge_x, old_dodge_y = target.x, target.y
        dodge_dir = (0, 0)
        if dodge_success:
            adjacent_positions = [
                (target.x + 1, target.y), (target.x - 1, target.y),
                (target.x, target.y + 1), (target.x, target.y - 1),
            ]
            if target.preferred_dodge_direction:
                preferred_order = {
                    "north": [(target.x, target.y - 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y + 1)],
                    "south": [(target.x, target.y + 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y - 1)],
                    "east":  [(target.x + 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x - 1, target.y)],
                    "west":  [(target.x - 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x + 1, target.y)],
                }
                adjacent_positions = preferred_order.get(target.preferred_dodge_direction.lower(), adjacent_positions)
            gm = self.engine.game_map
            for new_x, new_y in adjacent_positions:
                if (gm.in_bounds(new_x, new_y)
                        and gm.tiles["walkable"][new_x, new_y]
                        and not gm.get_blocking_entity_at_location(new_x, new_y)):
                    DodgeAction(target, new_x - target.x, new_y - target.y).perform()
                    self.engine.message_log.add_message(f"{target.name} dodges to the side!", color.teal)
                    break
            self.engine.animation_queue.append(
                gpu_stack.DodgeParticle((old_dodge_x, old_dodge_y),
                                        character=target.char,
                                        direction=dodge_dir))

        # Create attack description
        if hit_part:
            attack_desc = f"{self.entity.name.capitalize()} {shot_verb} {target.name}'s {hit_part.name}"
        else:
            attack_desc = f"{self.entity.name.capitalize()} {shot_verb} {target.name}"

        # Play sounds
        if hit_success and final_damage > 0:
            if target.fighter.hp <= final_damage:
                sounds.play_attack_sound_finishing_blow()
            elif target.equipment and target.equipment.equipped_items.get('ARMOR'):
                sounds.play_attack_sound_weapon_to_armor()
            else:
                sounds.play_attack_sound_weapon_to_no_armor()
        elif hit_success and final_damage == 0:
            sounds.play_block_sound()
        else:
            sounds.play_miss_sound()

        # Set attack color
        if self.entity is self.engine.player:
            attack_color = color.player_atk
        else:
            attack_color = color.enemy_atk

        # Display results
        if not hit_success:
            if dodge_success:
                self.engine.message_log.add_message(
                    f"{attack_desc}, but {target.name} dodges!", color.teal
                )
            else:
                self.engine.message_log.add_message(
                    f"{attack_desc}, but misses!", color.dark_gray
                )
            # Arrow always drops when missing/dodged - drop at target location
            self._drop_projectile_at((target.x, target.y), projectile_item)
        elif final_damage > 0:
            if hit_part:
                part_damage = hit_part.take_damage(final_damage)
                if hit_part.is_destroyed:
                    self.engine.message_log.add_message(
                        f"{attack_desc} and destroys it for {part_damage} damage!", color.red
                    )
                else:
                    self.engine.message_log.add_message(
                        f"{attack_desc} for {part_damage} damage.", attack_color
                    )
                

                target.fighter.take_damage(part_damage, targeted_part=self.target_part)
            else:
                self.engine.message_log.add_message(
                    f"{attack_desc} for {final_damage} hit points.", attack_color
                )
                target.fighter.take_damage(final_damage)
            #item_for_attack = self._get_ready_ranged_items()[0]  # Get the bow used for the attack

            # Most landed arrows can be recovered from the battlefield.
            if random.random() < ARROW_HIT_RECOVERY_CHANCE:
                self._drop_projectile_at((target.x, target.y), projectile_item)

            if target is self.engine.player:
                existing_bleed = next(
                    (a for a in self.engine.animation_queue
                     if isinstance(a, gpu_stack.CRTBleedAnim)), None
                )
                if existing_bleed is not None:
                    existing_bleed.frames = existing_bleed.total_frames
                else:
                    self.engine.animation_queue.append(gpu_stack.CRTBleedAnim())
                
        else:
            self.engine.message_log.add_message(
                f"{attack_desc}, but does no damage.", attack_color
            )
            # Arrow bounced off armor/blocked - drops to ground
            self._drop_projectile_at((target.x, target.y), projectile_item)

        # Grant trait XP for ranged combat
        if final_damage > 0:
            attacker_level = getattr(self.entity, "level", None)
            target_level = getattr(target, "level", None)

            # Award XP to attacker for bow usage
            if attacker_level is not None:
                attacker_level.add_xp({'agility': int(final_damage*2)})
            
            # Award XP to target for taking damage and armor defense
            if target_level is not None:
                target_level.add_xp({'vigor': int(final_damage)})
            
            # Award armor XP if target has armor that blocked damage
            armor_tags = target.equipment.get_armor_tags_for_part(hit_part.name) if hit_part and hasattr(target, "equipment") and target.equipment else []
            if armor_defense > 0 and armor_tags and target_level is not None:
                target_level.add_xp({'armor': int(armor_defense/2)})
                for trait in _armor_xp_traits_from_tags(armor_tags):
                    if trait == "armor":
                        continue
                    target_level.add_xp({trait: int(armor_defense)})

class DodgeAction(ActionWithDirection):
    """Dodge in a direction to attempt to avoid attacks, moving to an adjacent tile if successful."""

    def perform(self) -> None:
        
        if self.entity.dodge_cooldown > 0:
            raise exceptions.Impossible("Too tired to dodge!")
        else:
            target_x, target_y = self.dest_xy
            gm = self.engine.game_map

            if not gm.in_bounds(target_x, target_y):
                raise exceptions.Impossible("You can't dodge out of bounds!")
            if not gm.tiles["walkable"][target_x, target_y]:
                raise exceptions.Impossible("You can't dodge into a wall!")
            if gm.get_blocking_entity_at_location(target_x, target_y):
                raise exceptions.Impossible("You can't dodge into an obstacle!")
            sounds.play_miss_sound()
            self.entity.x = target_x
            self.entity.y = target_y
            import components.effect
            self.entity.effects.append(components.effect.TiredEffect(duration=self.entity.dodge_cooldown_max+1))
            self.engine.animation_queue.append(gpu_stack.DodgeParticle((target_x, target_y), character=self.entity.char, direction=(self.dx, self.dy)))
            self.entity.dodge_cooldown = self.entity.dodge_cooldown_max

class MeleeAction(ActionWithDirection):
    """Melee action that targets a specific body part."""

    def __init__(self, entity: Actor, dx: int, dy: int, target_part: Optional['BodyPartType'] = None, tile_rel_pos: Optional[Tuple[float, float]] = None):
        super().__init__(entity, dx, dy)
        self.target_part = target_part
        self.tile_rel_pos = tile_rel_pos  # normalised (x, y) within target tile, 0.0–1.0

    def _apply_precision_targeting(self, target: Actor) -> None:
        """Attempt to map tile-relative cursor position to a specific body part."""
        if not self.tile_rel_pos or self.target_part:
            return

        body_parts_comp = getattr(target, 'body_parts', None)
        if not body_parts_comp:
            return

        aimed = get_part_from_tile_position(body_parts_comp, *self.tile_rel_pos)
        if not aimed:
            return

        dist_from_center = ((self.tile_rel_pos[0] - 0.5) ** 2 + (self.tile_rel_pos[1] - 0.5) ** 2) ** 0.5
        accuracy_bonus = max(0.0, 1.0 - (dist_from_center / 0.5))
        if accuracy_bonus > 0.6:
            self.target_part = aimed.part_type

    def _resolve_melee_weapon(self, equipped_weapons: list) -> tuple[Optional[Item], str]:
        """Pick best melee weapon and derive a present-tense attack verb."""
        weapon = next((w for w in equipped_weapons if getattr(w, 'enchantments', None)), None)
        if weapon is None and equipped_weapons:
            weapon = equipped_weapons[0]

        weapon_verb = None
        if weapon:
            if getattr(weapon, 'verb_present', None):
                weapon_verb = weapon.verb_present
            elif getattr(weapon, 'verb_base', None):
                weapon_verb = weapon.verb_base + "s"

        if not weapon_verb:
            if getattr(self.entity, 'verb_present', None):
                weapon_verb = self.entity.verb_present
            elif getattr(self.entity, 'verb_base', None):
                weapon_verb = self.entity.verb_base + "s"

        return weapon, (weapon_verb or "attacks")

    def _compute_damage_profile(self, target: Actor, hit_part, damage_modifier: float, equipped_weapons: list) -> tuple[int, int, list, profsys.ProficiencyResult]:
        armor_tags = target.equipment.get_armor_tags_for_part(hit_part.name) if hit_part and target.equipment else []

        strength_multiplier = 1.0 + (trait_delta(_get_trait_level(self.entity, "strength")) * STRENGTH_MELEE_DAMAGE_PER_LEVEL)
        weapon_profile = _weapon_proficiency_profile(self.entity, equipped_weapons)
        damage_multiplier = damage_modifier * strength_multiplier * weapon_profile.damage_multiplier
        final_damage, armor_defense = target.fighter.mitigate_incoming_damage(
            self.entity.fighter.power,
            damage_multiplier=damage_multiplier,
            targeted_part=hit_part,
            armor_tags=armor_tags,
        )
        return final_damage, armor_defense, armor_tags, weapon_profile

    def _compute_hit_success(self, target: Actor, weapon_profile: profsys.ProficiencyResult) -> bool:
        if self.tile_rel_pos:
            dist_from_center = ((self.tile_rel_pos[0] - 0.5) ** 2 + (self.tile_rel_pos[1] - 0.5) ** 2) ** 0.5
            accuracy_bonus = max(0.0, 1.0 - (dist_from_center / 0.5))
            hit_chance = BASE_HIT * (0.8 + 0.4 * accuracy_bonus)
        else:
            hit_chance = BASE_HIT

        hit_chance += _get_agility_hit_modifier(self.entity, target)
        hit_chance *= weapon_profile.accuracy_multiplier
        hit_chance = max(MIN_HIT_CHANCE, min(MAX_HIT_CHANCE, hit_chance))
        return random.random() < hit_chance

    def _attempt_dodge(self, target: Actor, armor_tags: list) -> tuple[bool, tuple[int, int], tuple[int, int]]:
        """Try to dodge to an adjacent tile. Returns (did_dodge, old_pos, dodge_dir)."""
        old_pos = (target.x, target.y)
        effective_dodge = _effective_dodge_chance(target, armor_tags)

        if target.dodge_cooldown > 0 or random.random() >= effective_dodge:
            return False, old_pos, (0, 0)

        adjacent_positions = [
            (target.x + 1, target.y), (target.x - 1, target.y),
            (target.x, target.y + 1), (target.x, target.y - 1),
        ]
        if target.preferred_dodge_direction:
            preferred_order = {
                "north": [(target.x, target.y - 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y + 1)],
                "south": [(target.x, target.y + 1), (target.x + 1, target.y), (target.x - 1, target.y), (target.x, target.y - 1)],
                "east":  [(target.x + 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x - 1, target.y)],
                "west":  [(target.x - 1, target.y), (target.x, target.y - 1), (target.x, target.y + 1), (target.x + 1, target.y)],
            }
            adjacent_positions = preferred_order.get(target.preferred_dodge_direction.lower(), adjacent_positions)

        gm = self.engine.game_map
        for new_x, new_y in adjacent_positions:
            if (gm.in_bounds(new_x, new_y)
                    and gm.tiles["walkable"][new_x, new_y]
                    and not gm.get_blocking_entity_at_location(new_x, new_y)):
                dodge_dir = (new_x - target.x, new_y - target.y)
                DodgeAction(target, dodge_dir[0], dodge_dir[1]).perform()
                return True, old_pos, dodge_dir

        return False, old_pos, (0, 0)

    def _apply_hit_outcome(
        self,
        *,
        target: Actor,
        hit_part,
        final_damage: int,
        attack_desc: str,
        attack_color,
        weapon,
        weapon_verb: str,
        slash_angle: tuple[int, int],
    ) -> int:
        """Apply damage/effects and return body-part damage dealt (for XP)."""
        part_damage = 0

        if weapon and getattr(weapon, 'enchantments', None):
            for enchantment in weapon.enchantments:
                enchantment.on_hit(self.engine, target, hit_part)
                self.engine.animation_queue.append(
                    gpu_stack.SlashParticle((target.x, target.y), enchanted=True, color=enchantment.get_color(), angle=slash_angle, type=weapon_verb)
                )

        if hit_part:
            part_damage = hit_part.take_damage(final_damage)
            if hit_part.is_destroyed:
                self.engine.message_log.add_message(
                    f"{attack_desc} and destroys it for {part_damage} damage!", color.red
                )
            else:
                self.engine.message_log.add_message(
                    f"{attack_desc} for {part_damage} damage.", attack_color
                )
            target.fighter.take_damage(part_damage, targeted_part=self.target_part)
        else:
            self.engine.message_log.add_message(
                f"{attack_desc} for {final_damage} hit points.", attack_color
            )
            target.fighter.take_damage(final_damage)
            part_damage = final_damage

        if target is self.engine.player:
            existing_bleed = next(
                (a for a in self.engine.animation_queue if isinstance(a, gpu_stack.CRTBleedAnim)),
                None,
            )
            if existing_bleed is not None:
                existing_bleed.frames = existing_bleed.total_frames
            else:
                self.engine.animation_queue.append(gpu_stack.CRTBleedAnim())

        return part_damage

    def _award_melee_xp(self, target: Actor, equipped_weapons: list, part_damage: int, armor_defense: int, hit_part) -> None:
        if part_damage <= 0:
            return

        attacker_xp: dict = {}
        for trait in _weapon_xp_traits_from_items(equipped_weapons):
            attacker_xp[trait] = attacker_xp.get(trait, 0) + part_damage

        if attacker_xp:
            attacker_level = getattr(self.entity, "level", None)
            if attacker_level is not None:
                attacker_level.add_xp(attacker_xp)

        defender_xp = {'vigor': part_damage * 2}
        if armor_defense > 0 and hit_part and target.equipment:
            armor_tags = target.equipment.get_armor_tags_for_part(hit_part.name) or []
            for trait in _armor_xp_traits_from_tags(armor_tags):
                if trait == "armor":
                    continue
                defender_xp[trait] = defender_xp.get(trait, 0) + int(armor_defense * 1.5)

        target_level = getattr(target, "level", None)
        if target_level is not None:
            target_level.add_xp(defender_xp)
    
    def perform(self) -> None:
        _break_invisibility(self.entity)
        target = self.target_actor

        # Direction: actual attacker→target vector when target exists, else tile dx/dy
        if target:
            slash_angle = (target.x - self.entity.x, target.y - self.entity.y)
        else:
            slash_angle = (self.dx, self.dy)

        if not target:
            x, y = self.target_location
            self.engine.animation_queue.append(gpu_stack.SlashParticle((x, y), enchanted=False, angle=slash_angle, type="miss"))
            sounds.play_miss_sound()
            raise exceptions.Impossible("Nothing to attack.")

        # Manipulation check – may drop held items if arms are damaged
        for part in self.entity.body_parts.get_all_parts().values():
            if "manipulate" in part.tags:
                if part.damage_level_float >= 1.0:
                    self.entity.fighter._drop_grasped_items(part)
                elif part.damage_level_float > 0.5 and random.random() < 0.5:
                    self.entity.fighter._drop_grasped_items(part)

        self._apply_precision_targeting(target)

        hit_part, self.target_part, damage_modifier = _resolve_hit_part(target, self.target_part)
        equipped_weapons: list = _collect_equipped_weapons(self.entity)
        final_damage, armor_defense, armor_tags, weapon_profile = self._compute_damage_profile(
            target,
            hit_part,
            damage_modifier,
            equipped_weapons,
        )

        hit_success = self._compute_hit_success(target, weapon_profile)
        dodge_success = False
        dodge_origin = (target.x, target.y)
        dodge_dir = (0, 0)
        if hit_success:
            dodge_success, dodge_origin, dodge_dir = self._attempt_dodge(target, armor_tags)
            if dodge_success:
                hit_success = False

        weapon, weapon_verb = self._resolve_melee_weapon(equipped_weapons)

        # Build attack description
        if hit_part:
            attack_desc = f"{self.entity.name.capitalize()} {weapon_verb} {target.name}'s {hit_part.name}"
        else:
            attack_desc = f"{self.entity.name.capitalize()} {weapon_verb} {target.name}"

        # Sounds
        if hit_success:
            if final_damage > 0:
                if target.fighter.hp <= final_damage:
                    sounds.play_attack_sound_finishing_blow()
                elif self.entity.equipment and target.equipment and target.equipment.equipped_items.get('ARMOR'):
                    sounds.play_attack_sound_weapon_to_armor()
                else:
                    sounds.play_attack_sound_weapon_to_no_armor()
            else:
                sounds.play_block_sound()
        else:
            sounds.play_miss_sound()

        # Animation
        if hit_success:
            slash_type = weapon_verb if weapon else "unarmed"
            self.engine.animation_queue.append(gpu_stack.SlashParticle((target.x, target.y), enchanted=False, angle=slash_angle, type=slash_type))

        attack_color = color.player_atk if self.entity is self.engine.player else color.enemy_atk
        part_damage = 0

        # --- Outcome messages and damage ---
        if not hit_success:
            msg = (f"{attack_desc}, but {target.name} dodges!" if dodge_success
                   else f"{attack_desc}, but misses!")
            if dodge_success:
                self.engine.animation_queue.append(
                    gpu_stack.DodgeParticle(dodge_origin,
                                            character=target.char,
                                            direction=dodge_dir))
            self.engine.animation_queue.append(gpu_stack.SlashParticle((target.x, target.y), enchanted=False, angle=slash_angle, type="miss"))
            self.engine.message_log.add_message(msg, color.teal if dodge_success else color.dark_gray)

        elif final_damage > 0:
            part_damage = self._apply_hit_outcome(
                target=target,
                hit_part=hit_part,
                final_damage=final_damage,
                attack_desc=attack_desc,
                attack_color=attack_color,
                weapon=weapon,
                weapon_verb=weapon_verb,
                slash_angle=slash_angle,
            )
        else:
            self.engine.message_log.add_message(
                f"{attack_desc}, but does no damage.", attack_color
            )

        self._award_melee_xp(target, equipped_weapons, part_damage, armor_defense, hit_part)

class MovementAction(ActionWithDirection):

    def _update_swim_state(self, dest_x: int, dest_y: int) -> None:
        """Switch swimming state only on transition, not every frame."""
        tile_name = self.engine.game_map.tiles["name"][dest_x, dest_y]
        is_water = tile_name == "Water"
        was_swimming = getattr(self.entity, "is_swimming", False)

        if is_water and not was_swimming:
            self.entity.is_swimming = True
            if hasattr(self.entity, "ai") and self.entity.ai is not None:
                self.entity.ai.swim()

        elif not is_water and was_swimming:
            self.entity.is_swimming = False
            # Restore the normal sprite once when leaving water.
            sprite_manager.refresh_actor_sprite(self.entity)

        else:
            self.entity.is_swimming = is_water

    def perform(self) -> None:
        self.entity.dodge_cooldown = max(0, self.entity.dodge_cooldown - 1)
        dest_x, dest_y = self.dest_xy

        # Check if entity can move (has working legs/locomotion)
        if hasattr(self.entity, 'body_parts') and self.entity.body_parts:
            if not self.entity.body_parts.can_move():
                if self.entity == self.engine.player:
                    raise exceptions.Impossible("You can't move with your legs destroyed!")
                else:
                    raise exceptions.Impossible("The creature can't move!")
            
            # Warn player about movement penalties from leg injuries
            if self.entity == self.engine.player:
                self.engine.turn_count += 1
                penalty = self.entity.body_parts.get_movement_penalty()
                if penalty > 0.5:  # Significant penalty (> 50%)
                    if not hasattr(self, '_shown_movement_warning'):
                        self.engine.message_log.add_message("Your damaged legs make movement difficult!", color.yellow)
                        self._shown_movement_warning = True

        if not self.engine.game_map.in_bounds(dest_x, dest_y):
            raise exceptions.Impossible("That way is blocked.")  # Destination is out of bounds.
        
        if not self.engine.game_map.tiles["walkable"][dest_x, dest_y]:
            raise exceptions.Impossible("That way is blocked.")  # Destination is not walkable.
        if self.engine.game_map.get_blocking_entity_at_location(dest_x, dest_y):
            raise exceptions.Impossible("That way is blocked.")  # Destination is blocked by an entity.
        
        self.entity.move(self.dx, self.dy)

        # Always play footstep sounds for non-player entities (enemies)
        if self.entity != self.engine.player:
            # Play footstep sound with positional muffling
            dx = dest_x - self.engine.player.x
            dy = dest_y - self.engine.player.y
            distance = (dx * dx + dy * dy) ** 0.5


            
            if distance <= 10:  # Within hearing range
                # Check for liquid coating first, then tile type
                liquid_coating = None
                if hasattr(self.engine.game_map, 'liquid_system'):
                    liquid_coating = self.engine.game_map.liquid_system.get_coating(dest_x, dest_y)
                
                if liquid_coating and liquid_coating.depth >= 1:
                    sounds.play_movement_sound_at(sounds.play_liquid_walk_sound, dest_x, dest_y, self.engine.player, self.engine.game_map)
                else:
                    # Check tile type for sound variation
                    tile_name = self.engine.game_map.tiles["name"][dest_x, dest_y]
                    if tile_name == "Grass":
                        sounds.play_movement_sound_at(sounds.play_grass_walk_sound, dest_x, dest_y, self.engine.player, self.engine.game_map)
                    elif tile_name == "Mossy Floor":
                        sounds.play_movement_sound_at(sounds.play_moss_walk_sound, dest_x, dest_y, self.engine.player, self.engine.game_map)
                    elif tile_name == "Water":
                        self._update_swim_state(dest_x, dest_y)
                        sounds.play_movement_sound_at(sounds.play_swim_sound, dest_x, dest_y, self.engine.player, self.engine.game_map)
                    else:
                        self._update_swim_state(dest_x, dest_y)
                        sounds.play_movement_sound_at(sounds.play_walk_sound, dest_x, dest_y, self.engine.player, self.engine.game_map)

        # Track swimming state transitions based on tile content. This avoids per-frame sprite resets.
        self._update_swim_state(dest_x, dest_y)
        if self.entity == self.engine.player:
            tile_name = self.engine.game_map.tiles["name"][dest_x, dest_y]
            if tile_name == "Dungeon Exit":
                self.engine.game_world.ascend()
                import color
                self.engine.message_log.add_message("You surface from the dungeon", color.purple)
                return

        # If not in view, display sound tile animation (for all entities)
        from animations import HeardSoundAnimation
        if not self.engine.game_map.visible[dest_x, dest_y]:
            # Use different color for enemy footsteps vs other sounds
            if self.entity != self.engine.player:
                color = (255, 255, 255)  # Gray for footsteps
            else:
                color = (255, 255, 0)  # Yellow for other sounds
            self.engine.animation_queue.append(HeardSoundAnimation((dest_x, dest_y), self.engine.player, color, (self.dx, self.dy)))
        
        # Only play walk sound for player if not moving rapidly or holding key
        if self.entity == self.engine.player and self.engine.should_play_movement_sound():
            # Check if near player 
            dx = dest_x - self.engine.player.x
            dy = dest_y - self.engine.player.y
            distance = (dx * dx + dy * dy) ** 0.5

            if distance <= 8:
                # Check for liquid coating first, then tile type
                liquid_coating = None
                if hasattr(self.engine.game_map, 'liquid_system'):
                    liquid_coating = self.engine.game_map.liquid_system.get_coating(dest_x, dest_y)
                
                if liquid_coating and liquid_coating.depth >= 1:
                    sounds.play_liquid_walk_sound(dest_x, dest_y)
                else:
                    # Check tile type for sound variation
                    tile_name = self.engine.game_map.tiles["name"][dest_x, dest_y]
                    if tile_name == "Grass":
                        sounds.play_grass_walk_sound()
                    elif tile_name == "Mossy Floor":
                        sounds.play_moss_walk_sound()
                    elif tile_name == "Water":
                        self._update_swim_state(dest_x, dest_y)
                        sounds.play_swim_sound()
                    elif tile_name == "Floor":
                        self._update_swim_state(dest_x, dest_y)
                        sounds.play_walk_sound()


class MoveToAction(Action):
    """Pathfinds to a destination and auto-moves the player one step per turn."""

    def __init__(self, entity: Actor, dest_x: int, dest_y: int):
        super().__init__(entity)
        self.dest_x = dest_x
        self.dest_y = dest_y

    def perform(self) -> None:
        import numpy as np
        import tcod.path

        dest_x, dest_y = self.dest_x, self.dest_y
        game_map = self.engine.game_map

        if not game_map.in_bounds(dest_x, dest_y):
            raise exceptions.Impossible("That location is out of bounds.")

        if not game_map.explored[dest_x, dest_y]:
            raise exceptions.Impossible("You haven't explored that area.")

        # Build cost array restricted to walkable + explored tiles
        cost = np.array(game_map.tiles["walkable"], dtype=np.int8)
        cost &= game_map.explored.astype(np.int8)

        graph = tcod.path.SimpleGraph(cost=cost, cardinal=2, diagonal=3)
        pathfinder = tcod.path.Pathfinder(graph)
        pathfinder.add_root((self.entity.x, self.entity.y))
        raw_path = pathfinder.path_to((dest_x, dest_y))[1:].tolist()

        if not raw_path:
            raise exceptions.Impossible("No path to that location.")

        # Store remaining steps on the engine for subsequent turns
        self.engine.auto_move_path = [tuple(p) for p in raw_path[1:]]

        # Take the first step immediately (this turn)
        first = raw_path[0]
        MovementAction(self.entity, first[0] - self.entity.x, first[1] - self.entity.y).perform()


class ThrowItem(ItemAction):
    def __init__(self, entity: Actor, item: Item, target_x: int, target_y: int):
        super().__init__(entity, item, target_xy=(target_x, target_y))

    def check_throw_hit(self, x, y) -> None:
        # Check for actor at target location
        target = self.engine.game_map.get_actor_at_location(x, y)
        if target:
            item_weight = getattr(self.item, 'weight', 1.0)  # Default weight if not specified
            damage = int(item_weight)

            # Pick random body part to hit
            if hasattr(target, 'body_parts') and target.body_parts:
                random_part = target.body_parts.get_random_part()
                targeted_part = random_part.part_type if random_part else None
            else:
                targeted_part = None
                random_part = None

            # Inflict damage on part
            if targeted_part and random_part:
                target.fighter.take_damage(damage, targeted_part=targeted_part)
                self.engine.message_log.add_message(f"You throw the {self.item.name} and hit {target.name}'s {random_part.name} for {damage} damage!", color.orange)
            else:
                target.fighter.take_damage(damage)
                self.engine.message_log.add_message(f"You throw the {self.item.name} and hit {target.name} for {damage} damage!", color.orange)

    def perform(self) -> None:
        _break_invisibility(self.entity)
        # Remove item from inventory
        if self.entity.equipment.item_is_equipped(self.item):
            self.entity.equipment.toggle_equip(self.item)

        # Also check if contained liquid
        if self.item.liquid_type:
            x = self.target_xy[0]
            y = self.target_xy[1]
            self.engine.game_map.liquid_system.spill_volume(x=x, y=y, liquid_type=self.item.liquid_type, volume=self.item.liquid_amount)
        

        if self.item.tags and "fragile" in self.item.tags:
            # Handle fragile item breakage
            self.engine.message_log.add_message(f"You throw the {self.item.name}, and it shatters on impact!", color.purple)
            sounds.play_glass_break_sound()
            # Delete item
            self.entity.inventory.delete(self.item)
            return
        
        else:
            import tcod.los
            from animations import ThrowAnimation
            self.entity.inventory.drop(self.item)
            self.item.drop_sound()
            # Place item on the ground at target location
            self.check_throw_hit(*self.target_xy)
            self.item.x, self.item.y = self.target_xy
            
            # Queue a projectile animation from entity to target location
            path = list(tcod.los.bresenham((self.entity.x, self.entity.y), self.target_xy).tolist())
            self.engine.animation_queue.append(ThrowAnimation(path, self.item.char, self.item.color))


class BumpAction(ActionWithDirection):
    def perform(self) -> None:
        actor = self.target_actor
        if actor and getattr(actor, "blocks_movement", True):
            return MeleeAction(self.entity, self.dx, self.dy).perform()
        else:
            return MovementAction(self.entity, self.dx, self.dy).perform()
        

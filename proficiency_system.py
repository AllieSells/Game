from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Set
import random

from balance_config import (
    AGILITY_DODGE_BONUS_PER_LEVEL,
    ARMOR_AFFINITY_MITIGATION_CAP,
    ARMOR_AFFINITY_MITIGATION_PER_LEVEL,
    ARMOR_DODGE_BONUS_PER_LEVEL,
    HEAVY_ARMOR_DODGE_PENALTY,
    LIGHT_ARMOR_DODGE_PENALTY,
    MEDIUM_ARMOR_DODGE_PENALTY,
    PROFICIENCY_MULTIPLIER_MAX,
    PROFICIENCY_MULTIPLIER_MIN,
    ARMOR_SKILL_BASE_DEFENSE,
    ARMOR_SKILL_DEFENSE_PER_LEVEL,
    ARMOR_TAG_TRAIT_RULES,
    SPELL_BASE_SUCCESS_CHANCE,
    SPELL_MAX_SUCCESS_CHANCE,
    SPELL_MIN_SUCCESS_CHANCE,
    SPELL_SUCCESS_BONUS_PER_LEVEL,
    WEAPON_SKILL_ACCURACY_PER_LEVEL,
    WEAPON_SKILL_BASE_ACCURACY,
    WEAPON_SKILL_BASE_DAMAGE,
    WEAPON_SKILL_DAMAGE_PER_LEVEL,
    WEAPON_TAG_TRAIT_RULES,
    SHIELD_BLOCK_BASE_CHANCE,
    SHIELD_BLOCK_CHANCE_PER_LEVEL,
    SHIELD_BLOCK_MAX_CHANCE,
    trait_delta,
)

SPELL_SCHOOL_TO_TRAITS: Dict[str, tuple[str, ...]] = {
    "abjuration": ("abjuration", "arcana"),
    "conjuration": ("conjuration", "arcana"),
    "divination": ("divination", "arcana"),
    "enchantment": ("enchantment", "arcana"),
    "evocation": ("evocation", "arcana"),
    "illusion": ("illusion", "arcana"),
    "necromancy": ("necromancy", "arcana"),
    "transmutation": ("transmutation", "arcana"),
}

@dataclass(frozen=True)
class ProficiencyResult:
    accuracy_multiplier: float = 1.0
    damage_multiplier: float = 1.0
    mitigation_multiplier: float = 1.0
    defense_bonus_multiplier: float = 1.0
    dodge_delta: float = 0.0


@dataclass(frozen=True)
class SpellProficiencyResult:
    success_chance: float = SPELL_BASE_SUCCESS_CHANCE
    potency_multiplier: float = 1.0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _trait_level(actor, trait_name: str) -> int:
    try:
        return int(actor.level.traits.get(trait_name, {}).get("level", 1) or 1)
    except Exception:
        return 1


def _best_trait_delta(actor, trait_candidates: Iterable[str]) -> int:
    best = 0
    for trait in trait_candidates:
        best = max(best, trait_delta(_trait_level(actor, trait)))
    return best


def _weighted_best_delta(actor, trait_candidates: Iterable[tuple[str, float]]) -> float:
    best = 0.0
    for trait, weight in trait_candidates:
        best = max(best, trait_delta(_trait_level(actor, trait)) * float(weight))
    return best


def _normalize_tags(tags: Iterable[str]) -> set[str]:
    return {str(tag).lower().strip() for tag in (tags or []) if str(tag).strip()}


def _resolve_tag_traits(tags: Iterable[str], rule_map: Dict[str, tuple[tuple[str, float], ...]]) -> dict[str, tuple[tuple[str, float], ...]]:
    normalized = _normalize_tags(tags)
    matched: dict[str, tuple[tuple[str, float], ...]] = {}
    for tag in normalized:
        rule = rule_map.get(tag)
        if rule:
            matched[tag] = rule
    return matched


def weapon_traits_for_tags(tags: Iterable[str]) -> set[str]:
    traits: set[str] = set()
    for trait_rules in _resolve_tag_traits(tags, WEAPON_TAG_TRAIT_RULES).values():
        traits.update(trait for trait, _ in trait_rules)
    return traits


def armor_traits_for_tags(tags: Iterable[str]) -> set[str]:
    traits: set[str] = set()
    for trait_rules in _resolve_tag_traits(tags, ARMOR_TAG_TRAIT_RULES).values():
        traits.update(trait for trait, _ in trait_rules)
    return traits


# Domain pressure removed: players can specialize in any direction without inherent penalties.


def weapon_profile(attacker, weapon_tags: Iterable[str]) -> ProficiencyResult:
    matched_rules = _resolve_tag_traits(weapon_tags, WEAPON_TAG_TRAIT_RULES)
    if not matched_rules:
        return ProficiencyResult()

    prof_scores: list[float] = []
    matched_traits: Set[str] = set()

    for trait_candidates in matched_rules.values():
        if trait_candidates:
            prof_scores.append(_weighted_best_delta(attacker, trait_candidates))
            matched_traits.update(trait for trait, _ in trait_candidates)

    if not prof_scores:
        return ProficiencyResult()

    focus_score = max(prof_scores)
    support_score = sum(prof_scores) / len(prof_scores)
    proficiency_score = (focus_score * 0.75) + (support_score * 0.25)

    accuracy_multiplier = _clamp(
        WEAPON_SKILL_BASE_ACCURACY + (proficiency_score * WEAPON_SKILL_ACCURACY_PER_LEVEL),
        PROFICIENCY_MULTIPLIER_MIN,
        PROFICIENCY_MULTIPLIER_MAX,
    )
    damage_multiplier = _clamp(
        WEAPON_SKILL_BASE_DAMAGE + (proficiency_score * WEAPON_SKILL_DAMAGE_PER_LEVEL),
        PROFICIENCY_MULTIPLIER_MIN,
        PROFICIENCY_MULTIPLIER_MAX,
    )

    return ProficiencyResult(
        accuracy_multiplier=accuracy_multiplier,
        damage_multiplier=damage_multiplier,
    )


def spell_profile(caster, school: str) -> SpellProficiencyResult:
    school_key = str(school or "").lower().strip()
    trait_candidates = SPELL_SCHOOL_TO_TRAITS.get(school_key, ("arcana",))
    primary_delta = _best_trait_delta(caster, trait_candidates)

    success = SPELL_BASE_SUCCESS_CHANCE + (primary_delta * SPELL_SUCCESS_BONUS_PER_LEVEL)
    return SpellProficiencyResult(
        success_chance=_clamp(success, SPELL_MIN_SUCCESS_CHANCE, SPELL_MAX_SUCCESS_CHANCE),
        potency_multiplier=1.0,
    )


def armor_profile(defender, armor_tags: Iterable[str]) -> ProficiencyResult:
    matched_rules = _resolve_tag_traits(armor_tags, ARMOR_TAG_TRAIT_RULES)
    if not matched_rules:
        return ProficiencyResult()

    defense_scores: list[float] = []
    mitigation = 0.0
    dodge_delta = 0.0

    for tag, trait_candidates in matched_rules.items():
        if not trait_candidates:
            continue

        prof_delta = _best_trait_delta(defender, [trait for trait, _ in trait_candidates])
        defense_scores.append(_weighted_best_delta(defender, trait_candidates))
        mitigation += prof_delta * ARMOR_AFFINITY_MITIGATION_PER_LEVEL

        if tag == "light armor":
            dodge_delta += (prof_delta * ARMOR_DODGE_BONUS_PER_LEVEL) - LIGHT_ARMOR_DODGE_PENALTY
        elif tag == "medium armor":
            dodge_delta += (prof_delta * ARMOR_DODGE_BONUS_PER_LEVEL) - MEDIUM_ARMOR_DODGE_PENALTY
        elif tag == "heavy armor":
            dodge_delta += (prof_delta * ARMOR_DODGE_BONUS_PER_LEVEL) - HEAVY_ARMOR_DODGE_PENALTY

    if not defense_scores:
        return ProficiencyResult()

    reduction = min(ARMOR_AFFINITY_MITIGATION_CAP, mitigation)
    focus_score = max(defense_scores) if defense_scores else 0.0
    support_score = (sum(defense_scores) / len(defense_scores)) if defense_scores else 0.0
    armor_score = (focus_score * 0.8) + (support_score * 0.2)
    defense_multiplier = _clamp(
        ARMOR_SKILL_BASE_DEFENSE + (armor_score * ARMOR_SKILL_DEFENSE_PER_LEVEL),
        PROFICIENCY_MULTIPLIER_MIN,
        PROFICIENCY_MULTIPLIER_MAX,
    )

    return ProficiencyResult(
        mitigation_multiplier=1.0 - reduction,
        defense_bonus_multiplier=defense_multiplier,
        dodge_delta=dodge_delta,
    )


def agility_dodge_bonus(actor) -> float:
    return trait_delta(_trait_level(actor, "agility")) * AGILITY_DODGE_BONUS_PER_LEVEL


def shield_check(defender, armor_tags: Iterable[str]) -> bool:
    matched_rules = _resolve_tag_traits(armor_tags, ARMOR_TAG_TRAIT_RULES)
    shield_rules = {
        tag: trait_candidates
        for tag, trait_candidates in matched_rules.items()
        if "shield" in tag
    }
    if not shield_rules:
        return False

    block_chance = SHIELD_BLOCK_BASE_CHANCE
    shield_score = 0.0
    for trait_candidates in shield_rules.values():
        shield_score = max(shield_score, _weighted_best_delta(defender, trait_candidates))

    block_chance += shield_score * SHIELD_BLOCK_CHANCE_PER_LEVEL
    raw_block_chance = block_chance
    block_chance = _clamp(block_chance, 0.0, SHIELD_BLOCK_MAX_CHANCE)
    print(
        f"Shield block chance raw={raw_block_chance:.2%}, effective={block_chance:.2%} (cap={SHIELD_BLOCK_MAX_CHANCE:.0%})"
    )

    return block_chance > 0 and random.random() < block_chance
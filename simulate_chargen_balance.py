"""Quick simulator for character creation balance.

Evaluates every origin/profession combination and estimates opening power using:
- trait bonuses (after clamping to chargen rules)
- starting items (using json/chargen.json item costs)
- starting spells
- origin perks

The script prints ranked combos and flags statistical outliers.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, pstdev
from typing import Dict, List

from balance_config import STARTING_MANA_BASE, STARTING_MANA_PER_ARCANA_LEVEL


ROOT = Path(__file__).parent
CHARGEN_PATH = ROOT / "json" / "chargen.json"
PROF_PATH = ROOT / "json" / "professions.json"

BASE_TRAIT_LEVEL = 1
MIN_TRAIT_LEVEL = 1
MAX_TRAIT_LEVEL = 5
BASE_HP = 30
BASE_MANA = STARTING_MANA_BASE
MANA_PER_ARCANA_LEVEL = STARTING_MANA_PER_ARCANA_LEVEL


# Relative impact weights for opening strength.
TRAIT_WEIGHTS: Dict[str, float] = {
    "strength": 1.8,
    "agility": 1.8,
    "vigor": 1.9,
    "armor": 1.3,
    "light armor": 1.2,
    "medium armor": 1.3,
    "heavy armor": 1.4,
    "shields": 1.2,
    "blades": 1.1,
    "daggers": 1.1,
    "swords": 1.1,
    "arcana": 1.5,
    "abjuration": 1.0,
    "conjuration": 1.0,
    "divination": 1.0,
    "enchantment": 1.0,
    "evocation": 1.1,
    "illusion": 1.0,
    "necromancy": 1.0,
    "transmutation": 1.0,
}

DEFAULT_TRAIT_WEIGHT = 1.0

# Perk weights are intentionally modest to keep origin meaningful but not dominant.
PERK_WEIGHTS: Dict[str, float] = {
    "starting_gold": 0.06,
    "bonus_hp": 0.70,
    "bonus_mana": 0.22,
    "bonus_hunger": 0.03,
    "bonus_saturation": 0.04,
}

SPELL_WEIGHT = 2.5
OUTLIER_Z_THRESHOLD = 1.5


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _load_json(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _trait_score(traits: Dict[str, int]) -> float:
    score = 0.0
    for trait, level in traits.items():
        delta = int(level) - BASE_TRAIT_LEVEL
        weight = TRAIT_WEIGHTS.get(trait, DEFAULT_TRAIT_WEIGHT)
        score += delta * weight
    return score


def _perk_score(origin_perks: Dict[str, int]) -> float:
    score = 0.0
    for key, value in origin_perks.items():
        score += int(value) * PERK_WEIGHTS.get(key, 0.0)
    return score


def _projected_mana(arcana_level: int, bonus_mana: int) -> int:
    return BASE_MANA + max(0, arcana_level - 1) * MANA_PER_ARCANA_LEVEL + max(0, bonus_mana)


def _build_item_cost_map(chargen_data: dict) -> Dict[str, int]:
    cost_map: Dict[str, int] = {}
    for item in chargen_data.get("items_pool", []):
        ref = str(item.get("ref", ""))
        if not ref:
            continue
        try:
            cost_map[ref] = int(item.get("cost", 0))
        except Exception:
            cost_map[ref] = 0
    return cost_map


def _combo_report(origin: dict, profession: dict, item_costs: Dict[str, int]) -> dict:
    levels: Dict[str, int] = {}

    def apply_mods(mods: Dict[str, int]) -> None:
        for trait, bonus in mods.items():
            cur = levels.get(trait, BASE_TRAIT_LEVEL)
            levels[trait] = _clamp(cur + int(bonus), MIN_TRAIT_LEVEL, MAX_TRAIT_LEVEL)

    apply_mods(origin.get("aptitudes", {}) or {})
    apply_mods(profession.get("skills", {}) or {})

    origin_perks = origin.get("origin_perks", {}) or {}
    starting_items: List[str] = list(profession.get("starting_items", []) or [])
    starting_spells: List[str] = list(profession.get("starting_spells", []) or [])

    item_score = sum(item_costs.get(ref, 0) for ref in starting_items)
    spell_score = len(starting_spells) * SPELL_WEIGHT
    trait_score = _trait_score(levels)
    perk_score = _perk_score(origin_perks)

    total = trait_score + perk_score + item_score + spell_score

    arcana_level = levels.get("arcana", BASE_TRAIT_LEVEL)
    projected_hp = BASE_HP + int(origin_perks.get("bonus_hp", 0) or 0)
    projected_mana = _projected_mana(
        arcana_level=arcana_level,
        bonus_mana=int(origin_perks.get("bonus_mana", 0) or 0),
    )

    return {
        "origin": origin.get("id", ""),
        "profession": profession.get("id", ""),
        "score": round(total, 2),
        "trait_score": round(trait_score, 2),
        "perk_score": round(perk_score, 2),
        "item_score": round(item_score, 2),
        "spell_score": round(spell_score, 2),
        "projected_hp": projected_hp,
        "projected_mana": projected_mana,
        "items": starting_items,
        "spells": starting_spells,
    }


def _classify_outliers(rows: List[dict]) -> None:
    scores = [row["score"] for row in rows]
    if not scores:
        return

    avg = mean(scores)
    sigma = pstdev(scores)

    for row in rows:
        if sigma <= 0.0:
            row["z"] = 0.0
            row["outlier"] = "none"
            continue

        z = (row["score"] - avg) / sigma
        row["z"] = round(z, 2)
        if z >= OUTLIER_Z_THRESHOLD:
            row["outlier"] = "high"
        elif z <= -OUTLIER_Z_THRESHOLD:
            row["outlier"] = "low"
        else:
            row["outlier"] = "none"


def main() -> None:
    chargen_data = _load_json(CHARGEN_PATH)
    professions = _load_json(PROF_PATH)
    origins = list(chargen_data.get("origins", []))
    item_costs = _build_item_cost_map(chargen_data)

    rows: List[dict] = []
    for origin in origins:
        for profession in professions:
            rows.append(_combo_report(origin, profession, item_costs))

    _classify_outliers(rows)
    rows.sort(key=lambda r: r["score"], reverse=True)

    scores = [row["score"] for row in rows]
    avg = mean(scores) if scores else 0.0
    sigma = pstdev(scores) if len(scores) > 1 else 0.0

    print("== Chargen Balance Simulation ==")
    print(f"Combos: {len(rows)}")
    print(f"Mean score: {avg:.2f} | StdDev: {sigma:.2f}")
    print(f"Outlier threshold: |z| >= {OUTLIER_Z_THRESHOLD:.1f}")
    print()

    for idx, row in enumerate(rows, start=1):
        flag = ""
        if row["outlier"] == "high":
            flag = " [HIGH OUTLIER]"
        elif row["outlier"] == "low":
            flag = " [LOW OUTLIER]"

        print(
            f"{idx:>2}. {row['origin']} + {row['profession']} => {row['score']:.2f}"
            f" (z={row['z']:+.2f}){flag}"
        )
        print(
            "    parts: "
            f"traits={row['trait_score']:.2f}, perks={row['perk_score']:.2f}, "
            f"items={row['item_score']:.2f}, spells={row['spell_score']:.2f}"
        )
        print(
            "    projected: "
            f"hp={row['projected_hp']}, mana={row['projected_mana']}, "
            f"spells={row['spells']}"
        )

    print()
    highs = [r for r in rows if r["outlier"] == "high"]
    lows = [r for r in rows if r["outlier"] == "low"]
    print(f"High outliers: {len(highs)}")
    print(f"Low outliers: {len(lows)}")


if __name__ == "__main__":
    main()

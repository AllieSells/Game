import random
import copy
import entity_factories


def _instantiate(factory):
    item = copy.deepcopy(factory()) if callable(factory) else copy.deepcopy(factory)
    if hasattr(item, 'roll_for_enchantment'):
        item.roll_for_enchantment()
    return item


def generate_starter_chest_loot() -> list:
    return [
        _instantiate(entity_factories.dungeon_key),
        _instantiate(entity_factories.torch),
        _instantiate(entity_factories.dagger),
        _instantiate(entity_factories.leather_cap),
        _instantiate(entity_factories.generate_sigil_stone),
        _instantiate(entity_factories.lesser_health_potion),
    ]


def choose_item(pool):
    total_weight = sum(entry.weight for entry in pool)
    roll = random.uniform(0, total_weight)
    current = 0
    for entry in pool:
        current += entry.weight
        if roll <= current:
            return entry
    return pool[-1]


_CHEST_TIER_WEIGHTS = {
    "basic":    (("common", 70), ("uncommon", 22), ("rare", 8)),
    "advanced": (("common", 30), ("uncommon", 50), ("rare", 20)),
}

_POOL_MAP = None

def _get_pool_map():
    global _POOL_MAP
    if _POOL_MAP is None:
        _POOL_MAP = {
            "common":   entity_factories.COMMON_POOL,
            "uncommon": entity_factories.UNCOMMON_POOL,
            "rare":     entity_factories.RARE_POOL,
        }
    return _POOL_MAP


def generate_tiered_chest_loot(chest_tier: str = "basic") -> list:
    tiers = _CHEST_TIER_WEIGHTS.get(chest_tier, _CHEST_TIER_WEIGHTS["basic"])
    rarity_names   = [t[0] for t in tiers]
    rarity_weights = [t[1] for t in tiers]
    pool_map = _get_pool_map()

    items = []
    for _ in range(random.randint(0, 4)):
        rarity = random.choices(rarity_names, weights=rarity_weights, k=1)[0]
        entry  = choose_item(pool_map[rarity])
        item   = _instantiate(entry.item_factory)
        if item:
            items.append(item)
    return items

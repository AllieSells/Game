from __future__ import annotations
from typing import Dict
import entity_factories
from entity import Entity

# Dictionary of floor number to maximum items per room
max_items_by_floor: Dict[int, int] = {
    1: 2,
    4: 2,
}

# Dictionary of floor number to maximum chests per room
max_chests_by_floor: Dict[int, int] = {
    1: 1,
    3: 2,
}

# Dictionary of floor number to maximum monsters per room
max_monsters_by_floor: Dict[int, int] = {
    1: 2,
    4: 3,
    6: 5,
}

# Dictionary of floor number to maximum flora per room
max_flora_by_floor: Dict[int, int] = {
    1: 3,
    4: 5,
}

# Item spawn chances by floor (floor: {entity: weight})
item_chances: Dict[int, Dict[Entity, int]] = {
    0: {
        entity_factories.lesser_health_potion: 35,
        entity_factories.lightning_scroll: 25,
    },
    2: {
        entity_factories.confusion_scroll: 10,
    },
    4: {
        entity_factories.lightning_scroll: 25,
        entity_factories.sword: 5,
    },
    6: {
        entity_factories.fireball_scroll: 25,
        entity_factories.chain_mail: 15,
    },
}

# Enemy spawn chances by floor (floor: {entity: weight})
enemy_chances: Dict[int, Dict[Entity, int]] = {
    0: {
        entity_factories.goblin: 80,
        entity_factories.spider: 20,
    },
    3: {
        entity_factories.troll: 15,
    },
    5: {
        entity_factories.troll: 30,
    },
    7: {
        entity_factories.troll: 60,
    },
}

import json
import random
import copy
import entity_factories
import sys
import os

def get_data_path(filename):
    """Get the correct path for data files in both development and PyInstaller."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller executable
        base_path = sys._MEIPASS
    else:
        # Running in development
        base_path = os.path.dirname(__file__)
    return os.path.join(base_path, filename)

def load_loot_tables():
    """Load loot tables from JSON file."""
    try:
        with open(get_data_path('loot_tables.json'), 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("Warning: loot_tables.json not found")
        return {}

def generate_loot_from_table(table_name):
    """Generate loot items from a specific loot table."""
    tables = load_loot_tables()
    if table_name not in tables:
        return []
    
    loot_items = []
    for entry in tables[table_name]:
        item_name = entry["item"]
        count = entry.get("count", 1)
        chance = entry.get("chance", 100)
        
        # Roll for chance if specified
        if random.randint(1, 100) <= chance:
            for _ in range(count):
                item = create_item(item_name)
                if item:
                    loot_items.append(item)
    
    return loot_items

def create_item(item_name):
    """Create an item instance from name."""
    if item_name == "random_potion":
        return copy.deepcopy(entity_factories.get_random_potion())
    elif item_name == "random_scroll":
        return copy.deepcopy(entity_factories.get_random_scroll())
    elif item_name == "sigil_stone":
        return copy.deepcopy(entity_factories.generate_sigil_stone())
    elif item_name.startswith("leather_"):
        armor_type = item_name.replace("_", " ")
        return copy.deepcopy(entity_factories.generate_armor(armor_type))
    elif hasattr(entity_factories, item_name):
        return copy.deepcopy(getattr(entity_factories, item_name))
    else:
        print(f"Unknown item: {item_name}")
        return None
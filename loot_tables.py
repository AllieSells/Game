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
    """Create an item instance from name by looking it up directly in entity_factories."""
    if hasattr(entity_factories, item_name):
        item_or_function = getattr(entity_factories, item_name)
        
        # If it's a function, call it; if it's an object, copy it
        if callable(item_or_function):
            return copy.deepcopy(item_or_function())
        else:
            return copy.deepcopy(item_or_function)
    else:
        print(f"Unknown item: {item_name} (not found in entity_factories)")
        return None
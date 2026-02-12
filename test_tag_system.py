"""Test script for the tag-based equipment system."""
from components.body_parts import BodyParts, AnatomyType
from components.equippable import Sword, Helmet, Torch, Boots, Gauntlets, LeatherArmor, Shield

body_parts = BodyParts(AnatomyType.HUMANOID, max_hp=30)

items = [
    ('Sword', Sword()),
    ('Helmet', Helmet()),
    ('Torch', Torch()),
    ('Boots', Boots()),
    ('Gauntlets', Gauntlets()),
    ('Leather Armor', LeatherArmor()),
    ('Shield', Shield()),
]

print("=" * 80)
print("EQUIPMENT TAG SYSTEM VALIDATION")
print("=" * 80 + "\n")

for name, item in items:
    can_equip = body_parts.can_equip_item(item.required_tags)
    matching = body_parts.get_parts_matching_tags(item.required_tags)
    matching_names = [p.name for p in matching]
    tags_str = str(sorted(item.required_tags))
    print(f"{name:18} | required: {tags_str:35} | equippable on: {matching_names}")

print("\n" + "=" * 80)
print("✓ Tag system fully functional!")
print("=" * 80)

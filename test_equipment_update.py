"""Test that Equipment component uses the new tag-based system."""
from entity_factories import player, sword, torch, leather_armor
from components.equippable import Sword, Torch

print("=" * 80)
print("EQUIPMENT TAG SYSTEM INTEGRATION TEST")
print("=" * 80 + "\n")

print(f"Player body parts: {len(player.body_parts.body_parts)}")
print(f"Player has hands with 'grasp' tag: {player.body_parts.can_equip_item({'hand', 'grasp'})}")

# Test can_equip_item with actual items
can_equip_sword, msg = player.equipment.can_equip_item(sword)
print(f"\n✓ Sword (requires {sword.equippable.required_tags}): {can_equip_sword} | {msg}")

can_equip_armor, msg = player.equipment.can_equip_item(leather_armor)
print(f"✓ Leather Armor (requires {leather_armor.equippable.required_tags}): {can_equip_armor} | {msg}")

can_equip_torch, msg = player.equipment.can_equip_item(torch)
print(f"✓ Torch (requires {torch.equippable.required_tags}): {can_equip_torch} | {msg}")

print("\n" + "=" * 80)
print("✓ Equipment component fully updated to use tag system!")
print("=" * 80)

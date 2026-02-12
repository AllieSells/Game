"""
TAG-BASED EQUIPMENT SYSTEM

This document describes the new tag-based equipment system that replaces
strict left/right/arm/hand slot requirements.

==============================================================================
OVERVIEW
==============================================================================

Instead of hardcoding specific equipment slots (L.Hand, R.Hand, L.Arm, etc.),
the system now uses TAGS to match equipment with body parts:

- Each BODY PART has a set of TAGS describing what it can accommodate
- Each ITEM has REQUIRED_TAGS describing what it needs to be equipped
- An item can be equipped if ANY body part contains ALL of its required tags

This allows for flexible anatomy:
- Normal humans: 2 hands, 2 arms, 2 legs
- Three-armed creatures: 3 hands that can hold weapons
- Tentacled creatures: Multiple "grasp" parts
- Wingless creatures: Just a torso

==============================================================================
BODY PART TAGS
==============================================================================

The following tags are used to categorize body parts:

HANDS/ARMS:
  - "hand"       : Can hold/equip items → required by weapons, shields, torches
  - "grasp"      : Can grip tightly → required by weapons, shields
  - "manipulate" : Can perform fine manipulation → future ability checks
  - "hold"       : Can hold something loosely → required by torches, staves
  - "use"        : Can use equipment → required by torches, utility items
  - "arm"        : Whole arm (not just hand) → required by gauntlets

ARMOR/BODY:
  - "head"       : Part of head area → required by helmets
  - "torso"      : Main body → required by armor, backpacks
  - "armor"      : Can wear protective gear → body parts that include this

MOVEMENT:
  - "leg"        : Can move → counted for locomotion
  - "foot"       : End of leg for movement → required by boots
  - "locomotion" : Part of movement → checked by movement system

==============================================================================
ITEM REQUIRED TAGS
==============================================================================

Items specify what tags they need via `required_tags` set in Equippable:

WEAPONS (Sword, Dagger):
  required_tags = {"hand", "grasp"}
  → Can be equipped on any part with BOTH "hand" AND "grasp"
  → On humanoid: left hand, right hand

TORCHES:
  required_tags = {"hand", "hold", "use"}
  → Can be equipped on any part with "hand", "hold", AND "use"
  → On humanoid: left hand, right hand

ARMOR (Leather Armor, Chain Mail):
  required_tags = {"torso"}
  → Can be equipped on any part with "torso"
  → On humanoid: torso

HELMETS:
  required_tags = {"head"}
  → Can be equipped on any part with "head"
  → On humanoid: head

GAUNTLETS:
  required_tags = {"arm"}
  → Can be equipped on any part with "arm"
  → On humanoid: left arm, right arm

BOOTS:
  required_tags = {"foot"}
  → Can be equipped on any part with "foot"
  → On humanoid: left foot, right foot

SHIELDS (same as weapons):
  required_tags = {"hand", "grasp"}
  → Can be equipped on any part with "hand" AND "grasp"
  → On humanoid: left hand, right hand

==============================================================================
HUMANOID BODY PART TAGS (DEFAULT ANATOMY)
==============================================================================

head:
  tags = {"head", "armor"}

neck:
  tags = {} (no tags - supports armor checks only)

torso:
  tags = {"torso", "armor"}

left arm:
  tags = {"arm", "armor"}

right arm:
  tags = {"arm", "armor"}

left hand:
  tags = {"hand", "grasp", "manipulate", "hold", "use"}

right hand:
  tags = {"hand", "grasp", "manipulate", "hold", "use"}

left leg:
  tags = {"leg", "locomotion"}

right leg:
  tags = {"leg", "locomotion"}

left foot:
  tags = {"foot", "locomotion", "armor"}

right foot:
  tags = {"foot", "locomotion", "armor"}

==============================================================================
CREATING NEW BODY PARTS WITH CUSTOM ANATOMY
==============================================================================

When creating custom anatomy types, assign tags to each BodyPart:

Example: Three-armed creature

self.body_parts = {
    BodyPartType.TORSO: BodyPart(
        BodyPartType.TORSO, "torso", 1.0, max_hp=parent_hp,
        is_vital=True,
        tags={"torso", "armor"}
    ),
    
    # Three arms - all can grasp weapons
    BodyPartType.RIGHT_ARM: BodyPart(
        BodyPartType.RIGHT_ARM, "right arm", 0.4, max_hp=int(0.4 * parent_hp),
        is_limb=True,
        tags={"arm", "grasp", "hand", "manipulate", "hold", "use", "armor"}
    ),
    
    BodyPartType.LEFT_ARM: BodyPart(
        BodyPartType.LEFT_ARM, "left arm", 0.4, max_hp=int(0.4 * parent_hp),
        is_limb=True,
        tags={"arm", "grasp", "hand", "manipulate", "hold", "use", "armor"}
    ),
    
    BodyPartType.MIDDLE_ARM: BodyPart(
        BodyPartType.MIDDLE_ARM, "middle arm", 0.4, max_hp=int(0.4 * parent_hp),
        is_limb=True,
        tags={"arm", "grasp", "hand", "manipulate", "hold", "use", "armor"}
    ),
}

→ This 3-armed creature can now equip 3 weapons simultaneously!

==============================================================================
CREATING NEW ITEMS WITH TAG REQUIREMENTS
==============================================================================

When creating new items, specify what tags the equipped body part needs:

Example: Staff (requires two hands to wield, needs both grasp and hold)

class Staff(Equippable):
    def __init__(self) -> None:
        super().__init__(
            equipment_type=EquipmentType.WEAPON, 
            power_bonus=5,
            required_tags={"hand", "grasp", "hold"}  # Requires all three tags
        )

Example: Light Weapon (only needs to be held)

class Dagger(Equippable):
    def __init__(self) -> None:
        super().__init__(
            equipment_type=EquipmentType.WEAPON, 
            power_bonus=2,
            required_tags={"hand", "grasp"}  # Only needs hand grip
        )

==============================================================================
API REFERENCE
==============================================================================

BodyParts methods for tag-based checks:

can_equip_item(required_tags: Set[str]) -> bool
    Check if ANY undestroyed body part has ALL required tags.
    Returns True if equipment can be equipped somewhere.

get_parts_matching_tags(required_tags: Set[str]) -> List[BodyPart]
    Get all undestroyed body parts that have ALL required tags.
    Returns list of matching body parts where item can be equipped.

Example usage:

    if entity.body_parts.can_equip_item(sword.required_tags):
        matching_parts = entity.body_parts.get_parts_matching_tags(sword.required_tags)
        # matching_parts = [left hand, right hand]
        # Equip on first available part

==============================================================================
MIGRATION FROM OLD SYSTEM
==============================================================================

The old system used:
  - Strict slot names: "L.Hand", "R.Hand", "L.Arm", etc.
  - Equipment type matching: EquipmentType.WEAPON, HELMET, etc.
  - Hard-coded body part checks

The new system:
  - Uses tags for flexible matching
  - Works with ANY anatomy configuration
  - Allows creatures with unusual body plans
  - Enables future damage effects (lose hand → can't grip weapons)

Existing equipment still works! All items have been assigned appropriate
required_tags that match their old equipment types.

==============================================================================
FUTURE ENHANCEMENTS
==============================================================================

The tag system enables several future features:

1. DAMAGE EFFECTS
   - Destroy left hand → can't equip things requiring "grasp"
   - Lose leg → movement penalty increases
   - Break arm → can't use heavy weapons

2. SPECIAL ABILITIES
   - Items requiring "manipulate" tag for precise actions
   - Parts with "magic" tag for casting spells
   - Items requiring "tentacle" or "claw" tags for monsters

3. EXOTIC ANATOMY
   - Serpents with multiple bite slots
   - Centaurs with gear options for both halves
   - Swarms that distribute armor across 4+ bodies

4. EQUIPMENT COMBINATIONS
   - Items requiring 2+ body parts (dual-wielding, two-handed weapons)
   - Equipment chains (wear armor, then gauntlets over it)

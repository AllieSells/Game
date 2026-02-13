#!/usr/bin/env python3
"""
Test script to verify that hands no longer share data due to identical tags.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from components.body_parts import BodyParts, AnatomyType, BodyPartType

def test_hand_tag_uniqueness():
    """Test that hands have unique tags and don't share data."""
    print("🖐️ Testing Hand Tag Uniqueness...")
    
    # Create a body parts system with humanoid anatomy
    body_parts = BodyParts(anatomy_type=AnatomyType.HUMANOID, max_hp=100)
    
    # Get the hand parts
    left_hand = body_parts.body_parts.get(BodyPartType.LEFT_HAND)
    right_hand = body_parts.body_parts.get(BodyPartType.RIGHT_HAND)
    
    if not left_hand or not right_hand:
        print("❌ Hands not found in humanoid anatomy")
        return False
    
    print(f"Left Hand tags: {left_hand.tags}")
    print(f"Right Hand tags: {right_hand.tags}")
    
    # Check that tags are not identical sets
    if left_hand.tags == right_hand.tags:
        print("❌ Hand tags are still identical!")
        return False
    
    # Check that both hands share common functionality tags
    common_expected = {"hand", "grasp", "manipulate", "hold", "use"}
    left_common = left_hand.tags.intersection(common_expected)
    right_common = right_hand.tags.intersection(common_expected)
    
    if left_common != common_expected or right_common != common_expected:
        print("❌ Hands missing expected common functionality tags")
        print(f"Expected: {common_expected}")
        print(f"Left has: {left_common}")
        print(f"Right has: {right_common}")
        return False
    
    # Check that hands have unique identifiers
    if "left" not in left_hand.tags or "left_hand" not in left_hand.tags:
        print("❌ Left hand missing unique identifier tags")
        return False
        
    if "right" not in right_hand.tags or "right_hand" not in right_hand.tags:
        print("❌ Right hand missing unique identifier tags")
        return False
    
    # Check that they don't cross-contaminate unique tags
    if "left" in right_hand.tags or "left_hand" in right_hand.tags:
        print("❌ Right hand has left-specific tags")
        return False
        
    if "right" in left_hand.tags or "right_hand" in left_hand.tags:
        print("❌ Left hand has right-specific tags")
        return False
    
    print("✓ Hands have unique tag sets")
    print("✓ Hands share common functionality tags")
    print("✓ Hands have proper left/right identifiers")
    print("✓ No cross-contamination of unique tags")
    
    # Test that tag sets are independent objects (not shared references)
    original_left_tags = left_hand.tags.copy()
    left_hand.tags.add("test_tag")
    
    if "test_tag" in right_hand.tags:
        print("❌ Tag sets are sharing references!")
        return False
    
    # Clean up test
    left_hand.tags.remove("test_tag")
    print("✓ Tag sets are independent objects")
    
    return True

def test_all_paired_parts():
    """Test that all paired body parts have unique identifiers."""
    print("\n🔍 Testing All Paired Body Parts...")
    
    body_parts = BodyParts(anatomy_type=AnatomyType.HUMANOID, max_hp=100)
    
    paired_parts = [
        (BodyPartType.LEFT_ARM, BodyPartType.RIGHT_ARM, "arm"),
        (BodyPartType.LEFT_HAND, BodyPartType.RIGHT_HAND, "hand"), 
        (BodyPartType.LEFT_LEG, BodyPartType.RIGHT_LEG, "leg"),
        (BodyPartType.LEFT_FOOT, BodyPartType.RIGHT_FOOT, "foot")
    ]
    
    for left_type, right_type, part_name in paired_parts:
        left_part = body_parts.body_parts.get(left_type)
        right_part = body_parts.body_parts.get(right_type)
        
        if not left_part or not right_part:
            print(f"❌ {part_name.title()} parts not found")
            return False
        
        # Check that they have unique tag sets
        if left_part.tags == right_part.tags:
            print(f"❌ {part_name.title()} parts have identical tag sets")
            return False
        
        # Check for proper left/right identifiers
        if "left" not in left_part.tags or f"left_{part_name}" not in left_part.tags:
            print(f"❌ Left {part_name} missing unique identifiers")
            return False
            
        if "right" not in right_part.tags or f"right_{part_name}" not in right_part.tags:
            print(f"❌ Right {part_name} missing unique identifiers")
            return False
        
        print(f"✓ {part_name.title()} parts have unique tags")
    
    return True

if __name__ == "__main__":
    try:
        # Test hand uniqueness
        hands_ok = test_hand_tag_uniqueness()
        
        # Test all paired parts
        all_parts_ok = test_all_paired_parts()
        
        if hands_ok and all_parts_ok:
            print("\n🎯 BODY PART TAG SYSTEM FIXED!")
            print("   ✅ Hands have unique identifiers")
            print("   ✅ All paired parts have unique identifiers") 
            print("   ✅ No data sharing between paired parts")
            print("   ✅ Equipment system can distinguish between parts")
        else:
            print("\n⚠️  Issues detected - see output above")
            
    except Exception as e:
        print(f"\n💥 Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
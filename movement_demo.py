"""
Demo of the movement penalty system based on leg/foot damage
"""
import sys
import os
sys.path.append('c:\\Users\\User\\New folder\\Game')

import entity_factories
from components.body_parts import BodyPartType

def demo_movement_penalties():
    print("🦵 MOVEMENT PENALTY SYSTEM DEMO 🦵\n")
    
    # Create a test orc
    orc = entity_factories.orc
    print(f"Test entity: {orc.name}")
    print(f"Base speed: {orc.speed}")
    print(f"Initial effective speed: {orc.get_effective_speed()}")
    print(f"Movement penalty: {orc.body_parts.get_movement_penalty():.2f}")
    
    print("\n" + "="*50)
    print("Simulating leg damage:")
    
    # Get the left leg
    left_leg = orc.body_parts.get_part(BodyPartType.LEFT_LEG)
    if left_leg:
        print(f"\nLeft leg health: {left_leg.current_hp}/{left_leg.max_hp}")
        
        # Damage the left leg progressively
        for damage in [5, 10, 15]:  # Total damage: 5, 15, 30
            left_leg.take_damage(damage)
            penalty = orc.body_parts.get_movement_penalty()
            effective_speed = orc.get_effective_speed()
            
            if left_leg.is_destroyed:
                print(f"After {damage} more damage: LEFT LEG DESTROYED!")
            else:
                print(f"After {damage} more damage: {left_leg.current_hp}/{left_leg.max_hp} HP")
            
            print(f"  Movement penalty: {penalty:.2f} ({penalty*100:.0f}%)")
            print(f"  Effective speed: {effective_speed} (was {orc.speed})")
            
            # Show what this means for initiative
            if effective_speed > 100:
                print(f"  → Still fast enough for pre-player actions!")
            elif effective_speed == 100:
                print(f"  → Normal speed (same as player)")
            else:
                print(f"  → Slower than player")
            
            print()
    
    print("="*50)
    print("System features:")
    print("✓ Destroyed legs/feet reduce movement speed")
    print("✓ Speed affects initiative (slower enemies act less often)")
    print("✓ Movement blocked entirely if all legs destroyed")
    print("✓ Minimum 10% speed even with severe damage")
    print("✓ Player gets warning message for severe leg injuries")

if __name__ == "__main__":
    demo_movement_penalties()
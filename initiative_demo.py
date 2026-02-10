"""
Demo of the initiative system - shows how fast enemies can act before the player
"""
import sys
import os
sys.path.append('c:\\Users\\User\\New folder\\Game')

import entity_factories

def demo_initiative():
    print("🗡️ INITIATIVE SYSTEM DEMO 🗡️\n")
    
    # Create entities
    player = entity_factories.player
    orc = entity_factories.orc
    shade = entity_factories.shade  
    troll = entity_factories.troll
    
    print("Entity speeds:")
    print(f"  Player: {player.speed}")
    print(f"  Orc: {orc.speed} ⚡ (Fast - can act before player!)")
    print(f"  Shade: {shade.speed} ⚡⚡ (Very fast!)")
    print(f"  Troll: {troll.speed} 🐌 (Slow)")
    
    print("\n" + "="*50)
    print("How it works in combat:")
    print("- When you input a move, fast enemies (speed > 100) get to act first")
    print("- Orcs with 120 speed will sometimes attack before you move")
    print("- Shades with 130 speed attack even more frequently")
    print("- Trolls with 80 speed are slower and more predictable")
    print("\nExample turn sequence:")
    print("1. You press 'move right' →")
    print("2. Game message: 'You sense movement in the shadows...'") 
    print("3. Orc attacks you before you can move!")
    print("4. Your move executes")
    print("5. Regular enemy turns (including slower enemies)")
    
    print("\n" + "="*50)
    print("🎯 Initiative simulation (5 turns):")
    
    # Reset counters
    for entity in [player, orc, shade, troll]:
        entity.initiative_counter = 0
    
    for turn in range(1, 6):
        print(f"\nTurn {turn}:")
        
        # Player acts
        player.initiative_counter += player.speed
        print(f"  Player acts (initiative: {player.initiative_counter})")
        
        # Fast enemies act before regular turn processing
        pre_actions = []
        for name, entity in [("Orc", orc), ("Shade", shade)]:
            if entity.speed > 100:
                entity.initiative_counter += entity.speed
                if entity.initiative_counter >= player.initiative_counter:
                    pre_actions.append(name)
                    entity.initiative_counter -= 100
        
        if pre_actions:
            print(f"  💥 Fast enemies act first: {', '.join(pre_actions)}")
        
        # Regular enemy turns
        regular_actions = []
        for name, entity in [("Orc", orc), ("Shade", shade), ("Troll", troll)]:
            entity.initiative_counter += entity.speed
            while entity.initiative_counter >= 100:
                regular_actions.append(name)
                entity.initiative_counter -= 100
        
        if regular_actions:
            print(f"  ⚔️ Regular enemy turns: {', '.join(regular_actions)}")

if __name__ == "__main__":
    demo_initiative()
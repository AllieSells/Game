import pygame
import random
import numpy as np
from scipy import signal

pygame.mixer.init()

# Pitch variation helper function  
def play_sound_with_pitch_variation(sound, pitch_range=(0.85, 1.15), volume=1.0):
    """
    Play a sound with real pitch variation using scipy resampling.
    Much more reliable than previous attempts.
    """
    try:
        # Get random pitch multiplier
        pitch = random.uniform(*pitch_range)
        
        # Skip processing for very small changes
        if abs(pitch - 1.0) < 0.02:
            sound.set_volume(volume)
            sound.play()
            return
            
        # Get the raw audio data from pygame sound
        sound_array = pygame.sndarray.array(sound)
        
        # Handle both mono and stereo sounds
        if len(sound_array.shape) == 1:
            # Mono sound
            audio_data = sound_array.astype(np.float32)
        else:
            # Stereo sound - process each channel
            audio_data = sound_array.astype(np.float32)
        
        # Apply pitch shift via resampling
        # Higher pitch = shorter sound = fewer samples
        new_length = int(len(audio_data) / pitch)
        
        if len(audio_data.shape) == 1:
            # Mono
            pitched_audio = signal.resample(audio_data, new_length)
        else:
            # Stereo - resample each channel
            pitched_audio = np.zeros((new_length, audio_data.shape[1]), dtype=np.float32)
            for channel in range(audio_data.shape[1]):
                pitched_audio[:, channel] = signal.resample(audio_data[:, channel], new_length)
        
        # Convert back to int16 format for pygame
        pitched_audio = np.clip(pitched_audio, -32768, 32767).astype(np.int16)
        
        # Create new pygame sound from the pitched audio
        pitched_sound = pygame.sndarray.make_sound(pitched_audio)
        pitched_sound.set_volume(volume)
        pitched_sound.play()
        
    except Exception as e:
        # Fallback to normal playback
        try:
            sound.set_volume(volume)
            sound.play()
        except:
            sound.play()

quaff_sound = pygame.mixer.Sound("RP/sfx/quaff.wav")

# Helper functions for global sounds with pitch variation
def play_quaff_sound():
    play_sound_with_pitch_variation(quaff_sound, pitch_range=(0.9, 1.1))

def play_stairs_sound():
    play_sound_with_pitch_variation(stairs_sound, pitch_range=(0.95, 1.05))

def play_lightning_sound():
    play_sound_with_pitch_variation(lightning_sound, pitch_range=(0.9, 1.1))

def play_confusion_sound():
    play_sound_with_pitch_variation(confusion_sound, pitch_range=(0.95, 1.05))

def play_pickup_coin_sound():
    play_sound_with_pitch_variation(pickup_coin_sound, pitch_range=(0.9, 1.1))

def play_level_up_sound():
    play_sound_with_pitch_variation(level_up_sound, pitch_range=(0.95, 1.05))

def play_torch_burns_out_sound():
    play_sound_with_pitch_variation(torch_burns_out_sound, pitch_range=(0.9, 1.1))

# Humanoid death sound
def play_death_sound():
    death_sound = pygame.mixer.Sound("RP/sfx/death/humanoid_death.mp3")
    play_sound_with_pitch_variation(death_sound, volume=0.25)


#Door sounds
def play_door_open_sound():
    door_open_sounds = [
        pygame.mixer.Sound("C:/Users/User/New folder/Game/RP/sfx/doors/open1.wav"),
        pygame.mixer.Sound("C:/Users/User/New folder/Game/RP/sfx/doors/open2.wav"),
        pygame.mixer.Sound("C:/Users/User/New folder/Game/RP/sfx/doors/open3.wav"),
    ]
    sound = random.choice(door_open_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))

def play_door_close_sound():
    door_close_sounds = [
        pygame.mixer.Sound("C:/Users/User/New folder/Game/RP/sfx/doors/close1.wav"),
        pygame.mixer.Sound("C:/Users/User/New folder/Game/RP/sfx/doors/close2.wav"),
        pygame.mixer.Sound("C:/Users/User/New folder/Game/RP/sfx/doors/close3.wav"),
    ]
    sound = random.choice(door_close_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))



stairs_sound = pygame.mixer.Sound("RP/sfx/stairs.wav")

# Dark entity spawn sound
def play_darkness_spawn_sound():
    darkness_spawn_sound = pygame.mixer.Sound("RP/sfx/darkness_spawn/darkness_spawn.mp3")
    # Note: fade_ms not supported with pitch variation, using normal volume
    play_sound_with_pitch_variation(darkness_spawn_sound, pitch_range=(0.8, 1.2), volume=0.25)

def play_torch_pull_sound():
    torch_pull_sounds = [
        pygame.mixer.Sound("RP/sfx/torch_pull/pull1.wav"),
        pygame.mixer.Sound("RP/sfx/torch_pull/pull2.wav"),
    ]

    sound = random.choice(torch_pull_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))

def play_torch_extinguish_sound():
    torch_extinguish_sounds = [
        pygame.mixer.Sound("RP/sfx/burn_out.wav")
    ]
    sound = random.choice(torch_extinguish_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))
    

lightning_sound = pygame.mixer.Sound("RP/sfx/lightning_sound.wav")
confusion_sound = pygame.mixer.Sound("RP/sfx/confusion_cast.wav")
pickup_coin_sound = pygame.mixer.Sound("RP/sfx/pickup_coin.wav")
level_up_sound = pygame.mixer.Sound("RP/sfx/level_up.wav")
torch_burns_out_sound = pygame.mixer.Sound("RP/sfx/burn_out.wav")

def play_chest_open_sound():
    chest_open_sounds = [
        pygame.mixer.Sound("C:/Users/User/New folder/Game/RP/sfx/chest_open/chest_open1.mp3"),
        pygame.mixer.Sound("C:/Users/User/New folder/Game/RP/sfx/chest_open/chest_open2.mp3"),
        pygame.mixer.Sound("C:/Users/User/New folder/Game/RP/sfx/chest_open/chest_open3.mp3"),
    ]
    sound = random.choice(chest_open_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))

def play_transfer_item_sound():
    transfer_item_sounds = [
        pygame.mixer.Sound("RP/sfx/transfer/transfer.wav"),
        pygame.mixer.Sound("RP/sfx/transfer/transfer2.wav"),
        pygame.mixer.Sound("RP/sfx/transfer/transfer3.wav"),
        pygame.mixer.Sound("RP/sfx/transfer/transfer4.wav"),
    ]
    sound = random.choice(transfer_item_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.95, 1.2))

def play_walk_sound():
    if random.random() < 0.5:
        return  # 50% chance to not play a sound for variety
    walk_sounds = [
        pygame.mixer.Sound("RP/sfx/walk/walk1.wav"),
        pygame.mixer.Sound("RP/sfx/walk/walk2.wav"),
        pygame.mixer.Sound("RP/sfx/walk/walk3.wav"),
        pygame.mixer.Sound("RP/sfx/walk/walk4.wav"),
        pygame.mixer.Sound("RP/sfx/walk/walk5.wav"),
    ]
    sound = random.choice(walk_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.25))
    
def play_attack_sound_weapon_to_no_armor():
    #swing_sounds = [
    #    pygame.mixer.Sound("RP/sfx/weapon_swing/swing1.wav"),
    #    pygame.mixer.Sound("RP/sfx/weapon_swing/swing2.wav"),
    #    pygame.mixer.Sound("RP/sfx/weapon_swing/swing3.wav"),
    #]

    attack_sounds = [
        pygame.mixer.Sound("RP/sfx/hit_weapon_no_armor/hit1.wav"),
        pygame.mixer.Sound("RP/sfx/hit_weapon_no_armor/hit2.wav"),
        pygame.mixer.Sound("RP/sfx/hit_weapon_no_armor/hit3.wav"),
    ]

    #sound = random.choice(swing_sounds)
    #sound.play()
    sound = random.choice(attack_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.25))


def play_attack_sound_weapon_to_armor():
    #swing_sounds = [
    #    pygame.mixer.Sound("RP/sfx/weapon_swing/swing1.wav"),
    #    pygame.mixer.Sound("RP/sfx/weapon_swing/swing2.wav"),
    #    pygame.mixer.Sound("RP/sfx/weapon_swing/swing3.wav"),
    #]
    attack_sounds = [
        pygame.mixer.Sound("RP/sfx/hit_weapon_armor/hit1.wav"),
        pygame.mixer.Sound("RP/sfx/hit_weapon_armor/hit2.wav"),
        pygame.mixer.Sound("RP/sfx/hit_weapon_armor/hit3.wav"),
    ]
    #sound = random.choice(swing_sounds)
    #sound.play()

    sound = random.choice(attack_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.25))

## EQUIP

# Leather equip

def play_equip_leather_sound():
    equip_leather_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/leather/equip1.mp3")
    ]
    sound = random.choice(equip_leather_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)

def play_unequip_leather_sound():
    unequip_leather_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/leather/unequip1.mp3")
    ]
    sound = random.choice(unequip_leather_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)

def pick_up_leather_sound():
    pick_up_leather_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for leather items
        pygame.mixer.Sound("RP/sfx/equip/leather/unequip1.mp3")
    ]
    sound = random.choice(pick_up_leather_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=0.25)

def drop_leather_sound():
    drop_leather_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/leather/unequip1.mp3")
    ]
    sound = random.choice(drop_leather_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)


# Glass equip
def play_equip_glass_sound():
    equip_glass_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/glass/equip1.mp3")
    ]
    sound = random.choice(equip_glass_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def play_unequip_glass_sound():
    unequip_glass_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/glass/unequip1.mp3")
    ]
    sound = random.choice(unequip_glass_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def pick_up_glass_sound():
    pick_up_glass_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for glass items
        pygame.mixer.Sound("RP/sfx/equip/glass/equip1.mp3")
    ]
    sound = random.choice(pick_up_glass_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=1.0)

def drop_glass_sound():
    drop_glass_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/glass/unequip1.mp3")
    ]
    sound = random.choice(drop_glass_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)
    
# Paper equip
def play_equip_paper_sound():
    equip_paper_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/paper/equip1.mp3")
    ]
    sound = random.choice(equip_paper_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=3)

def play_unequip_paper_sound():
    unequip_paper_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/paper/unequip1.mp3")
    ]
    sound = random.choice(unequip_paper_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=3)

def pick_up_paper_sound():
    pick_up_paper_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for paper items
        pygame.mixer.Sound("RP/sfx/equip/paper/equip1.mp3")
    ]
    sound = random.choice(pick_up_paper_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=3)

def drop_paper_sound():
    drop_paper_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/paper/equip1.mp3")
    ]
    sound = random.choice(drop_paper_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=3)

# coin equip
def play_equip_coin_sound():
    equip_coin_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/coin/1coin.mp3")
    ]
    sound = random.choice(equip_coin_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def play_unequip_coin_sound():
    unequip_coin_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/coin/1coin.mp3")
    ]
    sound = random.choice(unequip_coin_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def pick_up_coin_sound():
    pick_up_coin_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for coin items
        pygame.mixer.Sound("RP/sfx/equip/coin/1coin.mp3")
    ]
    sound = random.choice(pick_up_coin_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=1.0)

def drop_coin_sound():
    drop_coin_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/coin/1coin.mp3")
    ]
    sound = random.choice(drop_coin_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

# many coins
def play_equip_manycoins_sound():
    equip_manycoins_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/coin/manycoins.mp3")
    ]
    sound = random.choice(equip_manycoins_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def play_unequip_manycoins_sound():
    unequip_manycoins_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/coin/manycoins.mp3")
    ]
    sound = random.choice(unequip_manycoins_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def pick_up_manycoins_sound():
    pick_up_manycoins_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for many coins items
        pygame.mixer.Sound("RP/sfx/equip/coin/manycoins.mp3")
    ]
    sound = random.choice(pick_up_manycoins_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=1.0)

def drop_manycoins_sound():
    drop_manycoins_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/coin/manycoins.mp3")
    ]
    sound = random.choice(drop_manycoins_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

# Wood sounds
def pick_up_wood_sound():
    pick_up_wood_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for wood items
        pygame.mixer.Sound("RP/sfx/equip/wood/pickup1.mp3")
    ]
    sound = random.choice(pick_up_wood_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=1.0)

def drop_wood_sound():
    drop_wood_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/wood/drop1.mp3")
    ]
    sound = random.choice(drop_wood_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

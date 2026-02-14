import pygame
import random
import numpy as np
from scipy import signal

pygame.mixer.init()

# Pitch variation helper function  
def play_sound_with_pitch_variation(sound, pitch_range=(0.85, 1.15), volume=1.0, fade_ms=0):
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
            if fade_ms > 0:
                sound.play(fade_ms=fade_ms)
            else:
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
        if fade_ms > 0:
            pitched_sound.play(fade_ms=fade_ms)
        else:
            pitched_sound.play()
        
    except Exception as e:
        # Fallback to normal playback
        try:
            sound.set_volume(volume)
            if fade_ms > 0:
                sound.play(fade_ms=fade_ms)
            else:
                sound.play()
        except:
            sound.play()

quaff_sound = pygame.mixer.Sound("RP/sfx/quaff.wav")

# Helper functions for global sounds with pitch variation
def play_quaff_sound():
    play_sound_with_pitch_variation(quaff_sound, pitch_range=(0.9, 1.3), volume=0.5)

def play_stairs_sound():
    play_sound_with_pitch_variation(stairs_sound, pitch_range=(0.95, 1.05), fade_ms=1000)

# Fade out lightning sound over 0.5 second with pitch variation
def play_lightning_sound():
    play_sound_with_pitch_variation(lightning_sound, pitch_range=(0.5, 1.5), volume=0.5, fade_ms=6000)

def play_confusion_sound():
    play_sound_with_pitch_variation(confusion_sound, pitch_range=(0.5, 1.5), volume=0.5, fade_ms=1000)

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

# Menu Sounds
def play_menu_move_sound():
    menu_move_sounds = [
        #pygame.mixer.Sound("RP/sfx/buttons/button1.wav"),
        pygame.mixer.Sound("RP/sfx/buttons/button2.wav"),
    ]
    sound = random.choice(menu_move_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.15), volume=1)

#UI move sound
def play_ui_move_sound():
    sound = pygame.mixer.Sound("RP/sfx/buttons/UI/button1.wav")
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.5), volume=1.0)


#Door sounds
def play_door_open_sound():
    door_open_sounds = [
        pygame.mixer.Sound("RP/sfx/doors/open1.wav"),
        pygame.mixer.Sound("RP/sfx/doors/open2.wav"),
        pygame.mixer.Sound("RP/sfx/doors/open3.wav"),
    ]
    sound = random.choice(door_open_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))

def play_door_close_sound():
    door_close_sounds = [
        pygame.mixer.Sound("RP/sfx/doors/close1.wav"),
        pygame.mixer.Sound("RP/sfx/doors/close2.wav"),
        pygame.mixer.Sound("RP/sfx/doors/close3.wav"),
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
        pygame.mixer.Sound("RP/sfx/chest_open/chest_open1.mp3"),
        pygame.mixer.Sound("RP/sfx/chest_open/chest_open2.mp3"),
        pygame.mixer.Sound("RP/sfx/chest_open/chest_open3.mp3"),
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
    if random.random() < 0.3:
        return  # 30% chance to not play a sound for variety
    walk_sounds = [
        pygame.mixer.Sound("RP/sfx/walk/stone/walk1.wav"),
        pygame.mixer.Sound("RP/sfx/walk/stone/walk2.wav"),
        pygame.mixer.Sound("RP/sfx/walk/stone/walk3.wav"),
        pygame.mixer.Sound("RP/sfx/walk/stone/walk4.wav"),
        pygame.mixer.Sound("RP/sfx/walk/stone/walk5.wav"),
        pygame.mixer.Sound("RP/sfx/walk/stone/walk6.wav"),
        pygame.mixer.Sound("RP/sfx/walk/stone/walk7.wav"),
        pygame.mixer.Sound("RP/sfx/walk/stone/walk8.wav"),
        pygame.mixer.Sound("RP/sfx/walk/stone/walk9.wav"),
        pygame.mixer.Sound("RP/sfx/walk/stone/walk10.wav"),
    ]
    sound = random.choice(walk_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.5), volume=0.5)

def play_block_sound():
    block_sounds = [
        pygame.mixer.Sound("RP/sfx/hit_block/block1.mp3"),
        pygame.mixer.Sound("RP/sfx/hit_block/block2.mp3"),
        pygame.mixer.Sound("RP/sfx/hit_block/block3.mp3"),
    ]
    sound = random.choice(block_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.2), volume=0.5)

def play_attack_sound_finishing_blow():
    finishing_blow_sounds = [
        pygame.mixer.Sound("RP/sfx/hit_final_blow/finalblow1.wav"),
        pygame.mixer.Sound("RP/sfx/hit_final_blow/finalblow2.wav"),
        pygame.mixer.Sound("RP/sfx/hit_final_blow/finalblow3.wav"),
    ]
    sound = random.choice(finishing_blow_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.2), volume=0.5)

def play_miss_sound():
    miss_sounds = [
        pygame.mixer.Sound("RP/sfx/hit_miss/miss1.wav"),
        pygame.mixer.Sound("RP/sfx/hit_miss/miss2.wav"),
    ]
    sound = random.choice(miss_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.2), volume=1.0)
    
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
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.5)
    
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
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=.25)

def drop_wood_sound():
    drop_wood_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/wood/drop1.mp3")
    ]
    sound = random.choice(drop_wood_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.1), volume=.25)

# Blade sounds
def pick_up_blade_sound():
    pick_up_blade_sounds = [
            pygame.mixer.Sound("RP/sfx/equip/blade/pickup1.wav"),
            pygame.mixer.Sound("RP/sfx/equip/blade/pickup2.wav")
        ]
    sound = random.choice(pick_up_blade_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=0.25)
def drop_blade_sound():
    drop_blade_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/blade/drop1.wav"),
        pygame.mixer.Sound("RP/sfx/equip/blade/drop2.wav"),
        pygame.mixer.Sound("RP/sfx/equip/blade/drop3.wav")
    ]
    sound = random.choice(drop_blade_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.1), volume=0.25)
def play_equip_blade_sound():
    equip_blade_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/blade/equip1.wav"),
        pygame.mixer.Sound("RP/sfx/equip/blade/equip2.wav")
    ]
    sound = random.choice(equip_blade_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)
def play_unequip_blade_sound():
    unequip_blade_sounds = [
        pygame.mixer.Sound("RP/sfx/equip/blade/unequip1.wav"),
        pygame.mixer.Sound("RP/sfx/equip/blade/unequip2.wav")
    ]
    sound = random.choice(unequip_blade_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)

# AMBIENT SOUND SYSTEM - Generic and Modular

class AmbientSoundType:
    """Configuration for an ambient sound type."""
    def __init__(self, name: str, sound_file: str, entity_names: list, map_type: str = None, 
                 proximity_threshold: int = 5, base_volume: float = 0.3):
        self.name = name
        self.sound_file = sound_file  
        self.entity_names = entity_names  # List of entity names that produce this ambient
        self.map_type = map_type  # Optional map type filter (e.g. "dungeon")
        self.proximity_threshold = proximity_threshold
        self.base_volume = base_volume

# Registry of ambient sound types
AMBIENT_TYPES = {
    'fire': AmbientSoundType(
        name='fire',
        sound_file='RP/sfx/loops/fire/fire_loop.wav',
        entity_names=['Campfire', 'Bonfire'],
        proximity_threshold=5,
        base_volume=0.3
    ),
    'dungeon': AmbientSoundType(
        name='dungeon',
        sound_file='RP/sfx/loops/dungeon/dungeon_loop.wav',
        entity_names=[None],
        map_type="dungeon",
        proximity_threshold=999,  # Always play in dungeons
        base_volume=0.5
    ),
    'menu': AmbientSoundType(
        name='menu',
        sound_file='RP/sfx/loops/menu/menu.wav',  # Reuse dungeon loop for now
        entity_names=[None],
        map_type=None,
        proximity_threshold=999,  # Always play when active
        base_volume=0.2
    ),
    # Future ambient types can be added here:
    # 'water': AmbientSoundType(
    #     name='water', 
    #     sound_file='RP/sfx/loops/water/water_loop.wav',
    #     entity_names=['Fountain', 'River', 'Waterfall'],
    #     proximity_threshold=8,
    #     base_volume=0.2
    # ),
}

class AmbientSoundManager:
    """Generic manager for ambient loop sounds."""
    def __init__(self):
        self.active_ambients = {}  # ambient_type -> {'channel': channel, 'sound': sound, 'active': bool}
        
    def is_player_near_ambient_source(self, player, entity, ambient_type, game_map) -> tuple[bool, float]:
        """Proximity check for entity-based ambient sounds using ray-casting."""
        if ambient_type not in AMBIENT_TYPES:
            return False, 0.0
            
        config = AMBIENT_TYPES[ambient_type]
        
        # This method is only for entity-based ambiance (map-based handled separately)
        if config.entity_names == [None]:
            return False, 0.0
        
        # Check if entity produces this ambient type
        if not hasattr(entity, 'name') or entity.name not in config.entity_names:
            return False, 0.0
            
        # Basic distance check first
        dx = abs(player.x - entity.x)
        dy = abs(player.y - entity.y) 
        distance = max(dx, dy)
        
        if distance > config.proximity_threshold:
            return False, 0.0
        
        try:
            # Ray-cast from source to player
            sound_strength = _ray_cast_sound(
                entity.x, entity.y,
                player.x, player.y,
                game_map
            )
            
            # Ambient needs at least 10% sound strength to be audible
            can_hear = sound_strength >= 0.1
            return can_hear, sound_strength
            
        except Exception:
            # Fallback to simple distance
            can_hear = distance <= config.proximity_threshold
            return can_hear, 1.0 if can_hear else 0.0
    
    def manage_ambient_loop(self, ambient_type: str, should_play: bool, sound_strength: float = 1.0):
        """Start, stop, or adjust volume of ambient loop."""
        if ambient_type not in AMBIENT_TYPES:
            return
            
        config = AMBIENT_TYPES[ambient_type]
        target_volume = config.base_volume * sound_strength if should_play else 0.0
        
        if ambient_type not in self.active_ambients:
            self.active_ambients[ambient_type] = {'channel': None, 'sound': None, 'active': False}
        
        ambient_state = self.active_ambients[ambient_type]
        
        if should_play and not ambient_state['active']:
            self.start_ambient_loop(ambient_type, target_volume)
        elif not should_play and ambient_state['active']:
            self.stop_ambient_loop(ambient_type)
        elif should_play and ambient_state['active']:
            # Adjust volume of existing loop
            if ambient_state['channel'] and ambient_state['channel'].get_busy():
                ambient_state['channel'].set_volume(target_volume)
            else:
                # Restart if channel died
                ambient_state['active'] = False
                self.start_ambient_loop(ambient_type, target_volume)
    
    def start_ambient_loop(self, ambient_type: str, initial_volume: float):
        """Start looping ambient sound at specified volume."""
        if ambient_type not in AMBIENT_TYPES:
            return
            
        config = AMBIENT_TYPES[ambient_type]
        
        # Initialize ambient state if it doesn't exist
        if ambient_type not in self.active_ambients:
            self.active_ambients[ambient_type] = {'channel': None, 'sound': None, 'active': False}
            
        ambient_state = self.active_ambients[ambient_type]
        
        try:
            if ambient_state['sound'] is None:
                ambient_state['sound'] = pygame.mixer.Sound(config.sound_file)
            
            ambient_state['channel'] = ambient_state['sound'].play(-1)  # Loop indefinitely
            ambient_state['channel'].set_volume(initial_volume)
            ambient_state['active'] = True
            
        except Exception as e:
            print(f"Could not start {ambient_type} loop: {e}")
    
    def stop_ambient_loop(self, ambient_type: str):
        """Stop ambient loop with fade out."""
        if ambient_type not in self.active_ambients:
            return
            
        ambient_state = self.active_ambients[ambient_type]
        
        if ambient_state['channel'] is not None:
            ambient_state['channel'].fadeout(500)  # Fade out over 0.5 seconds
            ambient_state['channel'] = None
            ambient_state['active'] = False
    
    def update_ambient_sounds(self, player, entities, game_map):
        """Update all ambient sounds based on player proximity."""
        # Check each ambient type (excluding menu which is manually controlled)
        for ambient_type in AMBIENT_TYPES:
            if ambient_type == 'menu':  # Skip menu - it's manually controlled
                continue
                
            config = AMBIENT_TYPES[ambient_type]
            player_near_source = False
            max_sound_strength = 0.0
            
            # Handle map-based ambiance (entity_names=[None])
            if config.entity_names == [None]:
                # Check map type filter
                if config.map_type is None or (hasattr(game_map, 'type') and game_map.type == config.map_type):
                    player_near_source = True
                    max_sound_strength = 1.0  # Full strength for map-based ambiance
            else:
                # Handle entity-based ambiance
                for entity in entities:
                    can_hear, sound_strength = self.is_player_near_ambient_source(
                        player, entity, ambient_type, game_map
                    )
                    if can_hear:
                        player_near_source = True
                        max_sound_strength = max(max_sound_strength, sound_strength)
                    
            self.manage_ambient_loop(ambient_type, player_near_source, max_sound_strength)

# Global ambient sound manager instance
_ambient_manager = AmbientSoundManager()

# Global menu state tracking
_menu_ambience_active = False

# CONVENIENCE FUNCTIONS - Maintain backwards compatibility

# CONVENIENCE FUNCTIONS - Backwards compatibility

def _ray_cast_sound(start_x, start_y, end_x, end_y, game_map):
    """Ray-cast for sound propagation with material attenuation."""
    
    # print(f"\nRay-casting from ({start_x}, {start_y}) to ({end_x}, {end_y})")
    
    # Bresenham's line algorithm for ray-casting
    dx = abs(end_x - start_x)
    dy = abs(end_y - start_y)
    
    x, y = start_x, start_y
    
    x_inc = 1 if start_x < end_x else -1
    y_inc = 1 if start_y < end_y else -1
    
    error = dx - dy
    
    sound_strength = 1.0  # Starting sound strength
    distance = 0
    obstacles_encountered = []  # Track what we hit for debugging
    
    while True:
        # Check if we've reached the target
        if x == end_x and y == end_y:
            break
            
        # Check bounds
        if not game_map.in_bounds(x, y):
            # print(f"Out of bounds at ({x}, {y})")
            return 0.0  # Sound doesn't reach if out of bounds
            
        # Get tile properties for sound physics
        tile_transparent = game_map.tiles["transparent"][x, y]
        
        if not tile_transparent:
            # Hit a wall - calculate sound attenuation
            try:
                tile_name = game_map.tiles["name"][x, y]
                obstacles_encountered.append(f"{tile_name}@({x},{y})")
                # print(f"Hit obstacle at ({x}, {y}): {tile_name}")
                
                # Material-based sound attenuation
                if "Wall" in tile_name:  # Handles "Wall", "Stone Wall", etc.
                    sound_strength *= 0.15  # Walls block some sound (85% blocked)
                    # print(f"Wall attenuation: {sound_strength:.2f}")
                elif tile_name == "Door":
                    sound_strength *= 0.3  # Doors allow some sound through
                    # print(f"Door attenuation: {sound_strength:.2f}")
                elif tile_name == "Open Door":
                    sound_strength *= 0.9  # Open doors barely affect sound
                    # print(f"Open Door attenuation: {sound_strength:.2f}")
                else:
                    sound_strength *= 0.2  # Unknown solid materials
                    # print(f"Unknown material ({tile_name}) attenuation: {sound_strength:.2f}")
                    
                # If sound is too weak, it doesn't propagate further
                if sound_strength < 0.05:
                    # print(f"Sound too weak, stopping propagation")
                    return 0.0
                    
            except Exception as e:
                # print(f"Exception getting tile info: {e}")
                sound_strength *= 0.1  # Default heavy attenuation for unknown walls
        
        # Distance-based attenuation (moderate falloff)
        distance += 1
        distance_attenuation = 1.0 / (1.0 + distance * 0.4)  # Between moderate and steep falloff
        
        # Calculate next point
        e2 = 2 * error
        if e2 > -dy:
            error -= dy
            x += x_inc
        if e2 < dx:
            error += dx
            y += y_inc
    
    final_strength = sound_strength * distance_attenuation
    # print(f"Obstacles: {obstacles_encountered if obstacles_encountered else 'None'}")
    # print(f"Final sound strength: {final_strength:.2f}\n")
    return final_strength



# CONVENIENCE FUNCTIONS - Backwards compatibility

# def start_dungeon_loop(initial_volume=0.2):\n#     \"\"\"Legacy wrapper - start dungeon ambient sound.\"\"\"\n#     _ambient_manager.start_ambient_loop('dungeon', initial_volume)\n\n# def stop_dungeon_loop():\n#     \"\"\"Legacy wrapper - stop dungeon ambient sound.\"\"\"\n#     _ambient_manager.stop_ambient_loop('dungeon')

# def update_fire_ambiance(player, entities, game_map):
#     """Legacy wrapper - use ambient manager to update fire sounds."""
#     _ambient_manager.update_ambient_sounds(player, entities, game_map)

# def start_fire_loop(initial_volume=0.3):
#     """Legacy wrapper - start fire ambient sound."""
#     _ambient_manager.start_ambient_loop('fire', initial_volume)

# def stop_fire_loop():
#     """Legacy wrapper - stop fire ambient sound."""
#     _ambient_manager.stop_ambient_loop('fire')

# NEW GENERIC API - Use these for new ambient types

def update_all_ambient_sounds(player, entities, game_map):
    """Update all registered ambient sounds based on player proximity."""
    _ambient_manager.update_ambient_sounds(player, entities, game_map)

def add_ambient_type(name: str, sound_file: str, entity_names: list, 
                    proximity_threshold: int = 5, base_volume: float = 0.3):
    """Register a new ambient sound type."""
    AMBIENT_TYPES[name] = AmbientSoundType(
        name, sound_file, entity_names, proximity_threshold, base_volume
    )

def start_ambient_sound(ambient_type: str, volume: float = None):
    """Start an ambient sound loop."""
    if ambient_type in AMBIENT_TYPES:
        vol = volume if volume is not None else AMBIENT_TYPES[ambient_type].base_volume
        _ambient_manager.start_ambient_loop(ambient_type, vol)

def stop_ambient_sound(ambient_type: str):
    """Stop an ambient sound loop."""
    global _menu_ambience_active
    if ambient_type == 'menu':
        _menu_ambience_active = False
    _ambient_manager.stop_ambient_loop(ambient_type)

def start_menu_ambience():
    """Start menu ambience if not already playing."""
    global _menu_ambience_active
    if not _menu_ambience_active:
        _menu_ambience_active = True
        start_ambient_sound('menu', volume=0.75)

def stop_menu_ambience():
    """Stop menu ambience."""
    global _menu_ambience_active
    if _menu_ambience_active:
        _menu_ambience_active = False
        stop_ambient_sound('menu')

def is_menu_ambience_playing():
    """Check if menu ambience is currently playing."""
    return _menu_ambience_active



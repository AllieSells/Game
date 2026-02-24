import sounddevice as sd
import soundfile as sf
import random
import numpy as np
from scipy import signal
from scipy.signal import butter, lfilter, lfilter_zi
import threading
from typing import Optional, Tuple, List, Dict
import time
import queue
import os

# Global audio cache to avoid reloading files repeatedly
_audio_cache = {}

class AudioMixer:
    """Handles mixing multiple audio streams together."""
    
    def __init__(self, samplerate: int = 44100, blocksize: int = 256):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.playing_sounds: List[Dict] = []  # List of currently playing sounds
        self.loop_sounds: List[Dict] = []     # List of looping sounds
        self.lock = threading.Lock()
        self.stream = None
        self.running = False
        
        # Sound muffling parameters
        self.muffling_enabled = False
        self.muffling_cutoff = 20000  # Hz - start with no muffling (full frequency range)
        self.muffling_order = 4  # Filter order for smoothness
        
        # Filter state for real-time processing
        self.filter_zi_l = None  # Left channel filter state
        self.filter_zi_r = None  # Right channel filter state  
        self.current_filter_b = None
        self.current_filter_a = None
        self.last_cutoff = 20000
        
        self.start_stream()
    
    def start_stream(self):
        """Start the audio output stream."""
        try:
            self.stream = sd.OutputStream(
                samplerate=self.samplerate,
                blocksize=self.blocksize,
                channels=2,  # Stereo output
                callback=self._audio_callback,
                dtype=np.float32
            )
            self.stream.start()
            self.running = True
        except Exception as e:
            print(f"Error starting audio stream: {e}")
    
    def _audio_callback(self, outdata, frames, time, status):
        """Audio callback that mixes all active sounds."""
        outdata.fill(0)  # Start with silence
        
        with self.lock:
            # Process one-shot sounds
            sounds_to_remove = []
            for i, sound_info in enumerate(self.playing_sounds):
                remaining_frames = len(sound_info['data']) - sound_info['position']
                if remaining_frames <= 0:
                    sounds_to_remove.append(i)
                    continue
                
                # Get the audio data for this block
                end_pos = min(sound_info['position'] + frames, len(sound_info['data']))
                audio_chunk = sound_info['data'][sound_info['position']:end_pos]
                
                # Apply volume
                if sound_info['volume'] != 1.0:
                    audio_chunk = audio_chunk * sound_info['volume']
                
                # Handle mono to stereo conversion
                if len(audio_chunk.shape) == 1:
                    # Mono - duplicate to both channels
                    chunk_len = len(audio_chunk)
                    stereo_chunk = np.zeros((chunk_len, 2), dtype=np.float32)
                    stereo_chunk[:, 0] = audio_chunk
                    stereo_chunk[:, 1] = audio_chunk
                    audio_chunk = stereo_chunk
                elif audio_chunk.shape[1] == 1:
                    # Mono in 2D array - convert to stereo
                    audio_chunk = np.repeat(audio_chunk, 2, axis=1)
                
                # Mix into output (add to existing audio)
                output_len = min(len(audio_chunk), len(outdata))
                outdata[:output_len] += audio_chunk[:output_len]
                
                sound_info['position'] = end_pos
            
            # Remove finished sounds
            for i in reversed(sounds_to_remove):
                del self.playing_sounds[i]
            
            # Process looping sounds
            for sound_info in self.loop_sounds:
                if not sound_info.get('active', True):
                    continue
                    
                frames_needed = frames
                output_pos = 0
                
                while frames_needed > 0 and output_pos < len(outdata):
                    remaining_in_loop = len(sound_info['data']) - sound_info['position']
                    
                    if remaining_in_loop <= 0:
                        sound_info['position'] = 0  # Loop back to start
                        remaining_in_loop = len(sound_info['data'])
                    
                    # Get audio chunk
                    chunk_size = min(frames_needed, remaining_in_loop)
                    end_pos = sound_info['position'] + chunk_size
                    audio_chunk = sound_info['data'][sound_info['position']:end_pos]
                    
                    # Apply volume
                    if sound_info['volume'] != 1.0:
                        audio_chunk = audio_chunk * sound_info['volume']
                    
                    # Handle mono to stereo conversion
                    if len(audio_chunk.shape) == 1:
                        chunk_len = len(audio_chunk)
                        stereo_chunk = np.zeros((chunk_len, 2), dtype=np.float32)
                        stereo_chunk[:, 0] = audio_chunk
                        stereo_chunk[:, 1] = audio_chunk
                        audio_chunk = stereo_chunk
                    elif audio_chunk.shape[1] == 1:
                        audio_chunk = np.repeat(audio_chunk, 2, axis=1)
                    
                    # Mix into output
                    output_end = min(output_pos + len(audio_chunk), len(outdata))
                    actual_len = output_end - output_pos
                    outdata[output_pos:output_end] += audio_chunk[:actual_len]
                    
                    sound_info['position'] = end_pos
                    frames_needed -= actual_len
                    output_pos += actual_len
        
        # Apply sound muffling (low-pass filter) if enabled
        if self.muffling_enabled and self.muffling_cutoff < 20000:
            try:
                outdata[:] = self._apply_lowpass_filter(outdata, self.muffling_cutoff)
            except Exception as e:
                print(f"Error applying muffling filter: {e}")
        
        # Prevent clipping
        np.clip(outdata, -1.0, 1.0, out=outdata)
    
    def play_sound(self, audio_data: np.ndarray, volume: float = 1.0):
        """Add a sound to the mixer for playback."""
        with self.lock:
            self.playing_sounds.append({
                'data': audio_data.copy(),
                'position': 0,
                'volume': volume
            })
    
    def start_loop(self, audio_data: np.ndarray, loop_id: str, volume: float = 1.0):
        """Start a looping sound."""
        with self.lock:
            # Remove any existing loop with this ID
            self.loop_sounds = [s for s in self.loop_sounds if s.get('id') != loop_id]
            
            # Add new loop
            self.loop_sounds.append({
                'id': loop_id,
                'data': audio_data.copy(),
                'position': 0,
                'volume': volume,
                'active': True
            })
    
    def stop_loop(self, loop_id: str):
        """Stop a looping sound."""
        with self.lock:
            for sound_info in self.loop_sounds:
                if sound_info.get('id') == loop_id:
                    sound_info['active'] = False
    
    def set_loop_volume(self, loop_id: str, volume: float):
        """Set volume of a looping sound."""
        with self.lock:
            for sound_info in self.loop_sounds:
                if sound_info.get('id') == loop_id:
                    sound_info['volume'] = max(0.0, min(1.0, volume))
    
    def _apply_lowpass_filter(self, audio_data: np.ndarray, cutoff: float) -> np.ndarray:
        """Apply low-pass filter for sound muffling effect with proper state management."""
        try:
            # Skip filtering if cutoff is too high (no effect)
            if cutoff >= 19000:
                return audio_data
                
            nyquist = 0.5 * self.samplerate
            normalized_cutoff = min(cutoff / nyquist, 0.99)  # Ensure cutoff is below Nyquist
            
            # Only recalculate filter if cutoff changed significantly
            if (self.current_filter_b is None or 
                abs(cutoff - self.last_cutoff) > 50):
                
                # Design Butterworth low-pass filter
                self.current_filter_b, self.current_filter_a = butter(
                    self.muffling_order, normalized_cutoff, btype='low'
                )
                
                # Initialize filter states for stereo channels
                zi = lfilter_zi(self.current_filter_b, self.current_filter_a)
                
                if len(audio_data.shape) == 1:
                    # Mono
                    self.filter_zi_l = zi * audio_data[0] if len(audio_data) > 0 else zi
                    self.filter_zi_r = None
                else:
                    # Stereo
                    self.filter_zi_l = zi * audio_data[0, 0] if len(audio_data) > 0 else zi
                    self.filter_zi_r = zi * audio_data[0, 1] if len(audio_data) > 0 else zi
                
                self.last_cutoff = cutoff
            
            # Apply filter with state preservation
            if len(audio_data.shape) == 1:
                # Mono
                if self.filter_zi_l is not None:
                    filtered, self.filter_zi_l = lfilter(
                        self.current_filter_b, self.current_filter_a, 
                        audio_data, zi=self.filter_zi_l
                    )
                else:
                    filtered = lfilter(self.current_filter_b, self.current_filter_a, audio_data)
            else:
                # Stereo - filter each channel separately with state
                filtered = np.zeros_like(audio_data)
                
                # Left channel
                if self.filter_zi_l is not None:
                    filtered[:, 0], self.filter_zi_l = lfilter(
                        self.current_filter_b, self.current_filter_a,
                        audio_data[:, 0], zi=self.filter_zi_l
                    )
                else:
                    filtered[:, 0] = lfilter(self.current_filter_b, self.current_filter_a, audio_data[:, 0])
                
                # Right channel  
                if self.filter_zi_r is not None:
                    filtered[:, 1], self.filter_zi_r = lfilter(
                        self.current_filter_b, self.current_filter_a,
                        audio_data[:, 1], zi=self.filter_zi_r
                    )
                else:
                    filtered[:, 1] = lfilter(self.current_filter_b, self.current_filter_a, audio_data[:, 1])
            
            return filtered.astype(np.float32)
            
        except Exception as e:
            print(f"Filter error: {e}")
            # Reset filter state on error
            self.filter_zi_l = None
            self.filter_zi_r = None
            self.current_filter_b = None
            self.current_filter_a = None
            return audio_data  # Return original on error
    
    def set_muffling(self, enabled: bool, cutoff: float = 2000):
        """Enable/disable sound muffling with specified cutoff frequency.
        
        Args:
            enabled: Whether muffling is active
            cutoff: Low-pass filter cutoff frequency in Hz (lower = more muffled)
                   Typical values: 20000 (no muffling) -> 500 (heavily muffled)
        """
        with self.lock:
            old_enabled = self.muffling_enabled
            self.muffling_enabled = enabled
            self.muffling_cutoff = max(100, min(cutoff, 20000))  # Clamp to reasonable range
            
            # Reset filter states when toggling muffling to avoid artifacts
            if old_enabled != enabled:
                self.filter_zi_l = None
                self.filter_zi_r = None
                self.current_filter_b = None
                self.current_filter_a = None
    
    def get_muffling_state(self) -> tuple[bool, float]:
        """Get current muffling state (enabled, cutoff_frequency)."""
        with self.lock:
            return self.muffling_enabled, self.muffling_cutoff
    
    def cleanup(self):
        """Stop the mixer and clean up resources."""
        if self.stream:
            self.stream.stop()
            self.stream.close()
        self.running = False

# Global mixer instance
_mixer = AudioMixer()

class LoopingSound:
    """Class to handle looping sounds with volume control."""
    
    def __init__(self, sound: 'Sound', loop_id: str):
        self.sound = sound
        self.loop_id = loop_id
        self.volume = 1.0
        self.playing = False
        
    def play(self, volume: float = 1.0):
        """Start playing the looping sound."""
        self.volume = volume
        self.playing = True
        _mixer.start_loop(self.sound.data, self.loop_id, volume)
    
    def set_volume(self, volume: float):
        """Update the volume of the looping sound."""
        self.volume = max(0.0, min(1.0, volume))
        if self.playing:
            _mixer.set_loop_volume(self.loop_id, self.volume)
    
    def stop(self):
        """Stop the looping sound."""
        if self.playing:
            _mixer.stop_loop(self.loop_id)
            self.playing = False

class Sound:
    """Sound class to mimic pygame.mixer.Sound interface."""
    
    def __init__(self, filename: str):
        self.filename = filename
        self.data, self.original_samplerate = self._load_audio(filename)
        
        # Resample to mixer's sample rate if needed
        if self.original_samplerate != _mixer.samplerate:
            self.data = self._resample_audio(self.data, self.original_samplerate, _mixer.samplerate)
        
        self.samplerate = _mixer.samplerate
        self.volume = 1.0
    
    def _resample_audio(self, audio_data: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
        """Resample audio to target sample rate."""
        if from_sr == to_sr:
            return audio_data
        
        try:
            # Calculate new length
            new_length = int(len(audio_data) * to_sr / from_sr)
            
            if len(audio_data.shape) == 1:
                # Mono
                resampled = signal.resample(audio_data, new_length)
            else:
                # Stereo - resample each channel
                resampled = np.zeros((new_length, audio_data.shape[1]), dtype=np.float32)
                for channel in range(audio_data.shape[1]):
                    resampled[:, channel] = signal.resample(audio_data[:, channel], new_length)
            
            return resampled.astype(np.float32)
        except Exception as e:
            print(f"Error resampling audio: {e}")
            return audio_data
    
    def _load_audio(self, filename: str) -> Tuple[np.ndarray, int]:
        """Load audio file using soundfile."""
        if filename in _audio_cache:
            return _audio_cache[filename]
        
        try:
            data, samplerate = sf.read(filename)
            # Ensure audio is in float32 format
            data = data.astype(np.float32)
            _audio_cache[filename] = (data, samplerate)
            return data, samplerate
        except Exception as e:
            print(f"Error loading sound {filename}: {e}")
            # Return silent audio as fallback
            silent_audio = np.zeros((int(0.1 * 22050),), dtype=np.float32)  # 0.1 second of silence
            _audio_cache[filename] = (silent_audio, 22050)
            return silent_audio, 22050
    
    def set_volume(self, volume: float):
        """Set the volume for this sound."""
        self.volume = max(0.0, min(1.0, volume))
    
    def play(self, fade_ms: int = 0):
        """Play the sound using the global mixer."""
        try:
            audio_data = self.data.copy()
            
            # Apply fade if specified
            if fade_ms > 0:
                fade_samples = int(fade_ms * self.samplerate / 1000)
                if fade_samples > 0 and fade_samples < len(audio_data):
                    # Create fade-in envelope
                    fade_in = np.linspace(0, 1, fade_samples)
                    if len(audio_data.shape) == 1:
                        audio_data[:fade_samples] *= fade_in
                    else:
                        audio_data[:fade_samples] *= fade_in[:, np.newaxis]
            
            # Send to mixer for playback
            _mixer.play_sound(audio_data, self.volume)
            
        except Exception as e:
            print(f"Error playing sound: {e}")
    
    def copy(self):
        """Create a copy of this sound."""
        new_sound = Sound.__new__(Sound)
        new_sound.filename = self.filename  
        new_sound.data = self.data.copy()
        new_sound.samplerate = self.samplerate
        new_sound.original_samplerate = getattr(self, 'original_samplerate', self.samplerate)
        new_sound.volume = self.volume
        return new_sound


# Pitch variation helper function  
def play_sound_with_pitch_variation(sound: Sound, pitch_range=(0.85, 1.15), volume=1.0, fade_ms=0):
    """
    Play a sound with real pitch variation using scipy resampling.
    """
    try:
        # Get random pitch multiplier
        pitch = random.uniform(*pitch_range)
        
        # Create a copy of the sound to modify
        modified_sound = sound.copy()
        
        # Skip processing for very small changes
        if abs(pitch - 1.0) < 0.02:
            modified_sound.set_volume(volume)
            modified_sound.play(fade_ms=fade_ms)
            return
        
        # Get the audio data
        audio_data = modified_sound.data.copy()
        
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
        
        # Update the sound data
        modified_sound.data = pitched_audio.astype(np.float32)
        modified_sound.set_volume(volume)
        modified_sound.play(fade_ms=fade_ms)
        
    except Exception as e:
        print(f"Error in pitch variation: {e}")
        # Fallback to normal playback
        try:
            sound.set_volume(volume)
            sound.play(fade_ms=fade_ms)
        except:
            sound.play()

quaff_sound = Sound("RP/sfx/quaff.wav")

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
    death_sound = Sound("RP/sfx/death/humanoid_death.mp3")
    play_sound_with_pitch_variation(death_sound, volume=0.25)

# Menu Sounds
def play_menu_move_sound():
    menu_move_sounds = [
        #Sound("RP/sfx/buttons/button1.wav"),
        Sound("RP/sfx/buttons/button2.wav"),
    ]
    sound = random.choice(menu_move_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.15), volume=1)

#UI move sound
def play_ui_move_sound():
    sound = Sound("RP/sfx/buttons/UI/button1.wav")
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.5), volume=1.0)


#Door sounds
def play_door_open_sound():
    door_open_sounds = [
        Sound("RP/sfx/doors/open1.wav"),
        Sound("RP/sfx/doors/open2.wav"),
        Sound("RP/sfx/doors/open3.wav"),
    ]
    sound = random.choice(door_open_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))

def play_door_close_sound():
    door_close_sounds = [
        Sound("RP/sfx/doors/close1.wav"),
        Sound("RP/sfx/doors/close2.wav"),
        Sound("RP/sfx/doors/close3.wav"),
    ]
    sound = random.choice(door_close_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))



stairs_sound = Sound("RP/sfx/stairs.wav")

# Dark entity spawn sound
def play_darkness_spawn_sound():
    darkness_spawn_sound = Sound("RP/sfx/darkness_spawn/darkness_spawn.mp3")
    # Note: fade_ms not supported with pitch variation, using normal volume
    play_sound_with_pitch_variation(darkness_spawn_sound, pitch_range=(0.8, 1.2), volume=0.25)

def play_torch_pull_sound():
    torch_pull_sounds = [
        Sound("RP/sfx/torch_pull/pull1.wav"),
        Sound("RP/sfx/torch_pull/pull2.wav"),
    ]

    sound = random.choice(torch_pull_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))

def play_torch_extinguish_sound():
    torch_extinguish_sounds = [
        Sound("RP/sfx/burn_out.wav")
    ]
    sound = random.choice(torch_extinguish_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))
    

lightning_sound = Sound("RP/sfx/lightning_sound.wav")
confusion_sound = Sound("RP/sfx/confusion_cast.wav")
pickup_coin_sound = Sound("RP/sfx/pickup_coin.wav")
level_up_sound = Sound("RP/sfx/level_up.wav")
torch_burns_out_sound = Sound("RP/sfx/burn_out.wav")

def play_chest_open_sound():
    chest_open_sounds = [
        Sound("RP/sfx/chest_open/chest_open1.mp3"),
        Sound("RP/sfx/chest_open/chest_open2.mp3"),
        Sound("RP/sfx/chest_open/chest_open3.mp3"),
    ]
    sound = random.choice(chest_open_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))

def play_transfer_item_sound():
    transfer_item_sounds = [
        Sound("RP/sfx/transfer/transfer.wav"),
        Sound("RP/sfx/transfer/transfer2.wav"),
        Sound("RP/sfx/transfer/transfer3.wav"),
        Sound("RP/sfx/transfer/transfer4.wav"),
    ]
    sound = random.choice(transfer_item_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.95, 1.2))

def play_grass_walk_sound(entity_x=0, entity_y=0):
    if random.random() < 0.3:
        return  # 30% chance to not play a sound for variety
    
    # Add unique stagger delay per entity using position as seed
    # Each entity gets a different delay based on their coordinates
    entity_seed = (entity_x * 31 + entity_y * 17) % 1000  # Create unique value per position
    delay = (entity_seed / 1000.0) * 0.1  # Convert to 0-100ms delay
    
    if delay > 0:
        threading.Timer(delay, _delayed_grass_walk_sound).start()
    else:
        _delayed_grass_walk_sound()

def _delayed_grass_walk_sound():
    """Internal function for delayed grass walk sound playback."""
    walk_sounds = [
        Sound("RP/sfx/walk/grass/walk1.wav"),
        Sound("RP/sfx/walk/grass/walk2.wav"),
    ]
    sound = random.choice(walk_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.5), volume=0.5)

def play_walk_sound(entity_x=0, entity_y=0):
    if random.random() < 0.3:
        return  # 30% chance to not play a sound for variety
    
    # Add unique stagger delay per entity using position as seed
    # Each entity gets a different delay based on their coordinates
    entity_seed = (entity_x * 31 + entity_y * 17) % 1000  # Create unique value per position
    delay = (entity_seed / 1000.0) * 0.05  # Convert to 0-50ms delay
    
    if delay > 0:
        threading.Timer(delay, _delayed_walk_sound).start()
    else:
        _delayed_walk_sound()

def _delayed_walk_sound():
    """Internal function for delayed walk sound playback."""
    walk_sounds = [
        Sound("RP/sfx/walk/stone/walk1.wav"),
        Sound("RP/sfx/walk/stone/walk2.wav"),
        Sound("RP/sfx/walk/stone/walk3.wav"),
        Sound("RP/sfx/walk/stone/walk4.wav"),
        Sound("RP/sfx/walk/stone/walk5.wav"),
        Sound("RP/sfx/walk/stone/walk6.wav"),
        Sound("RP/sfx/walk/stone/walk7.wav"),
        Sound("RP/sfx/walk/stone/walk8.wav"),
        Sound("RP/sfx/walk/stone/walk9.wav"),
        Sound("RP/sfx/walk/stone/walk10.wav"),
    ]
    sound = random.choice(walk_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.5), volume=0.5)

def play_block_sound():
    block_sounds = [
        Sound("RP/sfx/hit_block/block1.mp3"),
        Sound("RP/sfx/hit_block/block2.mp3"),
        Sound("RP/sfx/hit_block/block3.mp3"),
    ]
    sound = random.choice(block_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.2), volume=0.5)

def play_attack_sound_finishing_blow():
    finishing_blow_sounds = [
        Sound("RP/sfx/hit_final_blow/finalblow1.wav"),
        Sound("RP/sfx/hit_final_blow/finalblow2.wav"),
        Sound("RP/sfx/hit_final_blow/finalblow3.wav"),
    ]
    sound = random.choice(finishing_blow_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.2), volume=0.5)

def play_miss_sound():
    miss_sounds = [
        Sound("RP/sfx/hit_miss/miss1.wav"),
        Sound("RP/sfx/hit_miss/miss2.wav"),
    ]
    sound = random.choice(miss_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.2), volume=1.0)
    
def play_attack_sound_weapon_to_no_armor():
    #swing_sounds = [
    #    Sound("RP/sfx/weapon_swing/swing1.wav"),
    #    Sound("RP/sfx/weapon_swing/swing2.wav"),
    #    Sound("RP/sfx/weapon_swing/swing3.wav"),
    #]

    attack_sounds = [
        Sound("RP/sfx/hit_weapon_no_armor/hit1.wav"),
        Sound("RP/sfx/hit_weapon_no_armor/hit2.wav"),
        Sound("RP/sfx/hit_weapon_no_armor/hit3.wav"),
    ]

    #sound = random.choice(swing_sounds)
    #sound.play()
    sound = random.choice(attack_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.25))


def play_attack_sound_weapon_to_armor():
    #swing_sounds = [
    #    Sound("RP/sfx/weapon_swing/swing1.wav"),
    #    Sound("RP/sfx/weapon_swing/swing2.wav"),
    #    Sound("RP/sfx/weapon_swing/swing3.wav"),
    #]
    attack_sounds = [
        Sound("RP/sfx/hit_weapon_armor/hit1.wav"),
        Sound("RP/sfx/hit_weapon_armor/hit2.wav"),
        Sound("RP/sfx/hit_weapon_armor/hit3.wav"),
    ]
    #sound = random.choice(swing_sounds)
    #sound.play()

    sound = random.choice(attack_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.25))

def play_glass_break_sound():
    glass_break_sounds = [
        Sound("RP/sfx/materials/glass/break1.mp3")
    ]
    sound = random.choice(glass_break_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.25), volume=0.5)

def play_throw_sound():
    throw_sounds = [
        Sound("RP/sfx/throw.mp3")
    ]
    sound = random.choice(throw_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.25), volume=0.5)

## EQUIP

# Leather equip

def play_equip_leather_sound():
    equip_leather_sounds = [
        Sound("RP/sfx/equip/leather/equip1.mp3")
    ]
    sound = random.choice(equip_leather_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)

def play_unequip_leather_sound():
    unequip_leather_sounds = [
        Sound("RP/sfx/equip/leather/unequip1.mp3")
    ]
    sound = random.choice(unequip_leather_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)

def pick_up_leather_sound():
    pick_up_leather_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for leather items
        Sound("RP/sfx/equip/leather/unequip1.mp3")
    ]
    sound = random.choice(pick_up_leather_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=0.25)

def drop_leather_sound():
    drop_leather_sounds = [
        Sound("RP/sfx/equip/leather/unequip1.mp3")
    ]
    sound = random.choice(drop_leather_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)


# Glass equip
def play_equip_glass_sound():
    equip_glass_sounds = [
        Sound("RP/sfx/equip/glass/equip1.mp3")
    ]
    sound = random.choice(equip_glass_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def play_unequip_glass_sound():
    unequip_glass_sounds = [
        Sound("RP/sfx/equip/glass/unequip1.mp3")
    ]
    sound = random.choice(unequip_glass_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def pick_up_glass_sound():
    pick_up_glass_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for glass items
        Sound("RP/sfx/equip/glass/equip1.mp3")
    ]
    sound = random.choice(pick_up_glass_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=1.0)

def drop_glass_sound():
    drop_glass_sounds = [
        Sound("RP/sfx/equip/glass/unequip1.mp3")
    ]
    sound = random.choice(drop_glass_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.5)
    
# Paper equip
def play_equip_paper_sound():
    equip_paper_sounds = [
        Sound("RP/sfx/equip/paper/equip1.mp3")
    ]
    sound = random.choice(equip_paper_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=3)

def play_unequip_paper_sound():
    unequip_paper_sounds = [
        Sound("RP/sfx/equip/paper/unequip1.mp3")
    ]
    sound = random.choice(unequip_paper_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=3)

def pick_up_paper_sound():
    pick_up_paper_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for paper items
        Sound("RP/sfx/equip/paper/equip1.mp3")
    ]
    sound = random.choice(pick_up_paper_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=3)

def drop_paper_sound():
    drop_paper_sounds = [
        Sound("RP/sfx/equip/paper/equip1.mp3")
    ]
    sound = random.choice(drop_paper_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=3)

# coin equip
def play_equip_coin_sound():
    equip_coin_sounds = [
        Sound("RP/sfx/equip/coin/1coin.mp3")
    ]
    sound = random.choice(equip_coin_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def play_unequip_coin_sound():
    unequip_coin_sounds = [
        Sound("RP/sfx/equip/coin/1coin.mp3")
    ]
    sound = random.choice(unequip_coin_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def pick_up_coin_sound():
    pick_up_coin_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for coin items
        Sound("RP/sfx/equip/coin/1coin.mp3")
    ]
    sound = random.choice(pick_up_coin_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=1.0)

def drop_coin_sound():
    drop_coin_sounds = [
        Sound("RP/sfx/equip/coin/1coin.mp3")
    ]
    sound = random.choice(drop_coin_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

# many coins
def play_equip_manycoins_sound():
    equip_manycoins_sounds = [
        Sound("RP/sfx/equip/coin/manycoins.mp3")
    ]
    sound = random.choice(equip_manycoins_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def play_unequip_manycoins_sound():
    unequip_manycoins_sounds = [
        Sound("RP/sfx/equip/coin/manycoins.mp3")
    ]
    sound = random.choice(unequip_manycoins_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

def pick_up_manycoins_sound():
    pick_up_manycoins_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for many coins items
        Sound("RP/sfx/equip/coin/manycoins.mp3")
    ]
    sound = random.choice(pick_up_manycoins_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=1.0)

def drop_manycoins_sound():
    drop_manycoins_sounds = [
        Sound("RP/sfx/equip/coin/manycoins.mp3")
    ]
    sound = random.choice(drop_manycoins_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=1.0)

# Wood sounds
def pick_up_wood_sound():
    pick_up_wood_sounds = [
        # Use unequip sound for pickup as well, since we don't have a separate pickup sound for wood items
        Sound("RP/sfx/equip/wood/pickup1.mp3")
    ]
    sound = random.choice(pick_up_wood_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=.25)

def drop_wood_sound():
    drop_wood_sounds = [
        Sound("RP/sfx/equip/wood/drop1.mp3")
    ]
    sound = random.choice(drop_wood_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.1), volume=.25)

# Blade sounds
def pick_up_blade_sound():
    pick_up_blade_sounds = [
            Sound("RP/sfx/equip/blade/pickup1.wav"),
            Sound("RP/sfx/equip/blade/pickup2.wav")
        ]
    sound = random.choice(pick_up_blade_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.5), volume=0.25)
def drop_blade_sound():
    drop_blade_sounds = [
        Sound("RP/sfx/equip/blade/drop1.wav"),
        Sound("RP/sfx/equip/blade/drop2.wav"),
        Sound("RP/sfx/equip/blade/drop3.wav")
    ]
    sound = random.choice(drop_blade_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.1), volume=0.25)
def play_equip_blade_sound():
    equip_blade_sounds = [
        Sound("RP/sfx/equip/blade/equip1.wav"),
        Sound("RP/sfx/equip/blade/equip2.wav")
    ]
    sound = random.choice(equip_blade_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)
def play_unequip_blade_sound():
    unequip_blade_sounds = [
        Sound("RP/sfx/equip/blade/unequip1.wav"),
        Sound("RP/sfx/equip/blade/unequip2.wav")
    ]
    sound = random.choice(unequip_blade_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)

# AMBIENT SOUND SYSTEM - Generic and Modular

class AmbientSoundType:
    """Configuration for an ambient sound type."""
    def __init__(self, name: str, sound_file: str, entity_names: list, map_type: str = None, 
                 proximity_threshold: int = 5, base_volume: float = 0.2):
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
        sound_file='RP/sfx/loops/menu/menu3.mp3',
        entity_names=[None],
        map_type=None,
        proximity_threshold=999,  # Always play when active
        base_volume=0.1
    ),
    'dungeon_music': AmbientSoundType(
        name='dungeon_music', 
        sound_file='RP/music/dungeon1.mp3',  # Change this to your music file
        entity_names=[None],
        map_type=None,
        proximity_threshold=999,
        base_volume=0.3
    ),
    'menu_music': AmbientSoundType(
        name='menu_music',
        sound_file='RP/music/menu1.mp3',  # Change this to your music file  
        entity_names=[None],
        map_type=None,
        proximity_threshold=999,
        base_volume=0.2
    ),
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
            self.active_ambients[ambient_type] = {'looper': None, 'sound': None, 'active': False}
        
        ambient_state = self.active_ambients[ambient_type]
        
        if should_play and not ambient_state['active']:
            self.start_ambient_loop(ambient_type, target_volume)
        elif not should_play and ambient_state['active']:
            self.stop_ambient_loop(ambient_type)
        elif should_play and ambient_state['active']:
            # Adjust volume of existing loop
            if ambient_state['looper'] and ambient_state['looper'].playing:
                ambient_state['looper'].set_volume(target_volume)
            else:
                # Restart if looper died
                ambient_state['active'] = False
                self.start_ambient_loop(ambient_type, target_volume)
    
    def start_ambient_loop(self, ambient_type: str, initial_volume: float):
        """Start looping ambient sound at specified volume."""
        if ambient_type not in AMBIENT_TYPES:
            return
            
        config = AMBIENT_TYPES[ambient_type]
        
        # Initialize ambient state if it doesn't exist
        if ambient_type not in self.active_ambients:
            self.active_ambients[ambient_type] = {'looper': None, 'sound': None, 'active': False}
            
        ambient_state = self.active_ambients[ambient_type]
        
        try:
            if ambient_state['sound'] is None:
                ambient_state['sound'] = Sound(config.sound_file)
                ambient_state['looper'] = LoopingSound(ambient_state['sound'], f"ambient_{ambient_type}")
            
            ambient_state['looper'].play(initial_volume)
            ambient_state['active'] = True
            
        except Exception as e:
            print(f"Could not start {ambient_type} loop: {e}")
    
    def stop_ambient_loop(self, ambient_type: str):
        """Stop ambient loop with fade out."""
        if ambient_type not in self.active_ambients:
            return
            
        ambient_state = self.active_ambients[ambient_type]
        
        if ambient_state['looper'] is not None:
            ambient_state['looper'].stop()
            ambient_state['active'] = False
    
    def update_ambient_sounds(self, player, entities, game_map):
        """Update all ambient sounds based on player proximity."""
        # Check each ambient type (excluding music which is manually controlled)
        for ambient_type in AMBIENT_TYPES:
            if ambient_type in ['menu', 'dungeon_music', 'menu_music']:  # Skip manually controlled
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
        start_ambient_sound('menu')

def stop_menu_ambience():
    """Stop menu ambience."""
    global _menu_ambience_active
    if _menu_ambience_active:
        _menu_ambience_active = False
        stop_ambient_sound('menu')

def is_menu_ambience_playing():
    """Check if menu ambience is currently playing."""
    return _menu_ambience_active

# SOUND MUFFLING CONTROL FUNCTIONS

def set_sound_muffling(enabled: bool, cutoff: float = 2000):
    """Enable or disable sound muffling effect for all audio.
    
    Args:
        enabled: True to enable muffling, False to disable
        cutoff: Cutoff frequency in Hz, lower values = more muffled
               Examples: 20000 (no effect), 3000 (slight), 1000 (moderate), 500 (heavy)
    """
    global _mixer
    _mixer.set_muffling(enabled, cutoff)

def get_sound_muffling_state() -> tuple[bool, float]:
    """Get current muffling state.
    
    Returns:
        tuple: (enabled: bool, cutoff_frequency: float)
    """
    global _mixer
    return _mixer.get_muffling_state()

def demo_muffling_effect():
    """Demonstrate the muffling effect by transitioning from clear to muffled."""
    print("Demonstrating sound muffling effect...")
    print("Starting with clear audio...")
    set_sound_muffling(False)
    
    time.sleep(2)
    
    print("Applying light muffling (3000 Hz)...")
    set_sound_muffling(True, 3000)
    
    time.sleep(2)
    
    print("Applying moderate muffling (1500 Hz)...")
    set_sound_muffling(True, 1500)
    
    time.sleep(2)
    
    print("Applying heavy muffling (800 Hz)...")
    set_sound_muffling(True, 800)
    
    time.sleep(2)
    
    print("Returning to clear audio...")
    set_sound_muffling(False)

# Example usage functions for game scenarios

def apply_underwater_muffling():
    """Apply muffling effect suitable for underwater scenes."""
    set_sound_muffling(True, 1200)

def apply_wall_muffling():
    """Apply muffling effect for sounds heard through walls."""
    set_sound_muffling(True, 2500)

def apply_distance_muffling():
    """Apply muffling effect for distant sounds."""
    set_sound_muffling(True, 1800)

def clear_sound_muffling():
    """Remove all muffling effects."""
    set_sound_muffling(False)

# Positional sound muffling system

def should_muffle_sound(source_x, source_y, player, game_map):
    """
    Check if a sound at the given position should be muffled.
    Muffles sounds within 10 tiles that are not visible to the player.
    
    Args:
        source_x, source_y: Position of the sound source
        player: Player entity with x, y coordinates
        game_map: Game map with visible array
    
    Returns:
        bool: True if sound should be muffled, False otherwise
    """
    # Calculate distance from player
    dx = source_x - player.x
    dy = source_y - player.y  
    distance = (dx * dx + dy * dy) ** 0.5
    
    # Check if within 10 tiles and not visible
    if distance <= 10 and game_map.in_bounds(source_x, source_y):
        return not game_map.visible[source_x, source_y]
    
    return False

def should_play_sound(source_x, source_y, player, game_map, max_distance=10):
    """
    Check if a sound should be played at all based on distance from player.
    
    Args:
        source_x, source_y: Position of the sound source
        player: Player entity with x, y coordinates
        game_map: Game map (for bounds checking)
        max_distance: Maximum distance to play sounds
    
    Returns:
        bool: True if sound should be played, False otherwise
    """
    # Calculate distance from player
    dx = source_x - player.x
    dy = source_y - player.y  
    distance = (dx * dx + dy * dy) ** 0.5
    
    # Only play if within range
    return distance <= max_distance

def apply_muffling_to_audio(audio_data: np.ndarray, cutoff: float = 800, samplerate: int = 44100) -> np.ndarray:
    """
    Apply low-pass filter directly to audio data for muffling effect.
    
    Args:
        audio_data: Input audio data
        cutoff: Cutoff frequency in Hz
        samplerate: Sample rate of the audio
    
    Returns:
        Filtered audio data
    """
    try:
        nyquist = 0.5 * samplerate
        normalized_cutoff = min(cutoff / nyquist, 0.99)
        
        # Design Butterworth low-pass filter
        from scipy.signal import butter, lfilter
        b, a = butter(4, normalized_cutoff, btype='low')
        
        # Apply filter
        if len(audio_data.shape) == 1:
            # Mono
            filtered = lfilter(b, a, audio_data)
        else:
            # Stereo - filter each channel separately
            filtered = np.zeros_like(audio_data)
            for channel in range(audio_data.shape[1]):
                filtered[:, channel] = lfilter(b, a, audio_data[:, channel])
        
        return filtered.astype(np.float32)
        
    except Exception as e:
        print(f"Muffling filter error: {e}")
        return audio_data  # Return original on error

def play_positional_sound(sound_func, source_x, source_y, player, game_map, muffled_cutoff=800):
    """
    Play a sound with positional muffling if the source is within 10 tiles but not visible.
    
    Args:
        sound_func: Function to call to play the sound (e.g., play_door_open_sound)
        source_x, source_y: Position of the sound source
        player: Player entity with x, y coordinates  
        game_map: Game map with visible array
        muffled_cutoff: Cutoff frequency for muffled sounds (Hz)
    """
    # First check if sound should be played at all (distance check)
    if not should_play_sound(source_x, source_y, player, game_map):
        return  # Don't play sounds beyond 10 tiles
    
    # Check if this sound should be muffled
    should_muffle = should_muffle_sound(source_x, source_y, player, game_map)
    
    if should_muffle:
        # Play muffled version by modifying the sound function
        play_muffled_sound(sound_func, muffled_cutoff)
    else:
        # Play normal sound
        sound_func()

def play_muffled_sound(sound_func, cutoff=800):
    """
    Play a sound with muffling applied directly to the audio data.
    """
    # Get the original sound functions and their associated sounds
    if sound_func.__name__ == 'play_door_open_sound':
        door_open_sounds = [
            Sound("RP/sfx/doors/open1.wav"),
            Sound("RP/sfx/doors/open2.wav"),
        ] 
        sound = random.choice(door_open_sounds)
        
    elif sound_func.__name__ == 'play_door_close_sound':
        door_close_sounds = [
            Sound("RP/sfx/doors/close1.wav"),
            Sound("RP/sfx/doors/close2.wav"),
        ]
        sound = random.choice(door_close_sounds)
        
    elif sound_func.__name__ == 'play_grass_walk_sound':
        # 30% chance to not play a sound for variety (same as original)
        if random.random() < 0.3:
            return
        grass_walk_sounds = [
            Sound("RP/sfx/walk/grass/walk1.wav"),
            Sound("RP/sfx/walk/grass/walk2.wav"),
        ]
        sound = random.choice(grass_walk_sounds)
        sound.set_volume(0.5)  # Match original volume
        
    elif sound_func.__name__ == 'play_walk_sound':
        # 30% chance to not play a sound for variety (same as original)
        if random.random() < 0.3:
            return
        walk_sounds = [
            Sound("RP/sfx/walk/stone/walk1.wav"),
            Sound("RP/sfx/walk/stone/walk2.wav"),
            Sound("RP/sfx/walk/stone/walk3.wav"),
            Sound("RP/sfx/walk/stone/walk4.wav"),
            Sound("RP/sfx/walk/stone/walk5.wav"),
            Sound("RP/sfx/walk/stone/walk6.wav"),
            Sound("RP/sfx/walk/stone/walk7.wav"),
            Sound("RP/sfx/walk/stone/walk8.wav"),
            Sound("RP/sfx/walk/stone/walk9.wav"),
            Sound("RP/sfx/walk/stone/walk10.wav"),
        ]
        sound = random.choice(walk_sounds)
        sound.set_volume(0.5)  # Match original volume
        
    else:
        # Fallback - just play the original function (no muffling)
        print(f"Warning: No muffling support for sound function: {sound_func.__name__}")
        sound_func()
        return
    
    # Apply muffling to the sound data
    muffled_data = apply_muffling_to_audio(sound.data, cutoff, 44100)
    
    # Apply pitch variation to muffled data (same as original functions)
    pitch = random.uniform(0.9, 1.5)
    if abs(pitch - 1.0) >= 0.02:  # Only if significant change
        try:
            if len(muffled_data.shape) == 1:
                # Mono
                new_length = int(len(muffled_data) / pitch)
                muffled_data = signal.resample(muffled_data, new_length)
            else:
                # Stereo
                new_length = int(len(muffled_data) / pitch)
                pitched_data = np.zeros((new_length, muffled_data.shape[1]), dtype=np.float32)
                for channel in range(muffled_data.shape[1]):
                    pitched_data[:, channel] = signal.resample(muffled_data[:, channel], new_length)
                muffled_data = pitched_data
        except Exception as e:
            print(f"Pitch variation error: {e}")
    
    # Play the muffled sound directly through the mixer
    global _mixer
    _mixer.play_sound(muffled_data, sound.volume)

def play_positional_sound_with_pitch(sound, pitch_range, source_x, source_y, player, game_map, 
                                   volume=1.0, fade_ms=0, muffled_cutoff=800):
    """
    Play a sound with pitch variation and positional muffling.
    
    Args:
        sound: Sound object to play
        pitch_range: Tuple of (min_pitch, max_pitch) for variation
        source_x, source_y: Position of the sound source
        player: Player entity with x, y coordinates
        game_map: Game map with visible array  
        volume: Volume level (0.0 to 1.0)
        fade_ms: Fade duration in milliseconds
        muffled_cutoff: Cutoff frequency for muffled sounds (Hz)
    """
    # First check if sound should be played at all (distance check)
    if not should_play_sound(source_x, source_y, player, game_map):
        return  # Don't play sounds beyond 10 tiles
    
    # Check if this sound should be muffled
    should_muffle = should_muffle_sound(source_x, source_y, player, game_map)
    
    if should_muffle:
        # Create modified sound with muffling
        modified_sound = sound.copy()
        muffled_data = apply_muffling_to_audio(modified_sound.data, muffled_cutoff, 44100)
        modified_sound.data = muffled_data
        play_sound_with_pitch_variation(modified_sound, pitch_range, volume, fade_ms)
    else:
        # Play normal sound with pitch variation
        play_sound_with_pitch_variation(sound, pitch_range, volume, fade_ms)

# Wrapper functions for common positional sounds

def play_door_open_sound_at(x, y, player, game_map):
    """Play door opening sound with positional muffling."""
    # Add blue door animation for sounds within range
    from animations import HeardDoorAnimation
    dx = x - player.x
    dy = y - player.y
    distance = (dx * dx + dy * dy) ** 0.5
    if distance <= 10 and not game_map.visible[x, y]:
        game_map.engine.animation_queue.append(HeardDoorAnimation((x, y), player))
    
    play_positional_sound(play_door_open_sound, x, y, player, game_map, muffled_cutoff=600)

def play_door_close_sound_at(x, y, player, game_map):
    """Play door closing sound with positional muffling."""
    # Add blue door animation for sounds within range  
    from animations import HeardDoorAnimation
    dx = x - player.x
    dy = y - player.y
    distance = (dx * dx + dy * dy) ** 0.5
    if distance <= 10 and not game_map.visible[x, y]:
        game_map.engine.animation_queue.append(HeardDoorAnimation((x, y), player))
    
    play_positional_sound(play_door_close_sound, x, y, player, game_map, muffled_cutoff=600)

def play_combat_sound_at(sound_func, x, y, player, game_map):
    """Play combat sound with positional muffling."""
    play_positional_sound(sound_func, x, y, player, game_map, muffled_cutoff=700)

def play_movement_sound_at(sound_func, x, y, player, game_map):
    """Play movement sound with positional muffling and entity-specific timing."""
    # Pass coordinates to sound function for unique entity timing
    if sound_func.__name__ in ['play_walk_sound', 'play_grass_walk_sound']:
        # First check if sound should be played at all (distance check)
        if not should_play_sound(x, y, player, game_map):
            return  # Don't play sounds beyond 10 tiles
        
        # Check if this sound should be muffled
        should_muffle = should_muffle_sound(x, y, player, game_map)
        
        if should_muffle:
            # Play muffled version with entity coordinates for unique timing
            play_muffled_sound_with_coords(sound_func, 900, x, y)
        else:
            # Play normal sound with entity coordinates for unique timing
            sound_func(x, y)
    else:
        # Fallback to original function for non-footstep sounds
        play_positional_sound(sound_func, x, y, player, game_map, muffled_cutoff=900)

def play_muffled_sound_with_coords(sound_func, cutoff=800, entity_x=0, entity_y=0):
    """Play a muffled sound with entity-specific timing."""
    # Get the original sound functions and their associated sounds
    if sound_func.__name__ == 'play_grass_walk_sound':
        # 30% chance to not play a sound for variety (same as original)
        if random.random() < 0.3:
            return
        grass_walk_sounds = [
            Sound("RP/sfx/walk/grass/walk1.wav"),
            Sound("RP/sfx/walk/grass/walk2.wav"),
        ]
        sound = random.choice(grass_walk_sounds)
        sound.set_volume(0.5)  # Match original volume
        
    elif sound_func.__name__ == 'play_walk_sound':
        # 30% chance to not play a sound for variety (same as original)
        if random.random() < 0.3:
            return
        walk_sounds = [
            Sound("RP/sfx/walk/stone/walk1.wav"),
            Sound("RP/sfx/walk/stone/walk2.wav"),
            Sound("RP/sfx/walk/stone/walk3.wav"),
            Sound("RP/sfx/walk/stone/walk4.wav"),
            Sound("RP/sfx/walk/stone/walk5.wav"),
            Sound("RP/sfx/walk/stone/walk6.wav"),
            Sound("RP/sfx/walk/stone/walk7.wav"),
            Sound("RP/sfx/walk/stone/walk8.wav"),
            Sound("RP/sfx/walk/stone/walk9.wav"),
            Sound("RP/sfx/walk/stone/walk10.wav"),
        ]
        sound = random.choice(walk_sounds)
        sound.set_volume(0.5)  # Match original volume
    else:
        # Fallback - just play the original function (no muffling)
        print(f"Warning: No muffling support for sound function: {sound_func.__name__}")
        sound_func(entity_x, entity_y) if 'walk_sound' in sound_func.__name__ else sound_func()
        return
    
    # Apply muffling to the sound data
    muffled_data = apply_muffling_to_audio(sound.data, cutoff, 44100)
    
    # Apply pitch variation to muffled data (same as original functions)
    pitch = random.uniform(0.9, 1.5)
    if abs(pitch - 1.0) >= 0.02:  # Only if significant change
        try:
            if len(muffled_data.shape) == 1:
                # Mono
                new_length = int(len(muffled_data) / pitch)
                muffled_data = signal.resample(muffled_data, new_length)
            else:
                # Stereo
                new_length = int(len(muffled_data) / pitch)
                pitched_data = np.zeros((new_length, muffled_data.shape[1]), dtype=np.float32)
                for channel in range(muffled_data.shape[1]):
                    pitched_data[:, channel] = signal.resample(muffled_data[:, channel], new_length)
                muffled_data = pitched_data
        except Exception as e:
            print(f"Pitch variation error: {e}")
    
    # Add unique stagger delay per entity using position as seed
    entity_seed = (entity_x * 31 + entity_y * 17) % 1000
    delay = (entity_seed / 1000.0) * 0.05  # Convert to 0-50ms delay
    
    # Play the muffled sound directly through the mixer with delay
    global _mixer
    if delay > 0:
        threading.Timer(delay, lambda: _mixer.play_sound(muffled_data, sound.volume)).start()
    else:
        _mixer.play_sound(muffled_data, sound.volume)

# Simple Music System

def start_dungeon_music():
    """Start dungeon music."""
    stop_all_music()
    start_ambient_sound('dungeon_music')

def start_menu_music():
    """Start menu music."""
    stop_all_music()
    start_ambient_sound('menu_music')

def stop_all_music():
    """Stop all music."""
    stop_ambient_sound('dungeon_music')
    stop_ambient_sound('menu_music')

def set_music_volume(volume: float):
    """Set music volume."""
    for music_type in ["dungeon_music", "menu_music"]:
        if music_type in AMBIENT_TYPES:
            AMBIENT_TYPES[music_type].base_volume = .3
            # FOR FUTURE USE: max(0.0, min(1.0, volume))

def set_music_files(dungeon_file: str, menu_file: str):
    """Set music file paths."""
    AMBIENT_TYPES['dungeon_music'].sound_file = dungeon_file
    AMBIENT_TYPES['menu_music'].sound_file = menu_file



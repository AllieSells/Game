import json
import sounddevice as sd
import soundfile as sf
import random
import numpy as np
from scipy import signal
from scipy.signal import butter, lfilter, lfilter_zi
import threading
from typing import Tuple, List, Dict
import time
import os
import sys

def get_data_path(filename):
    """Get the correct path for data files in both development and PyInstaller."""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(__file__)
    return os.path.join(base_path, filename)


def _log(message: str) -> None:
    """Write to logs/log.txt, creating the directory if it doesn't exist."""
    try:
        log_path = get_data_path('logs/log.txt')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a') as f:
            f.write(message if message.endswith('\n') else message + '\n')
    except Exception:
        pass  # Never let logging crash the game


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
        self.vhs_enabled = False
        self.vhs_time = 0.0
        self.vhs_decay = 1.0
        self._vhs_wow     = 0.0
        self._vhs_flutter = 0.0

        # Ring buffer for VHS wow/flutter (allows true slow-down by reading from history)
        _VHS_LATENCY = 1024         # ~23 ms head-start so read can lag behind write
        self._vhs_buf_size  = 65536 # ~1.5s of history — enough for extreme sag without overrun
        self._vhs_buffer    = np.zeros((self._vhs_buf_size, 2), dtype=np.float32)
        self._vhs_write_idx = _VHS_LATENCY  # write pointer starts ahead of read
        self._vhs_read_pos  = 0.0           # fractional read pointer
        self._VHS_LATENCY   = _VHS_LATENCY
        self._wow_freq = 0.3
        self._wow_amp = 0.9
        self._wow2_freq = 0.73
        self._wow2_amp = 0.15
        self._flutter_freq = 6.0
        self._flutter_amp = 0.03
        self._flutter2_freq = 19.0
        self._flutter2_amp = 0.025
        self._flutter_phase = 5.5
        self._flutter2_phase = 0.0
        self._head_switch_freq = 30.0
        self._head_switch_phase = 0.0
        self._vhs_dropout_rng = np.random.default_rng(42)

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

    def trigger_vhs_effect(self):
        # Reset all state before enabling so callback never sees partial state
        self.vhs_time        = 0.0
        self.vhs_decay       = 1.0
        self._vhs_wow        = 0.0
        self._vhs_flutter    = 0.0
        self._flutter_phase  = 0.0
        self._vhs_buffer[:]  = 0.0
        self._vhs_write_idx  = self._VHS_LATENCY
        self._vhs_read_pos   = 0.0
        self._vhs_dropout_rng = np.random.default_rng()
        # --- Bad VHS player parameters ---
        # Deep, slow warble — like a stretched/wrinkled tape
        self._wow_freq = 0.96          # slow, sickly pitch roll
        self._wow_amp  = 0.65          # very heavy pitch swing
        # Secondary wow — irregular tape tension
        self._wow2_freq = 1.6
        self._wow2_amp  = 0.65
        # Jittery flutter — worn capstan/pinch roller
        self._flutter_freq = 7.5
        self._flutter_amp  = 0.06
        # Second flutter harmonic
        self._flutter2_freq = 19.0
        self._flutter2_amp  = 0.025
        self._flutter_phase  = 0.0
        self._flutter2_phase = 0.0
        # Head-switching noise rate (~30 Hz vertical sync artifacts)
        self._head_switch_freq = 30.0
        self._head_switch_phase = 0.9
        self.vhs_enabled = True  # set last — gate opens after buffer is clean
    def _apply_vhs_effect(self, audio: np.ndarray) -> np.ndarray:
        """Apply dramatic bad-VHS-player effect — fully vectorised."""
        if not self.vhs_enabled or len(audio) == 0:
            return audio

        # Normalise to stereo 2-D
        if audio.ndim == 1:
            audio_2d = np.stack([audio, audio], axis=1).astype(np.float32)
        elif audio.shape[1] == 1:
            audio_2d = np.repeat(audio, 2, axis=1).astype(np.float32)
        else:
            audio_2d = audio

        N        = audio_2d.shape[0]
        buf_size = self._vhs_buf_size

        # --- 1. Write block into ring buffer (vectorised) ---
        t_vec    = self.vhs_time + np.arange(N, dtype=np.float64) / self.samplerate
        indices  = (self._vhs_write_idx + np.arange(N)) % buf_size
        self._vhs_buffer[indices] = audio_2d
        self._vhs_write_idx      += N

        # --- 2. Build per-sample speed curve ---
        # Slower decay = effect lasts longer (~4 seconds audible)
        decay = np.exp(-t_vec / 0.8).astype(np.float32)

        # PRIMARY WOW: deep sickly warble
        wow1 = (self._wow_amp * np.sin(2 * np.pi * self._wow_freq * t_vec)).astype(np.float32)
        # SECONDARY WOW: irregular tape-tension wobble
        wow2 = (self._wow2_amp * np.sin(2 * np.pi * self._wow2_freq * t_vec)).astype(np.float32)
        wow = wow1 + wow2

        # PRIMARY FLUTTER: worn capstan jitter
        fl_phases = self._flutter_phase + 2 * np.pi * self._flutter_freq * np.arange(N) / self.samplerate
        flutter1 = (self._flutter_amp * np.sin(fl_phases)).astype(np.float32)
        self._flutter_phase = float(fl_phases[-1]) % (2 * np.pi)

        # SECONDARY FLUTTER: higher-frequency mechanical rattle
        fl2_phases = self._flutter2_phase + 2 * np.pi * self._flutter2_freq * np.arange(N) / self.samplerate
        flutter2 = (self._flutter2_amp * np.sin(fl2_phases)).astype(np.float32)
        self._flutter2_phase = float(fl2_phases[-1]) % (2 * np.pi)

        flutter = flutter1 + flutter2

        # --- Startup motor sag: tape struggles to reach speed ---
        startup_duration = 2.5
        sag = np.ones(N, dtype=np.float32)
        mask = t_vec < startup_duration
        if mask.any():
            # Start at 0.72 (way too slow), crawl up to 1.0 with a slight overshoot
            progress = (t_vec[mask] / startup_duration).astype(np.float32)
            # Ease-out with a small overshoot bump around 80%
            base_sag = 0.72 + 0.28 * progress
            overshoot = 0.04 * np.sin(np.pi * progress) * (1.0 - progress)
            sag[mask] = base_sag + overshoot

        # Wider speed range — allow really dramatic pitch swings
        speed = np.clip((1.0 + (wow + flutter) * decay) * sag, 0.55, 1.45)

        # --- 3. Integrate speed → fractional read positions ---
        read_positions = self._vhs_read_pos + np.cumsum(speed) - speed[0]
        self._vhs_read_pos = float(read_positions[-1]) + float(speed[-1])

        # Safety: clamp read so it never falls more than (buf_size - margin) behind write,
        # and never overtakes write. This prevents reading overwritten or unwritten data.
        write_end = self._vhs_write_idx
        min_read = write_end - buf_size + 256   # don't read overwritten data
        max_read = write_end - 2                 # don't read ahead of write
        read_positions = np.clip(read_positions, min_read, max_read)
        self._vhs_read_pos = np.clip(self._vhs_read_pos, min_read, max_read)

        # Keep both pointers from overflowing
        if self._vhs_read_pos >= buf_size * 4:
            self._vhs_read_pos  -= buf_size
            self._vhs_write_idx -= buf_size
            read_positions      -= buf_size

        # --- 4. Linear interpolation from ring buffer ---
        r0   = np.floor(read_positions).astype(np.int64) % buf_size
        r1   = (r0 + 1) % buf_size
        frac = (read_positions - np.floor(read_positions)).astype(np.float32)[:, np.newaxis]

        processed = self._vhs_buffer[r0] * (1.0 - frac) + self._vhs_buffer[r1] * frac

        # --- 5. Treble loss: bad VHS eats high frequencies ---
        # Simple single-pole low-pass approximation (vectorised via EMA)
        if self.vhs_time < startup_duration:
            # Cutoff ramps from ~2kHz up to ~8kHz during startup
            progress = min(self.vhs_time / startup_duration, 1.0)
            cutoff = 2000.0 + 6000.0 * progress
        else:
            # After startup, still slightly muffled
            cutoff = 8000.0 + 4000.0 * min((self.vhs_time - startup_duration) / 2.0, 1.0)
        rc = 1.0 / (2.0 * np.pi * cutoff)
        dt = 1.0 / self.samplerate
        alpha = np.float32(dt / (rc + dt))
        # Apply simple EMA low-pass per channel (fast enough for 256 samples)
        for ch in range(processed.shape[1]):
            for i in range(1, N):
                processed[i, ch] = processed[i-1, ch] + alpha * (processed[i, ch] - processed[i-1, ch])

        # --- 9. Stereo azimuth error: offset one channel slightly ---
        if self.vhs_time < startup_duration and N > 8:
            shift = max(1, int(4 * (1.0 - self.vhs_time / startup_duration)))
            processed[shift:, 1] = processed[:-shift, 1]

        # --- 10. Soft clip with saturation ---
        processed = np.tanh(processed * 1.8).astype(np.float32)

        # Update persistent state
        self.vhs_time  = float(t_vec[-1]) + 1.0 / self.samplerate
        self.vhs_decay = float(decay[-1])

        if self.vhs_decay < 0.03:
            self.vhs_enabled = False

        return processed[:, 0] if audio.ndim == 1 else processed
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
            _log(f"Error starting audio stream: {e}\n")
    
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
                vol = sound_info['volume']
                n = min(len(audio_chunk), len(outdata))

                # Mix into output, handling mono→stereo inline to avoid extra allocations
                if audio_chunk.ndim == 1:
                    scaled = audio_chunk[:n] * vol
                    outdata[:n, 0] += scaled
                    outdata[:n, 1] += scaled
                elif audio_chunk.shape[1] == 1:
                    scaled = audio_chunk[:n, 0] * vol
                    outdata[:n, 0] += scaled
                    outdata[:n, 1] += scaled
                else:
                    outdata[:n] += audio_chunk[:n] * vol

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
                    vol = sound_info['volume']
                    actual_len = min(len(audio_chunk), len(outdata) - output_pos)

                    # Mix into output, handling mono→stereo inline
                    if audio_chunk.ndim == 1:
                        scaled = audio_chunk[:actual_len] * vol
                        outdata[output_pos:output_pos + actual_len, 0] += scaled
                        outdata[output_pos:output_pos + actual_len, 1] += scaled
                    elif audio_chunk.shape[1] == 1:
                        scaled = audio_chunk[:actual_len, 0] * vol
                        outdata[output_pos:output_pos + actual_len, 0] += scaled
                        outdata[output_pos:output_pos + actual_len, 1] += scaled
                    else:
                        outdata[output_pos:output_pos + actual_len] += audio_chunk[:actual_len] * vol

                    sound_info['position'] = end_pos
                    frames_needed -= actual_len
                    output_pos += actual_len
        
        # Apply sound muffling (low-pass filter) if enabled
        if self.muffling_enabled and self.muffling_cutoff < 20000:
            try:
                outdata[:] = self._apply_lowpass_filter(outdata, self.muffling_cutoff)
            except Exception as e:
                _log(f"Error applying muffling filter: {e}\n")

        try:
            outdata[:] = self._apply_vhs_effect(outdata)
        except Exception as e:
            _log(f"Error applying VHS effect: {e}\n")

        # Prevent clipping
        np.clip(outdata, -1.0, 1.0, out=outdata)
    
    def play_sound(self, audio_data: np.ndarray, volume: float = 1.0):
        """Add a sound to the mixer for playback."""
        # Apply global audio volume from settings
        try:
            settings = load_settings()
            global_volume = settings.get("audio", 50)
            
            if isinstance(global_volume, bool):
                # Handle old boolean format
                global_volume_multiplier = 1.0 if global_volume else 0.0
            else:
                # Handle new 0-100 format
                global_volume_multiplier = max(0.0, min(1.0, global_volume / 100.0))
            
            final_volume = volume * global_volume_multiplier
        except Exception:
            # Fallback if settings can't be loaded
            final_volume = volume

        with self.lock:
            self.playing_sounds.append({'data': audio_data, 'position': 0, 'volume': final_volume})
    
    def start_loop(self, audio_data: np.ndarray, loop_id: str, volume: float = 1.0):
        """Start a looping sound."""
        # Apply global audio volume from settings
        try:
            settings = load_settings()
            global_volume = settings.get("audio", 50)
            if isinstance(global_volume, bool):
                # Handle old boolean format
                global_volume_multiplier = 1.0 if global_volume else 0.0
            else:
                # Handle new 0-100 format
                global_volume_multiplier = max(0.0, min(1.0, global_volume / 100.0))
            final_volume = volume * global_volume_multiplier
        except Exception as e:
            # Fallback if settings can't be loaded
            _log(f"Error loading settings for audio volume: {e}\n")
            final_volume = volume
            
        with self.lock:
            # Remove any existing loop with this ID
            self.loop_sounds = [s for s in self.loop_sounds if s.get('id') != loop_id]

            # Add new loop — always active; VHS effect warps it in the callback
            self.loop_sounds.append({
                'id': loop_id,
                'data': audio_data,
                'position': 0,
                'volume': final_volume,
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
        # Apply global audio volume from settings
        try:
            settings = load_settings()
            global_volume = settings.get("audio", 50)
            if isinstance(global_volume, bool):
                # Handle old boolean format
                global_volume_multiplier = 1.0 if global_volume else 0.0
            else:
                # Handle new 0-100 format
                global_volume_multiplier = max(0.0, min(1.0, global_volume / 100.0))
            
            final_volume = max(0.0, min(1.0, volume)) * global_volume_multiplier
        except Exception:
            # Fallback if settings can't be loaded
            final_volume = max(0.0, min(1.0, volume))
            
        with self.lock:
            for sound_info in self.loop_sounds:
                if sound_info.get('id') == loop_id:
                    sound_info['volume'] = final_volume
    
    def update_all_loop_volumes(self):
        """Update volumes of all currently playing loops based on current settings."""
        try:
            settings = load_settings()
            global_volume = settings.get("audio", 50)
            
            if isinstance(global_volume, bool):
                # Handle old boolean format
                global_volume_multiplier = 1.0 if global_volume else 0.0
            else:
                # Handle new 0-100 format
                global_volume_multiplier = max(0.0, min(1.0, global_volume / 100.0))
                _log(f"Updating loop volumes with global volume: {global_volume} (multiplier: {global_volume_multiplier})\n")
                
            with self.lock:
                for sound_info in self.loop_sounds:
                    if sound_info.get('active', False):
                        # Get base volume (assume it was stored at 1.0 originally)
                        base_volume = 0.3
                        sound_info['volume'] = base_volume * global_volume_multiplier
                        _log(f"Updated loop '{sound_info.get('id')}' volume to {sound_info['volume']}\n")
                        
        except Exception as e:
            _log(f"Failed to update loop volumes: {e}\n")
    
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
            _log(f"Filter error: {e}\n")
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


_settings_cache: dict = {}
_settings_cache_time: float = 0.0
_SETTINGS_CACHE_TTL: float = 2.0  # Refresh settings at most every 2 seconds
_settings_cache_mtime: float = -1.0

def _get_settings_path() -> str:
    """Return the user-writable settings path (next to exe in prod, project folder in dev)."""
    try:
        import sys as _sys
        if getattr(_sys, "frozen", False):
            return os.path.join(os.path.dirname(_sys.executable), "json", "settings.json")
    except Exception:
        pass
    return get_data_path("json/settings.json")


def load_settings():
    """Load settings from JSON file (cached for up to 2 seconds)."""
    global _settings_cache, _settings_cache_time, _settings_cache_mtime
    now = time.monotonic()
    settings_path = _get_settings_path()

    try:
        current_mtime = os.path.getmtime(settings_path)
    except OSError:
        current_mtime = -1.0

    if (
        _settings_cache
        and (now - _settings_cache_time) < _SETTINGS_CACHE_TTL
        and current_mtime == _settings_cache_mtime
    ):
        return _settings_cache

    try:
        with open(settings_path, 'r') as f:
            content = f.read()
            # Remove JSON comments
            lines = [line for line in content.split('\n') if not line.strip().startswith('//')]
            clean_content = '\n'.join(lines)
            _settings_cache = json.loads(clean_content)
            _settings_cache_time = now
            _settings_cache_mtime = current_mtime
            return _settings_cache
    except (FileNotFoundError, json.JSONDecodeError):
        return {"fullscreen": False, "audio": 50, "graphics": "high"}

class Sound:
    """Sound class to mimic pygame.mixer.Sound interface."""
    
    def __init__(self, filename: str):
        self.filename = filename
        self.data, self.original_samplerate = self._load_audio(filename)
        
        # Resample to mixer's sample rate if needed
        if self.original_samplerate != _mixer.samplerate:
            self.data = self._resample_audio(self.data, self.original_samplerate, _mixer.samplerate)
        
        self.samplerate = _mixer.samplerate
        self.volume = 1.0  # Base volume, global volume applied at playback
    
    def _resample_audio(self, audio_data: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
        """Resample audio to target sample rate."""
        if from_sr == to_sr:
            return audio_data
        
        try:
            # Calculate new length
            new_length = int(len(audio_data) * to_sr / from_sr)

            # Resample all channels in one pass to reduce temporary allocations.
            resampled = signal.resample(audio_data, new_length, axis=0)
            return resampled.astype(np.float32, copy=False)
        except Exception as e:
            _log(f"Error resampling audio: {e}\n")
            return audio_data
    
    def _load_audio(self, filename: str) -> Tuple[np.ndarray, int]:
        """Load audio file using soundfile."""
        if filename in _audio_cache:
            return _audio_cache[filename]
        
        try:
            audio_path = get_data_path(filename)
            data, samplerate = sf.read(audio_path, dtype='float32')
            _audio_cache[filename] = (data, samplerate)
            return data, samplerate
        except Exception as e:
            _log(f"Error loading sound {filename}: {e}\n")
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
            audio_data = self.data
            
            # Apply fade if specified
            if fade_ms > 0:
                fade_samples = int(fade_ms * self.samplerate / 1000)
                if fade_samples > 0 and fade_samples < len(audio_data):
                    audio_data = audio_data.copy()
                    # Create fade-in envelope
                    fade_in = np.linspace(0, 1, fade_samples)
                    if len(audio_data.shape) == 1:
                        audio_data[:fade_samples] *= fade_in
                    else:
                        audio_data[:fade_samples] *= fade_in[:, np.newaxis]
            
            # Send to mixer for playback
            _mixer.play_sound(audio_data, self.volume)
            
        except Exception as e:
            with open(get_data_path('log.txt'), 'a') as log_file:
                log_file.write(f"Error playing sound: {e}\n")
    
    def copy(self):
        """Create a copy of this sound."""
        new_sound = Sound.__new__(Sound)
        new_sound.filename = self.filename  
        new_sound.data = self.data
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
        audio_data = modified_sound.data
        
        # Apply pitch shift via resampling
        # Higher pitch = shorter sound = fewer samples
        new_length = int(len(audio_data) / pitch)
        
        pitched_audio = signal.resample(audio_data, new_length, axis=0)
        
        # Update the sound data
        modified_sound.data = pitched_audio.astype(np.float32, copy=False)
        modified_sound.set_volume(volume)
        modified_sound.play(fade_ms=fade_ms)
        
    except Exception as e:
        _log(f"Error in pitch variation: {e}\n")
        # Fallback to normal playback
        try:
            sound.set_volume(volume)
            sound.play(fade_ms=fade_ms)
        except Exception:
            sound.play()


def play_gameover_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/death.wav"), pitch_range=(0.75, 0.75), volume=0.5)

def play_boot_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/boot.mp3"), pitch_range=(0.9, 1.1), volume=0.5)

def play_floppy_seek_sound():
    """Floppy disk seek/read — same source as boot sound but pitched lower and quieter,
    giving the characteristic slow mechanical clunk of a drive head seeking a new cylinder."""
    play_sound_with_pitch_variation(Sound("RP/sfx/boot_read.mp3"), pitch_range=(0.8, 0.9), volume=0.5)

quaff_sound = Sound("RP/sfx/quaff.wav")
# Pre-loaded burn sound — avoids per-call Sound() construction during effect ticks.
_burn_sound_preloaded = Sound("RP/sfx/materials/acid/burn1.mp3")
_explosion_sounds_preloaded = [
    Sound("RP/sfx/spells/fireball/fireball1.mp3"),
    Sound("RP/sfx/spells/fireball/fireball2.mp3"),
]
_dragon_breath_sound_preloaded = Sound("RP/sfx/spells/dragon_breath/dragon_breath1.mp3")
_block_sounds_preloaded = [
    Sound("RP/sfx/hit_block/block1.mp3"),
    Sound("RP/sfx/hit_block/block2.mp3"),
    Sound("RP/sfx/hit_block/block3.mp3"),
]
_finishing_blow_sounds_preloaded = [
    Sound("RP/sfx/hit_final_blow/finalblow1.wav"),
    Sound("RP/sfx/hit_final_blow/finalblow2.wav"),
    Sound("RP/sfx/hit_final_blow/finalblow3.wav"),
]
_miss_sounds_preloaded = [
    Sound("RP/sfx/hit_miss/miss1.wav"),
    Sound("RP/sfx/hit_miss/miss2.wav"),
    Sound("RP/sfx/hit_miss/miss3.wav"),
    Sound("RP/sfx/hit_miss/miss4.wav"),
    Sound("RP/sfx/hit_miss/miss5.wav"),
]
_weapon_hit_no_armor_sounds_preloaded = [
    Sound("RP/sfx/hit_weapon_no_armor/hit1.wav"),
    Sound("RP/sfx/hit_weapon_no_armor/hit2.wav"),
    Sound("RP/sfx/hit_weapon_no_armor/hit3.wav"),
]
_weapon_hit_armor_sounds_preloaded = [
    Sound("RP/sfx/hit_weapon_armor/hit1.wav"),
    Sound("RP/sfx/hit_weapon_armor/hit2.wav"),
    Sound("RP/sfx/hit_weapon_armor/hit3.wav"),
]

# Helper functions for global sounds with pitch variation
def play_quaff_sound():
    play_sound_with_pitch_variation(quaff_sound, pitch_range=(0.9, 1.3), volume=0.5)

def play_crt_off_sound():
    sound = Sound("RP/sfx/crtoff.mp3")
    play_sound_with_pitch_variation(sound, pitch_range=(0.75, 0.75), volume=1.0)

def play_video_mode_switch_sound():
    """Short static crackle for INT 10h video mode switch — high-pitched blip,
    not a power-down.  Uses crtoff.mp3 pitched up so it sounds like a snap of
    static rather than a monitor switching off."""
    sound = Sound("RP/sfx/crtoff.mp3")
    play_sound_with_pitch_variation(sound, pitch_range=(1.6, 1.9), volume=0.45)

def play_crt_load_sound():
    sound = Sound("RP/sfx/crtload.mp3")
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.0), volume=0.5)

def trigger_vhs_audio_effect():
    """Trigger the VHS wow/flutter effect on the mixer for the CRT power-on animation."""
    _mixer.trigger_vhs_effect()

def play_crt_on_sound():
    sound = Sound("RP/sfx/crton.mp3")
    play_sound_with_pitch_variation(sound, pitch_range=(1.0, 1.0), volume=0.5)


def play_stairs_sound():
    play_sound_with_pitch_variation(stairs_sound, pitch_range=(0.95, 1.05), fade_ms=1000)

def play_darkvision_sound():
    sound = Sound("RP/sfx/darkvision.mp3")
    play_sound_with_pitch_variation(sound, pitch_range=(0.75, 0.9), volume=0.75)

def play_stone_sound():
    sounds = [
        Sound("RP/sfx/materials/stone/stone1.mp3"),
        Sound("RP/sfx/materials/stone/stone2.mp3"),
        Sound("RP/sfx/materials/stone/stone3.mp3"),
    ]
    sound = random.choice(sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1), volume=1.0)

def play_heal_spell_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/spells/health/health1.mp3"), pitch_range=(0.8, 1.2), volume=0.75)

def play_teleport_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/spells/teleport/teleport1.mp3"), pitch_range=(0.8, 1.2), volume=0.75)


def play_dark_spell_sound():
    sounds = [
        Sound("RP/sfx/spells/dark/dark1.mp3"),
        Sound("RP/sfx/spells/dark/dark2.mp3"),
        Sound("RP/sfx/spells/dark/dark3.mp3"),
    ]
    sound = random.choice(sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.2), volume=0.75)

# Fade out lightning sound over 0.5 second with pitch variation
def play_lightning_sound():
    play_sound_with_pitch_variation(lightning_sound, pitch_range=(0.5, 1.5), volume=0.5, fade_ms=6000)

def play_confusion_sound():
    play_sound_with_pitch_variation(confusion_sound, pitch_range=(0.75, 1.25), volume=0.5, fade_ms=1000)

def play_level_up_sound():
    play_sound_with_pitch_variation(level_up_sound, pitch_range=(0.95, 1.05))

def play_torch_burns_out_sound():
    play_sound_with_pitch_variation(torch_burns_out_sound, pitch_range=(0.9, 1.1))

def play_fizzle_sound():
    fizzle_sounds = [
        Sound("RP/sfx/spells/fizzle.mp3")
    ]
    sound = random.choice(fizzle_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.2), volume=0.75)

# Humanoid death sound
def play_death_sound():
    death_sound = Sound("RP/sfx/death/humanoid_death.mp3")
    play_sound_with_pitch_variation(death_sound, volume=0.25)

# Menu Sounds / UI move sound
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
    dark_spawn = Sound("RP/sfx/darkness_spawn/darkness_spawn.mp3")
    play_sound_with_pitch_variation(dark_spawn, pitch_range=(0.8, 1.2), volume=0.25)

def play_torch_pull_sound():
    torch_pull_sounds = [
        Sound("RP/sfx/torch_pull/pull1.wav"),
        Sound("RP/sfx/torch_pull/pull2.wav"),
    ]

    sound = random.choice(torch_pull_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.9, 1.1))

def play_torch_extinguish_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/burn_out.wav"), pitch_range=(0.9, 1.1))
    

lightning_sound = Sound("RP/sfx/lightning_sound.wav")
confusion_sound = Sound("RP/sfx/confusion_cast.wav")
pickup_coin_sound = Sound("RP/sfx/pickup_coin.wav")
level_up_sound = Sound("RP/sfx/level_up.wav")
torch_burns_out_sound = Sound("RP/sfx/burn_out.wav")

def play_explosion_sound():
    sound = random.choice(_explosion_sounds_preloaded)
    play_sound_with_pitch_variation(sound, pitch_range=(0.99, 1.01), volume=0.75)

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

_STONE_WALK_FILES  = [f"RP/sfx/walk/stone/walk{i}.wav" for i in range(1, 11)]
_GRASS_WALK_FILES  = ["RP/sfx/walk/grass/walk1.wav", "RP/sfx/walk/grass/walk2.wav"]
_MOSS_WALK_FILES   = [f"RP/sfx/walk/moss/walk{i}.mp3" for i in range(1, 5)]
_LIQUID_WALK_FILES = [f"RP/sfx/walk/liquid/walk{i}.wav" for i in range(1, 5)]


def _play_delayed_footstep(files, volume, pitch_range, entity_x=0, entity_y=0, delay_scale=0.05, skip_chance=0.3):
    """Pick a random sound file, apply per-entity stagger delay, and play with pitch variation."""
    if random.random() < skip_chance:
        return
    entity_seed = (entity_x * 31 + entity_y * 17) % 1000
    delay = (entity_seed / 1000.0) * delay_scale
    def _play():
        play_sound_with_pitch_variation(Sound(random.choice(files)), pitch_range=pitch_range, volume=volume)
    if delay > 0:
        threading.Timer(delay, _play).start()
    else:
        _play()


def play_moss_walk_sound(entity_x=0, entity_y=0):
    _play_delayed_footstep(_MOSS_WALK_FILES, 0.5, (0.9, 1.5), entity_x, entity_y, delay_scale=0.1)

def play_grass_walk_sound(entity_x=0, entity_y=0):
    _play_delayed_footstep(_GRASS_WALK_FILES, 0.5, (0.9, 1.5), entity_x, entity_y, delay_scale=0.1)

def play_liquid_walk_sound(entity_x=0, entity_y=0):
    _play_delayed_footstep(_LIQUID_WALK_FILES, 0.2, (0.8, 1.2), entity_x, entity_y, delay_scale=0.08)

def play_swim_sound():
    swim_sounds = [
        Sound("RP/sfx/walk/swim/swim1.mp3"),
        Sound("RP/sfx/walk/swim/swim2.mp3"),
        Sound("RP/sfx/walk/swim/swim3.mp3")
    ]
    sound = random.choice(swim_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.2), volume=0.3)

def play_walk_sound(entity_x=0, entity_y=0):
    _play_delayed_footstep(_STONE_WALK_FILES, 0.5, (0.9, 1.5), entity_x, entity_y, delay_scale=0.05)

def play_block_sound():
    sound = random.choice(_block_sounds_preloaded)
    play_sound_with_pitch_variation(sound, pitch_range=(0.99, 1.01), volume=0.5)

def play_attack_sound_finishing_blow():
    sound = random.choice(_finishing_blow_sounds_preloaded)
    play_sound_with_pitch_variation(sound, pitch_range=(0.99, 1.01), volume=0.5)

def play_chain_sound():
    chain_sounds = [
        Sound("RP/sfx/equip/chain/chain1.mp3"),
        Sound("RP/sfx/equip/chain/chain2.mp3"),
        Sound("RP/sfx/equip/chain/chain3.mp3"),
        Sound("RP/sfx/equip/chain/chain4.mp3"),
    ]
    sound = random.choice(chain_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)

def play_plate_sound():
    plate_sounds = [
        Sound("RP/sfx/equip/plate/plate1.mp3"),
        Sound("RP/sfx/equip/plate/plate2.mp3"),
    ]
    sound = random.choice(plate_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.5), volume=0.25)


def play_miss_sound():
    sound = random.choice(_miss_sounds_preloaded)
    play_sound_with_pitch_variation(sound, pitch_range=(0.99, 1.01), volume=0.5)
    
def play_attack_sound_weapon_to_no_armor():
    sound = random.choice(_weapon_hit_no_armor_sounds_preloaded)
    play_sound_with_pitch_variation(sound, pitch_range=(0.99, 1.01))


def play_dragon_breath_sound():
    play_sound_with_pitch_variation(_dragon_breath_sound_preloaded, pitch_range=(0.99, 1.01), volume=0.75)

def play_attack_sound_weapon_to_armor():
    sound = random.choice(_weapon_hit_armor_sounds_preloaded)
    play_sound_with_pitch_variation(sound, pitch_range=(0.99, 1.01))

def play_glass_break_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/materials/glass/break1.mp3"), pitch_range=(0.8, 1.25), volume=0.5)

def play_throw_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/throw.mp3"), pitch_range=(0.8, 1.25), volume=0.5)

## EQUIP

# Leather equip

def play_equip_leather_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/leather/equip1.mp3"), pitch_range=(0.8, 1.5), volume=0.25)

def play_unequip_leather_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/leather/unequip1.mp3"), pitch_range=(0.8, 1.5), volume=0.25)

def pick_up_leather_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/leather/unequip1.mp3"), pitch_range=(1.0, 1.5), volume=0.25)

def drop_leather_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/leather/unequip1.mp3"), pitch_range=(0.8, 1.5), volume=0.25)
# Acid sounds
def play_poison_burn_sound():
    # Use (0.99, 1.01) so abs(pitch-1.0) < 0.02 always triggers the fast path
    # in play_sound_with_pitch_variation, skipping the expensive signal.resample call.
    play_sound_with_pitch_variation(_burn_sound_preloaded, pitch_range=(0.99, 1.01), volume=0.5)

# Module-level burn-sound throttle: cap how many burn sounds actually play per
# second so that rooms with many burning entities don't flood the mixer with
# concurrent pitch-shifted audio — each call still has a 1-in-3 chance to fire.
_burn_sound_last_time: float = 0.0

def _play_burn_sound_at(x, y, player, game_map):
    global _burn_sound_last_time
    # Skip ~80% of burn sound calls to avoid running sound code per-entity per-turn.
    if random.random() > 0.20:
        return
    import time as _time
    now = _time.monotonic()
    if now - _burn_sound_last_time < 0.15:  # Hard cap: no more than ~6-7 burn sounds/second
        return
    _burn_sound_last_time = now

    from animations import HeardDoorAnimation
    dx = x - player.x
    dy = y - player.y
    sound_func = play_poison_burn_sound
    if (dx * dx + dy * dy) ** 0.5 <= 10 and not game_map.visible[x, y]:
        game_map.engine.animation_queue.append(HeardDoorAnimation((x, y), player))
    play_positional_sound(sound_func, x, y, player, game_map, muffled_cutoff=800)


# Glass equip
def play_equip_glass_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/glass/equip1.mp3"), pitch_range=(0.8, 1.5), volume=1.0)

def play_unequip_glass_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/glass/unequip1.mp3"), pitch_range=(0.8, 1.5), volume=1.0)

def pick_up_glass_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/glass/equip1.mp3"), pitch_range=(1.0, 1.5), volume=1.0)

def drop_glass_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/glass/unequip1.mp3"), pitch_range=(0.8, 1.5), volume=0.5)
    
# Paper equip
def play_equip_paper_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/paper/equip1.mp3"), pitch_range=(0.8, 1.5), volume=3)

def play_unequip_paper_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/paper/unequip1.mp3"), pitch_range=(0.8, 1.5), volume=3)

def pick_up_paper_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/paper/equip1.mp3"), pitch_range=(1.0, 1.5), volume=3)

def drop_paper_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/paper/equip1.mp3"), pitch_range=(0.8, 1.5), volume=3)

# coin equip
def play_equip_coin_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/coin/1coin.mp3"), pitch_range=(0.8, 1.5), volume=1.0)

def play_unequip_coin_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/coin/1coin.mp3"), pitch_range=(0.8, 1.5), volume=1.0)

def pick_up_coin_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/coin/1coin.mp3"), pitch_range=(1.0, 1.5), volume=1.0)

def drop_coin_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/coin/1coin.mp3"), pitch_range=(0.8, 1.5), volume=1.0)

# many coins
def play_equip_manycoins_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/coin/manycoins.mp3"), pitch_range=(0.8, 1.5), volume=1.0)

def play_unequip_manycoins_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/coin/manycoins.mp3"), pitch_range=(0.8, 1.5), volume=1.0)

def pick_up_manycoins_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/coin/manycoins.mp3"), pitch_range=(1.0, 1.5), volume=1.0)

def drop_manycoins_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/coin/manycoins.mp3"), pitch_range=(0.8, 1.5), volume=1.0)

# Wood sounds
def pick_up_wood_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/wood/pickup1.mp3"), pitch_range=(1.0, 1.5), volume=.25)

def drop_wood_sound():
    play_sound_with_pitch_variation(Sound("RP/sfx/equip/wood/drop1.mp3"), pitch_range=(0.8, 1.1), volume=.25)

def play_bite_sound():
    bite_sounds = [
        Sound("RP/sfx/eat/bite1.wav"),
        Sound("RP/sfx/eat/bite2.wav"),
        Sound("RP/sfx/eat/bite3.wav"),
    ]
    sound = random.choice(bite_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.2), volume=0.5)

def play_meat_sound():
    meat_sounds = [
        Sound("RP/sfx/equip/meat/meat1.mp3"),
        Sound("RP/sfx/equip/meat/meat2.mp3"),
        Sound("RP/sfx/equip/meat/meat3.mp3"),
        Sound("RP/sfx/equip/meat/meat4.mp3"),
        Sound("RP/sfx/equip/meat/meat5.mp3"),
        Sound("RP/sfx/equip/meat/meat6.mp3"),
    ]
    sound = random.choice(meat_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.0), volume=0.5)

def play_vegetation_sound():
    vegetation_sounds = [
        Sound("RP/sfx/vegetation/1.mp3"),
        Sound("RP/sfx/vegetation/2.mp3"),
        Sound("RP/sfx/vegetation/3.mp3"),
    ]
    sound = random.choice(vegetation_sounds)
    play_sound_with_pitch_variation(sound, pitch_range=(0.8, 1.2), volume=0.5)

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
                 proximity_threshold: int = 5, base_volume: float = 1.0):
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
        base_volume=1.0
    ),
    'dungeon': AmbientSoundType(
        name='dungeon',
        sound_file='RP/sfx/loops/dungeon/dungeon_loop.wav',
        entity_names=[None],
        map_type="dungeon",
        proximity_threshold=999,  # Always play in dungeons
        base_volume=0.5
    ),
    'lush': AmbientSoundType(
        name='lush',
        sound_file='RP/sfx/loops/dungeon/lushcave_loop.wav',
        entity_names=[None],
        map_type="lush",
        proximity_threshold=999,  # Always play in lush areas
        base_volume=1.0
    ),
    'menu': AmbientSoundType(
        name='menu',
        sound_file='RP/sfx/loops/fire/fire_loop.wav',
        entity_names=[None],
        map_type=None,
        proximity_threshold=999,  # Always play when active
        base_volume=1.0
    ),
    'dungeon_music': AmbientSoundType(
        name='dungeon_music', 
        sound_file='RP/music/dungeon1.wav',  # Change this to your music file
        entity_names=[None],
        map_type=None,
        proximity_threshold=999,
        base_volume=1.0
    ),
    'menu_music': AmbientSoundType(
        name='menu_music',
        sound_file='RP/music/menu1.wav',  # Change this to your music file  
        entity_names=[None],
        map_type=None,
        proximity_threshold=999,
        base_volume=1.0
    ),
    'boss_music': AmbientSoundType(
        name='boss_music',
        sound_file='RP/sfx/loops/boss/boss1.wav',
        entity_names=[None],
        map_type=None,
        proximity_threshold=999,
        base_volume=1.0
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
            _log(f"Could not start {ambient_type} loop: {e}\n")
    
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
            if ambient_type in ['menu', 'dungeon_music', 'menu_music', 'boss_music']:  # Skip manually controlled
                continue
                
            config = AMBIENT_TYPES[ambient_type]
            player_near_source = False
            max_sound_strength = 0.0
            
            # Handle map-based ambiance (entity_names=[None])
            if config.entity_names == [None]:
                # Check map type filter
                if config.map_type is None or (hasattr(game_map, 'biome') and game_map.biome == config.map_type):
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
_menu_music_active = False

def _ray_cast_sound(start_x, start_y, end_x, end_y, game_map):
    """Ray-cast for sound propagation with material attenuation."""
    

    
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
    distance_attenuation = 1.0  # Initialize distance attenuation
    
    while True:
        # Check if we've reached the target
        if x == end_x and y == end_y:
            break
            
        # Check bounds
        if not game_map.in_bounds(x, y):

            return 0.0  # Sound doesn't reach if out of bounds
            
        # Get tile properties for sound physics
        tile_transparent = game_map.tiles["transparent"][x, y]
        
        if not tile_transparent:
            # Hit a wall - calculate sound attenuation
            try:
                tile_name = game_map.tiles["name"][x, y]
                obstacles_encountered.append(f"{tile_name}@({x},{y})")

                
                # Material-based sound attenuation
                if "Wall" in tile_name:  # Handles "Wall", "Stone Wall", etc.
                    sound_strength *= 0.15  # Walls block some sound (85% blocked)

                elif tile_name == "Door":
                    sound_strength *= 0.3  # Doors allow some sound through

                elif tile_name == "Open Door":
                    sound_strength *= 0.9  # Open doors barely affect sound

                else:
                    sound_strength *= 0.2  # Unknown solid materials

                    
                # If sound is too weak, it doesn't propagate further
                if sound_strength < 0.05:

                    return 0.0
                    
            except Exception as e:
                _log(f"Exception getting tile info: {e}\n")
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


def stop_vhs_audio_effect():
    """Immediately disable the VHS wow/flutter audio effect."""
    _mixer.vhs_enabled = False
    _mixer.vhs_time    = 0.0


def stop_all_sounds():
    """Stop all ambient loops, music, one-shot sounds, and VHS effect immediately."""
    global _menu_ambience_active, _menu_music_active

    # Stop all ambient loops
    for ambient_type in list(_ambient_manager.active_ambients):
        _ambient_manager.stop_ambient_loop(ambient_type)

    # Clear any in-flight one-shot sounds so they don't bleed into the next scene
    with _mixer.lock:
        _mixer.playing_sounds.clear()

    # Kill the VHS wow/flutter effect so it doesn't warp the next scene's audio
    stop_vhs_audio_effect()

    # Reset all global state variables
    _menu_ambience_active = False
    _menu_music_active = False

def stop_ambient_sound(ambient_type: str):
    """Stop an ambient sound loop."""
    global _menu_ambience_active, _menu_music_active
    if ambient_type == 'menu':
        _menu_ambience_active = False
    elif ambient_type == 'menu_music':
        _menu_music_active = False
    _ambient_manager.stop_ambient_loop(ambient_type)

def start_menu_ambience():
    """Start menu ambience if not already playing."""
    global _menu_ambience_active
    if not _menu_ambience_active:
        _menu_ambience_active = True
        start_ambient_sound('menu')

def stop_menu_ambience():
    """Stop menu ambience."""
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

def update_all_loop_volumes_from_settings():
    """Update volumes of all currently playing loops based on current settings."""
    global _mixer
    _mixer.update_all_loop_volumes()

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
        b, a = butter(4, normalized_cutoff, btype='low')
        
        # Apply filter along sample axis (works for both mono and stereo)
        filtered = lfilter(b, a, audio_data, axis=0)
        
        return filtered.astype(np.float32, copy=False)
        
    except Exception as e:
        _log(f"Muffling filter error: {e}\n")
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
        
    elif sound_func.__name__ == 'play_liquid_walk_sound':
        # 30% chance to not play a sound for variety
        if random.random() < 0.3:
            return
        liquid_walk_sounds = [
            Sound("RP/sfx/quaff.wav"),
            Sound("RP/sfx/quaff.wav"),
        ]
        sound = random.choice(liquid_walk_sounds)
        sound.set_volume(0.4)  # Match original volume

    elif sound_func.__name__ == 'play_poison_burn_sound':
        sound = _burn_sound_preloaded
        sound.set_volume(1.0)
        
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
        _log(f"Warning: No muffling support for sound function: {sound_func.__name__}\n")
        sound_func()
        return
    
    # Apply muffling to the sound data
    muffled_data = apply_muffling_to_audio(sound.data, cutoff, 44100)
    
    # Apply pitch variation to muffled data (same as original functions)
    pitch = random.uniform(0.9, 1.5)
    if abs(pitch - 1.0) >= 0.02:  # Only if significant change
        try:
            new_length = int(len(muffled_data) / pitch)
            muffled_data = signal.resample(muffled_data, new_length, axis=0).astype(np.float32, copy=False)
        except Exception as e:
            _log(f"Pitch variation error: {e}\n")
    
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

def _play_door_sound_at(sound_func, x, y, player, game_map):
    from animations import HeardDoorAnimation
    dx = x - player.x
    dy = y - player.y
    if (dx * dx + dy * dy) ** 0.5 <= 10 and not game_map.visible[x, y]:
        game_map.engine.animation_queue.append(HeardDoorAnimation((x, y), player))
    play_positional_sound(sound_func, x, y, player, game_map, muffled_cutoff=600)

def play_door_open_sound_at(x, y, player, game_map):
    _play_door_sound_at(play_door_open_sound, x, y, player, game_map)

def play_door_close_sound_at(x, y, player, game_map):
    _play_door_sound_at(play_door_close_sound, x, y, player, game_map)

def play_combat_sound_at(sound_func, x, y, player, game_map):
    """Play combat sound with positional muffling."""
    play_positional_sound(sound_func, x, y, player, game_map, muffled_cutoff=700)

def play_movement_sound_at(sound_func, x, y, player, game_map):
    """Play movement sound with positional muffling and entity-specific timing."""
    # Pass coordinates to sound function for unique entity timing
    if sound_func.__name__ in ['play_walk_sound', 'play_grass_walk_sound', 'play_liquid_walk_sound', 'play_swim_sound', 'play_moss_walk_sound']:
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
        
    elif sound_func.__name__ == 'play_moss_walk_sound':
        # 30% chance to not play a sound for variety (same as original)
        if random.random() < 0.3:
            return
        moss_walk_sounds = [
            Sound("RP/sfx/walk/moss/moss1.mp3"),
            Sound("RP/sfx/walk/moss/moss2.mp3"),
            Sound("RP/sfx/walk/moss/moss3.mp3"),
            Sound("RP/sfx/walk/moss/moss4.mp3"),
        ]
        sound = random.choice(moss_walk_sounds)
        sound.set_volume(0.5)  # Match original volume
    elif sound_func.__name__ == 'play_liquid_walk_sound':
        # 30% chance to not play a sound for variety
        if random.random() < 0.3:
            return
        liquid_walk_sounds = [
            Sound("RP/sfx/quaff.wav"),
            Sound("RP/sfx/quaff.wav"),
        ]
        sound = random.choice(liquid_walk_sounds)
        sound.set_volume(0.4)  # Match original volume

    elif sound_func.__name__ == 'play_swim_sound':
        swim_sounds = [
            Sound("RP/sfx/walk/swim/swim1.mp3"),
            Sound("RP/sfx/walk/swim/swim2.mp3"),
            Sound("RP/sfx/walk/swim/swim3.mp3"),
        ]
        sound = random.choice(swim_sounds)
        sound.set_volume(0.4)  # Match original volume
        
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
        _log(f"Warning: No muffling support for sound function: {sound_func.__name__}\n")
        sound_func(entity_x, entity_y) if 'walk_sound' in sound_func.__name__ else sound_func()
        return
    
    # Apply muffling to the sound data
    muffled_data = apply_muffling_to_audio(sound.data, cutoff, 44100)
    
    # Apply pitch variation to muffled data (same as original functions)
    pitch = random.uniform(0.9, 1.5)
    if abs(pitch - 1.0) >= 0.02:  # Only if significant change
        try:
            new_length = int(len(muffled_data) / pitch)
            muffled_data = signal.resample(muffled_data, new_length, axis=0).astype(np.float32, copy=False)
        except Exception as e:
            _log(f"Pitch variation error: {e}\n")
    
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
    global _menu_music_active
    if not _menu_music_active:
        _menu_music_active = True
        start_ambient_sound('menu_music')

def start_boss_music():
    """Start boss battle music."""
    stop_all_music()
    start_ambient_sound('boss_music')

def stop_all_music():
    """Stop all music."""
    stop_ambient_sound('dungeon_music')
    stop_ambient_sound('menu_music')
    stop_ambient_sound('boss_music')

def set_music_volume(volume: float):
    """Set music volume."""
    for music_type in ["dungeon_music", "menu_music", "boss_music"]:
        if music_type in AMBIENT_TYPES:
            AMBIENT_TYPES[music_type].base_volume = .3
            # FOR FUTURE USE: max(0.0, min(1.0, volume))

def set_music_files(dungeon_file: str, menu_file: str):
    """Set music file paths."""
    AMBIENT_TYPES['dungeon_music'].sound_file = dungeon_file
    AMBIENT_TYPES['menu_music'].sound_file = menu_file


def load_voice_sounds(gender: str, count: int = 30):
    folder = f"RP/voice/{gender.lower()}/"
    prefix = gender.lower()

    paths = [f"{folder}{prefix}{i}.wav" for i in range(1, count + 1)]

    #print(*paths, sep="\n")  # debug

    return [Sound(path) for path in paths]


def play_voice(gender: str, pitch: float):
    try:
        if not load_settings().get("voice_blips", True):
            return
    except Exception:
        pass
    voice_sounds = load_voice_sounds(gender)
    sound = random.choice(voice_sounds)
    play_sound_with_pitch_variation(sound, (pitch, pitch), volume=0.5)
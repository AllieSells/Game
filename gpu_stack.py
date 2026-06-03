"""gpu_stack.py — All GPU rendering, post-processing, and particle physics.

Sections
--------
  1.  IMPORTS & SHARED UTILITIES
    2.  GPU PARTICLE PHYSICS CLASSES   — DripParticle, SmokeCloudParticle, EmberParticle,
                                                                             DustParticle
  3.  CRT SETUP HELPERS              — generate_scanlines_texture, create_vignette_texture,
                                       create_glare_texture
  4.  DEGAUSS ANIMATION CLASS        — DegaussAnimation (degauss / teleport modes)
  5.  GPU STACK CLASS                — GPUStack: all per-frame GPU state and render passes
        5a. Bloom render targets
        5b. Game-layer animation targets & registry
        5c. CRT barrel curvature & chromatic aberration
        5d. Particle render passes  — _gpu_ember_render, _gpu_smoke_render, _gpu_drip_render
        5e. Animation pass runner   — run_gpu_anim_passes (bloom + no-bloom)
        5f. Full-scene Kawase bloom — gpu_bloom
        5g. Lightmap                — _apply_lightmap
"""

# =============================================================================
# SECTION 1 — IMPORTS & SHARED UTILITIES
# =============================================================================

from __future__ import annotations

import random
import numpy as np
import tcod
import tcod.sdl.render
import math

from PIL import Image


class _BurnSpark:
    __slots__ = ("origin_y", "vx", "vy", "frames", "total_frames", "fx", "fy")

    def __init__(
        self,
        origin_y: float,
        vx: float,
        vy: float,
        frames: int,
        total_frames: int,
        fx: float,
        fy: float,
    ) -> None:
        self.origin_y = origin_y
        self.vx = vx
        self.vy = vy
        self.frames = frames
        self.total_frames = total_frames
        self.fx = fx
        self.fy = fy


def get_data_path(filename: str) -> str:
    """Re-exported so callers can import it from here if convenient."""
    import os
    base = getattr(get_data_path, "_base", None)
    if base is None:
        base = os.path.dirname(os.path.abspath(__file__))
        get_data_path._base = base
    return os.path.join(base, filename)


# =============================================================================
# SECTION 2 — GPU PARTICLE PHYSICS CLASSES
# =============================================================================
# These classes own only the *physics* state for each particle.
# All pixel rendering is performed by the GPU render passes in Section 5d.
# They are kept here (alongside the render passes) so the full lifecycle of
# each particle type — spawn → physics tick → GPU draw → expire — is in one file.

class DripParticle:
    """Physics state for a falling liquid-drip pixel.

    Rendered by GPUStack._gpu_drip_render (no-bloom, BLEND composite).
    Starts near the top of its origin tile and expires at the bottom.
    """

    def __init__(self, position: tuple, color: tuple):
        x, y = position
        self.origin_y = float(y)
        self.fx = float(x) + random.uniform(-0.3, 0.3)
        self.fy = self.origin_y - 0.35          # start near top of tile
        self.vy = random.uniform(0.05, 0.1)     # fall speed (tiles/tick)
        self.vx = 0.0
        self.frames = random.randint(20, 40)
        self.total_frames = self.frames
        self.render_priority = 2
        self.color = color

    def tick(self, console, game_map) -> None:
        if self.frames <= 0:
            return
        if self.fy >= self.origin_y + 0.5:
            self.fy = self.origin_y + 0.5
        else:
            self.fy += self.vy
            self.fx += self.vx
            self.vx = max(-0.3, min(0.3, self.vx))
        self.frames -= 1


class LightShaftParticles:
    """Physics state for a directional light shaft from a Window tile.

    shaft_direction: -1 = going north (up on screen), 1 = going south (down on screen).
    Rendered by GPUStack._light_shaft_render (bloom pass) as a fading trapezoid.
    """

    def __init__(self, position: tuple, shaft_direction: int):
        x, y = position
        self.fx = float(x)
        self.fy = float(y)
        self.shaft_direction = shaft_direction   # -1 north/up, +1 south/down
        self.frames = 999999999   # perpetual — never expires
        self.total_frames = self.frames
        self.render_priority = 1
        self.length = 2.0               # shaft length in world tiles
        self.color = (255, 242, 210)    # warm-white RGB

    def tick(self, console, game_map) -> None:
        pass  # perpetual; no countdown


class DustParticle:
    """Physics state for a slow ambient dust mote.

    Spawned by Engine ambient particle ticking on visible tiles that pass the
    current dust gate. Rendered by GPUStack._dust_render as a drifting mote.
    """

    def __init__(self, position: tuple):
        x, y = position
        self.source_pos = (int(x), int(y))
        self.origin_x = float(x)
        self.origin_y = float(y)
        self.fx = float(x) + random.uniform(-0.42, 0.42)
        self.fy = float(y) + random.uniform(-0.08, 0.42)
        self.vx = random.uniform(-0.006, 0.006)
        self.vy = random.uniform(-0.014, -0.005)
        self.frames = random.randint(80, 150)
        self.total_frames = self.frames
        self.render_priority = 2
        self.size = random.uniform(0.7, 1.7)
        self.twinkle_phase = random.uniform(0.0, math.tau)
        self.color = random.choice(
            (
                (150, 140, 126),
                (164, 154, 138),
                (178, 168, 152),
            )
        )

    def tick(self, console, game_map) -> None:
        if self.frames <= 0:
            return
        age_ticks = self.total_frames - self.frames
        self.fx += self.vx + math.sin(age_ticks * 0.07 + self.twinkle_phase) * 0.0018
        self.fy += self.vy
        self.vx = max(-0.02, min(0.02, self.vx + random.uniform(-0.0012, 0.0012)))
        if self.fy < self.origin_y - 0.8:
            self.fy = self.origin_y - 0.8
            self.vy = random.uniform(-0.003, 0.0)
        self.frames -= 1

class RevealParticle:
    """Sparkles along a path or at a point"""

    def __init__(self, position: tuple, color: tuple = (255, 255, 255), path: list[tuple] = None):
        x, y = position
        self.fx = float(x)
        self.fy = float(y)
        self.path = path or []
        self.frames = 1200
        self.total_frames = self.frames
        self.render_priority = 2
        self.color = color

    def tick(self, console, game_map) -> None:
        if self.frames <= 0:
            return
        self.frames -= 1

class SpaceDistortSpellParticle:
    """A brief expanding distortion effect for space-warping spells like Blink.

    Rendered by GPUStack._space_distort_render (bloom pass) as a brightening halo
    around the target tile that rapidly expands and fades over its lifetime.
    """

    def __init__(self, position: tuple):
        x, y = position
        self.fx = float(x)
        self.fy = float(y)
        self.frames = 12
        self.total_frames = self.frames
        self.render_priority = 2
        self.color = (200, 220, 255)  # icy blue-white

    def tick(self, console, game_map) -> None:
        if self.frames <= 0:
            return
        self.frames -= 1


class JaggedLineSpellParticle:
    """Jagged line spell that follows path from caster to target."""

    def __init__(self, path: list[tuple], color: tuple, frames: int = 12):
        self.path = path
        self.color = color
        self.frames = 12
        self.total_frames = self.frames
        self.render_priority = 2

    def get_light(self):
        if self.frames <= 0 or not self.path:
            return None
        
        max_nodes = 4
        stride = max(1, len(self.path) // max_nodes)
        pts = self.path[::stride]
        if pts[-1] != self.path[-1]:
            pts.append(self.path[-1])
        pts = pts[:max_nodes]

        age = 1.0 - self.frames / self.total_frames
        pulse = 0.85 + 0.15 * math.sin(age * 20)
        base_i = 1.0 * pulse

        return [
            {
                "source_x": int(x),
                "source_y": int(y),
                "radius": 1,
                "max_intensity": base_i,
                "color": self.color,
            }
            for (x, y) in pts
        ]

    def tick(self, console=None, game_map=None) -> None:
        self.frames -= 1


class ProjectileTrailParticle:
    """Projectile trail rendered entirely in GPU passes.

    Used for thrown items and bow shots; stores only physics/path timing state.
    """

    def __init__(self, path: list[tuple], color: tuple):
        self.path = [(int(px), int(py)) for px, py in (path or [])]
        self.color = color
        self.frames = max(8, min(18, len(self.path) + 6))
        self.total_frames = self.frames
        self.render_priority = 2

    def tick(self, console=None, game_map=None) -> None:
        self.frames -= 1


class IlluminatedParticle:
    """Persistent light-ray corona for a light orb (rendered by GPUStack._illuminated_render).

    Tracks the entity position every tick so the glow moves with the orb.
    Lifetime is long enough to outlast the LightEffect duration; the engine
    keeps exactly one instance per entity and never spawns a second while one
    is alive.
    """

    # Shared slow-breath phase so all orbs pulse together
    _breath_speed = 0.4   # Hz — full cycle every 2.5 s

    def __init__(self, entity, color: tuple = (255, 255, 210)):
        self.entity = entity
        self.fx = float(entity.x)
        self.fy = float(entity.y)
        self.frames = 9000        # ~150 s @ 60 fps — outlasts any LightEffect
        self.total_frames = self.frames
        self.render_priority = 2
        self.color = color

    def tick(self, console, game_map) -> None:
        # Always follow the entity so the glow never trails behind
        self.fx = float(self.entity.x)
        self.fy = float(self.entity.y)
        # Expire if the entity no longer has the Illuminated effect
        still_lit = any(
            getattr(e, 'name', '') == 'Illuminated'
            for e in getattr(self.entity, 'effects', [])
        )
        if not still_lit:
            self.frames = 0
        else:
            self.frames -= 1


class SleepingParticle:
    """Persistent sleep aura for an entity that is currently asleep.

    The particle follows the entity and renders a small drifting blue 'Z'
    cluster above the actor's tile until the Sleep effect ends.
    """

    _breath_speed = 0.85  # faster, lighter pulse than illumination

    def __init__(self, entity, color: tuple = (160, 180, 255)):
        self.entity = entity
        self.fx = float(entity.x)
        self.fy = float(entity.y)
        self.frames = 9000
        self.total_frames = self.frames
        self.render_priority = 2
        self.color = color

    def tick(self, console, game_map) -> None:
        self.fx = float(self.entity.x)
        self.fy = float(self.entity.y)
        still_asleep = any(
            getattr(e, 'name', '') == 'Sleep'
            for e in getattr(self.entity, 'effects', [])
        )
        if not still_asleep:
            self.frames = 0
        else:
            self.frames -= 1

class HealthParticle:
    """Rising green cross indicating healing."""
    def __init__(self, position: tuple, entity):
        x, y = position
        self.fx = float(x)
        self.fy = float(y)
        self.vx = random.uniform(-0.018, 0.018)   # gentle horizontal wobble
        self.entity = entity
        self.frames = 20
        self.total_frames = self.frames
        self.render_priority = 2
    
    def tick(self, console, game_map) -> None:
        if self.frames <= 0:
            return
    
        self.fx += self.vx
        self.fy -= 0.02  # rise speed
        self.frames -= 1

class DamageNumberParticle:
    """Rising damage number that floats up from a damaged entity.

    Rendered by GPUStack._damage_number_render (bloom pass).
    Displays the damage amount as small pixel-art digits in orange-red.
    """

    # Minimal 3-wide × 5-tall pixel font (list of (col, row) 'on' cells)
    _PIXEL_DIGITS: dict = {
        '0': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(2,2),(0,3),(2,3),(0,4),(1,4),(2,4)],
        '1': [(1,0),(1,1),(1,2),(1,3),(1,4)],
        '2': [(0,0),(1,0),(2,0),(2,1),(0,2),(1,2),(2,2),(0,3),(0,4),(1,4),(2,4)],
        '3': [(0,0),(1,0),(2,0),(2,1),(1,2),(2,2),(2,3),(0,4),(1,4),(2,4)],
        '4': [(0,0),(2,0),(0,1),(2,1),(0,2),(1,2),(2,2),(2,3),(2,4)],
        '5': [(0,0),(1,0),(2,0),(0,1),(0,2),(1,2),(2,3),(0,4),(1,4),(2,4)],
        '6': [(0,0),(1,0),(2,0),(0,1),(0,2),(1,2),(2,2),(0,3),(2,3),(0,4),(1,4),(2,4)],
        '7': [(0,0),(1,0),(2,0),(2,1),(2,2),(2,3),(2,4)],
        '8': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(1,2),(2,2),(0,3),(2,3),(0,4),(1,4),(2,4)],
        '9': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(1,2),(2,2),(2,3),(0,4),(1,4),(2,4)],
    }

    def __init__(self, position: tuple, number: int, color: tuple = (0, 225, 0)):
        x, y = position
        # Offset to one side so numbers don't sit directly on the entity
        side = random.choice((-1, 1))
        self.fx = float(x) + side * random.uniform(0.35, 0.6)
        self.fy = float(y) - 0.3          # spawn just above the entity's tile
        self.vx = side * random.uniform(0.03, 0.06)  # arc outward
        self.vy = random.uniform(-0.10, -0.07)        # initial upward pop
        self.number = str(number)
        self.color = color                 # (r, g, b) base colour
        self.frames = 28                   # shorter lifetime — less time in the way
        self.total_frames = self.frames
        self.render_priority = 2

    def tick(self, console, game_map) -> None:
        if self.frames <= 0:
            return
        self.vy += 0.012    # gravity — pulls the number back down after the pop
        self.fx += self.vx
        self.fy += self.vy
        self.frames -= 1


class BurningParticle:
    """Fire emitter that owns multiple internal sparks.

    One emitter instance is reused per fire source (tile/entity/campfire) and
    emits short-lived spark states internally, avoiding burst allocation of many
    BurningParticle class objects in the animation queue.
    """

    def __init__(
        self,
        position: tuple,
        entity: object = None,
        contained: bool = False,
        max_sparks: int = 2,
        emit_per_tick: int = 1,
        ttl_frames: int = 18,
    ):
        x, y = position
        self.entity = entity
        self.contained = contained
        self.render_priority = 2

        self.anchor_x = float(x)
        self.anchor_y = float(y)
        self.max_sparks = max(1, int(max_sparks))
        self.emit_per_tick = max(1, int(emit_per_tick))
        self.frames = max(1, int(ttl_frames))
        self.total_frames = self.frames
        self.emitting = True

        # Render code and caches expect fx/fy on animations; keep these in sync
        # with the emitter anchor for compatibility.
        self.fx = self.anchor_x
        self.fy = self.anchor_y

        # Internal spark states are slot-based objects to keep per-spark overhead low.
        self.sparks: list[_BurnSpark] = []

    def set_anchor(self, x: float, y: float) -> None:
        self.anchor_x = float(x)
        self.anchor_y = float(y)
        self.fx = self.anchor_x
        self.fy = self.anchor_y

    def refresh(self, ttl_frames: int = 18, max_sparks: int | None = None, emit_per_tick: int | None = None) -> None:
        self.emitting = True
        self.frames = max(self.frames, max(1, int(ttl_frames)))
        if max_sparks is not None:
            self.max_sparks = max(1, int(max_sparks))
        if emit_per_tick is not None:
            self.emit_per_tick = max(1, int(emit_per_tick))

    def deactivate(self) -> None:
        """Stop spawning new sparks but allow current sparks to fade out."""
        self.emitting = False

    def _spawn_spark(self) -> None:
        spark_origin_y = self.anchor_y
        spark_frames = random.randint(8, 14)
        spark = _BurnSpark(
            origin_y=spark_origin_y,
            vx=random.uniform(-0.018, 0.018),
            vy=random.uniform(-0.07, -0.035),
            frames=spark_frames,
            total_frames=spark_frames,
            fx=self.anchor_x + (random.uniform(-0.42, 0.42) if not self.contained else 0.0),
            fy=self.anchor_y + (random.uniform(0.0, 0.35) if not self.contained else 0.2),
        )
        self.sparks.append(spark)

    def tick(self, console, game_map) -> None:
        # Follow dynamic entities while keeping a stable anchor for static sources.
        if self.entity is not None and hasattr(self.entity, "x") and hasattr(self.entity, "y"):
            self.set_anchor(self.entity.x, self.entity.y)

        # Emit new sparks up to current budget while active.
        if self.emitting and self.frames > 0 and len(self.sparks) < self.max_sparks:
            emit_count = min(self.emit_per_tick, self.max_sparks - len(self.sparks))
            for _ in range(emit_count):
                self._spawn_spark()

        updated_sparks: list[_BurnSpark] = []
        for spark in self.sparks:
            if self.contained:
                spark.fx += spark.vx * 2
                spark.fy += spark.vy / 2
            else:
                spark.fx += spark.vx
                spark.fy += spark.vy

            # Cap rise at 1 tile above spawn.
            min_y = spark.origin_y - 1.0
            if spark.fy < min_y:
                spark.fy = min_y
                spark.vy = 0.0

            spark.frames -= 1
            if spark.frames > 0:
                updated_sparks.append(spark)
        self.sparks = updated_sparks

        self.frames -= 1
        if self.frames <= 0:
            self.emitting = False

        # Keep emitter alive while existing sparks are still visible, but do not emit.
        if self.sparks:
            self.frames = max(1, self.frames)

class DodgeParticle:
    """Physics state for a dodge-step effect.

    The tile image slides in *direction* over its lifetime while leaving
    ghost afterimage copies trailing behind it.  Rendered by
    GPUStack._dodge_render (bloom pass).
    """
    def __init__(self, position: tuple, character: str = "*",
                 direction: tuple = (0, 0)):
        x, y = position
        self.fx = float(x)
        self.fy = float(y)
        self.frames = 10
        self.total_frames = self.frames
        self.render_priority = 2
        self.character = character

        dx, dy = direction
        mag = math.hypot(dx, dy)
        if mag > 0:
            self.dir = (dx / mag, dy / mag)
        else:
            self.dir = (0.0, 0.0)

    def tick(self, console, game_map) -> None:
        if self.frames <= 0:
            return
        self.frames -= 1


class SlashParticle:
    """Physics state for a brief melee slash effect."""

    def __init__(self, position: tuple, enchanted: bool = False, color: tuple = (255, 255, 255), angle: tuple = (0, 0), type: str = "blade"):
        import math as _math
        import random as _random
        x, y = position
        self.fx = float(x)
        self.fy = float(y)
        self.total_frames = 12
        self.frames = self.total_frames
        self.enchanted = enchanted
        self.color = color
        self.type = type
        # Bake a fixed jitter angle so the slash renders at the same angle every frame
        dx, dy = angle
        mag = _math.hypot(dx, dy)
        if mag > 0:
            jitter = _random.uniform(-0.5, 0.5)
            cos_j, sin_j = _math.cos(jitter), _math.sin(jitter)
            nx = (cos_j * dx - sin_j * dy) / mag
            ny = (sin_j * dx + cos_j * dy) / mag
            self.angle = (nx, ny)
        else:
            self.angle = (0.0, 0.0)

    def tick(self, console, game_map) -> None:
        if self.frames <= 0:
            return
        self.frames -= 1




class SmokeCloudParticle:
    """Physics state for a rising smoke puff.

    Rendered by GPUStack._gpu_smoke_render (bloom composite).
    """

    def __init__(self, position: tuple):
        x, y = position
        self.fx = float(x) + random.uniform(-0.2, 0.2)
        self.fy = float(y) + random.uniform(-0.2, 0.2)
        self.vy = random.uniform(0.02, 0.05)    # rise speed (tiles/tick)
        self.vx = random.uniform(-0.01, 0.01)
        self.frames = random.randint(60, 120)
        self.total_frames = self.frames
        self.render_priority = 2

    def tick(self, console, game_map) -> None:
        if self.frames <= 0:
            return
        self.fy -= self.vy
        self.fx += self.vx
        self.vx += random.uniform(-0.005, 0.005)
        self.vx = max(-0.2, min(0.2, self.vx))
        self.frames -= 1

class CRTBleedAnim:
    """Physics state for a brief red bleed effect when the player takes damage.

    Rendered by GPUStack._damage_bleed_render (no-bloom, BLEND composite).
    """

    def __init__(self):
        self.frames = 30
        self.total_frames = self.frames
        self.render_priority = 2

    def tick(self, console=None, game_map=None) -> None:
        if self.frames <= 0:
            return
        self.frames -= 1


class EmberParticle:
    """Physics state for a bright ember pixel rising from fire.

    Rendered by GPUStack._gpu_ember_render (bloom composite).
    Starts near-white so the Kawase bloom picks it up at full intensity,
    then the render pass fades it through orange → red as it ages.
    """

    def __init__(self, position: tuple):
        x, y = position
        self.fx = float(x) + random.uniform(-0.07, 0.07)
        self.fy = float(y) + random.uniform(-0.3, 0.3)
        self.vy = random.uniform(0.08, 0.1)     # rise speed (tiles/tick)
        self.vx = random.uniform(-0.005, 0.005)
        self.frames = random.randint(12, 22)
        self.total_frames = self.frames
        self.render_priority = 2

    def tick(self, console, game_map) -> None:
        if self.frames <= 0:
            return
        self.fy -= self.vy
        self.fx += self.vx
        self.vx += random.uniform(-0.006, 0.006)
        self.vx = max(-0.35, min(0.35, self.vx))
        self.frames -= 1


class FireballExplosionParticle:
    """Expanding fire explosion for the Fireball spell.

    Rendered by GPUStack._fireball_explosion_render (bloom pass) as a
    bright central flash that blooms into an expanding ring of fire embers.
    """

    def __init__(self, position: tuple, radius: float = 2.5):
        x, y = position
        self.fx = float(x)
        self.fy = float(y)
        self.radius = float(radius)     # blast radius in world tiles
        self.frames = 24
        self.total_frames = self.frames
        self.render_priority = 2

    def tick(self, console=None, game_map=None) -> None:
        if self.frames <= 0:
            return
        self.frames -= 1


class PoisonSprayParticle:
    """Toxic acid splatter for the Poison Spray spell.

    Rendered by GPUStack._poison_spray_render (bloom pass) as a burst of
    acid-green droplets radiating outward from the target tile.
    Droplet directions are baked at spawn so the pattern is stable each frame.
    """

    _TWO_PI = 2.0 * math.pi

    def __init__(self, position: tuple):
        x, y = position
        self.fx = float(x)
        self.fy = float(y)
        N = 20
        self.directions = [
            (
                math.cos(self._TWO_PI * i / N + random.uniform(-0.25, 0.25)),
                math.sin(self._TWO_PI * i / N + random.uniform(-0.25, 0.25)),
                random.uniform(0.55, 1.0),   # per-droplet speed factor
            )
            for i in range(N)
        ]
        self.frames = 18
        self.total_frames = self.frames
        self.render_priority = 2

    def tick(self, console=None, game_map=None) -> None:
        if self.frames <= 0:
            return
        self.frames -= 1


# =============================================================================
# SECTION 3 — CRT SETUP HELPERS
# =============================================================================

def generate_scanlines_texture(line_density: float = 0.5, intensity: float = 0.35) -> np.ndarray:
    """Return a seamlessly tileable scanline overlay as an RGBA numpy array.

    line_density  — higher → more scanlines (thinner gaps).
    intensity     — 0.0 = no effect, 1.0 = fully black troughs.
    The texture is 1 px wide (SDL stretches horizontally) and tall enough
    for smooth 1 px-per-frame scrolling without visible pattern repeats.
    """
    period   = 2.0 * np.pi / line_density
    single_h = max(int(np.round(period)), 2)
    repeats  = max(1024 // single_h, 1)
    tile_h   = single_h * repeats
    y        = np.arange(tile_h, dtype=np.float32)
    scanline    = 0.5 + 0.5 * np.sin(y * line_density)
    brightness  = (1.0 - intensity * (1.0 - scanline))
    brightness_u8 = (np.clip(brightness, 0.0, 1.0) * 255).astype(np.uint8)
    tex_np = np.empty((tile_h, 1, 4), dtype=np.uint8)
    tex_np[..., 0] = brightness_u8[:, np.newaxis]
    tex_np[..., 1] = brightness_u8[:, np.newaxis]
    tex_np[..., 2] = brightness_u8[:, np.newaxis]
    tex_np[..., 3] = 255
    return tex_np


def create_vignette_texture(renderer, w: int = 512, h: int = 512):
    """Return an SDL texture that darkens the screen edges (BLEND mode)."""
    y_idx, x_idx = np.ogrid[:h, :w]
    cx, cy = w / 2, h / 2
    dist   = ((x_idx - cx) ** 2 + (y_idx - cy) ** 2) / (cx * cx + cy * cy)
    alpha  = (np.clip(dist, 0, 1) * 50).astype(np.uint8)
    tex    = np.zeros((h, w, 4), dtype=np.uint8)
    tex[..., 3] = alpha
    texture = renderer.upload_texture(tex)
    texture.blend_mode = tcod.sdl.render.BlendMode.BLEND
    return texture


def create_glare_texture(renderer, w: int = 512, h: int = 512):
    """Return an SDL texture that adds a subtle CRT glass glare (BLEND mode)."""
    y_idx, x_idx = np.ogrid[:h, :w]
    cx, cy = w * 0.35, h * 0.22
    dist   = np.sqrt(((x_idx - cx) / (w * 0.55)) ** 2 + ((y_idx - cy) / (h * 0.42)) ** 2)
    glare  = np.clip(1.0 - dist, 0.0, 1.0) ** 2.5
    alpha  = (glare * 28).astype(np.uint8)
    tex    = np.zeros((h, w, 4), dtype=np.uint8)
    tex[..., :3] = 255
    tex[..., 3]  = alpha
    texture = renderer.upload_texture(tex)
    texture.blend_mode = tcod.sdl.render.BlendMode.BLEND
    return texture




# =============================================================================
# SECTION 3b — CRT POWER ANIMATION CLASS
# =============================================================================
# Blocking CRT power-off / power-on animation played on the main thread.
# Power-off: image contracts vertically to a bright horizontal line, then
#            line fades to black.  (~0.45 s total)
# Power-on:  white flash expands outward, image grows from line to full height.
#            (~0.45 s total)
#
# Usage (blocking — call from main thread):
#   anim = CRTSwitchAnimation(renderer, scene_tex, window_w, window_h)
#   anim.play_off()   # blocks until complete
#   anim.play_on()    # blocks until complete

class CRTSwitchAnimation:
    """Blocking CRT power-off / power-on wipe.

    play_off(scene_tex) — rapid vertical collapse to a bright line, line
                          contracts to a dot, dot pops.  (~0.55 s)
    play_on()           — phosphor warm-up: dot → line → full-height bloom,
                          no scene_tex needed; game frame takes over after.
                          (~0.65 s)
    """

    _LINE_H = 3   # pixel height of the contracted line

    def __init__(self, renderer, window_w: int, window_h: int):
        self._renderer = renderer
        self._w        = window_w
        self._h        = window_h

        # 1×1 white pixel stretched as overlay / line / dot
        # alpha=255 is required — SDL alpha_mod multiplies per-pixel alpha,
        # so alpha=0 would make the texture permanently invisible.
        _px = np.array([[[255, 255, 255, 255]]], dtype=np.uint8)
        self._overlay = renderer.upload_texture(_px)
        self._overlay.blend_mode = tcod.sdl.render.BlendMode.BLEND

    # ------------------------------------------------------------------

    def play_off(self, scene_tex, event_pump=None, glare_tex=None) -> None:
        """Physically accurate CRT power-off.  Blocks until done (~1.4 s).

        Phases                                              (real seconds)
        ------
        0.00-0.05  Vertical snap     — p^12 easing, collapses in ~3 frames  (~0.07 s)
        0.05-0.57  Retrace line hold — bright white phosphor stripe           (~0.73 s)
        0.57-0.76  Line contracts    — shrinks symmetrically from both ends   (~0.27 s)
        0.76-0.90  Phosphor dot      — hot spot lingers at screen centre      (~0.20 s)
        0.90-1.00  Dot pops          — quadratic fade to black                (~0.14 s)
        """
        import math
        import time

        # ---- Tunable parameters ----
        DURATION         = 1.4    # total length in seconds
        # Phase boundaries (0..1 normalised)
        T_SNAP_END       = 0.1   # vertical snap ends
        T_LINE_END       = 0.57   # retrace line hold ends
        T_CONTRACT_END   = 0.76   # line contracts to dot
        T_DOT_END        = 0.90   # dot holds, then pops to black
        # Retrace line
        LINE_FLICKER_AMP  = 0.025 # flicker amplitude (0 = none, 0.05 = strong)
        LINE_FLICKER_FREQ = 36    # flicker cycles across the line phase
        LINE_DIM_RATE     = 0.50  # fraction brightness lost over line phase
        # Phosphor dot
        DOT_W            = 1     # peak pixel width
        DOT_H            = 1      # peak pixel height
        DOT_HALO_PAD_W   = 2     # extra px added to dot_w for halo
        DOT_HALO_PAD_H   = 2     # extra px added to dot_h for halo
        DOT_HALO_ALPHA   = 100     # max halo alpha (0-255)
        # Dot pop (final fade)
        POP_W            = 10     # pixel width at start of pop
        POP_H            = 4      # pixel height at start of pop
        # ---------------------

        t_start  = time.perf_counter()
        w, h     = self._w, self._h
        renderer = self._renderer
        ov       = self._overlay
        LINE_H   = self._LINE_H
        line_cy  = h // 2

        def _draw_line(lx: int, line_w: int, alpha: int, color: tuple) -> None:
            """Retrace line with soft vertical bloom (3-layer feather)."""
            r, g, b = color
            ly = line_cy - LINE_H // 2
            ov.color_mod = (r, g, b)
            # Outer feather ±2 px
            ov.alpha_mod = max(0, int(alpha * 0.22))
            renderer.copy(ov, dest=(lx, max(0, ly - 2),              line_w, 1))
            renderer.copy(ov, dest=(lx, min(h - 1, ly + LINE_H + 1), line_w, 1))
            # Inner feather ±1 px
            ov.alpha_mod = max(0, int(alpha * 0.60))
            renderer.copy(ov, dest=(lx, max(0, ly - 1),         line_w, 1))
            renderer.copy(ov, dest=(lx, min(h - 1, ly + LINE_H), line_w, 1))
            # Core line
            ov.alpha_mod = min(255, alpha)
            renderer.copy(ov, dest=(lx, ly, line_w, LINE_H))

        _off_frame = 0
        print("[CRT play_off] loop start")
        while True:
            if event_pump:
                for _ in event_pump():
                    pass
            t = (time.perf_counter() - t_start) / DURATION
            if t >= 1.0:
                break

            renderer.draw_color = (0, 0, 0, 255)
            renderer.clear()
            ov.blend_mode = tcod.sdl.render.BlendMode.BLEND

            if t < T_SNAP_END:
                # ---- SNAP: image collapses vertically in ~3 frames ----
                p     = t / T_SNAP_END
                ep    = p ** 12          # near-instantaneous
                cur_h = max(LINE_H, int(h * (1.0 - ep)))
                dy    = (h - cur_h) // 2
                scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                scene_tex.alpha_mod  = 255
                scene_tex.color_mod  = (255, 255, 255)
                renderer.copy(scene_tex, dest=(0, dy, w, cur_h))
                # Extreme overexposure as beam energy concentrates into one line
                boost_a = int(ep * 245)
                if boost_a > 0:
                    ov.alpha_mod = boost_a
                    ov.color_mod = (255, 252, 215)
                    renderer.copy(ov, dest=(0, dy, w, cur_h))

            elif t < T_LINE_END:
                # ---- Full-width retrace line: blazing bright, holds a long time ----
                p       = (t - T_SNAP_END) / (T_LINE_END - T_SNAP_END)
                # Phosphor flicker — more pronounced early on
                flicker = 1.0 + LINE_FLICKER_AMP * math.sin(p * math.pi * LINE_FLICKER_FREQ) * (1.0 - p)
                # Brightness starts near-blinding, dims gradually
                alpha   = max(12, int(flicker * (1.0 - p * LINE_DIM_RATE) * 255))
                # Warm white cools from near-UV to amber as beam current drops
                rr      = 255
                gg      = int(255 - p * 18)
                bb      = int(220 - p * 50)
                _draw_line(0, w, alpha, (rr, gg, max(1, bb)))

            elif t < T_CONTRACT_END:
                # ---- Line contracts symmetrically from both ends ----
                p      = (t - T_LINE_END) / (T_CONTRACT_END - T_LINE_END)
                ep     = p ** 1.6        # ease-in
                line_w = max(6, int(w * (1.0 - ep)))
                lx     = (w - line_w) // 2
                alpha  = max(10, int((1.0 - p * 0.35) * 220))
                _draw_line(lx, line_w, alpha, (255, 244, 188))

            elif t < T_DOT_END:
                # ---- Phosphor dot persists at screen centre ----
                p     = (t - T_CONTRACT_END) / (T_DOT_END - T_CONTRACT_END)
                dot_w = max(6,  int(DOT_W * (1.0 - p * 0.55)))
                dot_h = max(2,  int(DOT_H * (1.0 - p * 0.40)))
                dot_x = (w - dot_w) // 2
                dot_y = line_cy - dot_h // 2
                # Outer halo — diffuse glow around the bright core
                halo_w = dot_w + DOT_HALO_PAD_W
                halo_h = dot_h + DOT_HALO_PAD_H
                ov.color_mod = (255, 248, 200)
                ov.alpha_mod = max(0, int((1.0 - p * 0.60) * DOT_HALO_ALPHA))
                renderer.copy(ov, dest=((w - halo_w) // 2, dot_y - 5, halo_w, halo_h))
                # Core dot — fully opaque solid rect
                core_a = max(30, int((1.0 - p * 0.55) * 255))
                ov.color_mod = (255, 252, 215)
                ov.alpha_mod = core_a
                renderer.copy(ov, dest=(dot_x, dot_y, dot_w, dot_h))

            else:
                # ---- Dot pops: quadratic fade ----
                p     = (t - T_DOT_END) / (1.0 - T_DOT_END)
                fade  = (1.0 - p) ** 2
                dot_w = max(2, int(POP_W * fade))
                dot_h = max(1, int(POP_H * fade))
                dot_x = (w - dot_w) // 2
                dot_y = line_cy - dot_h // 2
                ov.color_mod = (255, 252, 220)
                ov.alpha_mod = int(fade * 255)
                renderer.copy(ov, dest=(dot_x, dot_y, dot_w, dot_h))

            if glare_tex is not None:
                renderer.copy(glare_tex, dest=(0, 0, w, h))
            print(f"[CRT play_off] frame {_off_frame} t={t:.3f} pre-present")
            renderer.present()
            print(f"[CRT play_off] frame {_off_frame} post-present")
            _off_frame += 1
            time.sleep(1.0 / 60)

        print(f"[CRT play_off] loop done after {_off_frame} frames")
        # Fully black
        renderer.draw_color = (0, 0, 0, 255)
        renderer.clear()
        if glare_tex is not None:
            renderer.copy(glare_tex, dest=(0, 0, w, h))
        renderer.present()

    # ------------------------------------------------------------------

    def play_on(self, scene_tex, event_pump=None, glare_tex=None, gpu_stack=None,
                scanlines_tex=None, scanlines_h=0, vignette_tex=None) -> None:
        """Physically accurate CRT power-on.  Blocks until done (~1.8 s).

        Phases                                                  (real seconds)
        ------
        0.00-0.18  Phosphor warmup  — dim green glow builds from nothing       (~0.32 s)
        0.18-0.42  Dot brightens    — green shifts to warm white, blooms large  (~0.43 s)
        0.42-0.57  Dot to line      — horizontal scan locks in, stretches out   (~0.27 s)
        0.57-0.67  Line hold        — blazing full-width stripe at peak         (~0.18 s)
        0.67-0.87  Expansion        — image unrolls with spring overshoot       (~0.36 s)
        0.87-1.00  Settle           — AGC normalises, final bloom fades         (~0.23 s)
        """
        import math
        import time
        import sounds

        # ---- Tunable parameters ----
        DURATION           = 1.8    # total length in seconds
        # Phase boundaries (0..1 normalised)
        T_WARMUP_END       = 0.18   # green phosphor warmup ends
        T_BLOOM_END        = 0.42   # dot bloom ends
        T_STRETCH_END      = 0.57   # dot-to-line stretch ends
        T_LINE_END         = 0.67   # blazing line hold ends
        T_EXPAND_END       = 1.2   # vertical expansion ends
        # Warmup dot (green, dim)
        WARMUP_HALO_W      = 6     # max halo width (px)
        WARMUP_HALO_H      = 4     # max halo height (px)
        WARMUP_HALO_ALPHA  = 70     # max halo alpha (0-255)
        WARMUP_DOT_W       = 1     # max core dot width (px)
        WARMUP_DOT_H       = 1      # max core dot height (px)
        WARMUP_DOT_ALPHA   = 220    # max core dot alpha (0-255)
        # Bloom (dot grows green → white)
        BLOOM_DOT_W_START  = 16     # dot width at bloom start
        BLOOM_DOT_W_GROW   = 22     # px of growth by bloom end
        BLOOM_DOT_H_START  = 1      # dot height at bloom start
        BLOOM_DOT_H_GROW   = 1      # px of growth by bloom end
        BLOOM_HALO_PAD_W   = 5     # extra px on outer halo width
        BLOOM_HALO_PAD_H   = 2     # extra px on outer halo height
        BLOOM_MID_PAD_W    = 3     # extra px on mid halo width
        BLOOM_MID_PAD_H    = 2      # extra px on mid halo height
        BLOOM_OUTER_ALPHA  = 6    # max outer halo alpha
        BLOOM_MID_ALPHA    = 4    # max mid halo alpha
        # Spring overshoot during expansion
        SPRING_OVERSHOOT   = -40.0   # fraction (0.07 = 7% overshoot)
        SPRING_DECAY       = 7.0    # damping coefficient
        SPRING_FREQ        = 3.2    # oscillation frequency
        # VHS horizontal wobble during expansion
        VHS_WOBBLE_AMP     = 10     # max horizontal shift (px)
        VHS_WOBBLE_FREQ    = 13.0   # oscillation cycles within the phase
        VHS_WOBBLE_DECAY   = 4.5   # damping rate (higher = damps faster)
        # Bloom wash (warm white flash as image expands — uniform, scene-independent)
        BLOOM_WASH_ALPHA   = 180    # peak wash alpha (high = visible on dark scenes)
        BLOOM_WASH_DECAY   = 2.5    # how quickly the wash fades
        BLOOM_WASH_COLOR   = (255, 245, 220)  # warm white (CRT phosphor tint)
        # AGC oversaturation — additive self-blend lifts everything
        OVERSAT_BOOST      = 120    # additive alpha at peak (high for dark scenes)
        OVERSAT_DECAY      = 3.0    # damping rate for color boost
        # Settle
        SETTLE_ALPHA       = 60      # residual brightness alpha at start of settle
        # ---------------------

        t_start  = time.perf_counter()
        w, h     = self._w, self._h
        renderer = self._renderer
        ov       = self._overlay
        LINE_H   = self._LINE_H
        line_cy  = h // 2
        _load_sound_played = False

        def _draw_line(lx: int, line_w: int, alpha: int, color: tuple) -> None:
            r, g, b = color
            ly = line_cy - LINE_H // 2
            ov.color_mod = (r, g, b)
            ov.alpha_mod = max(0, int(alpha * 0.22))
            renderer.copy(ov, dest=(lx, max(0, ly - 2),              line_w, 1))
            renderer.copy(ov, dest=(lx, min(h - 1, ly + LINE_H + 1), line_w, 1))
            ov.alpha_mod = max(0, int(alpha * 0.60))
            renderer.copy(ov, dest=(lx, max(0, ly - 1),         line_w, 1))
            renderer.copy(ov, dest=(lx, min(h - 1, ly + LINE_H), line_w, 1))
            ov.alpha_mod = min(255, alpha)
            renderer.copy(ov, dest=(lx, ly, line_w, LINE_H))

        scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
        scene_tex.alpha_mod  = 255
        scene_tex.color_mod  = (255, 255, 255)

        while True:
            if event_pump:
                for _ in event_pump():
                    pass
            t = (time.perf_counter() - t_start) / DURATION
            if t >= 1.0:
                break

            renderer.draw_color = (0, 0, 0, 255)
            renderer.clear()
            ov.blend_mode = tcod.sdl.render.BlendMode.BLEND

            if t < T_WARMUP_END:
                # ---- Phosphor cathode warming: green glow crawls up from almost nothing ----
                p    = t / T_WARMUP_END
                glow = p ** 1.8      # slow start, accelerates
                # Outer halo
                halo_w = max(4, int(WARMUP_HALO_W * glow))
                halo_h = max(2, int(WARMUP_HALO_H * glow))
                ov.color_mod = (20, 180, 25)
                ov.alpha_mod = max(1, int(glow * WARMUP_HALO_ALPHA))
                renderer.copy(ov, dest=((w - halo_w) // 2, line_cy - halo_h // 2, halo_w, halo_h))
                # Core dot
                dot_w = max(2, int(WARMUP_DOT_W * glow))
                dot_h = max(1, int(WARMUP_DOT_H * glow))
                ov.color_mod = (40, 255, 50)
                ov.alpha_mod = max(8, int(glow * WARMUP_DOT_ALPHA))
                renderer.copy(ov, dest=((w - dot_w) // 2, line_cy - dot_h // 2, dot_w, dot_h))

            elif t < T_BLOOM_END:
                # ---- Dot blooms bright: green → warm white ----
                p   = (t - T_WARMUP_END) / (T_BLOOM_END - T_WARMUP_END)
                # Colour morph: cold green → warm white
                rr  = int(40  + p * 215)
                gg  = 255
                bb  = int(50  + p * 165)
                # Dot grows as more beam current flows
                dot_w = max(BLOOM_DOT_W_START, int(BLOOM_DOT_W_START + p * BLOOM_DOT_W_GROW))
                dot_h = max(BLOOM_DOT_H_START, int(BLOOM_DOT_H_START + p * BLOOM_DOT_H_GROW))
                # Wide outer halo
                halo_w = dot_w + int(p * BLOOM_HALO_PAD_W)
                halo_h = dot_h + int(p * BLOOM_HALO_PAD_H)
                ov.color_mod = (max(1, rr), gg, max(1, bb))
                ov.alpha_mod = max(0, int(p * BLOOM_OUTER_ALPHA))
                renderer.copy(ov, dest=((w - halo_w) // 2, line_cy - halo_h // 2, halo_w, halo_h))
                # Mid bloom
                mid_w = dot_w + int(p * BLOOM_MID_PAD_W)
                mid_h = dot_h + int(p * BLOOM_MID_PAD_H)
                ov.alpha_mod = max(0, int(p * BLOOM_MID_ALPHA))
                renderer.copy(ov, dest=((w - mid_w) // 2, line_cy - mid_h // 2, mid_w, mid_h))
                # Core dot — full brightness
                ov.alpha_mod = min(255, int(200 + p * 55))
                renderer.copy(ov, dest=((w - dot_w) // 2, line_cy - dot_h // 2, dot_w, dot_h))

            elif t < T_STRETCH_END:
                # ---- Dot stretches to full-width line (ease-out) ----
                p      = (t - T_BLOOM_END) / (T_STRETCH_END - T_BLOOM_END)
                ep     = 1.0 - (1.0 - p) ** 2.5
                line_w = max(40, int(w * ep))
                lx     = (w - line_w) // 2
                rr = min(255, int(185 + ep * 70))
                bb = min(255, int(160 + ep * 65))
                _draw_line(lx, line_w, min(255, int(220 + ep * 35)), (rr, 255, bb))

            elif t < T_LINE_END:
                # ---- Full-width blazing line at peak brightness ----
                p     = (t - T_STRETCH_END) / (T_LINE_END - T_STRETCH_END)
                _draw_line(0, w, max(12, int((1.0 - p * 0.10) * 255)), (255, 255, 218))

            elif t < T_EXPAND_END:
                # ---- Vertical expansion with spring overshoot ----
                p      = (t - T_LINE_END) / (T_EXPAND_END - T_LINE_END)
                if not _load_sound_played:
                    # Play crt_load (vhs_bypass=True — allowed through the VHS gate)
                    sounds.play_crt_load_sound()
                    _load_sound_played = True
                ep     = 1.0 - (1.0 - p) ** 3.0    # ease-out cubic
                spring = 1.0 + math.exp(-p * SPRING_DECAY) * math.cos(p * math.pi * SPRING_FREQ) ** SPRING_OVERSHOOT
                # Horizontal wobble — decaying sinusoid mimicking VHS tape settling
                wobble_x = int(math.exp(-p * VHS_WOBBLE_DECAY) * VHS_WOBBLE_AMP
                               * math.sin(p * math.pi * VHS_WOBBLE_FREQ))

                cur_h  = min(h, max(LINE_H, int(h * ep * spring)))
                dy     = max(0, (h - cur_h) // 2)
                # Base image
                scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                scene_tex.alpha_mod = 255
                scene_tex.color_mod = (255, 255, 255)
                renderer.copy(scene_tex, dest=(wobble_x, dy, w, cur_h))
                # AGC oversaturation: additive pass of the scene itself (boosts bright areas)
                oversat_a = max(0, int(math.exp(-p * OVERSAT_DECAY) * OVERSAT_BOOST))
                if oversat_a > 0:
                    scene_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                    scene_tex.alpha_mod = oversat_a
                    renderer.copy(scene_tex, dest=(wobble_x, dy, w, cur_h))
                    scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    scene_tex.alpha_mod = 255
                # Warm white bloom wash — uniform brightness lift, visible on any scene
                bloom_a = int(max(0.0, 1.0 - p * BLOOM_WASH_DECAY) * BLOOM_WASH_ALPHA)
                if bloom_a > 0:
                    ov.alpha_mod = bloom_a
                    ov.color_mod = BLOOM_WASH_COLOR
                    renderer.copy(ov, dest=(wobble_x, dy, w, cur_h))

            else:
                # ---- Full image: AGC settles, residual brightness fades ----
                p = (t - T_EXPAND_END) / (1.0 - T_EXPAND_END)
                renderer.copy(scene_tex, dest=(0, 0, w, h))
                settle_a = int((1.0 - p) ** 2 * SETTLE_ALPHA)
                if settle_a > 0:
                    ov.alpha_mod = settle_a
                    ov.color_mod = (255, 255, 255)
                    renderer.copy(ov, dest=(0, 0, w, h))

            # CRT post-processing — same pipeline as the main loop
            if gpu_stack is not None:
                gpu_stack.apply_crt_overlays(
                    w, h, scanlines_tex=scanlines_tex, scanlines_h=scanlines_h,
                    vignette_tex=vignette_tex, glare_tex=glare_tex,
                    bloom_source=gpu_stack.post_crt_tex if t >= T_LINE_END else None,
                )
            elif glare_tex is not None:
                renderer.copy(glare_tex, dest=(0, 0, w, h))
            renderer.present()
            time.sleep(1.0 / 60)

        # End on the full scene — game continues naturally from here
        renderer.copy(scene_tex, dest=(0, 0, w, h))
        if gpu_stack is not None:
            gpu_stack.apply_crt_overlays(
                w, h, scanlines_tex=scanlines_tex, scanlines_h=scanlines_h,
                vignette_tex=vignette_tex, glare_tex=glare_tex,
                bloom_source=gpu_stack.post_crt_tex,
            )
        elif glare_tex is not None:
            renderer.copy(glare_tex, dest=(0, 0, w, h))
            renderer.copy(glare_tex, dest=(0, 0, w, h))
        renderer.present()


class VideoModeSwitchAnimation:
    """DOS-accurate INT 10h video mode switch animation.

    What actually happens when a DOS game calls INT 10h AH=00h to switch mode:
      play_off(scene_tex)  ~0.45 s
        Phase 1 — register tear:   CRTC regs written mid-frame → horizontal
                                   band corruption sweeping top→bottom
        Phase 2 — framebuf garbage: card resets, screen fills with noise
        Phase 3 — blank:            monitor loses sync, black

      play_on(scene_tex)   ~0.30 s
        Phase 1 — resync roll:  monitor hunts for new sync freq → bright
                                bars sweep upward on black
        Phase 2 — snap:         content appears instantly + brief AGC flash

    Replaces CRTSwitchAnimation for the floppy-load → game transition.
    """

    def __init__(self, renderer, window_w: int, window_h: int):
        self._renderer = renderer
        self._w        = window_w
        self._h        = window_h
        _px = np.array([[[255, 255, 255, 255]]], dtype=np.uint8)
        self._overlay = renderer.upload_texture(_px)
        self._overlay.blend_mode = tcod.sdl.render.BlendMode.BLEND

    # ------------------------------------------------------------------

    def play_off(self, scene_tex, event_pump=None, glare_tex=None) -> None:
        """Register tear → framebuffer garbage → blank.  ~0.45 s."""
        import time
        DURATION        = 0.45
        T_GARBAGE_START = 0.18   # full-noise phase starts here
        T_BLANK_START   = 0.34   # sync lost, black from here

        t_start  = time.perf_counter()
        w, h     = self._w, self._h
        renderer = self._renderer
        ov       = self._overlay
        _rng     = random.Random(7)   # fixed seed → deterministic look

        while True:
            if event_pump:
                for _ in event_pump():
                    pass
            t = (time.perf_counter() - t_start) / DURATION
            if t >= 1.0:
                break

            renderer.draw_color = (0, 0, 0, 255)
            renderer.clear()

            if t < T_GARBAGE_START:
                # ── Register tear ── scene visible, bands corrupt top→bottom ──
                p = t / T_GARBAGE_START
                scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                scene_tex.alpha_mod  = 255
                scene_tex.color_mod  = (255, 255, 255)
                renderer.copy(scene_tex, dest=(0, 0, w, h))
                band_h     = max(1, h // 30)
                n_bands    = int(p * p * (h // band_h))   # quadratic: sparse→dense
                tear_limit = int(p * h)                    # corrupted region grows downward
                for _ in range(n_bands):
                    by  = _rng.randint(0, max(1, tear_limit))
                    bw  = _rng.randint(w // 3, w)
                    bx  = _rng.randint(0, max(1, w - bw))
                    r   = _rng.randint(0, 100)
                    g   = _rng.randint(0, 100)
                    b   = _rng.randint(0, 100)
                    renderer.draw_color = (r, g, b, 255)
                    renderer.fill_rect((bx, by, bw, band_h))
                    # horizontal shift: row read from wrong scanline address
                    if _rng.random() < 0.4 * p:
                        shift  = _rng.randint(-32, 32)
                        src_y  = max(0, min(h - band_h, by + shift))
                        scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                        scene_tex.alpha_mod  = 200
                        renderer.copy(scene_tex,
                                      source=(0, src_y, w, band_h),
                                      dest=(0, by, w, band_h))

            elif t < T_BLANK_START:
                # ── Framebuffer garbage ── random dim scanline strips ──────────
                p     = (t - T_GARBAGE_START) / (T_BLANK_START - T_GARBAGE_START)
                row_h = max(1, h // 35)
                for row in range(0, h, row_h):
                    rh  = min(row_h, h - row)
                    r   = _rng.randint(0, 70)
                    g   = _rng.randint(0, 70)
                    b   = _rng.randint(0, 70)
                    renderer.draw_color = (r, g, b, 255)
                    renderer.fill_rect((0, row, w, rh))
                # fade to black as monitor loses sync
                ov.blend_mode = tcod.sdl.render.BlendMode.BLEND
                ov.color_mod  = (0, 0, 0)
                ov.alpha_mod  = int(p * 220)
                renderer.copy(ov, dest=(0, 0, w, h))

            # else: blank — already cleared to black

            if glare_tex is not None:
                renderer.copy(glare_tex, dest=(0, 0, w, h))
            renderer.present()
            time.sleep(1.0 / 60)

        renderer.draw_color = (0, 0, 0, 255)
        renderer.clear()
        if glare_tex is not None:
            renderer.copy(glare_tex, dest=(0, 0, w, h))
        renderer.present()

    # ------------------------------------------------------------------

    def play_on(self, scene_tex, event_pump=None, glare_tex=None, gpu_stack=None,
                scanlines_tex=None, scanlines_h=0, vignette_tex=None) -> None:
        """Resync roll then instant snap to game content.  ~0.65 s."""
        import time
        DURATION = 0.65
        T_SNAP   = 0.50   # content snaps in from here

        t_start  = time.perf_counter()
        w, h     = self._w, self._h
        renderer = self._renderer
        ov       = self._overlay

        scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
        scene_tex.alpha_mod  = 255
        scene_tex.color_mod  = (255, 255, 255)

        while True:
            if event_pump:
                for _ in event_pump():
                    pass
            t = (time.perf_counter() - t_start) / DURATION
            if t >= 1.0:
                break

            renderer.draw_color = (0, 0, 0, 255)
            renderer.clear()
            ov.blend_mode = tcod.sdl.render.BlendMode.BLEND

            if t < T_SNAP:
                # ── Resync roll ── two bright bars sweep upward on black ──────
                p     = t / T_SNAP
                bar_h = max(3, h // 16)
                for idx in range(2):
                    by         = int((1.0 - p) * h - idx * (h // 2)) % h
                    brightness = max(60, int((1.0 - p * 0.4) * 255))
                    ov.color_mod = (brightness, brightness, brightness)
                    ov.alpha_mod = brightness
                    renderer.copy(ov, dest=(0, by, w, bar_h))
                    # soft trailing edge
                    ov.alpha_mod = brightness // 4
                    renderer.copy(ov, dest=(0, min(h - 1, by + bar_h), w, bar_h // 2))
                if glare_tex is not None:
                    renderer.copy(glare_tex, dest=(0, 0, w, h))
                renderer.present()
                time.sleep(1.0 / 60)
                continue

            else:
                # ── Snap ── content appears instantly (no AGC flash for mode switch) ──
                renderer.copy(scene_tex, dest=(0, 0, w, h))
                if gpu_stack is not None:
                    gpu_stack.apply_crt_overlays(
                        w, h,
                        scanlines_tex=scanlines_tex, scanlines_h=scanlines_h,
                        vignette_tex=vignette_tex, glare_tex=glare_tex,
                        bloom_source=gpu_stack.post_crt_tex,
                    )
                elif glare_tex is not None:
                    renderer.copy(glare_tex, dest=(0, 0, w, h))
                renderer.present()
                time.sleep(1.0 / 60)
                continue

        # End on full scene
        renderer.copy(scene_tex, dest=(0, 0, w, h))
        if gpu_stack is not None:
            gpu_stack.apply_crt_overlays(
                w, h,
                scanlines_tex=scanlines_tex, scanlines_h=scanlines_h,
                vignette_tex=vignette_tex, glare_tex=glare_tex,
                bloom_source=gpu_stack.post_crt_tex,
            )
        elif glare_tex is not None:
            renderer.copy(glare_tex, dest=(0, 0, w, h))
        renderer.present()


# =============================================================================
# SECTION 4 — DEGAUSS ANIMATION CLASS
# =============================================================================
# Self-contained CRT degauss/teleport flash effect.  Can be triggered both at
# startup and during gameplay (e.g. player death, teleport spells).
#
# Usage:
#   anim = DegaussAnimation(renderer)
#   while not anim.done:
#       anim.tick(dt)
#       anim.draw(window_w, window_h, scene_tex=_post_crt_tex)
#
# Modes:
#   "degauss"  — damped oscillation with chromatic fringe + hue wash
#   "teleport" — per-band spatial scramble (more chaotic, shorter duration)

class DegaussAnimation:
    DURATION   = 5.0    # seconds
    _AMPLITUDE = 60.0   # max chromatic pixel shift at peak
    _DECAY     = 3.0    # damping rate (e-folding seconds⁻¹)
    _FREQ      = 6.0    # oscillation frequency (Hz)
    _FLASH_END = 0.12   # initial white flash window (seconds)
    _SCRAMBLE_BANDS = 16

    def __init__(self, renderer, mode: str = "degauss"):
        self._renderer = renderer
        self._t        = 0.0
        self.done      = False
        self._mode     = mode
        if mode == "teleport":
            self.DURATION   = 2.0
            self._AMPLITUDE = 80.0
            self._DECAY     = 3.5
            self._FREQ      = 9.0
        _px = np.array([[[255, 255, 255, 0]]], dtype=np.uint8)
        self._overlay_tex = renderer.upload_texture(_px)
        self._overlay_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ca_shift(self) -> float:
        """Signed pixel shift for the current elapsed time; damps toward 0."""
        if self._t < 0.005:
            return 0.0
        return (self._AMPLITUDE
                * np.exp(-self._DECAY * self._t)
                * np.sin(self._FREQ * 2.0 * np.pi * self._t))

    def _compress_scale(self) -> float:
        """Unused stub — kept so external references don't crash."""
        return 1.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tick(self, dt: float) -> None:
        """Advance animation by *dt* seconds."""
        self._t = min(self._t + dt, self.DURATION)
        if self._t >= self.DURATION:
            self.done = True

    def draw(self, window_w: int, window_h: int, scene_tex=None) -> None:
        """Draw degauss overlays on top of the already-blitted scene.

        scene_tex — the post-CRT scene texture.  R and B fringe passes are
        layered via ADD on top of the framebuffer.  The caller must have
        already blitted scene_tex normally (BLEND) before calling this.
        """
        if self._mode == "teleport":
            self._draw_teleport(window_w, window_h, scene_tex)
            return

        ca       = self._ca_shift()
        ca_i     = int(round(ca))
        envelope = abs(ca) / self._AMPLITUDE

        # Chromatic fringe: ADD-shifted R and B channels
        if scene_tex is not None and abs(ca_i) >= 1:
            fringe_alpha = int(min(envelope, 1.0) * 215)
            scene_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
            scene_tex.alpha_mod  = fringe_alpha
            scene_tex.color_mod  = (255, 0, 0)
            self._renderer.copy(scene_tex, dest=(ca_i, 0, window_w, window_h))
            scene_tex.color_mod  = (0, 0, 255)
            self._renderer.copy(scene_tex, dest=(-ca_i, 0, window_w, window_h))
            scene_tex.alpha_mod  = 255
            scene_tex.color_mod  = (255, 255, 255)
            scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND

        # White flash (phosphors momentarily overdriven)
        if self._t < self._FLASH_END:
            t_n   = self._t / self._FLASH_END
            alpha = int((min(t_n / 0.2, 1.0) - max((t_n - 0.2) / 0.8, 0.0)) * 230)
            alpha = max(0, min(255, alpha))
            self._overlay_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
            self._overlay_tex.alpha_mod  = alpha
            self._overlay_tex.color_mod  = (255, 255, 255)
            self._renderer.copy(self._overlay_tex, dest=(0, 0, window_w, window_h))

        # Hue-cycling ADD wash (fades with the CA envelope)
        if abs(ca_i) >= 1:
            hue_alpha = int(min(envelope, 1.0) * 50)
            if hue_alpha > 0:
                phase = self._t * self._FREQ * 2.0 * np.pi
                r = int(255 * max(0.0, np.sin(phase) ** 2))
                g = int(255 * max(0.0, np.sin(phase + 2.094) ** 2))
                b = int(255 * max(0.0, np.sin(phase + 4.189) ** 2))
                self._overlay_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                self._overlay_tex.alpha_mod  = hue_alpha
                self._overlay_tex.color_mod  = (max(1, r), max(1, g), max(1, b))
                self._renderer.copy(self._overlay_tex, dest=(0, 0, window_w, window_h))
                self._overlay_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND

    def draw_color_mod(self) -> tuple:
        """Legacy helper — colour effects are handled inside draw()."""
        return (255, 255, 255)

    # ------------------------------------------------------------------
    # Teleport mode
    # ------------------------------------------------------------------

    def _draw_teleport(self, window_w: int, window_h: int, scene_tex=None) -> None:
        """Per-band spatial scramble: R, G, B channels get independent shifts."""
        t        = self._t
        ca       = self._ca_shift()
        envelope = abs(ca) / self._AMPLITUDE if self._AMPLITUDE > 0 else 0.0

        if scene_tex is not None and envelope > 0.005:
            N            = 32
            fringe_alpha = int(min(envelope, 1.0) * 210)
            scene_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
            scene_tex.alpha_mod  = fringe_alpha

            w1 = self._FREQ * 2.0 * np.pi
            w2 = self._FREQ * 2.0 * np.pi * 1.37
            w3 = self._FREQ * 2.0 * np.pi * 0.71  # noqa: F841 (kept for symmetry)

            for i in range(N):
                y0 = int(window_h * i / N)
                y1 = int(window_h * (i + 1) / N)
                bh = max(1, y1 - y0)
                yn = (i + 0.5) / N

                edge  = 1.0 + 1.8 * (abs(yn - 0.5) * 2.0) ** 1.5
                r_s   = (np.sin(yn * np.pi * 2.7 + t * w1)       * 0.65 +
                         np.sin(yn * np.pi * 5.2 + t * w2 + 1.1) * 0.35)
                g_s   = (np.sin(yn * np.pi * 3.8 + t * w2 + 0.7) * 0.55 +
                         np.sin(yn * np.pi * 1.9 + t * w1 + 2.3) * 0.45)
                b_s   = -(r_s * 0.6 + g_s * 0.4)
                amp   = self._AMPLITUDE * envelope * edge
                r_shift = int(round(amp * r_s))
                g_shift = int(round(amp * g_s * 0.6))
                b_shift = int(round(amp * b_s))

                src = (0, y0, window_w, bh)
                if abs(r_shift) >= 1:
                    scene_tex.color_mod = (255, 0, 0)
                    self._renderer.copy(scene_tex, source=src, dest=(r_shift, y0, window_w, bh))
                if abs(g_shift) >= 1:
                    scene_tex.color_mod = (0, 255, 0)
                    self._renderer.copy(scene_tex, source=src, dest=(g_shift, y0, window_w, bh))
                if abs(b_shift) >= 1:
                    scene_tex.color_mod = (0, 0, 255)
                    self._renderer.copy(scene_tex, source=src, dest=(b_shift, y0, window_w, bh))

            scene_tex.alpha_mod  = 255
            scene_tex.color_mod  = (255, 255, 255)
            scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND

            # Hue-cycling wash
            hue_alpha = int(min(envelope, 1.0) * 65)
            if hue_alpha > 0:
                phase = t * self._FREQ * 2.0 * np.pi
                r = int(255 * max(0.0, np.sin(phase) ** 2))
                g = int(255 * max(0.0, np.sin(phase + 2.094) ** 2))
                b = int(255 * max(0.0, np.sin(phase + 4.189) ** 2))
                self._overlay_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                self._overlay_tex.alpha_mod  = hue_alpha
                self._overlay_tex.color_mod  = (max(1, r), max(1, g), max(1, b))
                self._renderer.copy(self._overlay_tex, dest=(0, 0, window_w, window_h))
                self._overlay_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND

        # White flash
        if t < self._FLASH_END:
            t_n   = t / self._FLASH_END
            alpha = int((min(t_n / 0.2, 1.0) - max((t_n - 0.2) / 0.8, 0.0)) * 210)
            alpha = max(0, min(255, alpha))
            if alpha > 0:
                self._overlay_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                self._overlay_tex.alpha_mod  = alpha
                self._overlay_tex.color_mod  = (255, 255, 255)
                self._renderer.copy(self._overlay_tex, dest=(0, 0, window_w, window_h))


# =============================================================================
# SECTION 4b — VHS GLITCH ANIMATION CLASS
# =============================================================================
# Persistent VHS-tape distortion effect used on the game over screen.
# Loops indefinitely until .done is set to True externally (or the caller
# stops calling tick/draw).
#
# Usage:
#   anim = VHSGlitchAnimation(renderer)
#   # each frame:
#   anim.tick(dt)
#   anim.draw(window_w, window_h, scene_tex=gpu.post_crt_tex)

class VHSGlitchAnimation:
    """Persistent VHS glitch overlay for the game over screen.

    Continuously renders:
      • A pulsing dark-red desaturation tint
      • Mild persistent chromatic aberration
      • Periodic burst mode: random horizontal band displacement with per-band
        R/G/B channel fringe (matching the teleport-mode per-band technique)
      • Occasional static noise lines during bursts
    """

    def __init__(self, renderer):
        self._renderer = renderer
        self._t        = 0.0
        self.done      = False

        # 1×1 white pixel stretched as overlay / noise source
        _px = np.array([[[255, 255, 255, 128]]], dtype=np.uint8)
        self._overlay_tex = renderer.upload_texture(_px)
        self._overlay_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND

        # Burst scheduling
        self._burst_active = False
        self._burst_t      = 0.0
        self._burst_dur    = 0.0
        self._next_burst   = random.uniform(0.05, 0.5)  # seconds until first burst

        # Current band list: (y_frac, band_h, x_shift, r_shift, b_shift, base_alpha)
        self._bands: list = []

    # ------------------------------------------------------------------
    def tick(self, dt: float) -> None:
        """Advance animation by *dt* seconds.  Call once per frame."""
        self._t += dt

        if self._burst_active:
            self._burst_t += dt
            if self._burst_t >= self._burst_dur:
                self._burst_active = False
                self._bands        = []
                self._next_burst   = random.uniform(0.08, 0.4)
            elif random.random() < 0.35:
                self._regenerate_bands()
        else:
            self._next_burst -= dt
            if self._next_burst <= 0.0:
                self._burst_active = True
                self._burst_t      = 0.0
                self._burst_dur    = random.uniform(0.4, 1.2)
                self._regenerate_bands()

    # ------------------------------------------------------------------
    def _regenerate_bands(self) -> None:
        """Build a fresh set of random displacement bands."""
        self._bands = []
        count = random.randint(10, 28)
        for _ in range(count):
            y_frac   = random.random()
            band_h   = random.randint(4, 40)
            x_shift  = random.randint(-60, 60)
            r_shift  = x_shift + random.randint(-20, 20)
            b_shift  = -x_shift + random.randint(-14, 14)
            alpha    = random.randint(160, 255)
            self._bands.append((y_frac, band_h, x_shift, r_shift, b_shift, alpha))

    # ------------------------------------------------------------------
    def draw(self, window_w: int, window_h: int, scene_tex=None, gpu=None) -> None:
        """Composite VHS glitch on top of the already-blitted framebuffer.

        scene_tex — post-CRT scene texture used for chromatic passes.
        gpu       — GPUStack instance; when provided, all pixel copies are
                    clipped to the barrel-curve boundary at each row so that
                    glitch artefacts never bleed outside the curved screen area.
        """
        renderer = self._renderer
        ov       = self._overlay_tex

        # --- Barrel-curve horizontal clip helper ----------------------------
        # Returns (barrel_left, barrel_right) in physical pixels for a given
        # mid-Y screen position.  Falls back to full width when CRT is off.
        def _barrel_clip(y_mid: float):
            if gpu is None or not getattr(gpu, 'crt_curvature_on', False):
                return 0, window_w
            st_h = getattr(gpu, 'crt_strength', 0.0)
            if st_h <= 0.0:
                return 0, window_w
            ny = (y_mid / window_h - 0.5) * 2.0 if window_h > 0 else 0.0
            horz_scale = max(0.0, 1.0 - st_h * ny * ny)
            bl = int(round(window_w * (1.0 - horz_scale) * 0.5))
            br = window_w - bl
            return bl, br

        # --- 1:1 clipped horizontal copy ------------------------------------
        # Copies scene_tex row (src_y, src_h) shifted to dest_x, clamped to
        # [barrel_left, barrel_right].  Adjusts source rect to match.
        def _band_copy(tex, src_y: int, src_h: int, dest_x: int, bl: int, br: int):
            cl = max(bl, dest_x)
            cr = min(br, dest_x + window_w)
            if cl >= cr:
                return
            src_off = cl - dest_x          # how many px into source we start
            renderer.copy(tex,
                          source=(src_off, src_y, cr - cl, src_h),
                          dest=(cl, src_y, cr - cl, src_h))

        # ---- Persistent dark-red desaturation tint (pulsing) ----
        tint_a = int(55 + 30 * math.sin(self._t * 2.4))
        tint_a = max(0, min(255, tint_a))
        ov.blend_mode = tcod.sdl.render.BlendMode.BLEND
        ov.alpha_mod  = tint_a
        ov.color_mod  = (80, 0, 0)
        renderer.copy(ov, dest=(0, 0, window_w, window_h))

        # ---- Persistent chromatic aberration ----
        if scene_tex is not None:
            ca_i = int(4 + 5 * abs(math.sin(self._t * 3.1)))
            if ca_i >= 1:
                scene_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                scene_tex.alpha_mod  = 70
                scene_tex.color_mod  = (255, 0, 0)
                renderer.copy(scene_tex, dest=(ca_i, 0, window_w, window_h))
                scene_tex.color_mod  = (0, 0, 255)
                renderer.copy(scene_tex, dest=(-ca_i, 0, window_w, window_h))
                scene_tex.alpha_mod  = 255
                scene_tex.color_mod  = (255, 255, 255)
                scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND

        # ---- Burst: per-band displacement + RGB fringe + static noise ----
        if not self._burst_active or not self._bands or scene_tex is None:
            return

        burst_p  = min(1.0, self._burst_t / max(self._burst_dur, 0.001))
        envelope = min(1.0, burst_p * 3.0) * min(1.0, (1.0 - burst_p) * 4.0)
        if envelope <= 0.0:
            return

        for y_frac, band_h, x_shift, r_shift, b_shift, base_alpha in self._bands:
            y0  = int(y_frac * window_h)
            bh  = max(1, min(band_h, window_h - y0))
            alpha = int(base_alpha * envelope)
            if alpha <= 0:
                continue

            bl, br = _barrel_clip(y0 + bh * 0.5)

            # Displaced base copy (brighter to simulate tape bleed)
            scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
            scene_tex.alpha_mod  = min(255, int(alpha * 1.4))
            scene_tex.color_mod  = (255, 255, 255)
            _band_copy(scene_tex, y0, bh, x_shift, bl, br)

            # R channel fringe
            if abs(r_shift) >= 1:
                scene_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                scene_tex.alpha_mod  = int(alpha * 0.75)
                scene_tex.color_mod  = (255, 0, 0)
                _band_copy(scene_tex, y0, bh, r_shift, bl, br)

            # B channel fringe
            if abs(b_shift) >= 1:
                scene_tex.color_mod = (0, 0, 255)
                scene_tex.alpha_mod = int(alpha * 0.60)
                _band_copy(scene_tex, y0, bh, b_shift, bl, br)

        # Reset scene_tex state
        scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
        scene_tex.alpha_mod  = 255
        scene_tex.color_mod  = (255, 255, 255)

        # Static noise lines during the burst (multiple passes)
        for _ in range(random.randint(1, 4)):
            if random.random() < 0.7:
                noise_y = random.randint(0, max(0, window_h - 5))
                noise_h = random.randint(1, 6)
                noise_a = int(random.uniform(40, 120) * envelope)
                if noise_a > 0:
                    bl, br = _barrel_clip(noise_y + noise_h * 0.5)
                    ov.blend_mode = tcod.sdl.render.BlendMode.ADD
                    ov.alpha_mod  = noise_a
                    ov.color_mod  = (200, 200, 220)
                    renderer.copy(ov, dest=(bl, noise_y, br - bl, noise_h))
                    ov.blend_mode = tcod.sdl.render.BlendMode.BLEND


# =============================================================================
# SECTION 5 — GPU STACK CLASS
# =============================================================================
# Owns all per-session GPU render targets, parameters, and render passes.
# Instantiated once inside main() and receives the renderer + per-frame
# window/tile measurements via update_frame_dims() each frame.

class GPUStack:
    """Container for all GPU render state and post-processing passes.

    Call update_frame_dims() once per frame before any render methods.

    Sub-sections
    ------------
      5a. Bloom render targets
      5b. Game-layer animation targets & registry
      5c. CRT barrel curvature & chromatic aberration
      5d. Particle render passes  (ember / smoke / drip)
      5e. Animation pass runner   (bloom + no-bloom pipelines)
      5f. Full-scene Kawase bloom
      5g. Lightmap
    """

    def __init__(self, renderer, tileset, game_view_width: int, game_view_height: int,
                 screen_width: int, screen_height: int, get_data_path_fn):
        self.renderer         = renderer
        self.tileset          = tileset
        self.game_view_width  = game_view_width
        self.game_view_height = game_view_height
        self.screen_width     = screen_width
        self.screen_height    = screen_height
        self._get_data_path   = get_data_path_fn

        # Per-frame dimensions — refreshed by update_frame_dims()
        self.window_w    = 1
        self.window_h    = 1
        self.base_tile_w = 1.0
        self.base_tile_h = 1.0

        # CRT toggle flags (loaded from settings)
        self.crt_scanlines_on = True
        self.crt_vignette_on  = True
        self.crt_bloom_on     = True
        self.crt_ca_on        = True
        self.crt_curvature_on = True
        self.crt_force_fast_path = False

        # CRT geometry parameters
        self.crt_bands      = 116
        self.crt_strength   = 0.05
        self.crt_strength_v = 0.05
        self.ca_shift       = 1.5    # pixel shift for R/B channels (0 = disabled)

        # ---------------------------------------------------------------
        # 5a — Bloom render targets
        # ---------------------------------------------------------------
        self._bloom_intensity   = 255
        self._bloom_passes      = 2
        self._bloom_downsample  = 2
        self._bloom_threshold   = 255
        self._bloom_spread      = 1.0

        self._scene_tex     = None
        self._barrel_tex    = None
        self._post_crt_tex  = None
        self._bloom_a       = None
        self._bloom_b       = None
        self._bloom_scene_w = 0
        self._bloom_scene_h = 0

        # ---------------------------------------------------------------
        # 5b — Game-layer animation targets & registry
        # ---------------------------------------------------------------
        # _gpu_anim_registry        — bloom pipeline: Kawase blur + composite
        # _gpu_anim_nobloom_registry — no-bloom pipeline: BLEND composite only
        #
        # To add a new pass:
        #   1. Define  fn(active_engine) -> bool  (draw into _gal_src, return True if drew)
        #   2. Append: self.gpu_anim_registry.append(fn)         # bloom
        #              self.gpu_anim_nobloom_registry.append(fn) # no-bloom
        self.gpu_anim_registry        = []
        self.gpu_anim_nobloom_registry = []

        self._gal_src    = None
        self._gal_blur_a = None
        self._gal_blur_b = None
        self._gal_w      = 0
        self._gal_h      = 0
        self._gal_ds     = 2

        # 1×1 white pixel overlay (used for bloom wash / tint overlays)
        _px = np.array([[[255, 255, 255, 255]]], dtype=np.uint8)
        self._overlay = renderer.upload_texture(_px)
        self._overlay.blend_mode = tcod.sdl.render.BlendMode.BLEND

        # ---------------------------------------------------------------
        # CRT glitch state (jitter + vertical roll)
        # ---------------------------------------------------------------
        self._jitter_x       = 0
        self._jitter_y       = 0
        self._jitter_band_h  = 3
        self._jitter_frames  = 0

        self._vroll_offset   = 0.0
        self._vroll_speed    = 0.0
        self._vroll_ttl      = 0.0
        self._vroll_elapsed  = 0.0
        self._vroll_next     = float(np.random.uniform(5.0, 10.0))

        # ---------------------------------------------------------------
        # VHS wobble state (screen shake + oversaturation on load)
        # ---------------------------------------------------------------
        self._wobble_active       = False
        self._wobble_time         = 0.0
        self._wobble_dur          = 1.2
        self._wobble_amp          = 10
        self._wobble_freq         = 13.0
        self._wobble_decay        = 4.5
        self._spring_overshoot    = -40.0
        self._spring_decay        = 7.0
        self._spring_freq         = 3.2
        self._wobble_oversat_boost = 120
        self._wobble_oversat_decay = 3.0
        self._wobble_bloom_alpha   = 180
        self._wobble_bloom_decay   = 2.5
        self._wobble_bloom_color   = (255, 245, 220)

        # ---------------------------------------------------------------
        # Channel overlay (boot splash / dungeon-load splash)
        # ---------------------------------------------------------------
        self._chan_overlay_frames  = 30
        self._chan_overlay_counter = 0
        self._chan_overlay_active  = None   # "menu", "game", or None
        self._chan_menu_tex        = None
        self._chan_menu_w          = 0
        self._chan_menu_h          = 0
        self._chan_game_tex        = None
        self._chan_game_w          = 0
        self._chan_game_h          = 0

        self._smoke_tex    = None
        self._smoke_frames = None
        self._smoke_tex_frames = None
        self._dodge_tile_cache: dict = {}  # codepoint -> uploaded texture

        # Ember/smoke bloom tuning
        self._ember_bloom_passes    = 3
        self._ember_bloom_spread    = 1.4
        self._ember_bloom_intensity = 255

        # ---------------------------------------------------------------
        # 5g — Lightmap
        # ---------------------------------------------------------------
        self._lightmap_tex      = None
        self._lightmap_tex_size = (0, 0)
        self.lightmap_update_interval = 1
        self._lightmap_frame_counter = 0
        # Optional bridge for a future unified ModernGL frame compositor.
        # When disabled or no composer is registered, the legacy SDL path is used.
        self.enable_modern_gl_lightmap_unified = False
        self.modern_gl_lightmap_composer = None
        self._unified_gl_status_logged = False
        self._unified_runtime_disabled = False
        self._cached_lighting_engine = None

        # Register the built-in particle passes
        self.gpu_anim_registry.append(self._gpu_ember_render)   
        self.gpu_anim_registry.append(self._jagged_line_spell_render)      # bloom
        self.gpu_anim_registry.append(self._projectile_trail_render)        # bloom
        self.gpu_anim_registry.append(self._burn_render)      # bloom
        self.gpu_anim_registry.append(self._dodge_render)      # under entities, no bloom
        self.gpu_anim_registry.append(self._gpu_crtbleed_render)      # bloom
        self.gpu_anim_registry.append(self._gpu_smoke_render)         # bloom
        self.gpu_anim_registry.append(self._light_shaft_render)       # bloom
        self.gpu_anim_registry.append(self._dust_render)              # ambient
        self.gpu_anim_registry.append(self._slash_render)            # bloom
        self.gpu_anim_registry.append(self._gpu_drip_render)  # bloom ? (exact color)
        self.gpu_anim_registry.append(self._heal_render)  # bloom ? (exact color)
        self.gpu_anim_registry.append(self._damage_number_render)     # bloom
        self.gpu_anim_registry.append(self._space_distort_spell_render)    # bloom
        self.gpu_anim_registry.append(self._fireball_explosion_render)     # bloom
        self.gpu_anim_registry.append(self._poison_spray_render)           # bloom
        self.gpu_anim_registry.append(self._sleep_render)                 # bloom
        self.gpu_anim_registry.append(self._illuminated_render)            # bloom
        self.gpu_anim_registry.append(self._reveal_render)                 # bloom

    # ------------------------------------------------------------------
    # Frame dimension update
    # ------------------------------------------------------------------

    def update_frame_dims(self, window_w: int, window_h: int,
                          base_tile_w: float, base_tile_h: float,
                          game_zoom: float = 4.0) -> None:
        """Call once per frame before any render methods."""
        self.window_w    = window_w
        self.window_h    = window_h
        self.base_tile_w = base_tile_w
        self.base_tile_h = base_tile_h
        self.game_zoom   = game_zoom

    def _active_anim_bucket(self, active_engine, anim_type):
        getter = getattr(active_engine, "get_active_animation_bucket", None)
        if callable(getter):
            return getter(anim_type)
        return [
            anim for anim in active_engine.animation_queue
            if isinstance(anim, anim_type) and getattr(anim, "frames", 0) > 0
        ]

    # ------------------------------------------------------------------
    # 5a — Bloom render target management
    # ------------------------------------------------------------------

    def ensure_bloom_targets(self, w: int, h: int) -> None:
        """Create or resize GPU render targets for the full-scene bloom pass."""
        if w == self._bloom_scene_w and h == self._bloom_scene_h:
            return
        self._bloom_scene_w, self._bloom_scene_h = w, h
        ds = self._bloom_downsample
        bw, bh = max(1, w // ds), max(1, h // ds)
        _TA = tcod.sdl.render.TextureAccess.TARGET
        self._scene_tex    = self.renderer.new_texture(w, h, access=_TA)
        self._barrel_tex   = self.renderer.new_texture(w, h, access=_TA)
        self._post_crt_tex = self.renderer.new_texture(w, h, access=_TA)
        self._bloom_a      = self.renderer.new_texture(bw, bh, access=_TA)
        self._bloom_b      = self.renderer.new_texture(bw, bh, access=_TA)

    @property
    def scene_tex(self):
        return self._scene_tex

    @property
    def post_crt_tex(self):
        return self._post_crt_tex

    @property
    def barrel_tex(self):
        return self._barrel_tex

    # ------------------------------------------------------------------
    # 5b — Game-layer animation target management
    # ------------------------------------------------------------------

    def ensure_gpu_anim_layer(self, gw: int, gh: int) -> None:
        """Create or resize game-area GPU render targets for animation passes.

        Targets are sized to (gw × gh) — the game viewport in pixels — so they
        physically cannot contain UI region pixels.
        """
        gw, gh = max(1, int(gw)), max(1, int(gh))
        if gw == self._gal_w and gh == self._gal_h:
            return
        self._gal_w, self._gal_h = gw, gh
        bw = max(1, gw // self._gal_ds)
        bh = max(1, gh // self._gal_ds)
        _TA = tcod.sdl.render.TextureAccess.TARGET
        self._gal_src    = self.renderer.new_texture(gw, gh, access=_TA)
        self._gal_blur_a = self.renderer.new_texture(bw, bh, access=_TA)
        self._gal_blur_b = self.renderer.new_texture(bw, bh, access=_TA)

    # ------------------------------------------------------------------
    # 5c — CRT barrel curvature & chromatic aberration
    # ------------------------------------------------------------------

    def copy_curved(self, tex, dest, source=None, src_size=None) -> None:
        """Copy a texture with CRT barrel curvature (horizontal + vertical)."""
        renderer = self.renderer
        if not self.crt_curvature_on or self.crt_force_fast_path:
            if source is not None:
                renderer.copy(tex, source=source, dest=dest)
            else:
                renderer.copy(tex, dest=dest)
            return

        dst_x, dst_y, dst_w, dst_h = (float(v) for v in dest)
        have_src = source is not None or src_size is not None
        if source is not None:
            sx, sy, sw, sh = (float(v) for v in source)
        elif src_size is not None:
            sx, sy, sw, sh = 0.0, 0.0, float(src_size[0]), float(src_size[1])
        else:
            sx, sy, sw, sh = 0.0, 0.0, 0.0, 0.0

        wh      = float(self.window_h)
        ww      = float(self.window_w)
        inv_wh  = 1.0 / wh if wh > 0 else 1.0
        inv_ww  = 1.0 / ww if ww > 0 else 1.0
        st_h    = self.crt_strength
        st_v    = self.crt_strength_v
        bands   = self.crt_bands

        def _distort_y(f, horz_scale_at_f):
            base_y = dst_y + f * dst_h
            if st_v > 0:
                bw_est    = dst_w * horz_scale_at_f
                cx_est    = dst_x + (dst_w - bw_est) * 0.5 + bw_est * 0.5
                nx        = (cx_est * inv_ww - 0.5) * 2.0
                vert_scale = 1.0 - st_v * nx * nx
                center_y  = dst_y + 0.5 * dst_h
                base_y    = center_y + (base_y - center_y) * vert_scale
            return base_y

        def _horz_scale_at_f(f):
            y  = dst_y + f * dst_h
            ny = (y * inv_wh - 0.5) * 2.0
            return 1.0 - st_h * ny * ny

        band_by = [
            round(_distort_y(i / bands, _horz_scale_at_f(i / bands)))
            for i in range(bands + 1)
        ]

        for i in range(bands):
            f0    = i / bands
            f1    = (i + 1) / bands
            f_mid = (f0 + f1) * 0.5
            mid_y = dst_y + f_mid * dst_h
            ny    = (mid_y * inv_wh - 0.5) * 2.0
            horz_scale = 1.0 - st_h * ny * ny
            bw    = round(dst_w * horz_scale)
            bx    = round(dst_x + (dst_w - bw) * 0.5)
            by0   = band_by[i]
            by1   = band_by[i + 1]
            bh    = by1 - by0
            if bh <= 0:
                continue
            if have_src and sh > 1:
                bsy0 = int(sy + f0 * sh)
                bsy1 = int(sy + f1 * sh)
                bsh  = bsy1 - bsy0
                if bsh <= 0:
                    continue
                renderer.copy(tex, source=(int(sx), bsy0, int(sw), bsh),
                              dest=(bx, by0, bw, bh))
            elif have_src:
                renderer.copy(tex,
                              source=(int(sx), int(sy), int(sw), max(1, int(sh))),
                              dest=(bx, by0, bw, bh))
            else:
                renderer.copy(tex, dest=(bx, by0, bw, bh))

    def undistort_mouse(self, px: float, py: float) -> tuple:
        """Map a screen pixel back to its logical (pre-distortion) position."""
        if not self.crt_curvature_on:
            return float(px), float(py)
        wh    = float(self.window_h)
        ww    = float(self.window_w)
        st_h  = self.crt_strength
        st_v  = self.crt_strength_v
        ny    = (py / wh - 0.5) * 2.0 if wh > 0 else 0.0
        horz_scale = 1.0 - st_h * ny * ny
        if horz_scale > 0:
            center_offset = ww * (1.0 - horz_scale) * 0.5
            logical_x     = (px - center_offset) / horz_scale
        else:
            logical_x = px
        if st_v > 0:
            nx = (logical_x / ww - 0.5) * 2.0 if ww > 0 else 0.0
            vert_scale = 1.0 - st_v * nx * nx
            if vert_scale > 0:
                center_offset_y = wh * (1.0 - vert_scale) * 0.5
                logical_y = (py - center_offset_y) / vert_scale
            else:
                logical_y = py
        else:
            logical_y = py
        return logical_x, logical_y

    def copy_curved_crt(self, tex, dest, source=None, src_size=None) -> None:
        """Copy with barrel distortion and per-channel chromatic aberration."""
        ca = self.ca_shift if (self.crt_ca_on and not self.crt_force_fast_path) else 0
        orig_color = tex.color_mod
        orig_blend = tex.blend_mode
        orig_alpha = tex.alpha_mod
        if ca > 0:
            dx, dy, dw, dh = dest
            tex.blend_mode = tcod.sdl.render.BlendMode.ADD
            tex.color_mod  = (255, 0, 0)
            self.copy_curved(tex, (dx - ca, dy, dw, dh), source=source, src_size=src_size)
            tex.color_mod  = (0, 255, 0)
            self.copy_curved(tex, dest, source=source, src_size=src_size)
            tex.color_mod  = (0, 0, 255)
            self.copy_curved(tex, (dx + ca, dy, dw, dh), source=source, src_size=src_size)
        else:
            tex.color_mod  = orig_color
            tex.blend_mode = orig_blend
            self.copy_curved(tex, dest, source=source, src_size=src_size)
        tex.color_mod  = orig_color
        tex.blend_mode = orig_blend
        tex.alpha_mod  = orig_alpha

    # ------------------------------------------------------------------
    # 5d — Particle render passes
    # ------------------------------------------------------------------
    # Each method draws into self._gal_src (assumed pre-cleared) and
    # returns True if at least one pixel was drawn.


    def _gpu_crtbleed_render(self, active_engine) -> bool:
        """Draw screen-edge red color bleed for each CRTBleedAnim (damage flash)."""
        bleeds = [a for a in active_engine.animation_queue
                  if isinstance(a, CRTBleedAnim) and a.frames > 0]

        if not bleeds:
            return False

        # Deduplicated by the spawner — there should only be one, but guard anyway
        bleed     = max(bleeds, key=lambda b: b.frames)
        renderer  = self.renderer
        gw        = float(self._gal_w)
        gh        = float(self._gal_h)

        # Linear fade: bright flash at birth, fully gone at end
        age       = 1.0 - (bleed.frames / float(bleed.total_frames))
        intensity = int(210 * (1.0 - age))
        if intensity < 6:
            return False

        # CRT bleed is a screen-space indicator, not world-space. Since the game
        # animation layer is composited with camera world offsets, compensate here
        # so the effect remains fixed on screen.
        off_x = 0
        off_y = 0
        try:
            tile_px_w = float(self.base_tile_w) * float(self.game_zoom)
            tile_px_h = float(self.base_tile_h) * float(self.game_zoom)
            cam_off_x, cam_off_y = active_engine.get_camera_render_offset_px(tile_px_w, tile_px_h)
            off_x = -int(cam_off_x)
            off_y = -int(cam_off_y)
        except Exception:
            off_x = 0
            off_y = 0

        # Smooth gradient: many thin strips from each edge, cubic falloff
        STEPS     = 20
        max_depth = gh * 0.07          # 7% of viewport height from each edge
        step_size = max(1.0, max_depth / STEPS)

        drew = False
        with renderer.set_render_target(self._gal_src):
            for i in range(STEPS):
                t           = i / STEPS                           # 0 at edge, ~1 at max_depth
                alpha       = int(intensity * (1.0 - t) ** 3)    # cubic: very fast center falloff
                if alpha < 3:
                    break                                         # remaining strips will also be < 3
                offset = i * step_size
                renderer.draw_color = (intensity, int(intensity * 0.05), 0, alpha)
                renderer.fill_rect((0.0 + off_x,               float(offset) + off_y,              gw,        step_size))  # top
                renderer.fill_rect((0.0 + off_x,               gh - offset - step_size + off_y,    gw,        step_size))  # bottom
                renderer.fill_rect((float(offset) + off_x,     0.0 + off_y,                        step_size, gh))         # left
                renderer.fill_rect((gw - offset - step_size + off_x, 0.0 + off_y,                 step_size, gh))         # right
            drew = True
        return drew




    def _gpu_ember_render(self, active_engine) -> bool:
        """Draw EmberParticle emission rects into _gal_src (bloom pass)."""
        embers = self._active_anim_bucket(active_engine, EmberParticle)
        if not embers:
            return False
        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        sz        = 1
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map  = active_engine.game_map
        renderer  = self.renderer
        drew      = False
        with renderer.set_render_target(self._gal_src):
            for ember in embers:
                world_xi = int(round(ember.fx))
                world_yi = int(round(ember.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue
                scr_x = ember.fx - origin_x
                scr_y = ember.fy - origin_y
                if not (0.0 <= scr_x < self.game_view_width and
                        0.0 <= scr_y < self.game_view_height):
                    continue
                px = int(scr_x * tile_px_w + tile_px_w * 0.5)
                py = int(scr_y * tile_px_h + tile_px_h * 0.5)
                if not (sz <= px < self._gal_w - sz and sz <= py < self._gal_h - sz):
                    continue
                age = 1.0 - (ember.frames / float(ember.total_frames))
                if age < 0.25:
                    t = age / 0.25
                    er, eg, eb = 255, int(255 - t * 70), int(230 - t * 200)
                elif age < 0.60:
                    t = (age - 0.25) / 0.35
                    er, eg, eb = 255, int(185 - t * 130), 0
                else:
                    t = (age - 0.60) / 0.40
                    er, eg, eb = int(255 - t * 130), max(0, int(55 - t * 45)), 0
                renderer.draw_color = (er, eg, eb, 255)
                renderer.fill_rect((float(px - sz), float(py - sz),
                                    float(sz * 2), float(sz * 2)))
                drew = True
        return drew

    def _reveal_render(self, active_engine) -> bool:
        """Draw sparkles along a path or at a point (bloom pass)."""
        particles = self._active_anim_bucket(active_engine, RevealParticle)
        if not particles:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map = active_engine.game_map
        renderer = self.renderer
        drew = False
        spread = tile_px_w * 0.35

        with renderer.set_render_target(self._gal_src):
            for p in particles:
                age     = 1.0 - (p.frames / float(p.total_frames))
                elapsed = p.total_frames - p.frames

                if age < 0.03:
                    fade = age / 0.03
                elif age > 0.95:
                    fade = (1.0 - age) / 0.05
                else:
                    fade = 1.0

                if fade <= 0.0:
                    continue

                if hasattr(p, 'path') and p.path:
                    path_len = len(p.path)
                    for i, (wx, wy) in enumerate(p.path):
                        if not game_map.in_bounds(wx, wy):
                            continue
                        if not game_map.visible[wx, wy]:
                            continue
                        scr_x = wx - origin_x
                        scr_y = wy - origin_y
                        if not (0.0 <= scr_x < self.game_view_width and
                                0.0 <= scr_y < self.game_view_height):
                            continue

                        cx = int(scr_x * tile_px_w + tile_px_w * 0.5)
                        cy = int(scr_y * tile_px_h + tile_px_h * 0.5)

                        # Stable positions per tile — seed never changes
                        pos_rng = random.Random(hash((wx, wy, id(p))))
                        offsets = [(pos_rng.uniform(-spread, spread),
                                    pos_rng.uniform(-spread, spread),
                                    pos_rng.randint(1, 2))   # sz capped at 2
                                for _ in range(4)]        # 4 sparkles, not 5

                        for j, (ox, oy, sz) in enumerate(offsets):
                            # Each sparkle twinkles on its own sine, no position jitter
                            phase     = elapsed * 0.13 + i * 1.7 + j * 2.4
                            twinkle   = 0.25 + 0.75 * (math.sin(phase) * 0.5 + 0.5)
                            alpha     = int(180 * fade * twinkle)
                            alpha     = max(0, min(255, alpha))
                            if alpha < 12:
                                continue
                            renderer.draw_color = (255, 80, 255, alpha)
                            renderer.fill_rect((float(cx + ox - sz), float(cy + oy - sz),
                                                float(sz * 2), float(sz * 2)))
                        drew = True

                else:
                    world_xi = int(round(p.fx))
                    world_yi = int(round(p.fy))
                    if not game_map.in_bounds(world_xi, world_yi):
                        continue
                    if not game_map.visible[world_xi, world_yi]:
                        continue
                    scr_x = p.fx - origin_x
                    scr_y = p.fy - origin_y
                    if not (0.0 <= scr_x < self.game_view_width and
                            0.0 <= scr_y < self.game_view_height):
                        continue

                    cx = int(scr_x * tile_px_w + tile_px_w * 0.5)
                    cy = int(scr_y * tile_px_h + tile_px_h * 0.5)

                    pos_rng = random.Random(hash((world_xi, world_yi, id(p))))
                    offsets = [(pos_rng.uniform(-spread, spread),
                                pos_rng.uniform(-spread, spread),
                                pos_rng.randint(1, 2))
                            for _ in range(4)]

                    for j, (ox, oy, sz) in enumerate(offsets):
                        phase   = elapsed * 0.13 + j * 2.4
                        twinkle = 0.25 + 0.75 * (math.sin(phase) * 0.5 + 0.5)
                        alpha   = int(160 * fade * twinkle)
                        alpha   = max(0, min(255, alpha))
                        if alpha < 12:
                            continue
                        renderer.draw_color = (255, 80, 255, alpha)
                        renderer.fill_rect((float(cx + ox - sz), float(cy + oy - sz),
                                            float(sz * 2), float(sz * 2)))
                    drew = True

        return drew
    
    def _space_distort_spell_render(self, active_engine) -> bool:
        """Expanding warp-rings for SpaceDistortSpellParticle (bloom pass).

        Each particle draws:
          1. A brief central pinpoint flash (first 25 % of life).
          2. A single tight ring that expands via ease-out quadratic over roughly
             1 tile radius, with per-dot radial noise so the edge looks 'torn'.
          3. 6 radial rift lines from center outward — short dotted streaks with
             perpendicular wobble that grows with distance (crack-in-space look).
          4. Chromatic fringe dots inside/outside the ring.
        """
        particles = self._active_anim_bucket(active_engine, SpaceDistortSpellParticle)
        if not particles:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map = active_engine.game_map
        renderer = self.renderer
        drew     = False

        TWO_PI  = 2.0 * math.pi
        N_DOTS  = 28                      # sample points per ring sweep
        N_RIFTS = 6                       # radial crack lines
        aspect  = tile_px_h / tile_px_w  # oval correction

        # max ring radius: just over one tile wide
        max_r     = tile_px_w * 1.1
        # radial noise amplitude: how far each dot can be pushed off the ring
        r_noise   = tile_px_w * 0.28
        dot_sz    = max(1, int(tile_px_w * 0.09))
        fringe_sz = max(1, dot_sz - 1)
        fringe_r  = tile_px_w * 0.18     # CA offset distance

        with renderer.set_render_target(self._gal_src):
            for p in particles:
                world_xi = int(round(p.fx))
                world_yi = int(round(p.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue

                scr_x = p.fx - origin_x
                scr_y = p.fy - origin_y
                if not (0.0 <= scr_x < self.game_view_width and
                        0.0 <= scr_y < self.game_view_height):
                    continue

                cx  = scr_x * tile_px_w + tile_px_w * 0.5
                cy  = scr_y * tile_px_h + tile_px_h * 0.5
                age = 1.0 - (p.frames / float(p.total_frames))

                # ── 1. Central flash (first 25 % of life) ────────────────────
                if age < 0.25:
                    t_f     = age / 0.25
                    f_alpha = int(200 * math.sin(t_f * math.pi))
                    sz      = max(1, int(tile_px_w * 0.22))
                    px_c    = int(cx)
                    py_c    = int(cy)
                    if f_alpha > 8 and 1 <= px_c < self._gal_w - 1 and 1 <= py_c < self._gal_h - 1:
                        renderer.draw_color = (210, 230, 255, f_alpha)
                        renderer.fill_rect((float(px_c - sz), float(py_c - sz),
                                            float(sz * 2), float(sz * 2)))

                # ── 2. Torn ring ──────────────────────────────────────────────
                # ease-out quadratic: r_norm = 1-(1-age)^2
                r_norm     = 1.0 - (1.0 - age) ** 2
                radius     = max_r * r_norm
                ring_alpha = int(210 * math.sin(age * math.pi))

                if ring_alpha > 5:
                    rr = int((1.0 - age) * 190 + age * 130)
                    rg = int((1.0 - age) * 220 + age * 100)
                    rb = 255

                    for i in range(N_DOTS):
                        theta = TWO_PI * i / N_DOTS + random.uniform(-0.20, 0.20)
                        cos_t = math.cos(theta)
                        sin_t = math.sin(theta)

                        # Radial noise: push dot inward or outward randomly
                        r_jit = radius + random.gauss(0.0, r_noise * math.sin(age * math.pi))
                        pxd   = int(cx + r_jit * cos_t)
                        pyd   = int(cy + r_jit * sin_t * aspect)

                        if not (dot_sz <= pxd < self._gal_w - dot_sz and
                                dot_sz <= pyd < self._gal_h - dot_sz):
                            continue

                        # Fade dots that are far off the ideal ring
                        radial_dev = abs(r_jit - radius) / max(r_noise, 1.0)
                        dot_a = int(ring_alpha * max(0.0, 1.0 - radial_dev * 0.6))
                        if dot_a > 6:
                            renderer.draw_color = (rr, rg, rb, dot_a)
                            renderer.fill_rect((float(pxd - dot_sz), float(pyd - dot_sz),
                                                float(dot_sz * 2), float(dot_sz * 2)))

                        # Chromatic fringe
                        ca_a = dot_a // 5
                        if ca_a > 5:
                            inner_bx = int(cx + (r_jit - fringe_r) * cos_t)
                            inner_by = int(cy + (r_jit - fringe_r) * sin_t * aspect)
                            outer_bx = int(cx + (r_jit + fringe_r) * cos_t)
                            outer_by = int(cy + (r_jit + fringe_r) * sin_t * aspect)
                            if (fringe_sz <= inner_bx < self._gal_w - fringe_sz and
                                    fringe_sz <= inner_by < self._gal_h - fringe_sz):
                                renderer.draw_color = (40, 90, 255, ca_a)
                                renderer.fill_rect((float(inner_bx - fringe_sz),
                                                    float(inner_by - fringe_sz),
                                                    float(fringe_sz * 2),
                                                    float(fringe_sz * 2)))
                            if (fringe_sz <= outer_bx < self._gal_w - fringe_sz and
                                    fringe_sz <= outer_by < self._gal_h - fringe_sz):
                                renderer.draw_color = (255, 60, 200, ca_a)
                                renderer.fill_rect((float(outer_bx - fringe_sz),
                                                    float(outer_by - fringe_sz),
                                                    float(fringe_sz * 2),
                                                    float(fringe_sz * 2)))

                # ── 3. Radial rift lines (cracks in space) ────────────────────
                # Only visible in first 70 % of life; each crack is a dotted
                # line from center outward with perpendicular wobble that grows
                # with distance (wider crack tip).
                if age < 0.70 and ring_alpha > 10:
                    rift_len   = radius * 0.88
                    rift_alpha = int(ring_alpha * 0.75)
                    N_STEPS    = 7
                    for ri in range(N_RIFTS):
                        base_angle  = TWO_PI * ri / N_RIFTS
                        rift_angle  = base_angle + random.uniform(-0.18, 0.18)
                        rc = math.cos(rift_angle)
                        rs = math.sin(rift_angle)
                        # perpendicular direction (rotated 90°)
                        pc = -rs
                        ps =  rc
                        for si in range(1, N_STEPS + 1):
                            t_r  = si / N_STEPS
                            dr   = rift_len * t_r
                            # perpendicular wobble grows toward the tip
                            wobble = random.gauss(0.0, tile_px_w * 0.14 * t_r)
                            rpx = int(cx + dr * rc + wobble * pc)
                            rpy = int(cy + (dr * rs + wobble * ps) * aspect)
                            if not (1 <= rpx < self._gal_w - 1 and 1 <= rpy < self._gal_h - 1):
                                continue
                            # Fade along the crack: bright at base, dim at tip
                            step_a = int(rift_alpha * (1.0 - t_r * 0.55))
                            if step_a > 6:
                                renderer.draw_color = (rr, rg, rb, step_a)
                                renderer.fill_rect((float(rpx - 1), float(rpy - 1), 2.0, 2.0))

                drew = True
        return drew

    def _jagged_line_spell_render(self, active_engine) -> bool:
        """Draws a jagged lightning bolt along the full spell path (bloom pass)."""
        jagged_lines = self._active_anim_bucket(active_engine, JaggedLineSpellParticle)
        if not jagged_lines:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map  = active_engine.game_map
        renderer  = self.renderer
        drew      = False

        with renderer.set_render_target(self._gal_src):
            for spell in jagged_lines:
                if not spell.path:
                    continue

                age = 1.0 - (spell.frames / float(spell.total_frames))
                # Stay bright for 70% of lifetime, fade over the last 30%
                alpha = int(255 * max(0.0, 1.0 - max(0.0, age - 0.7) / 0.1))
                if alpha < 8:
                    continue

                r, g, b = spell.color

                # Draw a segment for every consecutive pair of tiles in the path
                for i in range(len(spell.path) - 1):
                    ax, ay = spell.path[i]
                    bx, by = spell.path[i + 1]

                    # Visibility: skip if neither endpoint is on screen
                    if not (game_map.in_bounds(ax, ay) and game_map.visible[ax, ay]) and \
                       not (game_map.in_bounds(bx, by) and game_map.visible[bx, by]):
                        continue

                    # Screen pixel centres for this segment
                    scr_ax = (ax - origin_x) * tile_px_w + tile_px_w * 0.5
                    scr_ay = (ay - origin_y) * tile_px_h + tile_px_h * 0.5
                    scr_bx = (bx - origin_x) * tile_px_w + tile_px_w * 0.5
                    scr_by = (by - origin_y) * tile_px_h + tile_px_h * 0.5

                    # Interpolate along the segment and draw jittered dots
                    STEPS = 10
                    for s in range(STEPS + 1):
                        t = s / STEPS
                        ix = scr_ax + (scr_bx - scr_ax) * t
                        iy = scr_ay + (scr_by - scr_ay) * t

                        # Perpendicular jitter — magnitude shrinks at endpoints
                        jitter_scale = tile_px_w * 0.25 * math.sin(t * math.pi)
                        jx = random.uniform(-jitter_scale, jitter_scale)
                        jy = random.uniform(-jitter_scale, jitter_scale)

                        px = int(ix + jx)
                        py = int(iy + jy)

                        if not (2 <= px < self._gal_w - 2 and 2 <= py < self._gal_h - 2):
                            continue

                        # Core bolt: bright center
                        renderer.draw_color = (r, g, b, alpha)
                        renderer.fill_rect((float(px - 2), float(py - 2), 4.0, 4.0))

                        # Glow halo: slightly larger, semi-transparent
                        halo_a = alpha // 2
                        if halo_a > 8:
                            renderer.draw_color = (r, g, b, halo_a)
                            renderer.fill_rect((float(px - 4), float(py - 4), 8.0, 8.0))

                drew = True

        return drew

    def _projectile_trail_render(self, active_engine) -> bool:
        """Draw a smooth arced projectile stroke (slash-like, no orb trail)."""
        projectiles = [a for a in self._active_anim_bucket(active_engine, ProjectileTrailParticle) if a.path]
        if not projectiles:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height
        )
        game_map = active_engine.game_map
        renderer = self.renderer
        drew = False

        with renderer.set_render_target(self._gal_src):
            for proj in projectiles:
                if len(proj.path) == 1:
                    idx = 0
                else:
                    age = 1.0 - (proj.frames / float(max(1, proj.total_frames)))
                    age = max(0.0, min(1.0, age))
                    # Slight ease-out so the launch reads punchier.
                    eased = 1.0 - ((1.0 - age) ** 2)
                    idx = int(round(eased * (len(proj.path) - 1)))

                start_tx, start_ty = proj.path[0]
                head_tx, head_ty = proj.path[idx]
                end_tx, end_ty = proj.path[-1]

                # Build a smooth quadratic arc from launch -> current head, with the
                # control point offset perpendicular to overall travel.
                vec_x = end_tx - start_tx
                vec_y = end_ty - start_ty
                vec_mag = math.sqrt((vec_x * vec_x) + (vec_y * vec_y))
                if vec_mag <= 1e-6:
                    vec_x, vec_y = 1.0, 0.0
                    vec_mag = 1.0
                norm_x, norm_y = (vec_x / vec_mag), (vec_y / vec_mag)
                perp_x, perp_y = -norm_y, norm_x

                # Keep arc subtle and consistent with slash style.
                arc_sign = -1.0 if ((start_tx + start_ty + end_tx + end_ty) % 2 == 0) else 1.0
                arc_amp_tiles = max(0.15, min(0.55, vec_mag * 0.06))

                ctrl_tx = (start_tx + head_tx) * 0.5 + (perp_x * arc_amp_tiles * arc_sign)
                ctrl_ty = (start_ty + head_ty) * 0.5 + (perp_y * arc_amp_tiles * arc_sign)

                # Distance-scaled sample count for a smooth line.
                span = math.sqrt(((head_tx - start_tx) ** 2) + ((head_ty - start_ty) ** 2))
                segments = max(10, min(34, int(span * 8) + 10))

                r, g, b = proj.color
                for i in range(segments):
                    t = i / max(1, segments - 1)

                    # Quadratic Bezier: B(t) = (1-t)^2 P0 + 2(1-t)t P1 + t^2 P2
                    omt = 1.0 - t
                    bx = (omt * omt * start_tx) + (2.0 * omt * t * ctrl_tx) + (t * t * head_tx)
                    by = (omt * omt * start_ty) + (2.0 * omt * t * ctrl_ty) + (t * t * head_ty)

                    tx = int(round(bx))
                    ty = int(round(by))
                    if not game_map.in_bounds(tx, ty) or not game_map.visible[tx, ty]:
                        continue

                    sx = bx - origin_x
                    sy = by - origin_y
                    if not (0 <= sx < self.game_view_width and 0 <= sy < self.game_view_height):
                        continue

                    px = int(sx * tile_px_w + tile_px_w * 0.5)
                    py = int(sy * tile_px_h + tile_px_h * 0.5)
                    if not (2 <= px < self._gal_w - 2 and 2 <= py < self._gal_h - 2):
                        continue

                    # Slash-like envelope: bright in the middle, tapered tips, with
                    # a slight bias toward the moving front.
                    env = math.sin(t * math.pi)
                    front_bias = 0.75 + (0.25 * t)
                    alpha = int(220 * env * front_bias)
                    if alpha <= 8:
                        continue

                    core = 1.8 + (0.8 * env)
                    renderer.draw_color = (r, g, b, alpha)
                    renderer.fill_rect((float(px - core), float(py - core), float(core * 2.0), float(core * 2.0)))

                    drew = True

        return drew


    def _illuminated_render(self, active_engine) -> bool:
        """Draws a smooth breathing corona for each IlluminatedParticle (bloom pass).

        One persistent particle exists per orb.  The glow brightness is driven
        by a shared wall-clock sine so the corona breathes smoothly regardless
        of particle age or spawn timing.
        """
        import time as _time
        rays = self._active_anim_bucket(active_engine, IlluminatedParticle)
        if not rays:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map  = active_engine.game_map
        renderer  = self.renderer
        drew      = False

        N_BEAMS  = 8
        SEGS     = 24
        max_len  = tile_px_w * 1.1

        # Clock-based envelope: smoothly breathes between 0.55 and 1.0
        t_now    = _time.monotonic()
        envelope = 0.55 + 0.25 * math.sin(t_now * IlluminatedParticle._breath_speed * 2.0 * math.pi)
        peak_alpha = 55
        base_alpha = int(peak_alpha * envelope)

        with renderer.set_render_target(self._gal_src):
            for ray in rays:
                world_xi = int(round(ray.fx))
                world_yi = int(round(ray.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue

                scr_x = ray.fx - origin_x
                scr_y = ray.fy - origin_y
                if not (0.0 <= scr_x < self.game_view_width and
                        0.0 <= scr_y < self.game_view_height):
                    continue

                cx = scr_x * tile_px_w + tile_px_w * 0.5
                cy = scr_y * tile_px_h + tile_px_h * 0.5
                if not (4 <= cx < self._gal_w - 4 and 4 <= cy < self._gal_h - 4):
                    continue

                r, g, b = ray.color
                beam_len = max_len * (0.5 + 0.5 * envelope)

                # Unique per-orb angle offset so multiple orbs don't look identical
                angle_offset = (hash(id(ray)) % 360)

                for i in range(N_BEAMS):
                    rad   = math.radians(i * (360 / N_BEAMS) + angle_offset)
                    cos_a = math.cos(rad)
                    sin_a = math.sin(rad)

                    for s in range(1, SEGS + 1):
                        t = s / SEGS

                        # Squared falloff: bright near center, dim at tip
                        seg_alpha = int(base_alpha * (1.0 - t * t))
                        if seg_alpha < 2:
                            continue

                        dist = beam_len * t
                        sx = cx + cos_a * dist
                        sy = cy + sin_a * dist

                        half = max(0.5, 1.5 * (1.0 - t))

                        sx_i = int(sx)
                        sy_i = int(sy)
                        if not (int(half) + 1 <= sx_i < self._gal_w - int(half) - 1 and
                                int(half) + 1 <= sy_i < self._gal_h - int(half) - 1):
                            continue

                        renderer.draw_color = (r, g, b, seg_alpha)
                        renderer.fill_rect((sx - half, sy - half, half * 2.0, half * 2.0))

                # Soft central glow dot
                glow_alpha = int(base_alpha * 1.4)
                if glow_alpha > 0:
                    glow_r = max(1.5, tile_px_w * 0.12)
                    renderer.draw_color = (r, g, min(255, b + 20), min(255, glow_alpha))
                    renderer.fill_rect((cx - glow_r, cy - glow_r, glow_r * 2.0, glow_r * 2.0))

                drew = True

        return drew


    def _sleep_render(self, active_engine) -> bool:
        """Draw a soft drifting blue Z-aura for each SleepingParticle (bloom pass)."""
        sleeps = self._active_anim_bucket(active_engine, SleepingParticle)
        if not sleeps:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map = active_engine.game_map
        renderer = self.renderer
        drew = False

        with renderer.set_render_target(self._gal_src):
            for sleep in sleeps:
                world_xi = int(round(sleep.fx))
                world_yi = int(round(sleep.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue

                scr_x = sleep.fx - origin_x
                scr_y = sleep.fy - origin_y
                if not (0.0 <= scr_x < self.game_view_width and
                        0.0 <= scr_y < self.game_view_height):
                    continue

                cx = scr_x * tile_px_w + tile_px_w * 0.5
                cy = scr_y * tile_px_h + tile_px_h * 0.18
                if not (2 <= cx < self._gal_w - 2 and 2 <= cy < self._gal_h - 2):
                    continue

                import time as _time
                t_now = _time.monotonic()
                envelope = 0.65 + 0.20 * math.sin(t_now * SleepingParticle._breath_speed * 2.0 * math.pi)
                age = 1.0 - (sleep.frames / float(sleep.total_frames))
                alpha = int(190 * envelope * max(0.15, 1.0 - age * 0.55))
                if alpha < 8:
                    continue

                r, g, b = sleep.color
                # Build a small Z-shape from rectangles, with a faint drifting trail.
                top_w = max(3, int(tile_px_w * 0.16))
                top_h = max(2, int(tile_px_h * 0.05))
                mid_w = max(2, int(tile_px_w * 0.10))
                mid_h = max(2, int(tile_px_h * 0.05))
                bot_w = max(3, int(tile_px_w * 0.16))
                bot_h = max(2, int(tile_px_h * 0.05))
                drift = math.sin(t_now * 1.7 + (id(sleep) % 11)) * max(1.0, tile_px_h * 0.03)

                renderer.draw_color = (r, g, b, alpha)
                renderer.fill_rect((cx - top_w * 0.5, cy - tile_px_h * 0.18 + drift, top_w, top_h))
                renderer.fill_rect((cx + tile_px_w * 0.06, cy + drift * 0.5, mid_w, mid_h))
                renderer.fill_rect((cx - bot_w * 0.5, cy + tile_px_h * 0.16 + drift, bot_w, bot_h))

                # Faint mist puff under the Z to make it feel sleepy rather than magical.
                renderer.draw_color = (220, 230, 255, max(8, alpha // 3))
                puff = max(2, int(tile_px_w * 0.08))
                renderer.fill_rect((cx - puff * 0.5, cy + tile_px_h * 0.28 + drift * 0.3, puff, puff))
                drew = True

        return drew


    def _heal_render(self, active_engine) -> bool:
        """Draw rising green crosses for each HealthParticle (bloom pass)."""
        heals = self._active_anim_bucket(active_engine, HealthParticle)
        if not heals:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map  = active_engine.game_map
        renderer  = self.renderer
        drew      = False

        with renderer.set_render_target(self._gal_src):
            for heal in heals:
                world_xi = int(round(heal.fx))
                world_yi = int(round(heal.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue

                scr_x = heal.fx - origin_x
                scr_y = heal.fy - origin_y
                if not (0.0 <= scr_x < self.game_view_width and
                        0.0 <= scr_y < self.game_view_height):
                    continue

                px = int(scr_x * tile_px_w + tile_px_w * 0.5)
                py = int(scr_y * tile_px_h + tile_px_h * 0.5)
                if not (2 <= px < self._gal_w - 2 and 2 <= py < self._gal_h - 2):
                    continue

                age = 1.0 - (heal.frames / float(heal.total_frames))

                # Colour: bright green fading to transparent
                alpha = int(200 * (1.0 - age))
                if alpha < 8:
                    continue

                # Cross shape: two thin rectangles intersecting at the center
                # Draw three randomly offset copies
                sz = max(2, int(min(tile_px_w, tile_px_h) * 0.15))
                renderer.draw_color = (120, 255, 120, alpha)
                renderer.fill_rect((float(px + random.random() * sz - sz // 2), float(py - sz // 4),
                                    float(sz * 2), float(sz // 2)))
                renderer.fill_rect((float(px + random.random() * sz - sz // 4), float(py - sz),
                                    float(sz // 2), float(sz * 2)))
                renderer.fill_rect((float(px - sz), float(py - sz // 4),
                                    float(sz * 2), float(sz // 2)))
                renderer.fill_rect((float(px - sz // 4), float(py - sz),
                                    float(sz // 2), float(sz * 2)))
                drew = True

        return drew

    def _damage_number_render(self, active_engine) -> bool:
        """Draw floating damage numbers for each DamageNumberParticle (bloom pass).

        Renders orange-red pixel-art digits that rise from a hit entity and fade out.
        """
        nums = self._active_anim_bucket(active_engine, DamageNumberParticle)
        if not nums:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map  = active_engine.game_map
        renderer  = self.renderer
        drew      = False

        with renderer.set_render_target(self._gal_src):
            for num in nums:
                world_xi = int(round(num.fx))
                world_yi = int(round(num.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue

                scr_x = num.fx - origin_x
                scr_y = num.fy - origin_y
                # Allow slightly off-screen vertically so numbers rising upward stay visible
                if not (-1.0 <= scr_x < self.game_view_width and
                        -2.0 <= scr_y < self.game_view_height):
                    continue

                cx = int(scr_x * tile_px_w + tile_px_w * 0.5)
                cy = int(scr_y * tile_px_h + tile_px_h * 0.5)

                age = 1.0 - (num.frames / float(num.total_frames))
                # Ramp up briefly then fade — avoids a hard bright flash at spawn
                if age < 0.12:
                    alpha = int(120 * (age / 0.12))
                elif age < 0.30:
                    alpha = 120
                else:
                    alpha = int(120 * (1.0 - (age - 0.30) / 0.70))
                if alpha < 8:
                    continue

                # Colour: lerp from full base colour toward a slightly lighter shade
                br, bg, bb_base = num.color
                rr = min(255, int(br + (255 - br) * age * 0.3))
                gg = min(255, int(bg + (255 - bg) * age * 0.15))
                bb = min(255, int(bb_base + (255 - bb_base) * age * 0.1))

                # Pixel font: each cell is sz × sz pixels
                sz = max(1, int(min(tile_px_w, tile_px_h) * 0.10))
                n_chars  = len(num.number)
                char_w   = 3   # digit grid width
                gap      = 1   # one-cell gap between digits
                total_w  = (n_chars * char_w + max(0, n_chars - 1) * gap) * sz
                start_x  = cx - total_w // 2

                for i, ch in enumerate(num.number):
                    dots = DamageNumberParticle._PIXEL_DIGITS.get(ch)
                    if dots is None:
                        continue
                    dx_off = i * (char_w + gap) * sz
                    for (dc, dr) in dots:
                        px   = start_x + dx_off + dc * sz
                        py_d = cy + dr * sz
                        if 0 <= px < self._gal_w - sz and 0 <= py_d < self._gal_h - sz:
                            renderer.draw_color = (rr, gg, bb, alpha)
                            renderer.fill_rect((float(px), float(py_d),
                                                float(sz), float(sz)))
                drew = True

        return drew

    def _burn_render(self, active_engine) -> bool:
        """Draw rising flame sparks for each BurningParticle (bloom pass).

        Each particle is a small vertically-elongated rect whose colour shifts
        from bright yellow-white at birth through orange to dim red at death,
        mirroring how a real flame tongue cools as it rises.
        """
        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map  = active_engine.game_map
        renderer  = self.renderer
        drew      = False
        spark_w   = max(2, int(tile_px_w * 0.09))
        spark_h   = max(3, int(tile_px_h * 0.18))

        with renderer.set_render_target(self._gal_src):
            for burn in self._active_anim_bucket(active_engine, BurningParticle):
                # Visibility — check origin tile (entity tile), not spark tile
                entity = getattr(burn, "entity", None)
                ex = int(round(entity.x if entity is not None and hasattr(entity, 'x') else burn.anchor_x))
                ey = int(round(entity.y if entity is not None and hasattr(entity, 'y') else burn.anchor_y))
                if not game_map.in_bounds(ex, ey):
                    continue
                if not game_map.visible[ex, ey]:
                    continue

                for spark in getattr(burn, "sparks", []):
                    scr_x = spark.fx - origin_x
                    scr_y = spark.fy - origin_y
                    if not (-1.0 <= scr_x < self.game_view_width + 1.0 and
                            -1.0 <= scr_y < self.game_view_height + 1.0):
                        continue

                    px = int(scr_x * tile_px_w + tile_px_w * 0.5)
                    py = int(scr_y * tile_px_h + tile_px_h * 0.5)
                    if not (2 <= px < self._gal_w - 2 and 2 <= py < self._gal_h - 2):
                        continue

                    # age 0=birth 1=death
                    age = 1.0 - (spark.frames / float(spark.total_frames))

                    # Colour: young=yellow-white, middle=orange, old=dim red
                    if age < 0.4:
                        t   = age / 0.4
                        r   = 255
                        g   = int(255 - t * 105)   # 255 -> 150
                        b   = int(180 - t * 180)   # 180 -> 0
                    else:
                        t   = (age - 0.4) / 0.6
                        r   = int(255 - t * 55)    # 255 -> 200
                        g   = int(150 - t * 150)   # 150 -> 0
                        b   = 0

                    # Alpha: full for first 60%, then fade out
                    alpha = int(220 * max(0.0, 1.0 - max(0.0, age - 0.6) / 0.4))
                    if alpha < 8:
                        continue

                    # Small vertically-elongated flame tongue
                    renderer.draw_color = (r, g, b, alpha)
                    renderer.fill_rect((float(px - spark_w // 2), float(py - spark_h // 2),
                                        float(spark_w), float(spark_h)))
                    drew = True

        return drew

    def _dodge_render(self, active_engine) -> bool:
        """Draw DodgeParticle tiles with a directional slide and ghost afterimages.

        The leading tile moves up to half a tile in dodge.dir over its lifetime.
        Two ghost copies are drawn behind it at decreasing alpha to sell the
        speed-step feel.  The codepoint must sit in the 0xE000 PUA range.
        """
        dodges = self._active_anim_bucket(active_engine, DodgeParticle)
        if not dodges:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        hw        = int(tile_px_w * 0.5)
        hh        = int(tile_px_h * 0.5)
        renderer  = self.renderer
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map = active_engine.game_map
        drew     = False

        # Ghost offsets in tile-fractions behind the leader (negative = behind)
        GHOSTS = (
            (-0.35, 55),   # (tile-fraction back, base alpha)
            (-0.70, 25),
        )
        # Max leader travel — half a tile
        MAX_TRAVEL_PX = tile_px_w * 0.5

        with renderer.set_render_target(self._gal_src):
            for dodge in dodges:
                world_xi = int(round(dodge.fx))
                world_yi = int(round(dodge.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue

                scr_x = dodge.fx - origin_x
                scr_y = dodge.fy - origin_y
                if not (0.0 <= scr_x < self.game_view_width and
                        0.0 <= scr_y < self.game_view_height):
                    continue

                base_px = int(scr_x * tile_px_w + tile_px_w * 0.5)
                base_py = int(scr_y * tile_px_h + tile_px_h * 0.5)

                # Resolve / cache texture
                cp = ord(dodge.character)
                if cp not in self._dodge_tile_cache:
                    tile_pixels = self.tileset.get_tile(cp)  # (H, W, 4) RGBA
                    tex = renderer.upload_texture(tile_pixels)
                    tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    self._dodge_tile_cache[cp] = tex
                tex = self._dodge_tile_cache[cp]

                # age: 0 at birth → 1 at death
                age      = 1.0 - (dodge.frames / float(dodge.total_frames))
                # Leader slides forward, then fades out in the last 35%
                travel   = age * MAX_TRAVEL_PX
                fade_in  = min(1.0, age / 0.10)           # quick flash-in
                fade_out = max(0.0, 1.0 - max(0.0, age - 0.65) / 0.35)
                lead_alpha = int(50 * fade_in * fade_out)

                ndx, ndy = dodge.dir

                # Pale cyan tint — visible but not blinding
                tex.color_mod = (160, 220, 255)

                # --- Ghost afterimages ---
                for ghost_frac, ghost_base_alpha in GHOSTS:
                    g_off    = travel + ghost_frac * tile_px_w
                    g_px     = base_px + int(ndx * g_off)
                    g_py     = base_py + int(ndy * g_off)
                    if not (hw <= g_px < self._gal_w - hw and
                            hh <= g_py < self._gal_h - hh):
                        continue
                    g_alpha  = int(ghost_base_alpha * fade_in * fade_out)
                    if g_alpha <= 0:
                        continue
                    tex.alpha_mod = g_alpha
                    renderer.copy(tex, dest=(float(g_px - hw), float(g_py - hh),
                                             float(tile_px_w), float(tile_px_h)))

                # --- Leading tile ---
                lead_px = base_px + int(ndx * travel)
                lead_py = base_py + int(ndy * travel)
                if (hw <= lead_px < self._gal_w - hw and
                        hh <= lead_py < self._gal_h - hh
                        and lead_alpha > 0):
                    tex.alpha_mod = lead_alpha
                    renderer.copy(tex, dest=(float(lead_px - hw), float(lead_py - hh),
                                             float(tile_px_w), float(tile_px_h)))
                    drew = True

        return drew


    def _slash_render(self, active_engine) -> bool:
        """Draw a slicing slash effect for each SlashParticle into _gal_src (bloom pass)."""
        slashes = self._active_anim_bucket(active_engine, SlashParticle)
        if not slashes:
            return False
        
        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        renderer  = self.renderer
        game_map  = active_engine.game_map

        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        
        drew = False
        with renderer.set_render_target(self._gal_src):
            for slash in slashes:
                wx, wy = int(slash.fx), int(slash.fy)
                if not game_map.in_bounds(wx, wy) or not game_map.visible[wx, wy]:
                    continue

                # Screen position
                scr_x = slash.fx - origin_x
                scr_y = slash.fy - origin_y

                if not (0.0 <= scr_x < self.game_view_width and
                        0.0 <= scr_y < self.game_view_height):
                    continue

                px = int(scr_x * tile_px_w + tile_px_w * 0.5)
                py = int(scr_y * tile_px_h + tile_px_h * 0.5)

                if not (0 <= px < self._gal_w and 0 <= py < self._gal_h):
                    continue

                # Intensity: linear fade from 255 → 0 over lifetime
                age = 1.0 - (slash.frames / float(slash.total_frames))
                intensity = int(255 * (1.0 - age))

                if intensity <= 8: # Avoid invisible slashes
                    continue

                # Color
                r, g, b = slash.color
                if slash.enchanted:
                    r = min(255, int(r * 1.5))
                    g = min(255, int(g * 1.5))
                    b = min(255, int(b * 2.0))
                else:
                    r = min(255, int(r * 1.3))
                    g = min(255, int(g * 1.3))
                    b = min(255, int(b * 1.3))

                # Direction — already normalized + jittered at spawn time
                norm_dx, norm_dy = slash.angle
                if norm_dx == 0.0 and norm_dy == 0.0:
                    continue

                # Perpendicular vector (for arc bow)
                perp_dx = -norm_dy
                perp_dy =  norm_dx

                # ~1 tile, centered on the target tile
                half_len = tile_px_w * 0.55
                arc_amp  = tile_px_h * 0.18   # small perpendicular bow

                SEGMENTS = 18
                for i in range(SEGMENTS):
                    t   = i / (SEGMENTS - 1)                 # 0..1 inclusive
                    s   = t * 2.0 - 1.0                      # -1..1 centered
                    arc = math.sin(t * math.pi) * arc_amp    # smooth bow, 0 at tips

                    sx = px + norm_dx * half_len * s + perp_dx * arc
                    sy = py + norm_dy * half_len * s + perp_dy * arc

                    # Sin envelope: bright centre, dim at tips; scaled by overall intensity
                    env  = math.sin(t * math.pi)
                    fade = int(intensity * env)
                    if fade < 8:
                        continue

                    renderer.draw_color = (r, g, b, fade)
                    if slash.type == "miss":
                        renderer.draw_color = (int(r/2), int(g//3), int(b//4), int(fade//3))
                        renderer.fill_rect((sx - 25, sy - 25, 3.0, 3.0))
                    elif slash.type == "unarmed":
                        # Impact cross: two overlapping arcs at the hit point.
                        # Arc 1 (i < half): attack direction, wide bow → looks like a
                        #   hook/punch concave curve.
                        # Arc 2 (i >= half): perpendicular, tighter → cross mark.
                        half = SEGMENTS // 2
                        if i < half:
                            t2  = i / max(half - 1, 1)
                            s2  = t2 * 2.0 - 1.0
                            hl2 = tile_px_w * 0.28
                            aa2 = tile_px_h * 0.44
                            bow = math.sin(t2 * math.pi)
                            sx2 = px + norm_dx * hl2 * s2 + perp_dx * aa2 * bow
                            sy2 = py + norm_dy * hl2 * s2 + perp_dy * aa2 * bow
                        else:
                            t2  = (i - half) / max(SEGMENTS - half - 1, 1)
                            s2  = t2 * 2.0 - 1.0
                            hl2 = tile_px_w * 0.18
                            aa2 = tile_px_h * 0.20
                            bow = math.sin(t2 * math.pi)
                            sx2 = px + perp_dx * hl2 * s2 - norm_dx * aa2 * bow
                            sy2 = py + perp_dy * hl2 * s2 - norm_dy * aa2 * bow
                        dot_r = max(1.5, 3.5 * env)
                        renderer.draw_color = (r, g, b, fade)
                        renderer.fill_rect((sx2 - dot_r, sy2 - dot_r, dot_r * 2, dot_r * 2))
                    else:
                        renderer.fill_rect((sx - 1.5, sy - 1.5, 3.0, 3.0))

                drew = True
        return drew
                


    
    def _light_shaft_render(self, active_engine) -> bool:
        """Draw a fading trapezoid light shaft for each LightShaftParticles into _gal_src (bloom).

        Each shaft is sliced into SLICES horizontal bands.  Near the window the
        band is 1 tile wide; at the far end it spreads to (1 + 2*SPREAD) tiles.
        RGB intensity fades linearly to zero at the far end.  The whole thing
        also fades in/out at birth/death via an age envelope.
        """
        shafts = self._active_anim_bucket(active_engine, LightShaftParticles)
        if not shafts:
            return False

        SLICES    = 80
        SPREAD    = .75    # extra half-tiles of width gained over the shaft length
        BASE_INT  = 0.3   # peak brightness (0–1); bloom amplifies this further

        tile_px_w  = self.base_tile_w * self.game_zoom
        tile_px_h  = self.base_tile_h * self.game_zoom
        renderer   = self.renderer
        game_map   = active_engine.game_map
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)

        drew = False
        with renderer.set_render_target(self._gal_src):
            for shaft in shafts:
                wx, wy = int(shaft.fx), int(shaft.fy)
                if not game_map.in_bounds(wx, wy) or not game_map.visible[wx, wy]:
                    continue

                # Screen-pixel centre of the window tile
                cx_px = (shaft.fx - origin_x) * tile_px_w + tile_px_w * 0.5
                if shaft.shaft_direction == 1:
                    cy_px = (shaft.fy - origin_y) * tile_px_h + tile_px_h * 1
                else:
                    cy_px = (shaft.fy - origin_y) * tile_px_h + tile_px_h * 0

                # +1 = downward (south), -1 = upward (north)
                screen_sign = float(shaft.shaft_direction)
                length_px   = shaft.length * tile_px_h

                sr, sg, sb = shaft.color
                half_tile_w = tile_px_w * 0.30
                spread_px   = SPREAD * tile_px_w

                for i in range(SLICES):
                    t0    = i       / SLICES
                    t1    = (i + 1) / SLICES
                    t_mid = (t0 + t1) * 0.5

                    # Vertical extent of this slice
                    y_a   = cy_px + screen_sign * t0 * length_px
                    y_b   = cy_px + screen_sign * t1 * length_px
                    y_top = min(y_a, y_b)
                    
                    s_h   = max(1.0, abs(y_b - y_a))

                    # Horizontal extent: widens from 1 tile → (1 + 2·SPREAD) tiles
                    half_w = half_tile_w + spread_px * t_mid
                    x0     = cx_px - half_w

                    # Intensity fades to zero at the far tip
                    intensity = BASE_INT * (1.0 - t_mid)
                    r = int(sr * intensity)
                    g = int(sg * intensity)
                    b = int(sb * intensity)
                    if r == 0 and g == 0 and b == 0:
                        continue

                    renderer.draw_color = (r, g, b, 150)
                    renderer.fill_rect((float(x0), float(y_top),
                                        float(half_w * 2.0), float(s_h)))
                drew = True
        return drew

    def _dust_render(self, active_engine) -> bool:
        """Draw faint drifting dust motes into _gal_src.

        Dust is intentionally subtle: tiny warm-gray specks with a soft fade
        envelope so they read as atmospheric particulate rather than magic.
        """
        motes = self._active_anim_bucket(active_engine, DustParticle)
        if not motes:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map = active_engine.game_map
        renderer = self.renderer
        drew = False
        _dust_min_light = 0.0
        try:
            getter = getattr(active_engine, "get_ambient_particle_min_light", None)
            if callable(getter):
                _dust_min_light = float(getter("dust", 0.0))
        except Exception:
            _dust_min_light = 0.0

        with renderer.set_render_target(self._gal_src):
            for mote in motes:
                sx_tile = int(mote.source_pos[0])
                sy_tile = int(mote.source_pos[1])
                if not game_map.in_bounds(sx_tile, sy_tile):
                    continue
                if not game_map.visible[sx_tile, sy_tile]:
                    continue

                world_xi = int(round(mote.fx))
                world_yi = int(round(mote.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue

                if _dust_min_light > 0.0:
                    try:
                        if float(game_map.tiles["light_level"][world_xi, world_yi]) < _dust_min_light:
                            continue
                    except Exception:
                        continue

                scr_x = mote.fx - origin_x
                scr_y = mote.fy - origin_y
                if not (-0.5 <= scr_x < self.game_view_width + 0.5 and
                        -0.5 <= scr_y < self.game_view_height + 0.5):
                    continue

                px = int(scr_x * tile_px_w + tile_px_w * 0.5)
                py = int(scr_y * tile_px_h + tile_px_h * 0.5)
                sz = max(1, int(round(mote.size)))
                if not (sz <= px < self._gal_w - sz and sz <= py < self._gal_h - sz):
                    continue

                age = 1.0 - (mote.frames / float(max(1, mote.total_frames)))
                if age < 0.15:
                    fade = age / 0.15
                elif age > 0.82:
                    fade = max(0.0, (1.0 - age) / 0.18)
                else:
                    fade = 1.0
                if fade <= 0.0:
                    continue

                # Cheap local lighting response: dust catches bright shafts and
                # light gradients (forward-scatter look) while staying faint in dark.
                try:
                    ll = game_map.tiles["light_level"]
                    l_center = float(ll[world_xi, world_yi])
                    l_max_n = l_center
                    if game_map.in_bounds(world_xi + 1, world_yi):
                        l_max_n = max(l_max_n, float(ll[world_xi + 1, world_yi]))
                    if game_map.in_bounds(world_xi - 1, world_yi):
                        l_max_n = max(l_max_n, float(ll[world_xi - 1, world_yi]))
                    if game_map.in_bounds(world_xi, world_yi + 1):
                        l_max_n = max(l_max_n, float(ll[world_xi, world_yi + 1]))
                    if game_map.in_bounds(world_xi, world_yi - 1):
                        l_max_n = max(l_max_n, float(ll[world_xi, world_yi - 1]))
                except Exception:
                    l_center = 0.25
                    l_max_n = l_center

                l_center = max(0.0, min(1.0, l_center))
                l_edge = max(0.0, min(1.0, l_max_n - l_center))
                light_response = max(0.0, min(1.0, (0.20 + l_center * 0.80 + l_edge * 0.55) ** 0.72))

                twinkle = 0.60 + 0.40 * math.sin(age * 8.5 + mote.twinkle_phase)
                alpha = int((22 + 90 * light_response) * fade * twinkle)
                if alpha < 5:
                    continue

                r, g, b = mote.color
                warm_lift = int(16 * light_response)
                renderer.draw_color = (
                    min(255, int(r * (0.86 + 0.34 * light_response)) + warm_lift),
                    min(255, int(g * (0.86 + 0.32 * light_response)) + warm_lift),
                    min(255, int(b * (0.84 + 0.26 * light_response))),
                    alpha,
                )
                renderer.fill_rect((float(px - sz * 0.5), float(py - sz * 0.5),
                                    float(sz), float(sz)))

                halo_alpha = int(alpha * (0.25 + 0.45 * light_response))
                if halo_alpha > 4:
                    renderer.draw_color = (min(255, r + 10), min(255, g + 10), min(255, b + 10), halo_alpha)
                    renderer.fill_rect((float(px - sz), float(py - sz),
                                        float(sz * 2), float(sz * 2)))
                drew = True

        return drew


    def _gpu_smoke_render(self, active_engine) -> bool:
        """Draw SmokeCloudParticle sprite frames into _gal_src (bloom pass)."""
        smokes = self._active_anim_bucket(active_engine, SmokeCloudParticle)
        if not smokes:
            return False
        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        renderer  = self.renderer

        # Lazy-load animated smoke sprite sheet
        if self._smoke_tex is None:
            smoke_frames = []
            smoke_tex_frames = []
            for i in range(7):
                img = Image.open(
                    self._get_data_path(f"RP/particles/smoke/smoke{i+1}.png")
                ).convert("RGBA")
                frame_np = np.array(img, dtype=np.uint8)
                smoke_frames.append(frame_np)
                frame_tex = renderer.upload_texture(frame_np)
                frame_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                smoke_tex_frames.append(frame_tex)
            self._smoke_tex = smoke_tex_frames[0]
            self._smoke_frames = smoke_frames
            self._smoke_tex_frames = smoke_tex_frames

        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map = active_engine.game_map
        drew     = False
        with renderer.set_render_target(self._gal_src):
            for smoke in smokes:
                world_xi = int(round(smoke.fx))
                world_yi = int(round(smoke.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue
                scr_x = smoke.fx - origin_x
                scr_y = smoke.fy - origin_y
                if not (0.0 <= scr_x < self.game_view_width and
                        0.0 <= scr_y < self.game_view_height):
                    continue
                px = int(scr_x * tile_px_w + tile_px_w * 0.5)
                py = int(scr_y * tile_px_h + tile_px_h * 0.5)
                if not (16 <= px < self._gal_w - 16 and 16 <= py < self._gal_h - 16):
                    continue
                age         = 1.0 - (smoke.frames / float(smoke.total_frames))
                frame_index = min(
                    len(self._smoke_frames) - 1,
                    int(age * len(self._smoke_frames))
                )
                smoke_tex = self._smoke_tex_frames[frame_index]
                if age < 0.15:
                    smoke_alpha = int(age / 0.15 * 180)
                elif age < 0.70:
                    smoke_alpha = 180
                else:
                    smoke_alpha = int((1.0 - age) / 0.30 * 180)
                smoke_tex.alpha_mod = max(0, smoke_alpha)
                renderer.copy(smoke_tex,
                              dest=(float(px - 16), float(py - 16), 32.0, 32.0))
                drew = True
        return drew

    def _gpu_drip_render(self, active_engine) -> bool:
        """Draw DripParticle rects into _gal_src (no-bloom, BLEND pass).

        Uses exact drip.color with a late-fade curve so drips stay fully
        opaque for 85% of their lifetime then fade out over the last 15%.
        """
        drips = self._active_anim_bucket(active_engine, DripParticle)
        if not drips:
            return False
        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        sz        = 1
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map  = active_engine.game_map
        renderer  = self.renderer
        drew      = False
        with renderer.set_render_target(self._gal_src):
            for drip in drips:
                world_xi = int(round(drip.fx))
                world_yi = int(round(drip.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue
                scr_x = drip.fx - origin_x
                scr_y = drip.fy - origin_y
                if not (0.0 <= scr_x < self.game_view_width and
                        0.0 <= scr_y < self.game_view_height):
                    continue
                px = int(scr_x * tile_px_w + tile_px_w * 0.5)
                py = int(scr_y * tile_px_h + tile_px_h * 0.5)
                if not (sz <= px < self._gal_w - sz and sz <= py < self._gal_h - sz):
                    continue
                age  = 1.0 - (drip.frames / float(drip.total_frames))
                br, bg, bb = drip.color
                # Fully opaque for 85% of lifetime, fade only in final 15%
                fade = max(0.0, 1.0 - max(0.0, age - 0.85) / 0.15)
                renderer.draw_color = (int(br * fade), int(bg * fade), int(bb * fade), 255)
                renderer.fill_rect((float(px - sz), float(py - sz),
                                    float(sz * 2), float(sz * 2)))
                drew = True
        return drew

    def _fireball_explosion_render(self, active_engine) -> bool:
        """Expanding fire blast for FireballExplosionParticle (bloom pass).

        Draws:
          1. Bright white-hot central flash (first 30 % of life).
          2. Expanding ring of orange-red fire dots (ease-out, grows to particle radius).
          3. Scattered inner ember dots inside the blast area.
          4. 8 radial heat-ray streaks from the centre.
        """
        particles = self._active_anim_bucket(active_engine, FireballExplosionParticle)
        if not particles:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map = active_engine.game_map
        renderer = self.renderer
        drew     = False

        TWO_PI   = 2.0 * math.pi
        N_RING   = 32           # sample points for the fire ring
        N_RAYS   = 8            # radial heat streaks
        N_EMBERS = 18           # scattered inner ember dots
        aspect   = tile_px_h / tile_px_w

        with renderer.set_render_target(self._gal_src):
            for p in particles:
                world_xi = int(round(p.fx))
                world_yi = int(round(p.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue

                scr_x = p.fx - origin_x
                scr_y = p.fy - origin_y
                if not (0.0 <= scr_x < self.game_view_width and
                        0.0 <= scr_y < self.game_view_height):
                    continue

                cx  = scr_x * tile_px_w + tile_px_w * 0.5
                cy  = scr_y * tile_px_h + tile_px_h * 0.5
                age = 1.0 - (p.frames / float(p.total_frames))
                max_r = p.radius * tile_px_w

                # ── 1. Central white-hot flash (first 30 % of life) ──────────
                if age < 0.30:
                    t_flash  = age / 0.30
                    f_alpha  = int(230 * math.sin(t_flash * math.pi))
                    sz_flash = max(2, int(tile_px_w * (0.55 - t_flash * 0.35)))
                    px_c     = int(cx)
                    py_c     = int(cy)
                    if f_alpha > 8 and 2 <= px_c < self._gal_w - 2 and 2 <= py_c < self._gal_h - 2:
                        renderer.draw_color = (255, 255, int(200 * (1.0 - t_flash)), f_alpha)
                        renderer.fill_rect((float(px_c - sz_flash), float(py_c - sz_flash),
                                            float(sz_flash * 2), float(sz_flash * 2)))
                        halo_sz = sz_flash + max(1, int(tile_px_w * 0.18))
                        ha = int(f_alpha * 0.4)
                        if ha > 6:
                            renderer.draw_color = (255, 180, 0, ha)
                            renderer.fill_rect((float(px_c - halo_sz), float(py_c - halo_sz),
                                                float(halo_sz * 2), float(halo_sz * 2)))

                # ── 2. Expanding fire ring ────────────────────────────────────
                # ease-out quad: ring expands quickly then slows at the edge
                r_norm     = 1.0 - (1.0 - age) ** 2
                radius     = max_r * r_norm
                ring_alpha = int(200 * math.sin(age * math.pi))
                dot_sz     = max(1, int(tile_px_w * 0.10))
                r_noise    = tile_px_w * 0.18

                if ring_alpha > 8:
                    rg_ring = max(0, int(180 - age * 180))
                    for i in range(N_RING):
                        theta = TWO_PI * i / N_RING
                        cos_t = math.cos(theta)
                        sin_t = math.sin(theta)
                        r_jit = radius + random.gauss(0.0, r_noise * math.sin(age * math.pi))
                        pxd   = int(cx + r_jit * cos_t)
                        pyd   = int(cy + r_jit * sin_t * aspect)
                        if not (dot_sz <= pxd < self._gal_w - dot_sz and
                                dot_sz <= pyd < self._gal_h - dot_sz):
                            continue
                        renderer.draw_color = (255, rg_ring, 0, ring_alpha)
                        renderer.fill_rect((float(pxd - dot_sz), float(pyd - dot_sz),
                                            float(dot_sz * 2), float(dot_sz * 2)))

                # ── 3. Scattered inner ember dots ─────────────────────────────
                if age > 0.05 and ring_alpha > 10:
                    e_alpha = int(ring_alpha * 0.7)
                    esz     = max(1, dot_sz - 1)
                    for i in range(N_EMBERS):
                        theta = TWO_PI * (i / N_EMBERS) + random.uniform(-0.3, 0.3)
                        r_e   = radius * random.uniform(0.1, 0.85)
                        epx   = int(cx + r_e * math.cos(theta))
                        epy   = int(cy + r_e * math.sin(theta) * aspect)
                        if not (esz <= epx < self._gal_w - esz and
                                esz <= epy < self._gal_h - esz):
                            continue
                        t_heat = 1.0 - (r_e / max(radius, 1.0))
                        eg_e   = int(200 * t_heat)
                        eb_e   = int(150 * t_heat)
                        renderer.draw_color = (255, eg_e, eb_e, e_alpha)
                        renderer.fill_rect((float(epx - esz), float(epy - esz),
                                            float(esz * 2), float(esz * 2)))

                # ── 4. Radial heat rays ───────────────────────────────────────
                if age < 0.65 and ring_alpha > 12:
                    ray_len   = radius * 0.80
                    ray_alpha = int(ring_alpha * 0.65)
                    N_STEPS   = 8
                    rg_ray    = max(0, int(160 - age * 160))
                    for ri in range(N_RAYS):
                        ray_angle = TWO_PI * ri / N_RAYS + random.uniform(-0.15, 0.15)
                        rc = math.cos(ray_angle)
                        rs = math.sin(ray_angle)
                        for si in range(1, N_STEPS + 1):
                            t_r  = si / N_STEPS
                            dr   = ray_len * t_r
                            rpx  = int(cx + dr * rc)
                            rpy  = int(cy + dr * rs * aspect)
                            if not (1 <= rpx < self._gal_w - 1 and 1 <= rpy < self._gal_h - 1):
                                continue
                            step_a = int(ray_alpha * (1.0 - t_r * 0.6))
                            if step_a > 6:
                                renderer.draw_color = (255, rg_ray, 0, step_a)
                                renderer.fill_rect((float(rpx - 1), float(rpy - 1), 2.0, 2.0))

                drew = True
        return drew

    def _poison_spray_render(self, active_engine) -> bool:
        """Acid-green splatter for PoisonSprayParticle (bloom pass).

        Draws:
          1. Bright central glob flash (first 25 % of life).
          2. Radiating acid droplets flying outward with ease-out cubic slowdown.
          3. A halfway trail dot per droplet for a flung-liquid look.
        """
        particles = self._active_anim_bucket(active_engine, PoisonSprayParticle)
        if not particles:
            return False

        tile_px_w = self.base_tile_w * self.game_zoom
        tile_px_h = self.base_tile_h * self.game_zoom
        origin_x, origin_y = active_engine.get_camera_origin(
            self.game_view_width, self.game_view_height)
        game_map = active_engine.game_map
        renderer = self.renderer
        drew     = False

        aspect   = tile_px_h / tile_px_w
        max_dist = tile_px_w * 1.4     # droplets travel up to ~1.4 tiles from center

        with renderer.set_render_target(self._gal_src):
            for p in particles:
                world_xi = int(round(p.fx))
                world_yi = int(round(p.fy))
                if not game_map.in_bounds(world_xi, world_yi):
                    continue
                if not game_map.visible[world_xi, world_yi]:
                    continue

                scr_x = p.fx - origin_x
                scr_y = p.fy - origin_y
                if not (0.0 <= scr_x < self.game_view_width and
                        0.0 <= scr_y < self.game_view_height):
                    continue

                cx  = scr_x * tile_px_w + tile_px_w * 0.5
                cy  = scr_y * tile_px_h + tile_px_h * 0.5
                age = 1.0 - (p.frames / float(p.total_frames))

                # ── 1. Central glob flash (first 25 % of life) ───────────────
                if age < 0.25:
                    t_f     = age / 0.25
                    f_alpha = int(210 * math.sin(t_f * math.pi))
                    sz      = max(2, int(tile_px_w * (0.30 - t_f * 0.12)))
                    px_c    = int(cx)
                    py_c    = int(cy)
                    if f_alpha > 8 and 2 <= px_c < self._gal_w - 2 and 2 <= py_c < self._gal_h - 2:
                        renderer.draw_color = (60, 255, 80, f_alpha)
                        renderer.fill_rect((float(px_c - sz), float(py_c - sz),
                                            float(sz * 2), float(sz * 2)))
                        ring_sz = sz + max(1, int(tile_px_w * 0.14))
                        ring_a  = int(f_alpha * 0.45)
                        if ring_a > 5:
                            renderer.draw_color = (30, 200, 50, ring_a)
                            renderer.fill_rect((float(px_c - ring_sz), float(py_c - ring_sz),
                                                float(ring_sz * 2), float(ring_sz * 2)))

                # ── 2. Radiating acid droplets ────────────────────────────────
                # ease-out cubic: droplets shoot out fast then decelerate
                travel_t   = min(1.0, age / 0.65)
                dist_frac  = 1.0 - (1.0 - travel_t) ** 3
                dist_px    = max_dist * dist_frac
                drop_alpha = int(200 * max(0.0, 1.0 - max(0.0, age - 0.60) / 0.40))
                dot_sz     = max(1, int(tile_px_w * 0.08))

                if drop_alpha > 8:
                    for cos_d, sin_d, speed in p.directions:
                        final_dist = dist_px * speed
                        dpx = int(cx + cos_d * final_dist)
                        dpy = int(cy + sin_d * final_dist * aspect)
                        if not (dot_sz <= dpx < self._gal_w - dot_sz and
                                dot_sz <= dpy < self._gal_h - dot_sz):
                            continue
                        renderer.draw_color = (30, 220, 60, drop_alpha)
                        renderer.fill_rect((float(dpx - dot_sz), float(dpy - dot_sz),
                                            float(dot_sz * 2), float(dot_sz * 2)))

                        # Trail dot halfway between center and droplet
                        if dist_frac > 0.15:
                            trail_px = int(cx + cos_d * final_dist * 0.5)
                            trail_py = int(cy + sin_d * final_dist * aspect * 0.5)
                            trail_a  = drop_alpha // 3
                            tsz      = max(1, dot_sz - 1)
                            if (trail_a > 5 and
                                    tsz <= trail_px < self._gal_w - tsz and
                                    tsz <= trail_py < self._gal_h - tsz):
                                renderer.draw_color = (20, 170, 40, trail_a)
                                renderer.fill_rect((float(trail_px - tsz),
                                                    float(trail_py - tsz),
                                                    float(tsz * 2), float(tsz * 2)))

                drew = True
        return drew

    # ------------------------------------------------------------------
    # 5e — Animation pass runner
    # ------------------------------------------------------------------

    def run_gpu_anim_passes(
        self,
        active_engine,
        gw: int,
        gh: int,
        dest_offset_x: int = 0,
        dest_offset_y: int = 0,
    ) -> None:
        """Run all registered GPU animation passes, composited to the game area.

        Bloom pipeline    — clear → draw → Kawase blur → halo + sharp ADD composite.
        No-bloom pipeline — clear → draw → BLEND composite (exact color, no tinting).
        Both are hard-clipped to (0,0,gw,gh) via renderer.clip_rect so no pixel
        can reach the HUD or popup layers.
        """
        if self._gal_src is None:
            return
        import time as _time
        gw, gh = int(gw), int(gh)
        renderer = self.renderer
        bw = max(1, self._gal_w // self._gal_ds)
        bh = max(1, self._gal_h // self._gal_ds)
        _draw_bloom_ms = 0.0
        _draw_nobloom_ms = 0.0

        rebuild_cache = getattr(active_engine, "rebuild_active_animation_cache", None)
        if callable(rebuild_cache):
            rebuild_cache()

        def _apply_lightmap_to_anim_layer() -> None:
            # Reuse the frame's cached lightmap so GPU anims dim with local lighting.
            if self._lightmap_tex is None:
                return
            prev_blend = self._lightmap_tex.blend_mode
            prev_alpha = self._lightmap_tex.alpha_mod
            prev_color = self._lightmap_tex.color_mod
            try:
                self._lightmap_tex.blend_mode = tcod.sdl.render.BlendMode.MOD
                self._lightmap_tex.alpha_mod = 255
                self._lightmap_tex.color_mod = (255, 255, 255)
                renderer.copy(self._lightmap_tex, dest=(0, 0, gw, gh))
            finally:
                self._lightmap_tex.blend_mode = prev_blend
                self._lightmap_tex.alpha_mod = prev_alpha
                self._lightmap_tex.color_mod = prev_color

        # --- Bloom pass ---
        if self.gpu_anim_registry:
            with renderer.set_render_target(self._gal_src):
                renderer.draw_color = (0, 0, 0, 255)
                renderer.clear()

            _draw_bloom_start = _time.perf_counter()
            results = [fn(active_engine) for fn in self.gpu_anim_registry]
            _draw_bloom_ms = max(0.0, (_time.perf_counter() - _draw_bloom_start) * 1000.0)
            if active_engine is not None and hasattr(active_engine, "profile_external_ms"):
                active_engine.profile_external_ms("gpu_anim_draw_bloom", _draw_bloom_ms)

            if any(results):
                with renderer.set_render_target(self._gal_src):
                    _apply_lightmap_to_anim_layer()
                with renderer.set_render_target(self._gal_blur_a):
                    renderer.draw_color = (0, 0, 0, 255)
                    renderer.clear()
                    self._gal_src.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    self._gal_src.alpha_mod  = 255
                    self._gal_src.color_mod  = (255, 255, 255)
                    renderer.copy(self._gal_src, dest=(0, 0, bw, bh))

                src, dst = self._gal_blur_a, self._gal_blur_b
                for i in range(self._ember_bloom_passes):
                    offset = max(1, int((i + 1) * self._ember_bloom_spread))
                    src.blend_mode = tcod.sdl.render.BlendMode.ADD
                    src.alpha_mod  = 51
                    with renderer.set_render_target(dst):
                        renderer.draw_color = (0, 0, 0, 255)
                        renderer.clear()
                        for tap_dx, tap_dy in [(0, 0), (-offset, -offset), (offset, -offset),
                                               (-offset, offset), (offset, offset)]:
                            dx0 = max(0, tap_dx)
                            dy0 = max(0, tap_dy)
                            sx0 = max(0, -tap_dx)
                            sy0 = max(0, -tap_dy)
                            cw = bw - abs(tap_dx)
                            ch = bh - abs(tap_dy)
                            if cw > 0 and ch > 0:
                                renderer.copy(src, source=(sx0, sy0, cw, ch),
                                              dest=(dx0, dy0, cw, ch))
                    src.alpha_mod = 255
                    src, dst = dst, src

                try:
                    renderer.clip_rect = (0, 0, gw, gh)
                    src.blend_mode = tcod.sdl.render.BlendMode.ADD
                    src.alpha_mod  = self._ember_bloom_intensity
                    renderer.copy(src, dest=(int(dest_offset_x), int(dest_offset_y), gw, gh))
                    self._gal_src.blend_mode = tcod.sdl.render.BlendMode.ADD
                    self._gal_src.alpha_mod  = 255
                    self._gal_src.color_mod  = (255, 255, 255)
                    renderer.copy(self._gal_src, dest=(int(dest_offset_x), int(dest_offset_y), gw, gh))
                finally:
                    renderer.clip_rect = None

        # --- No-bloom pass (BLEND composite — exact color, no additive tinting) ---
        if self.gpu_anim_nobloom_registry:
            with renderer.set_render_target(self._gal_src):
                renderer.draw_color = (0, 0, 0, 0)   # transparent clear
                renderer.clear()

            _draw_nobloom_start = _time.perf_counter()
            results = [fn(active_engine) for fn in self.gpu_anim_nobloom_registry]
            _draw_nobloom_ms = max(0.0, (_time.perf_counter() - _draw_nobloom_start) * 1000.0)
            if active_engine is not None and hasattr(active_engine, "profile_external_ms"):
                active_engine.profile_external_ms("gpu_anim_draw_nobloom", _draw_nobloom_ms)

            if any(results):
                with renderer.set_render_target(self._gal_src):
                    _apply_lightmap_to_anim_layer()
                try:
                    renderer.clip_rect = (0, 0, gw, gh)
                    self._gal_src.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    self._gal_src.alpha_mod  = 255
                    self._gal_src.color_mod  = (255, 255, 255)
                    renderer.copy(self._gal_src, dest=(int(dest_offset_x), int(dest_offset_y), gw, gh))
                finally:
                    renderer.clip_rect = None

        if active_engine is not None and hasattr(active_engine, "profile_external_ms"):
            _draw_total_ms = float(_draw_bloom_ms) + float(_draw_nobloom_ms)
            active_engine.profile_external_ms("gpu_anim_draw_total", _draw_total_ms)

    # ------------------------------------------------------------------
    # 5f — Full-scene Kawase bloom
    # ------------------------------------------------------------------

    def load_channel_overlays(self, menu_path: str, game_path: str) -> None:
        """Preload the two channel-splash PNGs.  Call once after the renderer exists."""
        import numpy as _np
        from PIL import Image as _Image
        def _load(path):
            img = _Image.open(path).convert("RGBA")
            px  = _np.array(img, dtype=_np.uint8)
            tex = self.renderer.upload_texture(px)
            tex.blend_mode = tcod.sdl.render.BlendMode.ADD
            h, w = px.shape[:2]
            return tex, w, h
        self._chan_menu_tex, self._chan_menu_w, self._chan_menu_h = _load(menu_path)
        self._chan_game_tex, self._chan_game_w, self._chan_game_h = _load(game_path)

    def start_channel_overlay(self, kind: str) -> None:
        """Trigger the channel overlay.  kind = 'menu' or 'game'."""
        self._chan_overlay_active  = kind
        self._chan_overlay_counter = 0

    def draw_channel_overlay(self, glare_tex=None) -> None:
        """Draw the active channel overlay for one frame; auto-expires after the frame limit."""
        if self._chan_overlay_active is None:
            return
        if self._chan_overlay_counter >= self._chan_overlay_frames:
            self._chan_overlay_active = None
            return
        w = self.window_w
        h = self.window_h
        if self._chan_overlay_active == "menu" and self._chan_menu_tex is not None:
            self.renderer.copy(self._chan_menu_tex,
                               dest=(0, 0, self._chan_menu_w, self._chan_menu_h))
        elif self._chan_game_tex is not None:
            self.renderer.copy(self._chan_game_tex,
                               dest=(0, 0, self._chan_game_w, self._chan_game_h))
        if glare_tex is not None:
            self.renderer.copy(glare_tex, dest=(0, 0, w, h))
        self._chan_overlay_counter += 1

    def apply_barrel_and_ca(self, window_w: int, window_h: int) -> None:
        """Barrel-distort scene_tex → barrel_tex, then apply chromatic aberration → post_crt_tex.

        Equivalent to the two-step inline pipeline previously in main.py.
        """
        renderer = self.renderer

        # Step 1: barrel curvature
        with renderer.set_render_target(self.barrel_tex):
            renderer.draw_color = (0, 0, 0, 255)
            renderer.clear()
            self.scene_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
            self.scene_tex.alpha_mod  = 255
            self.scene_tex.color_mod  = (255, 255, 255)
            self.copy_curved(self.scene_tex, dest=(0, 0, window_w, window_h),
                             src_size=(window_w, window_h))

        # Step 2: chromatic aberration (3-channel pixel shift)
        with renderer.set_render_target(self.post_crt_tex):
            renderer.draw_color = (0, 0, 0, 255)
            renderer.clear()
            if self.crt_ca_on and not self.crt_force_fast_path and self.ca_shift > 0:
                ca = round(self.ca_shift)
                self.barrel_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                self.barrel_tex.alpha_mod  = 255
                self.barrel_tex.color_mod  = (255, 0, 0)
                renderer.copy(self.barrel_tex, dest=(-ca, 0, window_w, window_h))
                self.barrel_tex.color_mod  = (0, 255, 0)
                renderer.copy(self.barrel_tex, dest=(0, 0, window_w, window_h))
                self.barrel_tex.color_mod  = (0, 0, 255)
                renderer.copy(self.barrel_tex, dest=(ca, 0, window_w, window_h))
                self.barrel_tex.color_mod  = (255, 255, 255)
                self.barrel_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
            else:
                self.barrel_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                self.barrel_tex.alpha_mod  = 255
                self.barrel_tex.color_mod  = (255, 255, 255)
                renderer.copy(self.barrel_tex, dest=(0, 0, window_w, window_h))

    def tick_wobble(self, dt: float) -> tuple[int, int]:
        """Advance the VHS wobble timer.  Returns (wx, wy) pixel offsets for this frame."""
        import math as _math
        if not self._wobble_active:
            return 0, 0
        self._wobble_time += dt
        if self._wobble_time >= self._wobble_dur:
            self._wobble_active = False
            self._wobble_time   = 0.0
            return 0, 0
        p = self._wobble_time / self._wobble_dur
        wx = int(_math.exp(-p * self._wobble_decay) * self._wobble_amp
                 * _math.sin(p * _math.pi * self._wobble_freq))
        cos_val = _math.cos(p * _math.pi * self._spring_freq)
        if abs(cos_val) > 1e-6:
            spring = (_math.exp(-p * self._spring_decay)
                      * abs(cos_val) ** self._spring_overshoot)
            if cos_val < 0:
                spring = -spring
        else:
            spring = 0.0
        wy = int(spring * self.window_h * 0.04)
        return wx, wy

    def start_wobble(self) -> None:
        """Kick off the VHS wobble effect (e.g. after CRT power-on)."""
        self._wobble_active = True
        self._wobble_time   = 0.0

    def blit_post_crt(self, wx: int, wy: int) -> None:
        """Composite post_crt_tex onto the default framebuffer with wobble + vroll offsets.

        Also applies the additive oversaturation and warm-white bloom wash
        while the wobble is active, matching the play_on() AGC effect.
        """
        import math as _math
        renderer  = self.renderer
        window_w  = self.window_w
        window_h  = self.window_h
        vroll_off = self._vroll_offset

        # Reset texture state before blitting
        self.post_crt_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
        self.post_crt_tex.alpha_mod  = 255
        self.post_crt_tex.color_mod  = (255, 255, 255)

        if not self.crt_force_fast_path and vroll_off != 0.0:
            vo = int(vroll_off) % window_h
            if vo < 0:
                vo += window_h
            if vo == 0:
                renderer.copy(self.post_crt_tex, dest=(wx, wy, window_w, window_h))
            else:
                bot_h = window_h - vo
                renderer.copy(self.post_crt_tex,
                              source=(0, 0, window_w, bot_h),
                              dest=(wx, vo + wy, window_w, bot_h))
                renderer.copy(self.post_crt_tex,
                              source=(0, bot_h, window_w, vo),
                              dest=(wx, wy, window_w, vo))
        else:
            renderer.copy(self.post_crt_tex, dest=(wx, wy, window_w, window_h))

        # Wobble oversaturation + bloom wash
        if self._wobble_active and self._wobble_time > 0:
            p = self._wobble_time / self._wobble_dur
            oversat_a = max(0, int(_math.exp(-p * self._wobble_oversat_decay)
                                   * self._wobble_oversat_boost))
            if oversat_a > 0:
                self.post_crt_tex.blend_mode = tcod.sdl.render.BlendMode.ADD
                self.post_crt_tex.alpha_mod  = oversat_a
                renderer.copy(self.post_crt_tex, dest=(wx, wy, window_w, window_h))
                self.post_crt_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
                self.post_crt_tex.alpha_mod  = 255
            bloom_a = int(max(0.0, 1.0 - p * self._wobble_bloom_decay)
                          * self._wobble_bloom_alpha)
            if bloom_a > 0:
                ov = self._overlay
                ov.blend_mode = tcod.sdl.render.BlendMode.BLEND
                ov.alpha_mod  = bloom_a
                ov.color_mod  = self._wobble_bloom_color
                renderer.copy(ov, dest=(wx, wy, window_w, window_h))

    def tick_crt_glitches(self, dt: float) -> None:
        """Advance jitter and vertical-roll state for this frame (call once per frame)."""
        # Scanline jitter: random one-band horizontal slip
        if self._jitter_frames > 0:
            self._jitter_frames -= 1
            if self._jitter_frames == 0:
                self._jitter_x = 0
        elif np.random.random() < 0.25 / 30:   # ~0.8% per frame at 30 fps
            self._jitter_x      = int(np.random.choice([-4, -3, -2, 2, 3, 4]))
            self._jitter_y      = int(np.random.randint(4, max(5, self.window_h - 8)))
            self._jitter_band_h = int(np.random.choice([2, 2, 3, 3, 4]))
            self._jitter_frames = int(np.random.randint(1, 3))

        # Vertical roll: slow sync-loss scroll
        self._vroll_elapsed += dt
        if self._vroll_ttl > 0.0:
            self._vroll_offset = (self._vroll_offset + self._vroll_speed * dt) % self.window_h
            self._vroll_ttl   -= dt
            if self._vroll_ttl <= 0.0:
                self._vroll_speed  = 0.0
                self._vroll_offset = 0.0
        elif self._vroll_elapsed >= self._vroll_next:
            self._vroll_speed   = float(np.random.uniform(3.0, 8.0))
            self._vroll_ttl     = float(np.random.uniform(0.4, 1.2))
            self._vroll_elapsed = 0.0
            self._vroll_next    = float(np.random.uniform(30.0, 90.0))

    def draw_scanline_jitter(self) -> None:
        """Draw the current jitter band (if active) on top of the framebuffer."""
        if self._jitter_frames <= 0 or self._jitter_x == 0:
            return
        src_x  = max(-self._jitter_x, 0)
        dst_x  = max( self._jitter_x, 0)
        band_w = self.window_w - abs(self._jitter_x)
        self.renderer.copy(
            self.post_crt_tex,
            source=(src_x, self._jitter_y, band_w, self._jitter_band_h),
            dest  =(dst_x, self._jitter_y, band_w, self._jitter_band_h),
        )

    def apply_crt_overlays(self, w: int, h: int, scanlines_tex=None, scanlines_h: int = 0,
                           scanlines_y_offset: int = 0,
                           vignette_tex=None, glare_tex=None, bloom_source=None,
                           skip_scanlines: bool = False,
                           skip_vignette: bool = False) -> None:
        """Apply the standard CRT overlay stack: scanlines → vignette + glare → bloom.

        Called from the main loop and from CRTSwitchAnimation.play_on() so both
        paths produce identical output.  All textures are optional; pass None to skip.

        skip_scanlines / skip_vignette allow the caller to handle those passes
        externally (e.g. the main loop draws game-layer animations between
        scanlines and vignette, so it calls twice with different skip flags).
        """
        renderer = self.renderer

        # --- Scanlines (MOD) ---
        if not skip_scanlines and self.crt_scanlines_on and scanlines_tex is not None and scanlines_h > 0:
            y = -scanlines_y_offset
            while y < h:
                src_y = 0 if y >= 0 else -y
                dst_y = max(y, 0)
                draw_h = min(scanlines_h - src_y, h - dst_y)
                if draw_h > 0:
                    renderer.copy(scanlines_tex,
                                  source=(0, src_y, 1, draw_h),
                                  dest=(0, dst_y, w, draw_h))
                y += scanlines_h

        # --- Vignette + glare ---
        if not skip_vignette:
            if self.crt_vignette_on and vignette_tex is not None:
                renderer.copy(vignette_tex, dest=(0, 0, w, h))
            if glare_tex is not None:
                renderer.copy(glare_tex, dest=(0, 0, w, h))

        # --- Bloom (ADD) ---
        if self.crt_bloom_on and bloom_source is not None:
            self.gpu_bloom(bloom_source, w, h)

    def gpu_bloom(self, source_tex, window_w: int, window_h: int) -> None:
        """Run a full GPU Kawase bloom pass from source_tex onto the framebuffer.

        source_tex should be the post-CRT image so bloom positions match
        the barrel-distorted pixels exactly.  Zero CPU pixel work.

        Pipeline:
          1. Downsample source → bloom_a  (soft brightness threshold via color_mod)
          2. Ping-pong Kawase blur between bloom_a and bloom_b
          3. ADD-composite final blur onto the default framebuffer
        """
        if source_tex is None or self._bloom_intensity <= 0:
            return
        renderer = self.renderer
        ds = self._bloom_downsample
        bw = max(1, self._bloom_scene_w // ds)
        bh = max(1, self._bloom_scene_h // ds)
        t  = self._bloom_threshold

        tex_a, tex_b = self._bloom_a, self._bloom_b
        with renderer.set_render_target(tex_a):
            renderer.draw_color    = (0, 0, 0, 255)
            renderer.clear()
            source_tex.blend_mode  = tcod.sdl.render.BlendMode.BLEND
            source_tex.alpha_mod   = 255
            source_tex.color_mod   = (t, t, t)
            renderer.copy(source_tex, dest=(0, 0, bw, bh))

        src, dst = tex_a, tex_b
        for i in range(self._bloom_passes):
            offset = max(1, int((i + 1) * self._bloom_spread))
            src.blend_mode = tcod.sdl.render.BlendMode.ADD
            src.alpha_mod  = 51
            with renderer.set_render_target(dst):
                renderer.draw_color = (0, 0, 0, 255)
                renderer.clear()
                for tap_dx, tap_dy in [(0, 0), (-offset, -offset), (offset, -offset),
                                       (-offset, offset), (offset, offset)]:
                    dst_x = max(0, tap_dx)
                    dst_y = max(0, tap_dy)
                    src_x = max(0, -tap_dx)
                    src_y = max(0, -tap_dy)
                    copy_w = bw - abs(tap_dx)
                    copy_h = bh - abs(tap_dy)
                    if copy_w > 0 and copy_h > 0:
                        renderer.copy(src,
                                      source=(src_x, src_y, copy_w, copy_h),
                                      dest=(dst_x, dst_y, copy_w, copy_h))
            src.alpha_mod = 255
            src, dst = dst, src

        src.blend_mode = tcod.sdl.render.BlendMode.ADD
        src.alpha_mod  = self._bloom_intensity
        renderer.copy(src, dest=(0, 0, window_w, window_h))

    # ------------------------------------------------------------------
    # 5g — Lightmap
    # ------------------------------------------------------------------

    def apply_lightmap(
        self,
        active_engine,
        game_dest_w: int,
        game_dest_h: int,
        game_console,
        dest_offset_x: int = 0,
        dest_offset_y: int = 0,
    ) -> None:
        """Blit the per-tile lightmap over the game area (MOD blend).

        Call immediately after game tiles and BEFORE any UI overlays so
        menus and the HUD are never affected.
        """
        if self.crt_force_fast_path or active_engine is None:
            return
        game_map = getattr(active_engine, "game_map", None)
        if game_map is None:
            return
        import time as _time

        def _emit_unified_status_once() -> None:
            if self._unified_gl_status_logged:
                return
            try:
                if not self.enable_modern_gl_lightmap_unified:
                    msg = "UnifiedGL status: disabled by setting"
                else:
                    c = self.modern_gl_lightmap_composer
                    if c is None:
                        msg = "UnifiedGL status: enabled but no composer attached"
                    else:
                        snapshot_fn = getattr(c, "status_snapshot", None)
                        if callable(snapshot_fn):
                            s = snapshot_fn()
                            # Wait until we have meaningful unified-path state.
                            if not bool(s.get("bridge_adopted", False)) and int(s.get("compose_attempts", 0)) == 0:
                                return
                        status_fn = getattr(c, "status_line", None)
                        if callable(status_fn):
                            msg = status_fn()
                        else:
                            msg = "UnifiedGL status: composer attached (no status provider)"
                print("[INFO]: " + msg)
                try:
                    if hasattr(active_engine, "message_log") and active_engine.message_log is not None:
                        active_engine.message_log.add_message(msg)
                except Exception:
                    pass
            finally:
                self._unified_gl_status_logged = True

        def _record_ms(section: str, start_time: float, end_time: float | None = None) -> None:
            if active_engine is None:
                return
            t1 = _time.perf_counter() if end_time is None else end_time
            active_engine.profile_external_ms(section, max(0.0, (t1 - start_time) * 1000.0))

        _t0 = _time.perf_counter()

        if not self.enable_modern_gl_lightmap_unified:
            self._unified_runtime_disabled = False

        self._lightmap_frame_counter += 1
        # Force the shader.py GPU backend here; it will fall back internally
        # if ModernGL is unavailable.
        lighting_engine = self._cached_lighting_engine
        if lighting_engine is None or getattr(lighting_engine, "mode", None) != "gpu":
            import shader as _shader_mod
            lighting_engine = _shader_mod.get_lighting_engine(mode="gpu")
            self._cached_lighting_engine = lighting_engine

        interval = max(1, int(getattr(self, "lightmap_update_interval", 1) or 1))
        can_reuse = self._lightmap_tex is not None and interval > 1
        should_rebuild = (not can_reuse) or (self._lightmap_frame_counter % interval == 0)

        # Unified path hook: render lightmap into shader.py ModernGL target,
        # then let an external composer blend it without CPU readback.
        composer = self.modern_gl_lightmap_composer
        if self.enable_modern_gl_lightmap_unified and not self._unified_runtime_disabled and callable(composer):
            try:
                _t_unified0 = _time.perf_counter()
                prepared = True
                prepare_fn = getattr(composer, "prepare_engine", None)
                if callable(prepare_fn):
                    prepared = bool(prepare_fn(lighting_engine))

                if prepared and lighting_engine.render_lightmap_to_gpu_target(game_map, game_console):
                    composed = bool(composer(
                        lighting_engine=lighting_engine,
                        renderer=self.renderer,
                        dest_offset_x=int(dest_offset_x),
                        dest_offset_y=int(dest_offset_y),
                        game_dest_w=int(game_dest_w),
                        game_dest_h=int(game_dest_h),
                    ))
                    if composed:
                        self._unified_runtime_disabled = False
                        _emit_unified_status_once()
                        return

                # Unified path was requested but could not compose this frame.
                # Disable runtime retries to avoid paying this cost every frame.
                self._unified_runtime_disabled = True
                try:
                    active_engine.profile_external_ms("lightmap_unified_disabled", 1.0)
                    msg = "UnifiedGL runtime auto-disabled after fallback; using SDL lightmap path."
                    print("[INFO]: " + msg)
                except Exception:
                    pass
            except Exception:
                # Fall through to legacy path on any bridge/composer failure.
                self._unified_runtime_disabled = True

        if should_rebuild:
            lm_np = lighting_engine.build_lightmap(game_map, game_console)

            _t_upload0 = _time.perf_counter()
            lm_size = (lm_np.shape[1], lm_np.shape[0])
            if self._lightmap_tex is None or lm_size != self._lightmap_tex_size:
                self._lightmap_tex      = self.renderer.upload_texture(lm_np)
                self._lightmap_tex_size = lm_size
            else:
                self._lightmap_tex.update(lm_np)
            _t_upload1 = _time.perf_counter()
            _record_ms("lightmap_upload", _t_upload0, _t_upload1)
        else:
            _record_ms("lightmap_upload", _t0, _t0)

        if self._lightmap_tex is None:
            return

        _t_blit0 = _time.perf_counter()
        self._lightmap_tex.blend_mode = tcod.sdl.render.BlendMode.MOD
        self.renderer.copy(self._lightmap_tex,
                           dest=(int(dest_offset_x), int(dest_offset_y), int(game_dest_w), int(game_dest_h)))
        _t_blit1 = _time.perf_counter()
        _emit_unified_status_once()
        _record_ms("lightmap_blit", _t_blit0, _t_blit1)

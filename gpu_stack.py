"""gpu_stack.py — All GPU rendering, post-processing, and particle physics.

Sections
--------
  1.  IMPORTS & SHARED UTILITIES
  2.  GPU PARTICLE PHYSICS CLASSES   — DripParticle, SmokeCloudParticle, EmberParticle
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

from PIL import Image


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


# =============================================================================
# SECTION 3 — CRT SETUP HELPERS
# =============================================================================

def generate_scanlines_texture(line_density: float = 3.0, intensity: float = 0.35) -> np.ndarray:
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
        import time, math

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
        print(f"[CRT play_off] loop start")
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
                halo_w = dot_w + DOT_HALO_PAD_W;  halo_h = dot_h + DOT_HALO_PAD_H
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
        import time, math
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
                mid_w = dot_w + int(p * BLOOM_MID_PAD_W);  mid_h = dot_h + int(p * BLOOM_MID_PAD_H)
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

        # Ember/smoke bloom tuning
        self._ember_bloom_passes    = 3
        self._ember_bloom_spread    = 1.4
        self._ember_bloom_intensity = 255

        # ---------------------------------------------------------------
        # 5g — Lightmap
        # ---------------------------------------------------------------
        self._lightmap_tex      = None
        self._lightmap_tex_size = (0, 0)

        # Register the built-in particle passes
        self.gpu_anim_registry.append(self._gpu_ember_render)         # bloom
        self.gpu_anim_registry.append(self._gpu_smoke_render)         # bloom
        self.gpu_anim_nobloom_registry.append(self._gpu_drip_render)  # no-bloom (exact color)

    # ------------------------------------------------------------------
    # Frame dimension update
    # ------------------------------------------------------------------

    def update_frame_dims(self, window_w: int, window_h: int,
                          base_tile_w: float, base_tile_h: float) -> None:
        """Call once per frame before any render methods."""
        self.window_w    = window_w
        self.window_h    = window_h
        self.base_tile_w = base_tile_w
        self.base_tile_h = base_tile_h

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

    def _gpu_ember_render(self, active_engine) -> bool:
        """Draw EmberParticle emission rects into _gal_src (bloom pass)."""
        embers = [a for a in active_engine.animation_queue
                  if isinstance(a, EmberParticle) and a.frames > 0]
        if not embers:
            return False
        tile_px_w = self.base_tile_w * 2.0
        tile_px_h = self.base_tile_h * 2.0
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

    def _gpu_smoke_render(self, active_engine) -> bool:
        """Draw SmokeCloudParticle sprite frames into _gal_src (bloom pass)."""
        smokes = [a for a in active_engine.animation_queue
                  if isinstance(a, SmokeCloudParticle) and a.frames > 0]
        if not smokes:
            return False
        tile_px_w = self.base_tile_w * 2.0
        tile_px_h = self.base_tile_h * 2.0
        renderer  = self.renderer

        # Lazy-load animated smoke sprite sheet
        if self._smoke_tex is None:
            smoke_frames = []
            for i in range(7):
                img = Image.open(
                    self._get_data_path(f"RP/particles/smoke/smoke{i+1}.png")
                ).convert("RGBA")
                smoke_frames.append(np.array(img, dtype=np.uint8))
            self._smoke_tex = renderer.upload_texture(smoke_frames[0])
            self._smoke_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
            self._smoke_frames = smoke_frames

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
                self._smoke_tex.update(
                    self._smoke_frames[frame_index])
                if age < 0.15:
                    smoke_alpha = int(age / 0.15 * 180)
                elif age < 0.70:
                    smoke_alpha = 180
                else:
                    smoke_alpha = int((1.0 - age) / 0.30 * 180)
                self._smoke_tex.alpha_mod = max(0, smoke_alpha)
                renderer.copy(self._smoke_tex,
                              dest=(float(px - 16), float(py - 16), 32.0, 32.0))
                drew = True
        return drew

    def _gpu_drip_render(self, active_engine) -> bool:
        """Draw DripParticle rects into _gal_src (no-bloom, BLEND pass).

        Uses exact drip.color with a late-fade curve so drips stay fully
        opaque for 85% of their lifetime then fade out over the last 15%.
        """
        drips = [a for a in active_engine.animation_queue
                 if isinstance(a, DripParticle) and a.frames > 0]
        if not drips:
            return False
        tile_px_w = self.base_tile_w * 2.0
        tile_px_h = self.base_tile_h * 2.0
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

    # ------------------------------------------------------------------
    # 5e — Animation pass runner
    # ------------------------------------------------------------------

    def run_gpu_anim_passes(self, active_engine, gw: int, gh: int) -> None:
        """Run all registered GPU animation passes, composited to the game area.

        Bloom pipeline    — clear → draw → Kawase blur → halo + sharp ADD composite.
        No-bloom pipeline — clear → draw → BLEND composite (exact color, no tinting).
        Both are hard-clipped to (0,0,gw,gh) via renderer.clip_rect so no pixel
        can reach the HUD or popup layers.
        """
        if self._gal_src is None:
            return
        gw, gh = int(gw), int(gh)
        renderer = self.renderer
        bw = max(1, self._gal_w // self._gal_ds)
        bh = max(1, self._gal_h // self._gal_ds)

        # --- Bloom pass ---
        if self.gpu_anim_registry:
            with renderer.set_render_target(self._gal_src):
                renderer.draw_color = (0, 0, 0, 255)
                renderer.clear()

            results = [fn(active_engine) for fn in self.gpu_anim_registry]
            if any(results):
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
                            dx0 = max(0,  tap_dx);  dy0 = max(0,  tap_dy)
                            sx0 = max(0, -tap_dx);  sy0 = max(0, -tap_dy)
                            cw  = bw - abs(tap_dx); ch  = bh - abs(tap_dy)
                            if cw > 0 and ch > 0:
                                renderer.copy(src, source=(sx0, sy0, cw, ch),
                                              dest=(dx0, dy0, cw, ch))
                    src.alpha_mod = 255
                    src, dst = dst, src

                try:
                    renderer.clip_rect = (0, 0, gw, gh)
                    src.blend_mode = tcod.sdl.render.BlendMode.ADD
                    src.alpha_mod  = self._ember_bloom_intensity
                    renderer.copy(src, dest=(0, 0, gw, gh))
                    self._gal_src.blend_mode = tcod.sdl.render.BlendMode.ADD
                    self._gal_src.alpha_mod  = 255
                    self._gal_src.color_mod  = (255, 255, 255)
                    renderer.copy(self._gal_src, dest=(0, 0, gw, gh))
                finally:
                    renderer.clip_rect = None

        # --- No-bloom pass (BLEND composite — exact color, no additive tinting) ---
        if self.gpu_anim_nobloom_registry:
            with renderer.set_render_target(self._gal_src):
                renderer.draw_color = (0, 0, 0, 0)   # transparent clear
                renderer.clear()

            results = [fn(active_engine) for fn in self.gpu_anim_nobloom_registry]
            if any(results):
                try:
                    renderer.clip_rect = (0, 0, gw, gh)
                    self._gal_src.blend_mode = tcod.sdl.render.BlendMode.BLEND
                    self._gal_src.alpha_mod  = 255
                    self._gal_src.color_mod  = (255, 255, 255)
                    renderer.copy(self._gal_src, dest=(0, 0, gw, gh))
                finally:
                    renderer.clip_rect = None

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
                    dst_x   = max(0, tap_dx);   dst_y   = max(0, tap_dy)
                    src_x   = max(0, -tap_dx);  src_y   = max(0, -tap_dy)
                    copy_w  = bw - abs(tap_dx); copy_h  = bh - abs(tap_dy)
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

    def apply_lightmap(self, active_engine, game_dest_w: int, game_dest_h: int,
                       game_console) -> None:
        """Blit the per-tile lightmap over the game area (MOD blend).

        Call immediately after game tiles and BEFORE any UI overlays so
        menus and the HUD are never affected.
        """
        if self.crt_force_fast_path or active_engine is None:
            return
        game_map = getattr(active_engine, "game_map", None)
        if game_map is None or getattr(game_map, "sunlit", False):
            return
        lm_np   = game_map.build_lightmap(game_console)
        lm_size = (lm_np.shape[1], lm_np.shape[0])
        if self._lightmap_tex is None or lm_size != self._lightmap_tex_size:
            self._lightmap_tex      = self.renderer.upload_texture(lm_np)
            self._lightmap_tex_size = lm_size
        else:
            self._lightmap_tex.update(lm_np)
        self._lightmap_tex.blend_mode = tcod.sdl.render.BlendMode.MOD
        self.renderer.copy(self._lightmap_tex,
                           dest=(0, 0, int(game_dest_w), int(game_dest_h)))

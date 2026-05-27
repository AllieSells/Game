"""Sprite manager: loads extra tiles from RP/extras.png into the tcod tileset.

How to add new overlay sprites:
  1. Open RP/extras.png in your image editor.
  2. Draw your sprite in a 10x10 pixel cell.
     The grid is 16 columns wide. Tiles are read left-to-right, top-to-bottom.
     Row 0, Col 0  = slot 0  -> codepoint 0xE000 -> tile_ids.EXTRAS[0]
     Row 0, Col 1  = slot 1  -> codepoint 0xE001 -> tile_ids.EXTRAS[1]
     ... and so on.
  3. Add a named constant to tile_ids.py:
       VINE   = chr(0xE000)
       BLOOD  = chr(0xE001)
  4. Use it anywhere: console.print(x, y, tile_ids.VINE, fg=(34,139,34))
"""
from __future__ import annotations
import os
import numpy as np

# Import shader for dirty tracking (lazy import to avoid circular deps)
_shader_module = None


def _get_shader():
    """Lazy import shader module to notify of sprite changes."""
    global _shader_module
    if _shader_module is None:
        try:
            import shader
            _shader_module = shader
        except ImportError:
            pass
    return _shader_module

TILE_W = 32
TILE_H = 32
EXTRAS_COLS = 16  # Width of extras.png grid in tiles
EXTRAS_START_CP = 0xE000  # First Unicode Private Use Area codepoint
_SPRITE_CP_MIN = 0xE000
_SPRITE_CP_MAX = 0xF8FF

# --- Composite sprite state ---
COMPOSITE_START_CP = 0xEF00  # Start of composite region
_composite_cache: dict = {}   # full key -> assigned codepoint int
_composite_next: int = COMPOSITE_START_CP
_composite_free_list: list = []  # Recycled slots for permanent composites
_entity_tile_free_list: list = []  # Recycled slots for per-frame entity-on-tile composites
_tileset = None               # Set by load_extras; used by compose/refresh

# Per-position puddle slot registry.
# Guarantees at most ONE tileset slot per world tile for the puddle sprite,
# and ONE for the tile+puddle composite, regardless of how many times depth
# or neighbour pattern changes.  Slots are updated in-place instead of
# allocating a new codepoint on every evaporation tick.
_puddle_pos_slot: dict = {}       # (tile_x, tile_y) -> puddle codepoint int
_tile_puddle_pos_slot: dict = {}  # (tile_x, tile_y) -> tile+puddle composite codepoint int

# --- Deferred set_tile queue (used during background gen to avoid GPU calls) ---
_deferred_mode: bool = False
_deferred_tiles: list = []       # List of (cp, pixels_uint8) to flush on main thread
_deferred_pixel_store: dict = {} # cp -> pixels_uint8: CPU-side store so get_tile works during deferred mode

# --- Normal-map state ---
# Explicit average normals loaded from extras normal sheet, keyed by codepoint.
_avg_normal_by_cp: dict[int, tuple[float, float, float]] = {}
# Cache of lazily-derived average normals from albedo when no explicit normal exists.
_derived_avg_normal_cache: dict[int, tuple[float, float, float]] = {}
# Per-codepoint per-pixel normal field cache:
#   value = (normals_f32[H,W,3], alpha_f32[H,W])
_normal_field_by_cp: dict[int, tuple[np.ndarray, np.ndarray]] = {}
# Per-codepoint albedo alpha mask cache used for lighting coverage.
_albedo_alpha_by_cp: dict[int, np.ndarray] = {}

# --- Emissive and Specular material state ---
# Per-codepoint emissive RGB data: value = emissive_f32[H,W,3]
_emissive_by_cp: dict[int, np.ndarray] = {}
# Per-codepoint specular RGB data: value = specular_f32[H,W,3]
_specular_by_cp: dict[int, np.ndarray] = {}
# Per-codepoint normal detail mask: value = detail_f32[H,W]
_normal_detail_by_cp: dict[int, np.ndarray] = {}
# Per-codepoint specular mask: value = mask_f32[H,W]
_specular_mask_by_cp: dict[int, np.ndarray] = {}
# Per-codepoint emissive light overrides: keys are any subset of
# {radius, intensity, min_luma, tinted, enabled}. Absent keys fall back to
# the global LightingShaderConfig values.
_emissive_light_config_by_cp: dict[int, dict] = {}


def set_emissive_light_config(cp: int, **kwargs) -> None:
    """Set per-codepoint emissive light overrides.

    Supported keys: radius (float), intensity (float), min_luma (float),
    tinted (bool), enabled (bool).  Call with no kwargs to clear overrides.

    Example — make torch rune cast a warm wide glow:
        set_emissive_light_config(tile_ids.TORCH_RUNE, radius=3.0, intensity=0.8)
    Example — disable light emission for a purely decorative glow:
        set_emissive_light_config(tile_ids.DECO_GLOW, enabled=False)
    """
    cp_i = int(cp)
    if kwargs:
        _emissive_light_config_by_cp[cp_i] = dict(kwargs)
    else:
        _emissive_light_config_by_cp.pop(cp_i, None)


def _normalize_vec3(x: float, y: float, z: float) -> tuple[float, float, float]:
    mag = float(np.sqrt(x * x + y * y + z * z))
    if mag <= 1e-6:
        return (0.0, 0.0, 1.0)
    inv = 1.0 / mag
    return (x * inv, y * inv, z * inv)


def _derive_avg_normal_from_pixels(tile_pixels: np.ndarray) -> tuple[float, float, float]:
    """Estimate one average normal from RGBA pixels when no authored normal is available."""
    try:
        rgba = tile_pixels.astype(np.float32) / 255.0
        alpha = rgba[..., 3]
        if float(np.max(alpha)) <= 1e-4:
            return (0.0, 0.0, 1.0)

        rgb = rgba[..., :3]
        luma = rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
        # Blend alpha and luma so fully opaque glyphs still produce some shape.
        height = np.clip(alpha * 0.7 + luma * 0.3, 0.0, 1.0)

        # Simple Sobel-like gradient using shifts.
        gx = (
            np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)
            + 0.5 * (np.roll(np.roll(height, -1, axis=0), -1, axis=1) - np.roll(np.roll(height, -1, axis=0), 1, axis=1))
            + 0.5 * (np.roll(np.roll(height, 1, axis=0), -1, axis=1) - np.roll(np.roll(height, 1, axis=0), 1, axis=1))
        )
        gy = (
            np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)
            + 0.5 * (np.roll(np.roll(height, -1, axis=0), -1, axis=1) - np.roll(np.roll(height, 1, axis=0), -1, axis=1))
            + 0.5 * (np.roll(np.roll(height, -1, axis=0), 1, axis=1) - np.roll(np.roll(height, 1, axis=0), 1, axis=1))
        )

        strength = 2.2
        nx = -gx * strength
        ny = -gy * strength
        nz = np.ones_like(nx)

        mag = np.sqrt(nx * nx + ny * ny + nz * nz)
        mag = np.where(mag > 1e-6, mag, 1.0)
        nx = nx / mag
        ny = ny / mag
        nz = nz / mag

        w = np.clip(alpha, 0.0, 1.0)
        wsum = float(np.sum(w))
        if wsum <= 1e-6:
            return (0.0, 0.0, 1.0)

        ax = float(np.sum(nx * w) / wsum)
        ay = float(np.sum(ny * w) / wsum)
        az = float(np.sum(nz * w) / wsum)
        return _normalize_vec3(ax, ay, az)
    except Exception:
        return (0.0, 0.0, 1.0)


def _derive_normal_field_from_pixels(tile_pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Estimate per-pixel normals from RGBA pixels (fallback for missing authored normals)."""
    rgba = tile_pixels.astype(np.float32) / 255.0
    alpha = np.clip(rgba[..., 3], 0.0, 1.0)
    rgb = rgba[..., :3]
    luma = rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
    height = np.clip(alpha * 0.7 + luma * 0.3, 0.0, 1.0)

    gx = (
        np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)
        + 0.5 * (np.roll(np.roll(height, -1, axis=0), -1, axis=1) - np.roll(np.roll(height, -1, axis=0), 1, axis=1))
        + 0.5 * (np.roll(np.roll(height, 1, axis=0), -1, axis=1) - np.roll(np.roll(height, 1, axis=0), 1, axis=1))
    )
    gy = (
        np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)
        + 0.5 * (np.roll(np.roll(height, -1, axis=0), -1, axis=1) - np.roll(np.roll(height, 1, axis=0), -1, axis=1))
        + 0.5 * (np.roll(np.roll(height, -1, axis=0), 1, axis=1) - np.roll(np.roll(height, 1, axis=0), 1, axis=1))
    )

    strength = 2.2
    nx = -gx * strength
    ny = -gy * strength
    nz = np.ones_like(nx, dtype=np.float32)
    mag = np.sqrt(nx * nx + ny * ny + nz * nz)
    mag = np.where(mag > 1e-6, mag, 1.0)

    normals = np.empty((tile_pixels.shape[0], tile_pixels.shape[1], 3), dtype=np.float32)
    normals[..., 0] = nx / mag
    normals[..., 1] = ny / mag
    normals[..., 2] = nz / mag
    return normals, alpha.astype(np.float32)


def _decode_normal_field_from_normal_pixels(normal_pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Decode authored tangent-space normal RGBA into normalized XYZ + alpha."""
    n = normal_pixels.astype(np.float32) / 255.0
    nx = n[..., 0] * 2.0 - 1.0
    ny = n[..., 1] * 2.0 - 1.0
    nz = n[..., 2] * 2.0 - 1.0
    mag = np.sqrt(nx * nx + ny * ny + nz * nz)
    mag = np.where(mag > 1e-6, mag, 1.0)

    normals = np.empty((normal_pixels.shape[0], normal_pixels.shape[1], 3), dtype=np.float32)
    normals[..., 0] = nx / mag
    normals[..., 1] = ny / mag
    normals[..., 2] = nz / mag
    alpha = np.clip(n[..., 3], 0.0, 1.0).astype(np.float32)
    return normals, alpha


def _register_normal_field(cp: int, normals: np.ndarray, alpha: np.ndarray) -> None:
    _normal_field_by_cp[int(cp)] = (normals.astype(np.float32), alpha.astype(np.float32))


def _register_albedo_alpha(cp: int, tile_pixels: np.ndarray) -> None:
    _albedo_alpha_by_cp[int(cp)] = np.clip(tile_pixels[..., 3].astype(np.float32) / 255.0, 0.0, 1.0)


def _decode_emissive_from_pixels(emissive_pixels: np.ndarray) -> np.ndarray:
    """Decode emissive RGB data from RGBA pixels."""
    e = emissive_pixels.astype(np.float32) / 255.0
    return np.clip(e[..., :3], 0.0, 1.0)


def _register_emissive(cp: int, emissive_pixels: np.ndarray) -> None:
    """Register emissive data for a codepoint."""
    emissive_data = _decode_emissive_from_pixels(emissive_pixels)
    # Only register if there's actual emission (not pure black)
    if np.any(emissive_data > 1e-4):
        _emissive_by_cp[int(cp)] = emissive_data


def _decode_specular_from_pixels(specular_pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decode specular RGB, normal detail (from alpha), and specular mask.
    
    Returns:
        - specular RGB (H, W, 3): The specular color/tint
        - normal_detail (H, W): Binary mask from alpha channel (detail flag)
        - specular_mask (H, W): Luminance-based specular strength mask
    """
    s = specular_pixels.astype(np.float32) / 255.0
    specular_rgb = np.clip(s[..., :3], 0.0, 1.0)
    
    # Use alpha channel as normal detail flag (>0.5 = has detail)
    normal_detail = np.clip(s[..., 3], 0.0, 1.0)
    
    # Compute specular mask from luminance of RGB
    specular_mask = np.clip(
        specular_rgb[..., 0] * 0.299 + 
        specular_rgb[..., 1] * 0.587 + 
        specular_rgb[..., 2] * 0.114,
        0.0, 1.0
    )
    
    return specular_rgb, normal_detail, specular_mask


def _register_specular(cp: int, specular_pixels: np.ndarray) -> None:
    """Register specular data for a codepoint."""
    specular_rgb, normal_detail, specular_mask = _decode_specular_from_pixels(specular_pixels)
    _specular_by_cp[int(cp)] = specular_rgb
    _normal_detail_by_cp[int(cp)] = normal_detail
    _specular_mask_by_cp[int(cp)] = specular_mask


def get_albedo_alpha_mask(cp: int) -> np.ndarray:
    """Return per-pixel sprite alpha mask from the glyph albedo tile."""
    cp_i = int(cp)
    cached = _albedo_alpha_by_cp.get(cp_i)
    if cached is not None:
        return cached
    try:
        tile = _get_tile(cp_i)
        alpha = np.clip(tile[..., 3].astype(np.float32) / 255.0, 0.0, 1.0)
    except Exception:
        alpha = np.ones((TILE_H, TILE_W), dtype=np.float32)
    _albedo_alpha_by_cp[cp_i] = alpha
    return alpha


def get_normal_field(cp: int) -> tuple[np.ndarray, np.ndarray]:
    """Return per-pixel normal field (XYZ) and alpha mask for a codepoint."""
    cp_i = int(cp)
    cached = _normal_field_by_cp.get(cp_i)
    if cached is not None:
        return cached
    try:
        derived = _derive_normal_field_from_pixels(_get_tile(cp_i))
    except Exception:
        # Last-resort flat normal.
        tile = _get_tile(cp_i)
        h, w = tile.shape[:2]
        normals = np.zeros((h, w, 3), dtype=np.float32)
        normals[..., 2] = 1.0
        alpha = np.ones((h, w), dtype=np.float32)
        derived = (normals, alpha)
    _normal_field_by_cp[cp_i] = derived
    return derived


def get_packed_material(cp: int, scale: int = 1, out_h: int | None = None, out_w: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return all material channels for a codepoint, resized to exact output dimensions.
    
    Args:
        cp: The codepoint to fetch materials for
        scale: Downsampling factor (1 = full resolution, 2 = half, etc.)
        out_h: Exact output height in pixels (overrides scale calculation)
        out_w: Exact output width in pixels (overrides scale calculation)
    
    Returns:
        Tuple of 6 numpy arrays (all float32):
        - normals (H, W, 3): XYZ tangent-space normals
        - alpha (H, W): Opacity mask
        - emission (H, W, 3): RGB emissive glow
        - specular (H, W, 3): RGB specular tint
        - normal_detail (H, W): Normal detail flag mask
        - specular_mask (H, W): Specular strength mask
    """
    cp_i = int(cp)
    scale = max(1, int(scale))
    
    # Get base normal and alpha
    normals, alpha = get_normal_field(cp_i)
    
    # Get emissive (default to black if not available)
    emission = _emissive_by_cp.get(cp_i)
    if emission is None:
        h, w = normals.shape[:2]
        emission = np.zeros((h, w, 3), dtype=np.float32)
    else:
        # Debug: Check if we're returning non-zero emission
        max_e = float(np.max(emission))
        if max_e > 0.01 and cp_i < 0xE010:  # First few tiles only
            print(f"[DEBUG] get_packed_material cp 0x{cp_i:04X} returning emission max={max_e:.4f}")
    
    # Get specular data (default to zeros if not available)
    specular = _specular_by_cp.get(cp_i)
    normal_detail = _normal_detail_by_cp.get(cp_i)
    specular_mask = _specular_mask_by_cp.get(cp_i)
    
    if specular is None:
        h, w = normals.shape[:2]
        specular = np.zeros((h, w, 3), dtype=np.float32)
        normal_detail = np.zeros((h, w), dtype=np.float32)
        specular_mask = np.zeros((h, w), dtype=np.float32)
    
    # Determine target dimensions
    if out_h is not None and out_w is not None:
        new_h = max(1, int(out_h))
        new_w = max(1, int(out_w))
    else:
        h, w = normals.shape[:2]
        new_h = max(1, h // scale)
        new_w = max(1, w // scale)
    
    # Resize if needed
    h, w = normals.shape[:2]
    if h != new_h or w != new_w:
        # Downsample using simple indexing (nearest neighbor for speed)
        y_idx = np.minimum((np.arange(new_h, dtype=np.int32) * h) // max(1, new_h), h - 1)
        x_idx = np.minimum((np.arange(new_w, dtype=np.int32) * w) // max(1, new_w), w - 1)
        
        normals = normals[y_idx[:, None], x_idx[None, :], :]
        alpha = alpha[y_idx[:, None], x_idx[None, :]]
        emission = emission[y_idx[:, None], x_idx[None, :], :]
        specular = specular[y_idx[:, None], x_idx[None, :], :]
        normal_detail = normal_detail[y_idx[:, None], x_idx[None, :]]
        specular_mask = specular_mask[y_idx[:, None], x_idx[None, :]]
    
    return normals, alpha, emission, specular, normal_detail, specular_mask


def _register_avg_normal_from_normal_pixels(cp: int, normal_pixels: np.ndarray) -> None:
    """Decode authored tangent-space normal pixels and store their average vector."""
    try:
        normals, alpha = _decode_normal_field_from_normal_pixels(normal_pixels)
        nx = normals[..., 0]
        ny = normals[..., 1]
        nz = normals[..., 2]
        w = np.clip(alpha, 0.0, 1.0)
        wsum = float(np.sum(w))
        if wsum <= 1e-6:
            _avg_normal_by_cp[cp] = (0.0, 0.0, 1.0)
            _register_normal_field(cp, normals, alpha)
        else:
            ax = float(np.sum(nx * w) / wsum)
            ay = float(np.sum(ny * w) / wsum)
            az = float(np.sum(nz * w) / wsum)
            _avg_normal_by_cp[cp] = _normalize_vec3(ax, ay, az)
            _register_normal_field(cp, normals, alpha)
        _derived_avg_normal_cache.pop(cp, None)
    except Exception:
        _avg_normal_by_cp[cp] = (0.0, 0.0, 1.0)
        _derived_avg_normal_cache.pop(cp, None)


def _register_flat_normals(cp: int, tile_pixels: np.ndarray) -> None:
    """Register flat normals (0, 0, 1) for liquid surfaces / flat sprites.
    
    Use this for puddles, liquid splashes, and other flat surfaces that should
    not have derived height-based normals.
    """
    h, w = tile_pixels.shape[:2]
    alpha = np.clip(tile_pixels[..., 3].astype(np.float32) / 255.0, 0.0, 1.0)
    normals = np.zeros((h, w, 3), dtype=np.float32)
    normals[..., 2] = 1.0  # Flat normal pointing straight up
    _avg_normal_by_cp[cp] = (0.0, 0.0, 1.0)
    _register_normal_field(cp, normals, alpha)
    _derived_avg_normal_cache.pop(cp, None)


def _register_avg_normal_from_albedo_pixels(cp: int, tile_pixels: np.ndarray) -> None:
    normals, alpha = _derive_normal_field_from_pixels(tile_pixels)
    w = np.clip(alpha, 0.0, 1.0)
    wsum = float(np.sum(w))
    if wsum <= 1e-6:
        avg = (0.0, 0.0, 1.0)
    else:
        ax = float(np.sum(normals[..., 0] * w) / wsum)
        ay = float(np.sum(normals[..., 1] * w) / wsum)
        az = float(np.sum(normals[..., 2] * w) / wsum)
        avg = _normalize_vec3(ax, ay, az)
    _avg_normal_by_cp[cp] = avg
    _register_normal_field(cp, normals, alpha)
    _derived_avg_normal_cache.pop(cp, None)


def get_average_normal(cp: int) -> tuple[float, float, float]:
    """Return average normal vector for a glyph codepoint.

    Prefers authored normals loaded from RP/extras_normals.png. Falls back to
    a cheap albedo-derived estimate for codepoints without authored normals.
    """
    cp_i = int(cp)
    authored = _avg_normal_by_cp.get(cp_i)
    if authored is not None:
        return authored

    cached = _derived_avg_normal_cache.get(cp_i)
    if cached is not None:
        return cached

    try:
        derived = _derive_avg_normal_from_pixels(_get_tile(cp_i))
    except Exception:
        derived = (0.0, 0.0, 1.0)
    _derived_avg_normal_cache[cp_i] = derived
    return derived


def set_deferred_mode(enabled: bool) -> None:
    """Enable/disable deferred GPU tile uploads. Call set_deferred_mode(True) before
    running world gen on a background thread, then flush_deferred_tiles() afterwards
    on the main thread to safely apply all set_tile calls."""
    global _deferred_mode
    _deferred_mode = enabled
    # Do NOT clear _deferred_tiles here — flush_deferred_tiles() owns that.
    # When disabling, only drop the CPU-side lookup store (no longer needed).
    if not enabled:
        _deferred_pixel_store.clear()


def flush_deferred_tiles() -> None:
    """Apply all queued set_tile calls. Must be called from the main (SDL) thread."""
    global _deferred_tiles, _deferred_pixel_store
    if _tileset is None:
        _deferred_tiles.clear()
        _deferred_pixel_store.clear()
        return
    for cp, pixels in _deferred_tiles:
        _tileset.set_tile(cp, pixels)
    _deferred_tiles.clear()
    _deferred_pixel_store.clear()


def get_loaded_tileset():
    """Return the tileset currently loaded into sprite_manager, if any."""
    return _tileset


def get_loaded_tile_size() -> tuple[int, int]:
    """Return the active tileset tile size as (width, height)."""
    if _tileset is not None:
        return int(_tileset.tile_width), int(_tileset.tile_height)
    return TILE_W, TILE_H


def reset_sprite_cache() -> None:
    """Clear all runtime sprite cache state and reset composite allocation."""
    global _composite_next, _composite_cache, _composite_free_list, _entity_tile_free_list
    global _puddle_pos_slot, _tile_puddle_pos_slot, _puddle_sprite_cache
    global _entity_tile_cache, _entity_tile_prev_slots
    global _avg_normal_by_cp, _derived_avg_normal_cache, _normal_field_by_cp, _albedo_alpha_by_cp
    global _emissive_by_cp, _specular_by_cp, _normal_detail_by_cp, _specular_mask_by_cp

    _composite_cache.clear()
    _composite_free_list.clear()
    _entity_tile_free_list.clear()
    _puddle_pos_slot.clear()
    _tile_puddle_pos_slot.clear()
    _puddle_sprite_cache.clear()
    _entity_tile_cache.clear()
    _entity_tile_prev_slots.clear()
    _deferred_tiles.clear()
    _deferred_pixel_store.clear()
    # Only clear derived/composite data — material dicts loaded from disk by load_extras
    # (_emissive_by_cp, _specular_by_cp, _normal_field_by_cp, etc.) are NOT cleared here
    # because reset_sprite_cache is called after load_extras and would wipe tileset data.
    _avg_normal_by_cp.clear()
    _derived_avg_normal_cache.clear()
    _normal_field_by_cp.clear()
    _albedo_alpha_by_cp.clear()
    # Purge composite-range entries from emissive/specular dicts (runtime-generated).
    # Base tile entries (loaded by load_extras) are preserved — reset_sprite_cache is
    # called after load_extras and must not wipe tileset material data.
    for _cp in range(COMPOSITE_START_CP, _composite_next):
        _emissive_by_cp.pop(_cp, None)
        _specular_by_cp.pop(_cp, None)
        _normal_detail_by_cp.pop(_cp, None)
        _specular_mask_by_cp.pop(_cp, None)
    _composite_next = COMPOSITE_START_CP


def invalidate_cache(cp: int) -> None:
    """Invalidate all cached material data for a specific codepoint.
    
    Use this when reloading materials (normals, emissive, specular) to ensure
    stale cached data is cleared before new data is loaded.
    """
    cp_i = int(cp)
    _normal_field_by_cp.pop(cp_i, None)
    _albedo_alpha_by_cp.pop(cp_i, None)
    _avg_normal_by_cp.pop(cp_i, None)
    _derived_avg_normal_cache.pop(cp_i, None)
    _emissive_by_cp.pop(cp_i, None)
    _specular_by_cp.pop(cp_i, None)
    _normal_detail_by_cp.pop(cp_i, None)
    _specular_mask_by_cp.pop(cp_i, None)


def _release_composite_slot(cp: int) -> None:
    """Return a composite codepoint to the free pool and clear its cached material data.

    Must be used instead of a bare ``_composite_free_list.append(cp)`` whenever
    a slot is being freed, so that any subsequent re-user of the same codepoint
    does not inherit stale normal/albedo data from the previous owner.
    """
    _composite_free_list.append(cp)
    _normal_field_by_cp.pop(cp, None)
    _albedo_alpha_by_cp.pop(cp, None)
    _avg_normal_by_cp.pop(cp, None)
    _derived_avg_normal_cache.pop(cp, None)
    _emissive_by_cp.pop(cp, None)
    _specular_by_cp.pop(cp, None)
    _normal_detail_by_cp.pop(cp, None)
    _specular_mask_by_cp.pop(cp, None)


def _get_tile(cp: int) -> np.ndarray:
    """Get tile pixels, checking CPU-side deferred store before the GPU tileset."""
    if _deferred_mode and cp in _deferred_pixel_store:
        return _deferred_pixel_store[cp].copy()
    return _tileset.get_tile(cp)


def _offset_overlay_tile(tile_pixels: np.ndarray, x_offset: int, y_offset: int) -> np.ndarray:
    """Shift an overlay tile by the given pixel offsets, filling empty space with transparency."""
    if x_offset == 0 and y_offset == 0:
        return tile_pixels

    height, width = tile_pixels.shape[:2]
    canvas = np.zeros_like(tile_pixels)

    src_x0 = max(0, -x_offset)
    src_x1 = min(width, width - x_offset)
    src_y0 = max(0, -y_offset)
    src_y1 = min(height, height - y_offset)

    dest_x0 = max(0, x_offset)
    dest_x1 = min(width, width + x_offset)
    dest_y0 = max(0, y_offset)
    dest_y1 = min(height, height + y_offset)

    copy_width = dest_x1 - dest_x0
    copy_height = dest_y1 - dest_y0
    if copy_width <= 0 or copy_height <= 0:
        return canvas

    canvas[dest_y0:dest_y1, dest_x0:dest_x1, :] = tile_pixels[src_y0:src_y1, src_x0:src_x1, :]
    return canvas


def _crop_overlay_tile(tile_pixels: np.ndarray, x_crop: int, y_crop: int) -> np.ndarray:
    """Crop an overlay tile by the given pixel amounts on each side, filling empty space with transparency."""
    if x_crop == 0 and y_crop == 0:
        return tile_pixels

    height, width = tile_pixels.shape[:2]
    canvas = np.zeros_like(tile_pixels)

    # x_crop > 0 removes right columns, x_crop < 0 removes left columns.
    if x_crop >= 0:
        src_x0 = 0
        src_x1 = max(0, width - x_crop)
    else:
        src_x0 = min(width, -x_crop)
        src_x1 = width

    # y_crop > 0 removes bottom rows, y_crop < 0 removes top rows.
    if y_crop >= 0:
        src_y0 = 0
        src_y1 = max(0, height - y_crop)
    else:
        src_y0 = min(height, -y_crop)
        src_y1 = height

    dest_x0 = 0
    dest_x1 = src_x1 - src_x0
    dest_y0 = 0
    dest_y1 = src_y1 - src_y0

    copy_width = dest_x1 - dest_x0
    copy_height = dest_y1 - dest_y0
    if copy_width <= 0 or copy_height <= 0:
        return canvas

    canvas[dest_y0:dest_y1, dest_x0:dest_x1, :] = tile_pixels[src_y0:src_y1, src_x0:src_x1, :]
    return canvas

def _scale_overlay_tile(tile_pixels: np.ndarray, scale: float) -> np.ndarray:
    """Compress an overlay tile vertically and anchor it to the bottom of the cell."""
    if scale == 1.0:
        return tile_pixels

    height, width = tile_pixels.shape[:2]
    scaled_height = max(1, int(round(height * scale)))

    src_y = np.minimum((np.arange(scaled_height) / scale).astype(int), height - 1)
    resized = tile_pixels[src_y, :, :]

    canvas = np.zeros_like(tile_pixels)

    dest_y0 = height - scaled_height
    dest_y1 = dest_y0 + scaled_height
    src_y0 = 0

    if dest_y0 < 0:
        src_y0 = -dest_y0
        dest_y0 = 0

    dest_y1 = min(height, dest_y1)

    copy_height = dest_y1 - dest_y0
    if copy_height <= 0:
        return canvas

    canvas[dest_y0:dest_y1, :, :] = resized[
        src_y0:src_y0 + copy_height,
        :,
        :,
    ]
    return canvas


def load_extras(tileset, path: str = "RP/extras.png", normals_path: str | None = None, emissive_path: str | None = None, specular_path: str | None = None) -> int:
    """Load every tile from the extras sheet into the tileset.

    Returns the number of tiles registered.
    Silently skips if the file doesn't exist yet.
    
    NOTE: This function invalidates cached normals/materials for the codepoint
    range being reloaded to ensure updated normal maps are properly loaded.
    """
    if not os.path.exists(path):
        return 0

    try:
        from PIL import Image
    except ImportError:
        print("[sprite_manager] Pillow not installed — extras sheet skipped.")
        return 0

    img = Image.open(path).convert("RGBA")
    img_w, img_h = img.size
    cols = img_w // TILE_W
    rows = img_h // TILE_H

    # Auto-detect material map paths if not provided
    root, ext = os.path.splitext(path)
    if normals_path is None:
        normals_path = f"{root}_normals{ext}"
    if emissive_path is None:
        emissive_path = f"{root}_emissive{ext}"
    if specular_path is None:
        specular_path = f"{root}_specular{ext}"
    
    # IMPORTANT: Clear cached materials for codepoints we're about to reload
    # This ensures updated normal/emissive/specular maps are properly loaded
    total_tiles = rows * cols
    for i in range(total_tiles):
        cp = EXTRAS_START_CP + i
        invalidate_cache(cp)
    
    print(f"[sprite_manager] Cleared material cache for {total_tiles} codepoints before reload.")

    # Load normal map
    normal_img = None
    if normals_path and os.path.exists(normals_path):
        try:
            normal_img = Image.open(normals_path).convert("RGBA")
        except Exception:
            normal_img = None

    # Load emissive map
    emissive_img = None
    if emissive_path and os.path.exists(emissive_path):
        try:
            emissive_img = Image.open(emissive_path).convert("RGBA")
        except Exception:
            emissive_img = None

    # Load specular map
    specular_img = None
    if specular_path and os.path.exists(specular_path):
        try:
            specular_img = Image.open(specular_path).convert("RGBA")
        except Exception:
            specular_img = None

    ncols = cols
    nrows = rows
    if normal_img is not None:
        nimg_w, nimg_h = normal_img.size
        ncols = nimg_w // TILE_W
        nrows = nimg_h // TILE_H

    ecols = cols
    erows = rows
    if emissive_img is not None:
        eimg_w, eimg_h = emissive_img.size
        ecols = eimg_w // TILE_W
        erows = eimg_h // TILE_H

    scols = cols
    srows = rows
    if specular_img is not None:
        simg_w, simg_h = specular_img.size
        scols = simg_w // TILE_W
        srows = simg_h // TILE_H

    count = 0
    for row in range(rows):
        for col in range(cols):
            left   = col * TILE_W
            top    = row * TILE_H
            right  = left + TILE_W
            bottom = top  + TILE_H
            
            # Load albedo/base texture
            tile_pixels = np.array(img.crop((left, top, right, bottom)), dtype=np.uint8)
            cp = EXTRAS_START_CP + count
            tileset.set_tile(cp, tile_pixels)
            _register_albedo_alpha(cp, tile_pixels)
            
            # Load normals
            if normal_img is not None and row < nrows and col < ncols:
                normal_pixels = np.array(normal_img.crop((left, top, right, bottom)), dtype=np.uint8)
                _register_avg_normal_from_normal_pixels(cp, normal_pixels)
            else:
                _register_avg_normal_from_albedo_pixels(cp, tile_pixels)
            
            # Load emissive
            if emissive_img is not None and row < erows and col < ecols:
                emissive_pixels = np.array(emissive_img.crop((left, top, right, bottom)), dtype=np.uint8)
                _register_emissive(cp, emissive_pixels)
                # Debug: Check first tile
                if count == 0:
                    min_val = np.min(emissive_pixels[..., :3])
                    max_val = np.max(emissive_pixels[..., :3])
                    #print(f"[DEBUG] First emissive tile (cp 0x{cp:04X}): RGB range [{min_val}, {max_val}]")
            
            # Load specular
            if specular_img is not None and row < srows and col < scols:
                specular_pixels = np.array(specular_img.crop((left, top, right, bottom)), dtype=np.uint8)
                _register_specular(cp, specular_pixels)
            
            count += 1
    
    global _tileset
    _tileset = tileset  # store for use by compose_sprite / refresh_actor_sprite
    
    # Build status message
    materials_loaded = []
    if normal_img is not None:
        materials_loaded.append(f"normals='{normals_path}'")
    if emissive_img is not None:
        materials_loaded.append(f"emissive='{emissive_path}'")
    if specular_img is not None:
        materials_loaded.append(f"specular='{specular_path}'")
    
    if materials_loaded:
        materials_str = ", ".join(materials_loaded)
        print(f"[sprite_manager] Loaded {count} extras from '{path}' with {materials_str} (0xE000 – 0x{EXTRAS_START_CP + count - 1:04X}).")
    else:
        print(f"[sprite_manager] Loaded {count} extras from '{path}' (no material maps found, using derived normals).")
    
    return count


def reload_materials(tileset, path: str = "RP/extras.png", normals_path: str | None = None, emissive_path: str | None = None, specular_path: str | None = None) -> int:
    """Force reload all materials from the extras sheet.
    
    This is a convenience wrapper around load_extras() that explicitly clears all
    caches before reloading. Use this when normal maps, emissive maps, or specular
    maps have been moved or updated and you need to ensure the new versions are loaded.
    
    Returns the number of tiles reloaded.
    """
    print("[sprite_manager] Force reloading materials...")
    return load_extras(tileset, path, normals_path, emissive_path, specular_path)


def compose_sprite(layer_codepoints: list[int], overlay_scale: float = 1.0, x_offset: int = 0, y_offset: int = 0, x_crop: int = 0, y_crop: int = 0, top_first_layer: bool = True, layer_tints: list | None = None) -> str:
    """Alpha-composite multiple tile layers into a new tileset slot.

    Takes codepoints and converts to chr output

    Blends codepoints bottom-up (first = base, last = top layer) by default.
    If top_first_layer=False, the first layer is treated as the top, and all following
    layers are composed behind it.

    layer_tints: optional list of (R,G,B) tuples (or None entries) to multiply
    into each layer's pixels before compositing.  None = no tint (white).

    Caches results so identical combos reuse the same slot.
    Returns the chr() of the resulting codepoint.

    Note: x_crop/y_crop apply to the first layer only.
    """
    try:
        global _composite_next, _tileset
        if _tileset is None:
            raise RuntimeError("[sprite_manager] compose_sprite called before load_extras set the tileset.")

        normalized_scale = max(0.05, float(overlay_scale))
        # Normalise tints for cache key: None → (255,255,255)
        norm_tints = None
        if layer_tints is not None:
            norm_tints = tuple(
                (255, 255, 255) if t is None else tuple(int(v) for v in t)
                for t in layer_tints
            )
        key = (tuple(layer_codepoints), round(normalized_scale, 4), x_offset, y_offset, x_crop, y_crop, top_first_layer, norm_tints)
        if key in _composite_cache:
            return chr(_composite_cache[key])

        def _apply_tint(pixels: np.ndarray, tint) -> np.ndarray:
            """Multiply RGB channels of pixel data by a (R,G,B) tint."""
            if tint is None or tint == (255, 255, 255):
                return pixels
            t = np.array([tint[0], tint[1], tint[2], 255], dtype=np.float32) / 255.0
            result = pixels.astype(np.float32)
            result[..., :3] *= t[:3]
            return result

        def _tint_for(idx: int):
            if norm_tints is None or idx >= len(norm_tints):
                return None
            return norm_tints[idx]

        # First layer (entity) is special: cropped and/or preserved as top if requested.
        first = _get_tile(layer_codepoints[0]).astype(np.float32).copy()
        first = _apply_tint(first, _tint_for(0))
        first_is_cropped = (x_crop != 0 or y_crop != 0)
        if first_is_cropped:
            first = _crop_overlay_tile(first, x_crop, y_crop).astype(np.float32)

        if top_first_layer:
            base = first
            overlay_layers = layer_codepoints[1:]
        else:
            # Compose all background layers (the rest) first, then draw first on top.
            if len(layer_codepoints) > 1:
                base = _get_tile(layer_codepoints[1]).astype(np.float32).copy()
                for cp in layer_codepoints[2:]:
                    overlay_pixels = _get_tile(cp)
                    if normalized_scale != 1.0:
                        overlay_pixels = _scale_overlay_tile(overlay_pixels, normalized_scale)
                    if x_offset != 0 or y_offset != 0:
                        overlay_pixels = _offset_overlay_tile(overlay_pixels, x_offset, y_offset)
                    overlay = overlay_pixels.astype(np.float32)
                    alpha = overlay[..., 3:4] / 255.0
                    base[..., :3] = overlay[..., :3] * alpha + base[..., :3] * (1.0 - alpha)
                    base[..., 3] = np.maximum(base[..., 3], overlay[..., 3])
            else:
                base = np.zeros_like(first)
            overlay_layers = []

        if not top_first_layer:
            # if first is top, we already have background base; now overlay first last.
            overlay_layers = []
            for cp in [layer_codepoints[0]]:
                overlay_pixels = first
                # first already has crop and no transforms applied
                alpha = (overlay_pixels[..., 3:4] / 255.0)
                base[..., :3] = overlay_pixels[..., :3] * alpha + base[..., :3] * (1.0 - alpha)
                base[..., 3] = np.maximum(base[..., 3], overlay_pixels[..., 3])
        else:
            for layer_idx, cp in enumerate(overlay_layers, start=1):
                overlay_pixels = _get_tile(cp)
                overlay_pixels = _apply_tint(overlay_pixels, _tint_for(layer_idx))
                if normalized_scale != 1.0:
                    overlay_pixels = _scale_overlay_tile(overlay_pixels, normalized_scale)
                if x_offset != 0 or y_offset != 0:
                    overlay_pixels = _offset_overlay_tile(overlay_pixels, x_offset, y_offset)
                overlay = overlay_pixels.astype(np.float32)
                alpha = overlay[..., 3:4] / 255.0
                base[..., :3] = overlay[..., :3] * alpha + base[..., :3] * (1.0 - alpha)
                base[..., 3] = np.maximum(base[..., 3], overlay[..., 3])

        result = base.astype(np.uint8)
        
        # Composite material channels (emissive, specular, normals) from source layers
        # Use same layer order and alpha blending as albedo composition
        h, w = result.shape[:2]
        composed_emission = np.zeros((h, w, 3), dtype=np.float32)
        composed_specular = np.zeros((h, w, 3), dtype=np.float32)
        composed_normal_detail = np.zeros((h, w), dtype=np.float32)
        composed_specular_mask = np.zeros((h, w), dtype=np.float32)
        composed_normals = np.zeros((h, w, 3), dtype=np.float32)
        composed_normals[..., 2] = 1.0  # Default flat normal
        
        # Composite materials in the same order as the albedo layers
        if top_first_layer:
            material_order = layer_codepoints
        else:
            material_order = list(layer_codepoints[1:]) + [layer_codepoints[0]]
        
        for layer_idx, layer_cp in enumerate(material_order):
            # Get material data for this layer
            layer_emission = _emissive_by_cp.get(layer_cp)
            layer_specular = _specular_by_cp.get(layer_cp)
            layer_normal_detail = _normal_detail_by_cp.get(layer_cp)
            layer_specular_mask = _specular_mask_by_cp.get(layer_cp)
            
            # Get normal field (might not be cached yet)
            layer_normal_tuple = _normal_field_by_cp.get(layer_cp)
            if layer_normal_tuple is not None:
                layer_normals, _ = layer_normal_tuple
            else:
                layer_normals = None
            
            # Get alpha for blending
            layer_pixels = _get_tile(layer_cp).astype(np.float32)
            
            # Apply crop to first layer if needed
            is_first_layer = (layer_cp == layer_codepoints[0])
            if is_first_layer and first_is_cropped:
                layer_pixels = _crop_overlay_tile(layer_pixels, x_crop, y_crop).astype(np.float32)
                if layer_emission is not None:
                    layer_emission = _crop_overlay_tile(np.concatenate([layer_emission, np.ones((layer_emission.shape[0], layer_emission.shape[1], 1))], axis=2), x_crop, y_crop)[..., :3]
                if layer_specular is not None:
                    layer_specular = _crop_overlay_tile(np.concatenate([layer_specular, np.ones((layer_specular.shape[0], layer_specular.shape[1], 1))], axis=2), x_crop, y_crop)[..., :3]
                if layer_normal_detail is not None:
                    layer_normal_detail = _crop_overlay_tile(np.stack([layer_normal_detail, layer_normal_detail, layer_normal_detail, np.ones_like(layer_normal_detail)], axis=2), x_crop, y_crop)[..., 0]
                if layer_specular_mask is not None:
                    layer_specular_mask = _crop_overlay_tile(np.stack([layer_specular_mask, layer_specular_mask, layer_specular_mask, np.ones_like(layer_specular_mask)], axis=2), x_crop, y_crop)[..., 0]
                if layer_normals is not None:
                    # Crop normals to match cropped albedo
                    layer_normals_rgba = np.concatenate([layer_normals, np.ones((layer_normals.shape[0], layer_normals.shape[1], 1))], axis=2)
                    layer_normals = _crop_overlay_tile(layer_normals_rgba, x_crop, y_crop)[..., :3]
            
            # Resize all material data to match output size if needed
            lh, lw = layer_pixels.shape[:2]
            if lh != h or lw != w:
                # Simple nearest-neighbor resize for materials
                y_idx = np.minimum((np.arange(h, dtype=np.int32) * lh) // max(1, h), lh - 1)
                x_idx = np.minimum((np.arange(w, dtype=np.int32) * lw) // max(1, w), lw - 1)
                
                layer_pixels = layer_pixels[y_idx[:, None], x_idx[None, :], :]
                if layer_emission is not None:
                    layer_emission = layer_emission[y_idx[:, None], x_idx[None, :], :]
                if layer_specular is not None:
                    layer_specular = layer_specular[y_idx[:, None], x_idx[None, :], :]
                if layer_normal_detail is not None:
                    layer_normal_detail = layer_normal_detail[y_idx[:, None], x_idx[None, :]]
                if layer_specular_mask is not None:
                    layer_specular_mask = layer_specular_mask[y_idx[:, None], x_idx[None, :]]
                if layer_normals is not None:
                    layer_normals = layer_normals[y_idx[:, None], x_idx[None, :], :]
            
            layer_alpha_3d = (layer_pixels[..., 3:4] / 255.0).clip(0.0, 1.0)  # Keep (H, W, 1) for broadcasting
            layer_alpha_2d = layer_alpha_3d[..., 0]  # (H, W) for 2D arrays
            
            # Blend emissive (additive for glows)
            if layer_emission is not None:
                composed_emission += layer_emission * layer_alpha_3d
            
            # Blend specular (overlay with alpha)
            if layer_specular is not None:
                composed_specular = layer_specular * layer_alpha_3d + composed_specular * (1.0 - layer_alpha_3d)
            
            # Blend masks (max for flags)
            if layer_normal_detail is not None:
                composed_normal_detail = np.maximum(composed_normal_detail, layer_normal_detail * layer_alpha_2d)
            if layer_specular_mask is not None:
                composed_specular_mask = np.maximum(composed_specular_mask, layer_specular_mask * layer_alpha_2d)
            
            # Blend normals (weighted average)
            if layer_normals is not None:
                # Weight by alpha and accumulate
                composed_normals = layer_normals * layer_alpha_3d + composed_normals * (1.0 - layer_alpha_3d)
        
        # Normalize the composed normal
        mag = np.sqrt(np.sum(composed_normals * composed_normals, axis=2, keepdims=True))
        mag = np.where(mag > 1e-6, mag, 1.0)
        composed_normals = composed_normals / mag
        
        # Reuse a previously freed slot before consuming a new codepoint.
        if _composite_free_list:
            cp = _composite_free_list.pop()
        else:
            cp = _composite_next
            _composite_next += 1
        if _deferred_mode:
            _deferred_pixel_store[cp] = result
            _deferred_tiles.append((cp, result))
        else:
            _tileset.set_tile(cp, result)
        
        # Register all material data for the composite
        _register_albedo_alpha(cp, result)
        _register_normal_field(cp, composed_normals, result[..., 3].astype(np.float32) / 255.0)
        
        # Only register non-zero material data to save memory
        if np.any(composed_emission > 1e-4):
            _emissive_by_cp[cp] = composed_emission.clip(0.0, 1.0)
        if np.any(composed_specular > 1e-4) or np.any(composed_specular_mask > 1e-4):
            _specular_by_cp[cp] = composed_specular.clip(0.0, 1.0)
            _normal_detail_by_cp[cp] = composed_normal_detail.clip(0.0, 1.0)
            _specular_mask_by_cp[cp] = composed_specular_mask.clip(0.0, 1.0)
        
        _composite_cache[key] = cp
        
        # Notify shader engine that this codepoint has new material data
        shader_mod = _get_shader()
        if shader_mod:
            shader_mod.invalidate_material_cache(cp)
        
        return chr(cp)
    except Exception as e:
        print(f"[sprite_manager] Error composing sprite from layers {[hex(c) for c in layer_codepoints]}: {e}")
        return chr(layer_codepoints[0])  # fallback to base layer if composition fails


# ---------------------------------------------------------------------------
# Procedural puddle sprite generation
# ---------------------------------------------------------------------------
_puddle_sprite_cache: dict = {}   # (neighbor_key, tint_tuple, depth, seed) -> cp int


def _generate_puddle_pixels(
    tile_x: int, tile_y: int,
    has_top: bool, has_bottom: bool, has_left: bool, has_right: bool,
    has_tl: bool, has_tr: bool, has_bl: bool, has_br: bool,
    tint: tuple, depth: int,
) -> np.ndarray:
    """Return a (TILE_H, TILE_W, 4) uint8 RGBA array for a splatter stain.

    Edge jaggedness comes from world-space FBM value noise applied to the
    metaball isosurface threshold.  Because both this tile and its neighbours
    sample the same continuous noise function at the shared boundary, seams
    are impossible — the edge shape is physically continuous across tiles.
    """
    W, H = TILE_W, TILE_H
    # Per-tile RNG only drives satellite drop positions, not edge shape.
    rng = np.random.default_rng((abs(tile_x) * 7919 + abs(tile_y) * 6271) & 0xFFFF)

    pu = (np.arange(W, dtype=np.float32) + 0.5) / W
    pv = (np.arange(H, dtype=np.float32) + 0.5) / H
    U, V = np.meshgrid(pu, pv)
    EPS = 1e-4

    # World-space coordinates for each pixel — shared with neighbours.
    WX = (tile_x + U).astype(np.float32)
    WY = (tile_y + V).astype(np.float32)

    field = np.zeros((H, W), dtype=np.float32)

    def add_ball(cx: float, cy: float, r: float) -> None:
        nonlocal field
        d2 = (U - cx) ** 2 + (V - cy) ** 2
        field += (r * r) / (d2 + EPS)

    # --- Core blob -------------------------------------------------------
    add_ball(0.5, 0.5, 0.27)

    # --- Satellite splatter drops (per-tile seeded) ----------------------
    n_drops = int(rng.integers(3, 8))
    for _ in range(n_drops):
        ang  = rng.uniform(0.0, 2 * np.pi)
        dist = rng.uniform(0.18, 0.44)
        dr   = rng.uniform(0.04, 0.09)
        add_ball(0.5 + np.cos(ang) * dist, 0.5 + np.sin(ang) * dist, dr)

    # --- Neighbour connectivity balls (unwarped for reliable seams) ------
    EDGE_R = 0.26
    if has_top:
        add_ball(0.5, 0.0, EDGE_R)
    if has_bottom:
        add_ball(0.5, 1.0, EDGE_R)
    if has_left:
        add_ball(0.0, 0.5, EDGE_R)
    if has_right:
        add_ball(1.0, 0.5, EDGE_R)

    CORNER_R = 0.19
    if has_top and has_left:
        add_ball(0.0, 0.0, CORNER_R)
    if has_top and has_right:
        add_ball(1.0, 0.0, CORNER_R)
    if has_bottom and has_left:
        add_ball(0.0, 1.0, CORNER_R)
    if has_bottom and has_right:
        add_ball(1.0, 1.0, CORNER_R)

    DIAG_R = 0.16
    if has_tl:
        add_ball(0.18, 0.18, DIAG_R)
    if has_tr:
        add_ball(0.82, 0.18, DIAG_R)
    if has_bl:
        add_ball(0.18, 0.82, DIAG_R)
    if has_br:
        add_ball(0.82, 0.82, DIAG_R)

    # --- World-space FBM to roughen the isosurface edge -----------------
    # Both this tile and its neighbours sample the same noise values at the
    # shared boundary row/column → zero visible seam.
    def _hash(ix_arr: np.ndarray, iy_arr: np.ndarray) -> np.ndarray:
        """Scramble int32 tile coords to float in [0,1]. Wraps on overflow."""
        n = ix_arr.astype(np.int32) * np.int32(127) ^ iy_arr.astype(np.int32) * np.int32(311)
        n = n * np.int32(1664525) + np.int32(1013904223)
        return n.view(np.uint32).astype(np.float32) * np.float32(2.3283064365386963e-10)

    def _val_noise(wx: np.ndarray, wy: np.ndarray) -> np.ndarray:
        iwx = np.floor(wx).astype(np.int32)
        iwy = np.floor(wy).astype(np.int32)
        fx  = (wx - np.floor(wx)).astype(np.float32)
        fy  = (wy - np.floor(wy)).astype(np.float32)
        ux  = fx * fx * (3.0 - 2.0 * fx)
        uy  = fy * fy * (3.0 - 2.0 * fy)
        a = _hash(iwx,     iwy    )
        b = _hash(iwx + 1, iwy    )
        c = _hash(iwx,     iwy + 1)
        d = _hash(iwx + 1, iwy + 1)
        return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy

    # 3 octaves — low freq gives broad lopsidedness, high freq jagged detail.
    noise = (_val_noise(WX * 4.0,  WY * 4.0 ) * 1.00
           + _val_noise(WX * 9.0,  WY * 9.0 ) * 0.50
           + _val_noise(WX * 18.0, WY * 18.0) * 0.25) / 1.75  # → [0, 1]
    # Add to field as a threshold shift: ±0.20 in field units.
    field_noised = field + (noise - 0.5) * 0.40

    # --- Edge fades on free (non-neighbour) sides -------------------------
    # When 3 sides are connected, the combined connectivity-ball field can
    # exceed the threshold all the way to the 4th (free) edge, producing a
    # solid rectangular block instead of an organic rounded puddle.
    # Applying a smoothstep fade on each free edge forces the blood to taper
    # to zero at the tile boundary while leaving connected edges untouched,
    # ensuring organic splat shapes on the pool perimeter.
    # The FBM noise still varies the exact fade curve from tile to tile.
    FADE_WIDTH = 0.22
    if not has_left:
        t = np.clip(U / FADE_WIDTH, 0.0, 1.0)
        field_noised = field_noised * (t * t * (3.0 - 2.0 * t))
    if not has_right:
        t = np.clip((1.0 - U) / FADE_WIDTH, 0.0, 1.0)
        field_noised = field_noised * (t * t * (3.0 - 2.0 * t))
    if not has_top:
        t = np.clip(V / FADE_WIDTH, 0.0, 1.0)
        field_noised = field_noised * (t * t * (3.0 - 2.0 * t))
    if not has_bottom:
        t = np.clip((1.0 - V) / FADE_WIDTH, 0.0, 1.0)
        field_noised = field_noised * (t * t * (3.0 - 2.0 * t))

    # --- Corner rounding for concave corners ----------------------------
    # When two adjacent cardinal edges are connected but the diagonal between
    # them is NOT, the combined edge-ball potential at that corner exceeds
    # the threshold → 90° square bite.  Apply a radial smoothstep fade
    # inside each such corner to round it into an organic curve.
    # Corners where the diagonal IS present are left untouched so the
    # cross-tile seam stays seamless.
    CORNER_ROUND = 0.25
    if has_top and has_left and not has_tl:
        dist = np.sqrt(U ** 2 + V ** 2)
        t = np.clip(dist / CORNER_ROUND, 0.0, 1.0)
        fade = t * t * (3.0 - 2.0 * t)
        field_noised = np.where((U < CORNER_ROUND) & (V < CORNER_ROUND), field_noised * fade, field_noised)
    if has_top and has_right and not has_tr:
        dist = np.sqrt((1.0 - U) ** 2 + V ** 2)
        t = np.clip(dist / CORNER_ROUND, 0.0, 1.0)
        fade = t * t * (3.0 - 2.0 * t)
        field_noised = np.where((U > 1.0 - CORNER_ROUND) & (V < CORNER_ROUND), field_noised * fade, field_noised)
    if has_bottom and has_left and not has_bl:
        dist = np.sqrt(U ** 2 + (1.0 - V) ** 2)
        t = np.clip(dist / CORNER_ROUND, 0.0, 1.0)
        fade = t * t * (3.0 - 2.0 * t)
        field_noised = np.where((U < CORNER_ROUND) & (V > 1.0 - CORNER_ROUND), field_noised * fade, field_noised)
    if has_bottom and has_right and not has_br:
        dist = np.sqrt((1.0 - U) ** 2 + (1.0 - V) ** 2)
        t = np.clip(dist / CORNER_ROUND, 0.0, 1.0)
        fade = t * t * (3.0 - 2.0 * t)
        field_noised = np.where((U > 1.0 - CORNER_ROUND) & (V > 1.0 - CORNER_ROUND), field_noised * fade, field_noised)

    # --- Alpha: narrow feather = crisp stain edge ------------------------
    THRESHOLD = 0.55
    FEATHER   = 0.10
    t = np.clip((field_noised - THRESHOLD) / FEATHER, 0.0, 1.0)
    alpha_field = t * t * (3.0 - 2.0 * t)
    max_opacity = 0.85 + (depth - 1) * 0.05
    alpha_field *= max_opacity

    # --- Colour ----------------------------------------------------------
    tr, tg, tb = tint[0] / 255.0, tint[1] / 255.0, tint[2] / 255.0
    wet = np.clip((field_noised - THRESHOLD) / 1.5, 0.0, 1.0)
    brightness = np.clip(0.68 - wet * 0.22, 0.46, 0.72)

    r_ch = np.clip(tr * brightness * 255, 0, 255).astype(np.uint8)
    g_ch = np.clip(tg * brightness * 255, 0, 255).astype(np.uint8)
    b_ch = np.clip(tb * brightness * 255, 0, 255).astype(np.uint8)
    a_ch = np.clip(alpha_field * 255, 0, 255).astype(np.uint8)

    return np.stack([r_ch, g_ch, b_ch, a_ch], axis=-1)


def get_puddle_sprite(
    tile_x: int, tile_y: int,
    has_top: bool, has_bottom: bool, has_left: bool, has_right: bool,
    has_tl: bool, has_tr: bool, has_bl: bool, has_br: bool,
    tint: tuple, depth: int,
) -> str:
    """Return ``chr()`` of a procedural puddle codepoint for the given tile.

    Each world position is given exactly one tileset slot.  When depth or
    neighbour pattern changes the slot's pixels are updated in-place instead
    of allocating a fresh codepoint, preventing slot exhaustion during
    evaporation.  Downstream compose_sprite entries that referenced the old
    pixels are evicted from the cache so they rebuild on the next call.
    """
    global _composite_next, _tileset, _puddle_sprite_cache, _puddle_pos_slot

    norm_tint = tuple(int(v) for v in tint)
    key = (
        tile_x, tile_y,
        has_top, has_bottom, has_left, has_right,
        has_tl, has_tr, has_bl, has_br,
        norm_tint, depth,
    )
    pos_key = (tile_x, tile_y)

    existing_cp = _puddle_pos_slot.get(pos_key)

    if existing_cp is not None:
        # Slot already allocated for this world position.
        if _puddle_sprite_cache.get(key) == existing_cp:
            # Exact same config — pixels already up to date.
            return chr(existing_cp)
        # Config changed (new depth or new neighbours): regenerate pixels
        # in the existing slot instead of consuming a new codepoint.
        pixels = _generate_puddle_pixels(
            tile_x, tile_y,
            has_top, has_bottom, has_left, has_right,
            has_tl, has_tr, has_bl, has_br,
            tint, depth,
        )
        if _deferred_mode:
            _deferred_pixel_store[existing_cp] = pixels
            _deferred_tiles.append((existing_cp, pixels))
        else:
            if _tileset is None:
                raise RuntimeError("[sprite_manager] get_puddle_sprite called before tileset is loaded.")
            _tileset.set_tile(existing_cp, pixels)
        _register_albedo_alpha(existing_cp, pixels)
        _register_flat_normals(existing_cp, pixels)  # Puddles are flat liquid surfaces
        # Evict any compose_sprite cache entries whose pixel inputs included
        # this puddle codepoint — they are now stale.
        # Guard: compose_dungeon_water stores keys like ('_dw', ...) where k[0] is
        # a string, so skip those entries.
        stale = [k for k, v in _composite_cache.items()
                 if isinstance(k[0], tuple) and existing_cp in k[0]]
        for k in stale:
            _release_composite_slot(_composite_cache.pop(k))
        # Drop all previous puddle cache entries for this position — their
        # pixels are now stale (GPU slot was overwritten).  Without this,
        # a later config that happens to match an old key returns early with
        # the wrong sprite (e.g. after evaporation reverts neighbour flags).
        stale_puddle = [k for k, v in _puddle_sprite_cache.items()
                        if k[0] == tile_x and k[1] == tile_y and v == existing_cp]
        for k in stale_puddle:
            del _puddle_sprite_cache[k]
        _puddle_sprite_cache[key] = existing_cp
        return chr(existing_cp)

    # New world position — allocate a slot, preferring recycled entries.
    pixels = _generate_puddle_pixels(
        tile_x, tile_y,
        has_top, has_bottom, has_left, has_right,
        has_tl, has_tr, has_bl, has_br,
        tint, depth,
    )
    if _composite_free_list:
        cp = _composite_free_list.pop()
    else:
        cp = _composite_next
        _composite_next += 1
    _puddle_sprite_cache[key] = cp
    _puddle_pos_slot[pos_key] = cp

    if _deferred_mode:
        _deferred_pixel_store[cp] = pixels
        _deferred_tiles.append((cp, pixels))
    else:
        if _tileset is None:
            raise RuntimeError("[sprite_manager] get_puddle_sprite called before tileset is loaded.")
        _tileset.set_tile(cp, pixels)
    _register_albedo_alpha(cp, pixels)
    _register_flat_normals(cp, pixels)  # Puddles are flat liquid surfaces

    return chr(cp)


def compose_puddle_tile(tile_x: int, tile_y: int, orig_cp: int, puddle_cp: int) -> str:
    """Composite orig_cp beneath puddle_cp and return chr() of the result.

    Allocates a fresh codepoint for each update so the ch value written to
    ``game_map.tiles`` always changes when blood state changes.
    ``SDLConsoleRender`` uses dirty-tracking: it only re-renders console cells
    whose ch/fg/bg changed vs the previous call.  If we overwrote pixel data
    in-place without changing the codepoint the dirty flag would never fire and
    blood depth/shape changes would stay invisible.  The old slot is returned to
    ``_composite_free_list`` immediately so the total number of live slots stays
    bounded.
    """
    global _composite_next, _tileset, _tile_puddle_pos_slot

    pos_key = (tile_x, tile_y)
    existing_cp = _tile_puddle_pos_slot.get(pos_key)

    # Build composite pixels (orig tile as base, puddle on top).
    base = _get_tile(orig_cp).astype(np.float32).copy()
    overlay = _get_tile(puddle_cp).astype(np.float32)
    alpha = overlay[..., 3:4] / 255.0
    base[..., :3] = overlay[..., :3] * alpha + base[..., :3] * (1.0 - alpha)
    base[..., 3] = np.maximum(base[..., 3], overlay[..., 3])
    result = base.astype(np.uint8)

    if existing_cp is not None:
        # Allocate a NEW slot so the codepoint changes, forcing SDL dirty-render.
        if _composite_free_list:
            new_cp = _composite_free_list.pop()
        else:
            new_cp = _composite_next
            _composite_next += 1

        if _deferred_mode:
            _deferred_pixel_store[new_cp] = result
            _deferred_tiles.append((new_cp, result))
        else:
            _tileset.set_tile(new_cp, result)
        _register_albedo_alpha(new_cp, result)
        _register_avg_normal_from_albedo_pixels(new_cp, result)

        # Return the old slot to the free list for immediate reuse.
        _release_composite_slot(existing_cp)

        # Evict entity/item composites built on the OLD codepoint.
        stale = [k for k, v in _composite_cache.items()
                 if isinstance(k[0], tuple) and existing_cp in k[0]]
        for k in stale:
            _release_composite_slot(_composite_cache.pop(k))

        _tile_puddle_pos_slot[pos_key] = new_cp
        return chr(new_cp)

    # First time for this position — allocate a fresh slot.
    if _composite_free_list:
        cp = _composite_free_list.pop()
    else:
        cp = _composite_next
        _composite_next += 1
    _tile_puddle_pos_slot[pos_key] = cp
    if _deferred_mode:
        _deferred_pixel_store[cp] = result
        _deferred_tiles.append((cp, result))
    else:
        _tileset.set_tile(cp, result)
    _register_albedo_alpha(cp, result)
    _register_avg_normal_from_albedo_pixels(cp, result)
    return chr(cp)


def release_puddle_slots(tile_x: int, tile_y: int) -> None:
    """Release per-position puddle and composite slots for a tile.

    Call this when blood/liquid is fully removed from a world position.
    The codepoints themselves cannot be recycled (tcod tileset slots are
    permanent), but clearing the registry prevents stale cache hits and
    lets the position receive fresh slots if liquid returns later.
    """
    pos_key = (tile_x, tile_y)

    puddle_cp = _puddle_pos_slot.pop(pos_key, None)
    if puddle_cp is not None:
        # Evict composite cache entries that used this puddle as input.
        # Guard: compose_dungeon_water stores keys like ('_dw', ...) where k[0] is
        # a string, so skip those entries.
        stale = [k for k, v in _composite_cache.items()
                 if isinstance(k[0], tuple) and puddle_cp in k[0]]
        for k in stale:
            _release_composite_slot(_composite_cache.pop(k))
        stale_p = [k for k, v in _puddle_sprite_cache.items() if v == puddle_cp]
        for k in stale_p:
            del _puddle_sprite_cache[k]
        # The puddle sprite slot itself is now unused — return it for reuse.
        _release_composite_slot(puddle_cp)

    tile_puddle_cp = _tile_puddle_pos_slot.pop(pos_key, None)
    if tile_puddle_cp is not None:
        # Also evict entity composites that used this tile+puddle codepoint.
        stale = [k for k, v in _composite_cache.items()
                 if isinstance(k[0], tuple) and tile_puddle_cp in k[0]]
        for k in stale:
            _release_composite_slot(_composite_cache.pop(k))
        _release_composite_slot(tile_puddle_cp)


# ---------------------------------------------------------------------------
# Per-frame entity-on-tile compositing  (recycled every render pass)
# ---------------------------------------------------------------------------
_entity_tile_cache: dict = {}       # (tile_cp, entity_cp, tint_tuple) -> cp int  (current frame)
_entity_tile_prev_slots: list = []  # cp ints from the previous frame — freed at next begin_render_frame


def begin_render_frame() -> None:
    """Rotate entity-on-tile composite slots.

    Call once at the start of each map render pass, before any entity
    rendering.  Slots used last frame are returned to the free list so they
    can be reused immediately without permanently growing the tileset.
    """
    global _entity_tile_cache, _entity_tile_prev_slots
    # Clear stale emissive/specular data from last frame's slots before recycling them.
    for _cp in _entity_tile_prev_slots:
        _emissive_by_cp.pop(_cp, None)
        _specular_by_cp.pop(_cp, None)
        _normal_detail_by_cp.pop(_cp, None)
        _specular_mask_by_cp.pop(_cp, None)
    # Return last frame's slots to the pool.
    _entity_tile_free_list.extend(_entity_tile_prev_slots)
    # Save current frame's slots to free next time.
    _entity_tile_prev_slots = list(_entity_tile_cache.values())
    # Fresh cache for the new frame.
    _entity_tile_cache = {}


def compose_entity_tile(tile_cp: int, entity_cp: int, entity_tint) -> str:
    """Composite entity_cp on top of tile_cp for a single render frame.

    Unlike compose_sprite the returned codepoint is only valid for the current
    frame — the slot is recycled by the next begin_render_frame() call, so the
    total number of permanent tileset slots does not grow as entities walk
    around the map.

    The tile layer is rendered un-tinted; entity_tint is applied to the entity
    layer.  Returns the raw entity char as a fallback if the tileset is not
    initialised.
    """
    global _entity_tile_cache, _composite_next, _tileset
    if _tileset is None:
        return chr(entity_cp)

    norm_tint: tuple = tuple(int(v) for v in entity_tint) if entity_tint else (255, 255, 255)
    key = (tile_cp, entity_cp, norm_tint)

    if key in _entity_tile_cache:
        return chr(_entity_tile_cache[key])

    try:
        base = _get_tile(tile_cp).astype(np.float32).copy()
        overlay = _get_tile(entity_cp).astype(np.float32)
        if norm_tint != (255, 255, 255):
            t = np.array(norm_tint[:3], dtype=np.float32) / 255.0
            overlay[..., :3] *= t
        alpha = overlay[..., 3:4] / 255.0
        base[..., :3] = overlay[..., :3] * alpha + base[..., :3] * (1.0 - alpha)
        base[..., 3] = np.maximum(base[..., 3], overlay[..., 3])
        result = base.astype(np.uint8)

        # Blend source average normals by entity alpha coverage so entity normals
        # dominate opaque sprite regions while floor normal still contributes.
        try:
            coverage = float(np.mean(alpha))
        except Exception:
            coverage = 0.0
        tile_n = get_average_normal(tile_cp)
        ent_n = get_average_normal(entity_cp)
        mix_n = _normalize_vec3(
            tile_n[0] * (1.0 - coverage) + ent_n[0] * coverage,
            tile_n[1] * (1.0 - coverage) + ent_n[1] * coverage,
            tile_n[2] * (1.0 - coverage) + ent_n[2] * coverage,
        )

        tile_nf, tile_a = get_normal_field(tile_cp)
        ent_nf, ent_a = get_normal_field(entity_cp)
        # Use entity sprite alpha for mask, with authored normal alpha as multiplier.
        mask = np.clip(alpha[..., 0] * ent_a, 0.0, 1.0)
        inv_mask = 1.0 - mask
        comb = np.empty_like(tile_nf)
        comb[..., 0] = tile_nf[..., 0] * inv_mask + ent_nf[..., 0] * mask
        comb[..., 1] = tile_nf[..., 1] * inv_mask + ent_nf[..., 1] * mask
        comb[..., 2] = tile_nf[..., 2] * inv_mask + ent_nf[..., 2] * mask
        mag = np.sqrt(comb[..., 0] * comb[..., 0] + comb[..., 1] * comb[..., 1] + comb[..., 2] * comb[..., 2])
        mag = np.where(mag > 1e-6, mag, 1.0)
        comb[..., 0] /= mag
        comb[..., 1] /= mag
        comb[..., 2] /= mag
        comb_alpha = np.clip(np.maximum(tile_a * inv_mask, ent_a * mask), 0.0, 1.0)

        if _entity_tile_free_list:
            cp = _entity_tile_free_list.pop()
        else:
            cp = _composite_next
            _composite_next += 1

        if _deferred_mode:
            _deferred_pixel_store[cp] = result
            _deferred_tiles.append((cp, result))
        else:
            _tileset.set_tile(cp, result)

        _register_albedo_alpha(cp, result)
        _avg_normal_by_cp[cp] = mix_n
        _register_normal_field(cp, comb, comb_alpha)
        _derived_avg_normal_cache.pop(cp, None)

        # Blend emissive: entity emissive over base using entity alpha mask
        h_px, w_px = result.shape[:2]
        alpha2d = alpha[..., 0]  # (H, W) float32 in [0, 1]
        base_em = _emissive_by_cp.get(tile_cp)
        ent_em = _emissive_by_cp.get(entity_cp)
        if base_em is not None or ent_em is not None:
            if base_em is None:
                base_em = np.zeros((h_px, w_px, 3), dtype=np.float32)
            if ent_em is None:
                ent_em = np.zeros((h_px, w_px, 3), dtype=np.float32)
            comp_em = ent_em * alpha + base_em * (1.0 - alpha)
            if np.any(comp_em > 1e-4):
                _emissive_by_cp[cp] = comp_em
            else:
                _emissive_by_cp.pop(cp, None)

        # Blend specular channels: entity over base using entity alpha mask
        base_spec = _specular_by_cp.get(tile_cp)
        ent_spec = _specular_by_cp.get(entity_cp)
        base_nd = _normal_detail_by_cp.get(tile_cp)
        ent_nd = _normal_detail_by_cp.get(entity_cp)
        base_sm = _specular_mask_by_cp.get(tile_cp)
        ent_sm = _specular_mask_by_cp.get(entity_cp)
        if any(x is not None for x in (base_spec, ent_spec, base_nd, ent_nd, base_sm, ent_sm)):
            if base_spec is None:
                base_spec = np.zeros((h_px, w_px, 3), dtype=np.float32)
            if ent_spec is None:
                ent_spec = np.zeros((h_px, w_px, 3), dtype=np.float32)
            if base_nd is None:
                base_nd = np.zeros((h_px, w_px), dtype=np.float32)
            if ent_nd is None:
                ent_nd = np.zeros((h_px, w_px), dtype=np.float32)
            if base_sm is None:
                base_sm = np.zeros((h_px, w_px), dtype=np.float32)
            if ent_sm is None:
                ent_sm = np.zeros((h_px, w_px), dtype=np.float32)
            _specular_by_cp[cp] = ent_spec * alpha + base_spec * (1.0 - alpha)
            _normal_detail_by_cp[cp] = ent_nd * alpha2d + base_nd * (1.0 - alpha2d)
            _specular_mask_by_cp[cp] = ent_sm * alpha2d + base_sm * (1.0 - alpha2d)

        _entity_tile_cache[key] = cp
        return chr(cp)
    except Exception as e:
        print(f"[sprite_manager] compose_entity_tile tile={hex(tile_cp)} entity={hex(entity_cp)}: {e}")
        return chr(entity_cp)


def get_composite_slot_usage() -> dict:
    """Return a dict with composite slot usage info for debugging."""
    allocated = _composite_next - COMPOSITE_START_CP
    frame_slots = len(_entity_tile_cache) + len(_entity_tile_prev_slots)
    return {
        "next_cp": _composite_next,
        "start_cp": COMPOSITE_START_CP,
        "slots_allocated": allocated,
        "slots_free": len(_composite_free_list) + len(_entity_tile_free_list),
        "permanent_free": len(_composite_free_list),
        "frame_free": len(_entity_tile_free_list),
        "slots_live": allocated - len(_composite_free_list) - len(_entity_tile_free_list),
        "puddle_positions": len(_puddle_pos_slot),
        "tile_puddle_positions": len(_tile_puddle_pos_slot),
        "compose_cache_entries": len(_composite_cache),
        "puddle_sprite_cache_entries": len(_puddle_sprite_cache),
        "entity_tile_frame_slots": frame_slots,
    }


def _collect_codepoints_from_value(value, live_codepoints: set[int]) -> None:
    if isinstance(value, np.ndarray):
        flat = np.asarray(value).ravel()
        for item in flat:
            try:
                cp = int(item)
            except Exception:
                continue
            if _SPRITE_CP_MIN <= cp <= _SPRITE_CP_MAX:
                live_codepoints.add(cp)
        return

    if isinstance(value, (int, np.integer)):
        cp = int(value)
        if _SPRITE_CP_MIN <= cp <= _SPRITE_CP_MAX:
            live_codepoints.add(cp)
        return

    if isinstance(value, str):
        if len(value) == 1:
            cp = ord(value)
            if _SPRITE_CP_MIN <= cp <= _SPRITE_CP_MAX:
                live_codepoints.add(cp)
        return

    if isinstance(value, dict):
        for item in value.values():
            _collect_codepoints_from_value(item, live_codepoints)
        return

    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _collect_codepoints_from_value(item, live_codepoints)


def collect_live_codepoints(engine, include_cached_world_maps: bool = True) -> set[int]:
    """Return sprite codepoints reachable from the loaded engine.

    include_cached_world_maps controls whether maps in game_world stacks/cache
    are scanned in addition to the active map. Disabling this significantly
    reduces prune-time spikes; pruned composites can still be regenerated if a
    cached map is later re-entered.
    """
    live_codepoints: set[int] = set()
    seen_maps: set[int] = set()
    seen_entities: set[int] = set()
    seen_items: set[int] = set()

    def _add_item(item) -> None:
        if item is None:
            return
        item_id = id(item)
        if item_id in seen_items:
            return
        seen_items.add(item_id)

        for attr_name in ("char", "base_char", "equip_sprite_cp"):
            _collect_codepoints_from_value(getattr(item, attr_name, None), live_codepoints)

        container = getattr(item, "container", None)
        for nested in list(getattr(container, "items", []) or []) if container is not None else []:
            _add_item(nested)

    def _add_entity(entity) -> None:
        if entity is None:
            return
        entity_id = id(entity)
        if entity_id in seen_entities:
            return
        seen_entities.add(entity_id)

        for attr_name in ("char", "base_char", "_portrait_cp"):
            _collect_codepoints_from_value(getattr(entity, attr_name, None), live_codepoints)

        equipment = getattr(entity, "equipment", None)
        for group_name in ("grasped_items", "equipped_items", "body_part_coverage"):
            for item in list(getattr(equipment, group_name, {}).values()) if equipment is not None else []:
                _collect_codepoints_from_value(getattr(item, "equip_sprite_cp", None), live_codepoints)
                _collect_codepoints_from_value(getattr(item, "char", None), live_codepoints)

        inventory = getattr(entity, "inventory", None)
        for item in list(getattr(inventory, "items", []) or []) if inventory is not None else []:
            _add_item(item)

        container = getattr(entity, "container", None)
        for item in list(getattr(container, "items", []) or []) if container is not None else []:
            _add_item(item)

    def _add_map(game_map) -> None:
        if game_map is None:
            return
        map_id = id(game_map)
        if map_id in seen_maps:
            return
        seen_maps.add(map_id)

        tiles = getattr(game_map, "tiles", None)
        if tiles is not None:
            try:
                _collect_codepoints_from_value(tiles["dark"]["ch"], live_codepoints)
                _collect_codepoints_from_value(tiles["light"]["ch"], live_codepoints)
            except Exception:
                pass

        for entity in list(getattr(game_map, "entities", []) or []):
            _add_entity(entity)

        for anim_attr in ("river_anim", "beach_water_anim", "dungeon_water_anim"):
            _collect_codepoints_from_value(getattr(game_map, anim_attr, None), live_codepoints)

    _add_map(getattr(engine, "game_map", None))

    if include_cached_world_maps:
        game_world = getattr(engine, "game_world", None)
        if game_world is not None:
            for stack_name in ("up_stack", "down_stack"):
                for entry in list(getattr(game_world, stack_name, []) or []):
                    if isinstance(entry, tuple) and entry:
                        _add_map(entry[0])

            for cached in (getattr(game_world, "dungeon_cache", {}) or {}).values():
                if isinstance(cached, tuple) and cached:
                    _add_map(cached[0])

    animation_queue = getattr(engine, "animation_queue", None)
    if animation_queue is not None:
        for animation in list(animation_queue):
            _add_entity(getattr(animation, "entity", None))
            _collect_codepoints_from_value(getattr(animation, "frames", None), live_codepoints)
            _collect_codepoints_from_value(getattr(animation, "frame_cp", None), live_codepoints)

    return live_codepoints


def prune_unused_composites(engine, include_cached_world_maps: bool = True) -> dict:
    """Drop composite cache entries no longer reachable from *engine*."""
    live_codepoints = collect_live_codepoints(
        engine,
        include_cached_world_maps=include_cached_world_maps,
    )
    pruned_entries = 0

    for key, cp in list(_composite_cache.items()):
        if cp not in live_codepoints:
            _release_composite_slot(cp)
            del _composite_cache[key]
            pruned_entries += 1

    return {
        "live_codepoints": len(live_codepoints),
        "pruned_entries": pruned_entries,
        "remaining_cache_entries": len(_composite_cache),
        "free_slots": len(_composite_free_list),
    }


def invalidate_all_puddle_sprites() -> None:
    """Clear the puddle sprite content-cache so every active blood tile
    regenerates its pixels on the next _update_tile_graphics call.

    The per-position SLOT registry (_puddle_pos_slot / _tile_puddle_pos_slot)
    is preserved, so regeneration reuses existing codepoints in-place rather
    than consuming new slots.  Call this after changing the puddle generation
    algorithm at runtime (e.g. adjusting FADE_WIDTH) to see the effect
    immediately on already-placed blood tiles.
    """
    _puddle_sprite_cache.clear()


def refresh_actor_sprite(actor) -> None:
    """Rebuild actor.char from base_char + sprite_layers of currently equipped items."""
    if not hasattr(actor, 'base_char'):
        return
    overlay_scale = getattr(actor, 'equipment_scale', 1.0)
    layers = [ord(actor.base_char)] + [
        item.equip_sprite_cp
        for item in list(getattr(actor.equipment, 'grasped_items', {}).values()) +
                     list(getattr(actor.equipment, 'equipped_items', {}).values()) +
                     list(getattr(actor.equipment, 'body_part_coverage', {}).values())
        if getattr(item, 'equip_sprite_cp', None) is not None
    ]
    # Deduplicate while preserving order
    seen: set = set()
    unique_layers = []
    for cp in layers:
        if cp not in seen:
            seen.add(cp)
            unique_layers.append(cp)

    if len(unique_layers) == 1:
        actor.char = actor.base_char
    else:
        actor.char = compose_sprite(unique_layers, overlay_scale=overlay_scale)
    
    # Mark this actor's tile as dirty for GPU atlas updates
    if hasattr(actor, 'x') and hasattr(actor, 'y'):
        shader_mod = _get_shader()
        if shader_mod:
            shader_mod.mark_sprite_dirty(actor.x, actor.y)


_WATER_FRAME_CPS = [0xE140, 0xE141, 0xE142, 0xE143, 0xE144]

# ---------------------------------------------------------------------------
# Dungeon water compositor
# ---------------------------------------------------------------------------
# Neighbor-mask bit assignments (cardinal directions).
_DW_N, _DW_E, _DW_S, _DW_W = 1, 2, 4, 8

# Tuning constants for 32×32 tiles.
# BLOB_R  – radius (pixels) of the semicircular water blob on each edge.
#           A circle of this radius is centred on the midpoint of the edge;
#           only the inward half is visible, giving a natural semicircle bite.
#           Adjacent edge blobs overlap at corners, naturally forming a larger
#           rounded blob — no triangle, no explicit arc formula needed.
# FEATHER – soft-blend width at the blob boundary (pixels).
_DW_BLOB_R  = 15   # ~47% of tile width; large enough to always cover the full edge
_DW_FEATHER = 4
# Floor sprite variants (kept for potential future use).
_DW_FLOOR_VARIANTS = list(range(0xE1E0, 0xE1E7))


def _dungeon_water_bite_mask(neighbor_mask: int) -> np.ndarray:
    """Return a (TILE_H, TILE_W) float32 array — 1.0 = water, 0.0 = floor.

    Each water-neighboring edge contributes a semicircle blob centred on the
    midpoint of that edge.  Adjacent blobs overlap via np.maximum, producing
    larger compound blobs at corners without any triangular narrowing.
    """
    W, H = TILE_W, TILE_H
    R       = float(_DW_BLOB_R)
    FEATHER = max(1.0, float(_DW_FEATHER))

    has_N = bool(neighbor_mask & _DW_N)
    has_E = bool(neighbor_mask & _DW_E)
    has_S = bool(neighbor_mask & _DW_S)
    has_W = bool(neighbor_mask & _DW_W)

    rows = np.arange(H, dtype=np.float32)
    cols = np.arange(W, dtype=np.float32)
    dist_N = rows[:, None]            # distance from top edge
    dist_S = (H - 1 - rows)[:, None] # distance from bottom edge
    dist_W = cols[None, :]            # distance from left edge
    dist_E = (W - 1 - cols)[None, :] # distance from right edge

    half_W = (W - 1) / 2.0
    half_H = (H - 1) / 2.0
    # Offset from the horizontal / vertical tile centre axis
    cols_c = cols[None, :] - half_W   # (1, W)
    rows_c = rows[:, None] - half_H   # (H, 1)

    water_alpha = np.zeros((H, W), dtype=np.float32)

    def _ramp(signed_dist: np.ndarray) -> np.ndarray:
        """signed_dist > 0 = inside blob; returns smooth [0,1] alpha."""
        return np.clip(signed_dist / FEATHER + 1.0, 0.0, 1.0)

    # Each bite is a circle of radius R centred on the midpoint of the edge
    # (row=0, col=half_W for North, etc.).  Only pixels inside the tile receive
    # non-zero alpha, so only the inward semicircle is ever visible.
    if has_N:
        water_alpha = np.maximum(water_alpha, _ramp(R - np.hypot(dist_N, cols_c)))
    if has_S:
        water_alpha = np.maximum(water_alpha, _ramp(R - np.hypot(dist_S, cols_c)))
    if has_W:
        water_alpha = np.maximum(water_alpha, _ramp(R - np.hypot(dist_W, rows_c)))
    if has_E:
        water_alpha = np.maximum(water_alpha, _ramp(R - np.hypot(dist_E, rows_c)))

    return water_alpha


def compose_dungeon_water(floor_cp: int, water_cp: int, neighbor_mask: int) -> str:
    """Composite animated water biting into a floor tile.

    neighbor_mask encodes which cardinal directions HAVE water neighbors.
    Water pixels are alpha-blended over floor pixels in the bite region.
    Returns chr() of the resulting cached codepoint.
    """
    global _composite_next, _tileset
    if _tileset is None:
        return chr(floor_cp)

    key = ('_dw', floor_cp, water_cp, neighbor_mask)
    if key in _composite_cache:
        return chr(_composite_cache[key])

    floor_pixels = _get_tile(floor_cp).astype(np.uint8)
    water_pixels = _get_tile(water_cp).astype(np.uint8)

    if neighbor_mask == 0:
        # No water neighbors — return the plain floor tile.
        result = floor_pixels.copy()
    else:
        # water_alpha [0,1]: 1.0 = full water, 0.0 = full floor.
        # Soft feathered boundary makes animation appear to wash against the shore.
        water_alpha = _dungeon_water_bite_mask(neighbor_mask)  # (H, W) float32
        floor_f = floor_pixels.astype(np.float32)
        water_f = water_pixels.astype(np.float32)
        a = water_alpha[:, :, np.newaxis]                      # broadcast over RGBA
        result = np.clip(floor_f * (1.0 - a) + water_f * a, 0, 255).astype(np.uint8)

    if _composite_free_list:
        cp = _composite_free_list.pop()
    else:
        cp = _composite_next
        _composite_next += 1
    if _deferred_mode:
        _deferred_pixel_store[cp] = result
        _deferred_tiles.append((cp, result))
    else:
        _tileset.set_tile(cp, result)
    _composite_cache[key] = cp
    return chr(cp)


def build_dungeon_water_anim(game_map) -> None:
    """Pre-compose animated water-bite frames for floor tiles that border water.

    For each walkable non-water tile adjacent to at least one water tile,
    compose 5 frames (one per water animation frame) where the water sprite
    bites into the floor tile from the water-neighboring edges.

    Central water tiles are left alone — GlobalWaterAnimation handles them.
    This means the composited edge blends use the exact same water sprites as
    the centre, so there is no seam.

    Stores game_map.dungeon_water_anim = {(x, y): (cp0, cp1, cp2, cp3, cp4)}.
    Safe to call inside deferred mode (background gen thread).
    """
    W, H = game_map.width, game_map.height
    tiles = game_map.tiles
    anim_map: dict = {}

    for x in range(W):
        for y in range(H):
            tile = tiles[x, y]
            # Only process walkable non-water floor tiles.
            if str(tile["name"]) == "Water" or not tile["walkable"]:
                continue

            # Neighbor mask: bit set for each cardinal direction that HAS water.
            nmask = 0
            if y > 0 and str(tiles[x, y - 1]["name"]) == "Water":
                nmask |= _DW_N
            if x < W - 1 and str(tiles[x + 1, y]["name"]) == "Water":
                nmask |= _DW_E
            if y < H - 1 and str(tiles[x, y + 1]["name"]) == "Water":
                nmask |= _DW_S
            if x > 0 and str(tiles[x - 1, y]["name"]) == "Water":
                nmask |= _DW_W

            if nmask == 0:
                continue  # no water neighbors, skip

            # Use the tile's own light codepoint as the floor base.
            floor_cp = int(tile["light"]["ch"])

            frames = tuple(
                ord(compose_dungeon_water(floor_cp, wcp, nmask))
                for wcp in _WATER_FRAME_CPS
            )
            anim_map[(x, y)] = frames

    game_map.dungeon_water_anim = anim_map
    print(f"[sprite_manager] Built dungeon water anim for {len(anim_map)} floor-edge tiles.")


def apply_neighbor_overlay(
    tilemap,
    candidates,
    neighbor_names,
    overlay_sprites: dict,
    overlay_tint_light=None,
    overlay_tint_dark=None,
    out_overlays=None,
) -> None:
    """Composite directional edge overlays onto tiles in *candidates* where they
    border tiles whose names are in *neighbor_names*.

    overlay_sprites maps direction string keys → integer codepoints.  Recognised keys:

      Cardinal  : 'N', 'S', 'E', 'W'
        Applied when that cardinal neighbour is in neighbor_names.

      Inner corners : 'NW', 'NE', 'SW', 'SE'
        Applied when BOTH adjacent cardinals are present; those two cardinals are
        then suppressed (the corner sprite covers them).

      Outer corners : 'NW_outer', 'NE_outer', 'SW_outer', 'SE_outer'
        Applied when ONLY the diagonal is present (convex corner nub); neither
        adjacent cardinal may match.

    Missing keys in overlay_sprites are simply skipped.

    overlay_tint_light / overlay_tint_dark : optional (R, G, B) tuples to
      multiply into every overlay pixel when compositing the light / dark state.
      None means no tint (white pass-through).

    out_overlays : optional dict {(x, y): [codepoints]}; if provided, every
      codepoint applied at each position is recorded here (appended on repeat
      calls to the same position).
    """
    W = tilemap.width
    H = tilemap.height
    for x, y in candidates:
        has_N  = 0 <= y - 1 < H and str(tilemap.tiles[x,     y - 1]["name"]) in neighbor_names
        has_S  = 0 <= y + 1 < H and str(tilemap.tiles[x,     y + 1]["name"]) in neighbor_names
        has_E  = 0 <= x + 1 < W and str(tilemap.tiles[x + 1, y    ]["name"]) in neighbor_names
        has_W  = 0 <= x - 1 < W and str(tilemap.tiles[x - 1, y    ]["name"]) in neighbor_names
        has_NE = 0 <= x + 1 < W and 0 <= y - 1 < H and str(tilemap.tiles[x + 1, y - 1]["name"]) in neighbor_names
        has_NW = 0 <= x - 1 < W and 0 <= y - 1 < H and str(tilemap.tiles[x - 1, y - 1]["name"]) in neighbor_names
        has_SE = 0 <= x + 1 < W and 0 <= y + 1 < H and str(tilemap.tiles[x + 1, y + 1]["name"]) in neighbor_names
        has_SW = 0 <= x - 1 < W and 0 <= y + 1 < H and str(tilemap.tiles[x - 1, y + 1]["name"]) in neighbor_names

        overlays: list[int] = []
        corner_N = corner_S = corner_E = corner_W = False

        # Inner corners: both adjacent cardinals present → one combined sprite
        if has_S and has_W and "SW" in overlay_sprites:
            overlays.append(overlay_sprites["SW"])
            corner_S = corner_W = True
        if has_S and has_E and "SE" in overlay_sprites:
            overlays.append(overlay_sprites["SE"])
            corner_S = corner_E = True
        if has_N and has_E and "NE" in overlay_sprites:
            overlays.append(overlay_sprites["NE"])
            corner_N = corner_E = True
        if has_N and has_W and "NW" in overlay_sprites:
            overlays.append(overlay_sprites["NW"])
            corner_N = corner_W = True

        # Cardinal edges (not already handled by an inner corner)
        if has_N and not corner_N and "N" in overlay_sprites:
            overlays.append(overlay_sprites["N"])
        if has_S and not corner_S and "S" in overlay_sprites:
            overlays.append(overlay_sprites["S"])
        if has_E and not corner_E and "E" in overlay_sprites:
            overlays.append(overlay_sprites["E"])
        if has_W and not corner_W and "W" in overlay_sprites:
            overlays.append(overlay_sprites["W"])

        # Outer corners: only diagonal present, neither adjacent cardinal
        if has_SW and not has_S and not has_W and "SW_outer" in overlay_sprites:
            overlays.append(overlay_sprites["SW_outer"])
        if has_SE and not has_S and not has_E and "SE_outer" in overlay_sprites:
            overlays.append(overlay_sprites["SE_outer"])
        if has_NW and not has_N and not has_W and "NW_outer" in overlay_sprites:
            overlays.append(overlay_sprites["NW_outer"])
        if has_NE and not has_N and not has_E and "NE_outer" in overlay_sprites:
            overlays.append(overlay_sprites["NE_outer"])

        if not overlays:
            continue

        base_dark  = int(tilemap.tiles[x, y]["dark"]["ch"])
        base_light = int(tilemap.tiles[x, y]["light"]["ch"])
        tints_light = ([None] + [overlay_tint_light] * len(overlays)) if overlay_tint_light is not None else None
        tints_dark  = ([None] + [overlay_tint_dark]  * len(overlays)) if overlay_tint_dark  is not None else None
        result = tilemap.tiles[x, y].copy()
        result["dark"]["ch"]  = ord(compose_sprite([base_dark]  + overlays, layer_tints=tints_dark))
        result["light"]["ch"] = ord(compose_sprite([base_light] + overlays, layer_tints=tints_light))
        tilemap.tiles[x, y] = result
        if out_overlays is not None:
            if (x, y) in out_overlays:
                out_overlays[(x, y)].extend(overlays)
            else:
                out_overlays[(x, y)] = list(overlays)


# ---------------------------------------------------------------------------
# Portrait compositor
# ---------------------------------------------------------------------------

_PORTRAIT_CACHE_DIR = os.path.join(os.path.dirname(__file__), "portrait_cache")
_PORTRAIT_PARTS_DIR = os.path.join(os.path.dirname(__file__), "components", "portrait_parts")
# Bump this string to invalidate all cached portraits (e.g. after changing tints or layers)
_PORTRAIT_CACHE_VERSION = "v2"

_VILLAGER_SPRITE_CODEPOINTS: dict = {
    "male": 0xE03C,
    "female": 0xE03D,
    "short": 0xE060,
    "long": 0xE061,
    "beard": 0xE062,
    "cap": 0xE063,
    "hood": 0xE064,
    "tunic": 0xE065,
    "trousers": 0xE066,
    "robe": 0xE067,
    "shoes": 0xE068,
}


# Hair-color → (R, G, B) multiply tint
_HAIR_TINTS: dict = {
    "black":  (30,  20,  20),
    "brown":  (80,  50,  30),
    "blonde": (220, 190, 100),
    "red":    (180, 60,  30),
    "gray":   (150, 150, 150),
    "grey":   (150, 150, 150),
    "white":  (230, 225, 215),
}

# Clothing color word → (R, G, B) multiply tint
_CLOTH_TINTS: dict = {
    "white":  (240, 240, 240),
    "black":  (40,  40,  40),
    "brown":  (100, 65,  35),
    "gray":   (140, 140, 140),
    "grey":   (140, 140, 140),
    "blue":   (50,  80,  180),
    "red":    (180, 40,  40),
    "green":  (40,  140, 50),
    "yellow": (220, 200, 50),
    "purple": (120, 50,  170),
    "linen":  (210, 195, 155),
    "thread": (180, 170, 140),
    "cloth":  (160, 155, 140),
    "leather":(120, 85,  50),
    "silk":   (200, 185, 215),
    "velvet": (100, 60,  120),
    "felt":   (90,  85,  80),
    "torn":   (110, 100, 90),
    "dirty":  (90,  80,  60),
    "worn":   (100, 90,  70),
    "ragged": (100, 90,  70),
    "broken": (100, 80,  50),
    "frayed": (110, 95,  70),
    "gold":   (210, 170, 40),
    "silver": (190, 195, 200),
    "simple": (155, 145, 130),
}

# Skin-tone → base sub-folder key
_SKIN_TO_BASE: dict = {
    "very pale":  "white",
    "pale":       "white",
    "fair":       "white",
    "light olive":"brown",
    "tan":        "brown",
    "brown":      "brown",
    "dark":       "black",
    "very dark":  "black",
}


def _tint_pil(img, tint_rgb: tuple):
    """Return a tinted copy of a PIL RGBA image (multiply each RGB channel)."""
    arr = np.array(img, dtype=np.float32)
    for c, t in enumerate(tint_rgb[:3]):
        arr[..., c] = arr[..., c] * (t / 255.0)
    from PIL import Image as _PILImage
    return _PILImage.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA")


def _extract_cloth_tint(description: str) -> tuple | None:
    """Return the tint for the first recognised word in a clothing slot string."""
    if not description:
        return None
    for word in description.lower().split():
        if word in _CLOTH_TINTS:
            return _CLOTH_TINTS[word]
    return None


def compose_portrait(actor) -> str | None:
    """Build a composited 32×32 portrait PNG for *actor* from portrait_parts layers.

    Reads actor.knowledge for skin_tone, gender, hair_color, hair_style,
    facial_hair, torso, head and accessories slots.

    Results are cached on disk in portrait_cache/<hash>.png.
    Sets actor._portrait_path and returns the path, or None on failure.
    """
    try:
        from PIL import Image
    except ImportError:
        print("[sprite_manager] Pillow not installed — portrait skipped.")
        return None

    know = getattr(actor, "knowledge", {})
    composite_sprite_layers = []
    composite_sprite_tints = []

    # ── Base layer ────────────────────────────────────────────────────────────
    skin       = know.get("skin_tone", "fair")
    gender     = know.get("gender", "Male")
    base_key   = _SKIN_TO_BASE.get(skin, "white")
    gender_key = "female" if gender == "Female" else "male"
    base_path  = os.path.join(_PORTRAIT_PARTS_DIR, "base", f"{base_key}_{gender_key}.png")
    if not os.path.isfile(base_path):
        base_path = os.path.join(_PORTRAIT_PARTS_DIR, "base", "white_male.png")
    if not os.path.isfile(base_path):
        return None

    # ── Cache key ─────────────────────────────────────────────────────────────
    import hashlib
    import json as _json
    _cache_fields = ["skin_tone", "gender", "hair_color", "hair_style",
                     "facial_hair", "torso", "legs", "feet", "head", "accessories"]
    cache_data  = {k: know.get(k) for k in _cache_fields}
    cache_data["_v"] = _PORTRAIT_CACHE_VERSION
    cache_hash  = hashlib.md5(_json.dumps(cache_data, sort_keys=True).encode()).hexdigest()[:12]
    os.makedirs(_PORTRAIT_CACHE_DIR, exist_ok=True)
    out_path = os.path.join(_PORTRAIT_CACHE_DIR, f"{cache_hash}.png")

    if os.path.isfile(out_path):
        actor._portrait_path = out_path
        return out_path

    # ── Build composite ───────────────────────────────────────────────────────
    _log = [f"base={base_key}_{gender_key}"]
    canvas = Image.open(base_path).convert("RGBA")

    # Get skin tone tint from base layer, to apply to clothing layers for better integration.
    if skin in _SKIN_TO_BASE:
        # Sample tint from the base skin layer (assuming it's a solid color).
        r, g, b, _ = canvas.getpixel((TILE_W // 2, TILE_H // 2))
        skin_tint = (r, g, b)

    if gender.lower() == "male":
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["male"])
        composite_sprite_tints.append(skin_tint)
    else:
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["female"])
        composite_sprite_tints.append(skin_tint)

    def _overlay(rel_path: str, tint=None) -> None:
        nonlocal canvas
        full = os.path.join(_PORTRAIT_PARTS_DIR, rel_path)
        if not os.path.isfile(full):
            _log.append(f"MISSING:{rel_path}")
            return
        layer = Image.open(full).convert("RGBA")
        if tint:
            layer = _tint_pil(layer, tint)
        merged = canvas.copy()
        merged.alpha_composite(layer)
        canvas = merged
        _log.append(f"{rel_path} tint={tint}")

    hair_color = know.get("hair_color")
    hair_tint  = _HAIR_TINTS.get(hair_color) if hair_color else None
    hair_style = know.get("hair_style", "short")

    # Torso clothing layer (below hair)
    torso_desc  = know.get("torso") or ""
    torso_lower = torso_desc.lower()
    torso_tint  = _extract_cloth_tint(torso_desc)
    if "robe" in torso_lower:
        _overlay(f"robe/{gender_key}.png", torso_tint)
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["robe"])
        composite_sprite_tints.append(torso_tint)
    elif any(w in torso_lower for w in ("tunic", "shirt", "jerkin")):
        _overlay(f"tunic/{gender_key}.png", torso_tint)
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["tunic"])
        composite_sprite_tints.append(torso_tint)

    # Accessories — necklace
    acc_desc  = know.get("accessories") or ""
    acc_tint  = _extract_cloth_tint(acc_desc)
    if "necklace" in acc_desc.lower():
        _overlay("necklace/necklace.png", acc_tint)

    # Hair
    if hair_tint and hair_color not in ("bald", "hairless"):
        # Switch for style comp
        match hair_style.lower():
            case "long":
                _overlay("hair/long.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["long"])
                composite_sprite_tints.append(hair_tint)

            case "curly":
                _overlay("hair/curly.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["long"])
                composite_sprite_tints.append(hair_tint)

            case "short":
                _overlay("hair/short.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["short"])
                composite_sprite_tints.append(hair_tint)

            case "straight":
                _overlay("hair/straight.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["short"])
                composite_sprite_tints.append(hair_tint)

            case "wavy":
                _overlay("hair/wavy.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["long"])
                composite_sprite_tints.append(hair_tint)

            case _:
                # Pass on no match, BALD!
                pass

    # Facial hair / beard
    facial_hair = know.get("facial_hair")
    if facial_hair and hair_tint:
        match facial_hair.lower():
            case "bearded":
                _overlay("facial_hair/beard.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["beard"])
                composite_sprite_tints.append(hair_tint)
            case "mustached":
                _overlay("facial_hair/mustache.png", hair_tint)
            case "goateed":
                _overlay("facial_hair/goatee.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["beard"])
                composite_sprite_tints.append(hair_tint)
            case "stubbled":
                _overlay("facial_hair/stubble.png", hair_tint)
            case _:
                pass
            
    # Head gear  (on top of hair)
    head_desc  = know.get("head") or ""
    head_lower = head_desc.lower()
    head_tint  = _extract_cloth_tint(head_desc)
    if "hood" in head_lower:
        _overlay("hood/hood.png", head_tint)
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["hood"])
        composite_sprite_tints.append(head_tint)

    elif "cap" in head_lower:
        _overlay("cap/cap.png", head_tint)
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["cap"])
        composite_sprite_tints.append(head_tint)

    elif "hat" in head_lower:
        _overlay("cone_hat/cone_hat.png", head_tint)

    feet_desc = know.get("feet") or ""
    feet_lower = feet_desc.lower()
    feet_tint = _extract_cloth_tint(feet_desc)
    if "shoes" in feet_lower:
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["shoes"])
        composite_sprite_tints.append(feet_tint)
    
    legs_desc = know.get("legs") or ""
    legs_lower = legs_desc.lower()
    legs_tint = _extract_cloth_tint(legs_desc)
    if "trousers" in legs_lower or "pants" in legs_lower:
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["trousers"])
        composite_sprite_tints.append(legs_tint)




    canvas.save(out_path, "PNG")
    print(f"[portrait] {getattr(actor, 'name', '?')} → {cache_hash}.png | layers: {', '.join(_log)}")
    actor._portrait_path = out_path
    # Check if actor is guide
    if not actor.name == "The Guide":
        actor.base_char = compose_sprite(composite_sprite_layers, layer_tints=composite_sprite_tints)
        if hasattr(actor, 'equipment'):
            refresh_actor_sprite(actor)
        else:
            actor.char = actor.base_char

    return out_path


def save_composites_sheet(path: str = "RP/composites.png") -> None:
    """Write all cached composite tiles to a PNG grid for visual inspection."""
    if not _composite_cache or _tileset is None:
        print("[sprite_manager] No composites to save.")
        return
    try:
        from PIL import Image
    except ImportError:
        print("[sprite_manager] Pillow not installed — cannot save composites sheet.")
        return
    cols = 16
    count = len(_composite_cache)
    rows = (count + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * TILE_W, rows * TILE_H), (0, 0, 0, 0))
    for i, cp in enumerate(_composite_cache.values()):
        pixels = _tileset.get_tile(cp)
        tile_img = Image.fromarray(pixels, "RGBA")
        col = i % cols
        row = i // cols
        sheet.paste(tile_img, (col * TILE_W, row * TILE_H))
    sheet.save(path)
    print(f"[sprite_manager] Saved {count} composite tile(s) to '{path}'.")


def save_full_atlas(path: str = "RP/full_atlas.png") -> None:
    """Dump every assigned tileset codepoint to a labelled PNG grid.

    Covers the full private-use range from EXTRAS_START_CP (0xE000) up to
    (but not including) _composite_next, so it shows:
      - Extras sheet tiles  (0xE000–0xEEFF)
      - Composite sprites   (0xEF00 onwards)
    Tiles are arranged left-to-right, top-to-bottom in rows of 32.
    A 1-pixel grey border is drawn around each tile and the codepoint is
    printed as a 4-char hex label in the top-left corner of each cell.
    Free-list slots (recycled) are tinted red so you can see churn.
    """
    if _tileset is None:
        print("[sprite_manager] Tileset not loaded — nothing to dump.")
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[sprite_manager] Pillow not installed — cannot save atlas.")
        return

    free_set = set(_composite_free_list)

    COLS = 32
    BORDER = 1
    CELL_W = TILE_W + BORDER * 2
    CELL_H = TILE_H + BORDER * 2

    start_cp = EXTRAS_START_CP
    end_cp   = _composite_next          # exclusive upper bound
    total    = end_cp - start_cp
    if total <= 0:
        print("[sprite_manager] No codepoints in range to dump.")
        return

    rows = (total + COLS - 1) // COLS
    img_w = COLS * CELL_W
    img_h = rows * CELL_H

    sheet = Image.new("RGBA", (img_w, img_h), (20, 20, 20, 255))
    draw  = ImageDraw.Draw(sheet)

    try:
        font = ImageFont.truetype("C:/Windows/Fonts/cour.ttf", 7)
    except Exception:
        font = ImageFont.load_default()

    for idx in range(total):
        cp    = start_cp + idx
        col   = idx % COLS
        row   = idx // COLS
        px    = col * CELL_W + BORDER
        py    = row * CELL_H + BORDER

        try:
            pixels = _tileset.get_tile(cp)
            tile   = Image.fromarray(pixels, "RGBA")
        except Exception:
            tile = Image.new("RGBA", (TILE_W, TILE_H), (0, 0, 0, 0))

        # Red tint for free-list (recycled, content may be stale)
        if cp in free_set:
            r, g, b, a = tile.split()
            r = r.point(lambda v: min(255, v + 120))
            g = g.point(lambda v: max(0,   v - 60))
            b = b.point(lambda v: max(0,   v - 60))
            tile = Image.merge("RGBA", (r, g, b, a))

        # Checkerboard background so transparency is visible
        check = Image.new("RGBA", (TILE_W, TILE_H), (0, 0, 0, 0))
        cd = ImageDraw.Draw(check)
        sq = 4
        for cy in range(0, TILE_H, sq):
            for cx in range(0, TILE_W, sq):
                c = (60, 60, 60, 255) if (cx // sq + cy // sq) % 2 == 0 else (40, 40, 40, 255)
                cd.rectangle([cx, cy, cx + sq - 1, cy + sq - 1], fill=c)
        combined = Image.alpha_composite(check, tile)
        sheet.paste(combined, (px, py))

        # Border
        border_colour = (180, 60, 60) if cp in free_set else (80, 80, 80)
        draw.rectangle([col * CELL_W, row * CELL_H,
                        col * CELL_W + CELL_W - 1, row * CELL_H + CELL_H - 1],
                       outline=border_colour)

        # Hex label — prefix EXT (extras sheet) or CMP (composite)
        label = f"{'E' if cp < COMPOSITE_START_CP else 'C'}{cp:04X}"
        draw.text((px, py), label, fill=(220, 220, 100, 220), font=font)

    sheet.save(path)
    print(f"[sprite_manager] Full atlas ({total} tiles, {rows} rows) saved to '{path}'.")
    print(f"  Range: 0x{start_cp:04X}–0x{end_cp - 1:04X}   Free slots (red): {len(free_set)}")

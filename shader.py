from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

import sprite_manager

if TYPE_CHECKING:
    import moderngl

# Try to import ModernGL for GPU acceleration
_MODERNGL_AVAILABLE = False
try:
    import moderngl
    _MODERNGL_AVAILABLE = True
except ImportError:
    pass

# Incremented whenever sprite material data changes for any codepoint.
_MATERIAL_CACHE_EPOCH: int = 0

# Try to import scipy for smooth FOV transitions
_SCIPY_AVAILABLE = False
try:
    import scipy.ndimage  # noqa: F401 - availability probe only
    _SCIPY_AVAILABLE = True
except ImportError:
    pass


def _shader_log(msg: str) -> None:
    """Write shader debug info to logs/shader.log — visible in both dev and packaged exe."""
    import os, sys
    try:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(base, "logs", "shader.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as _f:
            _f.write(msg if msg.endswith("\n") else msg + "\n")
    except Exception:
        pass


LIGHT_SCALE = 2  # Higher = faster (fewer pixels computed), relies on GPU bilinear upscaling
_ENGINE_SINGLETON: LightingShaderEngine | None = None

# NOTE: Dirty tracking and material caching optimizations are currently DISABLED
# They caused visual artifacts (mixed up normals, misaligned atlases). The GPU path
# now always does a full atlas rebuild each frame for visual correctness.
# Performance is still excellent due to GPU fragment shader lighting (~3-5x faster than CPU).


def mark_sprite_dirty(world_x: int, world_y: int) -> None:
    """Mark a world tile as dirty when its sprite changes (for incremental GPU updates).
    
    This also bumps material epoch so GPU lookup textures can be refreshed
    even when visible tile IDs remain unchanged.
    """
    global _MATERIAL_CACHE_EPOCH
    _MATERIAL_CACHE_EPOCH += 1


def invalidate_material_cache(codepoint: int) -> None:
    """Notify shader engine that material data changed for a codepoint."""
    global _MATERIAL_CACHE_EPOCH
    _MATERIAL_CACHE_EPOCH += 1


def get_shader_engine() -> LightingShaderEngine | None:
    """Get the global shader engine instance."""
    return _ENGINE_SINGLETON


def set_shader_engine(engine: LightingShaderEngine) -> None:
    """Set the global shader engine instance."""
    global _ENGINE_SINGLETON
    _ENGINE_SINGLETON = engine


@dataclass(frozen=True)
class LightingShaderConfig:
    """Configuration for lighting shader engine.
    
    All parameters are used identically in both CPU and GPU rendering paths.
    Modify these values to adjust lighting appearance and performance.
    """
    # Core lighting parameters
    ambient_floor: float = 0.0  # Base ambient brightness (0.0 = pitch black, 1.0 = full bright)
    explored_mod: float = 0.0  # Brightness multiplier for explored-but-not-visible tiles
    smooth_visibility_blur: bool = False  # Toggle expensive explored/visible edge smoothing passes
    warm_g: float = 0.25  # Green reduction for warm (non-white) lights (higher = more orange)
    warm_b: float = 0.40  # Blue reduction for warm lights (higher = more orange/red)
    directional_contrast: float = 0.5  # Strength of directional lighting detail (0.0 = flat, 1.0+ = strong)
    light_height: float = 1.25  # Height of lights above ground (affects shadow angles)
    
    # Specular parameters
    specular_strength: float = 4.0  # Intensity multiplier for specular highlights
    specular_power: float = 12.0  # Sharpness of specular highlights (higher = tighter spot)
    specular_threshold: float = 0.05  # Minimum light contribution required for specular pass
    
    # Threshold parameters (performance tuning)
    alpha_threshold: float = 1e-4  # Early exit for nearly-transparent pixels
    falloff_threshold: float = 1e-6  # Early exit for extremely weak light contributions
    detail_threshold: float = 0.5  # Threshold for normal_detail/specular_mask activation
    
    # Detail factor clamp range (directional contrast limits)
    detail_factor_min: float = 0.55  # Darkest areas can darken to 55% of base brightness
    detail_factor_max: float = 1.35  # Brightest areas can brighten to 135% of base brightness
    
    # Shadow ray-tracing parameters
    enable_shadows: bool = True  # Enable/disable ray-traced shadows
    shadow_step_size: float = 0.1  # Ray marching step size in tiles (smaller = smoother)
    shadow_max_samples: int = 40  # Maximum ray samples per light
    shadow_threshold: float = 0.015  # Early exit when shadow gets this dark
    shadow_min_distance: float = 0.5  # Don't trace shadows for lights closer than this (tiles)
    shadow_softness: float = 1.0  # Shadow edge diffusion (0.0=no shadow, 1.0=hard, 0.5=soft)


# =============================================================================
# GPU SHADERS - Deferred-style lighting compositor
# =============================================================================
# These shaders EXACTLY replicate the CPU lighting math from build_lightmap().

VERTEX_SHADER = """
#version 330 core

in vec2 in_vert;
in vec2 in_texcoord;
out vec2 v_texcoord;

void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
    v_texcoord = in_texcoord;
}
"""

FRAGMENT_SHADER = """
#version 330 core

uniform sampler2D u_tile_id_atlas;
uniform sampler2D u_lookup_normal;
uniform sampler2D u_lookup_alpha;
uniform sampler2D u_lookup_emission;
uniform sampler2D u_lookup_specular;
uniform sampler2D u_lookup_normal_detail;
uniform sampler2D u_lookup_specular_mask;
uniform sampler2D u_fog_mask;
uniform sampler2D u_visible_mask;
uniform sampler2D u_explored_floor;
uniform sampler2D u_transparency_atlas;  // Tile transparency for ray-traced shadows

uniform vec4 u_lights[256];  // (x, y, radius, intensity)
uniform vec4 u_light_colors[256];  // (is_white, r, g, b)
uniform int u_num_lights;

uniform vec2 u_grid_offset;  // (origin_x, origin_y)
uniform vec2 u_grid_scale;   // (px_per_tile_x, px_per_tile_y)
uniform vec2 u_texture_size; // (out_w, out_h)
uniform float u_ambient_floor;
uniform float u_warm_g;
uniform float u_warm_b;
uniform float u_directional_contrast;
uniform float u_light_height;
uniform float u_specular_strength;
uniform float u_specular_power;
uniform float u_specular_threshold;
uniform float u_alpha_threshold;
uniform float u_falloff_threshold;
uniform float u_detail_threshold;
uniform float u_detail_factor_min;
uniform float u_detail_factor_max;
uniform float u_lookup_layer_count;
uniform vec2 u_lookup_tile_size;

// Shadow ray-tracing uniforms
uniform bool u_enable_shadows;
uniform float u_shadow_step_size;
uniform int u_shadow_max_samples;
uniform float u_shadow_threshold;
uniform float u_shadow_min_distance;
uniform float u_shadow_softness;

in vec2 v_texcoord;
out vec4 frag_color;

// Sample tile transparency at world position for shadow ray marching
float sample_transparency(vec2 world_pos) {
    // Convert world position to texture coordinates
    vec2 tile_pos = world_pos - u_grid_offset;
    vec2 uv = (tile_pos + 0.5) * u_grid_scale / u_texture_size;
    
    // Flip Y for OpenGL convention
    uv.y = 1.0 - uv.y;
    
    // Clamp to valid texture range
    uv = clamp(uv, 0.0, 1.0);
    
    // Sample transparency (alpha channel represents how much light passes through)
    return texture(u_transparency_atlas, uv).r;
}

// Ray-trace shadow from pixel to light source
// Returns shadow factor: 1.0 = fully lit, 0.0 = fully shadowed
float trace_shadow(vec2 pixel_pos, vec2 light_pos, float dist) {
    if (!u_enable_shadows) {
        return 1.0;  // Shadows disabled
    }
    
    // Skip shadow tracing for very close lights (performance optimization)
    if (dist < u_shadow_min_distance) {
        return 1.0;
    }
    
    vec2 dir = (light_pos - pixel_pos) / dist;  // pre-normalized
    vec2 step = dir * u_shadow_step_size;
    
    // Adaptive sample count based on distance (closer = fewer samples needed)
    int max_samples = int(min(float(u_shadow_max_samples), dist / u_shadow_step_size));
    
    float shadow = 1.0;
    // Start slightly offset to avoid self-shadowing
    vec2 pos = pixel_pos + step * 0.75;
    
    // March along ray with smooth bilinear sampling
    for (int samples = 0; samples < max_samples; samples++) {
        float transparency = sample_transparency(pos);
        
        // Accumulate shadow softly (u_shadow_softness: 0.9=hard, 0.5=diffuse)
        shadow *= mix(1.0, transparency, u_shadow_softness);
        
        // Early exit if shadow is very dark
        if (shadow < u_shadow_threshold) {
            return 0.0;
        }
        
        pos += step;
    }
    
    return shadow;
}

// Fast specular curve approximating integer powers.
float fast_specular_curve(float x, float power) {
    int p = int(max(1.0, power));
    if (p >= 12) {
        float x2 = x * x;
        float x4 = x2 * x2;
        float x8 = x4 * x4;
        return x8 * x4;
    }
    if (p >= 8) {
        float x2 = x * x;
        float x4 = x2 * x2;
        return x4 * x4;
    }
    if (p >= 4) {
        float x2 = x * x;
        return x2 * x2;
    }
    if (p >= 2) {
        return x * x;
    }
    return x;
}

// Material lookup through a tile-id indirection atlas.
vec2 lookup_uv_from_layer(float layer_idx, vec2 tile_uv) {
    // Keep lookup UV in packed top-down order; avoid double Y inversion.
    float y_norm = (layer_idx + tile_uv.y) / max(1.0, u_lookup_layer_count);
    return vec2(tile_uv.x, y_norm);
}

void main() {
    // Compute pixel coordinate first (NumPy-style Y: top to bottom).
    vec2 pixel_coord = vec2(v_texcoord.x, 1.0 - v_texcoord.y) * u_texture_size;

    // Tile id atlas stores layer_id + 1 (0 means empty).
    float tile_id_enc = texture(u_tile_id_atlas, v_texcoord).r;
    float layer_idx = floor(tile_id_enc + 0.5) - 1.0;

    // Empty tile: ambient floor only.
    if (layer_idx < 0.0) {
        float amb = u_ambient_floor;
        frag_color = vec4(amb, amb, amb, 1.0);
        return;
    }

    // Local pixel coordinate inside its tile (for material sampling).
    vec2 tile_px = mod(pixel_coord, u_grid_scale);
    vec2 tile_uv = (floor(tile_px) + vec2(0.5, 0.5)) / u_lookup_tile_size;
    tile_uv = clamp(tile_uv, vec2(0.0, 0.0), vec2(1.0, 1.0));
    vec2 mat_uv = lookup_uv_from_layer(layer_idx, tile_uv);

    // Sample material channels from lookup textures.
    vec3 normal = texture(u_lookup_normal, mat_uv).rgb;
    float alpha = texture(u_lookup_alpha, mat_uv).r;
    vec3 emission = texture(u_lookup_emission, mat_uv).rgb;
    vec3 specular_map = texture(u_lookup_specular, mat_uv).rgb;
    float normal_detail = texture(u_lookup_normal_detail, mat_uv).r;
    float specular_mask = texture(u_lookup_specular_mask, mat_uv).r;
    
    // Early exit for transparent pixels
    if (alpha < u_alpha_threshold) {
        // Ambient floor only
        float amb = u_ambient_floor;
        frag_color = vec4(amb, amb, amb, 1.0);
        return;
    }
    
    
    // Compute world-space position (EXACTLY matches CPU grid_x, grid_y)
    // Note: pixel_coord already uses NumPy Y orientation.
    vec2 pixel_pos = u_grid_offset + (pixel_coord + 0.5) / u_grid_scale - 0.5;
    
    // Accumulate lighting
    float warm_acc = 0.0;
    float white_acc = 0.0;
    vec3 color_acc = vec3(0.0);  // Custom-colored light contributions
    vec3 specular_acc = vec3(0.0);
    
    // Precompute constants
    float light_height_sq = u_light_height * u_light_height;
    float spec_strength = u_specular_strength;
    bool has_spec = (normal_detail > u_detail_threshold) || (specular_mask > u_detail_threshold);
    
    // Accumulate contribution from each light (EXACTLY matches CPU loop)
    for (int i = 0; i < u_num_lights; i++) {
        vec4 light = u_lights[i];
        float lx = light.x;
        float ly = light.y;
        float radius = light.z;
        float intensity = light.w;
        bool is_white = u_light_colors[i].x > 0.5;
        
        // Compute distance to light (EXACTLY matches CPU dx, dy, dist_sq)
        float dx = lx - pixel_pos.x;
        float dy = ly - pixel_pos.y;
        float dist_sq = dx * dx + dy * dy;
        float radius_sq = radius * radius;
        
        // Early exit if outside light radius
        if (dist_sq > radius_sq) {
            continue;
        }
        
        float dist = sqrt(dist_sq);
        
        // Ray-trace shadow from pixel to light
        // IMPORTANT: Only apply shadows to transparent tiles (floors)
        // Wall faces should always be lit in top-down view
        float pixel_tile_transparency = sample_transparency(pixel_pos);
        float shadow = 1.0;
        
        // Only trace shadows for transparent tiles (floors, not walls)
        if (pixel_tile_transparency > 0.0) {
            shadow = trace_shadow(pixel_pos, vec2(lx, ly), dist);
            if (shadow < u_shadow_threshold) {
                continue;  // Fully shadowed, skip this light
            }
        }
        // Walls (opaque tiles) skip shadow tracing and receive full light
        
        // Compute falloff (EXACTLY matches CPU: (radius_sq - dist_sq) / radius_sq * intensity)
        float falloff = clamp((radius_sq - dist_sq) / radius_sq, 0.0, 1.0) * intensity;
        if (falloff < u_falloff_threshold) {
            continue;
        }
        
        // Compute light direction (EXACTLY matches CPU inv_len calculation)
        float inv_len = 1.0 / sqrt(dist_sq + light_height_sq);
        float light_dir_x = dx * inv_len;
        float light_dir_y = dy * inv_len;
        float light_dir_z = u_light_height * inv_len;
        
        // Diffuse lighting (EXACTLY matches CPU diffuse calculation)
        float diffuse = max(0.0, dot(normal, vec3(light_dir_x, light_dir_y, light_dir_z)));
        
        // Contribution (EXACTLY matches CPU) - apply shadow here
        float contribution = falloff * diffuse * alpha * shadow;
        if (contribution < u_falloff_threshold) {
            continue;
        }
        
        // Accumulate to appropriate channel (EXACTLY matches CPU)
        vec3 light_rgb = vec3(u_light_colors[i].y, u_light_colors[i].z, u_light_colors[i].w);
        bool has_custom_color = dot(light_rgb, light_rgb) > 0.001;
        if (has_custom_color) {
            color_acc += contribution * light_rgb;
        } else if (is_white) {
            white_acc += contribution;
        } else {
            warm_acc += contribution;
        }
        
        // Specular pass (EXACTLY matches CPU conditions and math)
        if (has_spec && contribution > u_specular_threshold) {
            // Compute half vector (view direction is (0, 0, 1))
            // EXACTLY matches CPU half vector calculation
            float half_z_unnorm = light_dir_z + 1.0;
            float half_inv_len = 1.0 / sqrt(light_dir_x * light_dir_x + 
                                           light_dir_y * light_dir_y + 
                                           half_z_unnorm * half_z_unnorm);
            float half_x = light_dir_x * half_inv_len;
            float half_y = light_dir_y * half_inv_len;
            float half_z = half_z_unnorm * half_inv_len;
            
            // Blinn-Phong specular (EXACTLY matches CPU)
            float specular = normal.x * half_x +
                            normal.y * half_y +
                            normal.z * half_z;
            specular = max(0.0, specular);
            specular = fast_specular_curve(specular, u_specular_power);
            specular *= contribution * spec_strength;
            
            if (specular > u_falloff_threshold) {
                specular_acc += specular * specular_map;
            }
        }
    }
    
    // Final composition (EXACTLY matches CPU)
    float total_acc = warm_acc + white_acc;
    float brightness = clamp(u_ambient_floor + total_acc, 0.0, 1.0);
    
    // Compute warm/white ratio (EXACTLY matches CPU)
    float white_ratio = (total_acc > u_falloff_threshold) ? clamp(white_acc / total_acc, 0.0, 1.0) : 1.0;
    float warm_ratio = 1.0 - white_ratio;
    
    // Base color with warm tint (EXACTLY matches CPU)
    vec3 base_rgb;
    base_rgb.r = brightness;
    base_rgb.g = brightness * (warm_ratio * (1.0 - u_warm_g * brightness) + white_ratio);
    base_rgb.b = brightness * (warm_ratio * (1.0 - u_warm_b * brightness) + white_ratio);
    
    // Detail factor (EXACTLY matches CPU directional contrast)
    float detail_factor = clamp(1.0 + u_directional_contrast * (total_acc - 0.5), u_detail_factor_min, u_detail_factor_max);
    detail_factor = 1.0 - alpha * (1.0 - detail_factor);
    
    // Apply detail, add specular and emissive (EXACTLY matches CPU)
    base_rgb *= detail_factor;
    base_rgb += color_acc;  // Custom-colored lights added directly as RGB
    base_rgb += specular_acc;
    base_rgb += emission;
    base_rgb = clamp(base_rgb, 0.0, 1.0);
    
    // Final visibility/exploration blend (moved from CPU to GPU).
    float floor_strength = texture(u_fog_mask, v_texcoord).r;
    float visible_strength = texture(u_visible_mask, v_texcoord).r;
    vec3 explored_floor = texture(u_explored_floor, v_texcoord).rgb;
    vec3 floor_rgb = explored_floor * floor_strength;
    vec3 final_rgb = floor_rgb * (1.0 - visible_strength) + base_rgb * visible_strength;

    frag_color = vec4(clamp(final_rgb, 0.0, 1.0), 1.0);
}
"""


class LightingShaderEngine:
    """Lighting shader engine backed by a ModernGL deferred compositor."""

    def __init__(self, mode: str = "gpu", config: LightingShaderConfig | None = None) -> None:
        self.mode = "gpu"
        self.config = config or LightingShaderConfig()
        self._buffer_shape: tuple[int, int] = (0, 0)
        self._last_gpu_total_ms: float = 0.0
        self._gpu_output_buffer: np.ndarray | None = None
        if mode != "gpu":
            print(f"[WARNING]: LightingShaderEngine is GPU-only; forcing mode='gpu' (requested '{mode}')")
        
        _shader_log(f"[DEBUG]: LightingShaderEngine initialized with mode='{mode}', moderngl_available={_MODERNGL_AVAILABLE}")
        
        # Material atlases used by the GPU pipeline.
        self._tile_id_atlas: np.ndarray | None = None
        self._transparency_atlas: np.ndarray | None = None
        
        # GPU state (lazy initialized)
        self._gpu_ctx: moderngl.Context | None = None
        self._gpu_program: moderngl.Program | None = None
        self._gpu_vao: moderngl.VertexArray | None = None
        self._gpu_fbo: moderngl.Framebuffer | None = None
        self._gpu_textures: dict[str, moderngl.Texture] = {}
        self._gpu_initialized = False
        self._gpu_failed = False
        
        # GPU optimization state
        self._atlas_prev_ch: np.ndarray | None = None
        self._atlas_prev_vis: np.ndarray | None = None
        self._atlas_prev_trans: np.ndarray | None = None
        self._gpu_prev_viewport: tuple[int, int, int, int] | None = None  # (origin_x, origin_y, view_w, view_h)
        self._gpu_pbo: moderngl.Buffer | None = None  # Pixel buffer object for async uploads
        self._gpu_pbo_size: int = 0
        
        # Pre-allocate flipped buffers for GPU uploads (optimization)
        self._gpu_flipped_normal: np.ndarray | None = None
        self._gpu_flipped_alpha: np.ndarray | None = None
        self._gpu_flipped_emission: np.ndarray | None = None
        self._gpu_flipped_specular: np.ndarray | None = None
        self._gpu_flipped_normal_detail: np.ndarray | None = None
        self._gpu_flipped_specular_mask: np.ndarray | None = None
        self._gpu_flipped_transparency: np.ndarray | None = None
        self._gpu_flipped_tile_id: np.ndarray | None = None
        self._gpu_flipped_fog_mask: np.ndarray | None = None
        self._gpu_flipped_visible_mask: np.ndarray | None = None
        self._gpu_flipped_explored_floor: np.ndarray | None = None

        # GPU material lookup state (tile-id indirection path)
        self._gpu_material_lookup_signature: tuple[int, int, tuple[int, ...]] | None = None
        self._gpu_layer_count: int = 0
        self._gpu_cp_to_layer: dict[int, int] = {}
        self._gpu_material_epoch_seen: int = -1
        
        # GPU fog-mask cache (optimization - avoids per-frame gaussian/zoom)
        self._gpu_vis_prev_visible: np.ndarray | None = None
        self._gpu_vis_prev_explored: np.ndarray | None = None
        self._gpu_fog_mask_cache: np.ndarray | None = None
        self._gpu_visible_mask_cache: np.ndarray | None = None
        self._gpu_unexplored_bleed_cache: np.ndarray | None = None
        self._gpu_vis_cache_shape: tuple[int, int] | None = None

    def set_external_gpu_context(self, ctx) -> bool:
        """Attach an externally managed ModernGL context for unified rendering."""
        if not _MODERNGL_AVAILABLE or ctx is None:
            return False
        try:
            if self._gpu_ctx is ctx and self._gpu_initialized:
                return True

            # Drop GPU objects tied to any previous context.
            try:
                if self._gpu_fbo is not None:
                    self._gpu_fbo.release()
            except Exception:
                pass
            self._gpu_fbo = None

            for _name, _tex in list(self._gpu_textures.items()):
                try:
                    _tex.release()
                except Exception:
                    pass
            self._gpu_textures = {}

            try:
                if self._gpu_vao is not None:
                    self._gpu_vao.release()
            except Exception:
                pass
            self._gpu_vao = None

            try:
                if self._gpu_program is not None:
                    self._gpu_program.release()
            except Exception:
                pass
            self._gpu_program = None

            try:
                if self._gpu_pbo is not None:
                    self._gpu_pbo.release()
            except Exception:
                pass
            self._gpu_pbo = None
            self._gpu_pbo_size = 0

            self._gpu_ctx = ctx
            self._gpu_initialized = False
            self._gpu_failed = False
            self._gpu_material_lookup_signature = None
            self._gpu_layer_count = 0
            self._gpu_cp_to_layer.clear()
            self._gpu_material_epoch_seen = -1
            self._gpu_flipped_tile_id = None
            return True
        except Exception:
            return False
    
    def _init_gpu(self) -> bool:
        """Initialize GPU context, shaders, and resources.
        
        Returns:
            True if GPU initialization succeeded, False otherwise.
        """
        if self._gpu_initialized:
            return True
        if self._gpu_failed:
            return False
        if not _MODERNGL_AVAILABLE:
            _shader_log("[ERROR]: ModernGL not available")
            self._gpu_failed = True
            return False
            
        try:
            # Use adopted shared context when provided, otherwise create standalone.
            if self._gpu_ctx is None:
                self._gpu_ctx = moderngl.create_standalone_context()
            
            # Compile shader program
            self._gpu_program = self._gpu_ctx.program(
                vertex_shader=VERTEX_SHADER,
                fragment_shader=FRAGMENT_SHADER,
            )
            
            # Create fullscreen quad vertices
            vertices = np.array([
                -1.0, -1.0,  0.0, 0.0,  # bottom-left
                 1.0, -1.0,  1.0, 0.0,  # bottom-right
                -1.0,  1.0,  0.0, 1.0,  # top-left
                 1.0,  1.0,  1.0, 1.0,  # top-right
            ], dtype=np.float32)
            
            vbo = self._gpu_ctx.buffer(vertices.tobytes())
            self._gpu_vao = self._gpu_ctx.vertex_array(
                self._gpu_program,
                [(vbo, '2f 2f', 'in_vert', 'in_texcoord')],
            )
            
            self._gpu_initialized = True
            _shader_log("[INFO]: GPU lighting initialized successfully")
            return True
            
        except Exception as e:
            _shader_log(f"[ERROR]: GPU init failed: {e}")
            import traceback as _tb; _shader_log(_tb.format_exc())
            self._gpu_failed = True
            self._gpu_ctx = None
            self._gpu_program = None
            self._gpu_vao = None
            return False
    
    def _ensure_gpu_textures(self, out_h: int, out_w: int) -> None:
        """Ensure GPU textures and framebuffer are allocated for the target resolution."""
        if not self._gpu_ctx:
            return
            
        # Check if we need to resize
        needs_resize = not self._gpu_fbo or self._gpu_fbo.size != (out_w, out_h)
        
        if needs_resize:
            # Create/recreate textures for material atlases
            texture_configs = [
                ('tile_id_atlas', 1),
                ('fog_mask', 1),
                ('visible_mask', 1),
                ('explored_floor', 3),
                ('transparency_atlas', 1),  # Tile transparency for ray-traced shadows
            ]
            
            # Create separate occlusion mask texture - stores per-light FOV masks
            # Layout: (view_w, view_h * 256) where each vertical slice is one light's FOV
            # We'll recreate this each frame as it depends on viewport size
            if 'occlusion_mask' in self._gpu_textures:
                self._gpu_textures['occlusion_mask'].release()
            # Note: We'll resize this dynamically based on viewport dimensions
            
            for name, components in texture_configs:
                if name in self._gpu_textures:
                    self._gpu_textures[name].release()
                self._gpu_textures[name] = self._gpu_ctx.texture(
                    (out_w, out_h), components, dtype='f4'
                )
                if name == 'tile_id_atlas':
                    # IDs must remain exact; interpolation would corrupt layer lookup.
                    self._gpu_textures[name].filter = (moderngl.NEAREST, moderngl.NEAREST)
                elif name == 'transparency_atlas':
                    # Bilinear filtering gives smoother shadow gradients.
                    self._gpu_textures[name].filter = (moderngl.LINEAR, moderngl.LINEAR)
                else:
                    self._gpu_textures[name].filter = (moderngl.LINEAR, moderngl.LINEAR)
            
            # Create output texture and framebuffer
            if 'output' in self._gpu_textures:
                self._gpu_textures['output'].release()
            self._gpu_textures['output'] = self._gpu_ctx.texture(
                (out_w, out_h), 4, dtype='f1'
            )
            
            if self._gpu_fbo:
                self._gpu_fbo.release()
            self._gpu_fbo = self._gpu_ctx.framebuffer(
                color_attachments=[self._gpu_textures['output']]
            )
            
            # Recreate PBO for async uploads (sized for largest atlas)
            pbo_size = out_w * out_h * 4 * 4  # 4 bytes per component, max 4 components
            if self._gpu_pbo:
                self._gpu_pbo.release()
            self._gpu_pbo = self._gpu_ctx.buffer(reserve=pbo_size)
            self._gpu_pbo_size = pbo_size

    def _ensure_buffers(self, out_h: int, out_w: int) -> None:
        if self._buffer_shape == (out_h, out_w):
            return
        
        # Invalidate flipped upload buffers on resize.
        self._gpu_flipped_transparency = None
        self._gpu_flipped_tile_id = None
        self._gpu_flipped_fog_mask = None
        self._gpu_flipped_visible_mask = None
        self._gpu_flipped_explored_floor = None
        self._gpu_material_lookup_signature = None
        self._gpu_layer_count = 0
        self._gpu_cp_to_layer.clear()
        self._gpu_material_epoch_seen = -1
        
        # Invalidate GPU output buffer on resize
        self._gpu_output_buffer = None

        # Invalidate GPU visibility mask cache on resize
        self._gpu_vis_prev_visible = None
        self._gpu_vis_prev_explored = None
        self._gpu_fog_mask_cache = None
        self._gpu_visible_mask_cache = None
        self._gpu_unexplored_bleed_cache = None
        self._gpu_vis_cache_shape = None

        # Invalidate atlas scene snapshots on resize.
        self._atlas_prev_ch = None
        self._atlas_prev_vis = None
        self._atlas_prev_trans = None
        
        # Use float32 atlases for GPU uploads.
        self._transparency_atlas = np.zeros((out_h, out_w), dtype=np.float32)
        self._tile_id_atlas = np.zeros((out_h, out_w), dtype=np.float32)
        self._buffer_shape = (out_h, out_w)

    def _resize2d_nearest(self, src: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
        """Resize a 2D array with nearest sampling for compatibility fallbacks."""
        in_h, in_w = src.shape[:2]
        if in_h == out_h and in_w == out_w:
            return src
        y_idx = np.minimum((np.arange(out_h, dtype=np.int32) * in_h) // max(1, out_h), in_h - 1)
        x_idx = np.minimum((np.arange(out_w, dtype=np.int32) * in_w) // max(1, out_w), in_w - 1)
        return src[y_idx[:, None], x_idx[None, :]]

    def _resize3d_nearest(self, src: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
        """Resize an HxWxC array with nearest sampling for compatibility fallbacks."""
        in_h, in_w = src.shape[:2]
        if in_h == out_h and in_w == out_w:
            return src
        y_idx = np.minimum((np.arange(out_h, dtype=np.int32) * in_h) // max(1, out_h), in_h - 1)
        x_idx = np.minimum((np.arange(out_w, dtype=np.int32) * in_w) // max(1, out_w), in_w - 1)
        return src[y_idx[:, None], x_idx[None, :], :]

    def _get_compat_material(self, cp: int, scale: int, out_h: int, out_w: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return packed material channels with compatibility fallbacks for older sprite_manager builds."""
        get_packed = getattr(sprite_manager, "get_packed_material", None)
        if callable(get_packed):
            try:
                return get_packed(cp, scale, out_h, out_w)
            except Exception:
                pass

        normals, alpha = sprite_manager.get_normal_field(cp)
        normals = np.asarray(normals, dtype=np.float32)
        alpha = np.asarray(alpha, dtype=np.float32)

        if normals.shape[0] != out_h or normals.shape[1] != out_w:
            normals = self._resize3d_nearest(normals, out_h, out_w)
        if alpha.shape[0] != out_h or alpha.shape[1] != out_w:
            alpha = self._resize2d_nearest(alpha, out_h, out_w)

        alpha = np.clip(alpha, 0.0, 1.0)
        normals = normals * alpha[..., None]

        emission = np.zeros((out_h, out_w, 3), dtype=np.float32)
        specular = np.zeros((out_h, out_w, 3), dtype=np.float32)
        normal_detail = np.zeros((out_h, out_w), dtype=np.float32)
        specular_mask = np.zeros((out_h, out_w), dtype=np.float32)
        return normals, alpha, emission, specular, normal_detail, specular_mask

    def _ensure_gpu_lookup_textures(self, tile_w: int, tile_h: int, layer_count: int) -> None:
        """Ensure material lookup textures are allocated for current tile size/layer count."""
        if not self._gpu_ctx:
            return

        lookup_size = (tile_w, max(1, tile_h * max(1, layer_count)))
        lookup_configs = [
            ('lookup_normal', 3),
            ('lookup_alpha', 1),
            ('lookup_emission', 3),
            ('lookup_specular', 3),
            ('lookup_normal_detail', 1),
            ('lookup_specular_mask', 1),
        ]

        for name, components in lookup_configs:
            tex = self._gpu_textures.get(name)
            if tex is None or tex.size != lookup_size:
                if tex is not None:
                    tex.release()
                tex = self._gpu_ctx.texture(lookup_size, components, dtype='f4')
                # Lookup should be exact per texel/layer.
                tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
                self._gpu_textures[name] = tex

    def _rebuild_material_lookup_gpu(self, cp_to_layer: dict[int, int], scale: int,
                                     px_per_tile_x: int, px_per_tile_y: int) -> None:
        """Build compact GPU lookup textures indexed by tile-id layer."""
        layer_count = max(1, len(cp_to_layer))
        self._ensure_gpu_lookup_textures(px_per_tile_x, px_per_tile_y, layer_count)

        h_total = px_per_tile_y * layer_count
        w_total = px_per_tile_x
        lookup_normal = np.zeros((h_total, w_total, 3), dtype=np.float32)
        lookup_alpha = np.zeros((h_total, w_total), dtype=np.float32)
        lookup_emission = np.zeros((h_total, w_total, 3), dtype=np.float32)
        lookup_specular = np.zeros((h_total, w_total, 3), dtype=np.float32)
        lookup_normal_detail = np.zeros((h_total, w_total), dtype=np.float32)
        lookup_specular_mask = np.zeros((h_total, w_total), dtype=np.float32)

        # cp_to_layer stores +1 encoded layer ids; convert to zero-based row index.
        for cp, enc_layer in cp_to_layer.items():
            layer_idx = int(enc_layer) - 1
            if layer_idx < 0:
                continue
            y0 = layer_idx * px_per_tile_y
            y1 = y0 + px_per_tile_y
            n_view, a_view, e_view, s_view, nd_view, sm_view = self._get_compat_material(
                cp=int(cp),
                scale=scale,
                out_h=px_per_tile_y,
                out_w=px_per_tile_x,
            )
            lookup_normal[y0:y1, :, :] = n_view
            lookup_alpha[y0:y1, :] = a_view
            lookup_emission[y0:y1, :, :] = e_view
            lookup_specular[y0:y1, :, :] = s_view
            lookup_normal_detail[y0:y1, :] = nd_view
            lookup_specular_mask[y0:y1, :] = sm_view

        self._gpu_textures['lookup_normal'].write(lookup_normal)
        self._gpu_textures['lookup_alpha'].write(lookup_alpha)
        self._gpu_textures['lookup_emission'].write(lookup_emission)
        self._gpu_textures['lookup_specular'].write(lookup_specular)
        self._gpu_textures['lookup_normal_detail'].write(lookup_normal_detail)
        self._gpu_textures['lookup_specular_mask'].write(lookup_specular_mask)
    
    def _build_lightmap_gpu(self, game_map, console, readback: bool = True) -> np.ndarray | None:
        """GPU-accelerated lightmap generation using ModernGL fragment shaders.
        
        This method EXACTLY replicates the CPU lighting math but performs the
        per-pixel accumulation on the GPU via fragment shaders.
        """
        import time as _time

        _gpu_t0 = _time.perf_counter()
        _gpu_profile: dict[str, float] = {}

        def _profile_mark(section: str, start_time: float) -> float:
            _gpu_profile[section] = _gpu_profile.get(section, 0.0) + ((_time.perf_counter() - start_time) * 1000.0)
            return _time.perf_counter()

        def _profile_span(section: str, start_time: float, end_time: float | None = None) -> None:
            t1 = _time.perf_counter() if end_time is None else end_time
            _gpu_profile[section] = _gpu_profile.get(section, 0.0) + max(0.0, (t1 - start_time) * 1000.0)

        def _flush_gpu_profile() -> None:
            total_ms = (_time.perf_counter() - _gpu_t0) * 1000.0
            self._last_gpu_total_ms = float(total_ms)
            eng = getattr(game_map, "engine", None)
            if eng is None:
                return
            if not hasattr(eng, "profile_external_ms"):
                return
            try:
                for k, v in _gpu_profile.items():
                    eng.profile_external_ms(k, float(v))
                eng.profile_external_ms("lm_gpu_total", total_ms)
            except Exception:
                pass

        if not self._init_gpu():
            return None

        _seg_t = _time.perf_counter()
        
        tile_w, tile_h = sprite_manager.get_loaded_tile_size()
        origin_x, origin_y, view_w, view_h = game_map.get_viewport(console)
        x_slice = slice(origin_x, origin_x + view_w)
        y_slice = slice(origin_y, origin_y + view_h)
        visible = np.asarray(game_map.visible[x_slice, y_slice], dtype=bool).T
        explored = np.asarray(game_map.explored[x_slice, y_slice], dtype=bool).T
        scale = max(1, int(LIGHT_SCALE))
        out_w = max(1, (view_w * tile_w) // scale)
        out_h = max(1, (view_h * tile_h) // scale)
        px_per_tile_x = max(1, tile_w // scale)
        px_per_tile_y = max(1, tile_h // scale)
        _seg_t = _profile_mark("lm_gpu_setup", _seg_t)

        explored_floor_f32: np.ndarray | None = None
        if np.any(explored):
            _explored_floor_t0 = _time.perf_counter()
            dark_bg = np.asarray(game_map.tiles["dark"]["bg"][x_slice, y_slice], dtype=np.float32).transpose(1, 0, 2)
            light_bg = np.asarray(game_map.tiles["light"]["bg"][x_slice, y_slice], dtype=np.float32).transpose(1, 0, 2)
            with np.errstate(divide="ignore", invalid="ignore"):
                explored_ratio = np.where(light_bg > 0.0, dark_bg / light_bg, 0.0)
            explored_ratio = np.clip(explored_ratio, 0.0, float(self.config.explored_mod))
            explored_floor_f32 = np.repeat(
                np.repeat(explored_ratio, px_per_tile_y, axis=0),
                px_per_tile_x,
                axis=1,
            )[:out_h, :out_w]
            explored_floor_f32 = np.clip(explored_floor_f32, 0.0, 1.0).astype(np.float32, copy=False)
            _profile_span("lm_epl_flr", _explored_floor_t0)

        _vis_cache_valid = (
            self._gpu_fog_mask_cache is not None
            and self._gpu_visible_mask_cache is not None
            and self._gpu_unexplored_bleed_cache is not None
            and self._gpu_vis_prev_visible is not None
            and self._gpu_vis_prev_explored is not None
            and self._gpu_vis_cache_shape == (out_h, out_w)
            and self._gpu_vis_prev_visible.shape == visible.shape
            and self._gpu_vis_prev_explored.shape == explored.shape
            and np.array_equal(visible, self._gpu_vis_prev_visible)
            and np.array_equal(explored, self._gpu_vis_prev_explored)
        )
        if _vis_cache_valid:
            fog_mask = self._gpu_fog_mask_cache
            visible_mask = self._gpu_visible_mask_cache
            unexplored_bleed_mask = self._gpu_unexplored_bleed_cache
        else:
            _vis_rebuild_t0 = _time.perf_counter()
            # Rebuild visibility masks for GPU shader - cached!
            
            tile_h, tile_w = visible.shape

            visible_tile = visible.astype(np.float32)
            explored_tile = explored.astype(np.float32)
            unexplored_tile = (~explored).astype(np.float32)
            support_visibility = visible | explored

            if self.config.smooth_visibility_blur and _SCIPY_AVAILABLE:
                _smooth_t0 = _time.perf_counter()
                from scipy.ndimage import  binary_dilation, zoom


                # soft field
                visible_soft = visible_tile.copy()
                edge_1 = (
                    binary_dilation(visible, iterations=1) & ~visible & support_visibility
                )
                edge_2 = (
                    binary_dilation(visible, iterations=2) & ~binary_dilation(visible, iterations=1) & support_visibility
                )

                # Feather strength
                visible_soft[edge_1] = 0.5
                visible_soft[edge_2] = 0.15

                # Fog fielding
                fog_soft = explored_tile * self.config.explored_mod

                # Upscale
                upscale = (px_per_tile_y, px_per_tile_x)
                visible_mask = zoom(visible_soft, upscale, order=1)
                #print(f"visible_mask after zoom: min={visible_mask.min()}, max={visible_mask.max()}, mean={visible_mask.mean()}")
                fog_mask = zoom(fog_soft, upscale, order=1)
                unexplored_bleed_mask = zoom(unexplored_tile, upscale, order=1)
                _profile_span("lm_gpu_smooth", _smooth_t0)
            else:
                fog_mask = np.repeat(
                    np.repeat(
                        explored_tile * self.config.explored_mod,
                        px_per_tile_y,
                        axis=0,
                    ),
                    px_per_tile_x,
                    axis=1,
                )

                visible_mask = np.repeat(
                    np.repeat(
                        visible_tile,
                        px_per_tile_y,
                        axis=0,
                    ),
                    px_per_tile_x,
                    axis=1,
                )

                unexplored_bleed_mask = np.repeat(
                    np.repeat(
                        unexplored_tile,
                        px_per_tile_y,
                        axis=0,
                    ),
                    px_per_tile_x,
                    axis=1,
                )

            # Clamp
            fog_mask = np.clip(fog_mask[:out_h, :out_w], 0.0, 1.0)
            visible_mask = np.clip(visible_mask[:out_h, :out_w], 0.0, 1.0)
            unexplored_bleed_mask = np.clip(unexplored_bleed_mask[:out_h, :out_w], 0.0, 1.0)

            self._gpu_fog_mask_cache = np.array(fog_mask, copy=True)
            self._gpu_visible_mask_cache = np.array(visible_mask, copy=True)
            self._gpu_unexplored_bleed_cache = np.array(unexplored_bleed_mask, copy=True)
            self._gpu_vis_prev_visible = np.array(visible, copy=True)
            self._gpu_vis_prev_explored = np.array(explored, copy=True)
            self._gpu_vis_cache_shape = (out_h, out_w)
            _profile_span("lm_gpu_vis_rebuild", _vis_rebuild_t0)

        visible_hard_mask = np.repeat(
            np.repeat(visible.astype(np.float32), px_per_tile_y, axis=0),
            px_per_tile_x,
            axis=1,
        )[:out_h, :out_w]
        if self.config.smooth_visibility_blur and np.any(visible_hard_mask > 0.0):
            visible_mask = visible_mask * (
                1.0 - 0.35 * unexplored_bleed_mask * visible_hard_mask
            )
        visible_mask = np.clip(visible_mask, 0.0, 1.0)
        _seg_t = _profile_mark("lm_gpu_vis_post", _seg_t)
        
        # Ensure CPU buffers and GPU resources
        _ensure_t0 = _time.perf_counter()
        self._ensure_buffers(out_h, out_w)
        self._ensure_gpu_textures(out_h, out_w)
        _profile_span("lm_gpu_resource_ensure", _ensure_t0)
        
        # Handle sunlit case (fast path)
        if getattr(game_map, "sunlit", False):
            if readback:
                out = np.zeros((out_h, out_w, 4), dtype=np.uint8)
                out[..., :3] = 190
                out[..., 3] = 255
                _gpu_profile["lm_gpu_sunlit_fastpath"] = (_time.perf_counter() - _seg_t) * 1000.0
                _flush_gpu_profile()
                return out
            if self._gpu_fbo is not None and self._gpu_ctx is not None:
                c = 190.0 / 255.0
                self._gpu_fbo.use()
                self._gpu_ctx.clear(c, c, c, 1.0)
            _gpu_profile["lm_gpu_sunlit_fastpath"] = (_time.perf_counter() - _seg_t) * 1000.0
            _flush_gpu_profile()
            return None
        
        # Check if viewport changed (camera moved) - requires full atlas rebuild
        viewport = (origin_x, origin_y, view_w, view_h)
        viewport_changed = (self._gpu_prev_viewport != viewport)
        if viewport_changed:
            self._gpu_prev_viewport = viewport

        material_epoch_changed = (self._gpu_material_epoch_seen != _MATERIAL_CACHE_EPOCH)
        
        # Early exit optimization: Check if scene has any lights
        active_lights = list(getattr(game_map, "_active_lights", []) or [])
        has_lights = len(active_lights) > 0

        # Skip atlas rebuild when visible scene inputs are unchanged.
        # Compare exact arrays (no hash collisions) and avoid per-frame .tobytes() copies.
        # IMPORTANT: console.ch is indexed in screen-space (0..view_w-1, 0..view_h-1).
        _ch_view = np.asarray(console.ch[0:view_w, 0:view_h])
        _vis_arr = np.asarray(game_map.visible[x_slice, y_slice], dtype=np.uint8)
        _trans_arr = np.asarray(game_map.tiles["transparent"][x_slice, y_slice], dtype=np.uint8)
        _need_atlas_rebuild = viewport_changed or material_epoch_changed
        if not _need_atlas_rebuild:
            if self._atlas_prev_ch is None or self._atlas_prev_vis is None or self._atlas_prev_trans is None:
                _need_atlas_rebuild = True
            elif not np.array_equal(_ch_view, self._atlas_prev_ch):
                _need_atlas_rebuild = True
            elif not np.array_equal(_vis_arr, self._atlas_prev_vis):
                _need_atlas_rebuild = True
            elif not np.array_equal(_trans_arr, self._atlas_prev_trans):
                _need_atlas_rebuild = True
        
        _atlas_t0 = _time.perf_counter()
        if _need_atlas_rebuild:
            _atlas_build_t0 = _time.perf_counter()
            # Build tile-id and transparency atlases for this viewport.
            self._gpu_cp_to_layer = self._build_material_atlases_gpu(
                game_map,
                console,
                origin_x,
                origin_y,
                view_w,
                view_h,
                out_w,
                out_h,
                scale,
                px_per_tile_x,
                px_per_tile_y,
            )
            _profile_span("lm_gpu_atlas_build", _atlas_build_t0)
            self._atlas_prev_ch = np.array(_ch_view, copy=True)
            self._atlas_prev_vis = np.array(_vis_arr, copy=True)
            self._atlas_prev_trans = np.array(_trans_arr, copy=True)

            lookup_signature = (
                int(px_per_tile_x),
                int(px_per_tile_y),
                tuple(sorted(self._gpu_cp_to_layer.keys())),
            )
            if lookup_signature != self._gpu_material_lookup_signature:
                _lookup_t0 = _time.perf_counter()
                self._rebuild_material_lookup_gpu(
                    cp_to_layer=self._gpu_cp_to_layer,
                    scale=scale,
                    px_per_tile_x=px_per_tile_x,
                    px_per_tile_y=px_per_tile_y,
                )
                _profile_span("lm_gpu_lookup_build", _lookup_t0)
                self._gpu_material_lookup_signature = lookup_signature

            self._gpu_layer_count = max(1, len(self._gpu_cp_to_layer))
            self._gpu_material_epoch_seen = _MATERIAL_CACHE_EPOCH
        
        # Ensure flipped upload buffers are allocated (always needed even when reusing)
        if self._gpu_flipped_tile_id is None or self._gpu_flipped_tile_id.shape != self._tile_id_atlas.shape:
            self._gpu_flipped_tile_id = np.empty_like(self._tile_id_atlas)
            self._gpu_flipped_transparency = np.empty_like(self._transparency_atlas)
            _need_atlas_rebuild = True  # Force upload after buffer reallocation
        
        if _need_atlas_rebuild:
            _atlas_upload_t0 = _time.perf_counter()
            # Flip Y axis in-place (NumPy Y=0 at top, OpenGL Y=0 at bottom)
            np.copyto(self._gpu_flipped_tile_id, self._tile_id_atlas[::-1])
            np.copyto(self._gpu_flipped_transparency, self._transparency_atlas[::-1])
            
            # Upload to GPU — per-frame payload now reduced to IDs + transparency.
            self._gpu_textures['tile_id_atlas'].write(self._gpu_flipped_tile_id)
            self._gpu_textures['transparency_atlas'].write(self._gpu_flipped_transparency)
            _profile_span("lm_gpu_atlas_upload", _atlas_upload_t0)
        _profile_span("lm_gpu_atlas", _atlas_t0)

        
        # Bind textures to shader
        _bind_t0 = _time.perf_counter()
        for i, name in enumerate([
            'tile_id_atlas',
            'lookup_normal',
            'lookup_alpha',
            'lookup_emission',
            'lookup_specular',
            'lookup_normal_detail',
            'lookup_specular_mask',
            'fog_mask',
            'visible_mask',
            'explored_floor',
            'transparency_atlas',
        ]):
            self._gpu_textures[name].use(location=i)
            self._gpu_program[f'u_{name}'] = i
        _profile_span("lm_gpu_bind_textures", _bind_t0)

        _blend_upload_t0 = _time.perf_counter()
        if self._gpu_flipped_fog_mask is None or self._gpu_flipped_fog_mask.shape != fog_mask.shape:
            self._gpu_flipped_fog_mask = np.empty_like(fog_mask)
            self._gpu_flipped_visible_mask = np.empty_like(visible_mask)
            self._gpu_flipped_explored_floor = np.zeros((out_h, out_w, 3), dtype=np.float32)

        explored_mod = float(self.config.explored_mod)
        if explored_mod > 0.0:
            np.copyto(self._gpu_flipped_fog_mask, (fog_mask / explored_mod)[::-1])
        else:
            self._gpu_flipped_fog_mask.fill(0.0)
        np.copyto(self._gpu_flipped_visible_mask, visible_mask[::-1])

        if explored_floor_f32 is not None:
            np.copyto(self._gpu_flipped_explored_floor, explored_floor_f32[::-1])
        else:
            self._gpu_flipped_explored_floor.fill(0.0)

        self._gpu_textures['fog_mask'].write(self._gpu_flipped_fog_mask)
        self._gpu_textures['visible_mask'].write(self._gpu_flipped_visible_mask)
        self._gpu_textures['explored_floor'].write(self._gpu_flipped_explored_floor)
        _profile_span("lm_gpu_blend_upload", _blend_upload_t0)

        self._gpu_program['u_lookup_layer_count'] = float(max(1, self._gpu_layer_count))
        self._gpu_program['u_lookup_tile_size'] = (float(px_per_tile_x), float(px_per_tile_y))
        
        # Prepare light data (already fetched above for early exit check)
        num_lights = min(len(active_lights), 256)
        
        # Early exit for completely dark scenes (no lights and already checked for emissive)
        if num_lights == 0 and not has_lights and readback:
            # Return ambient-only result (matches CPU behavior)
            out = np.zeros((out_h, out_w, 4), dtype=np.uint8)
            out[..., 3] = 255
            if np.any(visible):
                # Apply minimal ambient to visible tiles
                out[..., :3] = int(self.config.ambient_floor * 255)
            if explored_floor_f32 is not None:
                explored_mod = float(self.config.explored_mod)
                if explored_mod > 0.0:
                    floor_strength = np.clip(fog_mask / explored_mod, 0.0, 1.0)
                else:
                    floor_strength = np.zeros_like(fog_mask)
                visible_strength = visible_mask
                base_rgb = explored_floor_f32 * floor_strength[..., None]
                out[..., :3] = np.clip(
                    base_rgb * (1.0 - visible_strength[..., None])
                    + (out[..., :3].astype(np.float32) / 255.0) * visible_strength[..., None],
                    0.0,
                    1.0,
                )
                out[..., :3] = (out[..., :3] * 255.0).astype(np.uint8)
            _gpu_profile["lm_gpu_uniforms"] = _gpu_profile.get("lm_gpu_uniforms", 0.0)
            _gpu_profile["lm_gpu_dark_fastpath"] = (_time.perf_counter() - _seg_t) * 1000.0
            _flush_gpu_profile()
            return out
        
        light_data = np.zeros((256, 4), dtype=np.float32)
        light_colors = np.zeros((256, 4), dtype=np.float32)
        
        
        _light_pack_t0 = _time.perf_counter()
        for i, light in enumerate(active_lights[:256]):
            light_data[i] = [
                float(light.get("x", origin_x)),
                float(light.get("y", origin_y)),
                max(1.0, float(light.get("radius", 1.0) or 1.0)),
                float(np.clip(light.get("intensity", 1.0) or 1.0, 0.0, 1.0)),
            ]
            light_colors[i, 0] = 1.0 if light.get("is_white", False) else 0.0
            lc = light.get("color", None)
            if lc is not None:
                light_colors[i, 1] = float(lc[0])
                light_colors[i, 2] = float(lc[1])
                light_colors[i, 3] = float(lc[2])
        _profile_span("lm_gpu_light_pack", _light_pack_t0)
        
        # Set uniforms
        _uniform_t0 = _time.perf_counter()
        self._gpu_program['u_lights'].write(light_data.tobytes())
        self._gpu_program['u_light_colors'].write(light_colors.tobytes())
        self._gpu_program['u_num_lights'] = num_lights
        # DISABLED: self._gpu_program['u_occlusion_size'] = (float(view_w), float(view_h))
        self._gpu_program['u_grid_offset'] = (float(origin_x), float(origin_y))
        self._gpu_program['u_grid_scale'] = (float(px_per_tile_x), float(px_per_tile_y))
        self._gpu_program['u_texture_size'] = (float(out_w), float(out_h))
        self._gpu_program['u_ambient_floor'] = self.config.ambient_floor
        self._gpu_program['u_warm_g'] = self.config.warm_g
        self._gpu_program['u_warm_b'] = self.config.warm_b
        self._gpu_program['u_directional_contrast'] = self.config.directional_contrast
        self._gpu_program['u_light_height'] = self.config.light_height
        self._gpu_program['u_specular_strength'] = self.config.specular_strength
        self._gpu_program['u_specular_power'] = self.config.specular_power
        self._gpu_program['u_specular_threshold'] = self.config.specular_threshold
        self._gpu_program['u_alpha_threshold'] = self.config.alpha_threshold
        self._gpu_program['u_falloff_threshold'] = self.config.falloff_threshold
        self._gpu_program['u_detail_threshold'] = self.config.detail_threshold
        self._gpu_program['u_detail_factor_min'] = self.config.detail_factor_min
        self._gpu_program['u_detail_factor_max'] = self.config.detail_factor_max
        
        # Shadow ray-tracing uniforms
        self._gpu_program['u_enable_shadows'] = self.config.enable_shadows
        self._gpu_program['u_shadow_step_size'] = self.config.shadow_step_size
        self._gpu_program['u_shadow_max_samples'] = self.config.shadow_max_samples
        self._gpu_program['u_shadow_threshold'] = self.config.shadow_threshold
        self._gpu_program['u_shadow_min_distance'] = self.config.shadow_min_distance
        self._gpu_program['u_shadow_softness'] = self.config.shadow_softness
        _profile_span("lm_gpu_uniform_write", _uniform_t0)

        _seg_t = _profile_mark("lm_gpu_uniforms", _seg_t)
        
        # Render to framebuffer
        _draw_t0 = _time.perf_counter()
        self._gpu_fbo.use()
        self._gpu_ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._gpu_vao.render(moderngl.TRIANGLE_STRIP)
        _profile_span("lm_gpu_draw_only", _draw_t0)

        _seg_t = _profile_mark("lm_gpu_draw", _seg_t)

        # Unification path: keep result in GPU target and skip CPU readback.
        if not readback:
            _gpu_profile["lm_gpu_readback"] = 0.0
            _flush_gpu_profile()
            return None
        
        # Download result
        _readback_t0 = _time.perf_counter()
        raw = self._gpu_fbo.read(components=4, dtype='f1')
        
        # Reuse output buffer to avoid allocation every frame
        if self._gpu_output_buffer is None or self._gpu_output_buffer.shape != (out_h, out_w, 4):
            self._gpu_output_buffer = np.empty((out_h, out_w, 4), dtype=np.uint8)
        
        out = np.frombuffer(raw, dtype=np.uint8).reshape((out_h, out_w, 4))
        # Flip Y in-place into pre-allocated buffer
        np.copyto(self._gpu_output_buffer, out[::-1])
        out = self._gpu_output_buffer
        _profile_span("lm_gpu_readback_only", _readback_t0)

        _seg_t = _profile_mark("lm_gpu_readback", _seg_t)
        #print("TEST")
        
        _final_blend_t0 = _time.perf_counter()
        # Final blend is now done in the fragment shader.
        _profile_span("lm_gpu_final_blend", _final_blend_t0)

        _flush_gpu_profile()


        return out
    
    def _build_material_atlases_gpu(self, game_map, console, origin_x: int, origin_y: int,
                                    view_w: int, view_h: int, out_w: int, out_h: int,
                                    scale: int, px_per_tile_x: int, px_per_tile_y: int) -> dict[int, int]:
        """Build tile-id and transparency atlases for GPU material indirection.

        Returns:
            Mapping of codepoint -> encoded layer id (layer + 1, zero reserved).
        """
        x_slice = slice(origin_x, origin_x + view_w)
        y_slice = slice(origin_y, origin_y + view_h)

        # Clear atlases
        self._tile_id_atlas.fill(0.0)
        self._transparency_atlas.fill(1.0)  # Default to fully transparent (light passes through)

        visible = np.asarray(game_map.visible[x_slice, y_slice], dtype=bool).T

        # Build transparency atlas from tile data for ray-traced shadow sampling
        # IMPORTANT: Transparency for LIGHT, not visibility - windows are transparent to light
        tile_transparent = np.asarray(game_map.tiles["transparent"][x_slice, y_slice], dtype=np.float32).T
        tile_names = np.asarray(game_map.tiles["name"][x_slice, y_slice]).T

        # Vectorized transparency atlas construction.
        # The codebase uses exact tile name matching for windows, so use the same
        # fast path here instead of per-frame lowercase substring scans.
        window_mask = (tile_names == "Window")  # (view_h, view_w) bool
        # Merged transparency: windows always pass light through (1.0), others use tile value
        merged_trans = np.where(window_mask, np.float32(1.0), tile_transparent.astype(np.float32))
        # Expand to pixel resolution via np.repeat, then clip to atlas bounds
        trans_expanded = np.repeat(np.repeat(merged_trans, px_per_tile_y, axis=0), px_per_tile_x, axis=1)
        self._transparency_atlas[:] = trans_expanded[:out_h, :out_w]

        cp_to_layer: dict[int, int] = {}
        if not np.any(visible):
            return cp_to_layer

        tile_x0 = (np.arange(view_w, dtype=np.int32) * px_per_tile_x)
        tile_x1 = (np.arange(1, view_w + 1, dtype=np.int32) * px_per_tile_x)
        tile_y0 = (np.arange(view_h, dtype=np.int32) * px_per_tile_y)
        tile_y1 = (np.arange(1, view_h + 1, dtype=np.int32) * px_per_tile_y)
        tile_x1 = np.clip(np.maximum(tile_x1, tile_x0 + 1), 1, out_w)
        tile_y1 = np.clip(np.maximum(tile_y1, tile_y0 + 1), 1, out_h)

        # Visible tile pass: assign compact material layers and write tile-id atlas.
        gather_coords = np.argwhere(visible)
        for tile_y, tile_x in gather_coords:
            tx_int = int(tile_x)
            ty_int = int(tile_y)
            cp = int(console.ch[tx_int, ty_int])

            enc_layer = cp_to_layer.get(cp)
            if enc_layer is None:
                # 0 is reserved for empty/unassigned, so encode as index+1.
                enc_layer = len(cp_to_layer) + 1
                cp_to_layer[cp] = enc_layer

            px0 = int(tile_x0[tx_int])
            px1 = int(tile_x1[tx_int])
            py0 = int(tile_y0[ty_int])
            py1 = int(tile_y1[ty_int])
            if px1 <= px0 or py1 <= py0:
                continue

            self._tile_id_atlas[py0:py1, px0:px1] = float(enc_layer)

        return cp_to_layer
    
    def build_lightmap(self, game_map, console) -> np.ndarray:
        """Return a full-resolution RGBA lightmap for the current frame."""
        try:
            lm = self._build_lightmap_gpu(game_map, console)
        except Exception as e:
            print(f"[ERROR]: GPU lightmap build failed: {e}")
            import traceback as _tb; _shader_log(_tb.format_exc())
            raise

        if lm is None:
            raise RuntimeError("GPU lightmap build failed: ModernGL is unavailable or initialization failed")
        return lm

    def render_lightmap_to_gpu_target(self, game_map, console) -> bool:
        """Render the lightmap into the internal ModernGL output texture.

        This path performs no CPU readback.
        """
        if not _MODERNGL_AVAILABLE:
            return False
        try:
            return self._build_lightmap_gpu(game_map, console, readback=False) is None and self._gpu_initialized
        except Exception as e:
            print(f"[ERROR]: GPU target lightmap render failed: {e}")
            return False
def get_lighting_engine(mode: str | None = None) -> LightingShaderEngine:
    """Return a shared lighting engine instance used by map render callers.
    
    Args:
        mode: "gpu". If None, auto-detects from settings.json and forces GPU.
    """
    global _ENGINE_SINGLETON
    
    # Auto-detect mode from settings if not specified
    if mode is None:
        try:
            import json, sys as _sys, os as _os
            _base = _sys._MEIPASS if getattr(_sys, "frozen", False) else _os.path.dirname(_os.path.abspath(__file__))
            with open(_os.path.join(_base, "json", "settings.json"), 'r') as f:
                text = '\n'.join(line for line in f if not line.strip().startswith('//'))
                settings = json.loads(text)
                mode = settings.get("lighting_mode", "gpu")
                #print(f"[DEBUG]: Auto-detected lighting_mode from settings.json: '{mode}'")
        except Exception as e:
            print(f"[DEBUG]: Failed to read settings.json, defaulting to GPU: {e}")
            mode = "gpu"

    if mode != "gpu":
        print(f"[WARNING]: Requested lighting mode '{mode}' is no longer supported; using 'gpu'")
        mode = "gpu"
    
    if _ENGINE_SINGLETON is None or _ENGINE_SINGLETON.mode != mode:
        # Read optional config overrides from settings.json
        _cfg_kwargs: dict = {}
        try:
            import json as _json
            import sys as _sys2, os as _os2
            _base2 = _sys2._MEIPASS if getattr(_sys2, "frozen", False) else _os2.path.dirname(_os2.path.abspath(__file__))
            with open(_os2.path.join(_base2, "json", "settings.json"), 'r') as _f:
                _txt = '\n'.join(line for line in _f if not line.strip().startswith('//'))
                _s = _json.loads(_txt)
            if "shadow_softness" in _s:
                _cfg_kwargs["shadow_softness"] = float(_s["shadow_softness"])
            if "smooth_visibility_blur" in _s:
                _cfg_kwargs["smooth_visibility_blur"] = bool(_s["smooth_visibility_blur"])
        except Exception:
            pass
        _cfg = LightingShaderConfig(**_cfg_kwargs) if _cfg_kwargs else LightingShaderConfig()
        _ENGINE_SINGLETON = LightingShaderEngine(mode=mode, config=_cfg)
        # Ensure the singleton is set for dirty-tracking
        set_shader_engine(_ENGINE_SINGLETON)
    return _ENGINE_SINGLETON


def build_all_lighting_passes(game_map, console, mode: str | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compatibility facade for callers expecting (diffuse, specular, emissive).
    
    Args:
        mode: "gpu". If None, auto-detects from settings.json.
    """
    diffuse = get_lighting_engine(mode=mode).build_lightmap(game_map, console)
    specular = np.zeros_like(diffuse)
    emissive = np.zeros_like(diffuse)
    specular[..., 3] = 255
    emissive[..., 3] = 255
    return diffuse, specular, emissive
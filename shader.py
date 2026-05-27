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

# Try to import scipy for smooth FOV transitions
_SCIPY_AVAILABLE = False
try:
    from scipy.ndimage import distance_transform_edt
    _SCIPY_AVAILABLE = True
except ImportError:
    pass


LIGHT_SCALE = 2  # Higher = faster (fewer pixels computed), relies on GPU bilinear upscaling
_ENGINE_SINGLETON: LightingShaderEngine | None = None

# NOTE: Dirty tracking and material caching optimizations are currently DISABLED
# They caused visual artifacts (mixed up normals, misaligned atlases). The GPU path
# now always does a full atlas rebuild each frame for visual correctness.
# Performance is still excellent due to GPU fragment shader lighting (~3-5x faster than CPU).


def mark_sprite_dirty(world_x: int, world_y: int) -> None:
    """Mark a world tile as dirty when its sprite changes (for incremental GPU updates).
    
    DISABLED: Now doing full atlas rebuild every frame for visual correctness.
    """
    pass  # No-op: dirty tracking disabled


def invalidate_material_cache(codepoint: int) -> None:
    """Invalidate cached GPU material data when a sprite's material changes.
    
    DISABLED: Now doing full atlas rebuild every frame for visual correctness.
    """
    pass  # No-op: material caching disabled


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
    ambient_floor: float = 0.1  # Base ambient brightness (0.0 = pitch black, 1.0 = full bright)
    explored_mod: float = 0.5  # Brightness multiplier for explored-but-not-visible tiles
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
    shadow_max_samples: int = 80  # Maximum ray samples per light
    shadow_threshold: float = 0.015  # Early exit when shadow gets this dark
    shadow_min_distance: float = 0.5  # Don't trace shadows for lights closer than this (tiles)
    shadow_softness: float = 0.9  # Shadow edge diffusion (0.0=no shadow, 1.0=hard, 0.5=soft)


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

uniform sampler2D u_normal_atlas;
uniform sampler2D u_alpha_atlas;
uniform sampler2D u_emission_atlas;
uniform sampler2D u_specular_atlas;
uniform sampler2D u_normal_detail_atlas;
uniform sampler2D u_specular_mask_atlas;
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

// Fast specular curve - EXACTLY matches CPU _fast_specular_curve
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

void main() {
    // Sample material atlases
    vec3 normal = texture(u_normal_atlas, v_texcoord).rgb;
    float alpha = texture(u_alpha_atlas, v_texcoord).r;
    vec3 emission = texture(u_emission_atlas, v_texcoord).rgb;
    vec3 specular_map = texture(u_specular_atlas, v_texcoord).rgb;
    float normal_detail = texture(u_normal_detail_atlas, v_texcoord).r;
    float specular_mask = texture(u_specular_mask_atlas, v_texcoord).r;
    
    // Early exit for transparent pixels
    if (alpha < u_alpha_threshold) {
        // Ambient floor only
        float amb = u_ambient_floor;
        frag_color = vec4(amb, amb, amb, 1.0);
        return;
    }
    
    
    // Compute world-space position (EXACTLY matches CPU grid_x, grid_y)
    // Note: flip Y because OpenGL has Y=0 at bottom, NumPy has Y=0 at top
    vec2 pixel_coord = vec2(v_texcoord.x, 1.0 - v_texcoord.y) * u_texture_size;
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
    
    frag_color = vec4(base_rgb, 1.0);
}
"""


class LightingShaderEngine:
    """Lighting shader engine with CPU (NumPy) and GPU (ModernGL) backends.
    
    Modes:
    - 'cpu': Original NumPy-based lighting accumulation
    - 'gpu': Fragment shader-based deferred compositor (requires ModernGL)
    
    The GPU mode EXACTLY replicates CPU visual output by using identical
    lighting equations in fragment shaders.
    """

    def __init__(self, mode: str = "cpu", config: LightingShaderConfig | None = None) -> None:
        self.mode = mode
        self.config = config or LightingShaderConfig()
        self._buffer_shape: tuple[int, int] = (0, 0)
        
        print(f"[DEBUG]: LightingShaderEngine initialized with mode='{mode}', moderngl_available={_MODERNGL_AVAILABLE}")
        
        # CPU buffers
        self._normal_atlas: np.ndarray | None = None
        self._alpha_atlas: np.ndarray | None = None
        self._warm_acc: np.ndarray | None = None
        self._white_acc: np.ndarray | None = None
        self._specular_acc: np.ndarray | None = None
        self._base_rgb: np.ndarray | None = None
        self._emission_atlas: np.ndarray | None = None
        self._specular_atlas: np.ndarray | None = None
        self._normal_detail_atlas: np.ndarray | None = None
        self._specular_mask_atlas: np.ndarray | None = None
        self._grid_x: np.ndarray | None = None
        self._grid_y: np.ndarray | None = None
        self._x_idx: np.ndarray | None = None
        self._y_idx: np.ndarray | None = None
        self._static_light_bounds_cache: dict[tuple[float, float, float, float, float, float, float, int, int], tuple[int, int, int, int]] = {}
        # Vectorized light processing buffers
        self._light_positions: np.ndarray | None = None
        self._light_radii: np.ndarray | None = None
        self._light_intensities: np.ndarray | None = None
        self._light_is_white: np.ndarray | None = None
        
        # GPU state (lazy initialized)
        self._gpu_ctx: moderngl.Context | None = None
        self._gpu_program: moderngl.Program | None = None
        self._gpu_vao: moderngl.VertexArray | None = None
        self._gpu_fbo: moderngl.Framebuffer | None = None
        self._gpu_textures: dict[str, moderngl.Texture] = {}
        self._gpu_initialized = False
        self._gpu_failed = False
        
        # GPU optimization state
        self._gpu_atlas_cache: dict[tuple, tuple] = {}  # (cp, block_h, block_w) -> material tuple
        self._atlas_prev_ch: np.ndarray | None = None
        self._atlas_prev_vis: np.ndarray | None = None
        self._atlas_prev_trans: np.ndarray | None = None
        self._gpu_dirty_tiles: set[tuple[int, int]] = set()  # (tile_x, tile_y) needing update
        self._gpu_prev_viewport: tuple[int, int, int, int] | None = None  # (origin_x, origin_y, view_w, view_h)
        self._gpu_atlas_persistent: bool = False  # Track if atlas can be reused
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
        
        # FOV fade cache (optimization - expensive distance transform)
        self._fade_cache_visible: np.ndarray | None = None
        self._fade_cache_viewport: tuple[int, int, int, int] | None = None
        self._fade_cache_map: np.ndarray | None = None

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
            print("[ERROR]: ModernGL not available - install with: pip install moderngl")
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
            print("[INFO]: GPU lighting initialized successfully")
            return True
            
        except Exception as e:
            print(f"[ERROR]: GPU initialization failed: {e}")
            import traceback
            traceback.print_exc()
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
            # Invalidate atlas cache on resize
            self._gpu_atlas_persistent = False
            self._gpu_dirty_tiles.clear()
            
            # Create/recreate textures for material atlases
            texture_configs = [
                ('normal_atlas', 3),
                ('alpha_atlas', 1),
                ('emission_atlas', 3),
                ('specular_atlas', 3),
                ('normal_detail_atlas', 1),
                ('specular_mask_atlas', 1),
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
                # Use BILINEAR filtering for transparency to get smooth shadow gradients
                # This removes jagged tile boundaries
                if name == 'transparency_atlas':
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
        
        # Invalidate flipped buffer cache on resize
        self._gpu_flipped_normal = None
        self._gpu_flipped_alpha = None
        self._gpu_flipped_emission = None
        self._gpu_flipped_specular = None
        self._gpu_flipped_normal_detail = None
        self._gpu_flipped_specular_mask = None
        self._gpu_flipped_transparency = None
        
        # Invalidate FOV fade cache on resize
        self._fade_cache_map = None
        self._fade_cache_viewport = None
        self._fade_cache_visible = None
        
        # Invalidate GPU output buffer on resize
        self._gpu_output_buffer = None

        # Invalidate material cache and atlas scene snapshots on resize.
        self._gpu_atlas_cache.clear()
        self._atlas_prev_ch = None
        self._atlas_prev_vis = None
        self._atlas_prev_trans = None
        
        # Use float32 throughout to avoid expensive conversions
        self._normal_atlas = np.zeros((out_h, out_w, 3), dtype=np.float32)
        self._alpha_atlas = np.zeros((out_h, out_w), dtype=np.float32)
        self._warm_acc = np.zeros((out_h, out_w), dtype=np.float32)
        self._white_acc = np.zeros((out_h, out_w), dtype=np.float32)
        self._specular_acc = np.zeros((out_h, out_w, 3), dtype=np.float32)
        self._base_rgb = np.zeros((out_h, out_w, 3), dtype=np.float32)
        self._emission_atlas = np.zeros((out_h, out_w, 3), dtype=np.float32)
        self._specular_atlas = np.zeros((out_h, out_w, 3), dtype=np.float32)
        self._normal_detail_atlas = np.zeros((out_h, out_w), dtype=np.float32)
        self._specular_mask_atlas = np.zeros((out_h, out_w), dtype=np.float32)
        self._transparency_atlas = np.zeros((out_h, out_w), dtype=np.float32)
        self._grid_x = np.zeros((1, out_w), dtype=np.float32)
        self._grid_y = np.zeros((out_h, 1), dtype=np.float32)
        self._x_idx = np.arange(out_w, dtype=np.float32)
        self._y_idx = np.arange(out_h, dtype=np.float32)
        self._buffer_shape = (out_h, out_w)

    def _fast_specular_curve(self, specular: np.ndarray) -> np.ndarray:
        """Approximate specular exponent using repeated squaring (avoids np.power)."""
        p = int(max(1.0, float(self.config.specular_power)))
        x = specular
        if p >= 12:
            x2 = x * x
            x4 = x2 * x2
            x8 = x4 * x4
            return x8 * x4
        if p >= 8:
            x2 = x * x
            x4 = x2 * x2
            return x4 * x4
        if p >= 4:
            x2 = x * x
            return x2 * x2
        if p >= 2:
            return x * x
        return x

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

        def _flush_gpu_profile() -> None:
            eng = getattr(game_map, "engine", None)
            if eng is None:
                return
            if not hasattr(eng, "profile_external_ms"):
                return
            try:
                for k, v in _gpu_profile.items():
                    eng.profile_external_ms(k, float(v))
                eng.profile_external_ms("lm_gpu_total", (_time.perf_counter() - _gpu_t0) * 1000.0)
            except Exception:
                pass

        if not self._init_gpu():
            # Fallback to CPU only when a CPU image is requested.
            if readback:
                return self._build_lightmap_cpu(game_map, console)
            return None

        _seg_t = _time.perf_counter()
        
        tile_w, tile_h = sprite_manager.get_loaded_tile_size()
        origin_x, origin_y, view_w, view_h = game_map.get_viewport(console)
        x_slice = slice(origin_x, origin_x + view_w)
        y_slice = slice(origin_y, origin_y + view_h)
        scale = max(1, int(LIGHT_SCALE))
        out_w = max(1, (view_w * tile_w) // scale)
        out_h = max(1, (view_h * tile_h) // scale)
        px_per_tile_x = max(1, tile_w // scale)
        px_per_tile_y = max(1, tile_h // scale)
        
        # Ensure CPU buffers and GPU resources
        self._ensure_buffers(out_h, out_w)
        self._ensure_gpu_textures(out_h, out_w)
        
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
        
        # Early exit optimization: Check if scene has any lights
        active_lights = list(getattr(game_map, "_active_lights", []) or [])
        has_lights = len(active_lights) > 0
        
        # Skip atlas rebuild when visible scene inputs are unchanged.
        # Compare exact arrays (no hash collisions) and avoid per-frame .tobytes() copies.
        # IMPORTANT: console.ch is indexed in screen-space (0..view_w-1, 0..view_h-1).
        _ch_view = np.asarray(console.ch[0:view_w, 0:view_h])
        _vis_arr = np.asarray(game_map.visible[x_slice, y_slice], dtype=np.uint8)
        _trans_arr = np.asarray(game_map.tiles["transparent"][x_slice, y_slice], dtype=np.uint8)
        _need_atlas_rebuild = viewport_changed
        if not _need_atlas_rebuild:
            if self._atlas_prev_ch is None or self._atlas_prev_vis is None or self._atlas_prev_trans is None:
                _need_atlas_rebuild = True
            elif not np.array_equal(_ch_view, self._atlas_prev_ch):
                _need_atlas_rebuild = True
            elif not np.array_equal(_vis_arr, self._atlas_prev_vis):
                _need_atlas_rebuild = True
            elif not np.array_equal(_trans_arr, self._atlas_prev_trans):
                _need_atlas_rebuild = True
        
        if _need_atlas_rebuild:
            # Build material atlases (full rebuild for visual correctness)
            self._build_material_atlases_gpu(game_map, console, origin_x, origin_y, view_w, view_h,
                                             out_w, out_h, scale, px_per_tile_x, px_per_tile_y)
            self._atlas_prev_ch = np.array(_ch_view, copy=True)
            self._atlas_prev_vis = np.array(_vis_arr, copy=True)
            self._atlas_prev_trans = np.array(_trans_arr, copy=True)
        
        # Ensure flipped upload buffers are allocated (always needed even when reusing)
        if self._gpu_flipped_normal is None or self._gpu_flipped_normal.shape != self._normal_atlas.shape:
            self._gpu_flipped_normal = np.empty_like(self._normal_atlas)
            self._gpu_flipped_alpha = np.empty_like(self._alpha_atlas)
            self._gpu_flipped_emission = np.empty_like(self._emission_atlas)
            self._gpu_flipped_specular = np.empty_like(self._specular_atlas)
            self._gpu_flipped_normal_detail = np.empty_like(self._normal_detail_atlas)
            self._gpu_flipped_specular_mask = np.empty_like(self._specular_mask_atlas)
            self._gpu_flipped_transparency = np.empty_like(self._transparency_atlas)
            _need_atlas_rebuild = True  # Force upload after buffer reallocation
        
        if _need_atlas_rebuild:
            # Flip Y axis in-place (NumPy Y=0 at top, OpenGL Y=0 at bottom)
            np.copyto(self._gpu_flipped_normal, self._normal_atlas[::-1])
            np.copyto(self._gpu_flipped_alpha, self._alpha_atlas[::-1])
            np.copyto(self._gpu_flipped_emission, self._emission_atlas[::-1])
            np.copyto(self._gpu_flipped_specular, self._specular_atlas[::-1])
            np.copyto(self._gpu_flipped_normal_detail, self._normal_detail_atlas[::-1])
            np.copyto(self._gpu_flipped_specular_mask, self._specular_mask_atlas[::-1])
            np.copyto(self._gpu_flipped_transparency, self._transparency_atlas[::-1])
            
            # Upload to GPU — pass numpy arrays directly via buffer protocol (zero-copy)
            self._gpu_textures['normal_atlas'].write(self._gpu_flipped_normal)
            self._gpu_textures['alpha_atlas'].write(self._gpu_flipped_alpha)
            self._gpu_textures['emission_atlas'].write(self._gpu_flipped_emission)
            self._gpu_textures['specular_atlas'].write(self._gpu_flipped_specular)
            self._gpu_textures['normal_detail_atlas'].write(self._gpu_flipped_normal_detail)
            self._gpu_textures['specular_mask_atlas'].write(self._gpu_flipped_specular_mask)
            self._gpu_textures['transparency_atlas'].write(self._gpu_flipped_transparency)
            print("EMISSION DEBUG:")
            print("shape: ", self._gpu_flipped_emission.shape)
            print("dtype: ", self._gpu_flipped_emission.dtype)
            print("min/max: ", self._gpu_flipped_emission.min(), self._gpu_flipped_emission.max())

        _seg_t = _profile_mark("lm_gpu_atlas", _seg_t)

        
        # Bind textures to shader
        for i, name in enumerate(['normal_atlas', 'alpha_atlas', 'emission_atlas',
                                  'specular_atlas', 'normal_detail_atlas', 'specular_mask_atlas',
                                  'transparency_atlas']):
            self._gpu_textures[name].use(location=i)
            self._gpu_program[f'u_{name}'] = i
        
        # Prepare light data (already fetched above for early exit check)
        num_lights = min(len(active_lights), 256)
        
        # Early exit for completely dark scenes (no lights and already checked for emissive)
        if num_lights == 0 and not has_lights and readback:
            # Return ambient-only result (matches CPU behavior)
            out = np.zeros((out_h, out_w, 4), dtype=np.uint8)
            out[..., 3] = 255
            visible = np.asarray(game_map.visible[x_slice, y_slice], dtype=bool).T
            if np.any(visible):
                # Apply minimal ambient to visible tiles
                out[..., :3] = int(self.config.ambient_floor * 255)
            _gpu_profile["lm_gpu_uniforms"] = _gpu_profile.get("lm_gpu_uniforms", 0.0)
            _gpu_profile["lm_gpu_dark_fastpath"] = (_time.perf_counter() - _seg_t) * 1000.0
            _flush_gpu_profile()
            return out
        
        light_data = np.zeros((256, 4), dtype=np.float32)
        light_colors = np.zeros((256, 4), dtype=np.float32)
        
        # DISABLED: Occlusion mask computation for debugging
        # Compute per-light FOV occlusion masks
        # Store as a 2D texture: (view_w * view_h, 256) where each column is one light's tile-based FOV
        """
        occlusion_data = np.zeros((256, view_h, view_w), dtype=np.float32)
        
        try:
            from tcod.map import compute_fov
            import tcod
            
            # Compute FOV for each light on the tile grid
            for i, light in enumerate(active_lights[:256]):
                lx = int(light.get("x", origin_x))
                ly = int(light.get("y", origin_y))
                radius = int(max(1, light.get("radius", 1.0) or 1.0))
                
                # Compute FOV from this light's position
                try:
                    fov = compute_fov(
                        game_map.tiles["transparent"], (lx, ly),
                        radius=radius, algorithm=tcod.FOV_SHADOW
                    )
                    
                    # Extract the viewport region of the FOV
                    for ty in range(view_h):
                        for tx in range(view_w):
                            world_x = origin_x + tx
                            world_y = origin_y + ty
                            
                            if game_map.in_bounds(world_x, world_y) and fov[world_x, world_y]:
                                occlusion_data[i, ty, tx] = 1.0
                            
                except Exception:
                    # Fallback: assume full visibility for this light
                    occlusion_data[i, :, :] = 1.0
                    
        except Exception:
            # Fallback: if FOV computation fails entirely, assume full visibility
            occlusion_data[:, :, :] = 1.0
        
        # Reshape occlusion data for GPU upload: flatten to (256 * view_h, view_w)
        # This creates a tall texture where each view_h-high slice is one light's FOV
        occlusion_texture = occlusion_data.reshape((256 * view_h, view_w))
        
        # Create or update occlusion mask texture with correct dimensions
        occlusion_height = 256 * view_h
        occlusion_width = view_w
        if ('occlusion_mask' not in self._gpu_textures or 
            self._gpu_textures['occlusion_mask'].size != (occlusion_width, occlusion_height)):
            if 'occlusion_mask' in self._gpu_textures:
                self._gpu_textures['occlusion_mask'].release()
            self._gpu_textures['occlusion_mask'] = self._gpu_ctx.texture(
                (occlusion_width, occlusion_height), 1, dtype='f4'
            )
            self._gpu_textures['occlusion_mask'].filter = (moderngl.NEAREST, moderngl.NEAREST)
        
        # Upload occlusion mask (flip Y for OpenGL convention)
        self._gpu_textures['occlusion_mask'].write(np.flip(occlusion_texture, axis=0).tobytes())
        """
        
        # Bind occlusion mask texture to shader (DISABLED FOR NOW)
        # self._gpu_textures['occlusion_mask'].use(location=6)
        # self._gpu_program['u_occlusion_mask'] = 6
        
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
        
        # Set uniforms
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

        _seg_t = _profile_mark("lm_gpu_uniforms", _seg_t)
        
        # Render to framebuffer
        self._gpu_fbo.use()
        self._gpu_ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._gpu_vao.render(moderngl.TRIANGLE_STRIP)

        _seg_t = _profile_mark("lm_gpu_draw", _seg_t)

        # Unification path: keep result in GPU target and skip CPU readback.
        if not readback:
            _gpu_profile["lm_gpu_readback"] = 0.0
            _flush_gpu_profile()
            return None
        
        # Download result
        raw = self._gpu_fbo.read(components=4, dtype='f1')
        
        # Reuse output buffer to avoid allocation every frame
        if self._gpu_output_buffer is None or self._gpu_output_buffer.shape != (out_h, out_w, 4):
            self._gpu_output_buffer = np.empty((out_h, out_w, 4), dtype=np.uint8)
        
        out = np.frombuffer(raw, dtype=np.uint8).reshape((out_h, out_w, 4))
        # Flip Y in-place into pre-allocated buffer
        np.copyto(self._gpu_output_buffer, out[::-1])
        out = self._gpu_output_buffer

        _seg_t = _profile_mark("lm_gpu_readback", _seg_t)
        
        # Smooth fullscreen visibility compositing
        visible = np.asarray(game_map.visible[x_slice, y_slice], dtype=bool).T
        explored = np.asarray(game_map.explored[x_slice, y_slice], dtype=bool).T

        # Build LOW-RES tile visibility field first
        tile_h, tile_w = visible.shape

        visibility_tile = np.zeros((tile_h, tile_w), dtype=np.float32)

        # Explored fog baseline
        visibility_tile[explored] = self.config.explored_mod

        # Fully visible overrides explored
        visibility_tile[visible] = 1.0

        # -----------------------------
        # SAFE SMOOTHING (tile-space)
        # -----------------------------
        if _SCIPY_AVAILABLE:
            from scipy.ndimage import gaussian_filter, zoom

            # Blur ONLY in TILE space (critical fix)
            blurred = gaussian_filter(visibility_tile, sigma=0.8)

            # Preserve hard visibility (never let blur reduce real vision)
            blurred = np.maximum(blurred, visibility_tile)

            visibility_tile = blurred

        # -----------------------------
        # UPSCALE AFTER ALL LOGIC
        # -----------------------------
        visibility_mask = zoom(
            visibility_tile,
            (px_per_tile_y, px_per_tile_x),
            order=1,
        )

        visibility_mask = visibility_mask[:out_h, :out_w]

        # Final clamp
        visibility_mask = np.clip(visibility_mask, 0.0, 1.0)

        # Apply visibility globally ONCE
        out[..., :3] = (
            out[..., :3].astype(np.float32)
            * visibility_mask[..., None]
        ).astype(np.uint8)
        
        _gpu_profile["lm_gpu_explored_fade"] = (
            _time.perf_counter() - _seg_t
        ) * 1000.0

        _flush_gpu_profile()


        return out
    
    def _build_material_atlases_gpu(self, game_map, console, origin_x: int, origin_y: int,
                                    view_w: int, view_h: int, out_w: int, out_h: int,
                                    scale: int, px_per_tile_x: int, px_per_tile_y: int) -> None:
        """Build material atlases on CPU for GPU upload.
        
        EXACTLY replicates CPU material gather logic including spatial culling.
        """
        x_slice = slice(origin_x, origin_x + view_w)
        y_slice = slice(origin_y, origin_y + view_h)
        
        # Clear atlases
        self._normal_atlas.fill(0.0)
        self._alpha_atlas.fill(0.0)
        self._emission_atlas.fill(0.0)
        self._specular_atlas.fill(0.0)
        self._normal_detail_atlas.fill(0.0)
        self._specular_mask_atlas.fill(0.0)
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
        
        if not np.any(visible):
            return
        
        tile_x0 = (np.arange(view_w, dtype=np.int32) * px_per_tile_x)
        tile_x1 = (np.arange(1, view_w + 1, dtype=np.int32) * px_per_tile_x)
        tile_y0 = (np.arange(view_h, dtype=np.int32) * px_per_tile_y)
        tile_y1 = (np.arange(1, view_h + 1, dtype=np.int32) * px_per_tile_y)
        tile_x1 = np.clip(np.maximum(tile_x1, tile_x0 + 1), 1, out_w)
        tile_y1 = np.clip(np.maximum(tile_y1, tile_y0 + 1), 1, out_h)
        
        # Build light tile mask (EXACTLY matches CPU path)
        active_lights = list(getattr(game_map, "_active_lights", []) or [])
        lit_tile_mask = np.zeros((view_h, view_w), dtype=bool)
        
        # Optimization: Pre-compute light bounds and batch update mask
        for light in active_lights:
            radius = max(1.0, float(light.get("radius", 1.0) or 1.0))
            lx = float(light.get("x", origin_x))
            ly = float(light.get("y", origin_y))
            
            # Compute tile bounds (cache floor/ceil results)
            lx_minus_r = lx - radius - origin_x
            lx_plus_r = lx + radius - origin_x
            ly_minus_r = ly - radius - origin_y
            ly_plus_r = ly + radius - origin_y
            
            min_tx_tile = max(0, int(np.floor(lx_minus_r)))
            max_tx_tile = min(view_w, int(np.ceil(lx_plus_r)) + 1)
            min_ty_tile = max(0, int(np.floor(ly_minus_r)))
            max_ty_tile = min(view_h, int(np.ceil(ly_plus_r)) + 1)
            
            if min_tx_tile < max_tx_tile and min_ty_tile < max_ty_tile:
                lit_tile_mask[min_ty_tile:max_ty_tile, min_tx_tile:max_tx_tile] = True
        
        # Material gather pass (EXACTLY matches CPU conditional copying logic)
        gather_coords = np.argwhere(visible)
        # Cache packed material lookups per frame to avoid redundant work when
        # many visible tiles share the same codepoint/dimensions.
        frame_material_cache: dict[tuple[int, int, int], tuple[
            np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, bool, bool, bool
        ]] = {}
        for tile_y, tile_x in gather_coords:
            # Cache int conversions (optimization)
            tx_int = int(tile_x)
            ty_int = int(tile_y)
            
            cp = int(console.ch[tx_int, ty_int])
            px0 = int(tile_x0[tx_int])
            px1 = int(tile_x1[tx_int])
            py0 = int(tile_y0[ty_int])
            py1 = int(tile_y1[ty_int])
            if px1 <= px0 or py1 <= py0:
                continue
            
            block_h = py1 - py0
            block_w = px1 - px0
            mat_key = (cp, block_h, block_w)
            mat = frame_material_cache.get(mat_key)
            if mat is None:
                n_view, a_view, e_view, s_view, nd_view, sm_view = self._get_compat_material(
                    cp=cp, scale=scale, out_h=block_h, out_w=block_w,
                )
                has_emissive = bool(np.any(e_view > self.config.alpha_threshold))
                has_specular = bool(np.any(sm_view > self.config.detail_threshold))
                has_normal_detail = bool(np.any(nd_view > self.config.detail_threshold))
                mat = (
                    n_view, a_view, e_view, s_view, nd_view, sm_view,
                    has_emissive, has_specular, has_normal_detail,
                )
                frame_material_cache[mat_key] = mat
            n_view, a_view, e_view, s_view, nd_view, sm_view, has_emissive, has_specular, has_normal_detail = mat
            
            # Always copy alpha for composition
            self._alpha_atlas[py0:py1, px0:px1] = a_view
            
            in_light_tiles = lit_tile_mask[ty_int, tx_int]
            
            # Early-out: skip heavier material channels if not needed
            if not in_light_tiles and not has_emissive and not has_specular and not has_normal_detail:
                continue
            
            # Only copy channels that will be used (EXACTLY matches CPU)
            if in_light_tiles:
                self._normal_atlas[py0:py1, px0:px1, :] = n_view
            if has_emissive:
                self._emission_atlas[py0:py1, px0:px1, :] = e_view
            if in_light_tiles and (has_specular or has_normal_detail):
                self._specular_atlas[py0:py1, px0:px1, :] = s_view
                self._normal_detail_atlas[py0:py1, px0:px1] = nd_view
                self._specular_mask_atlas[py0:py1, px0:px1] = sm_view
    
    def _build_material_atlases_gpu_optimized(self, game_map, console, origin_x: int, origin_y: int,
                                              view_w: int, view_h: int, out_w: int, out_h: int,
                                              scale: int, px_per_tile_x: int, px_per_tile_y: int,
                                              viewport_changed: bool) -> None:
        """Optimized material atlas builder with caching and incremental updates.
        
        Only rebuilds changed tiles when viewport is stable. Falls back to full rebuild
        when viewport changes (camera movement).
        """
        x_slice = slice(origin_x, origin_x + view_w)
        y_slice = slice(origin_y, origin_y + view_h)
        
        visible = np.asarray(game_map.visible[x_slice, y_slice], dtype=bool).T
        if not np.any(visible):
            # No visible tiles - clear atlases quickly
            if not self._gpu_atlas_persistent or viewport_changed:
                self._normal_atlas.fill(0.0)
                self._alpha_atlas.fill(0.0)
                self._emission_atlas.fill(0.0)
                self._specular_atlas.fill(0.0)
                self._normal_detail_atlas.fill(0.0)
                self._specular_mask_atlas.fill(0.0)
                
                # Upload cleared atlases once
                self._gpu_textures['normal_atlas'].write(np.flip(self._normal_atlas, axis=0).tobytes())
                self._gpu_textures['alpha_atlas'].write(np.flip(self._alpha_atlas, axis=0).tobytes())
                self._gpu_textures['emission_atlas'].write(np.flip(self._emission_atlas, axis=0).tobytes())
                self._gpu_textures['specular_atlas'].write(np.flip(self._specular_atlas, axis=0).tobytes())
                self._gpu_textures['normal_detail_atlas'].write(np.flip(self._normal_detail_atlas, axis=0).tobytes())
                self._gpu_textures['specular_mask_atlas'].write(np.flip(self._specular_mask_atlas, axis=0).tobytes())
                
                self._gpu_atlas_persistent = True
            return
        
        tile_x0 = (np.arange(view_w, dtype=np.int32) * px_per_tile_x)
        tile_x1 = (np.arange(1, view_w + 1, dtype=np.int32) * px_per_tile_x)
        tile_y0 = (np.arange(view_h, dtype=np.int32) * px_per_tile_y)
        tile_y1 = (np.arange(1, view_h + 1, dtype=np.int32) * px_per_tile_y)
        tile_x1 = np.clip(np.maximum(tile_x1, tile_x0 + 1), 1, out_w)
        tile_y1 = np.clip(np.maximum(tile_y1, tile_y0 + 1), 1, out_h)
        
        # Build light tile mask
        active_lights = list(getattr(game_map, "_active_lights", []) or [])
        lit_tile_mask = np.zeros((view_h, view_w), dtype=bool)
        for light in active_lights:
            radius = max(1.0, float(light.get("radius", 1.0) or 1.0))
            lx = float(light.get("x", origin_x))
            ly = float(light.get("y", origin_y))
            
            min_tx_tile = max(0, int(np.floor(lx - radius - origin_x)))
            max_tx_tile = min(view_w, int(np.ceil(lx + radius - origin_x)) + 1)
            min_ty_tile = max(0, int(np.floor(ly - radius - origin_y)))
            max_ty_tile = min(view_h, int(np.ceil(ly + radius - origin_y)) + 1)
            if min_tx_tile < max_tx_tile and min_ty_tile < max_ty_tile:
                lit_tile_mask[min_ty_tile:max_ty_tile, min_tx_tile:max_tx_tile] = True
        
        # Determine which tiles need updating
        if not self._gpu_atlas_persistent or viewport_changed:
            # Full rebuild - clear atlases and update all visible tiles
            self._normal_atlas.fill(0.0)
            self._alpha_atlas.fill(0.0)
            self._emission_atlas.fill(0.0)
            self._specular_atlas.fill(0.0)
            self._normal_detail_atlas.fill(0.0)
            self._specular_mask_atlas.fill(0.0)
            tiles_to_update = np.argwhere(visible)
            full_upload = True
        else:
            # Incremental update - only process changed tiles
            # Detect changes by comparing current console to cached materials
            tiles_to_update = []
            for tile_y, tile_x in np.argwhere(visible):
                cp = int(console.ch[int(tile_x), int(tile_y)])
                world_pos = (origin_x + int(tile_x), origin_y + int(tile_y))
                
                # Check if this tile's sprite changed
                cached = self._gpu_atlas_cache.get(cp)
                if cached is None or world_pos in self._gpu_dirty_tiles:
                    tiles_to_update.append((tile_y, tile_x))
            
            tiles_to_update = np.array(tiles_to_update) if tiles_to_update else np.array([]).reshape(0, 2)
            full_upload = False
        
        # Early exit if no tiles need updating
        if len(tiles_to_update) == 0 and self._gpu_atlas_persistent:
            return
        
        # Batch material fetch and update
        for tile_y, tile_x in tiles_to_update:
            cp = int(console.ch[int(tile_x), int(tile_y)])
            px0 = int(tile_x0[int(tile_x)])
            px1 = int(tile_x1[int(tile_x)])
            py0 = int(tile_y0[int(tile_y)])
            py1 = int(tile_y1[int(tile_y)])
            if px1 <= px0 or py1 <= py0:
                continue
            
            block_h = py1 - py0
            block_w = px1 - px0
            
            # Check cache first
            cached = self._gpu_atlas_cache.get(cp)
            if cached is not None and cached[0].shape[:2] == (block_h, block_w):
                n_view, a_view, e_view, s_view, nd_view, sm_view = cached
            else:
                # Fetch and cache materials
                n_view, a_view, e_view, s_view, nd_view, sm_view = self._get_compat_material(
                    cp=cp, scale=scale, out_h=block_h, out_w=block_w,
                )
                self._gpu_atlas_cache[cp] = (n_view, a_view, e_view, s_view, nd_view, sm_view)
            
            # Always copy alpha
            self._alpha_atlas[py0:py1, px0:px1] = a_view
            
            in_light_tiles = lit_tile_mask[int(tile_y), int(tile_x)]
            has_emissive = np.any(e_view > self.config.alpha_threshold)
            has_specular = np.any(sm_view > self.config.detail_threshold)
            has_normal_detail = np.any(nd_view > self.config.detail_threshold)
            
            if not in_light_tiles and not has_emissive and not has_specular and not has_normal_detail:
                continue
            
            if in_light_tiles:
                self._normal_atlas[py0:py1, px0:px1, :] = n_view
            if has_emissive:
                self._emission_atlas[py0:py1, px0:px1, :] = e_view
            if in_light_tiles and (has_specular or has_normal_detail):
                self._specular_atlas[py0:py1, px0:px1, :] = s_view
                self._normal_detail_atlas[py0:py1, px0:px1] = nd_view
                self._specular_mask_atlas[py0:py1, px0:px1] = sm_view
        
        # Upload to GPU - always full upload for now (ModernGL doesn't expose partial updates easily)
        self._gpu_textures['normal_atlas'].write(np.flip(self._normal_atlas, axis=0).tobytes())
        self._gpu_textures['alpha_atlas'].write(np.flip(self._alpha_atlas, axis=0).tobytes())
        self._gpu_textures['emission_atlas'].write(np.flip(self._emission_atlas, axis=0).tobytes())
        self._gpu_textures['specular_atlas'].write(np.flip(self._specular_atlas, axis=0).tobytes())
        self._gpu_textures['normal_detail_atlas'].write(np.flip(self._normal_detail_atlas, axis=0).tobytes())
        self._gpu_textures['specular_mask_atlas'].write(np.flip(self._specular_mask_atlas, axis=0).tobytes())
        
        # Mark atlas as persistent and clear dirty tiles
        self._gpu_atlas_persistent = True
        self._gpu_dirty_tiles.clear()
    
    def mark_tile_dirty(self, world_x: int, world_y: int) -> None:
        """Mark a world tile as needing atlas update (call when sprite changes)."""
        self._gpu_dirty_tiles.add((world_x, world_y))
    
    def invalidate_sprite_cache(self, codepoint: int) -> None:
        """Invalidate cached material data for a specific codepoint."""
        keys_to_remove = [k for k in self._gpu_atlas_cache if k[0] == codepoint]
        for k in keys_to_remove:
            del self._gpu_atlas_cache[k]
        self._atlas_prev_ch = None
        self._atlas_prev_vis = None
        self._atlas_prev_trans = None
    
    def get_stats(self) -> dict:
        """Return performance statistics for debugging."""
        return {
            'mode': self.mode,
            'gpu_initialized': self._gpu_initialized,
            'atlas_persistent': self._gpu_atlas_persistent,
            'cached_materials': len(self._gpu_atlas_cache),
            'dirty_tiles': len(self._gpu_dirty_tiles),
        }

    def build_lightmap(self, game_map, console) -> np.ndarray:
        """Return a full-resolution RGBA lightmap for the current frame.
        
        Routes to GPU or CPU implementation based on mode setting.
        """
        if self.mode == "gpu" and _MODERNGL_AVAILABLE:
            try:
                return self._build_lightmap_gpu(game_map, console)
            except Exception as e:
                print(f"[ERROR]: GPU lightmap build failed: {e}")
                import traceback
                traceback.print_exc()
                import time
                time.sleep(5000)
                # Crash to reveal the error
                raise
        else:
            print(f"[WARNING]: GPU lightmap build not available (mode='{self.mode}', moderngl={_MODERNGL_AVAILABLE})")
            if self.mode == "gpu" and not _MODERNGL_AVAILABLE:
                print("[ERROR]: GPU mode requested but ModernGL is not installed!")
                print("[ERROR]: Install with: pip install moderngl")
            return self._build_lightmap_cpu(game_map, console)

    def render_lightmap_to_gpu_target(self, game_map, console) -> bool:
        """Render the lightmap into the internal ModernGL output texture.

        This path performs no CPU readback. Use get_gpu_output_texture()/
        get_gpu_output_size() to consume the rendered texture from a unified
        ModernGL frame pipeline.
        """
        if self.mode != "gpu" or not _MODERNGL_AVAILABLE:
            return False
        try:
            self._build_lightmap_gpu(game_map, console, readback=False)
            return True
        except Exception as e:
            print(f"[ERROR]: GPU target lightmap render failed: {e}")
            return False

    def get_gpu_output_texture(self):
        """Return the internal ModernGL color texture for the last GPU lightmap pass."""
        return self._gpu_textures.get('output')

    def get_gpu_output_size(self) -> tuple[int, int] | None:
        """Return (width, height) of the internal GPU lightmap output texture."""
        if self._gpu_fbo is None:
            return None
        return self._gpu_fbo.size
    
    def _build_lightmap_cpu(self, game_map, console) -> np.ndarray:
        """CPU implementation - original NumPy-based lighting accumulation."""
        tile_w, tile_h = sprite_manager.get_loaded_tile_size()
        origin_x, origin_y, view_w, view_h = game_map.get_viewport(console)
        x_slice = slice(origin_x, origin_x + view_w)
        y_slice = slice(origin_y, origin_y + view_h)
        scale = max(1, int(LIGHT_SCALE))
        out_w = max(1, (view_w * tile_w) // scale)
        out_h = max(1, (view_h * tile_h) // scale)
        px_per_tile_x = max(1, tile_w // scale)
        px_per_tile_y = max(1, tile_h // scale)

        self._ensure_buffers(out_h, out_w)
        normal_atlas = self._normal_atlas
        alpha_atlas = self._alpha_atlas
        warm_acc = self._warm_acc
        white_acc = self._white_acc
        specular_acc = self._specular_acc
        base_rgb = self._base_rgb
        emission_atlas = self._emission_atlas
        specular_atlas = self._specular_atlas
        normal_detail_atlas = self._normal_detail_atlas
        specular_mask_atlas = self._specular_mask_atlas
        grid_x = self._grid_x
        grid_y = self._grid_y
        x_idx = self._x_idx
        y_idx = self._y_idx

        normal_atlas.fill(0.0)
        alpha_atlas.fill(0.0)
        warm_acc.fill(0.0)
        white_acc.fill(0.0)
        specular_acc.fill(0.0)
        base_rgb.fill(0.0)
        emission_atlas.fill(0.0)
        specular_atlas.fill(0.0)
        normal_detail_atlas.fill(0.0)
        specular_mask_atlas.fill(0.0)

        grid_x[0, :] = origin_x + (x_idx + 0.5) / float(px_per_tile_x) - 0.5
        grid_y[:, 0] = origin_y + (y_idx + 0.5) / float(px_per_tile_y) - 0.5

        out = np.zeros((out_h, out_w, 4), dtype=np.uint8)
        out[..., 3] = 255

        if getattr(game_map, "sunlit", False):
            out[..., :3] = 190
            return out

        visible = np.asarray(game_map.visible[x_slice, y_slice], dtype=bool).T
        explored = np.asarray(game_map.explored[x_slice, y_slice], dtype=bool).T
        dark_bg = np.asarray(game_map.tiles["dark"]["bg"][x_slice, y_slice], dtype=np.float32).transpose(1, 0, 2)
        light_bg = np.asarray(game_map.tiles["light"]["bg"][x_slice, y_slice], dtype=np.float32).transpose(1, 0, 2)
        with np.errstate(divide="ignore", invalid="ignore"):
            explored_ratio = np.where(light_bg > 0.0, dark_bg / light_bg, 0.0)
        explored_ratio = np.clip(explored_ratio, 0.0, float(self.config.explored_mod))

        active_lights = list(getattr(game_map, "_active_lights", []) or [])
        visible_any = bool(np.any(visible))

        tile_x0 = (np.arange(view_w, dtype=np.int32) * tile_w) // scale
        tile_x1 = (np.arange(1, view_w + 1, dtype=np.int32) * tile_w) // scale
        tile_y0 = (np.arange(view_h, dtype=np.int32) * tile_h) // scale
        tile_y1 = (np.arange(1, view_h + 1, dtype=np.int32) * tile_h) // scale
        tile_x1 = np.clip(np.maximum(tile_x1, tile_x0 + 1), 1, out_w)
        tile_y1 = np.clip(np.maximum(tile_y1, tile_y0 + 1), 1, out_h)

        light_bounds: list[tuple[int, int, int, int, bool]] = []
        lit_tile_mask = np.zeros((view_h, view_w), dtype=bool)
        for light in active_lights:
            radius = max(1.0, float(light.get("radius", 1.0) or 1.0))
            lx = float(light.get("x", origin_x))
            ly = float(light.get("y", origin_y))
            static_light = bool(light.get("is_static", False))
            cache_key = (
                lx, ly, radius,
                float(px_per_tile_x), float(px_per_tile_y),
                float(origin_x), float(origin_y),
                int(out_w), int(out_h),
            )
            if static_light and cache_key in self._static_light_bounds_cache:
                min_tx, max_tx, min_ty, max_ty = self._static_light_bounds_cache[cache_key]
            else:
                min_tx = max(0, int((lx - radius - origin_x) * px_per_tile_x))
                max_tx = min(out_w, int((lx + radius - origin_x) * px_per_tile_x) + 1)
                min_ty = max(0, int((ly - radius - origin_y) * px_per_tile_y))
                max_ty = min(out_h, int((ly + radius - origin_y) * px_per_tile_y) + 1)
                if static_light:
                    self._static_light_bounds_cache[cache_key] = (min_tx, max_tx, min_ty, max_ty)
            light_bounds.append((min_tx, max_tx, min_ty, max_ty, bool(light.get("is_white", False))))

            min_tx_tile = max(0, int(np.floor(lx - radius - origin_x)))
            max_tx_tile = min(view_w, int(np.ceil(lx + radius - origin_x)) + 1)
            min_ty_tile = max(0, int(np.floor(ly - radius - origin_y)))
            max_ty_tile = min(view_h, int(np.ceil(ly + radius - origin_y)) + 1)
            if min_tx_tile < max_tx_tile and min_ty_tile < max_ty_tile:
                lit_tile_mask[min_ty_tile:max_ty_tile, min_tx_tile:max_tx_tile] = True

        if visible_any:
            # Material gather pass: direct blit from pre-packed materials only.
            gather_coords = np.argwhere(visible)
            for tile_y, tile_x in gather_coords:
                cp = int(console.ch[int(tile_x), int(tile_y)])
                px0 = int(tile_x0[int(tile_x)])
                px1 = int(tile_x1[int(tile_x)])
                py0 = int(tile_y0[int(tile_y)])
                py1 = int(tile_y1[int(tile_y)])
                if px1 <= px0 or py1 <= py0:
                    continue

                block_h = py1 - py0
                block_w = px1 - px0
                n_view, a_view, e_view, s_view, nd_view, sm_view = self._get_compat_material(
                    cp=cp,
                    scale=scale,
                    out_h=block_h,
                    out_w=block_w,
                )

                # Always copy alpha for composition
                alpha_atlas[py0:py1, px0:px1] = a_view
                
                in_light_tiles = lit_tile_mask[int(tile_y), int(tile_x)]
                # Use faster any() instead of max() for boolean checks
                has_emissive = np.any(e_view > self.config.alpha_threshold)
                has_specular = np.any(sm_view > self.config.detail_threshold)
                has_normal_detail = np.any(nd_view > self.config.detail_threshold)
                
                # Early-out: skip heavier material channels if not needed
                if not in_light_tiles and not has_emissive and not has_specular and not has_normal_detail:
                    continue

                # Only copy channels that will be used
                if in_light_tiles:
                    normal_atlas[py0:py1, px0:px1, :] = n_view
                if has_emissive:
                    emission_atlas[py0:py1, px0:px1, :] = e_view
                if in_light_tiles and (has_specular or has_normal_detail):
                    specular_atlas[py0:py1, px0:px1, :] = s_view
                    normal_detail_atlas[py0:py1, px0:px1] = nd_view
                    specular_mask_atlas[py0:py1, px0:px1] = sm_view

            # Spatially-culled lighting accumulation with optimized per-light processing
            # Pre-compute constants outside loop
            light_height_sq = self.config.light_height * self.config.light_height
            spec_strength = self.config.specular_strength
            
            # Check once if any specular pixels exist globally
            has_spec_pixels = False
            if np.any(alpha_atlas > 0.0):
                has_spec_pixels = np.any((normal_detail_atlas > self.config.detail_threshold) | (specular_mask_atlas > self.config.detail_threshold))
            
            for light_idx, light in enumerate(active_lights):
                min_tx, max_tx, min_ty, max_ty, is_white = light_bounds[light_idx]
                if min_tx >= max_tx or min_ty >= max_ty:
                    continue

                lx = float(light.get("x", origin_x))
                ly = float(light.get("y", origin_y))
                radius = max(1.0, float(light.get("radius", 1.0) or 1.0))
                intensity = float(np.clip(light.get("intensity", 1.0) or 1.0, 0.0, 1.0))

                # Extract local regions (already float32, no conversion needed)
                local_alpha = alpha_atlas[min_ty:max_ty, min_tx:max_tx]
                # Faster check using any() instead of max()
                if not np.any(local_alpha > self.config.alpha_threshold):
                    continue

                # Compute distance field for this light's region only
                local_grid_x = grid_x[:, min_tx:max_tx]
                local_grid_y = grid_y[min_ty:max_ty, :]
                dx = lx - local_grid_x
                dy = ly - local_grid_y
                dist_sq = dx * dx + dy * dy
                
                # Early exit if entire region is outside light radius
                radius_sq = radius * radius
                if np.min(dist_sq) > radius_sq:
                    continue

                # Compute falloff - fused operation
                falloff = np.clip((radius_sq - dist_sq) / radius_sq, 0.0, 1.0) * intensity
                if not np.any(falloff > self.config.falloff_threshold):
                    continue

                # Fast inverse square root using cached constant
                dist_plus_h = dist_sq + light_height_sq
                inv_len = 1.0 / np.sqrt(dist_plus_h)
                light_dir_x = dx * inv_len
                light_dir_y = dy * inv_len
                light_dir_z = self.config.light_height * inv_len

                # Extract local normals
                local_normals = normal_atlas[min_ty:max_ty, min_tx:max_tx]
                
                # Compute diffuse with in-place operations
                diffuse = (
                    local_normals[..., 0] * light_dir_x +
                    local_normals[..., 1] * light_dir_y +
                    local_normals[..., 2] * light_dir_z
                )
                np.maximum(diffuse, 0.0, out=diffuse)

                # Apply falloff and alpha in one fused operation
                contribution = falloff * diffuse * local_alpha
                if not np.any(contribution > self.config.falloff_threshold):
                    continue

                # Accumulate to appropriate channel
                if is_white:
                    white_acc[min_ty:max_ty, min_tx:max_tx] += contribution
                else:
                    warm_acc[min_ty:max_ty, min_tx:max_tx] += contribution

                # Specular pass - skip if disabled globally or contribution too weak
                if not has_spec_pixels or np.max(contribution) < self.config.specular_threshold:
                    continue
                    
                local_detail = normal_detail_atlas[min_ty:max_ty, min_tx:max_tx]
                local_specmask = specular_mask_atlas[min_ty:max_ty, min_tx:max_tx]
                spec_candidate = (local_detail > self.config.detail_threshold) | (local_specmask > self.config.detail_threshold)
                if not np.any(spec_candidate):
                    continue

                # Simplified half vector calculation (view = 0,0,1)
                # H = normalize(L + V) = normalize((lx,ly,lz) + (0,0,1))
                half_z_unnorm = light_dir_z + 1.0
                half_inv_len = 1.0 / np.sqrt(light_dir_x * light_dir_x + light_dir_y * light_dir_y + half_z_unnorm * half_z_unnorm)
                half_x = light_dir_x * half_inv_len
                half_y = light_dir_y * half_inv_len
                half_z = half_z_unnorm * half_inv_len

                # Compute specular highlight
                specular = (
                    local_normals[..., 0] * half_x +
                    local_normals[..., 1] * half_y +
                    local_normals[..., 2] * half_z
                )
                np.maximum(specular, 0.0, out=specular)
                specular = self._fast_specular_curve(specular)
                specular *= contribution * spec_strength * spec_candidate
                
                if not np.any(specular > self.config.falloff_threshold):
                    continue

                local_specular = specular_atlas[min_ty:max_ty, min_tx:max_tx]
                specular_acc[min_ty:max_ty, min_tx:max_tx] += specular[..., None] * local_specular

            # Final composition pass - already in float32, no conversions needed
            total_acc = warm_acc + white_acc
            brightness = np.clip(self.config.ambient_floor + total_acc, 0.0, 1.0)

            white_ratio = np.ones_like(total_acc, dtype=np.float32)
            np.divide(white_acc, total_acc, out=white_ratio, where=total_acc > self.config.falloff_threshold)
            white_ratio = np.clip(white_ratio, 0.0, 1.0)
            warm_ratio = 1.0 - white_ratio

            base_rgb[..., 0] = brightness
            base_rgb[..., 1] = brightness * (warm_ratio * (1.0 - self.config.warm_g * brightness) + white_ratio)
            base_rgb[..., 2] = brightness * (warm_ratio * (1.0 - self.config.warm_b * brightness) + white_ratio)

            detail_factor = np.clip(1.0 + self.config.directional_contrast * (total_acc - 0.5), self.config.detail_factor_min, self.config.detail_factor_max)
            detail_factor = 1.0 - alpha_atlas * (1.0 - detail_factor)

            base_rgb *= detail_factor[..., None]
            base_rgb += specular_acc
            base_rgb += emission_atlas
            np.clip(base_rgb, 0.0, 1.0, out=base_rgb)
            out[..., 0] = np.clip(base_rgb[..., 0] * 255.0, 0, 255).astype(np.uint8)
            out[..., 1] = np.clip(base_rgb[..., 1] * 255.0, 0, 255).astype(np.uint8)
            out[..., 2] = np.clip(base_rgb[..., 2] * 255.0, 0, 255).astype(np.uint8)

        # Explored-but-not-visible pass with pixel-smooth FOV falloff (cached)
        explored_coords = np.argwhere(np.logical_and(explored, np.logical_not(visible)))
        if len(explored_coords) == 0:
            return out  # No explored tiles, skip expensive distance transform
        
        if _SCIPY_AVAILABLE:
            # Check if we can reuse cached fade map
            viewport = (origin_x, origin_y, view_w, view_h)
            visibility_hash = hash(visible.tobytes())
            
            if (self._fade_cache_map is not None and 
                self._fade_cache_viewport == viewport and 
                self._fade_cache_visibility_hash == visibility_hash):
                # Reuse cached fade map
                pixel_fade_factor = self._fade_cache_map
            else:
                # Build pixel-resolution visibility mask (vectorized)
                visible_pixels = np.zeros((out_h, out_w), dtype=bool)
                for tile_y in range(view_h):
                    if not np.any(visible[tile_y, :]):
                        continue  # Skip empty rows
                    for tile_x in range(view_w):
                        if visible[tile_y, tile_x]:
                            px0 = int(tile_x0[tile_x])
                            px1 = int(tile_x1[tile_x])
                            py0 = int(tile_y0[tile_y])
                            py1 = int(tile_y1[tile_y])
                            visible_pixels[py0:py1, px0:px1] = True
                
                # Compute distance transform at pixel level
                visibility_distance = distance_transform_edt(~visible_pixels)
                fade_distance_pixels = 2.0 * px_per_tile_x  # 2 tiles worth of pixels
                pixel_fade_factor = np.clip(1.0 - (visibility_distance / fade_distance_pixels), 0.0, 1.0)
                
                # Cache for next frame
                self._fade_cache_visibility_hash = visibility_hash
                self._fade_cache_viewport = viewport
                self._fade_cache_map = pixel_fade_factor
        
        for tile_y, tile_x in explored_coords:
            px0 = int(tile_x0[int(tile_x)])
            px1 = int(tile_x1[int(tile_x)])
            py0 = int(tile_y0[int(tile_y)])
            py1 = int(tile_y1[int(tile_y)])
            
            if _SCIPY_AVAILABLE:
                # Apply pixel-smooth blend
                pixel_blend = pixel_fade_factor[py0:py1, px0:px1]
                explored_color = explored_ratio[int(tile_y), int(tile_x)] * 255.0
                current_color = out[py0:py1, px0:px1, :3].astype(np.float32)
                
                blended_r = current_color[..., 0] * pixel_blend + explored_color[0] * (1.0 - pixel_blend)
                blended_g = current_color[..., 1] * pixel_blend + explored_color[1] * (1.0 - pixel_blend)
                blended_b = current_color[..., 2] * pixel_blend + explored_color[2] * (1.0 - pixel_blend)
                
                out[py0:py1, px0:px1, 0] = np.uint8(np.clip(blended_r, 0.0, 255.0))
                out[py0:py1, px0:px1, 1] = np.uint8(np.clip(blended_g, 0.0, 255.0))
                out[py0:py1, px0:px1, 2] = np.uint8(np.clip(blended_b, 0.0, 255.0))
            else:
                # Fallback: hard transition
                out[py0:py1, px0:px1, 0] = np.uint8(np.clip(explored_ratio[int(tile_y), int(tile_x), 0] * 255.0, 0.0, 255.0))
                out[py0:py1, px0:px1, 1] = np.uint8(np.clip(explored_ratio[int(tile_y), int(tile_x), 1] * 255.0, 0.0, 255.0))
                out[py0:py1, px0:px1, 2] = np.uint8(np.clip(explored_ratio[int(tile_y), int(tile_x), 2] * 255.0, 0.0, 255.0))
        return out

    def _build_legacy_lightmap(self, game_map, console) -> np.ndarray:
        """Return the older tile-sized lightmap as a safe fallback."""
        origin_x, origin_y, view_w, view_h = game_map.get_viewport(console)
        x_slice = slice(origin_x, origin_x + view_w)
        y_slice = slice(origin_y, origin_y + view_h)

        out = np.empty((view_h, view_w, 4), dtype=np.uint8)
        out[..., 3] = 255

        if getattr(game_map, "sunlit", False):
            out[..., :3] = 190
            return out

        visible = np.asarray(game_map.visible[x_slice, y_slice], dtype=bool).T
        explored = np.asarray(game_map.explored[x_slice, y_slice], dtype=bool).T
        light_level = np.clip(np.asarray(game_map.tiles["light_level"][x_slice, y_slice], dtype=np.float32).T, 0.0, 1.0)

        raw_white = getattr(game_map, "_white_light_level", None)
        if raw_white is not None:
            white_level = np.clip(np.asarray(raw_white[x_slice, y_slice], dtype=np.float32).T, 0.0, 1.0)
        else:
            white_level = np.zeros_like(light_level)

        dark_bg = np.asarray(game_map.tiles["dark"]["bg"][x_slice, y_slice], dtype=np.float32).transpose(1, 0, 2)
        light_bg = np.asarray(game_map.tiles["light"]["bg"][x_slice, y_slice], dtype=np.float32).transpose(1, 0, 2)
        with np.errstate(divide="ignore", invalid="ignore"):
            explored_ratio = np.where(light_bg > 0.0, dark_bg / light_bg, 0.0)
        explored_ratio = np.clip(explored_ratio, 0.0, float(self.config.explored_mod))

        ll = light_level
        brightness = self.config.ambient_floor + (1.0 - self.config.ambient_floor) * ll
        safe_ll = np.where(ll > 0.0, ll, np.float32(1.0))
        white_ratio = np.clip(white_level / safe_ll, 0.0, 1.0)
        warm_ratio = 1.0 - white_ratio

        r = brightness
        g = brightness * (warm_ratio * (1.0 - self.config.warm_g * ll) + white_ratio)
        b = brightness * (warm_ratio * (1.0 - self.config.warm_b * ll) + white_ratio)

        zero = np.float32(0.0)
        exp_r = explored_ratio[..., 0]
        exp_g = explored_ratio[..., 1]
        exp_b = explored_ratio[..., 2]

        r = np.where(visible, r, np.where(explored, exp_r, zero))
        g = np.where(visible, g, np.where(explored, exp_g, zero))
        b = np.where(visible, b, np.where(explored, exp_b, zero))

        out[..., 0] = np.clip(r * 255.0, 0, 255).astype(np.uint8)
        out[..., 1] = np.clip(g * 255.0, 0, 255).astype(np.uint8)
        out[..., 2] = np.clip(b * 255.0, 0, 255).astype(np.uint8)
        return out


def create_lighting_engine(mode: str = "cpu") -> LightingShaderEngine:
    """Create the active lighting engine facade.
    
    Args:
        mode: "cpu" (NumPy) or "gpu" (ModernGL shaders). If "gpu" is requested
              but ModernGL is unavailable, automatically falls back to CPU.
    """
    return LightingShaderEngine(mode=mode)


def get_lighting_engine(mode: str | None = None) -> LightingShaderEngine:
    """Return a shared lighting engine instance used by map render callers.
    
    Args:
        mode: "cpu" or "gpu". If None, auto-detects from settings.json.
              Falls back to CPU if GPU is unavailable.
    """
    global _ENGINE_SINGLETON
    
    # Auto-detect mode from settings if not specified
    if mode is None:
        try:
            import json
            with open("json/settings.json", 'r') as f:
                # Strip comments for JSON parsing
                text = '\n'.join(line for line in f if not line.strip().startswith('//'))
                settings = json.loads(text)
                mode = settings.get("lighting_mode", "cpu")
                #print(f"[DEBUG]: Auto-detected lighting_mode from settings.json: '{mode}'")
        except Exception as e:
            print(f"[DEBUG]: Failed to read settings.json, defaulting to CPU: {e}")
            mode = "cpu"
    
    if _ENGINE_SINGLETON is None or _ENGINE_SINGLETON.mode != mode:
        # Read optional config overrides from settings.json
        _cfg_kwargs: dict = {}
        try:
            import json as _json
            with open("json/settings.json", 'r') as _f:
                _txt = '\n'.join(l for l in _f if not l.strip().startswith('//'))
                _s = _json.loads(_txt)
            if "shadow_softness" in _s:
                _cfg_kwargs["shadow_softness"] = float(_s["shadow_softness"])
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
        mode: "cpu" or "gpu". If None, auto-detects from settings.json.
    """
    diffuse = get_lighting_engine(mode=mode).build_lightmap(game_map, console)
    specular = np.zeros_like(diffuse)
    emissive = np.zeros_like(diffuse)
    specular[..., 3] = 255
    emissive[..., 3] = 255
    return diffuse, specular, emissive
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


LIGHT_SCALE = 2  # Higher = faster (fewer pixels computed), relies on GPU bilinear upscaling
_ENGINE_SINGLETON: LightingShaderEngine | None = None


@dataclass(frozen=True)
class LightingShaderConfig:
    """Configuration for lighting shader engine.
    
    All parameters are used identically in both CPU and GPU rendering paths.
    Modify these values to adjust lighting appearance and performance.
    """
    # Core lighting parameters
    ambient_floor: float = 0.1  # Base ambient brightness (0.0 = pitch black, 1.0 = full bright)
    explored_mod: float = 0.1  # Brightness multiplier for explored-but-not-visible tiles
    warm_g: float = 0.12  # Green reduction for warm (non-white) lights (higher = more orange)
    warm_b: float = 0.40  # Blue reduction for warm lights (higher = more orange/red)
    directional_contrast: float = 0.9  # Strength of directional lighting detail (0.0 = flat, 1.0+ = strong)
    light_height: float = 1.5  # Height of lights above ground (affects shadow angles)
    
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

in vec2 v_texcoord;
out vec4 frag_color;

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
        
        // Compute falloff (EXACTLY matches CPU: (radius_sq - dist_sq) / radius_sq * intensity)
        float falloff = clamp((radius_sq - dist_sq) / radius_sq, 0.0, 1.0) * intensity;
        if (falloff < u_falloff_threshold) {
            continue;
        }
        
        // Compute light direction (EXACTLY matches CPU inv_len calculation)
        float dist_plus_h = dist_sq + light_height_sq;
        float inv_len = 1.0 / sqrt(dist_plus_h);
        float light_dir_x = dx * inv_len;
        float light_dir_y = dy * inv_len;
        float light_dir_z = u_light_height * inv_len;
        
        // Diffuse lighting (EXACTLY matches CPU diffuse calculation)
        float diffuse = normal.x * light_dir_x +
                       normal.y * light_dir_y +
                       normal.z * light_dir_z;
        diffuse = max(0.0, diffuse);
        
        // Contribution (EXACTLY matches CPU)
        float contribution = falloff * diffuse * alpha;
        if (contribution < u_falloff_threshold) {
            continue;
        }
        
        // Accumulate to appropriate channel (EXACTLY matches CPU)
        if (is_white) {
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
    
    def _init_gpu(self) -> bool:
        """Initialize GPU context, shaders, and resources.
        
        Returns:
            True if GPU initialization succeeded, False otherwise.
        """
        if self._gpu_initialized:
            return True
        if self._gpu_failed or not _MODERNGL_AVAILABLE:
            return False
            
        try:
            # Create standalone OpenGL context
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
            return True
            
        except Exception:
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
        if self._gpu_fbo and self._gpu_fbo.size == (out_w, out_h):
            return
            
        # Create/recreate textures for material atlases
        texture_configs = [
            ('normal_atlas', 3),
            ('alpha_atlas', 1),
            ('emission_atlas', 3),
            ('specular_atlas', 3),
            ('normal_detail_atlas', 1),
            ('specular_mask_atlas', 1),
        ]
        
        for name, components in texture_configs:
            if name in self._gpu_textures:
                self._gpu_textures[name].release()
            self._gpu_textures[name] = self._gpu_ctx.texture(
                (out_w, out_h), components, dtype='f4'
            )
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

    def _ensure_buffers(self, out_h: int, out_w: int) -> None:
        if self._buffer_shape == (out_h, out_w):
            return
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
    
    def _build_lightmap_gpu(self, game_map, console) -> np.ndarray:
        """GPU-accelerated lightmap generation using ModernGL fragment shaders.
        
        This method EXACTLY replicates the CPU lighting math but performs the
        per-pixel accumulation on the GPU via fragment shaders.
        """
        if not self._init_gpu():
            # Fallback to CPU if GPU unavailable
            return self._build_lightmap_cpu(game_map, console)
        
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
            out = np.zeros((out_h, out_w, 4), dtype=np.uint8)
            out[..., :3] = 190
            out[..., 3] = 255
            return out
        
        # Build material atlases on CPU (same as CPU path)
        self._build_material_atlases_gpu(game_map, console, origin_x, origin_y, view_w, view_h,
                                        out_w, out_h, scale, px_per_tile_x, px_per_tile_y)
        
        # Upload atlases to GPU (flip Y axis: NumPy has Y=0 at top, OpenGL has Y=0 at bottom)
        self._gpu_textures['normal_atlas'].write(np.flip(self._normal_atlas, axis=0).tobytes())
        self._gpu_textures['alpha_atlas'].write(np.flip(self._alpha_atlas, axis=0).tobytes())
        self._gpu_textures['emission_atlas'].write(np.flip(self._emission_atlas, axis=0).tobytes())
        self._gpu_textures['specular_atlas'].write(np.flip(self._specular_atlas, axis=0).tobytes())
        self._gpu_textures['normal_detail_atlas'].write(np.flip(self._normal_detail_atlas, axis=0).tobytes())
        self._gpu_textures['specular_mask_atlas'].write(np.flip(self._specular_mask_atlas, axis=0).tobytes())
        
        # Bind textures to shader
        for i, name in enumerate(['normal_atlas', 'alpha_atlas', 'emission_atlas',
                                  'specular_atlas', 'normal_detail_atlas', 'specular_mask_atlas']):
            self._gpu_textures[name].use(location=i)
            self._gpu_program[f'u_{name}'] = i
        
        # Prepare light data
        active_lights = list(getattr(game_map, "_active_lights", []) or [])
        num_lights = min(len(active_lights), 256)
        
        light_data = np.zeros((256, 4), dtype=np.float32)
        light_colors = np.zeros((256, 4), dtype=np.float32)
        
        for i, light in enumerate(active_lights[:256]):
            light_data[i] = [
                float(light.get("x", origin_x)),
                float(light.get("y", origin_y)),
                max(1.0, float(light.get("radius", 1.0) or 1.0)),
                float(np.clip(light.get("intensity", 1.0) or 1.0, 0.0, 1.0)),
            ]
            light_colors[i, 0] = 1.0 if light.get("is_white", False) else 0.0
        
        # Set uniforms
        self._gpu_program['u_lights'].write(light_data.tobytes())
        self._gpu_program['u_light_colors'].write(light_colors.tobytes())
        self._gpu_program['u_num_lights'] = num_lights
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
        
        # Render to framebuffer
        self._gpu_fbo.use()
        self._gpu_ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._gpu_vao.render(moderngl.TRIANGLE_STRIP)
        
        # Download result
        raw = self._gpu_fbo.read(components=4, dtype='f1')
        out = np.frombuffer(raw, dtype=np.uint8).reshape((out_h, out_w, 4))
        out = np.flip(out, axis=0).copy()  # Flip Y (OpenGL convention)
        
        # Handle explored-but-not-visible tiles on CPU (same as CPU path)
        visible = np.asarray(game_map.visible[x_slice, y_slice], dtype=bool).T
        explored = np.asarray(game_map.explored[x_slice, y_slice], dtype=bool).T
        dark_bg = np.asarray(game_map.tiles["dark"]["bg"][x_slice, y_slice], dtype=np.float32).transpose(1, 0, 2)
        light_bg = np.asarray(game_map.tiles["light"]["bg"][x_slice, y_slice], dtype=np.float32).transpose(1, 0, 2)
        with np.errstate(divide="ignore", invalid="ignore"):
            explored_ratio = np.where(light_bg > 0.0, dark_bg / light_bg, 0.0)
        explored_ratio = np.clip(explored_ratio, 0.0, float(self.config.explored_mod))
        
        tile_x0 = (np.arange(view_w, dtype=np.int32) * tile_w) // scale
        tile_x1 = (np.arange(1, view_w + 1, dtype=np.int32) * tile_w) // scale
        tile_y0 = (np.arange(view_h, dtype=np.int32) * tile_h) // scale
        tile_y1 = (np.arange(1, view_h + 1, dtype=np.int32) * tile_h) // scale
        tile_x1 = np.clip(np.maximum(tile_x1, tile_x0 + 1), 1, out_w)
        tile_y1 = np.clip(np.maximum(tile_y1, tile_y0 + 1), 1, out_h)
        
        explored_coords = np.argwhere(np.logical_and(explored, np.logical_not(visible)))
        for tile_y, tile_x in explored_coords:
            px0 = int(tile_x0[int(tile_x)])
            px1 = int(tile_x1[int(tile_x)])
            py0 = int(tile_y0[int(tile_y)])
            py1 = int(tile_y1[int(tile_y)])
            out[py0:py1, px0:px1, 0] = np.uint8(np.clip(explored_ratio[int(tile_y), int(tile_x), 0] * 255.0, 0.0, 255.0))
            out[py0:py1, px0:px1, 1] = np.uint8(np.clip(explored_ratio[int(tile_y), int(tile_x), 1] * 255.0, 0.0, 255.0))
            out[py0:py1, px0:px1, 2] = np.uint8(np.clip(explored_ratio[int(tile_y), int(tile_x), 2] * 255.0, 0.0, 255.0))
        
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
        
        visible = np.asarray(game_map.visible[x_slice, y_slice], dtype=bool).T
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
        
        # Material gather pass (EXACTLY matches CPU conditional copying logic)
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
                cp=cp, scale=scale, out_h=block_h, out_w=block_w,
            )
            
            # Always copy alpha for composition
            self._alpha_atlas[py0:py1, px0:px1] = a_view
            
            in_light_tiles = lit_tile_mask[int(tile_y), int(tile_x)]
            # Use faster any() instead of max() for boolean checks
            has_emissive = np.any(e_view > self.config.alpha_threshold)
            has_specular = np.any(sm_view > self.config.detail_threshold)
            has_normal_detail = np.any(nd_view > self.config.detail_threshold)
            
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

    def build_lightmap(self, game_map, console) -> np.ndarray:
        """Return a full-resolution RGBA lightmap for the current frame.
        
        Routes to GPU or CPU implementation based on mode setting.
        """
        if self.mode == "gpu" and _MODERNGL_AVAILABLE:
            try:
                return self._build_lightmap_gpu(game_map, console)
            except Exception:
                # Fall back to CPU on any GPU error
                self._gpu_failed = True
                return self._build_lightmap_cpu(game_map, console)
        else:
            return self._build_lightmap_cpu(game_map, console)
    
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

        # Explored-but-not-visible pass.
        explored_coords = np.argwhere(np.logical_and(explored, np.logical_not(visible)))
        for tile_y, tile_x in explored_coords:
            px0 = int(tile_x0[int(tile_x)])
            px1 = int(tile_x1[int(tile_x)])
            py0 = int(tile_y0[int(tile_y)])
            py1 = int(tile_y1[int(tile_y)])
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
        except Exception:
            mode = "cpu"
    
    if _ENGINE_SINGLETON is None or _ENGINE_SINGLETON.mode != mode:
        _ENGINE_SINGLETON = create_lighting_engine(mode=mode)
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
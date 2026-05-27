"""Shared OpenGL bridge scaffold for unified renderer composition.

This module intentionally provides a conservative API surface that can be
implemented incrementally without destabilizing the SDL fallback path.
"""

from __future__ import annotations

try:
	import moderngl
except Exception:
	moderngl = None

try:
	from OpenGL import GL as _gl
except Exception:
	_gl = None


_COMPOSE_VS = """
#version 330
in vec2 in_vert;
in vec2 in_texcoord;
out vec2 v_uv;
void main() {
	v_uv = in_texcoord;
	gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""


_COMPOSE_FS = """
#version 330
uniform sampler2D u_lightmap;
in vec2 v_uv;
out vec4 fragColor;
void main() {
	fragColor = texture(u_lightmap, v_uv);
}
"""


class GLBridge:
	"""Bridge object for adopting/using a shared OpenGL context.

	Current status: scaffold only. Composition methods return False so callers
	can cleanly fall back to existing paths.
	"""

	def __init__(self) -> None:
		self._adopted = False
		self._reason = "GL bridge compose pass not implemented"
		self._ctx = None
		self._program = None
		self._vao = None
		self._vbo = None
		# Safety gate: composing to the default framebuffer from here can bypass
		# SDL render targets (scene/post buffers) and break visual parity.
		self._allow_default_framebuffer_compose = False

	@property
	def adopted(self) -> bool:
		return self._adopted

	def diagnostic_reason(self) -> str:
		return self._reason

	def adopt_from_renderer(self, renderer) -> bool:
		"""Attempt to adopt/share the active renderer's OpenGL context.

		Returns True on success; False means caller should use fallback paths.
		"""
		_ = renderer
		if self._adopted and self._ctx is not None:
			return True
		if moderngl is None:
			self._adopted = False
			self._reason = "ModernGL unavailable"
			return False
		try:
			# Adopt the currently bound GL context managed by SDL/renderer.
			self._ctx = moderngl.create_context()
			self._program = self._ctx.program(
				vertex_shader=_COMPOSE_VS,
				fragment_shader=_COMPOSE_FS,
			)
			# Simpler: build vertex bytes from float array.
			import struct
			quad = struct.pack(
				"16f",
				-1.0,
				-1.0,
				0.0,
				0.0,
				1.0,
				-1.0,
				1.0,
				0.0,
				-1.0,
				1.0,
				0.0,
				1.0,
				1.0,
				1.0,
				1.0,
				1.0,
			)
			self._vbo = self._ctx.buffer(quad)
			self._vao = self._ctx.vertex_array(
				self._program,
				[(self._vbo, "2f 2f", "in_vert", "in_texcoord")],
			)
			self._adopted = True
			self._reason = "adopted shared OpenGL context"
			print("[GLBridge] Adopted SDL OpenGL context (shared mode).")
			return True
		except Exception as e:
			self._adopted = False
			self._reason = f"context adoption failed: {type(e).__name__}: {e!r}"
			return False

	def get_context(self):
		return self._ctx

	def compose_modulate_from_shader_output(
		self,
		*,
		lighting_engine,
		dest_offset_x: int,
		dest_offset_y: int,
		game_dest_w: int,
		game_dest_h: int,
	) -> bool:
		"""Compose shader output onto the active frame with MOD-like blending.

		This is the future zero-copy composition entrypoint.
		"""
		_ = (dest_offset_x, dest_offset_y, game_dest_w, game_dest_h)
		if not self._adopted or self._ctx is None or self._program is None or self._vao is None:
			self._reason = "OpenGL context not adopted"
			return False
		if not self._allow_default_framebuffer_compose:
			self._reason = "compose blocked: cannot safely target SDL render target from GL bridge"
			return False
		stage = "start"
		old_viewport = None
		old_blend = None
		old_gl_blend_enabled = None
		old_gl_blend_src = None
		old_gl_blend_dst = None
		try:
			stage = "acquire_shader_output"
			tex = lighting_engine.get_gpu_output_texture()
			tex_size = lighting_engine.get_gpu_output_size()
			if tex is None or tex_size is None:
				self._reason = "shader output texture unavailable"
				return False

			# If contexts differ, sharing is not active and this compose path cannot proceed.
			tex_ctx = getattr(tex, "ctx", None)
			if tex_ctx is not None and tex_ctx is not self._ctx:
				self._reason = "shader/context not shared"
				return False

			# Convert top-left pixel coords into OpenGL bottom-left viewport.
			stage = "query_framebuffer_size"
			try:
				fb_w, fb_h = self._ctx.screen.size
			except Exception:
				vp = tuple(self._ctx.viewport)
				fb_h = int(vp[3])
			vx = int(dest_offset_x)
			vy = int(fb_h - (dest_offset_y + game_dest_h))
			vw = int(game_dest_w)
			vh = int(game_dest_h)
			if vw <= 0 or vh <= 0:
				self._reason = "invalid destination size"
				return False

			stage = "configure_blend_viewport"
			if _gl is not None:
				# Raw GL path is more reliable on adopted contexts.
				old_viewport = tuple(int(v) for v in _gl.glGetIntegerv(_gl.GL_VIEWPORT))
				old_gl_blend_enabled = bool(_gl.glIsEnabled(_gl.GL_BLEND))
				old_gl_blend_src = int(_gl.glGetIntegerv(_gl.GL_BLEND_SRC_RGB))
				old_gl_blend_dst = int(_gl.glGetIntegerv(_gl.GL_BLEND_DST_RGB))
				_gl.glEnable(_gl.GL_BLEND)
				# MOD-equivalent: src * dst + dst * 0
				_gl.glBlendFunc(_gl.GL_DST_COLOR, _gl.GL_ZERO)
				_gl.glViewport(vx, vy, vw, vh)
			else:
				# Fallback to ModernGL state API when PyOpenGL is unavailable.
				old_viewport = self._ctx.viewport
				old_blend = self._ctx.blend_func
				self._ctx.enable(moderngl.BLEND)
				self._ctx.blend_func = (moderngl.DST_COLOR, moderngl.ZERO)
				self._ctx.viewport = (vx, vy, vw, vh)

			stage = "draw"
			tex.use(location=0)
			self._program["u_lightmap"] = 0
			self._vao.render(moderngl.TRIANGLE_STRIP)

			self._reason = "composed"
			return True
		except Exception as e:
			self._reason = f"compose failed at {stage}: {type(e).__name__}: {e!r}"
			return False
		finally:
			if self._ctx is not None:
				if _gl is not None and old_viewport is not None:
					try:
						_gl.glViewport(*old_viewport)
					except Exception:
						pass
					if old_gl_blend_src is not None and old_gl_blend_dst is not None:
						try:
							_gl.glBlendFunc(old_gl_blend_src, old_gl_blend_dst)
						except Exception:
							pass
					if old_gl_blend_enabled is not None and not old_gl_blend_enabled:
						try:
							_gl.glDisable(_gl.GL_BLEND)
						except Exception:
							pass
				if _gl is None and old_viewport is not None:
					try:
						self._ctx.viewport = old_viewport
					except Exception:
						pass
				if _gl is None and old_blend is not None:
					try:
						self._ctx.blend_func = old_blend
					except Exception:
						pass


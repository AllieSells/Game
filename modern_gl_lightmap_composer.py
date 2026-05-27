"""ModernGL lightmap composition bridge for unified render experiments.

This module provides a guarded composer callable for GPUStack. It does not
force composition on unsupported backends and safely falls back to the
existing SDL lightmap path.
"""

from __future__ import annotations
import os

try:
    from renderer.gl_bridge import GLBridge
except Exception:
    GLBridge = None


class ModernGLLightmapComposer:
    """Bridge object used by GPUStack for optional unified lightmap composition."""

    def __init__(self, renderer):
        self.renderer = renderer
        self._warned_unavailable = False
        self._reported_success = False
        self._bridge = GLBridge() if GLBridge is not None else None
        self._bridge_adopted = False
        self._compose_attempts = 0
        self._compose_successes = 0
        self._last_reason = "not attempted"

    def __call__(self, **kwargs) -> bool:
        return self.compose(**kwargs)

    def _renderer_backend(self) -> str:
        """Best-effort backend detection from renderer attributes/repr."""
        candidates: list[str] = []
        for attr in ("name", "driver", "driver_name", "backend"):
            value = getattr(self.renderer, attr, None)
            if value is not None:
                candidates.append(str(value).lower())
        candidates.append(repr(self.renderer).lower())
        haystack = " ".join(candidates)
        if "opengl" in haystack or "gl" in haystack:
            return "opengl"
        if "d3d11" in haystack or "direct3d" in haystack or "d3d" in haystack:
            return "d3d11"
        if "metal" in haystack:
            return "metal"
        if "vulkan" in haystack:
            return "vulkan"
        return "unknown"

    def is_available(self) -> bool:
        """Return True only when unified composition is expected to be viable."""
        # Current frame path uses SDL renderer targets, and this bridge needs
        # a verified shared GL context pipeline to blend without readback.
        if self._bridge is None:
            self._last_reason = self.availability_reason()
            return False
        if not self._bridge_adopted:
            self._bridge_adopted = bool(self._bridge.adopt_from_renderer(self.renderer))
            if not self._bridge_adopted:
                self._last_reason = self.availability_reason()
        return self._bridge_adopted

    def availability_reason(self) -> str:
        """Return a short reason string for diagnostics/logging."""
        backend = self._renderer_backend()
        sdl_hint = os.environ.get("SDL_HINT_RENDER_DRIVER", "")
        hint_suffix = f" (SDL_HINT_RENDER_DRIVER={sdl_hint})" if sdl_hint else ""
        if self._bridge_adopted:
            return "available"
        if self._bridge is None:
            return "GL bridge module unavailable"
        if not self._bridge_adopted and not self.is_available():
            return self._bridge.diagnostic_reason() + hint_suffix + f"; backend={backend}"
        return "context not adopted" + hint_suffix + f"; backend={backend}"

    def prepare_engine(self, lighting_engine) -> bool:
        """Attach lighting engine to shared GL context before GPU render."""
        if not self.is_available():
            self._last_reason = self.availability_reason()
            return False
        if not hasattr(lighting_engine, "set_external_gpu_context"):
            self._last_reason = "lighting engine missing set_external_gpu_context"
            return False
        ctx = self._bridge.get_context() if self._bridge is not None else None
        if ctx is None:
            self._last_reason = "shared GL context unavailable"
            return False
        try:
            ok = bool(lighting_engine.set_external_gpu_context(ctx))
            if not ok:
                self._last_reason = "failed to attach external GL context to shader engine"
            return ok
        except Exception:
            self._last_reason = "exception while attaching external GL context"
            return False

    def status_snapshot(self) -> dict:
        return {
            "backend": self._renderer_backend(),
            "render_hint": os.environ.get("SDL_HINT_RENDER_DRIVER", ""),
            "bridge_adopted": bool(self._bridge_adopted),
            "compose_attempts": int(self._compose_attempts),
            "compose_successes": int(self._compose_successes),
            "last_reason": str(self._last_reason),
        }

    def status_line(self) -> str:
        s = self.status_snapshot()
        return (
            "UnifiedGL status: "
            + f"backend={s['backend']} "
            + (f"hint={s['render_hint']} " if s["render_hint"] else "")
            + f"adopted={s['bridge_adopted']} "
            + f"compose_ok={s['compose_successes']}/{s['compose_attempts']} "
            + f"reason={s['last_reason']}"
        )

    def compose(
        self,
        *,
        lighting_engine,
        renderer,
        dest_offset_x: int,
        dest_offset_y: int,
        game_dest_w: int,
        game_dest_h: int,
    ) -> bool:
        """Attempt to composite the pre-rendered GPU lightmap.

        Returns True if composition succeeded, False to let GPUStack use its
        stable legacy fallback path.
        """
        _ = (lighting_engine, renderer, dest_offset_x, dest_offset_y, game_dest_w, game_dest_h)

        if not self.is_available():
            self._last_reason = self.availability_reason()
            return False

        self._compose_attempts += 1

        composed = bool(
            self._bridge.compose_modulate_from_shader_output(
                lighting_engine=lighting_engine,
                dest_offset_x=dest_offset_x,
                dest_offset_y=dest_offset_y,
                game_dest_w=game_dest_w,
                game_dest_h=game_dest_h,
            )
        )
        if composed:
            self._compose_successes += 1
            self._last_reason = "composed"
            if not self._reported_success:
                print("[INFO]: Unified ModernGL lightmap compose active (shared-context path).")
                self._reported_success = True
            return True
        self._last_reason = self._bridge.diagnostic_reason()

        # Keep fallback semantics intact until shared-context composition is
        # fully integrated and validated for visual parity.
        if not self._warned_unavailable:
            print(
                "[INFO]: Unified ModernGL lightmap compositor not yet active"
                + f" ({self._bridge.diagnostic_reason()}); using SDL fallback."
            )
            self._warned_unavailable = True
        return False

"""
Sphere graph visual editor — tkinter Canvas

Controls
--------
  Left-click       select node
  Drag node        reposition
  Double-click     open edit dialog
  Middle-drag      pan canvas
  Scroll wheel     zoom in / out
  Right-click      context menu
  Delete key       delete selected node
"""

import json
import math
import os
import random
import tkinter as tk
from tkinter import messagebox, simpledialog

FORCE_REPULSION  = 180000.0 # node-node push strength
FORCE_SPRING     = 0.018    # child-edge pull strength
FORCE_GRAVITY    = 0.006    # weak pull toward canvas centre
FORCE_DAMPING    = 0.78     # velocity decay per tick
FORCE_REST_LEN   = 420.0    # ideal edge length (px world)
FORCE_TICKS      = 600      # simulation steps for one-shot layout
FORCE_TICK_MS    = 16       # ms per animated tick

JSON_PATH   = os.path.join(os.path.dirname(__file__), "..", "..", "json", "spheres.json")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "json", "sphere_schema.json")

# Built-in reserved keys — never treated as custom attributes
_RESERVED = {"children", "precluded"}

# ── Palette ────────────────────────────────────────────────────────────────
BG          = "#1e1e2e"
SIDEBAR_BG  = "#181825"
NODE_FILL   = "#313244"
NODE_SEL    = "#89b4fa"
NODE_OUT    = "#585b70"
NODE_SEL_OUT= "#89b4fa"
EDGE_CHILD  = "#a6e3a1"
EDGE_PREC   = "#f38ba8"
TEXT_COL    = "#cdd6f4"
TEXT_DARK   = "#1e1e2e"
BTN_BG      = "#45475a"
NODE_R      = 36


class SphereUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.configure(bg=BG)

        self.data: dict[str, dict] = {}
        self.pos: dict[str, list] = {}         # world coords [x, y]

        self.selected: str | None = None
        self._drag_node: str | None = None
        self._drag_ox: float = 0.0
        self._drag_oy: float = 0.0
        self._vel: dict[str, list] = {}   # velocity for force sim
        self._sim_job: str | None = None  # after() handle
        self._show_all_edges = tk.BooleanVar(value=False)

        # Pan / zoom
        self.scale: float = 1.0
        self.ox: float = 0.0
        self.oy: float = 0.0
        self._pan_start: tuple = (0, 0)
        self._pan_ox: float = 0.0
        self._pan_oy: float = 0.0
        self._panning: bool = False

        self._build_ui()
        self._load()
        self._load_schema()
        # Animate the initial layout once the window is visible
        self.root.after(100, self._cmd_auto_layout)

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Toolbar
        tb = tk.Frame(self.root, bg=SIDEBAR_BG, pady=6)
        tb.pack(side=tk.TOP, fill=tk.X)

        for label, cmd in [
            ("Add sphere",  self._cmd_add),
            ("Auto layout", self._cmd_auto_layout),
            ("Reload",      self._cmd_reload),
            ("Save",        self._cmd_save),
            ("Attributes",  self._cmd_manage_attrs),
        ]:
            tk.Button(
                tb, text=label, command=cmd,
                bg=BTN_BG, fg=TEXT_COL, relief=tk.FLAT,
                padx=12, pady=3, activebackground=NODE_SEL,
            ).pack(side=tk.LEFT, padx=4)

        tk.Checkbutton(
            tb, text="Show all edges",
            variable=self._show_all_edges,
            command=self._draw,
            bg=SIDEBAR_BG, fg=TEXT_COL, selectcolor=BTN_BG,
            activebackground=SIDEBAR_BG, activeforeground=TEXT_COL,
            relief=tk.FLAT, padx=8,
        ).pack(side=tk.LEFT, padx=4)

        tk.Label(tb, text="  ─ child", bg=SIDEBAR_BG, fg=EDGE_CHILD,
                 font=("Consolas", 10)).pack(side=tk.RIGHT, padx=6)
        tk.Label(tb, text="⋯ precluded", bg=SIDEBAR_BG, fg=EDGE_PREC,
                 font=("Consolas", 10)).pack(side=tk.RIGHT)

        # Canvas + sidebar
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(row, bg=BG, highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = tk.Frame(row, bg=SIDEBAR_BG, width=270)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        sb.pack_propagate(False)

        tk.Label(sb, text="Details", bg=SIDEBAR_BG, fg=NODE_SEL,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=12, pady=(12, 4))

        self.detail_text = tk.Text(
            sb, bg=SIDEBAR_BG, fg=TEXT_COL, font=("Consolas", 10),
            relief=tk.FLAT, state=tk.DISABLED, wrap=tk.WORD, width=30,
        )
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=8)

        tk.Frame(sb, bg=NODE_OUT, height=1).pack(fill=tk.X, padx=8, pady=8)

        tk.Label(sb, text="Attributes", bg=SIDEBAR_BG, fg=NODE_SEL,
                 font=("Consolas", 11, "bold")).pack(anchor="w", padx=12)

        self.attr_frame = tk.Frame(sb, bg=SIDEBAR_BG)
        self.attr_frame.pack(fill=tk.X, padx=8, pady=(4, 8))

        tk.Frame(sb, bg=NODE_OUT, height=1).pack(fill=tk.X, padx=8, pady=4)

        for label, cmd in [
            ("Edit selected",   self._cmd_edit_selected),
            ("Expand subtree",  self._cmd_expand_selected),
            ("Delete selected", self._cmd_delete_selected),
        ]:
            tk.Button(
                sb, text=label, command=cmd,
                bg=BTN_BG, fg=TEXT_COL, relief=tk.FLAT,
                pady=5, width=24, activebackground=NODE_SEL,
            ).pack(pady=3)

        tk.Label(sb, text="Middle-drag: pan  |  Scroll: zoom",
                 bg=SIDEBAR_BG, fg="#585b70", font=("Consolas", 8)
                 ).pack(pady=(8, 4))

        # ── Bindings
        c = self.canvas
        c.bind("<Button-1>",         self._on_click)
        c.bind("<Double-Button-1>",  self._on_dbl_click)
        c.bind("<B1-Motion>",        self._on_drag)
        c.bind("<ButtonRelease-1>",  self._on_release)
        c.bind("<Button-2>",         self._on_pan_start)
        c.bind("<B2-Motion>",        self._on_pan_drag)
        c.bind("<ButtonRelease-2>",  self._on_pan_end)
        c.bind("<Button-3>",         self._on_right_click)
        c.bind("<MouseWheel>",       self._on_scroll)     # Windows / macOS
        c.bind("<Button-4>",         self._on_scroll)     # Linux up
        c.bind("<Button-5>",         self._on_scroll)     # Linux down
        self.root.bind("<Delete>",   lambda _: self._cmd_delete_selected())

    # ── Data I/O ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if os.path.exists(JSON_PATH):
            with open(JSON_PATH, encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    self.data = json.loads(content)
        self.pos = {k: v for k, v in self.pos.items() if k in self.data}

    def _save_json(self) -> None:
        os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
    def _load_schema(self) -> None:
        """Load attribute schema: {name: type}  types: text | number | bool"""
        if os.path.exists(SCHEMA_PATH):
            with open(SCHEMA_PATH, encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    self.schema: dict[str, str] = json.loads(content)
                    return
        self.schema: dict[str, str] = {}

    def _save_schema(self) -> None:
        os.makedirs(os.path.dirname(SCHEMA_PATH), exist_ok=True)
        with open(SCHEMA_PATH, "w", encoding="utf-8") as f:
            json.dump(self.schema, f, indent=2, ensure_ascii=False)
    # ── Layout ─────────────────────────────────────────────────────────────

    def _circle_init(self) -> None:
        """Place nodes evenly on a circle as the force-sim starting point."""
        nodes = list(self.data.keys())
        n = len(nodes)
        if not n:
            return
        self._cx = max(600, self.canvas.winfo_width())  / 2
        self._cy = max(500, self.canvas.winfo_height()) / 2
        # Large starting radius so nodes have room to settle without collapsing first
        radius = max(500, NODE_R * 5.5 * math.sqrt(n))
        self.pos = {}
        self._vel = {}
        for i, key in enumerate(nodes):
            angle = 2 * math.pi * i / n
            self.pos[key] = [
                self._cx + radius * math.cos(angle) + random.uniform(-20, 20),
                self._cy + radius * math.sin(angle) + random.uniform(-20, 20),
            ]
            self._vel[key] = [0.0, 0.0]
        self.ox, self.oy, self.scale = 0.0, 0.0, 1.0

    def _force_tick(self, temperature: float) -> float:
        """One step of force-directed simulation. Returns updated temperature."""
        nodes = [k for k in self.data if k in self.pos]
        disp: dict[str, list] = {k: [0.0, 0.0] for k in nodes}

        cx = getattr(self, "_cx", 600.0)
        cy = getattr(self, "_cy", 400.0)

        # Repulsion between every pair
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                dx = self.pos[a][0] - self.pos[b][0]
                dy = self.pos[a][1] - self.pos[b][1]
                dist2 = max(dx * dx + dy * dy, 1.0)
                dist  = math.sqrt(dist2)
                force = FORCE_REPULSION / dist2
                fx, fy = force * dx / dist, force * dy / dist
                disp[a][0] += fx
                disp[a][1] += fy
                disp[b][0] -= fx
                disp[b][1] -= fy

        # Spring attraction along children edges ONLY (not precluded)
        for sphere, v in self.data.items():
            if sphere not in self.pos:
                continue
            for child in v.get("children", []):
                if child not in self.pos:
                    continue
                dx = self.pos[child][0] - self.pos[sphere][0]
                dy = self.pos[child][1] - self.pos[sphere][1]
                dist = math.hypot(dx, dy) or 0.01
                delta = dist - FORCE_REST_LEN
                fx = FORCE_SPRING * delta * dx / dist
                fy = FORCE_SPRING * delta * dy / dist
                disp[sphere][0] += fx
                disp[sphere][1] += fy
                disp[child][0]  -= fx
                disp[child][1]  -= fy

        # Weak gravity toward canvas centre (keeps isolated nodes from flying off)
        for k in nodes:
            disp[k][0] += FORCE_GRAVITY * (cx - self.pos[k][0])
            disp[k][1] += FORCE_GRAVITY * (cy - self.pos[k][1])

        # Apply, clamp to temperature, damp velocity
        for k in nodes:
            if k == self._drag_node:
                continue
            vx = (self._vel.get(k, [0.0, 0.0])[0] + disp[k][0]) * FORCE_DAMPING
            vy = (self._vel.get(k, [0.0, 0.0])[1] + disp[k][1]) * FORCE_DAMPING
            speed = math.hypot(vx, vy)
            if speed > temperature:
                vx, vy = vx / speed * temperature, vy / speed * temperature
            self._vel[k] = [vx, vy]
            self.pos[k][0] += vx
            self.pos[k][1] += vy

        return temperature * 0.985  # cool down

    def _cmd_auto_layout(self) -> None:
        """Reset to circle, then animate the force simulation."""
        if self._sim_job is not None:
            self.root.after_cancel(self._sim_job)
            self._sim_job = None
        self._circle_init()
        self._animate_sim(temperature=300.0, ticks_left=FORCE_TICKS)

    def _animate_sim(self, temperature: float, ticks_left: int) -> None:
        if ticks_left <= 0 or temperature < 0.5:
            self._fit_view()
            self._draw()
            self._sim_job = None
            return
        temperature = self._force_tick(temperature)
        self._draw()
        self._sim_job = self.root.after(
            FORCE_TICK_MS,
            lambda: self._animate_sim(temperature, ticks_left - 1)
        )

    def _fit_view(self) -> None:
        """Scale + pan so all nodes are visible with padding."""
        if not self.pos:
            return
        cw = self.canvas.winfo_width()  or 1000
        ch = self.canvas.winfo_height() or 700
        xs = [p[0] for p in self.pos.values()]
        ys = [p[1] for p in self.pos.values()]
        pad = NODE_R * 3
        wx = max(xs) - min(xs) + pad * 2
        wy = max(ys) - min(ys) + pad * 2
        self.scale = min(cw / wx, ch / wy, 1.0)   # never zoom in past 100%
        self.ox = cw / 2 - (min(xs) + max(xs)) / 2 * self.scale
        self.oy = ch / 2 - (min(ys) + max(ys)) / 2 * self.scale

    def _full_layout(self) -> None:
        """Instant (non-animated) force layout — run many ticks at once."""
        if not self.data:
            return
        self._circle_init()
        temp = 300.0
        for _ in range(FORCE_TICKS):
            temp = self._force_tick(temp)
            if temp < 0.5:
                break
        self._fit_view()

    def _ensure_positions(self) -> None:
        """Give any node missing a position a random spot near the centre."""
        if not self.pos and self.data:
            self._circle_init()
            return
        cx = sum(p[0] for p in self.pos.values()) / max(len(self.pos), 1)
        cy = sum(p[1] for p in self.pos.values()) / max(len(self.pos), 1)
        for key in self.data:
            if key not in self.pos:
                self.pos[key] = [
                    cx + random.uniform(-80, 80),
                    cy + random.uniform(-80, 80),
                ]
                self._vel[key] = [0.0, 0.0]

    # ── Transforms ─────────────────────────────────────────────────────────

    def _w2c(self, wx: float, wy: float) -> tuple[float, float]:
        return wx * self.scale + self.ox, wy * self.scale + self.oy

    def _c2w(self, cx: float, cy: float) -> tuple[float, float]:
        return (cx - self.ox) / self.scale, (cy - self.oy) / self.scale

    # ── Drawing ────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        self._ensure_positions()
        c = self.canvas
        c.delete("all")
        r = NODE_R * self.scale
        show_all = self._show_all_edges.get()

        # Work out which nodes are "active" (selected + its direct neighbours)
        active: set[str] = set()
        if self.selected and self.selected in self.data:
            active.add(self.selected)
            v = self.data[self.selected]
            active.update(v.get("children", []))
            active.update(v.get("precluded", []))
            # also nodes that list selected as their child
            for k, vv in self.data.items():
                if self.selected in vv.get("children", []) or self.selected in vv.get("precluded", []):
                    active.add(k)

        # ── Edges ──────────────────────────────────────────────────────────
        for sphere, v in self.data.items():
            if sphere not in self.pos:
                continue
            cx1, cy1 = self._w2c(*self.pos[sphere])

            for child in v.get("children", []):
                if child not in self.pos:
                    continue
                cx2, cy2 = self._w2c(*self.pos[child])
                if show_all or (sphere in active and child in active):
                    self._draw_edge(cx1, cy1, cx2, cy2, r, EDGE_CHILD, (), alpha=1.0)
                elif not active:  # nothing selected — show faint
                    self._draw_edge(cx1, cy1, cx2, cy2, r, "#2a3d2a", (), alpha=1.0)
                else:             # not in focus — very dim
                    self._draw_edge(cx1, cy1, cx2, cy2, r, "#252535", (), alpha=1.0)

            for prec in v.get("precluded", []):
                if prec not in self.pos:
                    continue
                cx2, cy2 = self._w2c(*self.pos[prec])
                if show_all or (sphere in active and prec in active):
                    self._draw_edge(cx1, cy1, cx2, cy2, r, EDGE_PREC, (5, 4), alpha=1.0)
                elif not active:
                    self._draw_edge(cx1, cy1, cx2, cy2, r, "#3d2a2a", (5, 4), alpha=1.0)
                else:
                    self._draw_edge(cx1, cy1, cx2, cy2, r, "#252535", (5, 4), alpha=1.0)

        # ── Nodes ──────────────────────────────────────────────────────────
        font_size = max(7, int(9 * self.scale))
        for sphere in self.data:
            if sphere not in self.pos:
                continue
            cx, cy = self._w2c(*self.pos[sphere])
            sel = sphere == self.selected
            neighbour = sphere in active and not sel
            dimmed = bool(active) and sphere not in active and not show_all

            fill    = NODE_SEL  if sel      else (NODE_FILL if not dimmed else "#252535")
            outline = NODE_SEL_OUT if sel   else (NODE_OUT  if not dimmed else "#303040")
            txt_col = TEXT_DARK if sel      else (TEXT_COL  if not dimmed else "#404055")

            c.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill=fill, outline=outline,
                width=3 if sel else (2 if neighbour else 1),
                tags=("node", f"N:{sphere}"),
            )
            label = sphere if len(sphere) <= 11 else sphere[:10] + "…"
            c.create_text(
                cx, cy, text=label,
                fill=txt_col,
                font=("Consolas", font_size, "bold"),
            )

    def _draw_edge(self, x1, y1, x2, y2, r, color, dash, alpha=1.0) -> None:
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy)
        if dist < 1:
            return
        ux, uy = dx / dist, dy / dist
        lw = max(1.0, 1.5 * self.scale)
        asz = (max(6, int(10 * self.scale)),
               max(8, int(12 * self.scale)),
               max(3, int(4  * self.scale)))
        self.canvas.create_line(
            x1 + ux * r, y1 + uy * r,
            x2 - ux * r, y2 - uy * r,
            fill=color, width=lw, dash=dash,
            arrow=tk.LAST, arrowshape=asz,
        )

    # ── Sidebar ────────────────────────────────────────────────────────────

    def _update_sidebar(self) -> None:
        t = self.detail_text
        t.config(state=tk.NORMAL)
        t.delete("1.0", tk.END)
        if self.selected and self.selected in self.data:
            v = self.data[self.selected]
            parents = [k for k, vv in self.data.items()
                       if self.selected in vv.get("children", [])]
            t.insert(tk.END, f"[ {self.selected} ]\n\n")
            t.insert(tk.END, f"Parents:\n  {', '.join(parents) or '(none)'}\n\n")
            t.insert(tk.END, f"Children:\n  {chr(10).join('  ' + c for c in v.get('children', [])) or '  (none)'}\n\n")
            t.insert(tk.END, f"Precluded:\n  {chr(10).join('  ' + p for p in v.get('precluded', [])) or '  (none)'}")
        else:
            t.insert(tk.END, "Click a node to\nsee its details.")
        t.config(state=tk.DISABLED)

        # Refresh attribute widgets
        for widget in self.attr_frame.winfo_children():
            widget.destroy()
        if self.selected and self.selected in self.data and self.schema:
            v = self.data[self.selected]
            for attr, atype in self.schema.items():
                val = v.get(attr, "")
                row = tk.Frame(self.attr_frame, bg=SIDEBAR_BG)
                row.pack(fill=tk.X, pady=1)
                tk.Label(row, text=f"{attr}:", bg=SIDEBAR_BG, fg="#a6adc8",
                         font=("Consolas", 9), width=14, anchor="w").pack(side=tk.LEFT)
                display = str(val) if val != "" else "—"
                btn = tk.Button(
                    row, text=display, bg=BTN_BG, fg=TEXT_COL,
                    font=("Consolas", 9), relief=tk.FLAT, anchor="w",
                    command=lambda a=attr, at=atype: self._edit_attr(a, at),
                )
                btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        elif self.schema and not self.selected:
            tk.Label(self.attr_frame, text="(select a node)",
                     bg=SIDEBAR_BG, fg="#585b70", font=("Consolas", 9)).pack(anchor="w")
        elif not self.schema:
            tk.Label(self.attr_frame, text="No attributes defined.\nClick 'Attributes'.",
                     bg=SIDEBAR_BG, fg="#585b70", font=("Consolas", 9),
                     justify=tk.LEFT).pack(anchor="w")

    # ── Hit detection ──────────────────────────────────────────────────────

    def _node_at(self, cx: float, cy: float) -> str | None:
        r = NODE_R * self.scale
        for sphere, wp in self.pos.items():
            ncx, ncy = self._w2c(*wp)
            if math.hypot(cx - ncx, cy - ncy) <= r:
                return sphere
        return None

    # ── Canvas events ──────────────────────────────────────────────────────

    def _on_click(self, event) -> None:
        node = self._node_at(event.x, event.y)
        self.selected = node
        if node:
            wx, wy = self._c2w(event.x, event.y)
            self._drag_node = node
            self._drag_ox = wx - self.pos[node][0]
            self._drag_oy = wy - self.pos[node][1]
        self._draw()
        self._update_sidebar()

    def _on_dbl_click(self, event) -> None:
        node = self._node_at(event.x, event.y)
        if node:
            self.selected = node
            self._cmd_edit_selected()

    def _on_drag(self, event) -> None:
        if self._drag_node and self._drag_node in self.pos:
            wx, wy = self._c2w(event.x, event.y)
            self.pos[self._drag_node][0] = wx - self._drag_ox
            self.pos[self._drag_node][1] = wy - self._drag_oy
            self._draw()

    def _on_release(self, event) -> None:
        self._drag_node = None

    def _on_pan_start(self, event) -> None:
        self._panning = True
        self._pan_start = (event.x, event.y)
        self._pan_ox, self._pan_oy = self.ox, self.oy

    def _on_pan_drag(self, event) -> None:
        if self._panning:
            self.ox = self._pan_ox + event.x - self._pan_start[0]
            self.oy = self._pan_oy + event.y - self._pan_start[1]
            self._draw()

    def _on_pan_end(self, event) -> None:
        self._panning = False

    def _on_scroll(self, event) -> None:
        if hasattr(event, "delta"):
            factor = 1.1 if event.delta > 0 else 0.9
        elif event.num == 4:
            factor = 1.1
        else:
            factor = 0.9
        self.scale = max(0.15, min(4.0, self.scale * factor))
        self.ox = event.x - factor * (event.x - self.ox)
        self.oy = event.y - factor * (event.y - self.oy)
        self._draw()

    def _on_right_click(self, event) -> None:
        node = self._node_at(event.x, event.y)
        if not node:
            return
        self.selected = node
        self._draw()
        self._update_sidebar()
        m = tk.Menu(self.root, tearoff=0, bg=BTN_BG, fg=TEXT_COL,
                    activebackground=NODE_SEL, activeforeground=TEXT_DARK)
        m.add_command(label=f"Edit '{node}'",   command=self._cmd_edit_selected)
        m.add_command(label="Expand subtree",   command=self._cmd_expand_selected)
        m.add_separator()
        m.add_command(label="Delete",           command=self._cmd_delete_selected)
        m.tk_popup(event.x_root, event.y_root)

    # ── Commands ───────────────────────────────────────────────────────────

    def _norm(self, s: str) -> str:
        return s.strip().lower().replace(" ", "_")

    def _cmd_add(self) -> None:
        name = simpledialog.askstring("Add sphere", "Sphere name:", parent=self.root)
        if not name:
            return
        key = self._norm(name)
        if key in self.data:
            messagebox.showinfo("Exists", f"'{key}' already exists.", parent=self.root)
            return
        self.data[key] = {"children": [], "precluded": []}
        self._save_json()
        self._ensure_positions()
        self.selected = key
        self._draw()
        self._update_sidebar()

    def _cmd_reload(self) -> None:
        self._load()
        self._full_layout()
        self._draw()
        self._update_sidebar()

    def _cmd_save(self) -> None:
        self._save_json()
        messagebox.showinfo("Saved", f"Saved {len(self.data)} spheres.", parent=self.root)

    # ── Attribute management ────────────────────────────────────────────

    def _edit_attr(self, attr: str, atype: str) -> None:
        """Edit a single attribute on the selected sphere."""
        if not self.selected or self.selected not in self.data:
            return
        v = self.data[self.selected]
        current = v.get(attr, "")

        if atype == "bool":
            new_val = not bool(current)
            v[attr] = new_val
        elif atype == "number":
            raw = simpledialog.askstring(
                attr, f"{attr} (number):",
                initialvalue=str(current), parent=self.root
            )
            if raw is None:
                return
            try:
                v[attr] = float(raw) if "." in raw else int(raw)
            except ValueError:
                messagebox.showerror("Invalid", f"'{raw}' is not a number.", parent=self.root)
                return
        else:  # text
            raw = simpledialog.askstring(
                attr, f"{attr}:",
                initialvalue=str(current), parent=self.root
            )
            if raw is None:
                return
            v[attr] = raw

        self._save_json()
        self._update_sidebar()

    def _cmd_manage_attrs(self) -> None:
        """Dialog to add/remove attribute definitions and bulk-fill them."""
        win = tk.Toplevel(self.root)
        win.title("Attribute Schema")
        win.configure(bg=BG)
        win.geometry("420x480")
        win.grab_set()

        tk.Label(win, text="Attribute Schema", bg=BG, fg=NODE_SEL,
                 font=("Consolas", 13, "bold")).pack(pady=(16, 4))
        tk.Label(win, text="Attributes saved to json/sphere_schema.json",
                 bg=BG, fg="#585b70", font=("Consolas", 9)).pack()

        list_frame = tk.Frame(win, bg=BG)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        def _refresh_list() -> None:
            for w in list_frame.winfo_children():
                w.destroy()
            if not self.schema:
                tk.Label(list_frame, text="No attributes yet.",
                         bg=BG, fg="#585b70", font=("Consolas", 10)).pack()
                return
            for attr, atype in list(self.schema.items()):
                row = tk.Frame(list_frame, bg=BG)
                row.pack(fill=tk.X, pady=2)
                tk.Label(row, text=f"{attr}  ({atype})",
                         bg=BG, fg=TEXT_COL, font=("Consolas", 10),
                         width=28, anchor="w").pack(side=tk.LEFT)
                tk.Button(
                    row, text="Bulk fill", bg=BTN_BG, fg=TEXT_COL,
                    relief=tk.FLAT, font=("Consolas", 9),
                    command=lambda a=attr, at=atype: _bulk_fill(a, at),
                ).pack(side=tk.LEFT, padx=4)
                tk.Button(
                    row, text="Remove", bg="#3d2a2a", fg=EDGE_PREC,
                    relief=tk.FLAT, font=("Consolas", 9),
                    command=lambda a=attr: _remove_attr(a),
                ).pack(side=tk.LEFT)

        def _bulk_fill(attr: str, atype: str) -> None:
            """Walk every sphere, prompting for this attribute in one persistent window."""
            win.grab_release()
            spheres = list(self.data.keys())
            idx = 0

            if atype == "bool":
                # bool stays as quick yes/no/cancel dialogs — no typing needed
                def _next_bool() -> None:
                    nonlocal idx
                    if idx >= len(spheres):
                        self._save_json()
                        self._update_sidebar()
                        messagebox.showinfo("Done", f"Bulk fill complete for '{attr}'.",
                                            parent=self.root)
                        win.grab_set()
                        return
                    key = spheres[idx]
                    current = self.data[key].get(attr, "")
                    ans = messagebox.askyesnocancel(
                        f"{attr}  [{idx+1}/{len(spheres)}]",
                        f"Sphere: {key}\nCurrent: {current}\n\nSet '{attr}' = True?",
                        parent=self.root,
                    )
                    if ans is None:
                        self._save_json()
                        self._update_sidebar()
                        win.grab_set()
                        return
                    self.data[key][attr] = bool(ans)
                    idx += 1
                    _next_bool()
                _next_bool()
                return

            # ── text / number: single persistent window ──────────────────
            dlg = tk.Toplevel(self.root)
            dlg.title(f"Bulk fill — {attr}")
            dlg.configure(bg=BG)
            dlg.geometry("380x200")
            dlg.resizable(False, False)
            dlg.grab_set()

            sphere_label = tk.Label(dlg, text="", bg=BG, fg=NODE_SEL,
                                    font=("Consolas", 12, "bold"))
            sphere_label.pack(pady=(18, 2))

            progress_label = tk.Label(dlg, text="", bg=BG, fg="#585b70",
                                      font=("Consolas", 9))
            progress_label.pack()

            tk.Label(dlg, text=f"{attr} ({atype}):", bg=BG, fg=TEXT_COL,
                     font=("Consolas", 10)).pack(pady=(8, 2))

            var = tk.StringVar()
            entry = tk.Entry(dlg, textvariable=var, bg=BTN_BG, fg=TEXT_COL,
                             font=("Consolas", 11), relief=tk.FLAT,
                             insertbackground=TEXT_COL)
            entry.pack(padx=24, fill=tk.X)

            btn_row = tk.Frame(dlg, bg=BG)
            btn_row.pack(pady=12)

            def _load_sphere() -> None:
                if idx >= len(spheres):
                    dlg.destroy()
                    self._save_json()
                    self._update_sidebar()
                    messagebox.showinfo("Done", f"Bulk fill complete for '{attr}'.",
                                        parent=self.root)
                    win.grab_set()
                    return
                key = spheres[idx]
                current = self.data[key].get(attr, "")
                sphere_label.config(text=key)
                progress_label.config(text=f"{idx + 1} / {len(spheres)}")
                var.set(str(current))
                entry.focus_set()
                entry.select_range(0, tk.END)

            def _save_and_next(skip: bool = False) -> None:
                nonlocal idx
                if not skip:
                    key = spheres[idx]
                    raw = var.get().strip()
                    if atype == "number" and raw:
                        try:
                            self.data[key][attr] = float(raw) if "." in raw else int(raw)
                        except ValueError:
                            messagebox.showerror("Invalid", f"'{raw}' is not a number.",
                                                 parent=dlg)
                            return
                    else:
                        self.data[key][attr] = raw
                idx += 1
                _load_sphere()

            def _stop() -> None:
                dlg.destroy()
                self._save_json()
                self._update_sidebar()
                win.grab_set()

            for txt, fn in [("Save & next", lambda: _save_and_next()),
                             ("Skip",        lambda: _save_and_next(skip=True)),
                             ("Stop",        _stop)]:
                tk.Button(btn_row, text=txt, command=fn,
                          bg=BTN_BG, fg=TEXT_COL, relief=tk.FLAT,
                          padx=10).pack(side=tk.LEFT, padx=4)

            dlg.bind("<Return>", lambda _: _save_and_next())
            dlg.bind("<Escape>", lambda _: _save_and_next(skip=True))

            _load_sphere()

        def _remove_attr(attr: str) -> None:
            if not messagebox.askyesno("Remove",
                    f"Remove '{attr}' from schema?\n(Data on spheres is kept)",
                    parent=win):
                return
            del self.schema[attr]
            self._save_schema()
            _refresh_list()
            self._update_sidebar()

        _refresh_list()

        # ── Add new attribute ──────────────────────────────────────────
        tk.Frame(win, bg=NODE_OUT, height=1).pack(fill=tk.X, padx=16, pady=8)
        add_row = tk.Frame(win, bg=BG)
        add_row.pack(fill=tk.X, padx=16)

        tk.Label(add_row, text="New:", bg=BG, fg=TEXT_COL,
                 font=("Consolas", 10)).pack(side=tk.LEFT)
        name_var = tk.StringVar()
        name_entry = tk.Entry(add_row, textvariable=name_var, bg=BTN_BG, fg=TEXT_COL,
                              font=("Consolas", 10), relief=tk.FLAT, width=14,
                              insertbackground=TEXT_COL)
        name_entry.pack(side=tk.LEFT, padx=6)

        type_var = tk.StringVar(value="text")
        for t_label in ("text", "number", "bool"):
            tk.Radiobutton(
                add_row, text=t_label, variable=type_var, value=t_label,
                bg=BG, fg=TEXT_COL, selectcolor=BTN_BG,
                activebackground=BG, font=("Consolas", 9),
            ).pack(side=tk.LEFT)

        def _add_attr() -> None:
            name = name_var.get().strip().lower().replace(" ", "_")
            if not name:
                return
            if name in _RESERVED:
                messagebox.showerror("Reserved", f"'{name}' is a reserved key.", parent=win)
                return
            if name in self.schema:
                messagebox.showinfo("Exists", f"'{name}' already in schema.", parent=win)
                return
            self.schema[name] = type_var.get()
            self._save_schema()
            name_var.set("")
            _refresh_list()
            self._update_sidebar()

        tk.Button(add_row, text="Add", command=_add_attr,
                  bg=NODE_SEL, fg=TEXT_DARK, relief=tk.FLAT,
                  font=("Consolas", 10, "bold"), padx=10).pack(side=tk.LEFT, padx=6)
        name_entry.bind("<Return>", lambda _: _add_attr())

    def _cmd_edit_selected(self) -> None:
        if not self.selected or self.selected not in self.data:
            return
        key = self.selected
        v = self.data[key]

        new_ch = simpledialog.askstring(
            f"'{key}' — children",
            "Children (comma-separated):",
            initialvalue=", ".join(v.get("children", [])),
            parent=self.root,
        )
        if new_ch is not None:
            v["children"] = [self._norm(c) for c in new_ch.split(",") if c.strip()]
            for c in v["children"]:
                if c not in self.data:
                    self.data[c] = {"children": [], "precluded": []}

        new_pr = simpledialog.askstring(
            f"'{key}' — precluded",
            "Precluded (comma-separated):",
            initialvalue=", ".join(v.get("precluded", [])),
            parent=self.root,
        )
        if new_pr is not None:
            v["precluded"] = [self._norm(p) for p in new_pr.split(",") if p.strip()]
            for p in v["precluded"]:
                if p not in self.data:
                    self.data[p] = {"children": [], "precluded": []}

        self._save_json()
        self._ensure_positions()
        self._draw()
        self._update_sidebar()

    def _cmd_expand_selected(self) -> None:
        if not self.selected or self.selected not in self.data:
            return
        # BFS collect subtree
        visited: list[str] = []
        seen: set[str] = set()
        q = [self.selected]
        while q:
            node = q.pop(0)
            if node in seen or node not in self.data:
                continue
            seen.add(node)
            visited.append(node)
            q.extend(self.data[node].get("children", []))

        preview = " → ".join(visited[:6]) + ("…" if len(visited) > 6 else "")
        if not messagebox.askyesno(
            "Expand subtree",
            f"Edit all {len(visited)} sphere(s) in '{self.selected}' subtree?\n\n{preview}",
            parent=self.root,
        ):
            return

        for node in visited:
            self.selected = node
            self._draw()
            self._update_sidebar()
            self.root.update()
            self._cmd_edit_selected()

        self._ensure_positions()
        self._draw()

    def _cmd_delete_selected(self) -> None:
        if not self.selected:
            return
        if not messagebox.askyesno("Delete", f"Delete '{self.selected}'?", parent=self.root):
            return
        key = self.selected
        del self.data[key]
        self.pos.pop(key, None)
        for v in self.data.values():
            v["children"] = [c for c in v.get("children", []) if c != key]
            v["precluded"] = [p for p in v.get("precluded", []) if p != key]
        self.selected = None
        self._save_json()
        self._draw()
        self._update_sidebar()


def main() -> None:
    root = tk.Tk()
    root.title("Sphere Graph Editor")
    root.geometry("1280x780")
    SphereUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

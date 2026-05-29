"""
Interactive sphere graph builder.

How it works
------------
1. You type a seed sphere (e.g. "fire").
2. You are asked for its children  — spheres that flow from it.
3. You are asked for its precluded — spheres it opposes/blocks.
4. Every new name you type is queued automatically.
5. Progress is saved to json/spheres.json after every entry.
6. Re-running resumes where you left off; dangling references
   are queued automatically.

Commands (usable at any prompt)
--------------------------------
  done / q         — stop the session and save
  skip             — skip the current sphere without defining it
  list             — compact one-liner per sphere (name → children | ✗ precluded)
  tree             — hierarchical view from root spheres
  show <name>      — details + parents for one sphere
  edit <name>      — add children / precluded to an existing sphere
  expand <name>    — walk a sphere + all its descendants, offering to extend each

Post-queue menu
---------------
  a — add a new sphere
  e — edit an existing sphere
  x — expand a subtree (recursive edit walk)
  l — list all   |   t — tree view   |   q — quit
"""

import json
import os
import sys
from collections import deque

JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "json", "spheres.json")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load() -> dict:
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    return {}


def save(data: dict) -> None:
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [saved — {len(data)} spheres]")


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _display_list(data: dict) -> None:
    """One compact line per sphere, alphabetical."""
    if not data:
        print("  (none yet)")
        return
    col = max(len(k) for k in data) + 2
    for key in sorted(data):
        v = data[key]
        children = v.get("children", [])
        precluded = v.get("precluded", [])
        parts = []
        if children:
            parts.append(f"→ {', '.join(children)}")
        if precluded:
            parts.append(f"✗ {', '.join(precluded)}")
        print(f"  {key:<{col}}{('  |  '.join(parts)) if parts else '(no relations)'}")


def _display_tree(data: dict) -> None:
    """Print a hierarchy from root spheres (those with no parents)."""
    all_children: set[str] = {c for v in data.values() for c in v.get("children", [])}
    roots = sorted(k for k in data if k not in all_children) or sorted(data)

    visited: set[str] = set()

    def _branch(key: str, indent: int = 0, prefix: str = "") -> None:
        if key not in data:
            print(f"  {'  ' * indent}{prefix}{key}  (undefined)")
            return
        already = key in visited
        prec = data[key].get("precluded", [])
        prec_str = f"  ✗ {', '.join(prec)}" if prec else ""
        marker = " *" if already else ""
        print(f"  {'  ' * indent}{prefix}{key}{marker}{prec_str}")
        if not already:
            visited.add(key)
            for child in data[key].get("children", []):
                _branch(child, indent + 1, "└─ ")

    for root in roots:
        _branch(root)
        print()


def _display_show(key: str, data: dict) -> None:
    if key not in data:
        print(f"  '{key}' is not defined yet.")
        return
    v = data[key]
    parents = sorted(k for k, vv in data.items() if key in vv.get("children", []))
    print(f"\n  {key}")
    print(f"    parents  : {parents or '(none)'}")
    print(f"    children : {v.get('children', []) or '(none)'}")
    print(f"    precluded: {v.get('precluded', []) or '(none)'}")


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _normalise(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def _prompt_list(prompt: str) -> list[str] | None:
    """Return a normalised list, or None to signal 'stop session'."""
    raw = input(prompt).strip()
    if raw.lower() in ("done", "q", "quit"):
        return None
    if raw.lower() in ("", "none", "-"):
        return []
    return [_normalise(t) for t in raw.split(",") if t.strip()]


def _handle_command(raw: str, data: dict, queue: deque, queued: set) -> bool:
    """Handle meta-commands. Returns True if consumed."""
    parts = raw.strip().split(None, 1)
    cmd = parts[0].lower()
    if cmd == "list":
        _display_list(data)
        return True
    if cmd == "tree":
        _display_tree(data)
        return True
    if cmd == "show" and len(parts) == 2:
        _display_show(_normalise(parts[1]), data)
        return True
    if cmd == "edit" and len(parts) == 2:
        _edit_sphere(_normalise(parts[1]), data, queue, queued)
        save(data)
        return True
    if cmd == "expand" and len(parts) == 2:
        _expand_subtree(_normalise(parts[1]), data, queue, queued)
        return True
    return False


# ---------------------------------------------------------------------------
# Sphere operations
# ---------------------------------------------------------------------------

def _edit_sphere(key: str, data: dict, queue: deque, queued: set) -> None:
    """Append more children / precluded to an already-defined sphere."""
    if key not in data:
        print(f"  '{key}' is not defined yet — define it as a new sphere instead.")
        return
    _display_show(key, data)
    v = data[key]

    result = _prompt_list("  Add children   (comma-sep, blank = skip): ")
    if result is None:
        return
    for c in result:
        if c not in v["children"]:
            v["children"].append(c)
            if c not in data and c not in queued:
                queue.append(c)
                queued.add(c)
                print(f"  → queued '{c}'")

    result = _prompt_list("  Add precluded  (comma-sep, blank = skip): ")
    if result is None:
        return
    for p in result:
        if p not in v["precluded"]:
            v["precluded"].append(p)
            if p not in data and p not in queued:
                queue.append(p)
                queued.add(p)
                print(f"  → queued '{p}'")

    print(f"  Updated — children: {v['children']}, precluded: {v['precluded']}")


def _expand_subtree(root: str, data: dict, queue: deque, queued: set) -> bool:
    """
    BFS walk from `root` through all its descendants, offering to
    add more children / precluded at each node.
    Returns False when the user ends the session.
    """
    if root not in data:
        print(f"  '{root}' is not defined yet — define it first.")
        return True

    visited: set[str] = set()
    bfs: deque[str] = deque([root])

    while bfs:
        key = bfs.popleft()
        if key in visited or key not in data:
            continue
        visited.add(key)

        _display_show(key, data)
        raw = input("  Expand this sphere? [y / skip / done]: ").strip().lower()
        if raw in ("done", "q"):
            save(data)
            print("\nSession ended.")
            return False
        if raw == "y":
            _edit_sphere(key, data, queue, queued)
            save(data)

        # Queue children for BFS (both pre-existing and newly added)
        for child in data[key].get("children", []):
            if child not in visited:
                bfs.append(child)

    print(f"  Finished expanding '{root}' subtree ({len(visited)} spheres visited).")
    return True


def _define_sphere(key: str, data: dict, queue: deque, queued: set) -> bool:
    """
    Prompt for a new sphere's relationships.
    Returns False when the user ends the session.
    """
    print(f"─── '{key}' ───────────────────────────────────────────")

    result = _prompt_list("  Children   (comma-sep, blank = none): ")
    if result is None:
        save(data)
        print("\nSession ended.")
        return False
    children = result

    result = _prompt_list("  Precluded  (comma-sep, blank = none): ")
    if result is None:
        save(data)
        print("\nSession ended.")
        return False
    precluded = result

    data[key] = {"children": children, "precluded": precluded}
    save(data)

    for ref in children + precluded:
        if ref not in data and ref not in queued:
            queue.append(ref)
            queued.add(ref)
            print(f"  → queued '{ref}'")
    print()
    return True


def _drain_queue(queue: deque, queued: set, data: dict) -> bool:
    """Define all pending spheres. Returns False if session ended."""
    while queue:
        key = queue.popleft()
        if key not in data:
            if not _define_sphere(key, data, queue, queued):
                return False
    return True


# ---------------------------------------------------------------------------
# Core build loop
# ---------------------------------------------------------------------------

def build() -> None:
    data = load()
    queue: deque[str] = deque()
    queued: set[str] = set()

    if data:
        print(f"Resuming — {len(data)} spheres defined.")
        print("  'list' or 'tree' to explore  |  'show <n>' / 'edit <n>' / 'expand <n>'\n")
        for sphere_data in data.values():
            for ref in sphere_data.get("children", []) + sphere_data.get("precluded", []):
                if ref not in data and ref not in queued:
                    queue.append(ref)
                    queued.add(ref)
        if queue:
            print(f"Pending (referenced but undefined): {', '.join(queue)}\n")
    else:
        print("No sphere data found. Let's build from scratch.\n")
        while True:
            raw = input("Starting sphere name: ").strip()
            if not raw:
                continue
            if _handle_command(raw, data, queue, queued):
                continue
            seed = _normalise(raw)
            queue.append(seed)
            queued.add(seed)
            break

    print("Commands: 'done'/'q' stop  |  'skip' skip  |  'list' / 'tree'  |  'show <n>' / 'edit <n>'\n")

    if not _drain_queue(queue, queued, data):
        return

    # Post-queue interactive menu
    MENU = "  [a] add new  [e] edit existing  [x] expand subtree  [l] list  [t] tree  [q] quit\n> "
    while True:
        print(f"\nAll pending spheres defined. ({len(data)} total)")
        raw = input(MENU).strip()
        if not raw or raw.lower() in ("q", "quit", "done"):
            break

        if raw.lower() == "a":
            new_raw = input("  New sphere name: ").strip()
            if not new_raw:
                continue
            new_key = _normalise(new_raw)
            if new_key in data:
                print(f"  '{new_key}' already defined — use 'e' to edit it.")
                continue
            if not _define_sphere(new_key, data, queue, queued):
                return
            if not _drain_queue(queue, queued, data):
                return

        elif raw.lower() == "e":
            edit_raw = input("  Sphere to edit (or blank to cancel): ").strip()
            if not edit_raw:
                continue
            _edit_sphere(_normalise(edit_raw), data, queue, queued)
            save(data)
            if not _drain_queue(queue, queued, data):
                return

        elif raw.lower() == "x":
            exp_raw = input("  Expand from sphere (or blank to cancel): ").strip()
            if not exp_raw:
                continue
            if not _expand_subtree(_normalise(exp_raw), data, queue, queued):
                return
            if not _drain_queue(queue, queued, data):
                return

        elif _handle_command(raw, data, queue, queued):
            pass

        else:
            print(f"  Unknown: '{raw}'")

    print(f"\nDone. {len(data)} spheres saved to {JSON_PATH}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        build()
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted. Progress was saved after each entry.")
        sys.exit(0)

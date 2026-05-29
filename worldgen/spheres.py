"""
Sphere relationship data — loaded from json/spheres.json.

Run sphere_generator.py to build or extend the sphere graph.

Each sphere in the JSON has:
  children  : spheres that flow from / are enabled by this sphere
  precluded : spheres that are blocked / opposed by this sphere
"""
from __future__ import annotations
import json
import os
import random

_JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "json", "spheres.json")


def _load() -> dict:
    if os.path.exists(_JSON_PATH):
        with open(_JSON_PATH, encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    return {}


SPHERES: dict[str, dict] = _load()


def reload() -> None:
    global SPHERES
    SPHERES = _load()


def children_of(key: str) -> list[str]:
    return list(SPHERES.get(key, {}).get("children", []))


def precluded_by(key: str) -> list[str]:
    return list(SPHERES.get(key, {}).get("precluded", []))

def hostility(key: str) -> float:
    return SPHERES.get(key, {}).get("hostility", 0.0)

def description(key: str) -> str:
    return SPHERES.get(key, {}).get("description", "")


# ---------------------------------------------------------------------------
# World generation
# ---------------------------------------------------------------------------

def generate_world_spheres(
    target: int = 20,
    seeds: list[str] | None = None,
    child_chance: float = 0.75,
    link_chance: float = 0.5,
    cross_link_chance: float = 0.1,
) -> dict[str, list[str]]:
    """
    Grow a world from a few seed spheres.

    For each sphere in the world:
      - Roll child_chance  → add one of its children to the world
      - Roll link_chance   → if child was added, link parent→child
      - Roll cross_link_chance for every other world sphere that isn't
        precluded → add a cross-link

    Returns { sphere: [linked_spheres] }
    Preclusions are never linked and block each other from coexisting.
    """
    if not SPHERES:
        return {}

    pool = list(SPHERES.keys())

    # Pick seeds
    if seeds:
        active = [s for s in seeds if s in SPHERES]
    else:
        active = random.sample(pool, min(3, len(pool)))

    world: set[str] = set(active)
    excluded: set[str] = set()

    def _exclude(key: str) -> None:
        for p in SPHERES[key].get("precluded", []):
            excluded.add(p)
        for k, v in SPHERES.items():
            if key in v.get("precluded", []):
                excluded.add(k)

    for s in active:
        _exclude(s)

    # Grow world up to target
    queue = list(active)
    while len(world) < target and queue:
        current = queue.pop(0)
        if random.random() < child_chance:
            candidates = [
                c for c in SPHERES[current].get("children", [])
                if c in SPHERES and c not in world and c not in excluded
            ]
            if candidates:
                child = random.choice(candidates)
                world.add(child)
                _exclude(child)
                queue.append(child)

        # Occasionally pull a wildcard if queue is thin
        if len(queue) < 2:
            wildcards = [k for k in pool if k not in world and k not in excluded]
            if wildcards:
                pick = random.choice(wildcards)
                world.add(pick)
                _exclude(pick)
                queue.append(pick)

    # Build a bidirectional distance map within the world via BFS
    # so closer spheres in the parent/child chain get higher link weight.
    def _bfs_distances(start: str) -> dict[str, int]:
        dist: dict[str, int] = {start: 0}
        queue_bfs = [start]
        while queue_bfs:
            node = queue_bfs.pop(0)
            neighbours = (
                [c for c in SPHERES[node].get("children", []) if c in world]
                + [k for k in world if node in SPHERES[k].get("children", [])]
            )
            for n in neighbours:
                if n not in dist:
                    dist[n] = dist[node] + 1
                    queue_bfs.append(n)
        return dist

    distances: dict[str, dict[str, int]] = {s: _bfs_distances(s) for s in world}

    # Build links
    links: dict[str, list[str]] = {s: [] for s in world}

    for sphere in world:
        # Parent→child links
        for child in SPHERES[sphere].get("children", []):
            if child in world and random.random() < link_chance:
                if child not in links[sphere]:
                    links[sphere].append(child)

        # Cross-links — sorted by graph distance so closer spheres are tried first.
        # Each candidate rolls cross_link_chance / distance; cap at 4 total links.
        others = [
            s for s in world
            if s != sphere
            and s not in SPHERES[sphere].get("precluded", [])
            and sphere not in SPHERES[s].get("precluded", [])
            and s not in links[sphere]
            and s not in SPHERES[sphere].get("children", [])
        ]
        others.sort(key=lambda o: distances[sphere].get(o, len(world)))
        for other in others:
            if len(links[sphere]) >= 4:
                break
            d = distances[sphere].get(other, len(world))
            if random.random() < cross_link_chance / max(d, 1):
                links[sphere].append(other)

    return links


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
"""
if __name__ == "__main__":
    if not SPHERES:
        print("No sphere data found. Run sphere_generator.py first.")
    else:
        world = generate_world_spheres(target=20)
        print(f"World ({len(world)} spheres):\n")
        for sphere, linked in world.items():
            linked_str = f"  → {linked}" if linked else ""
            print(f"  {sphere}{linked_str}")
"""



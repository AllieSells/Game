from spheres import SPHERES, hostility, generate_world_spheres
import random




NUM_DEITIES = 13

world_spheres = generate_world_spheres(target=NUM_DEITIES * 5)

class Diety:
    def __init__(self, name: str, spheres: list[str]):
        self.name = name
        self.spheres = spheres
        self.hostility = round(sum(hostility(s) for s in spheres), 1)


def generate_sphere_orientation(world):
    world_spheres = list(world.keys())
    available = [s for s in world_spheres if s not in TAKEN_SPHERES]
    if not available:
        return []

    sphere_list: list[str] = []
    max_spheres = random.randint(1, 5)

    # Pick a starting sphere
    start = random.choice(available)
    sphere_list.append(start)
    TAKEN_SPHERES.add(start)
    current = start

    for _ in range(max_spheres - 1):
        # 1. Try world links from current sphere
        candidates = [s for s in world.get(current, [])
                      if s in world and s not in TAKEN_SPHERES]
        # 2. Fall back to children in raw sphere graph
        if not candidates:
            candidates = [s for s in SPHERES.get(current, {}).get("children", [])
                          if s in world and s not in TAKEN_SPHERES]
        # 3. Fall back to any untaken world sphere
        if not candidates:
            candidates = [s for s in world_spheres if s not in TAKEN_SPHERES]
        if not candidates:
            break
        current = random.choice(candidates)
        sphere_list.append(current)
        TAKEN_SPHERES.add(current)

    return sphere_list



def gen_deities(num_deities: int = NUM_DEITIES) -> None:
    for x in range(num_deities):
        deity_name = f"Deity {x+1}"
        spheres = generate_sphere_orientation(world_spheres)
        if not spheres:
            print(f"Warning: Could not assign spheres to {deity_name} due to exhaustion.")
            continue
        diety = Diety(deity_name, spheres)
        dieties[deity_name] = diety

    # Check for at least one hostile and one friendly diety
    if not any(d.hostility > 0 for d in dieties.values()):
        print("Warning: No hostile deities generated. Regenerating with more aggressive parameters.")
        deity_name = f"Deity {NUM_DEITIES + 1}"
        spheres = generate_sphere_orientation(world_spheres)
        if spheres:
            # Check if any sphere has positive hostility
            if any(hostility(s) > 0.25 for s in spheres):
                diety = Diety(deity_name, spheres)
                dieties[deity_name] = diety


gen_attempts = 0

# PANTHEON ASSEMBLY

while True:
    gen_attempts += 1
    TAKEN_SPHERES:set[str] = set()
    dieties = {}
    gen_deities(13)
    if (round(sum(d.hostility for d in dieties.values()) / len(dieties), 2)) == 0:
        break

print(f"Tried {gen_attempts} times to generate a balanced pantheon.")
print("Deities and their spheres:")
for deity, spheres in dieties.items():
    print(f"{deity}: {spheres.spheres} (Hostility: {spheres.hostility})")

print(f"AVERAGE HOSTILITY: {round(sum(d.hostility for d in dieties.values()) / len(dieties), 2)}")


# == EVENT GENERATION ==
EVENT_TYPES = [
    "outpost_founded",
    "war_started",
    "war_ended",
    "artifact_created", 
]



class Event:
    def __init__(self, name: str, description: str, involved_spheres: list[str]):
        self.name = name
        self.type = random.choice(EVENT_TYPES)
        self.description = description
        self.involved_spheres = involved_spheres

for x in range(10):
    event_name = f"Event {x+1}"
    description = f"This is a description of {event_name}."
    involved_spheres = random.sample(list(world_spheres.keys()), random.randint(1, 3))
    event = Event(event_name, description, involved_spheres)
    print(f"{event.name} (Type: {event.type}) - Involved Spheres: {event.involved_spheres}")
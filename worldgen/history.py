from ast import In

from numpy import ma
from numpy.char import capitalize

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
    max_spheres = random.randint(1, min(3, len(available)))

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
    attempts = 0
    for x in range(num_deities):
        attempts += 1
        if attempts > num_deities * 10:
            print("Warning: Too many attempts to generate deities. Consider increasing the number of available spheres.")
            break
        deity_name = f"Deity {x+1}"
        spheres = generate_sphere_orientation(world_spheres)
        try:
            deity_name = f"the God of {capitalize(spheres[0])}" if len(spheres) == 1 else f"the God of {capitalize(spheres[0])} and {capitalize(spheres[1])}"
        except IndexError:
            pass
        if not spheres:
            print(f"Warning: Could not assign spheres to {deity_name} due to exhaustion.")
            continue
        diety = Diety(deity_name, spheres)
        deities[deity_name] = diety

    # Check for at least one hostile and one friendly diety
    if not any(d.hostility > .25 for d in deities.values()):
        print("Warning: No hostile deities generated. Regenerating with more aggressive parameters.")
        deity_name = f"Deity {NUM_DEITIES + 1}"
        spheres = generate_sphere_orientation(world_spheres)
        if spheres:
            # Check if any sphere has positive hostility
            if any(hostility(s) > 0.25 for s in spheres):
                diety = Diety(deity_name, spheres)
                deities[deity_name] = diety


gen_attempts = 0

# PANTHEON ASSEMBLY

while True:
    gen_attempts += 1
    TAKEN_SPHERES:set[str] = set()
    deities = {}
    gen_deities(13)
    if (round(sum(d.hostility for d in deities.values()) / len(deities), 2)) == 0:
        break

print(f"Tried {gen_attempts} times to generate a balanced pantheon.")
print("Deities and their spheres:")
for deity, spheres in deities.items():
    print(f"{deity}: {spheres.spheres} (Hostility: {spheres.hostility})")

print(f"AVERAGE HOSTILITY: {round(sum(d.hostility for d in deities.values()) / len(deities), 2)}")


# == SPECIES GENERATION ==








class Species:
    def __init__(self, name: str, hostility_min: float, hostility_max: float,
                 min_year_created: int = None, max_age: int = 100,
                 offspring_count: int = 2, reproduction_rate: float = 0.05,
                 carrying_capacity: int = None, death_rate: float = None,
                 maturity_age: int = None, founding_population: int = 50, can_have_culture: bool = False):
        self.name = name
        self.can_have_culture = can_have_culture
        self.hostility_min = hostility_min
        self.hostility_max = hostility_max
        self.creator = None
        self.min_year_created = min_year_created
        self.year_created = None
        self.offspring_count = offspring_count
        # reproduction_rate = fraction of adults that breed per year
        self.reproduction_rate = reproduction_rate
        self.max_age = max_age
        self.carrying_capacity = carrying_capacity
        # Default death rate: 1/max_age gives ~natural lifespan
        self.death_rate = death_rate if death_rate is not None else 1.0 / max_age
        # Default maturity at ~20% of lifespan
        self.maturity_age = maturity_age if maturity_age is not None else max(1, max_age // 5)
        self.founding_population = founding_population




# Species gen

SPECIES = {
    # reproduction_rate = fraction of adults that breed per year; offspring_count = young per breeding adult
    # Spiders: short-lived r-strategists, many young, low survival                   maturity  founding
    "giant spider": Species("giant spider", can_have_culture=False, hostility_min=0.1,   hostility_max=1, min_year_created=1,  offspring_count=10, max_age=5,   reproduction_rate=0.50, carrying_capacity=5000,  maturity_age=1,  founding_population=20),
    "kobold":       Species("kobold",        can_have_culture=True, hostility_min=0.25,  hostility_max=1, min_year_created=5,  offspring_count=4,  max_age=50,  reproduction_rate=0.15, carrying_capacity=5000,  maturity_age=8,  founding_population=40),
    "goblin":       Species("goblin",        can_have_culture=True, hostility_min=0.5,   hostility_max=1, min_year_created=1,  offspring_count=3,  max_age=100, reproduction_rate=0.10, carrying_capacity=5000,  maturity_age=12, founding_population=50),
    "naga":         Species("naga",          can_have_culture=False, hostility_min=0.25,  hostility_max=1, min_year_created=1,  offspring_count=2,  max_age=200, reproduction_rate=0.05, carrying_capacity=5000,  maturity_age=30, founding_population=30),
    "troll":        Species("troll",         can_have_culture=False, hostility_min=0.5,   hostility_max=1, min_year_created=1,  offspring_count=2,  max_age=150, reproduction_rate=0.06, carrying_capacity=5000,   maturity_age=20, founding_population=20),
    "human":        Species("human",         can_have_culture=True, hostility_min=-1.0, hostility_max=0.0,  min_year_created=50, offspring_count=2,  max_age=80,  reproduction_rate=0.08, carrying_capacity=5000, maturity_age=15, founding_population=100),
}

for species in SPECIES.values():
    prospective_deities = [
        d for d in deities.values()
        if species.hostility_min <= d.hostility <= species.hostility_max
    ]
    if prospective_deities:
        species.creator = random.choice(prospective_deities).name

print("\nSpecies and their creators:")
for species in SPECIES.values():
    creator_hostility = deities[species.creator].hostility if species.creator else "N/A"
    print(f"{species.name}: Created by {species.creator} | Creator hostility: {creator_hostility}")

print("\nSimulating world history and species emergence...")

# Civ gen

class Event:
    def __init__(self, name: str, year: int, description: str):
        self.name = name
        self.year = year
        self.description = description

class Relationship:
    value: float
    war: bool
    trade: bool 

entities_test = []





class Site():
    def __init__(self, name: str, location: int, founding_year: int):
        self.name = name
        self.location = location
        
        self.population = 0
        self.wealth = 0
        self.status = "active"
        self.events: list[Event] = []
    


class Civilization:
    def __init__(self, name: str, populaiton: int, founding_year: int, relationships: dict[str, float], sites: list[str]):
        self.name = name
        self.population = populaiton
        self.founding_year = founding_year

        self.relationships = relationships  # { other_civ_name: relationship_score }
        self.sites: list[Site] = []
        self.events: list[Event] = []

    def establish_self(self, year: int):
        self.events.append(Event(name="Established", year=year, description=f"In year {year}, {self.name} was founded."))

    def establish_site(self, year: int):
        site_name = f"{self.name} Camp"
        location = random.randint(0, 100)  # Placeholder for actual location logic
        new_site = Site(site_name, location, year)
        self.sites.append(new_site)
        self.events.append(Event(name="Site Established", year=year, description=f"In year {year}, {self.name} established a new site: {site_name}."))





world_civilizations = {}
world_sites = {}

# Seed world with civs

for species in SPECIES.values():
    if species.can_have_culture and species.creator:
        for x in range(random.randint(1, 3)):
            year_of_establishment = int(species.min_year_created * random.uniform(0.5, 1.5))
            civ_name = f"{species.name.capitalize()} Civ {x+1}"
            world_civilizations[civ_name] = Civilization(civ_name, int(species.founding_population*random.uniform(0.5, 1.5)), year_of_establishment, {}, [])
            world_civilizations[civ_name].establish_self(year_of_establishment)
            world_civilizations[civ_name].establish_site(year_of_establishment)


def tick_world(year: int, total_years: int = 1000) -> None:
    for x in range(total_years):
        year += 1



year = 0
tick_world(year)


for civ in world_civilizations.values():
    print(f"\nCivilization: {civ.name} | Population: {civ.population} | Founded: {civ.founding_year}")
    for event in civ.events:
        print(f"  - {event.year}: {event.name} - {event.description}")
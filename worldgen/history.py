import math
import random
from numpy.char import capitalize
try:
    from worldgen.spheres import SPHERES, hostility, generate_world_spheres
except ImportError:
    from spheres import SPHERES, hostility, generate_world_spheres

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NUM_DEITIES = 13

MIGRATION_POP_THRESHOLD = 0.45   # fraction of carrying capacity that triggers pressure
MIGRATION_WEALTH_THRESHOLD = 200
MIGRATION_CHANCE = 0.002         # 0.2% chance per year when thresholds are met
MIGRATION_SITE_COOLDOWN = 40     # years a site must wait before sending migrants
MIGRATION_CIV_COOLDOWN = 25      # years a civ must wait between any two migrations
MAX_SITES_PER_CIV = 10

# ---------------------------------------------------------------------------
# Pantheon
# ---------------------------------------------------------------------------

class Deity:
    def __init__(self, name: str, spheres: list[str]):
        self.name = name
        self.spheres = spheres
        self.hostility = round(sum(hostility(s) for s in spheres), 1)


world_spheres = generate_world_spheres(target=NUM_DEITIES * 5)
TAKEN_SPHERES: set[str] = set()
deities: dict[str, Deity] = {}


def generate_sphere_orientation(world: dict) -> list[str]:
    available = [s for s in world if s not in TAKEN_SPHERES]
    if not available:
        return []

    sphere_list: list[str] = []
    max_spheres = random.randint(1, min(3, len(available)))

    start = random.choice(available)
    sphere_list.append(start)
    TAKEN_SPHERES.add(start)
    current = start

    for _ in range(max_spheres - 1):
        candidates = [s for s in world.get(current, []) if s in world and s not in TAKEN_SPHERES]
        if not candidates:
            candidates = [s for s in SPHERES.get(current, {}).get("children", []) if s in world and s not in TAKEN_SPHERES]
        if not candidates:
            candidates = [s for s in world if s not in TAKEN_SPHERES]
        if not candidates:
            break
        current = random.choice(candidates)
        sphere_list.append(current)
        TAKEN_SPHERES.add(current)

    return sphere_list


def gen_deities(num: int = NUM_DEITIES) -> None:
    for i in range(num):
        spheres = generate_sphere_orientation(world_spheres)
        if not spheres:
            continue
        if len(spheres) == 1:
            name = f"the God of {capitalize(spheres[0])}"
        else:
            name = f"the God of {capitalize(spheres[0])} and {capitalize(spheres[1])}"
        deities[name] = Deity(name, spheres)

    if not any(d.hostility > 0.25 for d in deities.values()):
        print("Warning: No hostile deities generated.")
        extra = generate_sphere_orientation(world_spheres)
        if extra and any(hostility(s) > 0.25 for s in extra):
            deities["Deity (extra hostile)"] = Deity("Deity (extra hostile)", extra)


# Keep regenerating until the average hostility is non-zero (balanced pantheon)
gen_attempts = 0
while True:
    gen_attempts += 1
    TAKEN_SPHERES.clear()
    deities.clear()
    gen_deities(NUM_DEITIES)
    avg = sum(d.hostility for d in deities.values()) / len(deities)
    if round(avg, 2) != 0:
        break

print(f"Tried {gen_attempts} times to generate a balanced pantheon.")
for name, deity in deities.items():
    print(f"{name}: {deity.spheres} (Hostility: {deity.hostility})")
print(f"AVERAGE HOSTILITY: {round(sum(d.hostility for d in deities.values()) / len(deities), 2)}")

# ---------------------------------------------------------------------------
# Species
# ---------------------------------------------------------------------------

class Species:
    def __init__(self, name: str, hostility_min: float, hostility_max: float,
                 min_year_created: int = 1, max_age: int = 100,
                 offspring_count: int = 2, reproduction_rate: float = 0.05,
                 carrying_capacity: int = 5000, death_rate: float = None,
                 maturity_age: int = None, founding_population: int = 50,
                 can_have_culture: bool = False):
        self.name = name
        self.can_have_culture = can_have_culture
        self.hostility_min = hostility_min
        self.hostility_max = hostility_max
        self.creator: str | None = None
        self.min_year_created = min_year_created
        self.offspring_count = offspring_count
        self.reproduction_rate = reproduction_rate
        self.max_age = max_age
        self.carrying_capacity = carrying_capacity
        self.death_rate = death_rate if death_rate is not None else 1.0 / max_age
        self.maturity_age = maturity_age if maturity_age is not None else max(1, max_age // 5)
        self.founding_population = founding_population


SPECIES: dict[str, Species] = {
    "giant spider": Species("giant spider", can_have_culture=False, hostility_min=0.1,  hostility_max=1.0, min_year_created=1,  offspring_count=10, max_age=5,   reproduction_rate=0.50, carrying_capacity=5000, maturity_age=1,  founding_population=20),
    "kobold":       Species("kobold",       can_have_culture=True,  hostility_min=0.25, hostility_max=1.0, min_year_created=5,  offspring_count=4,  max_age=50,  reproduction_rate=0.15, carrying_capacity=5000, maturity_age=8,  founding_population=40),
    "goblin":       Species("goblin",       can_have_culture=True,  hostility_min=0.5,  hostility_max=1.0, min_year_created=1,  offspring_count=3,  max_age=100, reproduction_rate=0.10, carrying_capacity=5000, maturity_age=12, founding_population=50),
    "naga":         Species("naga",         can_have_culture=False, hostility_min=0.25, hostility_max=1.0, min_year_created=1,  offspring_count=2,  max_age=200, reproduction_rate=0.05, carrying_capacity=5000, maturity_age=30, founding_population=30),
    "troll":        Species("troll",        can_have_culture=False, hostility_min=0.5,  hostility_max=1.0, min_year_created=1,  offspring_count=2,  max_age=150, reproduction_rate=0.06, carrying_capacity=5000, maturity_age=20, founding_population=20),
    "human":        Species("human",        can_have_culture=True,  hostility_min=-1.0, hostility_max=0.0, min_year_created=50, offspring_count=2,  max_age=80,  reproduction_rate=0.08, carrying_capacity=5000, maturity_age=15, founding_population=100),
}

for species in SPECIES.values():
    candidates = [d for d in deities.values() if species.hostility_min <= d.hostility <= species.hostility_max]
    if candidates:
        species.creator = random.choice(candidates).name

print("\nSpecies and their creators:")
for species in SPECIES.values():
    creator_hostility = deities[species.creator].hostility if species.creator else "N/A"
    print(f"  {species.name}: {species.creator} (hostility {creator_hostility})")

# ---------------------------------------------------------------------------
# World objects
# ---------------------------------------------------------------------------

WORLD_W = 120
WORLD_H = 40

class Event:
    def __init__(self, name: str, year: int, description: str):
        self.name = name
        self.year = year
        self.description = description


class Site:
    def __init__(self, name: str, x: int, y: int, founding_year: int, location_quality: float = None):
        self.name = name
        self.x = x
        self.y = y
        # Triangular distribution: most sites average quality, few prime or barren
        self.location_quality = location_quality if location_quality is not None else round(random.triangular(0.05, 1.0, 0.45), 2)
        self.population = 0
        self.wealth = 0
        self.status = "active"
        self.is_capital = False
        self.last_migration_year = -999
        self.events: list[Event] = []

    @property
    def site_type(self) -> str:
        if self.is_capital:
            return "Capital"
        elif self.wealth >= 3_500:
            return "City"
        elif self.wealth >= 800:
            return "Village"
        elif self.wealth >= 150:
            return "Outpost"
        else:
            return "Camp"

    @property
    def glyph(self) -> str:
        return {"Capital": "@", "City": "#", "Village": "o", "Outpost": "*", "Camp": "."}.get(self.site_type, "?")


class Civilization:
    def __init__(self, name: str, population: int, founding_year: int, species_name: str):
        self.name = name
        self.population = population
        self.founding_year = founding_year
        self.species_name = species_name
        self.site_count = 1
        self.sites: list[Site] = []
        self.events: list[Event] = []
        self.last_migration_year = -999
        self.relationships: dict[str, float] = {}  # civ_name -> -1.0 (war) .. 1.0 (ally)

    def establish_self(self, year: int):
        self.events.append(Event("Established", year, f"In year {year}, {self.name} was founded."))

    def establish_site(self, year: int):
        site_name = f"{self.name} Camp"
        x = random.randint(2, WORLD_W - 3)
        y = random.randint(2, WORLD_H - 3)
        site = Site(site_name, x, y, year, location_quality=1.0)
        site.population = self.population
        self.sites.append(site)
        self.events.append(Event("Site Established", year, f"In year {year}, {self.name} established {site_name}."))

# ---------------------------------------------------------------------------
# World seeding
# ---------------------------------------------------------------------------

world_civilizations: dict[str, Civilization] = {}

print("\nSimulating world history...")

for species in SPECIES.values():
    if not (species.can_have_culture and species.creator):
        continue
    for i in range(random.randint(1, 3)):
        year = int(species.min_year_created * random.uniform(0.5, 1.5))
        civ_name = f"{species.name.capitalize()} Civ {i + 1}"
        pop = int(species.founding_population * random.uniform(0.5, 1.5))
        civ = Civilization(civ_name, pop, year, species.name)
        civ.establish_self(year)
        civ.establish_site(year)
        world_civilizations[civ_name] = civ

# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def tick_world(total_years: int = 1000) -> None:
    for year in range(1, total_years + 1):
        for civ in world_civilizations.values():
            species = SPECIES.get(civ.species_name)
            if species is None:
                continue

            new_sites: list[Site] = []
            civ_migrated = False

            for site in civ.sites:
                net_growth = 0
                if site.population > 0:
                    effective_cap = max(1, int(species.carrying_capacity * site.location_quality))
                    growth_pressure = 1.0 - (site.population / effective_cap)
                    adults = max(0, site.population - species.maturity_age * site.population // species.max_age)
                    births = int(adults * species.reproduction_rate * species.offspring_count * growth_pressure)
                    deaths = int(site.population * species.death_rate)
                    net_growth = births - deaths
                    site.population = max(0, min(site.population + net_growth, effective_cap))

                # Wealth: base from stable population + bonus from active growth
                site.wealth = max(0, site.wealth + site.population // 500 + max(0, net_growth) // 2 + random.randint(0, 2))

                # Migration
                pop_threshold = int(species.carrying_capacity * MIGRATION_POP_THRESHOLD)
                if (not civ_migrated
                        and len(civ.sites) + len(new_sites) < MAX_SITES_PER_CIV
                        and site.population > pop_threshold
                        and site.wealth > MIGRATION_WEALTH_THRESHOLD
                        and (year - site.last_migration_year) >= MIGRATION_SITE_COOLDOWN
                        and (year - civ.last_migration_year) >= MIGRATION_CIV_COOLDOWN
                        and random.random() < MIGRATION_CHANCE):

                    migrant_pop = int(site.population * random.uniform(0.03, 0.08))
                    site.population -= migrant_pop
                    site.wealth -= int(site.wealth * random.uniform(0.10, 0.20))
                    site.last_migration_year = year
                    civ.last_migration_year = year
                    civ_migrated = True

                    civ.site_count += 1
                    new_name = f"{civ.name} Settlement {civ.site_count}"
                    _angle = random.uniform(0, 2 * math.pi)
                    _radius = random.randint(3, 8)
                    x = max(2, min(WORLD_W - 3, int(site.x + _radius * math.cos(_angle))))
                    y = max(2, min(WORLD_H - 3, int(site.y + _radius * math.sin(_angle) / 3)))
                    new_site = Site(new_name, x, y, year)
                    new_site.population = migrant_pop
                    new_site.wealth = random.randint(10, 50)
                    new_sites.append(new_site)
                    civ.events.append(Event(
                        "Migration", year,
                        f"In year {year}, {migrant_pop} settlers departed {site.name} to found {new_name}."
                    ))

            civ.sites.extend(new_sites)
            civ.population = sum(s.population for s in civ.sites)

            for s in civ.sites:
                s.is_capital = False
            if civ.sites:
                max(civ.sites, key=lambda s: s.wealth).is_capital = True


tick_world(1000)


for civ in world_civilizations.values():
    print(f"\nCivilization: {civ.name} | Population: {civ.population} | Founded: {civ.founding_year}")
    for event in civ.events:
        print(f"  - {event.year}: {event.name} - {event.description}")
    for site in civ.sites:
        print(f"  [{site.site_type}] {site.name} | Pop: {site.population} | Wealth: {site.wealth} | Quality: {site.location_quality}")

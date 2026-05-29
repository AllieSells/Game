import numpy as np

TARGET_POPULATION = 100000
FEMALE_RATIO = 0.5

class Species:
    def __init__(self):
        self.lifespan_min = 50
        self.lifespan_max = 100
        self.fert_start = 0.2
        self.fert_end = 0.6
        self.lifetime_offspring = 1.6  # reproductive rate relative to replacement at low density (>1 = growth)

        # Precompute the per-tick birth rate a fertile female needs to exactly replace
        # the population at TARGET_POPULATION, given the species death rate.
        avg_lifespan = (self.lifespan_min + self.lifespan_max) / 2
        natural_death_rate = 1.0 / avg_lifespan
        fertile_fraction = self.fert_end - self.fert_start
        self.replacement_birth_rate = natural_death_rate / (FEMALE_RATIO * fertile_fraction)


species = Species()

rng = np.random.default_rng()

# Population stored as flat arrays — no per-entity objects.
n = TARGET_POPULATION
ages      = np.zeros(n, dtype=np.float32)
max_ages  = rng.integers(species.lifespan_min, species.lifespan_max + 1, size=n).astype(np.float32)
is_female = rng.random(n) < FEMALE_RATIO
# Precompute per-entity fertile window once at birth
fert_lo   = (species.fert_start * max_ages).astype(np.float32)
fert_hi   = (species.fert_end   * max_ages).astype(np.float32)

lo = species.lifetime_offspring
replacement_br = species.replacement_birth_rate

for year in range(1000):
    population = len(ages)

    # --- Death (vectorised) ---
    age_ratio    = ages / max_ages
    death_chance = 0.001 + age_ratio ** 8
    survived     = rng.random(population) >= death_chance

    ages      = ages[survived]
    max_ages  = max_ages[survived]
    is_female = is_female[survived]
    fert_lo   = fert_lo[survived]
    fert_hi   = fert_hi[survived]

    # --- Age survivors ---
    ages += 1

    # --- Births (vectorised, females only) ---
    pressure    = population / TARGET_POPULATION
    suppression = max(0.0, (1.0 + (lo - 1.0) * (1.0 - pressure)) / lo)
    birth_rate  = replacement_br * lo * suppression

    fertile      = is_female & (ages >= fert_lo) & (ages <= fert_hi)
    fertile_idx  = np.where(fertile)[0]
    if fertile_idx.size:
        gave_birth  = rng.random(fertile_idx.size) < birth_rate
        num_births  = int(gave_birth.sum())
        if num_births:
            new_max_ages = rng.integers(
                species.lifespan_min, species.lifespan_max + 1, size=num_births
            ).astype(np.float32)
            new_is_female = rng.random(num_births) < FEMALE_RATIO
            ages      = np.concatenate([ages,      np.zeros(num_births, dtype=np.float32)])
            max_ages  = np.concatenate([max_ages,  new_max_ages])
            is_female = np.concatenate([is_female, new_is_female])
            fert_lo   = np.concatenate([fert_lo,   (species.fert_start * new_max_ages).astype(np.float32)])
            fert_hi   = np.concatenate([fert_hi,   (species.fert_end   * new_max_ages).astype(np.float32)])

    males   = int((~is_female).sum())
    females = int(is_female.sum())
    if year % 10 == 0 or year < 50:
        print(f"Year {year:4d}: population={len(ages):6d}  males={males:6d}  females={females:6d}")


import random
from tcod.map import compute_fov
import tcod

class LightningAnimation:
    def __init__(self, path):
        self.path = path
        self.frames = 5  # duration in frames

    def tick(self, console, game_map):
        # Use shadowcasting FOV from the source of the lightning (path[0]) so
        # the bolt doesn't render through walls. Fall back to the game's
        # visible map if FOV computation fails for any reason.
        if not self.path:
            self.frames -= 1
            return

        origin = (int(self.path[0][0]), int(self.path[0][1]))
        try:
            # radius at least as long as the path so distant tiles are included
            radius = max(len(self.path), 10)
            fov_map = compute_fov(game_map.tiles["transparent"], origin, radius=radius, algorithm=tcod.FOV_SHADOW)
        except Exception:
            fov_map = game_map.visible

        for x, y in self.path:
            x = int(x)
            y = int(y)
            if not game_map.in_bounds(x, y):
                continue

            # Only draw if the tile is reachable from the origin using
            # shadowcasting (prevents drawing behind walls) AND the
            # player can currently see the tile. This avoids showing
            # animations through walls to the player.
            if fov_map[x, y] and game_map.visible[x, y]:

                x_draw, y_draw = x, y
                if random.random() < 0.05:
                    x_draw += 1
                if random.random() < 0.05:
                    y_draw += 1

                # Don't draw the animation glyph on a non-transparent tile
                # (e.g. a wall) — only draw on transparent tiles so the wall
                # glyph remains visible instead of being overwritten.
                if (
                    game_map.in_bounds(x_draw, y_draw)
                    and fov_map[x_draw, y_draw]
                    and game_map.visible[x_draw, y_draw]
                    and game_map.tiles["transparent"][x_draw, y_draw]
                ):
                    r = random.randint(200, 255)
                    g = random.randint(0, 255)
                    console.print(x_draw, y_draw, "*", fg=(r, g, 0))  # yellow-orange flicker

        self.frames -= 1


class FireballAnimation:
    def __init__(self, path):
        self.path = path
        self.frames = 6
        self.base_radius = 1  # starting radius
        self.max_radius = 4   # maximum bloom radius

    def tick(self, console, game_map):

        if not self.path:
            self.frames -= 1
            return

        center_x = int(self.path[0][0])
        center_y = int(self.path[0][1])

        progress = 1.0 - (self.frames / float(max(1, self.frames + 1)))

        life_index = max(0, (self.frames - 1))

        total_frames = 6
        current_radius = int(self.base_radius + (self.max_radius - self.base_radius) * (1 - (self.frames / total_frames)))
        current_radius = max(self.base_radius, min(self.max_radius, current_radius))

        try:
            fov_map = compute_fov(
                game_map.tiles["transparent"], (center_x, center_y), radius=current_radius, algorithm=tcod.FOV_SHADOW
            )
        except Exception:
            fov_map = game_map.visible

        # Color fades as the explosion blooms: compute intensity 1.0 -> 0.2
        intensity = 1.0 - (current_radius - self.base_radius) / float(max(1, self.max_radius - self.base_radius))
        intensity = max(0.2, intensity)

        for dx in range(-current_radius, current_radius + 1):
            for dy in range(-current_radius, current_radius + 1):
                if dx * dx + dy * dy <= current_radius * current_radius:
                    x = center_x + dx
                    y = center_y + dy
                    if not game_map.in_bounds(x, y):
                        continue
                    if (
                        fov_map[x, y]
                        and game_map.visible[x, y]
                        and game_map.tiles["transparent"][x, y]
                    ):
                        # color scales with intensity and a bit of randomness
                        r = int(255 * intensity) - random.randint(0, 30)
                        g = int(100 * intensity) - random.randint(0, 50)
                        r = max(100, min(255, r))
                        g = max(0, min(150, g))
                        console.print(x, y, "*", fg=(r, g, 0))

        self.frames -= 1


class FireFlicker:
    def __init__(self, position):
        self.position = position
        self.frames = 10  # duration in frames
        # Render priority: 0 = under entities/items, 1 = between items and actors, 2 = above actors
        # Set to 1 so campfire flicker renders above items but below actors.
        self.render_priority = 1

    def tick(self, console, game_map):
        x, y = self.position
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            r = random.randint(200, 255)
            g = random.randint(0, 150)
            console.print(x, y, "x", fg=(r, g, 0))  # yellow-orange flicker

        self.frames -= 1

class BonefireFlicker:
    def __init__(self, position):
        self.position = position
        self.frames = 10  # duration in frames
        # Render priority: 0 = under entities/items, 1 = between items and actors, 2 = above actors
        # Set to 1 so campfire flicker renders above items but below actors.
        self.render_priority = 1

    def tick(self, console, game_map):
        x, y = self.position
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            r = random.randint(200, 255)
            g = random.randint(0, 150)
            console.print(x, y, "X", fg=(r, g, 0))  # yellow-orange flicker
class FireSmoke:
    def __init__(self, position):
        self.position = position
        self.frames = 15  # duration in frames
        # Smoke should render between items and actors so it appears to rise above the campfire
        self.render_priority = 1

    def tick(self, console, game_map):
        x0, y0 = self.position
        # Drift upward slowly as smoke rises
        y = y0 - (15 - self.frames) // 3
        x = x0 + random.choice([-1, 0, 1])  # slight horizontal jitter

        if not game_map.in_bounds(int(x), int(y)):
            self.frames -= 1
            return

        # Use shadowcasting FOV from the smoke origin so smoke doesn't draw through walls
        try:
            origin = (int(x0), int(y0))
            radius = max(3, min(5, (15 - self.frames) + 2))
            fov_map = compute_fov(game_map.tiles["transparent"], origin, radius=radius, algorithm=tcod.FOV_SHADOW)
        except Exception:
            fov_map = game_map.visible

        xi, yi = int(x), int(y)
        if (
            game_map.in_bounds(xi, yi)
            and fov_map[xi, yi]
            and game_map.visible[xi, yi]
            and game_map.tiles["transparent"][xi, yi]
        ):
            gray_value = random.randint(100, 200)
            console.print(xi, yi, "+", fg=(gray_value, gray_value, gray_value))  # gray smoke

        self.frames -= 1

class GivingQuestAnimation():
    def __init__(self, entity):
        self.entity = entity
        self.frames = 10  # duration in frames
        # Render priority: 0 = under entities/items, 1 = between items and actors, 2 = above actors
        self.render_priority = 2  # Above actors to be clearly visible

    def tick(self, console, game_map):
        x, y = self.entity.x, self.entity.y
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            # Play animation in order
            if self.frames == 10:
                console.print(x, y, ".", fg=(255, 215, 0))  # Gold
            elif self.frames == 9:
                console.print(x, y, "o", fg=(255, 255, 0))  # Yellow
            elif self.frames == 8:
                console.print(x, y, "O", fg=(173, 255, 47))  # GreenYellow
            elif self.frames == 7:
                console.print(x, y, "0", fg=(0, 255, 127))  # SpringGreen
            elif self.frames <= 6:
                console.print(x, y, "!", fg=(0, 191, 255))  # DeepSkyBlue

        self.frames -= 1

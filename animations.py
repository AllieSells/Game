import random
from tcod.map import compute_fov
import tcod
import color
from gpu_stack import DripParticle as DripParticle, EmberParticle as EmberParticle, SmokeCloudParticle as SmokeCloudParticle

class ThrowAnimation:
    def __init__(self, path, item_char="|", item_color=(255, 255, 0)):
        self.path = path
        self.frames = 8  # duration in frames
        self.item_char = item_char
        self.item_color = item_color
        self.current_frame = 0

    def tick(self, console, game_map):
        if not self.path or self.frames <= 0:
            self.frames -= 1
            return
        
        # Calculate how far along the path we should be
        progress = self.current_frame / max(1, len(self.path) - 1)
        current_index = min(int(progress * len(self.path)), len(self.path) - 1)
        
        # Show the projectile at current position
        if current_index < len(self.path):
            x, y = self.path[current_index]
            x, y = int(x), int(y)
            
            if game_map.in_bounds(x, y) and game_map.visible[x, y]:
                # Show item character with motion trail
                game_map.screen_print_lit(console, x, y, self.item_char, fg=self.item_color)
                
                # Add trail effect - show previous positions fading
                """
                for i in range(1, min(3, current_index + 1)):
                    if current_index - i >= 0:
                        trail_x, trail_y = self.path[current_index - i]
                        trail_x, trail_y = int(trail_x), int(trail_y)
                        if game_map.in_bounds(trail_x, trail_y) and game_map.visible[trail_x, trail_y]:
                            # Fade the trail
                            fade_color = (
                                max(50, self.item_color[0] - i * 60),
                                max(50, self.item_color[1] - i * 60), 
                                max(50, self.item_color[2] - i * 60)
                            )
                            game_map.screen_print_lit(console, trail_x, trail_y, "·", fg=fade_color)
                """   # Needs rework TODO
        self.current_frame += 1
        self.frames -= 1

class TextPopupAnimation:
    def __init__(self, x, y, text, color=(255, 255, 255), duration=120):
        self.x = x
        self.y = y
        self.text = text
        self.color = color
        self.frames = duration  # duration in frames
        self.total_duration = duration

    def tick(self, console, game_map):
        if self.frames <= 0:
            return
        
        # Calculate how many characters to show based on elapsed time (slowed down by 3x)
        elapsed = self.total_duration - self.frames
        chars_to_show = min(len(self.text), elapsed // 3 + 1)  # Show one character every 3 frames
        
        # Show progressive text revelation at the same position
        displayed_text = self.text[:chars_to_show]
        game_map.screen_print(console, self.x, self.y, displayed_text, fg=self.color)
        
        self.frames -= 1


class TeleportAnimation:
    def __init__(self, position):
        self.position = position
        self.frames = 20  # duration in frames
        self.render_priority = 2  # Render above actors for visibility

    def tick(self, console, game_map):
        x, y = self.position
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            # Animate teleportation with a distortion effect
            import math
            
            progress = (10 - self.frames) / 10.0  # 0.0 to 1.0 progress through animation
            pulse_cycle = math.sin(progress * math.pi) * 0.25 + 0.75  # Oscillates between 0.75 and 1.0
            color = (
                int(255 * pulse_cycle),
                int(0 * pulse_cycle),
                int(255 * pulse_cycle)
            )
            if random.random() < 0.3:
                x += random.choice([-1, 0, 1])
            if random.random() < 0.3:
                y += random.choice([-1, 0, 1])
            if game_map.in_bounds(x, y) and game_map.visible[x, y]:
                options = [0xE0F3, 0xE0F4, 0xE0F5]
                game_map.screen_print_lit(console, x, y, chr(random.choice(options)), fg=color)

        self.frames -= 1

class ExplosionAnimation:
    def __init__(self, position, color=(255, 0, 0)):
        self.position = position
        self.color = color
        self.frames = 10  # duration in frames
        self.render_priority = 1  # Render above items but below actors
    
    def tick(self, console, game_map):
        x, y = self.position
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            # Animate explosion with expanding circles
            progress = (10 - self.frames) / 10.0  # 0.0 to 1.0 progress through animation
            radius = int(progress * 3)  # Expand from 0 to 3 tiles
            
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if dx * dx + dy * dy <= radius * radius:
                        sx, sy = x + dx, y + dy
                        if game_map.in_bounds(sx, sy) and game_map.visible[sx, sy]:
                            if random.random() < 0.5:
                                game_map.screen_print_lit(console, sx, sy, "*", fg=self.color)
                            else:
                                game_map.screen_print_lit(console, sx, sy, "o", fg=self.color)

        self.frames -= 1
        

class SplashAnimation:
    def __init__(self, position, color=(0, 255, 0)):
        self.position = position
        self.color = color
        self.frames = 10  # duration in frames
        self.render_priority = 1  # Render above items but below actors

    def tick(self, console, game_map):
        x, y = self.position
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            # Animate splash with expanding circles
            progress = (10 - self.frames) / 10.0  # 0.0 to 1.0 progress through animation
            radius = int(progress * 2)  # Expand from 0 to 2 tiles
            
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if dx * dx + dy * dy <= radius * radius:
                        sx, sy = x + dx, y + dy
                        if game_map.in_bounds(sx, sy) and game_map.visible[sx, sy]:
                            if random.random() < 0.5:
                                game_map.screen_print_lit(console, sx, sy, ".", fg=self.color)
                            else:
                                game_map.screen_print_lit(console, sx, sy, "*", fg=self.color)

        self.frames -= 1

class SigilStoneAnimation:
    def __init__(self, position):
        self.position = position
        self.frames = 60  # longer duration for slower breathing effect
        self.render_priority = 1  # Render above items but below actors

    def tick(self, console, game_map):
        x, y = self.position
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        # Check if there's still a sigil stone at this position
        has_sigil_stone = any(
            item.x == x and item.y == y and item.name == "Sigil Stone"
            for item in game_map.items
        )
        
        # If no sigil stone, let animation expire
        if not has_sigil_stone:
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            # Animate the sigil stone with a slow, gentle breathing effect
            import math
            
            # Find the sigil stone at this position to get its color
            sigil_stone = None
            for item in game_map.items:
                if item.x == x and item.y == y and item.name == "Sigil Stone":
                    sigil_stone = item
                    break
            
            # Use the entity's color or fallback to purple
            base_color = sigil_stone.color if sigil_stone else (255, 0, 255)
            
            progress = (60 - self.frames) / 60.0  # 0.0 to 1.0 progress through animation
            # Create slow breathing pulse - half cycle for gentle fade in and out
            pulse_cycle = math.sin(progress * math.pi) * 0.4 + 0.6  # Oscillates between 0.6 and 1.0
            color = (
                int(base_color[0] * pulse_cycle),
                int(base_color[1] * pulse_cycle),
                int(base_color[2] * pulse_cycle)
            )
            game_map.screen_print_lit(console, x, y, chr(0xE01F), fg=color)

        self.frames -= 1
        
        # Loop the animation seamlessly only if sigil stone is still there
        if self.frames <= 0:
            self.frames = 60


class GrassRustleAnimation:
    def __init__(self, position):
        self.position = position
        self.frames = 120  # duration in frames
        self.render_priority = 0  # Render under entities/items

    def tick(self, console, game_map):
        x, y = self.position

        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if not game_map.visible[x, y]:
            self.frames -= 1
            return

        # Base natural green range (no neon chaos)
        base_green = game_map.tiles["light"][x, y][1][1]  # Get the base green value from the tile's light color
        base_red = game_map.tiles["light"][x, y][1][0]  # Get the base red value from the tile's light color
        base_blue = game_map.tiles["light"][x, y][1][2]  # Get the base blue value from the tile's light color

        # Brightness curve - start light, get darker in middle, return to light
        progress = (120 - self.frames) / 120  # 0.0 to 1.0 progress through animation
        
        # Create curve that starts light, gets darker in middle, ends light
        import math
        intensity = 1.0 - 0.15 * math.sin(progress * math.pi)  # Varies from 1.0 -> 0.85 -> 1.0
        multiplier = intensity

        color = (
            int(base_red * multiplier),
            int(base_green * multiplier),
            int(base_blue * multiplier),
        )

        sequence = ['´', '"', "'", '`', '`', "'", '´']
        # Map the 60 frames to the 7-character sequence proportionally
        sequence_index = int((60 - self.frames) / 60 * (len(sequence) - 1))
        sequence_index = max(0, min(len(sequence) - 1, sequence_index))  # Clamp to valid range
        char = sequence[sequence_index]

        game_map.screen_print_lit(console, x, y, char, fg=color)

        self.frames -= 1


class HeardSoundAnimation:
    def __init__(self, position, player, color=(255, 255, 0), direction=None):
        self.position = position
        self.player = player
        self.color = color
        self.frames = 10  # duration in frames
        self.render_priority = 1  # Render above items but below actors
        self.direction = direction  # Will be set based on sound source direction

    def tick(self, console, game_map):
        x, y = self.position
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        # Calculate distance from player
        dx = x - self.player.x
        dy = y - self.player.y
        distance = (dx * dx + dy * dy) ** 0.5
        
        # If not visible and within 10 tiles of player, show sound tile animation
        if not game_map.visible[x, y] and distance <= 10:
            if self.direction is not None:
                # Show directional sound indicator (e.g. arrow pointing towards sound source)
                arrow_chars = { 
                    (0, -1): chr(0xE016),  # Up
                    (1, -1): chr(0xE017),  # Up-Right
                    (1, 0): chr(0xE018),   # Right
                    (1, 1): chr(0xE019),   # Down-Right
                    (0, 1): chr(0xE01A),   # Down
                    (-1, 1): chr(0xE01B),  # Down-Left
                    (-1, 0): chr(0xE01C),  # Left
                    (-1, -1): chr(0xE01D)  # Up-Left
                }
                char = arrow_chars.get(self.direction, '?')
                game_map.screen_print(console, x, y, char, fg=self.color)  # Colored sound tile
            else:
                game_map.screen_print(console, x, y, chr(0xE009), fg=self.color)  # Colored sound tile

        self.frames -= 1

class HeardDoorAnimation:
    def __init__(self, position, player):
        self.position = position
        self.player = player
        self.frames = 15  # duration in frames - longer for door sounds
        self.render_priority = 1  # Render above items but below actors

    def tick(self, console, game_map):
        x, y = self.position
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        # Calculate distance from player
        dx = x - self.player.x
        dy = y - self.player.y
        distance = (dx * dx + dy * dy) ** 0.5
        
        # If not visible and within 10 tiles of player, show door sound animation
        if not game_map.visible[x, y] and distance <= 10:
            game_map.screen_print(console, x, y, "!", fg=(0, 150, 255))  # Blue sound tile for doors

        self.frames -= 1

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
                    game_map.screen_print(console, x_draw, y_draw, "*", fg=(r, g, 0))  # yellow-orange flicker

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
                        game_map.screen_print(console, x, y, "*", fg=(r, g, 0))

        self.frames -= 1


class HealAnimation:
    def __init__(self, position):
        self.position = position
        self.frames = 20  # duration in frames
        self.render_priority = 1  # Render above items but below actors

    def tick(self, console, game_map):
        x, y = self.position
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            # Animate healing with a green pulse effect
            import math
            # Random rising pulsing particles
            for _ in range(3):
                offset_x = random.randint(-1, 1)
                offset_y = random.randint(-1, 0)  # Only rise upwards
                particle_x = x + offset_x
                particle_y = y + offset_y
                if game_map.in_bounds(particle_x, particle_y) and game_map.visible[particle_x, particle_y]:
                    # Create a pulsing green color
                    progress = (10 - self.frames) / 10.0  # 0.0 to 1.0 progress through animation
                    pulse_cycle = math.sin(progress * math.pi) * 0.5 + 0.5  # Oscillates between 0.5 and 1.0
                    color_intensity = int(255 * pulse_cycle)
                    game_map.screen_print_lit(console, particle_x, particle_y, "+", fg=(0, color_intensity, 0))  # green pulse
                    self.frames -= 1
            

class DarkBoltAnimation:
    def __init__(self, path):
        self.path = path
        self.frames = 5  # duration in frames

    def tick(self, console, game_map):
        # Use shadowcasting FOV from the source of the dark bolt so
        # the bolt doesn't render through walls
        if not self.path:
            self.frames -= 1
            return

        origin = (int(self.path[0][0]), int(self.path[0][1]))
        try:
            radius = max(len(self.path), 10)
            fov_map = compute_fov(game_map.tiles["transparent"], origin, radius=radius, algorithm=tcod.FOV_SHADOW)
        except Exception:
            fov_map = game_map.visible

        for x, y in self.path:
            x = int(x)
            y = int(y)
            if not game_map.in_bounds(x, y):
                continue
            
            # Only draw if visible and not blocked by walls
            if fov_map[x, y] and game_map.visible[x, y]:
                r = random.randint(100, 150)
                g = random.randint(0, 50)
                b = random.randint(100, 150)
                game_map.screen_print(console, x, y, "^", fg=(r, g, b))  # purple flicker

        self.frames -= 1

class FlameAnimation:
    def __init__(self, position):
        self.position = position
        self.frames = 10
        self.render_priority = 1
    
    def tick(self, console, game_map):
        x, y = self.position
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return
        if game_map.visible[x, y]:
            import sprite_manager
            chars = [chr(0xE110), chr(0xE111), chr(0xE112), chr(0xE113), chr(0xE114), chr(0xE115)]
            char = chars[(10 - self.frames) // 2 % len(chars)]
            tile_cp = int(game_map.tiles[x, y]["light"]["ch"])
            composite_char = sprite_manager.compose_entity_tile(tile_cp, ord(char), (255, 255, 255))
            game_map.screen_print(console, x, y, composite_char, fg=(255, 255, 255))
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
            chars = [chr(0xE003), chr(0xE004), chr(0xE005), chr(0xE006), chr(0xE007), chr(0xE008)]
            char = chars[(10 - self.frames) // 2 % len(chars)]
            game_map.screen_print(console, x, y, char, fg=(255, 200, 0))  # yellow-orange flicker
        self.frames -= 1

class EntityFireFlicker:
    def __init__(self, entity):
        self.entity = entity
        self.frames = 30  # Longer duration since it's more expensive to create
        # Render priority: 2 = above actors to overlay the fire effect
        self.render_priority = 2
        self.original_color = entity.color  # Store original color

    def tick(self, console, game_map):
        # Check if entity still exists and has fire coating
        if not hasattr(self.entity, 'body_parts') or not self.entity.body_parts:
            self.frames = 0  # End animation if no body parts
            return
            
        # Check if entity still has fire coating on any body part
        from liquid_system import LiquidType
        has_fire_coating = any(
            part.coating == LiquidType.FIRE 
            for part in self.entity.body_parts.body_parts.values()
        )
        
        if not has_fire_coating:
            self.frames = 0  # End animation if no fire coating
            return
            
        x, y = self.entity.x, self.entity.y
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            # Create flickering fire effect using entity's character
            r = random.randint(200, 255)
            g = random.randint(50, 150)
            game_map.screen_print(console, x, y, self.entity.char, fg=(r, g, 0))
            
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
            game_map.screen_print(console, x, y, "X", fg=(r, g, 0))  # yellow-orange flicker

class FireSmoke:
    def __init__(self, position):
        self.position = position
        self.frames = 12  # duration in frames
        # Smoke should render between items and actors so it appears to rise above the campfire
        self.render_priority = 1

    def tick(self, console, game_map):
        x0, y0 = self.position
        # Drift upward slowly as smoke rises
        y = y0 - (12 - self.frames) // 3
        x = x0 + random.choice([-1, 0, 1])  # slight horizontal jitter

        if not game_map.in_bounds(int(x), int(y)):
            self.frames -= 1
            return

        # Use shadowcasting FOV from the smoke origin so smoke doesn't draw through walls
        try:
            origin = (int(x0), int(y0))
            radius = max(3, min(5, (12 - self.frames) + 2))
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
            chars = [chr(0xE116), chr(0xE117), chr(0xE118), chr(0xE119), chr(0xE11A), chr(0xE11B)]
            char = chars[(12 - self.frames) // 2 % len(chars)]
            game_map.screen_print(console, x, y, char, fg=(255, 255, 255))
            game_map.screen_print(console, xi, yi, char, fg=(255, 255, 255))

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
                game_map.screen_print_lit(console, x, y, ".", fg=(255, 215, 0))  # Gold
            elif self.frames == 9:
                game_map.screen_print_lit(console, x, y, "o", fg=(255, 255, 0))  # Yellow
            elif self.frames == 8:
                game_map.screen_print_lit(console, x, y, "O", fg=(173, 255, 47))  # GreenYellow
            elif self.frames == 7:
                game_map.screen_print_lit(console, x, y, "0", fg=(0, 255, 127))  # SpringGreen
            elif self.frames <= 6:
                game_map.screen_print_lit(console, x, y, "!", fg=(0, 191, 255))  # DeepSkyBlue

        self.frames -= 1

class EnchantedSlashAnimation:
    def __init__(self, x, y, color):
        self.x = x
        self.y = y
        self.frames = 5  # duration in frames
        self.render_priority = 2  # Above actors
        self.color = color
    def tick(self, console, game_map):
        x, y = int(self.x), int(self.y)
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            # Curved slash effect with enchanted color
            if self.frames == 5:
                game_map.screen_print_lit(console, x, y, "_", fg=self.color)  # Base color
            elif self.frames == 4:
                game_map.screen_print_lit(console, x, y, "~", fg=(min(255, self.color[0] + 50), min(255, self.color[1] + 50), min(255, self.color[2] + 50)))  # Brighter
            elif self.frames <= 3:
                game_map.screen_print_lit(console, x, y, ")", fg=(min(255, self.color[0] + 100), min(255, self.color[1] + 100), min(255, self.color[2] + 100)))  # Even brighter
            
            # Random spark with enchanted color
            if random.random() < 0.3:
                spark_x = x + random.choice([-1, 0, 1])
                spark_y = y + random.choice([-1, 0, 1])
                if game_map.in_bounds(spark_x, spark_y) and game_map.visible[spark_x, spark_y]:
                    game_map.screen_print_lit(console, spark_x, spark_y, "`", fg=(min(255, self.color[0] + 150), min(255, self.color[1] + 150), min(255, self.color[2] + 150)))  # Bright spark

        self.frames -= 1


class SlashAnimation:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.frames = 5  # duration in frames
        self.render_priority = 2  # Above actors
    def tick(self, console, game_map):
        """Render a brief slash effect at the stored (x,y).

        This animation expects to be called with (console, game_map) from
        GameMap.render; it draws a small rotating glyph for a few frames
        and then expires.
        """
        x, y = int(self.x), int(self.y)
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            # Curved slash effect
            if self.frames == 3:
                game_map.screen_print_lit(console, x, y, "_", fg=(255, 0, 0))  # Red
            elif self.frames == 2:
                game_map.screen_print_lit(console, x, y, "~", fg=(255, 255, 0))  # Yellow
            elif self.frames == 1:
                game_map.screen_print_lit(console, x, y, ")", fg=(255, 255, 244))  # Yellow White
            
            # Random spark
            if random.random() < 0.3:
                spark_x = x + random.choice([-1, 0, 1])
                spark_y = y + random.choice([-1, 0, 1])
                if game_map.in_bounds(spark_x, spark_y) and game_map.visible[spark_x, spark_y]:
                    game_map.screen_print_lit(console, spark_x, spark_y, "`", fg=(255, 50, 0))  # Gold spark

        self.frames -= 1
        
class WaterDropAnimation:
    def __init__(self, position):
        self.position = position
        self.frames = 10  # duration in frames
        self.render_priority = 0  # Render below everything else for subtlety

    def tick(self, console, game_map):
        x, y = self.position
        if not game_map.in_bounds(x, y):
            self.frames -= 1
            return

        if game_map.visible[x, y]:
            # Animate water drop with a brief blue sparkle
            if self.frames == 10:
                game_map.screen_print_lit(console, x, y, "|", fg=(0, 191, 255))  # DeepSkyBlue
            elif self.frames == 9:
                game_map.screen_print_lit(console, x, y, ";", fg=(30, 144, 255))  # DodgerBlue
            elif self.frames == 8:
                game_map.screen_print_lit(console, x, y, ".", fg=(0, 0, 255))  # Pale Blue
            elif self.frames == 5:
                game_map.screen_print_lit(console, x, y, ".", fg=(0, 0, 0))  # Darkgrey

        self.frames -= 1

class WaterMoveAnimation:
    def __init__(self, position):
        self.position = position
        self.frames = 10 # duration in frames
        self.render_priority = 0  # Render below everything else for subtlety
    def tick(self, console, game_map):
        x, y = self.position
        self.frames -= 1
        if not game_map.in_bounds(x, y):
            return
        if game_map.visible[x, y]:
            if self.frames > 5:
                game_map.screen_print_lit(console, x, y, chr(0xE141), fg=color.shallow_water)
            else:
                game_map.screen_print_lit(console, x, y, chr(0xE142), fg=color.shallow_water)




class GlobalWaterAnimation:
    """Single persistent animation that oscillates all visible water tiles
    back and forth: 0→1→2→1→0→1→2→...
    """
    CHARS = [chr(0xE140), chr(0xE141), chr(0xE142), chr(0xE143), chr(0xE144)]
    # How many ticks each frame is held before advancing
    FRAME_DURATION = 5

    def __init__(self):
        self.render_priority = 0
        self.frames = 10 ** 9  # never expires
        self._tick = 0

    def tick(self, console, game_map):
        self._tick += 1
        sequence = [0, 1, 2, 1]
        idx = (self._tick // self.FRAME_DURATION) % len(sequence)
        char_cp = ord(self.CHARS[sequence[idx]])
        try:
            origin_x, origin_y, view_width, view_height = game_map.get_viewport(console)
            x_slice = slice(origin_x, origin_x + view_width)
            y_slice = slice(origin_y, origin_y + view_height)
            water_mask = (game_map.tiles["name"][x_slice, y_slice] == "Water") & game_map.visible[x_slice, y_slice]
            console.tiles_rgb["ch"][:view_width, :view_height][water_mask] = char_cp
            console.tiles_rgb["fg"][:view_width, :view_height][water_mask] = color.shallow_water
        except Exception:
            pass

class GlobalOceanAnimation:
    """Single persistent animation that loops all visible ocean tiles
    forward: 0→1→2→3→4→0→1→2→3→4→...
    """
    CHARS = [chr(0xE160), chr(0xE161), chr(0xE162), chr(0xE163), chr(0xE164), chr(0xE165), chr(0xE166), chr(0xE167)]
    # How many ticks each frame is held before advancing
    FRAME_DURATION = 5

    def __init__(self):
        self.render_priority = 0
        self.frames = 10 ** 9  # never expires
        self._tick = 0

    def tick(self, console, game_map):
        self._tick += 1
        idx = (self._tick // self.FRAME_DURATION) % len(self.CHARS)
        char_cp = ord(self.CHARS[idx])
        try:
            origin_x, origin_y, view_width, view_height = game_map.get_viewport(console)
            x_slice = slice(origin_x, origin_x + view_width)
            y_slice = slice(origin_y, origin_y + view_height)
            ocean_mask = (game_map.tiles["name"][x_slice, y_slice] == "Ocean") & game_map.visible[x_slice, y_slice]
            console.tiles_rgb["ch"][:view_width, :view_height][ocean_mask] = char_cp
            console.tiles_rgb["fg"][:view_width, :view_height][ocean_mask] = color.shallow_water
            deep_ocean_mask = (game_map.tiles["name"][x_slice, y_slice] == "Deep Ocean") & game_map.visible[x_slice, y_slice]
            console.tiles_rgb["ch"][:view_width, :view_height][deep_ocean_mask] = char_cp
            console.tiles_rgb["fg"][:view_width, :view_height][deep_ocean_mask] = color.deep_water
        except Exception:
            pass

class GlobalBeachWaterAnimation:
    """Animates beach tiles that border water.
    Each qualifying tile has a sequence of codepoints stored in
    game_map.beach_water_anim[(x, y)] = (cp0, cp1, ..., cp7).
    """
    FRAME_DURATION = 5  # ticks per frame, matches ocean animation speed

    # Frame sequences by border direction.
    # E/W variants are chosen randomly per-tile during world generation.
    FRAMES_N  = tuple(range(0xE190, 0xE198))
    FRAMES_S  = tuple(range(0xE198, 0xE1A0))
    FRAMES_W  = tuple(range(0xE1A0, 0xE1A8))
    FRAMES_W2 = tuple(range(0xE1A8, 0xE1B0))
    FRAMES_E  = tuple(range(0xE1B0, 0xE1B8))
    FRAMES_E2 = tuple(range(0xE1B8, 0xE1C0))
    FRAMES_SW = tuple(range(0xE1C0, 0xE1C8))
    FRAMES_SE = tuple(range(0xE1C8, 0xE1D0))
    FRAMES_NE = tuple(range(0xE1D0, 0xE1D8))
    FRAMES_NW = tuple(range(0xE1D8, 0xE1E0))

    def __init__(self):
        self.render_priority = 0
        self.frames = 10 ** 9  # never expires
        self._tick = 0

    def tick(self, console, game_map):
        self._tick += 1
        anim_map = getattr(game_map, "beach_water_anim", None)
        if not anim_map:
            return
        idx = (self._tick // self.FRAME_DURATION) % 8
        try:
            origin_x, origin_y, view_width, view_height = game_map.get_viewport(console)
            for (x, y), seq in anim_map.items():
                vx = x - origin_x
                vy = y - origin_y
                if 0 <= vx < view_width and 0 <= vy < view_height:
                    if game_map.visible[x, y]:
                        console.tiles_rgb["ch"][vx, vy] = seq[idx]
        except Exception:
            pass


class GlobalRiverAnimation:
    """Animates interior river tiles (not overlaid with bank sprites).

    Uses the same ocean wave frames (0xE160-0xE167) at the same speed
    but targets only tiles listed in game_map.river_anim.
    """
    FRAME_DURATION = 5

    def __init__(self):
        self.render_priority = 0
        self.frames = 10 ** 9
        self._tick = 0

    def tick(self, console, game_map):
        self._tick += 1
        anim_map = getattr(game_map, "river_anim", None)
        if not anim_map:
            return
        idx = (self._tick // self.FRAME_DURATION) % 8
        try:
            origin_x, origin_y, view_width, view_height = game_map.get_viewport(console)
            for (x, y), seq in anim_map.items():
                vx = x - origin_x
                vy = y - origin_y
                if 0 <= vx < view_width and 0 <= vy < view_height:
                    if game_map.visible[x, y]:
                        console.tiles_rgb["ch"][vx, vy] = seq[idx]
        except Exception:
            pass


class GlobalDungeonWaterAnimation:
    """Animates dungeon water tiles using precomposed neighbor-masked frames.

    Reads game_map.dungeon_water_anim, built by
    sprite_manager.build_dungeon_water_anim().  Each entry holds a tuple of
    5 codepoints — one per animation frame — that already contain the correct
    floor-edge compositing for that tile position.
    """
    FRAME_DURATION = 5  # ticks per frame, matches ocean animation speed
    N_FRAMES = 5        # must match len(sprite_manager._WATER_FRAME_CPS)

    def __init__(self):
        self.render_priority = 0
        self.frames = 10 ** 9  # never expires
        self._tick = 0

    def tick(self, console, game_map):
        self._tick += 1
        anim_map = getattr(game_map, 'dungeon_water_anim', None)
        if not anim_map:
            return
        idx = (self._tick // self.FRAME_DURATION) % self.N_FRAMES
        # Keep a current-frame lookup so _render_entity can composite entities
        # against the animated tile base rather than the static floor codepoint.
        current: dict = {}
        try:
            origin_x, origin_y, view_width, view_height = game_map.get_viewport(console)
            for (x, y), seq in anim_map.items():
                cp = seq[idx]
                current[(x, y)] = cp
                vx = x - origin_x
                vy = y - origin_y
                if 0 <= vx < view_width and 0 <= vy < view_height:
                    if game_map.visible[x, y]:
                        console.tiles_rgb["ch"][vx, vy] = cp
                        # Use white fg so the composited RGBA sprite isn't tinted
                        # by the floor tile's original fg colour.
                        console.tiles_rgb["fg"][vx, vy] = (255, 255, 255)
        except Exception:
            pass
        game_map.dungeon_water_current = current


# ------------------------------- #
# GPU ANIMS AND GPU PARTICLES
# --------------------------------- #
# Physics classes now live in gpu_stack.py alongside their render passes.
# Re-exported here so existing code that imports from animations still works.
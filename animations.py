import random

import game_map

class LightningAnimation:
    def __init__(self, path):
        self.path = path
        self.frames = 1000  # duration in frames

    def tick(self, console, game_map):
        for x, y in self.path:
            # Draws if visible
            if game_map.visible[x, y]:
                r = random.randint(200, 255)
                g = random.randint(180, 255)
                console.print(x, y, "*", fg=(r, g, 0))  # yellow-orange flicker
        self.frames -= 1

import time
import tcod
import tcod.event

WIDTH, HEIGHT = 40, 20

tileset = tcod.tileset.load_tilesheet(
    "dejavu16x16_gs_tc.png", 16, 16, tcod.tileset.CHARMAP_TCOD
)

class Animation:
    def __init__(self, frames, delay=0.1):
        """
        frames: list of (x, y, char, (r,g,b))
        delay: seconds per frame
        """
        self.frames = frames
        self.delay = delay
        self.timer = 0.0
        self.index = 0
        self.done = False

    def update(self, dt: float):
        if self.done:
            return
        self.timer += dt
        if self.timer >= self.delay:
            self.timer -= self.delay
            self.index += 1
            if self.index >= len(self.frames):
                self.done = True

    def render(self, console: tcod.Console):
        if not self.done and 0 <= self.index < len(self.frames):
            x, y, char, color = self.frames[self.index]
            console.print(x, y, char, fg=color)

with tcod.context.new_terminal(WIDTH, HEIGHT, tileset=tileset, title="Non-blocking Animations") as context:
    console = tcod.Console(WIDTH, HEIGHT, order="F")

    x, y = 10, 10
    animations: list[Animation] = []
    last_time = time.time()
    running = True

    while running:
        # --- time management
        now = time.time()
        dt = now - last_time
        last_time = now

        console.clear()

        # --- draw player
        console.print(x, y, "@", fg=(255, 255, 255))

        # --- update & draw animations
        for anim in list(animations):
            anim.update(dt)
            anim.render(console)
            if anim.done:
                animations.remove(anim)

        context.present(console)

        # --- handle input
        for event in tcod.event.get():
            if event.type == "QUIT":
                running = False
            elif event.type == "KEYDOWN":
                if event.sym == tcod.event.K_ESCAPE:
                    running = False
                elif event.sym == tcod.event.K_RIGHT:
                    x = min(WIDTH-1, x+1)
                elif event.sym == tcod.event.K_LEFT:
                    x = max(0, x-1)
                elif event.sym == tcod.event.KeySym.A:
                    # Launch a non-blocking projectile animation
                    frames = [(x+i, y, "*", (255, 200, 50)) for i in range(1, 8)]
                    animations.append(Animation(frames, delay=0.05))

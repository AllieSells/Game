import pygame
from pygame.locals import *
from OpenGL.GL import *
from OpenGL.GLU import *
import math
from OpenGL.GL import glutSolidCube

def draw_cube():
    """Draw a simple cube"""
    vertices = [
        [1, 1, 1], [1, 1, -1], [1, -1, -1], [1, -1, 1],
        [-1, 1, 1], [-1, 1, -1], [-1, -1, -1], [-1, -1, 1]
    ]
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7)
    ]
    
    glBegin(GL_LINES)
    for edge in edges:
        for vertex in edge:
            glVertex3fv(vertices[vertex])
    glEnd()

def main():
    pygame.init()
    display = (800, 600)
    pygame.display.set_mode(display, DOUBLEBUF | OPENGL)
    pygame.display.set_caption("3D Game")
    
    gluPerspective(45, (display[0] / display[1]), 0.1, 50.0)
    glTranslatef(0, 0, -5)
    
    clock = pygame.time.Clock()
    running = True
    rotation_x, rotation_y = 0, 0
    
    while running:
        for event in pygame.event.get():
            if event.type == QUIT:
                running = False
        
        keys = pygame.key.get_pressed()
        if keys[K_LEFT]:
            rotation_y += 2
        if keys[K_RIGHT]:
            rotation_y -= 2
        if keys[K_UP]:
            rotation_x += 2
        if keys[K_DOWN]:
            rotation_x -= 2
        
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        glTranslatef(0, 0, -5)
        glRotatef(rotation_x, 1, 0, 0)
        glRotatef(rotation_y, 0, 1, 0)
        
        draw_cube()
        pygame.display.flip()
        clock.tick(60)
    
    pygame.quit()

if __name__ == "__main__":
    main()
    class Player:
        def __init__(self):
            self.pos = [0, 1, 0]
            self.rot = [0, 0]
            self.speed = 0.1
        
        def update(self, keys, mouse_delta):
            # Mouse look
            self.rot[0] -= mouse_delta[1] * 0.1
            self.rot[1] -= mouse_delta[0] * 0.1
            self.rot[0] = max(-89, min(89, self.rot[0]))
            
            # WASD movement
            forward = [math.sin(math.radians(self.rot[1])), 0, math.cos(math.radians(self.rot[1]))]
            right = [math.cos(math.radians(self.rot[1])), 0, -math.sin(math.radians(self.rot[1]))]
            
            if keys[K_w]:
                self.pos = [self.pos[i] + forward[i] * self.speed for i in range(3)]
            if keys[K_s]:
                self.pos = [self.pos[i] - forward[i] * self.speed for i in range(3)]
            if keys[K_a]:
                self.pos = [self.pos[i] - right[i] * self.speed for i in range(3)]
            if keys[K_d]:
                self.pos = [self.pos[i] + right[i] * self.speed for i in range(3)]
            
            self.pos[1] = max(0.5, self.pos[1])
        
        def apply_camera(self):
            glRotatef(self.rot[0], 1, 0, 0)
            glRotatef(self.rot[1], 0, 1, 0)
            glTranslatef(-self.pos[0], -self.pos[1], -self.pos[2])

    def draw_floor():
        size = 20
        glColor3f(0.5, 0.8, 0.5)
        glBegin(GL_QUADS)
        glVertex3f(-size, 0, -size)
        glVertex3f(size, 0, -size)
        glVertex3f(size, 0, size)
        glVertex3f(-size, 0, size)
        glEnd()

    def draw_cube(x, y, z, size=1):
        glPushMatrix()
        glTranslatef(x, y, z)
        glColor3f(1, 0, 0)
        glutSolidCube(size)
        glPopMatrix()

    def main():
        pygame.init()
        display = (1200, 800)
        pygame.display.set_mode(display, DOUBLEBUF | OPENGL)
        pygame.display.set_caption("3D Game")
        pygame.event.set_grab(True)
        pygame.mouse.set_visible(False)
        
        glEnable(GL_DEPTH_TEST)
        gluPerspective(45, (display[0] / display[1]), 0.1, 500.0)
        
        player = Player()
        clock = pygame.time.Clock()
        running = True
        
        while running:
            for event in pygame.event.get():
                if event.type == QUIT:
                    running = False
                if event.type == KEYDOWN and event.key == K_ESCAPE:
                    running = False
            
            keys = pygame.key.get_pressed()
            mouse_delta = pygame.mouse.get_rel()
            player.update(keys, mouse_delta)
            
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glLoadIdentity()
            player.apply_camera()
            
            draw_floor()
            draw_cube(0, 1, -5, 1)
            draw_cube(5, 1, -5, 1)
            draw_cube(-5, 1, -5, 1)
            
            pygame.display.flip()
            clock.tick(60)
        
        pygame.quit()

    if __name__ == "__main__":
        main()
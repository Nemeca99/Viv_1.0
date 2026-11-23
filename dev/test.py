import pygame
import math
import os

pygame.init()
# Using a standard window size
WIDTH, HEIGHT = 800, 800
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Galactic Entropy")
clock = pygame.time.Clock()

BLACK = (0, 0, 0)
RED = (255, 50, 50)
GREEN = (50, 255, 50)
BLUE = (50, 50, 255)
PURPLE = (200, 50, 255)
WHITE = (255, 255, 255)
GRAY = (100, 100, 100)

t = 0.0
dt = 0.05
base_sequence = [1, 0.5, 0, -1, -0.5, 0]
spiral_points = []

center_x, center_y = WIDTH // 2, HEIGHT // 2

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Fade the screen slightly to create a glowing trail effect
    fade_surface = pygame.Surface((WIDTH, HEIGHT))
    fade_surface.set_alpha(10) 
    fade_surface.fill(BLACK)
    screen.blit(fade_surface, (0, 0))

    # 1. HARDWARE ENTROPY FROM YOUR PHONE
    raw_entropy = os.urandom(1)[0] 
    # Make the noise more visible for the spiral arms
    entropy_noise = ((raw_entropy / 255.0) - 0.5) * 0.5 

    # 2. THE THREE-BODY ALGEBRA
    step_index = int(t * 10) % 6
    body_A = base_sequence[step_index]
    body_B = base_sequence[(step_index + 2) % 6]
    body_C = base_sequence[(step_index + 4) % 6]
    net_force = (body_A + body_B + body_C) / 3.0

    # 3. THE EULER SPIRAL (FIXED SCALING)
    theta = t * (math.pi / 6) # Slightly slower rotation
    
    # Exponential growth: e^(0.03 * t)
    growth = math.exp(0.03 * t)
    
    # FIXED: Multiplier is now 40 instead of 15, so it actually expands!
    radius = (growth * 40) + (entropy_noise * 30)
    
    x = center_x + radius * math.cos(theta + entropy_noise)
    y = center_y + radius * math.sin(theta + entropy_noise)
    
    spiral_points.append((x, y))
    
    if len(spiral_points) > 5000:
        spiral_points.pop(0)

    t += dt

    # =================================================================
    # DRAWING
    # =================================================================
    
    # Draw the Spiral (The Galaxy)
    if len(spiral_points) > 1:
        for i in range(len(spiral_points) - 1):
            fade = i / len(spiral_points)
            # Fades from Cyan to deep Blue
            color = (int(50 * fade), int(150 * fade), int(255 * fade))
            # Draw thicker lines for the galactic dust look
            pygame.draw.line(screen, color, spiral_points[i], spiral_points[i+1], 2)

    # Draw the 3 Bodies (The Triangle)
    angle_A = 0
    angle_B = 2 * math.pi / 3
    angle_C = 4 * math.pi / 3
    
    tri_radius = 250 # Made the triangle bigger to compensate
    pos_A = (center_x + tri_radius * math.cos(angle_A), center_y + tri_radius * math.sin(angle_A))
    pos_B = (center_x + tri_radius * math.cos(angle_B), center_y + tri_radius * math.sin(angle_B))
    pos_C = (center_x + tri_radius * math.cos(angle_C), center_y + tri_radius * math.sin(angle_C))
    
    pygame.draw.polygon(screen, GRAY, [pos_A, pos_B, pos_C], 1)
    
    # The 3 Bodies (The anchors of reality)
    pygame.draw.circle(screen, RED, (int(pos_A[0]), int(pos_A[1])), 6)
    pygame.draw.circle(screen, BLUE, (int(pos_B[0]), int(pos_B[1])), 6)
    pygame.draw.circle(screen, GREEN, (int(pos_C[0]), int(pos_C[1])), 6)

    # Draw the Oscilloscope (The discrete pixels of time)
    graph_y = HEIGHT - 100
    for i in range(50): 
        step = int(t * 10) + i
        val = base_sequence[step % 6]
        line_y = graph_y - (val * 30)
        pygame.draw.rect(screen, WHITE, (i * 15, line_y, 10, 10))

    # Draw the Entropy Meter
    entropy_rect = pygame.Rect(20, 20, 20, 100)
    pygame.draw.rect(screen, GRAY, entropy_rect, 1)
    fill_height = int(raw_entropy / 255.0 * 100)
    fill_rect = pygame.Rect(20, 20 + (100 - fill_height), 20, fill_height)
    pygame.draw.rect(screen, PURPLE, fill_rect)

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
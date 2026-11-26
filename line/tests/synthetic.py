"""Draw floors with a line whose offset and angle are known exactly."""

import math

import cv2
import numpy as np

WIDTH, HEIGHT = 640, 480


def scene(offset=0.0, angle_deg=0.0, floor=(70, 70, 70), line=(235, 235, 235),
          line_px=40, gradient=0.0, noise=0.0, draw_line=True, seed=0):
    image = np.full((HEIGHT, WIDTH, 3), floor, np.uint8)
    if draw_line:
        x = (WIDTH - 1) / 2 * (1 + offset)
        dx = math.tan(math.radians(angle_deg))
        half = line_px / 2 / math.cos(math.radians(angle_deg))
        top_y, bottom_y = -20, HEIGHT + 20
        points = []
        for y, sign in ((bottom_y, -1), (bottom_y, 1), (top_y, 1), (top_y, -1)):
            points.append((x + dx * (HEIGHT - 1 - y) + sign * half, y))
        cv2.fillPoly(image, [np.round(points).astype(np.int32)], line)
    output = image.astype(np.float32)
    if gradient:  # Dark left side, bright right side.
        output *= np.linspace(1 - gradient, 1 + gradient, WIDTH)[None, :, None]
    if noise:
        output += np.random.default_rng(seed).normal(0, noise, output.shape)
    return np.clip(output, 0, 255).astype(np.uint8)

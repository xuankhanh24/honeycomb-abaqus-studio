# -*- coding: utf-8 -*-
"""Convex honeycomb b/l/theta geometry; compatible with Abaqus Python 2.7."""
import math


def network(panel, b, length, theta_deg, angle_deg, phase_x, phase_y, clip):
    theta = math.radians(theta_deg)
    half_width = length * math.sin(theta)
    rise = length * math.cos(theta)
    width, pitch = 2. * half_width, b + rise
    co, si = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    extent = int(math.ceil((panel * 1.5 + abs(phase_x) + abs(phase_y)) / min(width, pitch))) + 3
    vertices = ((half_width,b/2.), (0.,b/2.+rise), (-half_width,b/2.),
                (-half_width,-b/2.), (0.,-b/2.-rise), (half_width,-b/2.))
    walls = set()
    for row in range(-extent,extent+1):
        for col in range(-extent,extent+1):
            cx, cy = width * (col + .5 * (row % 2)), pitch * row
            pts = [((x+cx)*co-(y+cy)*si+phase_x,
                    (x+cx)*si+(y+cy)*co+phase_y) for x,y in vertices]
            for k in range(6):
                segment = clip(pts[k], pts[(k+1)%6])
                if segment:
                    walls.add(segment)
    return sorted(walls)

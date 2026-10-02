"""Small spherical buckets for fixed 150 m neighbourhood queries."""
from itertools import product
import math

RADIUS_M = 150
EARTH_M = 6371000
CELL = 2 * math.sin(RADIUS_M / EARTH_M / 2)
NEIGHBOURS = tuple(product((-1, 0, 1), repeat=3))


def cell(point):
    lat, lon = map(math.radians, point)
    return tuple(math.floor(value / CELL) for value in
                 (math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)))

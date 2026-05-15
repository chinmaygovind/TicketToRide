#!/usr/bin/env python3
"""Find swapped cities by comparing detected positions with expected positions."""
import math
from city_coords import CITIES as detected
from game_data import CITIES as expected

def dist(p1, p2):
    return math.hypot(p1[0]-p2[0], p1[1]-p2[1])

print("Comparing detected cities with expected positions...\n")

# For each detected city, find closest expected position
# If the detected position is very close to an expected position but labeled differently,
# it's a swap candidate

swaps = []

# Build a map of detected positions
detected_by_name = {name: pos for name, pos in detected.items()}
expected_by_name = {name: pos for name, pos in expected.items()}

# For each detected city, find what it should be based on position
for detected_name, detected_pos in detected_by_name.items():
    distances = [(expected_name, dist(detected_pos, expected_pos))
                 for expected_name, expected_pos in expected_by_name.items()]
    distances.sort(key=lambda x: x[1])
    
    closest_expected_name, closest_dist = distances[0]
    second_closest_name, second_closest_dist = distances[1]
    
    if detected_name != closest_expected_name and closest_dist < 30:
        # This detected city is close to a different expected position
        print(f"SWAP SUSPECT: {detected_name} at {detected_pos}")
        print(f"  Closest match: {closest_expected_name} (expected at {expected_by_name[closest_expected_name]}, distance: {closest_dist:.1f}px)")
        print(f"  2nd closest:    {second_closest_name} (expected at {expected_by_name[second_closest_name]}, distance: {second_closest_dist:.1f}px)")
        print()

print("\nAlignment check - expected vs detected coordinates:")
big_diffs = []
for name in expected_by_name:
    if name in detected_by_name:
        exp_pos = expected_by_name[name]
        det_pos = detected_by_name[name]
        d = dist(exp_pos, det_pos)
        if d > 15:
            big_diffs.append((name, d, exp_pos, det_pos))

if big_diffs:
    print(f"Found {len(big_diffs)} cities with positions differing by >15px:")
    for name, d, exp, det in sorted(big_diffs, key=lambda x: x[1], reverse=True):
        print(f"  {name}: expected {exp}, detected {det} (diff: {d:.1f}px)")
else:
    print("All cities match expected positions within 15px tolerance")


from routing.two_opt import (
    calculate_route_distance,
    two_opt
)

# Road-distance matrix returned by OSRM.
distance_matrix = [
    [0.00, 4.49, 6.59],
    [4.24, 0.00, 2.99],
    [6.34, 3.15, 0.00]
]

# Start at the warehouse (0), visit customers 1 and 2,
# then return to the warehouse (0).
initial_route = [0, 1, 2, 0]

# Calculate the distance before optimization.
initial_distance = calculate_route_distance(
    initial_route,
    distance_matrix
)

# Run the 2-opt algorithm.
optimized_route, optimized_distance = two_opt(
    initial_route,
    distance_matrix
)

print("Original route:", initial_route)
print("Original distance:", round(initial_distance, 2), "km")

print("Optimized route:", optimized_route)
print("Optimized distance:", round(optimized_distance, 2), "km")

print(
    "Distance saved:",
    round(initial_distance - optimized_distance, 2),
    "km"
)

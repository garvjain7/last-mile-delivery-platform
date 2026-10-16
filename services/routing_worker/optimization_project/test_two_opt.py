
from routing.route_matrix import get_distance_matrix
from routing.two_opt import calculate_route_distance, two_opt

# Store and two customer locations
locations = [
    (22.745049, 75.892471),
    (22.765049, 75.912471),
    (22.775049, 75.922471)
]

# Get real road distances from public OSRM
result = get_distance_matrix(locations)

distance_matrix = result["distance_matrix_km"]

# Start at location 0, visit locations 1 and 2, return to 0
initial_route = [0, 1, 2, 0]

# Calculate the original route distance
original_distance = calculate_route_distance(
    initial_route, distance_matrix
)

# Optimize the route using 2-opt
optimized_route, optimized_distance = two_opt(
    initial_route, distance_matrix
)

print("Original route:", initial_route)
print("Original distance:", round(original_distance, 2), "km")

print("Optimized route:", optimized_route)
print("Optimized distance:", round(optimized_distance, 2), "km")

print(
    "Distance saved:",
    round(original_distance - optimized_distance, 2),
    "km"
)

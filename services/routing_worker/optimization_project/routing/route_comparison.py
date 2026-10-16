
# Distance matrix returned by OSRM, in kilometres
distance_matrix = [
    [0.0, 4.49, 6.59],
    [4.24, 0.0, 2.99],
    [6.34, 3.15, 0.0]
]


def calculate_route_distance(route, matrix):

    total_distance = 0

    # Visit each consecutive pair of locations
    for i in range(len(route) - 1):
        current_location = route[i]
        next_location = route[i + 1]

        total_distance += matrix[current_location][next_location]

    return total_distance


# Location indices: A = 0, B = 1, C = 2
route_1 = [0, 1, 2, 0]
route_2 = [0, 2, 1, 0]

distance_1 = calculate_route_distance(
    route_1, distance_matrix
)

distance_2 = calculate_route_distance(
    route_2, distance_matrix
)

print("Route 1 distance:", round(distance_1, 2), "km")
print("Route 2 distance:", round(distance_2, 2), "km")

if distance_1 < distance_2:
    print("Shorter route: A -> B -> C -> A")
elif distance_2 < distance_1:
    print("Shorter route: A -> C -> B -> A")
else:
    print("Both routes have equal distance.")

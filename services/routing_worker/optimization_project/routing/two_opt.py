
def calculate_route_distance(route, distance_matrix):
    total_distance = 0

    for i in range(len(route) - 1):
        current_location = route[i]
        next_location = route[i + 1]

        total_distance += distance_matrix[current_location][next_location]

    return total_distance


def two_opt(route, distance_matrix):
    best_route = route.copy()
    best_distance = calculate_route_distance(best_route, distance_matrix)

    improved = True

    while improved:
        improved = False

        for i in range(1, len(best_route) - 2):
            for j in range(i + 1, len(best_route) - 1):

                new_route = best_route.copy()
                new_route[i:j + 1] = reversed(new_route[i:j + 1])

                new_distance = calculate_route_distance(
                    new_route, distance_matrix
                )

                if new_distance < best_distance:
                    best_route = new_route
                    best_distance = new_distance
                    improved = True
                    break

            if improved:
                break

    return best_route, best_distance

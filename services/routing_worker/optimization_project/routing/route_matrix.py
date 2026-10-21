
import requests


def get_distance_matrix(locations):
    """
    Get road distances and estimated travel durations
    between all supplied locations using OSRM.

    Each location must be a tuple:
    (latitude, longitude)
    """

    # OSRM expects longitude,latitude for each location.
    coordinates = ";".join(
        f"{lon},{lat}"
        for lat, lon in locations
    )

    # Build the OSRM Table API URL.
    url = (
        "https://router.project-osrm.org/table/v1/driving/"
        f"{coordinates}"
    )

    # Request both distance and duration matrices.
    params = {
        "annotations": "distance,duration"
    }

    # Send the request and wait up to 30 seconds.
    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    # Raise an error if the HTTP request failed.
    response.raise_for_status()

    # Convert the response into a Python dictionary.
    data = response.json()

    # Check whether OSRM successfully calculated the matrix.
    if data.get("code") != "Ok":
        raise ValueError(
            f"OSRM matrix failed: {data.get('code')}"
        )

    # Convert metres to kilometres and seconds to minutes.
    return {
        "distance_matrix_km": [
            [distance / 1000 for distance in row]
            for row in data["distances"]
        ],
        "duration_matrix_minutes": [
            [duration / 60 for duration in row]
            for row in data["durations"]
        ]
    }


# Run this example only when this file is executed directly.
# Importing get_distance_matrix from another file will not
# automatically run this example.
if __name__ == "__main__":

    # Warehouse and two example customer locations.
    locations = [
        (22.745049, 75.892471),
        (22.765049, 75.912471),
        (22.775049, 75.922471)
    ]

    result = get_distance_matrix(locations)

    print("Distance Matrix (km):")
    for row in result["distance_matrix_km"]:
        print([round(value, 2) for value in row])

    print("\nDuration Matrix (minutes):")
    for row in result["duration_matrix_minutes"]:
        print([round(value, 2) for value in row])

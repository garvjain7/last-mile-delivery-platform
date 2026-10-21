
import requests


def get_road_route(store_lat, store_lon, drop_lat, drop_lon):

    # OSRM expects longitude first, then latitude
    coordinates = (
        f"{store_lon},{store_lat};"
        f"{drop_lon},{drop_lat}"
    )

    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{coordinates}"
    )

    params = {
        "overview": "false"
    }

    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    response.raise_for_status()
    data = response.json()

    if data.get("code") != "Ok":
        raise ValueError(
            f"OSRM could not find a route: {data.get('code')}"
        )

    route = data["routes"][0]

    return {
        "road_distance_km": route["distance"] / 1000,
        "travel_time_minutes": route["duration"] / 60
    }


# Test with the first order from your dataset
result = get_road_route(
    22.745049,
    75.892471,
    22.765049,
    75.912471
)

print("OSRM Result:", result)


import math


def haversine_distance(lat1, lon1, lat2, lon2):

    # Step 1: Earth's approximate radius in kilometres
    earth_radius = 6371.0

    # Step 2: Convert latitude and longitude to radians
    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    # Step 3: Calculate the differences between coordinates
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    # Step 4: Apply the Haversine formula
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    # Step 5: Calculate the angular distance
    a = max(0.0, min(1.0, a))
    central_angle = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )

    # Step 6: Calculate distance in kilometres
    distance = earth_radius * central_angle

    return distance


# Test using two example locations in Delhi
store_latitude = 28.6139
store_longitude = 77.2090

customer_latitude = 28.5355
customer_longitude = 77.3910

distance = haversine_distance(
    store_latitude,
    store_longitude,
    customer_latitude,
    customer_longitude
)

print("Straight-line distance:", round(distance, 2), "km")


from data_loader import get_warehouse_and_orders
from routing.route_matrix import get_distance_matrix
from routing.two_opt import calculate_route_distance, two_opt
from save_route import save_optimized_route
from database import get_connection

def main():
    # 1. Load data from PostgreSQL
    warehouses, orders = get_warehouse_and_orders()

    print("Active warehouses:", len(warehouses))
    print("Pending orders:", len(orders))

    if not warehouses:
        print("No active warehouse found.")
        return

    # 2. Select the first active warehouse
    warehouse = warehouses[0]

    warehouse_id = warehouse[0]
    warehouse_name = warehouse[1]
    warehouse_lat = float(warehouse[2])
    warehouse_lon = float(warehouse[3])

    print("\nSelected warehouse:", warehouse_name)

    # 3. Keep pending orders assigned to this warehouse
    warehouse_orders = [
        order for order in orders
        if str(order[1]) == str(warehouse_id)
    ]

    if not warehouse_orders:
        print("No pending orders for this warehouse.")
        return

    # 4. Prepare coordinates: warehouse first, then customers
    locations = [(warehouse_lat, warehouse_lon)]

    for order in warehouse_orders:
        customer_lat = float(order[4])
        customer_lon = float(order[5])
        locations.append((customer_lat, customer_lon))

    print("Routing locations:", len(locations))
    print("\nRequesting road distances from OSRM...")

    # 5. Calculate road distance and duration matrices
    matrices = get_distance_matrix(locations)
    distance_matrix = matrices["distance_matrix_km"]
    duration_matrix = matrices["duration_matrix_minutes"]

    # 6. Build the initial route and return to the warehouse
    initial_route = list(range(len(locations))) + [0]

    # 7. Calculate initial distance and duration
    original_distance = calculate_route_distance(
        initial_route, distance_matrix
    )
    original_duration = calculate_route_distance(
        initial_route, duration_matrix
    )

    # 8. Optimize the route using 2-opt
    optimized_route, optimized_distance = two_opt(
        initial_route, distance_matrix
    )

    # 9. Calculate duration for the optimized route
    optimized_duration = calculate_route_distance(
        optimized_route, duration_matrix
    )

    
    # Get the available test driver and assigned vehicle.
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT d.user_id, d.vehicle_id
            FROM drivers d
            JOIN users u ON u.id = d.user_id
            JOIN vehicles v ON v.id = d.vehicle_id
            WHERE u.email = %s
              AND d.status = 'available'
              AND v.is_active = TRUE
        """, ("test-driver-2@example.com",))

        driver_record = cursor.fetchone()

        if driver_record is None:
            print("No available test driver and vehicle found.")
            return

        driver_id, vehicle_id = driver_record

    finally:
        connection.close()

    
    # Save the optimized route and its delivery stops.
    print("\nDEBUG: Calling save_optimized_route now...")
    saved_route_id = save_optimized_route(
        warehouse_id=warehouse_id,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        warehouse_location=(warehouse_lat, warehouse_lon),
        warehouse_orders=warehouse_orders,
        optimized_route=optimized_route,
        distance_matrix=distance_matrix,
        duration_matrix=duration_matrix
    )



    # 10. Display results
    
    
    print("\n--- ORIGINAL ROUTE ---")
    print("Route indices:", initial_route)
    print("Distance:", round(original_distance, 2), "km")
    print("Estimated duration:", round(original_duration, 2), "minutes")

    print("\n--- OPTIMIZED ROUTE ---")
    print("Route indices:", optimized_route)
    print("Distance:", round(optimized_distance, 2), "km")
    print("Estimated duration:", round(optimized_duration, 2), "minutes")

    print("\n--- OPTIMIZED DELIVERY SEQUENCE ---")

    for position, location_index in enumerate(optimized_route):
        if location_index == 0:
            print(f"{position + 1}. Warehouse: {warehouse_name}")
        else:
            order = warehouse_orders[location_index - 1]
            order_id = order[0]
            order_ref = order[2]

            print(
                f"{position + 1}. Deliver order {order_ref} "
                f"(Order ID: {order_id})"
            )

    print(
        "\nDistance saved:",
        round(original_distance - optimized_distance, 2),
        "km"
    )


if __name__ == "__main__":
    main()

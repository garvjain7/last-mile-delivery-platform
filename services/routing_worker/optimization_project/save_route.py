
from datetime import datetime, timedelta, timezone

from database import get_connection


def save_optimized_route(
    warehouse_id,
    driver_id,
    vehicle_id,
    warehouse_location,
    warehouse_orders,
    optimized_route,
    distance_matrix,
    duration_matrix
):
    """
    Save an optimized route and its delivery stops in PostgreSQL.

    warehouse_location: (latitude, longitude)
    warehouse_orders: database order tuples
    optimized_route: location indices; index 0 is the warehouse
    """

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Start the estimated schedule from the current UTC time.
        arrival_time = datetime.now(timezone.utc)

        # Convert the route's total distance and duration to
        # the integer units required by the database.
        total_distance_m = round(
            sum(
                distance_matrix[optimized_route[i]][optimized_route[i + 1]]
                for i in range(len(optimized_route) - 1)
            ) * 1000
        )

        total_duration_s = round(
            sum(
                duration_matrix[optimized_route[i]][optimized_route[i + 1]]
                for i in range(len(optimized_route) - 1)
            ) * 60
        )

        # Create the route record.
        cursor.execute(
            """
            INSERT INTO routes (
                warehouse_id,
                driver_id,
                vehicle_id,
                status,
                total_distance_m,
                total_duration_s
            )
            VALUES (%s, %s, %s, 'planned', %s, %s)
            RETURNING id
            """,
            (
                warehouse_id,
                driver_id,
                vehicle_id,
                total_distance_m,
                total_duration_s
            )
        )

        route_id = cursor.fetchone()[0]

        # Save each customer stop in optimized order.
        sequence = 0

        for i in range(1, len(optimized_route) - 1):
            location_index = optimized_route[i]

            # Location 0 is the warehouse. All other indices
            # correspond to warehouse_orders[index - 1].
            order = warehouse_orders[location_index - 1]

            order_id = order[0]
            latitude = float(order[4])
            longitude = float(order[5])

            # Add the OSRM duration for the previous route leg.
            previous_index = optimized_route[i - 1]
            leg_minutes = duration_matrix[previous_index][location_index]
            arrival_time += timedelta(minutes=leg_minutes)

            sequence += 1

            cursor.execute(
                """
                INSERT INTO route_stops (
                    route_id,
                    order_id,
                    sequence,
                    status,
                    planned_location,
                    planned_arrival_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    'pending',
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    %s
                )
                """,
                (
                    route_id,
                    order_id,
                    sequence,
                    longitude,
                    latitude,
                    arrival_time
                )
            )

        # Commit route and stop records together.
        
        # Mark the orders on this route as assigned.
        for i in range(1, len(optimized_route) - 1):
            location_index = optimized_route[i]
            order = warehouse_orders[location_index - 1]
            order_id = order[0]

            cursor.execute(
                """
                UPDATE orders
                SET status = 'assigned'
                WHERE id = %s
                  AND status = 'pending'
                """,
                (order_id,)
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Could not assign order {order_id}. "
                    "It may no longer be pending."
                )

        # Save the route, stops, and order statuses together.
        connection.commit()

        print("\nRoute successfully saved to PostgreSQL!")
        print("Route ID:", route_id)
        print("Total distance:", total_distance_m, "metres")
        print("Estimated duration:", total_duration_s, "seconds")
        print("Delivery stops saved:", sequence)
        print("Order statuses updated to assigned.")
        return route_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

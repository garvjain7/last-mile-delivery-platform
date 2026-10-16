
from database import get_connection


def get_warehouse_and_orders(warehouse_id=None):
    connection = get_connection()

    try:
        cursor = connection.cursor()

        # Fetch active warehouses
        cursor.execute("""
            SELECT
                id,
                name,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude
            FROM warehouses
            WHERE is_active = TRUE
        """)

        warehouses = cursor.fetchall()

        # Fetch eligible delivery orders
        query = """
            SELECT
             id,
            warehouse_id,
            merchant_order_ref,
            status,
            ST_Y(delivery_location::geometry) AS latitude,
            ST_X(delivery_location::geometry) AS longitude,
            window_earliest,
            window_latest
            FROM orders
            WHERE status = 'pending'
        """

        parameters = ()

        if warehouse_id is not None:
            query += " AND warehouse_id = %s"
            parameters = (warehouse_id,)

        cursor.execute(query, parameters)
        orders = cursor.fetchall()

        return warehouses, orders

    finally:
        connection.close()


if __name__ == "__main__":
    warehouses, orders = get_warehouse_and_orders()

    print("Active warehouses:", len(warehouses))
    print("Pending orders:", len(orders))

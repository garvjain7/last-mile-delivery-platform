from routing.data_loader import (
    load_delivery_data,
    validate_columns
)

from routing.data_preprocessing import (
    preprocess_delivery_data
)

from routing.distance_calculation import haversine_distance


def main():

    # Step 1: Load the dataset
    df = load_delivery_data()
    print("Original Rows:", len(df))

    # Step 2: Validate required columns
    df = validate_columns(df)
    print("Column validation successful!")

    # Step 3: Preprocess the dataset
    df = preprocess_delivery_data(df)

    # Step 4: Count valid and invalid routing records
    valid_rows = int(df["routing_valid"].sum())
    invalid_rows = len(df) - valid_rows

    print("\n--- ROUTING VALIDATION REPORT ---")
    print("Total Rows:", len(df))
    print("Routing Valid Rows:", valid_rows)
    print("Routing Invalid Rows:", invalid_rows)

    # Step 5: Check missing values
    print("\n--- MISSING VALUES ---")
    print(df.isnull().sum())

    # Step 6: Check duplicate order IDs
    duplicate_orders = df["Order_ID"].duplicated().sum()
    print("\nDuplicate Order IDs:", duplicate_orders)

    # Step 7: Check missing or invalid coordinates
    print(
        "\nRows with Missing Coordinates:",
        int(df["missing_coordinates"].sum())
    )

    print(
        "Rows with Invalid Store Coordinates:",
        int(df["invalid_store_coordinates"].sum())
    )

    print(
        "Rows with Invalid Drop Coordinates:",
        int(df["invalid_drop_coordinates"].sum())
    )

    # Step 8: Identify negative coordinates for review
    negative_coordinates = (
        (df["Store_Latitude"] < 0) |
        (df["Store_Longitude"] < 0) |
        (df["Drop_Latitude"] < 0) |
        (df["Drop_Longitude"] < 0)
    )

    print(
        "\nRows with Negative Coordinates:",
        int(negative_coordinates.sum())
    )

    # Step 9: Check invalid dates and times
    print(
        "\nInvalid Order Dates:",
        int(df["Order_Date"].isnull().sum())
    )

    print(
        "Invalid Order Times:",
        int(df["Order_Time"].isnull().sum())
    )

    print(
        "Invalid Pickup Times:",
        int(df["Pickup_Time"].isnull().sum())
    )

    
    # Diagnostic: inspect suspicious store coordinates
    suspicious_stores = df[
        (df["Store_Latitude"] <= 1) |
        (df["Store_Longitude"] <= 1)
    ]

    print("\n--- SUSPICIOUS STORE COORDINATES ---")
    print("Count:", len(suspicious_stores))

    print(
        suspicious_stores[
            [
                "Order_ID",
                "Store_Latitude",
                "Store_Longitude"
            ]
        ].head(20)
    )

    print("\n--- STORE COORDINATE RANGES ---")
    print(
        df[
            ["Store_Latitude", "Store_Longitude"]
        ].describe()
    )

    
    # Count store locations with both coordinates equal to zero
    zero_store_coordinates = (
        (df["Store_Latitude"] == 0) &
        (df["Store_Longitude"] == 0)
    )

    print(
        "\nStore locations with (0, 0):",
        int(zero_store_coordinates.sum())
    )

    # Count negative store latitudes
    negative_store_latitude = df["Store_Latitude"] < 0

    print(
        "Negative store latitudes:",
        int(negative_store_latitude.sum())
    )

    # Count negative store longitudes
    negative_store_longitude = df["Store_Longitude"] < 0

    print(
        "Negative store longitudes:",
        int(negative_store_longitude.sum())
    )

    # Count coordinates that are nonzero but <= 1
    small_nonzero_store_coordinates = (
        (
            (df["Store_Latitude"] != 0) &
            (df["Store_Latitude"] <= 1)
        ) |
        (
            (df["Store_Longitude"] != 0) &
            (df["Store_Longitude"] <= 1)
        )
    )

    print(
        "Rows with nonzero store coordinates <= 1:",
        int(small_nonzero_store_coordinates.sum())
    )

    print(
    "Negative store coordinate flags:",
    int(df["negative_store_coordinate"].sum())
)

    # Select records that passed coordinate validation
    valid_df = df[df["routing_valid"]].copy()

# Calculate straight-line distance for each valid order
    valid_df["straight_line_distance_km"] = valid_df.apply(
    lambda row: haversine_distance(
        row["Store_Latitude"],
        row["Store_Longitude"],
        row["Drop_Latitude"],
        row["Drop_Longitude"]
    ),
    axis=1
)

# Display the first five results
    print("\n--- DISTANCE CALCULATION RESULTS ---")
    print(
        valid_df[
            [
            "Order_ID",
            "Store_Latitude",
            "Store_Longitude",
            "Drop_Latitude",
            "Drop_Longitude",
            "straight_line_distance_km"
            ]
    ].head()
)

if __name__ == "__main__":
    main()

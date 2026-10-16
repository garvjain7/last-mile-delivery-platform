
import pandas as pd


COORDINATE_COLUMNS = [
    "Store_Latitude",
    "Store_Longitude",
    "Drop_Latitude",
    "Drop_Longitude"
]


def preprocess_delivery_data(df):

    # Create a copy to preserve original data
    df = df.copy()

    # Clean column names
    df.columns = df.columns.str.strip()

    # Define categorical columns
    CATEGORICAL_COLUMNS = [
        "Weather",
        "Traffic",
        "Vehicle",
        "Area",
        "Category"
    ]

    # Clean categorical values
    for column in CATEGORICAL_COLUMNS:
        if column in df.columns:
            df[column] = (
                df[column]
                .astype("string")
                .str.strip()
            )

    # Convert coordinates into numeric values
    for column in COORDINATE_COLUMNS:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    # Convert order date
    df["Order_Date"] = pd.to_datetime(
        df["Order_Date"],
        dayfirst=True,
        errors="coerce"
    )

    # Convert order time
    df["Order_Time"] = pd.to_datetime(
        df["Order_Time"],
        format="%H:%M:%S",
        errors="coerce"
    ).dt.time

    # Convert pickup time
    df["Pickup_Time"] = pd.to_datetime(
        df["Pickup_Time"],
        format="%H:%M:%S",
        errors="coerce"
    ).dt.time

    
    # Identify store locations with both coordinates equal to zero
    df["invalid_store_coordinates"] = (
        (df["Store_Latitude"] == 0) &
        (df["Store_Longitude"] == 0)
    )

    # Identify drop locations with both coordinates equal to zero
    df["invalid_drop_coordinates"] = (
        (df["Drop_Latitude"] == 0) &
        (df["Drop_Longitude"] == 0)
    )

    # Identify missing coordinates
    df["missing_coordinates"] = (
        df[COORDINATE_COLUMNS].isna().any(axis=1)
    )

    # Identify coordinates outside geographic boundaries
    df["out_of_bounds_coordinates"] = (
        df["Store_Latitude"].abs().gt(90) |
        df["Store_Longitude"].abs().gt(180) |
        df["Drop_Latitude"].abs().gt(90) |
        df["Drop_Longitude"].abs().gt(180)
    )

    # Flag negative coordinates without modifying them
    df["negative_store_coordinate"] = (
        (df["Store_Latitude"] < 0) |
        (df["Store_Longitude"] < 0)
    )

    # Mark records suitable for initial routing checks
    df["routing_valid"] = ~(
        df["missing_coordinates"] |
        df["invalid_store_coordinates"] |
        df["invalid_drop_coordinates"] |
        df["out_of_bounds_coordinates"]
    )


    return df

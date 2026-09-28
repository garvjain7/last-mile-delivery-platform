import pandas as pd
COORDINATE_COLUMNS=[
    "Store_Latitude",
    "Store_Longitude",
    "Drop_Latitude",
    "Drop_Longitude"
]

def preprocess_delivery_data(df):
    df=df.copy()
    df.columns=df.columns.str.strip()

    CATEGORICAL_COLUMNS=[
        "Weather",
        "Traffic",
        "Vehicle",
        "Area",
        "Category"
    ]

    for column in CATEGORICAL_COLUMNS:
        df[column]=df[column].astype(str).str.strip()

    for column in COORDINATE_COLUMNS:
        df[column]=pd.to_numeric(df[column], errors="coerce")

    df["Order_Date"]=pd.to_datetime(
        df["Order_Date"],
        dayfirst=True,
        errors="coerce"
    )

    df["Order_Time"]=pd.to_datetime(
        df["Order_Time"],
        format="%H:%M:%S",
        errors="coerce"
    ).dt.time

    df["Pickup_Time"]=pd.to_datetime(
            df["Pickup_Time"],
            format="%H:%M:%S",
            errors="coerce"
        ).dt.time

    df["invalid_store_coordinates"]=(
        (df["Store_Latitude"]==0) |
        (df["Store_Longitude"]==0)
    )

    df["invalid_drop_coordinates"]=(
        (df["Drop_Latitude"] <= 1) |
        (df["Drop_Longitude"] <= 1)
    )

    df["negative_store_coordinate"]=(
            (df["Store_Latitude"]<0) |
            (df["Store_Longitude"]<0)
    )

    df.loc[
        df["negative_store_coordinate"],
        "Store_Latitude"
    ] = (
        df.loc[
            df["negative_store_coordinate"],
            "Store_Latitude"
        ].abs()
    )

    # Repair suspicious negative store longitude
    df.loc[
        df["negative_store_coordinate"],
        "Store_Longitude"
    ] = (
        df.loc[
            df["negative_store_coordinate"],
            "Store_Longitude"
        ].abs()
    )

    # Mark records that can be used for routing
    df["routing_valid"] = ~(
        df["invalid_store_coordinates"] |
        df["invalid_drop_coordinates"]
    )

    return df
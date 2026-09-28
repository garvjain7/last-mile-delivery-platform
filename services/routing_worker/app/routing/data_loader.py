import pandas as pd
DATA_PATH="amazon_delivery.csv"

REQUIRED_COLUMNS = [
    "Order_ID",
    "Store_Latitude",
    "Store_Longitude",
    "Drop_Latitude",
    "Drop_Longitude",
    "Order_Date",
    "Order_Time",
    "Pickup_Time",
    "Traffic",
    "Vehicle",
    "Delivery_Time"
]

def load_delivery_data():
    df=pd.read_csv(DATA_PATH)
    return df

def validate_columns(df):

    missing_columns = [
        column
        for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            print(f"Missing required columns: {missing_columns}")
        )


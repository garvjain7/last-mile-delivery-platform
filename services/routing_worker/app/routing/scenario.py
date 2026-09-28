import pandas as pd
def create_routing_scenario(df,selected_date,selected_area=None):
    scenario=df.copy()

    scenario["Order_Date"]=pd.to_datetime(
        scenario["Order_Date"],
        dayfirst=True,
        errors="coerce"
    )

    selected_date=pd.to_datetime(
        selected_date,
        dayfirst=True,
        errors="coerce"
    )

    #Validate selected date
    if pd.isna(selected_date):
        raise ValueError("Invalid Selected Date")

    #Filter orders for selected date
    scenario=scenario[
        scenario["Order_Date"] == selected_date
    ].copy()

    #Optionally filter by area
    if selected_area is not None:
        scenario=scenario[
            scenario["Area"] == selected_area
        ].copy()

    if scenario.empty:
        raise ValueError(
            "No orders found for the selected scenario"
        )

    return scenario
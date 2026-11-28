
import streamlit as st

st.set_page_config(
    page_title="Control Tower",
    page_icon="🚚",
    layout="wide"
)

st.title("🚚 Control Tower")
st.caption("Last Mile Delivery Platform | Live Fleet Operations")

st.divider()

# Dashboard metrics
col1, col2, col3, col4 = st.columns(4)

col1.metric("Active Drivers", "0")
col2.metric("Active Routes", "0")
col3.metric("Completed Deliveries", "0")
col4.metric("Delayed Deliveries", "0")

st.divider()

# Main dashboard sections
left, right = st.columns([2, 1])

with left:
    st.subheader("📍 Live Fleet Map")
    st.info("Driver locations will appear here after backend integration.")

with right:
    st.subheader("🚚 Fleet Status")
    st.info("Driver information will appear here.")

st.subheader("🛣️ Route Monitoring")
st.info("Route progress and delivery stops will appear here.")

st.subheader("⚠️ Alerts")
st.info("Delivery exceptions and alerts will appear here.")

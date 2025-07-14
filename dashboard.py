import streamlit as st
import pandas as pd

# Replace with your actual published CSV URL
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTxyz123abc/pub?gid=0&single=true&output=csv"

st.set_page_config(page_title="LoRa Sensor Dashboard", layout="wide")
st.title("📡 Real-Time LoRa Sensor Dashboard")
st.caption("Auto-updates every ~5 seconds from your Google Sheet")

try:
    df = pd.read_csv(CSV_URL)

    # Display latest data
    st.subheader("Latest Sensor Readings")
    st.dataframe(df.tail(5), use_container_width=True)

    # Line charts
    st.subheader("Live Charts")
    chart_cols = ["CO2", "PM2.5", "PM10", "AGL"]
    for col in chart_cols:
        if col in df.columns:
            st.line_chart(df[col], height=150)

    # Map
    if "Lat" in df.columns and "Lon" in df.columns:
        st.subheader("GPS Position Map")
        map_df = df[["Lat", "Lon"]].rename(columns={"Lat": "latitude", "Lon": "longitude"})
        st.map(map_df.dropna())

except Exception as e:
    st.error(f"Failed to load data: {e}")
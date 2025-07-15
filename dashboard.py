import streamlit as st
import pandas as pd
import pydeck as pdk
from streamlit_autorefresh import st_autorefresh

# Refresh every 5 seconds
st_autorefresh(interval=5000, key="datarefresh")

# Google Sheets CSV URL
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vS1iTT7WRip-kWXp8BP3nt9AUj_0GlO1g0vCf0kH4TrkpDeWfCmxSQGflGOSQKe1xhBCTSPQYpq--b3/pub?gid=1212685962&single=true&output=csv"

st.set_page_config(page_title="LoRa Sensor Dashboard", layout="wide")
st.title("📡 Real-Time LoRa Sensor Dashboard")
st.caption("Auto-refreshes every 5 seconds from Google Sheets")

try:
    df = pd.read_csv(CSV_URL)

    # Data cleanup
    df = df.dropna(subset=["Lat", "Lon"])
    df["Lat"] = pd.to_numeric(df["Lat"], errors="coerce")
    df["Lon"] = pd.to_numeric(df["Lon"], errors="coerce")
    df["AGL"] = pd.to_numeric(df["AGL"], errors="coerce")
    df["CO2"] = pd.to_numeric(df["CO2"], errors="coerce")
    df["PM2.5"] = pd.to_numeric(df["PM2.5"], errors="coerce")

    # Latest Data Panel
    st.subheader("Latest Sensor Readings")
    st.dataframe(df.tail(5), use_container_width=True)

    # CO2 & PM Warnings
    latest = df.iloc[-1]
    if latest["CO2"] > 1000:
        st.error(f"⚠️ High CO2 Detected: {latest['CO2']} ppm")
    if latest["PM2.5"] > 35:
        st.warning(f"🌫️ Elevated PM2.5: {latest['PM2.5']} µg/m³")

    # 3D Map with Altitude as Elevation
    st.subheader("📍 3D GPS Position Map (AGL Elevation)")
    map_df = df[["Lat", "Lon", "AGL"]].dropna()

    layer = pdk.Layer(
        "ColumnLayer",
        data=map_df,
        get_position='[Lon, Lat]',
        get_elevation="AGL",
        elevation_scale=10,
        radius=30,
        get_fill_color='[200, 30, 0, 160]',
        pickable=True,
        auto_highlight=True,
    )

    view_state = pdk.ViewState(
        latitude=map_df["Lat"].mean(),
        longitude=map_df["Lon"].mean(),
        zoom=14,
        pitch=45,
    )

    r = pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip={"text": "AGL: {AGL} ft"})
    st.pydeck_chart(r)

except Exception as e:
    st.error(f"Failed to load data: {e}")
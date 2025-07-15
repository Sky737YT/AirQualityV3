import streamlit as st
import pandas as pd
import pydeck as pdk
import altair as alt
from streamlit_autorefresh import st_autorefresh
import time

# === Refresh every 5 seconds ===
st_autorefresh(interval=5000, key="datarefresh")

# === Google Sheet CSV with cachebuster ===
CSV_URL_BASE = "https://docs.google.com/spreadsheets/d/e/2PACX-1vS1iTT7WRip-kWXp8BP3nt9AUj_0GlO1g0vCf0kH4TrkpDeWfCmxSQGflGOSQKe1xhBCTSPQYpq--b3/pub?gid=1212685962&single=true&output=csv"
CSV_URL = CSV_URL_BASE + f"&cachebuster={int(time.time())}"

st.set_page_config(page_title="LoRa Sensor Dashboard", layout="wide")
st.title("📡 Real-Time LoRa Sensor Dashboard")
st.caption("Auto-refreshes every 5 seconds from Google Sheets")

try:
    df = pd.read_csv(CSV_URL)

    # Clean up data
    df = df.dropna(subset=["Lat", "Lon"])
    df["Lat"] = pd.to_numeric(df["Lat"], errors="coerce")
    df["Lon"] = pd.to_numeric(df["Lon"], errors="coerce")
    df["AGL"] = pd.to_numeric(df["AGL"], errors="coerce")
    df["CO2"] = pd.to_numeric(df["CO2"], errors="coerce")
    df["PM2.5"] = pd.to_numeric(df["PM2.5"], errors="coerce")
    df["PM1"] = pd.to_numeric(df["PM1"], errors="coerce")
    df["PM10"] = pd.to_numeric(df["PM10"], errors="coerce")
    df["Temp"] = pd.to_numeric(df["Temp"], errors="coerce")

    # === Live snapshot ===
    latest = df.iloc[-1]
    st.subheader("🌡️ Live Environment Snapshot")
    col1, col2 = st.columns(2)
    col1.metric("Temperature (°F)", f"{latest['Temp']}")
    col2.metric("Altitude AGL (ft)", f"{latest['AGL']}")

    # === Warnings ===
    if latest["CO2"] > 1000:
        st.error(f"⚠️ High CO2 Detected: {latest['CO2']} ppm")
    if latest["PM2.5"] > 35:
        st.warning(f"🌫️ Elevated PM2.5: {latest['PM2.5']} µg/m³")

    # === Latest rows table ===
    st.subheader("🧾 Latest Sensor Rows")
    df_display = df.tail(5).reset_index(drop=True)
    st.dataframe(df_display, use_container_width=True)

    # === Raw line charts ===
    st.subheader("📈 Raw Sensor Trends")

    def raw_chart(column_name):
        return alt.Chart(df).mark_line().encode(
            x=alt.X("Timestamp:T", title="Time"),
            y=alt.Y(f"{column_name}:Q", title=column_name)
        ).properties(title=f"{column_name} over time")

    for col in ["CO2", "PM1", "PM2.5", "PM10"]:
        if col in df.columns:
            st.altair_chart(raw_chart(col), use_container_width=True)

    # === 3D GPS Position Map ===
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
    st.error(f"❌ Failed to load data: {e}")
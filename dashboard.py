import streamlit as st
import pandas as pd
import pydeck as pdk
import altair as alt
from streamlit_autorefresh import st_autorefresh
import time

# === Auto-refresh every 5 seconds ===
st_autorefresh(interval=5000, key="datarefresh")

# === Google Sheet CSV with cache-busting ===
CSV_URL_BASE = "https://docs.google.com/spreadsheets/d/e/2PACX-1vS1iTT7WRip-kWXp8BP3nt9AUj_0GlO1g0vCf0kH4TrkpDeWfCmxSQGflGOSQKe1xhBCTSPQYpq--b3/pub?gid=1212685962&single=true&output=csv"
CSV_URL = CSV_URL_BASE + f"&cachebuster={int(time.time())}"

# === Page setup ===
st.set_page_config(page_title="LoRa Sensor Dashboard", layout="wide")
st.title("📡 Real-Time LoRa Sensor Dashboard")
st.caption("Auto-refreshes every 5 seconds from Google Sheets")

try:
    df = pd.read_csv(CSV_URL)

    # === Clean & Convert ===
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"])
    df = df.tail(4).reset_index(drop=True)  # Get last 4 rows only, no sorting

    for col in ["Lat", "Lon", "AGL", "CO2", "PM2.5", "PM1", "PM10", "Temp"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if df.empty or "Temp" not in df.columns:
        st.warning("Waiting for valid sensor data to arrive...")
        st.stop()

    # === Live snapshot ===
    latest = df.iloc[-1]  # Use the last row as the most recent
    st.subheader("🌡️ Live Environment Snapshot")
    col1, col2 = st.columns(2)
    col1.metric("Temperature (°F)", f"{latest['Temp']}")
    col2.metric("Altitude AGL (ft)", f"{latest['AGL']}")

    # === Warnings
    if latest["CO2"] > 1000:
        st.error(f"⚠️ High CO2 Detected: {latest['CO2']} ppm")
    if latest["PM2.5"] > 35:
        st.warning(f"🌫️ Elevated PM2.5: {latest['PM2.5']} µg/m³")

    # === Latest rows
    st.subheader("🧾 Latest Sensor Rows")
    st.dataframe(df.reset_index(drop=True), use_container_width=True)

    # === Sensor trends (limited)
    st.subheader("📈 Sensor Trends (Last 4 Rows Only)")

    def raw_chart_filtered(column_name, threshold=0):
        chart_df = df[df[column_name] > threshold]
        if chart_df.empty:
            st.warning(f"No valid data to plot for {column_name}")
            return None
        return alt.Chart(chart_df).mark_line().encode(
            x=alt.X("Timestamp:T", title="Time"),
            y=alt.Y(f"{column_name}:Q", title=column_name)
        ).properties(title=f"{column_name} Over Time (Last 4 Readings)")

    for col in ["CO2", "PM1", "PM2.5", "PM10"]:
        if col in df.columns:
            chart = raw_chart_filtered(col)
            if chart:
                st.altair_chart(chart, use_container_width=True)

    # === 3D GPS Position Map
    st.subheader("📍 3D GPS Position Map (AGL Elevation)")
    map_df = df.dropna(subset=["Lat", "Lon", "AGL"])

    if not map_df.empty:
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
    else:
        st.info("No GPS data to show on the map yet.")

except Exception as e:
    st.error(f"❌ Failed to load data: {e}")
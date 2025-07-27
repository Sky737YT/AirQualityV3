import streamlit as st
import pandas as pd
import pydeck as pdk
import altair as alt
from streamlit_autorefresh import st_autorefresh
import gspread
from google.oauth2.service_account import Credentials
import time

# === Auto-refresh every 5 seconds ===
st_autorefresh(interval=5000, key="datarefresh")

# === Page config ===
st.set_page_config(page_title="LoRa Sensor Dashboard", layout="wide")
st.title("📡 Real-Time LoRa Sensor Dashboard")
st.caption("Auto-refreshes every 5 seconds from Google Sheets (via API)")

try:
    # === Load service account from Streamlit Cloud secrets ===
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    service_account_info = st.secrets["gcp_service_account"].to_dict()
    creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    client = gspread.authorize(creds)

    # === Open sheet using its unique key ===
    spreadsheet = client.open_by_key("1b_8TWrMPYctgDK6_LNe0LHpWybadBLYf0uNBwBt_sKs")
    worksheet = spreadsheet.worksheet("Live")

    # === Read full sheet data ===
    data = worksheet.get_all_values()
    headers = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=headers)

    # === Clean & convert ===
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"])

    for col in ["Lat", "Lon", "AGL", "CO2", "PM2.5", "PM1", "PM10", "Temp", "Hum"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # === Filter out GPS 0,0 early ===
    df = df[(df["Lat"] != 0) & (df["Lon"] != 0)]

    # === Find most recent continuous data block ===
    df = df.sort_values("Timestamp")  # ensure it's sorted
    df["TimeDiff"] = df["Timestamp"].diff().dt.total_seconds().fillna(0)
    gap_threshold = 300  # 5 minutes
    df["BlockID"] = (df["TimeDiff"] > gap_threshold).cumsum()
    latest_block_id = df["BlockID"].iloc[-1]
    df = df[df["BlockID"] == latest_block_id].copy()
    df.drop(columns=["TimeDiff", "BlockID"], inplace=True)

    # === Stop if still empty after filtering ===
    if df.empty or "Temp" not in df.columns:
        st.warning("Waiting for valid sensor data to arrive...")
        st.stop()

    # === Live snapshot ===
    latest = df.iloc[-1]
    st.subheader("🌡️ Live Environment Snapshot")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Temperature (°F)", f"{latest['Temp']}")
    col2.metric("Humidity (%)", f"{latest['Hum']}")
    col3.metric("PM2.5 (µg/m³)", f"{latest['PM2.5']}")
    col4.metric("CO2 (ppm)", f"{latest['CO2']}")
    col5.metric("Altitude AGL (ft)", f"{latest['AGL']}")

    # === Warnings ===
    if latest["CO2"] > 1000:
        st.error(f"⚠️ High CO2 Detected: {latest['CO2']} ppm")
    if latest["PM2.5"] > 35:
        st.warning(f"🌫️ Elevated PM2.5: {latest['PM2.5']} µg/m³")

    # === Latest row table ===
    st.subheader("🧾 Latest Sensor Rows")
    st.dataframe(df.tail(1).reset_index(drop=True), use_container_width=True)

    # === Sensor trends ===
    st.subheader("📈 Sensor Trends")

    def raw_chart_filtered(column_name, threshold=0):
        chart_df = df[df[column_name] > threshold]
        if chart_df.empty:
            st.warning(f"No valid data to plot for {column_name}")
            return None
        return alt.Chart(chart_df).mark_line().encode(
            x=alt.X("Timestamp:T", title="Time"),
            y=alt.Y(f"{column_name}:Q", title=column_name)
        ).properties(title=f"{column_name} Over Time")

    for col in ["CO2", "PM1", "PM2.5", "PM10", "Temp", "Hum"]:
        if col in df.columns:
            chart = raw_chart_filtered(col)
            if chart:
                st.altair_chart(chart, use_container_width=True)

    # === 3D GPS Position Map ===
    st.subheader("📍 3D GPS Position Map (AGL Elevation)")
    map_df = df.dropna(subset=["Lat", "Lon", "AGL"])
    map_df = map_df.astype({"Lat": "float64", "Lon": "float64", "AGL": "float64"})

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
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

# === Set Mapbox Token ===
pdk.settings.mapbox_api_key = st.secrets["MAPBOX_TOKEN"]

try:
    # === Load service account from Streamlit Cloud secrets ===
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    service_account_info = st.secrets["gcp_service_account"].to_dict()
    creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    client = gspread.authorize(creds)

    # === Open sheet ===
    spreadsheet = client.open_by_key("1b_8TWrMPYctgDK6_LNe0LHpWybadBLYf0uNBwBt_sKs")
    worksheet = spreadsheet.worksheet("Live")
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

    # === Filter out GPS (0,0) early ===
    df = df[(df["Lat"] != 0) & (df["Lon"] != 0)]

    # === Detect latest session based on time gaps ===
    df = df.sort_values("Timestamp")
    df["TimeDiff"] = df["Timestamp"].diff().dt.total_seconds().fillna(0)
    gap_threshold = 120  # 2 minutes
    df["BlockID"] = (df["TimeDiff"] > gap_threshold).cumsum()
    latest_block_id = df["BlockID"].iloc[-1]
    df = df[df["BlockID"] == latest_block_id].copy()
    df.drop(columns=["TimeDiff", "BlockID"], inplace=True)

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

    if latest["CO2"] > 1000:
        st.error(f"⚠️ High CO2 Detected: {latest['CO2']} ppm")
    if latest["PM2.5"] > 35:
        st.warning(f"🌫️ Elevated PM2.5: {latest['PM2.5']} µg/m³")

    st.subheader("🧾 Latest Sensor Rows")
    st.dataframe(df.tail(1).reset_index(drop=True), use_container_width=True)

    # === Charts ===
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

    # === 3D Spheres Using ScenegraphLayer with Mapbox Satellite ===
    st.subheader("📍 3D Floating Spheres Color-Coded by PM2.5 AQI")

    map_df = df.dropna(subset=["Lat", "Lon", "PM2.5", "AGL"])
    map_df = map_df.astype({
        "Lat": "float64",
        "Lon": "float64",
        "PM2.5": "float64",
        "AGL": "float64"
    })

    def pm25_to_rgb(pm):
        if pm <= 12:
            return [0, 228, 0]
        elif pm <= 35.4:
            return [255, 255, 0]
        elif pm <= 55.4:
            return [255, 126, 0]
        elif pm <= 150.4:
            return [255, 0, 0]
        elif pm <= 250.4:
            return [143, 63, 151]
        else:
            return [126, 0, 35]

    map_df[["color_r", "color_g", "color_b"]] = map_df["PM2.5"].apply(
        lambda pm: pd.Series(pm25_to_rgb(pm))
    )

    # === Camera control sliders ===
    bearing = st.slider("Map View Bearing", 0, 360, 30)
    pitch = st.slider("Map View Pitch", 0, 90, 60)

    if not map_df.empty:
        layer = pdk.Layer(
            "ScenegraphLayer",
            data=map_df,
            get_position='[Lon, Lat, AGL]',
            scenegraph="https://raw.githubusercontent.com/Sky737YT/AirQualityV3/main/sphere.glb",
            size_scale=20,
            get_color='[color_r, color_g, color_b]',
            pickable=True,
            _animations=False,
        )

        view_state = pdk.ViewState(
            latitude=map_df["Lat"].mean(),
            longitude=map_df["Lon"].mean(),
            zoom=14,
            pitch=pitch,
            bearing=bearing
        )

        r = pdk.Deck(
            map_style="mapbox://styles/sky737/cmdlzoqfg006001s29a636diz",
            layers=[layer],
            initial_view_state=view_state,
            tooltip={"text": "PM2.5: {PM2.5} µg/m³\nAGL: {AGL} ft"}
        )
        st.pydeck_chart(r)

        st.markdown("### 🗘️ AQI Color Legend (PM2.5)")
        st.markdown("""
        <div style='display: flex; gap: 16px; flex-wrap: wrap;'>
            <div style='background-color: rgb(0,228,0); width: 20px; height: 20px; display: inline-block;'></div> Good (≤12)
            <div style='background-color: rgb(255,255,0); width: 20px; height: 20px; display: inline-block;'></div> Moderate (12.1–35.4)
            <div style='background-color: rgb(255,126,0); width: 20px; height: 20px; display: inline-block;'></div> Unhealthy for Sensitive Groups (35.5–55.4)
            <div style='background-color: rgb(255,0,0); width: 20px; height: 20px; display: inline-block;'></div> Unhealthy (55.5–150.4)
            <div style='background-color: rgb(143,63,151); width: 20px; height: 20px; display: inline-block;'></div> Very Unhealthy (150.5–250.4)
            <div style='background-color: rgb(126,0,35); width: 20px; height: 20px; display: inline-block;'></div> Hazardous (>250.4)
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("No GPS data to show on the map yet.")

except Exception as e:
    st.error(f"❌ Failed to load data: {e}")
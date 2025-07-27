import streamlit as st
import pandas as pd
import pydeck as pdk
import altair as alt
from streamlit_autorefresh import st_autorefresh
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# === Auto-refresh every 5 seconds ===
st_autorefresh(interval=5000, key="datarefresh")

# === Page Config ===
st.set_page_config(page_title="📡 LoRa Air Quality", layout="wide")
st.title("📡 Real-Time LoRa Air Quality Dashboard")
st.caption("Auto-refreshes every 5 seconds from Google Sheets")

# === Map Style (Carto Dark) ===
map_style = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"

# === Google Sheets Auth ===
scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
credentials = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"], scopes=scopes
)
client = gspread.authorize(credentials)

# === Load Data ===
SHEET_NAME = "LoRaData"
worksheet = client.open(SHEET_NAME).sheet1
data = worksheet.get_all_records()
df = pd.DataFrame(data)

# === Time Filter ===
df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
latest_time = df["Timestamp"].max()
cutoff = latest_time - timedelta(minutes=5)
df = df[df["Timestamp"] >= cutoff]
df = df[(df["Lat"] != 0) & (df["Lon"] != 0)]

# === AQI Color Logic ===
def aqi_color(pm25):
    if pm25 <= 12:
        return [0, 228, 0]
    elif pm25 <= 35.4:
        return [255, 255, 0]
    elif pm25 <= 55.4:
        return [255, 126, 0]
    elif pm25 <= 150.4:
        return [255, 0, 0]
    elif pm25 <= 250.4:
        return [143, 63, 151]
    else:
        return [126, 0, 35]

df["color"] = df["PM2.5"].apply(aqi_color)

# === View Controls ===
st.sidebar.title("🛰 View Controls")
bearing = st.sidebar.slider("Bearing", 0, 360, 0)
pitch = st.sidebar.slider("Pitch", 0, 90, 45)

# === Pydeck Layer (3D scatter) ===
layer = pdk.Layer(
    "ScatterplotLayer",
    data=df,
    get_position='[Lon, Lat]',
    get_fill_color='color',
    get_radius=200,
    pickable=True,
    auto_highlight=True,
)

# === View State ===
view_state = pdk.ViewState(
    latitude=df["Lat"].mean(),
    longitude=df["Lon"].mean(),
    zoom=13,
    pitch=pitch,
    bearing=bearing,
)

# === Display Map ===
st.pydeck_chart(
    pdk.Deck(
        map_style=map_style,
        initial_view_state=view_state,
        layers=[layer],
        tooltip={"text": "PM2.5: {PM2.5}\nLat: {Lat}, Lon: {Lon}"}
    )
)

# === Legend ===
st.markdown("### 🌫 PM2.5 AQI Legend")
st.markdown("""
- 🟢 **0–12**: Good  
- 🟡 **12.1–35.4**: Moderate  
- 🟠 **35.5–55.4**: Unhealthy for Sensitive Groups  
- 🔴 **55.5–150.4**: Unhealthy  
- 🟣 **150.5–250.4**: Very Unhealthy  
- 🟤 **250.5+**: Hazardous
""")
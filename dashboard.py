import streamlit as st
import pandas as pd
import pydeck as pdk
import altair as alt
from streamlit_autorefresh import st_autorefresh
import gspread
from google.oauth2.service_account import Credentials
import time
import simplekml
from io import BytesIO

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

    # === Open sheet ===
    spreadsheet = client.open_by_key("1b_8TWrMPYctgDK6_LNe0LHpWybadBLYf0uNBwBt_sKs")
    worksheet = spreadsheet.worksheet("Live")
    data = worksheet.get_all_values()
    headers = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=headers)
    st.write("Columns in sheet:", df.columns.tolist())


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
        st.warning(f"⚠️ Elevated PM2.5: {latest['PM2.5']} µg/m³")

    st.subheader("🧾 Latest Sensor Rows")
    st.dataframe(df.tail(1).reset_index(drop=True), use_container_width=True)

    # === Charts ===
    st.subheader("📈 Sensor Trends")

    def raw_chart_filtered(column_name, threshold=0):
        # Friendly display names
        label_map = {
            "Temp": "Temperature (°F)",
            "Hum": "Humidity (%)",
            "CO2": "CO2 (ppm)",
            "PM1": "PM1 (µg/m³)",
            "PM2.5": "PM2.5 (µg/m³)",
            "PM10": "PM10 (µg/m³)"
        }

        chart_df = df[df[column_name] > threshold]
        if chart_df.empty:
            st.warning(f"No valid data to plot for {label_map.get(column_name, column_name)}")
            return None

        display_name = label_map.get(column_name, column_name)

        return alt.Chart(chart_df).mark_line().encode(
            x=alt.X("Timestamp:T", title="Time"),
            y=alt.Y(f"{column_name}:Q", title=display_name)
        ).properties(title=f"{display_name} Over Time")

    for col in ["CO2", "PM1", "PM2.5", "PM10", "Temp", "Hum"]:
        if col in df.columns:
            chart = raw_chart_filtered(col)
            if chart:
                st.altair_chart(chart, use_container_width=True)


    # === 3D Spheres Using ScenegraphLayer ===
    st.subheader("📍 3D PM2.5 AQI Map")

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

    co2_df = df.dropna(subset=["Lat", "Lon", "CO2", "AGL"]).astype({
        "Lat": "float64",
        "Lon": "float64",
        "CO2": "float64",
        "AGL": "float64"
    })

    def co2_to_rgb(co2):
        if co2 <= 600:
            return [0, 200, 0]
        elif co2 <= 1000:
            return [255, 255, 0]
        elif co2 <= 1500:
            return [255, 126, 0]
        elif co2 <= 2000:
            return [255, 0, 0]
        elif co2 <= 5000:
            return [143, 63, 151]
        else:
            return [126, 0, 35]

    co2_df[["color_r", "color_g", "color_b"]] = co2_df["CO2"].apply(lambda x: pd.Series(co2_to_rgb(x)))

    if not map_df.empty or not co2_df.empty:
        # PM2.5 Map
        layer_pm = pdk.Layer(
            "ScenegraphLayer",
            data=map_df,
            get_position='[Lon, Lat, AGL]',
            scenegraph="https://raw.githubusercontent.com/Sky737YT/AirQualityV3/main/sphere.glb",
            size_scale=1.5,
            get_color='[color_r, color_g, color_b]',
            pickable=True,
            _animations=False,
        )

        view_state = pdk.ViewState(
            latitude=map_df["Lat"].mean(),
            longitude=map_df["Lon"].mean(),
            zoom=17,
            pitch=60,
            bearing=30
        )

        st.pydeck_chart(pdk.Deck(
            layers=[layer_pm],
            initial_view_state=view_state,
            tooltip={"text": "PM2.5: {PM2.5} µg/m³\nAGL: {AGL} ft"}
        ))

        st.markdown("### AQI Color Legend (PM2.5)")
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
        st.subheader("")
        # CO2 Map
        st.subheader("📍 3D CO2 Map")

        layer_co2 = pdk.Layer(
            "ScenegraphLayer",
            data=co2_df,
            get_position='[Lon, Lat, AGL]',
            scenegraph="https://raw.githubusercontent.com/Sky737YT/AirQualityV3/main/sphere.glb",
            size_scale=1.5,
            get_color='[color_r, color_g, color_b]',
            pickable=True,
            _animations=False,
        )

        view_state_co2 = pdk.ViewState(
            latitude=co2_df["Lat"].mean(),
            longitude=co2_df["Lon"].mean(),
            zoom=17,
            pitch=60,
            bearing=30
        )

        st.pydeck_chart(pdk.Deck(
            layers=[layer_co2],
            initial_view_state=view_state_co2,
            tooltip={"text": "CO2: {CO2} ppm\nAGL: {AGL} ft"}
        ))

        st.markdown("### CO2 Color Legend (ppm)")
        st.markdown("""
        <div style='display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 1em;'>
            <div style='background-color: rgb(0,200,0); width: 20px; height: 20px; display: inline-block;'></div> Normal (≤600)
            <div style='background-color: rgb(255,255,0); width: 20px; height: 20px; display: inline-block;'></div> Moderate (601–1000)
            <div style='background-color: rgb(255,126,0); width: 20px; height: 20px; display: inline-block;'></div> Elevated (1001–1500)
            <div style='background-color: rgb(255,0,0); width: 20px; height: 20px; display: inline-block;'></div> High (1501–2000)
            <div style='background-color: rgb(143,63,151); width: 20px; height: 20px; display: inline-block;'></div> Very High (2001–5000)
            <div style='background-color: rgb(126,0,35); width: 20px; height: 20px; display: inline-block;'></div> Dangerous (>5000)
        </div>
        """, unsafe_allow_html=True)
        st.subheader("")
        # === DOWNLOAD SECTION ===
        st.subheader("📥 Last Session Downloads")

        # PM2.5 KML
        def pm25_to_kml_color(pm):
            if pm <= 12:
                return simplekml.Color.rgb(0, 228, 0)
            elif pm <= 35.4:
                return simplekml.Color.rgb(255, 255, 0)
            elif pm <= 55.4:
                return simplekml.Color.rgb(255, 126, 0)
            elif pm <= 150.4:
                return simplekml.Color.rgb(255, 0, 0)
            elif pm <= 250.4:
                return simplekml.Color.rgb(143, 63, 151)
            else:
                return simplekml.Color.rgb(126, 0, 35)

        kml_pm = simplekml.Kml()
        for _, row in map_df.iterrows():
            pnt = kml_pm.newpoint(coords=[(row["Lon"], row["Lat"])])
            pnt.altitude = row["AGL"]
            pnt.altitudemode = simplekml.AltitudeMode.relativetoground
            pnt.extrude = 1
            pnt.description = f"PM2.5: {row['PM2.5']} µg/m³\nAGL: {row['AGL']} ft"
            pnt.style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/shaded_dot.png"
            pnt.style.iconstyle.color = pm25_to_kml_color(row["PM2.5"])

        kml_io_pm = BytesIO(kml_pm.kml().encode("utf-8"))

        # CO2 KML
        def co2_to_kml_color(co2):
            if co2 <= 600:
                return simplekml.Color.rgb(0, 200, 0)
            elif co2 <= 1000:
                return simplekml.Color.rgb(255, 255, 0)
            elif co2 <= 1500:
                return simplekml.Color.rgb(255, 126, 0)
            elif co2 <= 2000:
                return simplekml.Color.rgb(255, 0, 0)
            elif co2 <= 5000:
                return simplekml.Color.rgb(143, 63, 151)
            else:
                return simplekml.Color.rgb(126, 0, 35)

        kml_co2 = simplekml.Kml()
        for _, row in co2_df.iterrows():
            pnt = kml_co2.newpoint(coords=[(row["Lon"], row["Lat"])])
            pnt.altitude = row["AGL"]
            pnt.altitudemode = simplekml.AltitudeMode.relativetoground
            pnt.extrude = 1
            pnt.description = f"CO2: {row['CO2']} ppm\nAGL: {row['AGL']} ft"
            pnt.style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/shaded_dot.png"
            pnt.style.iconstyle.color = co2_to_kml_color(row["CO2"])

        kml_io_co2 = BytesIO(kml_co2.kml().encode("utf-8"))

        st.download_button(
            label="📄 Download PM2.5 .KML",
            data=kml_io_pm,
            file_name="pm25_session.kml",
            mime="application/vnd.google-earth.kml+xml"
            )
        
        st.download_button(
            label="📄 Download CO2 .KML",
            data=kml_io_co2,
            file_name="co2_session.kml",
            mime="application/vnd.google-earth.kml+xml"
            )

except Exception as e:
    st.error(f"❌ Failed to load data: {e}")
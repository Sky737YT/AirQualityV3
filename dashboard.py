import streamlit as st
import pandas as pd
import pydeck as pdk
import altair as alt
import numpy as np
from math import sin, cos, radians
from streamlit_autorefresh import st_autorefresh
import gspread
from google.oauth2.service_account import Credentials
import time
import simplekml
import re
import requests
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
    

    # === Clean & convert ===
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"])

    for col in ["Lat", "Lon", "AGL", "CO2", "PM2_5", "PM1", "PM10", "Temp", "Hum"]:
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
    col3.metric("PM2.5 (µg/m³)", f"{latest['PM2_5']}")
    col4.metric("CO2 (ppm)", f"{latest['CO2']}")
    col5.metric("Altitude AGL (ft)", f"{latest['AGL']}")

    if latest["CO2"] > 1000:
        st.error(f"⚠️ High CO2 Detected: {latest['CO2']} ppm")
    if latest["PM2_5"] > 55.5:
        st.error(f"⚠️ High PM2.5 Detected: {latest['PM2_5']} µg/m³")

    st.subheader("🧾 Latest Sensor Rows")
    st.dataframe(df.tail(1).reset_index(drop=True), use_container_width=True)

    # === Charts ===
    st.subheader("📈 Sensor Trends")

    def raw_chart_filtered(column_name, threshold=-1):
        # Friendly display names
        label_map = {
            "Temp": "Temperature (°F)",
            "Hum": "Humidity (%)",
            "CO2": "CO2 (ppm)",
            "PM1": "PM1 (µg/m³)",
            "PM2_5": "PM2.5 (µg/m³)",
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

    for col in ["CO2", "PM1", "PM2_5", "PM10", "Temp", "Hum"]:
        if col in df.columns:
            chart = raw_chart_filtered(col)
            if chart:
                st.altair_chart(chart, use_container_width=True)


    # === 3D Spheres Using ScenegraphLayer ===
    st.subheader("📍 3D PM2.5 AQI Map")

    map_df = df.dropna(subset=["Lat", "Lon", "PM2_5", "AGL"])
    map_df = map_df.astype({
        "Lat": "float64",
        "Lon": "float64",
        "PM2_5": "float64",
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

    map_df[["color_r", "color_g", "color_b"]] = map_df["PM2_5"].apply(
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
            tooltip={"text": "PM2.5: {PM2_5} µg/m³\nAGL: {AGL} ft"}
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
            pnt.description = f"PM2.5: {row['PM2_5']} µg/m³\nAGL: {row['AGL']} ft"
            pnt.style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/shaded_dot.png"
            pnt.style.iconstyle.color = pm25_to_kml_color(row["PM2_5"])

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
    # === WIND‑WEIGHTED DISPERSION (CO₂ + PM2.5) ===
    st.subheader("💨 Wind‑Weighted Dispersion (CO₂ + PM2.5)")

    # ---------- Utilities ----------
    @st.cache_data(ttl=120)
    def fetch_metar(icao: str) -> str | None:
        """Fetch latest METAR for an ICAO from NOAA TGFTP."""
        icao = (icao or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{4}", icao):
            return None
        url = f"https://tgftp.nws.noaa.gov/data/observations/metar/stations/{icao}.TXT"
        try:
            r = requests.get(url, timeout=4)
            if r.status_code == 200:
                lines = r.text.strip().splitlines()
                if len(lines) >= 2:
                    return lines[1].strip()
        except Exception:
            return None
        return None

    def parse_wind_from_metar(metar: str) -> tuple[int | None, float | None]:
        """
        Parse wind direction (deg FROM) and speed (m/s) from METAR.
        Handles '22012KT', 'VRB03KT', '18012G20KT'.
        """
        if not metar:
            return None, None
        m = re.search(r"\b(VRB|\d{3})(\d{2,3})(G\d{2,3})?KT\b", metar)
        if not m:
            return None, None
        d, s = m.group(1), m.group(2)
        wind_dir = None if d == "VRB" else int(d)
        wind_ms = round(int(s) * 0.514444, 2)  # kt -> m/s
        return wind_dir, wind_ms

    def haversine_km(lat1, lon1, lat2, lon2):
        R = 6371.0
        p1, p2 = np.radians(lat1), np.radians(lat2)
        dlat = np.radians(lat2 - lat1)
        dlon = np.radians(lon2 - lon1)
        a = np.sin(dlat/2)**2 + np.cos(p1)*np.cos(p2)*np.sin(dlon/2)**2
        return 2 * R * np.arcsin(np.sqrt(a))

    def meters_to_latlon(d_north_m, d_east_m, lat0):
        # Rough local ENU→LLA for small distances
        dlat = d_north_m / 111320.0
        dlon = d_east_m / (40075000.0 * np.cos(np.radians(lat0)) / 360.0)
        return dlat, dlon

    def simulate_plume(points, wind_deg, wind_ms, horizon_min=15, step_s=10,
                    base_sigma_m=15, spread_per_km=40, decay_half_life_min=12):
        """
        points: list of dicts with keys: lat, lon, strength (unitless hazard)
        wind_deg: meteo direction FROM which wind blows (0 = from North)
        wind_ms: wind speed (m/s)
        Early‑stops when strength decays below eps.
        """
        if wind_ms <= 0 or not points:
            return []
        # FROM -> TO
        to_deg = (wind_deg + 180.0) % 360.0
        th = radians(to_deg)
        vx, vy = wind_ms * sin(th), wind_ms * cos(th)  # x=east, y=north
        steps = int((horizon_min * 60) / step_s)
        lam = np.log(2) / (decay_half_life_min * 60.0) if decay_half_life_min > 0 else 0.0

        out = []
        eps = 0.02  # relevance cutoff
        for p in points:
            lat0, lon0, s0 = p["lat"], p["lon"], max(0.0, float(p["strength"]))
            if s0 <= 0:
                continue
            for k in range(1, steps + 1):
                t = k * step_s
                s_now = s0 * (np.exp(-lam * t) if lam > 0 else 1.0)
                if s_now < eps:
                    break  # no longer relevant
                dx, dy = vx * t, vy * t
                down_m = np.hypot(dx, dy)
                sigma_y = base_sigma_m + (down_m / 1000.0) * spread_per_km
                # Crosswind rays
                for cw in np.linspace(-2.5, 2.5, 11):
                    cross = cw * sigma_y
                    px, py = -vy / (wind_ms or 1e-9), vx / (wind_ms or 1e-9)
                    ex, ey = dx + cross * px, dy + cross * py
                    dlat, dlon = meters_to_latlon(ey, ex, lat0)
                    cross_w = np.exp(-0.5 * (cross / sigma_y) ** 2)
                    out.append({"lat": lat0 + dlat, "lon": lon0 + dlon, "strength": s_now * cross_w})
        return out

    # ---------- Auto‑select relevant METAR by location ----------
    # Center of your current session
    if not df.empty and {"Lat", "Lon"}.issubset(df.columns):
        center_lat = float(df["Lat"].mean())
        center_lon = float(df["Lon"].mean())
    else:
        center_lat, center_lon = 39.8729, -75.2437  # fallback near KPHL

    # Small built‑in station set (add more as you travel)
    STATIONS = [
        # Mid‑Atlantic / Northeast core (you can extend this list)
        ("KPHL", 39.872, -75.243), ("KPNE", 40.083, -75.016), ("KTTN", 40.277, -74.813),
        ("KILG", 39.678, -75.606), ("KACY", 39.457, -74.578), ("KABE", 40.652, -75.440),
        ("KMDT", 40.194, -76.763), ("KRDG", 40.378, -75.965),
        ("KEWR", 40.692, -74.169), ("KJFK", 40.639, -73.778), ("KLGA", 40.777, -73.872), ("KTEB", 40.851, -74.060),
        ("KHPN", 41.067, -73.707), ("KISP", 40.795, -73.100), ("KSWF", 41.504, -74.105),
        ("KBWI", 39.175, -76.668), ("KDCA", 38.852, -77.037), ("KIAD", 38.944, -77.456),
        ("KALB", 42.748, -73.803), ("KBOS", 42.362, -71.006), ("KBDL", 41.938, -72.683), ("KPVD", 41.723, -71.427),
        ("KROC", 43.119, -77.672), ("KBUF", 42.940, -78.732), ("KSYR", 43.112, -76.106),
        ("KPIT", 40.492, -80.232), ("KCMH", 39.998, -82.891), ("KDTW", 42.213, -83.353), ("KCLE", 41.412, -81.849)
    ]

    # Pick nearest from built‑in list
    nearest_icao, nearest_dist = None, 1e9
    for icao, la, lo in STATIONS:
        d = haversine_km(center_lat, center_lon, la, lo)
        if d < nearest_dist:
            nearest_dist, nearest_icao = d, icao

    # UI: allow override & extra stations
    ccA, ccB = st.columns([2, 3])
    with ccA:
        custom_icao = st.text_input("Override ICAO (optional)", value="")
    with ccB:
        extra_icaos = st.text_input("Extra ICAOs (comma‑sep, optional)", value="")

    candidate_icaos = [custom_icao.strip().upper()] if custom_icao.strip() else [nearest_icao]
    if extra_icaos.strip():
        candidate_icaos += [x.strip().upper() for x in extra_icaos.split(",") if x.strip()]

    # Try candidates in order until one returns data
    metar_text, metar_used = None, None
    for candidate in candidate_icaos:
        if not candidate:
            continue
        m = fetch_metar(candidate)
        if m:
            metar_text, metar_used = m, candidate
            break

    # ---------- Wind inputs (METAR‑aware, but editable) ----------
    cc1, cc2, cc3 = st.columns([2, 2, 6])
    with cc1:
        use_metar = st.checkbox("Use METAR wind", value=True)
    with cc2:
        st.caption(f"Nearest station: **{nearest_icao or 'N/A'}** (~{nearest_dist:.1f} km)")
    with cc3:
        if metar_text:
            st.caption(f"METAR {metar_used}: {metar_text}")
        else:
            st.caption("No METAR fetched (check ICAO/network or add extra ICAOs).")

    m_dir, m_ms = parse_wind_from_metar(metar_text) if (use_metar and metar_text) else (None, None)

    cc4, cc5, cc6, cc7 = st.columns(4)
    with cc4:
        wind_dir_deg = st.number_input(
            "Wind Dir (° FROM)", min_value=0, max_value=359,
            value=(m_dir if isinstance(m_dir, int) else st.session_state.get("wind_dir_deg", 270)),
            help="Meteorological direction the wind is coming FROM"
        )
    with cc5:
        wind_ms = st.number_input(
            "Wind Speed (m/s)", min_value=0.0, step=0.5,
            value=(m_ms if isinstance(m_ms, float) else st.session_state.get("wind_ms", 3.0))
        )
    with cc6:
        horizon_min = st.slider("Forecast Horizon (min)", 5, 45, st.session_state.get("horizon_min", 15))
    with cc7:
        decay_t12 = st.slider("Half-life (min)", 5, 60, st.session_state.get("decay_t12", 12),
                            help="Decay of anomaly over time")

    cc8, cc9, cc10, cc11 = st.columns(4)
    with cc8:
        bg_co2 = st.number_input("Background CO₂ (ppm)", min_value=350, max_value=600, value=420)
    with cc9:
        bg_pm  = st.number_input("Background PM2.5 (µg/m³)", min_value=0.0, value=8.0, step=0.5)
    with cc10:
        w_co2 = st.slider("Weight: CO₂", 0.0, 1.0, 0.6)
    with cc11:
        w_pm  = st.slider("Weight: PM2.5", 0.0, 1.0, 0.4)

    # Persist last chosen values to reduce flicker
    st.session_state["wind_dir_deg"] = wind_dir_deg
    st.session_state["wind_ms"] = wind_ms
    st.session_state["horizon_min"] = horizon_min
    st.session_state["decay_t12"] = decay_t12

    # Normalize weights
    w_sum = max(1e-6, (w_co2 + w_pm))
    w_co2, w_pm = w_co2 / w_sum, w_pm / w_sum

    # ---------- Emitters from *recent* anomalies (skip if normal) ----------
    emitters = []
    plume_df = pd.DataFrame(columns=["lat","lon","strength"])

    recent_seconds = 60  # only consider last minute for "active" plume
    if not df.empty and {"Lat","Lon","CO2","PM2_5","Timestamp"}.issubset(df.columns):
        cutoff = df["Timestamp"].max() - pd.Timedelta(seconds=recent_seconds)
        dd = df[df["Timestamp"] >= cutoff].copy()
        if dd.empty:
            dd = df.tail(50).copy()

        dd["co2_excess"] = (dd["CO2"] - bg_co2).clip(lower=0)
        dd["pm_excess"]  = (dd["PM2_5"] - bg_pm).clip(lower=0)
        # Scale to comparable magnitudes
        dd["co2_scaled"] = dd["co2_excess"] / 200.0
        dd["pm_scaled"]  = dd["pm_excess"]  / 35.0
        dd["hazard"] = w_co2 * dd["co2_scaled"] + w_pm * dd["pm_scaled"]

        if dd["hazard"].max() >= 0.08:
            dd = dd[(dd["hazard"] > 0.1) & dd["Lat"].notna() & dd["Lon"].notna()].tail(80)
            for _, r in dd.iterrows():
                emitters.append({"lat": float(r["Lat"]), "lon": float(r["Lon"]), "strength": float(r["hazard"])})

    # ---------- Simulate + render ----------
    if emitters:
        plume_pts = simulate_plume(
            emitters,
            wind_deg=wind_dir_deg,
            wind_ms=wind_ms,
            horizon_min=horizon_min,
            step_s=10,
            base_sigma_m=15,
            spread_per_km=40,
            decay_half_life_min=decay_t12
        )
        plume_df = pd.DataFrame(plume_pts)

    if not plume_df.empty:
        plume_layer = pdk.Layer(
            "HeatmapLayer",
            data=plume_df,
            get_position='[lon, lat]',
            get_weight="strength",
            radius_pixels=50,
            intensity=1.0,
            threshold=0.02,
            aggregation='"SUM"'
        )

        # Center on existing CO2/PM map center if available, else session center
        if 'co2_df' in locals() and not co2_df.empty:
            center_lat, center_lon = float(co2_df["Lat"].mean()), float(co2_df["Lon"].mean())
        elif 'map_df' in locals() and not map_df.empty:
            center_lat, center_lon = float(map_df["Lat"].mean()), float(map_df["Lon"].mean())

        view_state_plume = pdk.ViewState(
            latitude=center_lat,
            longitude=center_lon,
            zoom=16,
            pitch=55,
            bearing=30
        )

        st.pydeck_chart(pdk.Deck(
            layers=[plume_layer],
            initial_view_state=view_state_plume,
            tooltip={"text": "Plume Hazard Index (unitless): {strength}"}
        ))
        st.info("Plume shows a **combined hazard** (CO₂+PM2.5) advected by wind. It auto‑stops once anomalies decay.")
    else:
        st.warning("No significant anomalies to forecast (conditions normal or insufficient recent data).")
    # === /WIND‑WEIGHTED DISPERSION ===
except Exception as e:
    st.error(f"❌ Failed to load data: {e}")
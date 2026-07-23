import json
import requests
import streamlit as st
import streamlit.components.v1 as components

API_BASE = "http://127.0.0.1:8000/api"

st.set_page_config(
    page_title="Transit Journey Planner",
    page_icon="🚌",
    layout="wide",
)

# ── Data helpers ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=600)
def load_all_stops():
    try:
        r = requests.get(f"{API_BASE}/stops-list/", timeout=20)
        return r.json().get('stops', [])
    except Exception:
        return []

def plan_journey(start_id, end_id, modes):
    try:
        r = requests.get(
            f"{API_BASE}/journey/",
            params={'start': start_id, 'end': end_id, 'modes': ','.join(modes)},
            timeout=20,
        )
        return r.json()
    except Exception as e:
        return {'available': False, 'options': [], 'message': f'Planner error: {e}'}

# ── Live map (Leaflet in an iframe that polls the API itself) ──────────────────
# The whole point: bus markers refresh via JS setInterval INSIDE this iframe, so
# the Streamlit page never reruns/flickers when buses move.
MAP_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    html, body { margin:0; font-family: system-ui, sans-serif; }
    #map { height: 520px; border-radius: 12px; }
    #status { font-size: 12px; padding: 6px 4px; color:#444; }
  </style>
</head>
<body>
  <div id="map"></div>
  <div id="status">Loading live buses…</div>
  <script>
    const CFG = __CFG__;
    const map = L.map('map');
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(map);

    const legColors = ['#1976D2', '#E65100', '#6A1B9A'];
    let allPts = [];
    (CFG.legs || []).forEach((leg, i) => {
      if (!leg.geometry || !leg.geometry.length) return;
      const isWalk = leg.mode === 'walk';
      const color = isWalk ? '#777' : (leg.mode === 'metro' ? '#6A1B9A' : legColors[i % legColors.length]);
      L.polyline(leg.geometry, {
        color: color, weight: isWalk ? 4 : 6, opacity: 0.85,
        dashArray: isWalk ? '5,9' : null
      }).addTo(map);
      leg.geometry.forEach(pt => allPts.push(pt));
      if (!isWalk) {
        leg.geometry.forEach(pt =>
          L.circleMarker(pt, { radius: 3, color: color, fill: true, fillOpacity: 0.9 }).addTo(map));
      }
    });

    if (CFG.start) {
      L.marker(CFG.start).addTo(map).bindPopup('<b>Start</b><br>' + CFG.start_name);
    }
    if (CFG.end) {
      L.marker(CFG.end).addTo(map).bindPopup('<b>Destination</b><br>' + CFG.end_name);
    }
    if (allPts.length) { map.fitBounds(allPts, { padding: [30, 30] }); }
    else { map.setView([28.63, 77.22], 11); }

    // Live buses — updated in place, no page reload.
    const busIcon = L.divIcon({
      html: '<div style="font-size:22px;transform:translate(-11px,-11px)">🚌</div>',
      className: '', iconSize: [22, 22]
    });
    const busLayer = L.layerGroup().addTo(map);

    async function refreshBuses() {
      if (!CFG.route_ids || !CFG.route_ids.length) return;
      try {
        busLayer.clearLayers();
        let count = 0;
        for (const rid of CFG.route_ids) {
          const resp = await fetch(CFG.api + '/vehicles/?route_id=' + rid + '&demo=' + CFG.demo);
          const data = await resp.json();
          (data.vehicles || []).forEach(b => {
            L.marker([b.lat, b.lon], { icon: busIcon }).addTo(busLayer)
             .bindPopup('🚌 <b>' + (b.label || b.vehicle_id) + '</b><br>Route ' + rid +
                        '<br>' + (b.speed_kmh != null ? b.speed_kmh + ' km/h' : ''));
            count++;
          });
        }
        const tag = CFG.demo === 'true' ? '🟠 DEMO' : '🔴 LIVE';
        document.getElementById('status').textContent =
          tag + ' • ' + count + ' bus(es) • updated ' + new Date().toLocaleTimeString();
      } catch (e) {
        document.getElementById('status').textContent = 'Live update failed: ' + e;
      }
    }
    refreshBuses();
    setInterval(refreshBuses, (CFG.interval || 8) * 1000);
  </script>
</body>
</html>
"""

def render_live_map(cfg):
    html = MAP_TEMPLATE.replace('__CFG__', json.dumps(cfg))
    components.html(html, height=580)

# ── Delay-in-words styling ────────────────────────────────────────────────────
SEVERITY_STYLE = {
    'ok':       ('#1B5E20', '#E8F5E9', '✅'),
    'minor':    ('#E65100', '#FFF3E0', '⚠️'),
    'moderate': ('#E65100', '#FFF3E0', '⚠️'),
    'severe':   ('#B71C1C', '#FFEBEE', '🔴'),
}

def delay_badge(option):
    color, bg, icon = SEVERITY_STYLE.get(option['delay_severity'], SEVERITY_STYLE['minor'])
    return (
        f"<span style='background:{bg};color:{color};padding:2px 10px;"
        f"border-radius:12px;font-weight:600;font-size:13px'>"
        f"{icon} {option['delay_text']}</span>"
    )

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 🚌 Delhi Transit Journey Planner")
st.caption("Pick a start and destination — get the best bus route, live times, and an ML-predicted delay.")

stops = load_all_stops()
if not stops:
    st.error("Could not load stops. Is the Django backend running on :8000?")
    st.stop()

# Build searchable labels (names repeat, so disambiguate with the stop id).
label_to_stop = {f"{s['stop_name']}  ·  #{s['stop_id']}": s for s in stops}
labels = list(label_to_stop.keys())

def default_index(keyword, fallback):
    for i, lab in enumerate(labels):
        if keyword.lower() in lab.lower():
            return i
    return fallback

def index_by_id(stop_id, fallback):
    tag = f"#{stop_id}"
    for i, lab in enumerate(labels):
        if lab.endswith(tag):
            return i
    return fallback

# ── SIDEBAR: trip planner ─────────────────────────────────────────────────────
with st.sidebar:
    st.header("🧭 Plan your trip")

    modes = st.multiselect(
        "Mode", ["🚌 Bus", "🚆 Train"], default=["🚌 Bus"],
        help="Pick Bus, Train, or both. Train/Metro data isn't loaded yet.",
    )
    want_bus = any("Bus" in m for m in modes)
    want_train = any("Train" in m for m in modes)

    # Defaults land on a known-connected demo pair (route 828A).
    start_label = st.selectbox("🟢 Start stop", labels,
                               index=index_by_id("146", default_index("terminal", 0)))
    end_label = st.selectbox("🔴 Destination stop", labels,
                             index=index_by_id("2177", default_index("galib pur", 1)))
    start_stop = label_to_stop[start_label]
    end_stop = label_to_stop[end_label]

    go = st.button("🔍 Find routes", type="primary", use_container_width=True)

    sel_modes = []
    if want_bus:
        sel_modes.append("bus")
    if want_train:
        sel_modes.append("metro")
    if not sel_modes:
        sel_modes = ["bus"]

    if go or "journey" not in st.session_state:
        st.session_state["journey"] = plan_journey(
            start_stop["stop_id"], end_stop["stop_id"], sel_modes
        )
        st.session_state["sel_option"] = 0
    result = st.session_state["journey"]

    # If metro was requested but isn't loaded, the backend silently drops it.
    if (want_train and result.get("available")
            and "metro" not in (result.get("modes") or [])):
        st.caption("🚇 Metro data not loaded yet — showing bus routes. "
                   "Add the DMRC GTFS to enable trains.")

    # ── Route options + journey cards ─────────────────────────────────────────
    if not result.get("available"):
        st.warning(result.get("message", "No journey available."))
    elif not result.get("options"):
        st.info(result.get("message", "No route found between these stops."))
    else:
        conditions = result.get("weather") or {}
        traffic = result.get("traffic") or {}
        st.caption(
            f"Delay model inputs → {conditions.get('weather_condition', '?')}, "
            f"{conditions.get('temperature', '?')}°C, "
            f"traffic: {(traffic or {}).get('traffic_level', 'n/a')}"
        )

        options = result["options"]
        st.caption("👇 Tap a route to show it on the map")
        pick = st.session_state.get("sel_option", 0)
        if pick >= len(options):
            pick = 0
        st.session_state["sel_option"] = pick

        for idx, opt in enumerate(options):
            border = "2px solid #1976D2" if idx == pick else "1px solid #ddd"
            legs_html = ""
            prev_mode = None
            for leg in opt["legs"]:
                mode = leg.get("mode")
                if mode == "walk":
                    legs_html += (
                        f"<div style='margin:3px 0;color:#666;font-size:12px'>"
                        f"🚶 <b>Walk {leg['ride_minutes']} min</b> — "
                        f"{leg['board_stop_name']} → {leg['alight_stop_name']}</div>"
                    )
                else:
                    # Same-stop transfer between two rides (no walk in between).
                    if prev_mode in ("bus", "metro"):
                        legs_html += (
                            f"<div style='color:#888;font-size:12px;margin:2px 0'>"
                            f"↳ transfer at {leg['board_stop_name']}</div>"
                        )
                    badge_bg = "#6A1B9A" if mode == "metro" else "#1976D2"
                    legs_html += (
                        f"<div style='margin:3px 0'>"
                        f"<span style='background:{badge_bg};color:white;padding:1px 8px;"
                        f"border-radius:4px;font-weight:700;font-size:13px'>"
                        f"{leg.get('icon', '🚌')} {leg['route_label']}</span> "
                        f"<span style='color:#888;font-size:12px'>"
                        f"{leg['board_stop_name']} → {leg['alight_stop_name']} "
                        f"({leg['num_stops']} stops, ~{leg['ride_minutes']} min, "
                        f"every {leg['headway_min']} min)</span></div>"
                    )
                prev_mode = mode
            n_x = opt["transfers"]
            tag = "DIRECT" if n_x == 0 else f"{n_x} TRANSFER" + ("S" if n_x > 1 else "")
            st.markdown(
                f"<div style='border:{border};border-radius:12px;padding:10px;margin-bottom:10px'>"
                f"<div style='display:flex;justify-content:space-between;align-items:center'>"
                f"<span style='font-size:18px;font-weight:700'>{opt['depart']} → {opt['arrive']}</span>"
                f"<span style='color:#888;font-size:12px'>{opt['scheduled_minutes']} min · {tag}</span></div>"
                f"{legs_html}"
                f"<div style='margin-top:8px'>{delay_badge(opt)} "
                f"<span style='color:#888;font-size:12px'>· ETA "
                f"<b>{opt['arrive_predicted']}</b></span></div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button(
                "✅ Showing on map" if idx == pick else "Show this route on map",
                key=f"routeopt_{idx}",
                use_container_width=True,
                type="primary" if idx == pick else "secondary",
            ):
                st.session_state["sel_option"] = idx
                st.rerun()

# ── SIDEBAR (bottom): settings ────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.subheader("⚙️ Settings")
    demo_mode = st.checkbox(
        "Demo buses (simulated)", value=True,
        help="Shows buses moving along the route without an API key. "
             "Uncheck once OTD_API_KEY is set for real live tracking.",
    )
    interval = st.slider("Live refresh (sec)", 5, 20, 8, 1)
    st.caption("Buses update *inside* the map — the page never reloads.")

# ── MAIN: live map ────────────────────────────────────────────────────────────
st.markdown("### 🗺️ Live Map")
cfg = {
    "api": API_BASE,
    "demo": "true" if demo_mode else "false",
    "interval": interval,
    "legs": [],
    "route_ids": [],
    "start": [start_stop["lat"], start_stop["lon"]],
    "start_name": start_stop["stop_name"],
    "end": [end_stop["lat"], end_stop["lon"]],
    "end_name": end_stop["stop_name"],
}
result = st.session_state.get("journey", {})
if result.get("options"):
    sel = result["options"][st.session_state.get("sel_option", 0)]
    cfg["legs"] = [{"geometry": leg["geometry"], "mode": leg.get("mode")}
                   for leg in sel["legs"]]
    # Only buses have live GTFS-RT positions; metro/walk legs don't.
    cfg["route_ids"] = [leg["route_id"] for leg in sel["legs"]
                        if leg.get("mode") == "bus"]
render_live_map(cfg)
st.caption(
    "🔵/🟠/🟣 lines = your journey legs · 🚌 = live buses (move every "
    f"{interval}s without reloading the page)"
)

st.divider()
st.caption(
    "Delhi Transit Journey Planner · Buses: DTC + DIMTS (GTFS) · "
    "Delay: ML model · Live positions: GTFS-Realtime (OTD)"
)

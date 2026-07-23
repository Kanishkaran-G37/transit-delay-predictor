"""Precompute a compact, MULTI-MODAL journey-planning index from GTFS feeds.

Reads one or more GTFS feeds (buses today, Delhi Metro when present) and merges
them into a single index. Every route is tagged with its mode ('bus' / 'metro'),
and metro ids are namespaced with a prefix so they never collide with bus ids.

Drop the DMRC GTFS into ml/data/dmrc/ and rerun this script to light up trains.

Index contents (all ids are strings, metro ids prefixed 'M-'):
    stops          : {stop_id: {'name', 'lat', 'lon', 'mode'}}
    route_names    : {route_id: {'short', 'long', 'agency'}}
    route_mode     : {route_id: 'bus' | 'metro'}
    route_stops    : {route_id: [stop_id, ...]}            # representative trip, in order
    route_cum      : {route_id: [seconds_from_start, ...]} # aligned with route_stops
    route_headway  : {route_id: headway_minutes_estimate}
    stop_to_routes : {stop_id: [route_id, ...]}
"""
import os
import joblib
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, 'ml', 'data')
OUT_PATH = os.path.join(DATA_PATH, 'journey_index.joblib')

SERVICE_MINUTES = 18 * 60  # assumed daily service span for headway estimate

# Each feed: directory of GTFS .txt files, its mode, and an id prefix.
FEEDS = [
    {'dir': DATA_PATH, 'mode': 'bus', 'prefix': ''},
    {'dir': os.path.join(DATA_PATH, 'dmrc'), 'mode': 'metro', 'prefix': 'M-'},
]


def _time_to_seconds(series):
    """Vectorised 'HH:MM:SS' -> seconds. GTFS allows hours >= 24."""
    parts = series.str.split(':', expand=True).astype('int32')
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def _process_feed(feed):
    """Return per-feed index fragments, or None if the feed isn't present."""
    d, mode, prefix = feed['dir'], feed['mode'], feed['prefix']
    st_path = os.path.join(d, 'stop_times.txt')
    if not os.path.exists(st_path):
        return None

    def P(x):  # namespace an id
        return f"{prefix}{x}"

    print(f"Reading '{mode}' feed from {d} ...")
    stops_df = pd.read_csv(os.path.join(d, 'stops.txt'))
    routes_df = pd.read_csv(os.path.join(d, 'routes.txt'))
    trips_df = pd.read_csv(os.path.join(d, 'trips.txt'), usecols=['trip_id', 'route_id'])
    st = pd.read_csv(
        st_path,
        usecols=['trip_id', 'arrival_time', 'stop_id', 'stop_sequence'],
        dtype={'trip_id': str},
    )
    print(f"  stop_times rows: {len(st):,}")

    stops = {
        P(r.stop_id): {
            'name': str(r.stop_name),
            'lat': float(r.stop_lat),
            'lon': float(r.stop_lon),
            'mode': mode,
        }
        for r in stops_df.itertuples()
    }

    route_names, route_mode = {}, {}
    for r in routes_df.itertuples():
        rid = P(r.route_id)
        route_names[rid] = {
            'short': '' if pd.isna(r.route_short_name) else str(r.route_short_name),
            'long': '' if pd.isna(r.route_long_name) else str(r.route_long_name),
            'agency': str(getattr(r, 'agency_id', '')) if hasattr(r, 'agency_id') else '',
        }
        route_mode[rid] = mode

    # Representative trip per route (the one with the most stops).
    trip_to_route = {str(t): P(r) for t, r in
                     zip(trips_df['trip_id'], trips_df['route_id'])}
    st['trip_id'] = st['trip_id'].astype(str)
    st['route_id'] = st['trip_id'].map(trip_to_route)
    st = st.dropna(subset=['route_id'])

    sizes = st.groupby('trip_id', sort=False).size().rename('n').reset_index()
    sizes['route_id'] = sizes['trip_id'].map(trip_to_route)
    rep = sizes.sort_values('n').drop_duplicates('route_id', keep='last')
    rep_trips = set(rep['trip_id'])

    trips_per_route = trips_df.groupby(trips_df['route_id'].map(P)).size()

    def headway(route_id):
        n = int(trips_per_route.get(route_id, 1))
        return max(3, min(60, round(SERVICE_MINUTES / max(n, 1))))

    rep_st = st[st['trip_id'].isin(rep_trips)].copy()
    rep_st['arr_s'] = _time_to_seconds(rep_st['arrival_time'])
    rep_st['stop_id'] = rep_st['stop_id'].map(P)
    rep_st = rep_st.sort_values(['trip_id', 'stop_sequence'])

    route_stops, route_cum, route_headway, stop_to_routes = {}, {}, {}, {}
    for trip_id, grp in rep_st.groupby('trip_id', sort=False):
        route_id = trip_to_route[trip_id]
        stop_ids = grp['stop_id'].tolist()
        secs = grp['arr_s'].tolist()
        base = secs[0]
        route_stops[route_id] = stop_ids
        route_cum[route_id] = [int(s - base) for s in secs]
        route_headway[route_id] = headway(route_id)
        for sid in stop_ids:
            stop_to_routes.setdefault(sid, set()).add(route_id)

    print(f"  routes: {len(route_stops):,} | stops: {len(stops):,}")
    return {
        'stops': stops, 'route_names': route_names, 'route_mode': route_mode,
        'route_stops': route_stops, 'route_cum': route_cum,
        'route_headway': route_headway, 'stop_to_routes': stop_to_routes,
    }


def build():
    merged = {k: {} for k in ('stops', 'route_names', 'route_mode',
                              'route_stops', 'route_cum', 'route_headway')}
    stop_to_routes = {}
    modes_loaded = []

    for feed in FEEDS:
        frag = _process_feed(feed)
        if frag is None:
            print(f"(skipping '{feed['mode']}' feed — not found at {feed['dir']})")
            continue
        modes_loaded.append(feed['mode'])
        for key in merged:
            merged[key].update(frag[key])
        for sid, routes in frag['stop_to_routes'].items():
            stop_to_routes.setdefault(sid, set()).update(routes)

    merged['stop_to_routes'] = {k: sorted(v) for k, v in stop_to_routes.items()}

    joblib.dump(merged, OUT_PATH)
    print(f"\n[OK] Saved journey index -> {OUT_PATH}")
    print(f"   modes loaded   : {', '.join(modes_loaded) or 'none'}")
    print(f"   routes indexed : {len(merged['route_stops']):,}")
    print(f"   stops indexed  : {len(merged['stops']):,}")


if __name__ == '__main__':
    build()

"""Origin -> destination journey planner over the static GTFS network.

Finds DIRECT routes (one bus serves both stops) and ONE-TRANSFER routes
(bus A to a transfer stop, then bus B), computes scheduled departure/arrival
times from the precomputed journey index, and applies the ML delay model so
each option shows a predicted delay ("8 min late" / "On time").

The heavy lifting (scanning 3.7M stop_times rows) happened once in
ingestion/build_journey_index.py; here we just do fast dict lookups.
"""
import os
import joblib
from datetime import datetime

from services.prediction_service import predict_delay

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(BASE_DIR, 'ml', 'data', 'journey_index.joblib')

_INDEX = joblib.load(INDEX_PATH)
STOPS = _INDEX['stops']
ROUTE_NAMES = _INDEX['route_names']
ROUTE_STOPS = _INDEX['route_stops']
ROUTE_CUM = _INDEX['route_cum']
ROUTE_HEADWAY = _INDEX['route_headway']
STOP_TO_ROUTES = _INDEX['stop_to_routes']
ROUTE_MODE = _INDEX.get('route_mode', {})

# Which modes actually have data loaded (e.g. {'bus'} until DMRC is added).
MODES_LOADED = set(ROUTE_MODE.values()) or {'bus'}

# Precompute {route_id: {stop_id: first_position}} for O(1) position lookups.
ROUTE_POS = {}
for _rid, _stops in ROUTE_STOPS.items():
    pos = {}
    for _i, _sid in enumerate(_stops):
        if _sid not in pos:            # keep first occurrence (loops)
            pos[_sid] = _i
    ROUTE_POS[_rid] = pos

TRANSFER_BUFFER_MIN = 3  # fixed walk/buffer added at a transfer


def _routes_at(stop_id, allowed):
    """Routes serving a stop, restricted to the allowed modes."""
    return [r for r in STOP_TO_ROUTES.get(stop_id, [])
            if ROUTE_MODE.get(r, 'bus') in allowed]


# ── Small helpers ────────────────────────────────────────────────────────────
def _fmt_clock(seconds):
    seconds = int(seconds) % 86400
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"


def _now_seconds():
    now = datetime.now()
    return now.hour * 3600 + now.minute * 60 + now.second


def _route_label(route_id):
    info = ROUTE_NAMES.get(route_id, {})
    if ROUTE_MODE.get(route_id) == 'metro':
        # DMRC long names look like "RED_Rithala to Shaheed Sthal" — surface the
        # line colour as a friendly "Red Line" instead of a code like "R_RS".
        long = info.get('long', '')
        if '_' in long:
            return f"{long.split('_', 1)[0].strip().title()} Line"
        return info.get('short') or long or route_id
    return info.get('short') or info.get('long') or route_id


def _agency(route_id):
    return ROUTE_NAMES.get(route_id, {}).get('agency', '')


def _leg_geometry(route_id, i, j):
    """Coordinates from board position i to alight position j (inclusive)."""
    coords = []
    for sid in ROUTE_STOPS[route_id][i:j + 1]:
        s = STOPS.get(sid)
        if s:
            coords.append([s['lat'], s['lon']])
    return coords


def _make_leg(route_id, i, j, depart_s):
    """Build one ride leg dict; returns (leg, arrive_seconds)."""
    ride_s = ROUTE_CUM[route_id][j] - ROUTE_CUM[route_id][i]
    board_sid = ROUTE_STOPS[route_id][i]
    alight_sid = ROUTE_STOPS[route_id][j]
    arrive_s = depart_s + ride_s
    mode = ROUTE_MODE.get(route_id, 'bus')
    leg = {
        'route_id': route_id,
        'route_label': _route_label(route_id),
        'mode': mode,
        'icon': '🚇' if mode == 'metro' else '🚌',
        'agency': _agency(route_id),
        'board_stop_id': board_sid,
        'board_stop_name': STOPS.get(board_sid, {}).get('name', board_sid),
        'alight_stop_id': alight_sid,
        'alight_stop_name': STOPS.get(alight_sid, {}).get('name', alight_sid),
        'num_stops': j - i,
        'ride_minutes': round(ride_s / 60),
        'headway_min': ROUTE_HEADWAY.get(route_id, 15),
        'depart': _fmt_clock(depart_s),
        'arrive': _fmt_clock(arrive_s),
        'geometry': _leg_geometry(route_id, i, j),
    }
    return leg, arrive_s


def _delay_text(delay):
    if delay < 3:
        return 'On time', 'ok'
    if delay < 10:
        return f'{int(round(delay))} min late', 'minor'
    if delay < 20:
        return f'{int(round(delay))} min late', 'moderate'
    return f'{int(round(delay))} min late — consider leaving earlier', 'severe'


# ── Core planning ────────────────────────────────────────────────────────────
def _direct_options(start_id, end_id, allowed):
    """Routes that serve start before end."""
    out = []
    common = set(_routes_at(start_id, allowed)) & set(_routes_at(end_id, allowed))
    for r in common:
        i = ROUTE_POS[r].get(start_id)
        j = ROUTE_POS[r].get(end_id)
        if i is not None and j is not None and i < j:
            out.append((r, i, j))
    return out


def _transfer_options(start_id, end_id, allowed, max_candidates=6):
    """bus A (start -> t) then bus B (t -> end), best time per transfer stop."""
    # Best first leg reaching each downstream stop t.
    leg1 = {}
    for r in _routes_at(start_id, allowed):
        i = ROUTE_POS[r].get(start_id)
        if i is None:
            continue
        cum = ROUTE_CUM[r]
        stops = ROUTE_STOPS[r]
        for j in range(i + 1, len(stops)):
            t = stops[j]
            secs = cum[j] - cum[i]
            if t not in leg1 or secs < leg1[t][2]:
                leg1[t] = (r, i, secs, j)

    # Best second leg from each upstream stop t to end.
    leg2 = {}
    for r in _routes_at(end_id, allowed):
        k = ROUTE_POS[r].get(end_id)
        if k is None:
            continue
        cum = ROUTE_CUM[r]
        stops = ROUTE_STOPS[r]
        for j in range(0, k):
            t = stops[j]
            secs = cum[k] - cum[j]
            if t not in leg2 or secs < leg2[t][2]:
                leg2[t] = (r, j, secs, k)

    candidates = []
    for t in set(leg1) & set(leg2):
        r1, i, s1, j1 = leg1[t]
        r2, j2, s2, k = leg2[t]
        if r1 == r2:
            continue  # same bus = a direct route, handled elsewhere
        candidates.append((s1 + s2, t, (r1, i, j1), (r2, j2, k)))

    candidates.sort(key=lambda c: c[0])
    return candidates[:max_candidates]


def _reach_from_start(start_id, allowed):
    """Best first leg reaching each downstream stop t: t -> (route, board_i, secs, t_pos)."""
    leg = {}
    for r in _routes_at(start_id, allowed):
        i = ROUTE_POS[r].get(start_id)
        if i is None:
            continue
        cum, stops = ROUTE_CUM[r], ROUTE_STOPS[r]
        for j in range(i + 1, len(stops)):
            t = stops[j]
            secs = cum[j] - cum[i]
            if t not in leg or secs < leg[t][2]:
                leg[t] = (r, i, secs, j)
    return leg


def _reach_to_end(end_id, allowed):
    """Best last leg from each upstream stop t to end: t -> (route, t_pos, secs, end_pos)."""
    leg = {}
    for r in _routes_at(end_id, allowed):
        k = ROUTE_POS[r].get(end_id)
        if k is None:
            continue
        cum, stops = ROUTE_CUM[r], ROUTE_STOPS[r]
        for j in range(0, k):
            t = stops[j]
            secs = cum[k] - cum[j]
            if t not in leg or secs < leg[t][2]:
                leg[t] = (r, j, secs, k)
    return leg


def _two_transfer_options(start_id, end_id, allowed, max_candidates=4, scan_limit=200):
    """bus A (start->t1), bus B (t1->t2), bus C (t2->end). Used only as a
    fallback when nothing simpler connects the stops."""
    reach1 = _reach_from_start(start_id, allowed)
    reach3 = _reach_to_end(end_id, allowed)
    if not reach1 or not reach3:
        return []

    # Consider the quickest-to-reach intermediate stops first, and cap the scan.
    r1_items = sorted(reach1.items(), key=lambda kv: kv[1][2])[:scan_limit]

    seen = set()
    candidates = []
    for t1, (r1, i, s1, j1) in r1_items:
        for r2 in _routes_at(t1, allowed):
            if r2 == r1:
                continue
            p1 = ROUTE_POS[r2].get(t1)
            if p1 is None:
                continue
            cum2, stops2 = ROUTE_CUM[r2], ROUTE_STOPS[r2]
            for m in range(p1 + 1, len(stops2)):
                t2 = stops2[m]
                info3 = reach3.get(t2)
                if not info3:
                    continue
                r3, j3, s3, k = info3
                if r3 == r2 or r3 == r1:
                    continue
                combo = (r1, r2, r3)
                if combo in seen:
                    continue
                seen.add(combo)
                total = s1 + (cum2[m] - cum2[p1]) + s3
                candidates.append(
                    (total, t1, t2, (r1, i, j1), (r2, p1, m), (r3, j3, k))
                )
        if len(candidates) >= 80:
            break

    candidates.sort(key=lambda c: c[0])
    return candidates[:max_candidates]


def plan_journey(start_id, end_id, modes=('bus',),
                 weather=None, traffic_level='medium', max_options=4):
    """Return ranked journey options between two stop ids.

    modes: which networks to route over, e.g. ('bus',), ('metro',) or
    ('bus', 'metro'). Requested modes with no data loaded are ignored (with
    a message if that leaves nothing to route on).
    """
    start_id, end_id = str(start_id), str(end_id)
    requested = {m for m in modes if m in ('bus', 'metro')} or {'bus'}
    allowed = requested & MODES_LOADED

    if not allowed:
        missing = ', '.join(sorted(requested))
        return {
            'available': False,
            'message': f'No data loaded for: {missing}. '
                       'Add the DMRC GTFS to ml/data/dmrc/ and rebuild the index '
                       'to enable metro, or select Bus.',
            'options': [],
        }

    if start_id not in STOPS or end_id not in STOPS:
        return {'available': False, 'message': 'Unknown stop selected.', 'options': []}
    if start_id == end_id:
        return {'available': False, 'message': 'Start and end stops are the same.',
                'options': []}

    weather = weather or {}
    w_cond = weather.get('weather_condition', 'Clear')
    temp = weather.get('temperature', 30.0)
    humidity = weather.get('humidity', 60)
    wind = weather.get('wind_speed', 2.0)

    now_s = _now_seconds()
    raw = []  # (scheduled_total_seconds, journey_dict)

    # ── Direct options ───────────────────────────────────────────────────────
    for r, i, j in _direct_options(start_id, end_id, allowed):
        depart_s = now_s + ROUTE_HEADWAY.get(r, 15) * 60 // 2  # avg wait
        leg, arrive_s = _make_leg(r, i, j, depart_s)
        raw.append((arrive_s - now_s, {
            'type': 'direct',
            'transfers': 0,
            'legs': [leg],
            'depart_s': depart_s,
            'arrive_s': arrive_s,
        }))

    # ── One-transfer options ─────────────────────────────────────────────────
    for total_ride, t, (r1, i, j1), (r2, j2, k) in _transfer_options(start_id, end_id, allowed):
        depart_s = now_s + ROUTE_HEADWAY.get(r1, 15) * 60 // 2
        leg1, arr1 = _make_leg(r1, i, j1, depart_s)
        depart2_s = arr1 + TRANSFER_BUFFER_MIN * 60 + ROUTE_HEADWAY.get(r2, 15) * 60 // 2
        leg2, arr2 = _make_leg(r2, j2, k, depart2_s)
        raw.append((arr2 - now_s, {
            'type': 'transfer',
            'transfers': 1,
            'transfer_stop_name': STOPS.get(t, {}).get('name', t),
            'legs': [leg1, leg2],
            'depart_s': depart_s,
            'arrive_s': arr2,
        }))

    # ── Two-transfer fallback (only when nothing simpler connects) ───────────
    if not raw:
        for (total_ride, t1, t2, (r1, i, j1), (r2, p1, m), (r3, j3, k)) in \
                _two_transfer_options(start_id, end_id, allowed):
            depart_s = now_s + ROUTE_HEADWAY.get(r1, 15) * 60 // 2
            leg1, arr1 = _make_leg(r1, i, j1, depart_s)
            depart2_s = arr1 + TRANSFER_BUFFER_MIN * 60 + ROUTE_HEADWAY.get(r2, 15) * 60 // 2
            leg2, arr2 = _make_leg(r2, p1, m, depart2_s)
            depart3_s = arr2 + TRANSFER_BUFFER_MIN * 60 + ROUTE_HEADWAY.get(r3, 15) * 60 // 2
            leg3, arr3 = _make_leg(r3, j3, k, depart3_s)
            raw.append((arr3 - now_s, {
                'type': 'transfer',
                'transfers': 2,
                'transfer_stop_name': None,
                'legs': [leg1, leg2, leg3],
                'depart_s': depart_s,
                'arrive_s': arr3,
            }))

    if not raw:
        return {
            'available': True, 'modes': sorted(allowed), 'options': [],
            'message': 'No route found within 2 transfers between these stops. '
                       'They may be too far apart or poorly connected.',
        }

    # Rank: fewer transfers first, then earlier arrival.
    raw.sort(key=lambda x: (x[1]['transfers'], x[0]))
    raw = raw[:max_options]

    # ── Attach ML-predicted delay to each option ─────────────────────────────
    options = []
    for _, jr in raw:
        total_stops = sum(leg['num_stops'] for leg in jr['legs'])
        pred = predict_delay(
            weather_condition=w_cond, temperature=temp, humidity=humidity,
            wind_speed=wind, traffic_level=traffic_level, num_stops=total_stops,
        )
        delay = pred['predicted_delay_minutes']
        text, severity = _delay_text(delay)
        sched_min = round((jr['arrive_s'] - jr['depart_s']) / 60)
        options.append({
            'type': jr['type'],
            'transfers': jr['transfers'],
            'transfer_stop_name': jr.get('transfer_stop_name'),
            'legs': jr['legs'],
            'depart': _fmt_clock(jr['depart_s']),
            'arrive': _fmt_clock(jr['arrive_s']),
            'arrive_predicted': _fmt_clock(jr['arrive_s'] + delay * 60),
            'scheduled_minutes': sched_min,
            'predicted_total_minutes': sched_min + round(delay),
            'predicted_delay_minutes': delay,
            'delay_text': text,
            'delay_severity': severity,
            'is_peak_hour': pred['is_peak_hour'],
        })

    return {
        'available': True,
        'modes': sorted(allowed),
        'start_stop_name': STOPS[start_id]['name'],
        'end_stop_name': STOPS[end_id]['name'],
        'options': options,
    }


def search_stops(query, limit=20):
    """Simple case-insensitive stop-name search for the pickers."""
    q = (query or '').strip().lower()
    results = []
    for sid, meta in STOPS.items():
        if q in meta['name'].lower():
            results.append({'stop_id': sid, 'stop_name': meta['name'],
                            'lat': meta['lat'], 'lon': meta['lon']})
            if len(results) >= limit:
                break
    return results

"""Log REAL observed bus delays by comparing live positions to the schedule.

Delhi OTD publishes only GTFS-Realtime *VehiclePositions* (there is no
TripUpdates feed carrying a ready-made `delay` field), so we derive the delay:

  1. keep only live buses whose trip_id exists in the static GTFS — that way we
     can use the trip's OWN scheduled stop times rather than a route average
  2. snap the bus's GPS position to the nearest stop on that trip
  3. delay = observation time - that stop's scheduled arrival

Accuracy over volume: buses we cannot schedule-match exactly are skipped, so
every logged row is a genuine schedule-adherence measurement.

NOTE: coverage depends on how fresh ml/data/*.txt is. If few live trip_ids match
the static GTFS, re-download the bus GTFS from https://otd.delhi.gov.in — that
single step massively increases how many buses can be measured.

    python ingestion/log_delays.py

Run on a schedule (every ~5 min), then retrain with ml/train_on_observed.py.
"""
import os
import sys
import csv
import django
import pandas as pd
from math import radians, sin, cos, sqrt, atan2
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from services.realtime_service import get_live_vehicles
from services.weather_service import get_weather
from services.traffic_service import get_traffic_level
from services.journey_service import STOPS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'ml', 'data')
OUT_CSV = os.path.join(DATA_DIR, 'observed_delays.csv')
TRIPS_TXT = os.path.join(DATA_DIR, 'trips.txt')
STOP_TIMES_TXT = os.path.join(DATA_DIR, 'stop_times.txt')

PEAK_HOURS = {8, 9, 10, 17, 18, 19, 20}
CITY_CENTRE = (28.6315, 77.2167)      # one traffic sample per run
IST_OFFSET = int(5.5 * 3600)          # feed timestamps are UTC epoch
MAX_SNAP_KM = 1.0                     # bus must really be at that stop
PLAUSIBLE = (-45, 180)                # minutes; outside this it's bad data
EARLY_GRACE = 15 * 60                 # may be observed slightly before start
LATE_GRACE = 60 * 60                  # ...or up to an hour past scheduled end
# NOTE: LATE_GRACE caps how late a trip can be and still be measured, so very
# severe delays (>60 min) are under-represented in the collected data.

FIELDS = ['timestamp', 'hour_of_day', 'day_of_week', 'is_peak_hour', 'is_weekend',
          'weather_condition', 'temperature', 'humidity', 'wind_speed',
          'traffic_level', 'num_stops', 'city', 'delay_minutes',
          'route_id', 'trip_id', 'snap_km']


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    a = (sin((lat2 - lat1) / 2) ** 2
         + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2)
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _hms(t):
    h, m, s = str(t).split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def _static_trip_ids():
    return set(pd.read_csv(TRIPS_TXT, usecols=['trip_id'], dtype=str)['trip_id'])


def _load_schedules(trip_ids):
    """{trip_id: [(stop_id, scheduled_seconds, stop_sequence), ...]} for these trips."""
    want = set(trip_ids)
    out = {}
    for chunk in pd.read_csv(
            STOP_TIMES_TXT,
            usecols=['trip_id', 'arrival_time', 'stop_id', 'stop_sequence'],
            dtype={'trip_id': str, 'stop_id': str}, chunksize=500_000):
        hit = chunk[chunk['trip_id'].isin(want)]
        if hit.empty:
            continue
        for tid, g in hit.groupby('trip_id'):
            out.setdefault(tid, []).extend(
                (r.stop_id, _hms(r.arrival_time), int(r.stop_sequence))
                for r in g.itertuples())
    for tid in out:
        out[tid].sort(key=lambda x: x[2])
    return out


def run(city='Delhi'):
    res = get_live_vehicles()
    if res.get('source') != 'live':
        print(f"No live feed ({res.get('source')}): {res.get('error', '')}")
        return 0
    vehicles = res['vehicles']

    static = _static_trip_ids()
    usable = [v for v in vehicles
              if v.get('trip_id') in static and v.get('timestamp')]
    print(f"{len(vehicles)} live buses; {len(usable)} match the static GTFS exactly.")
    if not usable:
        print("No schedule-matchable buses — re-download the bus GTFS from "
              "https://otd.delhi.gov.in to refresh trip ids.")
        return 0

    schedules = _load_schedules({v['trip_id'] for v in usable})
    weather = get_weather(city)
    traffic = get_traffic_level(*CITY_CENTRE)
    now = datetime.now()
    hour, dow = now.hour, now.weekday()

    rows, skipped, stale = [], 0, 0
    for v in usable:
        sched = schedules.get(v['trip_id'])
        if not sched:
            skipped += 1
            continue

        obs_s = (int(v['timestamp']) + IST_OFFSET) % 86400
        trip_start, trip_end = sched[0][1], sched[-1][1]
        # A vehicle often keeps an old trip_id after finishing. Only measure
        # trips that could genuinely still be running right now.
        if not (trip_start - EARLY_GRACE <= obs_s <= trip_end + LATE_GRACE):
            stale += 1
            continue

        # Snap to the nearest stop ON THIS TRIP.
        best = None
        for seq_i, (sid, sec, _) in enumerate(sched):
            s = STOPS.get(sid)
            if not s:
                continue
            d = _haversine(v['lat'], v['lon'], s['lat'], s['lon'])
            if best is None or d < best[0]:
                best = (d, sec, seq_i)
        if best is None or best[0] > MAX_SNAP_KM:
            skipped += 1
            continue
        dist_km, scheduled_s, seq_i = best

        actual_s = (int(v['timestamp']) + IST_OFFSET) % 86400
        delay_min = (actual_s - scheduled_s) / 60.0
        if delay_min < -720:
            delay_min += 1440
        elif delay_min > 720:
            delay_min -= 1440
        if not (PLAUSIBLE[0] <= delay_min <= PLAUSIBLE[1]):
            skipped += 1
            continue

        rows.append({
            'timestamp': v['timestamp'],
            'hour_of_day': hour,
            'day_of_week': dow,
            'is_peak_hour': 1 if hour in PEAK_HOURS else 0,
            'is_weekend': 1 if dow >= 5 else 0,
            'weather_condition': weather['weather_condition'],
            'temperature': round(weather['temperature'], 1),
            'humidity': weather['humidity'],
            'wind_speed': round(weather['wind_speed'], 1),
            'traffic_level': traffic['traffic_level'],
            'num_stops': seq_i,
            'city': city,
            'delay_minutes': round(delay_min, 2),
            'route_id': v.get('route_id'),
            'trip_id': v['trip_id'],
            'snap_km': round(dist_km, 3),
        })

    exists = os.path.exists(OUT_CSV)
    with open(OUT_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)

    total = sum(1 for _ in open(OUT_CSV, encoding='utf-8')) - 1
    avg = sum(r['delay_minutes'] for r in rows) / len(rows) if rows else 0
    print(f"Logged {len(rows)} measurements (skipped {skipped}, "
          f"stale trip ids {stale}). "
          f"Avg delay {avg:.1f} min. Dataset now {total} rows -> {OUT_CSV}")
    return len(rows)


if __name__ == '__main__':
    run()

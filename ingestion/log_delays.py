"""Log REAL observed bus delays from GTFS-Realtime TripUpdates.

Each run records one observation per active trip (its current delay vs schedule)
plus the context features the model uses, appending to
ml/data/observed_delays.csv.

Run this on a schedule (every few minutes) for several days to build a real
dataset, then retrain with ml/train_on_observed.py.

    python ingestion/log_delays.py

Requires OTD_API_KEY in .env (free: https://otd.delhi.gov.in).
"""
import os
import sys
import csv
import django
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from services.realtime_service import get_trip_updates
from services.weather_service import get_weather
from services.traffic_service import get_traffic_level

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_CSV = os.path.join(BASE_DIR, 'ml', 'data', 'observed_delays.csv')

PEAK_HOURS = {8, 9, 10, 17, 18, 19, 20}
# City-centre point for a single traffic sample per run (Connaught Place).
CITY_CENTRE = (28.6315, 77.2167)

FIELDS = ['timestamp', 'hour_of_day', 'day_of_week', 'is_peak_hour', 'is_weekend',
          'weather_condition', 'temperature', 'humidity', 'wind_speed',
          'traffic_level', 'num_stops', 'city', 'delay_minutes',
          'route_id', 'trip_id']


def run(city='Delhi'):
    res = get_trip_updates()
    if res.get('source') != 'live':
        print(f"No live TripUpdates feed ({res.get('source')}): {res.get('error', '')}")
        return 0

    weather = get_weather(city)
    traffic = get_traffic_level(*CITY_CENTRE)
    now = datetime.now()
    hour, dow = now.hour, now.weekday()

    seen, rows = set(), []
    for u in res['updates']:
        tid = u['trip_id']
        if tid in seen:            # one (imminent) observation per trip
            continue
        seen.add(tid)
        # Sanity clamp — GTFS-RT occasionally emits absurd delay values.
        delay_min = max(-30, min(180, u['delay_seconds'] / 60.0))
        rows.append({
            'timestamp': u['timestamp'],
            'hour_of_day': hour,
            'day_of_week': dow,
            'is_peak_hour': 1 if hour in PEAK_HOURS else 0,
            'is_weekend': 1 if dow >= 5 else 0,
            'weather_condition': weather['weather_condition'],
            'temperature': round(weather['temperature'], 1),
            'humidity': weather['humidity'],
            'wind_speed': round(weather['wind_speed'], 1),
            'traffic_level': traffic['traffic_level'],
            'num_stops': u['stop_sequence'],
            'city': city,
            'delay_minutes': round(delay_min, 2),
            'route_id': u['route_id'],
            'trip_id': tid,
        })

    exists = os.path.exists(OUT_CSV)
    with open(OUT_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)

    total = sum(1 for _ in open(OUT_CSV, encoding='utf-8')) - 1
    print(f"Logged {len(rows)} observations (feed had {len(res['updates'])} stop "
          f"updates). Dataset now ~{total} rows -> {OUT_CSV}")
    return len(rows)


if __name__ == '__main__':
    run()

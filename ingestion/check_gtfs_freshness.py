"""Check how well a GTFS folder matches the CURRENT live feed.

The delay logger can only measure a bus whose trip_id exists in the static GTFS.
This reports that match rate, so you can verify a fresh download BEFORE
overwriting the data you already have.

    python ingestion/check_gtfs_freshness.py                 # checks ml/data
    python ingestion/check_gtfs_freshness.py ml/data/bus_new # checks a candidate

Rule of thumb: >50% trip match = good enough to measure delays.
"""
import os
import sys
import django
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from services.realtime_service import get_live_vehicles

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(BASE_DIR, 'ml', 'data')


def check(folder):
    trips_txt = os.path.join(folder, 'trips.txt')
    routes_txt = os.path.join(folder, 'routes.txt')
    if not os.path.exists(trips_txt):
        print(f"No trips.txt in {folder}")
        return

    res = get_live_vehicles()
    if res.get('source') != 'live':
        print(f"Cannot check — live feed unavailable ({res.get('source')}): "
              f"{res.get('error', '')}")
        return

    vehicles = res['vehicles']
    live_trips = [v['trip_id'] for v in vehicles if v.get('trip_id')]
    live_routes = [v['route_id'] for v in vehicles if v.get('route_id')]

    static_trips = set(pd.read_csv(trips_txt, usecols=['trip_id'], dtype=str)['trip_id'])
    static_routes = set(pd.read_csv(routes_txt, usecols=['route_id'],
                                    dtype=str)['route_id'])

    t_hit = sum(1 for t in live_trips if t in static_trips)
    r_hit = sum(1 for r in live_routes if r in static_routes)
    t_pct = 100 * t_hit / len(live_trips) if live_trips else 0
    r_pct = 100 * r_hit / len(live_routes) if live_routes else 0

    print(f"Checking: {folder}")
    print(f"  static trips: {len(static_trips):,} | static routes: {len(static_routes):,}")
    print(f"  live buses right now: {len(vehicles):,}")
    print(f"  trip_id  match: {t_hit:,}/{len(live_trips):,}  ({t_pct:.1f}%)")
    print(f"  route_id match: {r_hit:,}/{len(live_routes):,}  ({r_pct:.1f}%)")
    print()
    if t_pct >= 50:
        print("  VERDICT: fresh — delays can be measured reliably.")
    elif t_pct >= 10:
        print("  VERDICT: partially fresh — usable but limited coverage.")
    else:
        print("  VERDICT: STALE — too few trips match to measure delay honestly.")


if __name__ == '__main__':
    check(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR)

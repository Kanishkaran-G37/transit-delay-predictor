import os
import sys
import django
import pandas as pd

# Setup Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from routes.models import Route
from stops.models import Stop, RouteStop

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ml', 'data')

def load_routes():
    print("Loading routes...")
    df = pd.read_csv(os.path.join(DATA_PATH, 'routes.txt'))
    count = 0
    for _, row in df.iterrows():
        Route.objects.get_or_create(
            route_id=str(row['route_id']),
            defaults={
                'route_short_name': str(row.get('route_short_name', '')),
                'route_long_name': str(row.get('route_long_name', '')),
                'route_type': int(row.get('route_type', 3)),
                'city': 'Delhi'
            }
        )
        count += 1
    print(f"✅ Loaded {count} routes")

def load_stops():
    print("Loading stops...")
    df = pd.read_csv(os.path.join(DATA_PATH, 'stops.txt'))
    count = 0
    for _, row in df.iterrows():
        Stop.objects.get_or_create(
            stop_id=str(row['stop_id']),
            defaults={
                'stop_name': str(row['stop_name']),
                'stop_lat': float(row['stop_lat']),
                'stop_lon': float(row['stop_lon']),
                'city': 'Delhi'
            }
        )
        count += 1
    print(f"✅ Loaded {count} stops")

def load_route_stops():
    print("Loading route-stop relationships...")
    trips_df = pd.read_csv(os.path.join(DATA_PATH, 'trips.txt'))
    stop_times_df = pd.read_csv(os.path.join(DATA_PATH, 'stop_times.txt'))

    # Merge trips with stop_times to get route_id per stop
    merged = stop_times_df.merge(trips_df[['trip_id', 'route_id']], on='trip_id')
    merged = merged.drop_duplicates(subset=['route_id', 'stop_id', 'stop_sequence'])

    count = 0
    for _, row in merged.iterrows():
        try:
            route = Route.objects.get(route_id=str(row['route_id']))
            stop = Stop.objects.get(stop_id=str(row['stop_id']))
            RouteStop.objects.get_or_create(
                route=route,
                stop=stop,
                stop_sequence=int(row['stop_sequence'])
            )
            count += 1
        except (Route.DoesNotExist, Stop.DoesNotExist):
            continue
    print(f"✅ Loaded {count} route-stop relationships")

if __name__ == '__main__':
    load_routes()
    load_stops()
    load_route_stops()
    print("\n🎉 All GTFS data loaded successfully!")
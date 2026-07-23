import os
import requests
from dotenv import load_dotenv
from google.transit import gtfs_realtime_pb2

load_dotenv()

OTD_API_KEY = os.getenv('OTD_API_KEY')

# Delhi Open Transit Data — GTFS-Realtime vehicle positions (protobuf).
# Free API key: https://otd.delhi.gov.in
VEHICLE_POSITIONS_URL = "https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb"


def get_live_vehicles(route_id=None):
    """Fetch real-time bus positions from Delhi's GTFS-Realtime feed.

    Returns a dict:
        {
          'vehicles': [ {vehicle_id, label, route_id, trip_id,
                         lat, lon, bearing, speed_kmh, timestamp}, ... ],
          'total_in_feed': <all buses currently reporting>,
          'matched': <buses on the requested route>,
          'source': 'live' | 'no_key' | 'error',
        }

    route_id: optional GTFS route_id to filter to a single route.
    """
    if not OTD_API_KEY or OTD_API_KEY == 'your_key_here':
        return {
            'vehicles': [],
            'total_in_feed': 0,
            'matched': 0,
            'source': 'no_key',
            'error': 'OTD_API_KEY not set. Get a free key at https://otd.delhi.gov.in',
        }

    try:
        response = requests.get(
            VEHICLE_POSITIONS_URL,
            params={'key': OTD_API_KEY},
            timeout=10,
        )
        response.raise_for_status()

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)

        vehicles = []
        for entity in feed.entity:
            if not entity.HasField('vehicle'):
                continue
            v = entity.vehicle
            pos = v.position
            vehicles.append({
                'vehicle_id': v.vehicle.id or entity.id,
                'label': v.vehicle.label or '',
                'route_id': v.trip.route_id or None,
                'trip_id': v.trip.trip_id or None,
                'lat': pos.latitude,
                'lon': pos.longitude,
                'bearing': round(pos.bearing, 1) if pos.HasField('bearing') else None,
                # GTFS-RT speed is metres/second -> km/h
                'speed_kmh': round(pos.speed * 3.6, 1) if pos.HasField('speed') else None,
                'timestamp': v.timestamp or feed.header.timestamp,
            })

        if route_id:
            matched = [x for x in vehicles if str(x['route_id']) == str(route_id)]
        else:
            matched = vehicles

        return {
            'vehicles': matched,
            'total_in_feed': len(vehicles),
            'matched': len(matched),
            'feed_timestamp': feed.header.timestamp,
            'source': 'live',
        }

    except Exception as e:
        return {
            'vehicles': [],
            'total_in_feed': 0,
            'matched': 0,
            'source': 'error',
            'error': str(e),
        }

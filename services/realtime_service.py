import os
import requests
from dotenv import load_dotenv
from google.transit import gtfs_realtime_pb2

load_dotenv()

OTD_API_KEY = os.getenv('OTD_API_KEY')

# Delhi Open Transit Data — GTFS-Realtime feeds (protobuf).
# Free API key: https://otd.delhi.gov.in
VEHICLE_POSITIONS_URL = "https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb"
TRIP_UPDATES_URL = "https://otd.delhi.gov.in/api/realtime/TripUpdates.pb"


def get_trip_updates(route_id=None):
    """Fetch GTFS-Realtime TripUpdates — the feed reports the actual delay
    (seconds early/late vs schedule) per stop. This is the ground truth used to
    train a real delay model.

    Returns a dict with 'updates': a list of
        {trip_id, route_id, stop_id, stop_sequence, delay_seconds, timestamp}
    """
    if not OTD_API_KEY or OTD_API_KEY == 'your_key_here':
        return {'updates': [], 'source': 'no_key',
                'error': 'OTD_API_KEY not set. Get a free key at https://otd.delhi.gov.in'}

    try:
        response = requests.get(TRIP_UPDATES_URL, params={'key': OTD_API_KEY}, timeout=15)
        response.raise_for_status()
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        return {'updates': _parse_trip_updates(feed, route_id),
                'feed_timestamp': feed.header.timestamp, 'source': 'live'}
    except Exception as e:
        return {'updates': [], 'source': 'error', 'error': str(e)}


def _parse_trip_updates(feed, route_id=None):
    """Extract per-stop delays from a parsed GTFS-RT FeedMessage."""
    updates = []
    for entity in feed.entity:
        if not entity.HasField('trip_update'):
            continue
        tu = entity.trip_update
        rid = tu.trip.route_id or None
        if route_id is not None and str(rid) != str(route_id):
            continue
        for stu in tu.stop_time_update:
            # Prefer arrival delay, fall back to departure delay.
            delay = None
            if stu.HasField('arrival') and stu.arrival.HasField('delay'):
                delay = stu.arrival.delay
            elif stu.HasField('departure') and stu.departure.HasField('delay'):
                delay = stu.departure.delay
            if delay is None:
                continue
            updates.append({
                'trip_id': tu.trip.trip_id or None,
                'route_id': rid,
                'stop_id': stu.stop_id or None,
                'stop_sequence': stu.stop_sequence,
                'delay_seconds': delay,
                'timestamp': tu.timestamp or feed.header.timestamp,
            })
    return updates


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

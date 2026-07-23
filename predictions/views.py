from rest_framework.decorators import api_view
from rest_framework.response import Response
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.weather_service import get_weather
from services.traffic_service import get_traffic_level
from services.prediction_service import predict_delay
from services.realtime_service import get_live_vehicles
from services.journey_service import plan_journey, STOPS

@api_view(['GET'])
def get_weather_view(request):
    city = request.GET.get('city', 'Delhi')
    data = get_weather(city)
    return Response(data)

@api_view(['GET'])
def get_traffic_view(request):
    try:
        lat = float(request.GET.get('lat', 28.6315))
        lon = float(request.GET.get('lon', 77.2167))
    except ValueError:
        return Response({'error': 'Invalid lat/lon'}, status=400)
    data = get_traffic_level(lat, lon)
    return Response(data)

@api_view(['GET'])
def get_prediction(request):
    """
    Full prediction combining weather + traffic + ML model
    Params: lat, lon, route_id, num_stops, city
    """
    try:
        lat = float(request.GET.get('lat', 28.6315))
        lon = float(request.GET.get('lon', 77.2167))
        num_stops = int(request.GET.get('num_stops', 15))
        city = request.GET.get('city', 'Delhi')
        route_id = request.GET.get('route_id', 'unknown')

        # Get live weather
        weather = get_weather(city)

        # Get live traffic
        traffic = get_traffic_level(lat, lon)

        # Predict delay
        prediction = predict_delay(
            weather_condition=weather['weather_condition'],
            temperature=weather['temperature'],
            humidity=weather['humidity'],
            wind_speed=weather['wind_speed'],
            traffic_level=traffic['traffic_level'],
            num_stops=num_stops,
            city=city
        )

        return Response({
            'route_id': route_id,
            'city': city,
            'location': {'lat': lat, 'lon': lon},
            'weather': weather,
            'traffic': traffic,
            'prediction': prediction,
            'summary': {
                'predicted_delay': f"{prediction['predicted_delay_minutes']} minutes",
                'predicted_eta': prediction['predicted_eta'],
                'traffic_level': traffic['traffic_level'],
                'weather': weather['weather_condition'],
                'is_peak_hour': prediction['is_peak_hour']
            }
        })

    except Exception as e:
        return Response({'error': str(e)}, status=500)


@api_view(['GET'])
def get_live_vehicles_view(request):
    """Live bus positions for a route (GTFS-Realtime).

    Params:
        route_id : filter to one route (recommended)
        demo     : 'true' -> if the live feed has no buses (e.g. no API key
                   yet), return clearly-labelled simulated buses that move
                   along the route so the feature can be demoed.
    """
    route_id = request.GET.get('route_id')
    demo = request.GET.get('demo', 'false').lower() == 'true'

    data = get_live_vehicles(route_id)

    if demo and not data.get('vehicles'):
        sim = _simulate_vehicles(route_id)
        if sim:
            data = {
                'vehicles': sim,
                'total_in_feed': len(sim),
                'matched': len(sim),
                'source': 'simulated',
                'note': ('Simulated positions for demo only. '
                         'Set OTD_API_KEY in .env for real live tracking.'),
                'live_feed_status': data.get('source'),
            }

    return Response(data)


@api_view(['GET'])
def get_journey_view(request):
    """Plan a journey between two stops.

    Params: start (stop_id), end (stop_id), mode ('bus'|'train'), city
    """
    start = request.GET.get('start')
    end = request.GET.get('end')
    # modes: comma-separated, e.g. "bus", "metro", or "bus,metro"
    modes = [m.strip() for m in request.GET.get('modes', 'bus').split(',') if m.strip()]
    city = request.GET.get('city', 'Delhi')

    if not start or not end:
        return Response(
            {'available': False, 'options': [],
             'message': 'start and end stop ids are required'},
            status=400,
        )

    # Real conditions feed the ML delay model.
    weather = get_weather(city)
    s = STOPS.get(str(start))
    if s:
        traffic = get_traffic_level(s['lat'], s['lon'])
        traffic_level = traffic['traffic_level']
    else:
        traffic, traffic_level = None, 'medium'

    result = plan_journey(start, end, modes=modes,
                          weather=weather, traffic_level=traffic_level)
    result['weather'] = weather
    result['traffic'] = traffic
    return Response(result)


@api_view(['GET'])
def get_stops_list(request):
    """All stops (optionally name-filtered) for the origin/destination pickers."""
    q = request.GET.get('q', '').strip().lower()
    items = [
        {'stop_id': sid, 'stop_name': m['name'], 'lat': m['lat'], 'lon': m['lon']}
        for sid, m in STOPS.items()
    ]
    if q:
        items = [x for x in items if q in x['stop_name'].lower()]
    items.sort(key=lambda x: x['stop_name'])
    return Response({'count': len(items), 'stops': items})


def _bearing(lat1, lon1, lat2, lon2):
    """Compass bearing (degrees) from point 1 to point 2."""
    from math import radians, degrees, sin, cos, atan2
    dlon = radians(lon2 - lon1)
    y = sin(dlon) * cos(radians(lat2))
    x = (cos(radians(lat1)) * sin(radians(lat2))
         - sin(radians(lat1)) * cos(radians(lat2)) * cos(dlon))
    return (degrees(atan2(y, x)) + 360) % 360


def _simulate_vehicles(route_id, num_buses=3, cycle_seconds=600.0):
    """Demo-only: buses that glide along the route's stops, driven by the
    clock so they visibly move on each auto-refresh. Not real data."""
    if not route_id:
        return []

    from datetime import datetime
    from stops.models import RouteStop

    route_stops = list(
        RouteStop.objects.filter(route__route_id=route_id)
        .select_related('stop').order_by('stop_sequence')
    )
    n = len(route_stops)
    if n < 2:
        return []

    pts = [(rs.stop.stop_lat, rs.stop.stop_lon) for rs in route_stops]
    t = datetime.now().timestamp()

    vehicles = []
    for i in range(num_buses):
        # Each bus offset by an equal phase along the route.
        frac = ((t / cycle_seconds) + (i / num_buses)) % 1.0
        pos = frac * (n - 1)
        idx = int(pos)
        r = pos - idx
        lat1, lon1 = pts[idx]
        lat2, lon2 = pts[min(idx + 1, n - 1)]
        lat = lat1 + (lat2 - lat1) * r
        lon = lon1 + (lon2 - lon1) * r
        vehicles.append({
            'vehicle_id': f'SIM-{i + 1}',
            'label': f'Demo Bus {i + 1}',
            'route_id': route_id,
            'trip_id': None,
            'lat': round(lat, 6),
            'lon': round(lon, 6),
            'bearing': round(_bearing(lat1, lon1, lat2, lon2), 1),
            'speed_kmh': 22.0,
            'timestamp': int(t),
        })
    return vehicles
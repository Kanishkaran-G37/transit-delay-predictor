from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Stop, RouteStop
from .serializers import StopSerializer
from math import radians, sin, cos, sqrt, atan2

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance in km between two GPS coordinates"""
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

@api_view(['GET'])
def get_nearby_stops(request):
    """
    Find stops near a user's location on a specific route
    Params: lat, lng, route_id (optional), radius_km (default 1.0)
    """
    try:
        lat = float(request.GET.get('lat'))
        lng = float(request.GET.get('lng'))
    except (TypeError, ValueError):
        return Response({'error': 'lat and lng are required'}, status=400)

    radius_km = float(request.GET.get('radius_km', 1.0))
    route_id = request.GET.get('route_id')

    # Filter stops by route if provided
    if route_id:
        stop_ids = RouteStop.objects.filter(
            route__route_id=route_id
        ).values_list('stop_id', flat=True)
        stops = Stop.objects.filter(id__in=stop_ids)
    else:
        stops = Stop.objects.all()

    # Calculate distance for each stop
    nearby = []
    for stop in stops:
        distance = haversine_distance(lat, lng, stop.stop_lat, stop.stop_lon)
        if distance <= radius_km:
            nearby.append({
                'stop_id': stop.stop_id,
                'stop_name': stop.stop_name,
                'stop_lat': stop.stop_lat,
                'stop_lon': stop.stop_lon,
                'distance_km': round(distance, 3)
            })

    # Sort by nearest first
    nearby.sort(key=lambda x: x['distance_km'])

    return Response({
        'user_location': {'lat': lat, 'lng': lng},
        'radius_km': radius_km,
        'route_id': route_id,
        'count': len(nearby),
        'stops': nearby
    })

@api_view(['GET'])
def get_stops_for_route(request, route_id):
    """Get all stops for a specific route in order"""
    route_stops = RouteStop.objects.filter(
        route__route_id=route_id
    ).select_related('stop').order_by('stop_sequence')

    if not route_stops.exists():
        return Response({'error': 'Route not found'}, status=404)

    stops = [{
        'sequence': rs.stop_sequence,
        'stop_id': rs.stop.stop_id,
        'stop_name': rs.stop.stop_name,
        'stop_lat': rs.stop.stop_lat,
        'stop_lon': rs.stop.stop_lon,
    } for rs in route_stops]

    return Response({
        'route_id': route_id,
        'total_stops': len(stops),
        'stops': stops
    })
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Route
from .serializers import RouteSerializer

@api_view(['GET'])
def get_all_routes(request):
    city = request.GET.get('city', 'Delhi')
    routes = Route.objects.filter(city=city)[:100]
    serializer = RouteSerializer(routes, many=True)
    return Response({
        'city': city,
        'count': routes.count(),
        'routes': serializer.data
    })

@api_view(['GET'])
def get_route_detail(request, route_id):
    try:
        route = Route.objects.get(route_id=route_id)
        serializer = RouteSerializer(route)
        return Response(serializer.data)
    except Route.DoesNotExist:
        return Response({'error': 'Route not found'}, status=404)
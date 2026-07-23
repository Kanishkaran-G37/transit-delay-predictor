from django.test import TestCase, Client

from routes.models import Route
from stops.models import Stop, RouteStop
from stops.views import haversine_distance


class HaversineTests(TestCase):
    def test_zero_distance(self):
        self.assertAlmostEqual(haversine_distance(28.6, 77.2, 28.6, 77.2), 0, places=5)

    def test_known_distance(self):
        """~1 degree of latitude is ~111 km."""
        d = haversine_distance(28.0, 77.0, 29.0, 77.0)
        self.assertAlmostEqual(d, 111, delta=2)


class StopApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        route = Route.objects.create(route_id='R1', route_short_name='1',
                                     route_long_name='Test Line', city='Delhi')
        # Roughly 1 km apart along longitude at this latitude.
        near = Stop.objects.create(stop_id='S1', stop_name='Near Stop',
                                   stop_lat=28.6000, stop_lon=77.2000)
        far = Stop.objects.create(stop_id='S2', stop_name='Far Stop',
                                  stop_lat=28.7000, stop_lon=77.2000)  # ~11 km
        RouteStop.objects.create(route=route, stop=near, stop_sequence=0)
        RouteStop.objects.create(route=route, stop=far, stop_sequence=1)

    def setUp(self):
        self.client = Client()

    def test_nearby_respects_radius(self):
        r = self.client.get('/api/stops/nearby/',
                            {'lat': 28.6, 'lng': 77.2, 'radius_km': 2})
        self.assertEqual(r.status_code, 200)
        names = [s['stop_name'] for s in r.json()['stops']]
        self.assertIn('Near Stop', names)
        self.assertNotIn('Far Stop', names)

    def test_wider_radius_includes_more(self):
        r = self.client.get('/api/stops/nearby/',
                            {'lat': 28.6, 'lng': 77.2, 'radius_km': 20})
        self.assertEqual(r.json()['count'], 2)

    def test_nearby_requires_coordinates(self):
        r = self.client.get('/api/stops/nearby/')
        self.assertEqual(r.status_code, 400)

    def test_route_stops_are_ordered(self):
        r = self.client.get('/api/stops/route/R1/')
        self.assertEqual(r.status_code, 200)
        stops = r.json()['stops']
        self.assertEqual([s['sequence'] for s in stops], [0, 1])
        self.assertEqual(stops[0]['stop_name'], 'Near Stop')

    def test_unknown_route_returns_404(self):
        r = self.client.get('/api/stops/route/NOPE/')
        self.assertEqual(r.status_code, 404)

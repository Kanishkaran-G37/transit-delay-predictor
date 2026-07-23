from django.test import TestCase, Client

from routes.models import Route


class RouteApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Route.objects.create(route_id='T1', route_short_name='1',
                             route_long_name='Test Line UP', city='Delhi')
        Route.objects.create(route_id='T2', route_short_name='2',
                             route_long_name='Test Line DOWN', city='Delhi')
        Route.objects.create(route_id='T3', route_short_name='3',
                             route_long_name='Elsewhere', city='Mumbai')

    def setUp(self):
        self.client = Client()

    def test_lists_routes_for_city(self):
        r = self.client.get('/api/routes/', {'city': 'Delhi'})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['count'], 2)
        self.assertEqual({x['route_id'] for x in data['routes']}, {'T1', 'T2'})

    def test_city_filter_excludes_others(self):
        r = self.client.get('/api/routes/', {'city': 'Mumbai'})
        self.assertEqual(r.json()['count'], 1)

    def test_route_detail(self):
        r = self.client.get('/api/routes/T1/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['route_long_name'], 'Test Line UP')

    def test_missing_route_returns_404(self):
        r = self.client.get('/api/routes/NOPE/')
        self.assertEqual(r.status_code, 404)

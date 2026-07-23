"""Tests for the delay predictor, journey planner, realtime feed and APIs."""
import datetime as dt
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client

from services.prediction_service import predict_delay
from services import journey_service as js
from services.journey_service import plan_journey, _fmt_clock, _delay_text


# ── Delay prediction ─────────────────────────────────────────────────────────
class PredictionServiceTests(TestCase):
    def test_eta_never_exceeds_23_hours(self):
        """Regression: ETA used to print '24:10' when a delay crossed midnight."""
        with patch('services.prediction_service.datetime') as m:
            m.now.return_value = dt.datetime(2026, 1, 1, 23, 50, 0)
            result = predict_delay('Rain', 30, 70, 3, 'high', 20)
        hour = int(result['predicted_eta'].split(':')[0])
        self.assertLess(hour, 24, f"ETA wrapped badly: {result['predicted_eta']}")

    def test_delay_is_never_negative(self):
        result = predict_delay('Clear', 28, 50, 2, 'low', 5)
        self.assertGreaterEqual(result['predicted_delay_minutes'], 0)

    def test_unseen_category_does_not_crash(self):
        """Unknown weather/traffic labels must fall back, not raise."""
        result = predict_delay('Sharknado', 28, 50, 2, 'apocalyptic', 5)
        self.assertIn('predicted_delay_minutes', result)

    def test_peak_hour_flag_matches_hour(self):
        result = predict_delay('Clear', 28, 50, 2, 'low', 5, hour=9, day_of_week=1)
        self.assertTrue(result['is_peak_hour'])
        result = predict_delay('Clear', 28, 50, 2, 'low', 5, hour=3, day_of_week=1)
        self.assertFalse(result['is_peak_hour'])


# ── Helpers ──────────────────────────────────────────────────────────────────
class HelperTests(TestCase):
    def test_clock_wraps_past_midnight(self):
        self.assertEqual(_fmt_clock(23 * 3600 + 50 * 60), '23:50')
        self.assertEqual(_fmt_clock(24 * 3600 + 10 * 60), '00:10')

    def test_delay_text_categories(self):
        self.assertEqual(_delay_text(1)[1], 'ok')
        self.assertEqual(_delay_text(6)[1], 'minor')
        self.assertEqual(_delay_text(15)[1], 'moderate')
        self.assertEqual(_delay_text(45)[1], 'severe')


# ── Journey planner ──────────────────────────────────────────────────────────
class JourneyPlannerTests(TestCase):
    """Runs against the real journey index, but picks its data dynamically."""

    @classmethod
    def setUpTestData(cls):
        cls.bus_route = next(r for r, m in js.ROUTE_MODE.items() if m == 'bus'
                             and len(js.ROUTE_STOPS[r]) > 3)
        stops = js.ROUTE_STOPS[cls.bus_route]
        cls.start, cls.end = stops[0], stops[-1]

    def test_direct_route_is_found(self):
        res = plan_journey(self.start, self.end, modes=['bus'])
        self.assertTrue(res['available'])
        self.assertTrue(res['options'], 'expected at least one option')
        self.assertTrue(any(o['transfers'] == 0 for o in res['options']))

    def test_option_shape_is_complete(self):
        opt = plan_journey(self.start, self.end, modes=['bus'])['options'][0]
        for key in ('depart', 'arrive', 'scheduled_minutes', 'delay_text', 'legs'):
            self.assertIn(key, opt)
        leg = opt['legs'][0]
        self.assertIn(leg['mode'], ('bus', 'metro', 'walk'))
        self.assertTrue(leg['geometry'], 'leg needs coordinates for the map')

    def test_journey_takes_positive_time(self):
        opt = plan_journey(self.start, self.end, modes=['bus'])['options'][0]
        self.assertGreater(opt['scheduled_minutes'], 0)

    def test_same_start_and_end_rejected(self):
        res = plan_journey(self.start, self.start, modes=['bus'])
        self.assertFalse(res['available'])

    def test_unknown_stop_rejected(self):
        res = plan_journey('definitely-not-a-stop', self.end, modes=['bus'])
        self.assertFalse(res['available'])

    def test_mode_filter_is_respected(self):
        """Bus-only planning must never return a metro leg."""
        res = plan_journey(self.start, self.end, modes=['bus'])
        for opt in res['options']:
            for leg in opt['legs']:
                self.assertNotEqual(leg['mode'], 'metro')

    def test_unloaded_mode_reports_clearly(self):
        with patch.object(js, 'MODES_LOADED', {'bus'}):
            res = plan_journey(self.start, self.end, modes=['metro'])
        self.assertFalse(res['available'])
        self.assertIn('metro', res['message'].lower())


# ── Realtime feed ────────────────────────────────────────────────────────────
class RealtimeServiceTests(TestCase):
    def _feed_bytes(self):
        from google.transit import gtfs_realtime_pb2
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = '2.0'
        feed.header.timestamp = 1000
        e = feed.entity.add()
        e.id = '1'
        v = e.vehicle
        v.trip.trip_id = 'T1'
        v.trip.route_id = '142'
        v.position.latitude = 28.61
        v.position.longitude = 77.20
        v.position.speed = 10.0          # m/s -> 36 km/h
        v.timestamp = 1000
        return feed.SerializeToString()

    def test_parses_vehicle_positions(self):
        from services import realtime_service as rt
        resp = MagicMock(content=self._feed_bytes())
        resp.raise_for_status.return_value = None
        with patch.object(rt, 'OTD_API_KEY', 'testkey'), \
                patch.object(rt.requests, 'get', return_value=resp):
            out = rt.get_live_vehicles()
        self.assertEqual(out['source'], 'live')
        self.assertEqual(len(out['vehicles']), 1)
        self.assertAlmostEqual(out['vehicles'][0]['speed_kmh'], 36.0, places=1)

    def test_route_filter(self):
        from services import realtime_service as rt
        resp = MagicMock(content=self._feed_bytes())
        resp.raise_for_status.return_value = None
        with patch.object(rt, 'OTD_API_KEY', 'testkey'), \
                patch.object(rt.requests, 'get', return_value=resp):
            out = rt.get_live_vehicles(route_id='999')
        self.assertEqual(out['matched'], 0)
        self.assertEqual(out['total_in_feed'], 1)

    def test_missing_key_is_graceful(self):
        from services import realtime_service as rt
        with patch.object(rt, 'OTD_API_KEY', None):
            out = rt.get_live_vehicles()
        self.assertEqual(out['source'], 'no_key')
        self.assertEqual(out['vehicles'], [])


# ── HTTP API ─────────────────────────────────────────────────────────────────
FAKE_WEATHER = {'weather_condition': 'Clear', 'temperature': 30.0,
                'humidity': 60, 'wind_speed': 2.0, 'source': 'fallback'}
FAKE_TRAFFIC = {'traffic_level': 'medium', 'source': 'fallback'}


class ApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        route = next(r for r, m in js.ROUTE_MODE.items() if m == 'bus'
                     and len(js.ROUTE_STOPS[r]) > 3)
        stops = js.ROUTE_STOPS[route]
        self.start, self.end = stops[0], stops[-1]

    def test_stops_list_search(self):
        r = self.client.get('/api/stops-list/', {'q': 'terminal'})
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.json()['count'], 0)

    @patch('predictions.views.get_traffic_level', return_value=FAKE_TRAFFIC)
    @patch('predictions.views.get_weather', return_value=FAKE_WEATHER)
    def test_journey_endpoint(self, _w, _t):
        r = self.client.get('/api/journey/',
                            {'start': self.start, 'end': self.end, 'modes': 'bus'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['options'])

    @patch('predictions.views.get_traffic_level', return_value=FAKE_TRAFFIC)
    @patch('predictions.views.get_weather', return_value=FAKE_WEATHER)
    def test_journey_requires_both_stops(self, _w, _t):
        r = self.client.get('/api/journey/', {'start': self.start})
        self.assertEqual(r.status_code, 400)

    def test_vehicles_endpoint_without_key(self):
        from services import realtime_service as rt
        with patch.object(rt, 'OTD_API_KEY', None):
            r = self.client.get('/api/vehicles/', {'route_id': '142'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['source'], 'no_key')

    def test_pwa_is_served(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'manifest.webmanifest', r.content)

    def test_manifest_content_type(self):
        r = self.client.get('/manifest.webmanifest')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/manifest+json')

import requests
import os
from dotenv import load_dotenv

load_dotenv()

TOMTOM_API_KEY = os.getenv('TOMTOM_API_KEY')

def get_traffic_level(lat, lon):
    """Get traffic conditions at a location"""
    try:
        url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
        params = {
            'point': f"{lat},{lon}",
            'key': TOMTOM_API_KEY
        }
        response = requests.get(url, params=params, timeout=5)
        data = response.json()

        flow = data['flowSegmentData']
        current_speed = flow['currentSpeed']
        free_flow_speed = flow['freeFlowSpeed']

        # Calculate congestion ratio
        ratio = current_speed / free_flow_speed if free_flow_speed > 0 else 1.0

        if ratio >= 0.8:
            level = 'low'
            delay_factor = 1.0
        elif ratio >= 0.5:
            level = 'medium'
            delay_factor = 1.5
        else:
            level = 'high'
            delay_factor = 2.5

        return {
            'current_speed_kmh': current_speed,
            'free_flow_speed_kmh': free_flow_speed,
            'congestion_ratio': round(ratio, 2),
            'traffic_level': level,
            'delay_factor': delay_factor,
            'source': 'live'
        }
    except Exception as e:
        return {
            'current_speed_kmh': 30,
            'free_flow_speed_kmh': 50,
            'congestion_ratio': 0.6,
            'traffic_level': 'medium',
            'delay_factor': 1.5,
            'source': 'fallback',
            'error': str(e)
        }
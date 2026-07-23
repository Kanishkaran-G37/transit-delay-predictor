import requests
import os
from dotenv import load_dotenv

load_dotenv()

OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')

def get_weather(city='Delhi'):
    """Get current weather for a city"""
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather"
        params = {
            'q': city,
            'appid': OPENWEATHER_API_KEY,
            'units': 'metric'
        }
        response = requests.get(url, params=params, timeout=5)
        data = response.json()

        return {
            'city': city,
            'temperature': data['main']['temp'],
            'feels_like': data['main']['feels_like'],
            'humidity': data['main']['humidity'],
            'weather_condition': data['weather'][0]['main'],
            'weather_description': data['weather'][0]['description'],
            'wind_speed': data['wind']['speed'],
            'visibility': data.get('visibility', 10000) / 1000,  # convert to km
            'source': 'live'
        }
    except Exception as e:
        # Fallback if API fails
        return {
            'city': city,
            'temperature': 30.0,
            'feels_like': 33.0,
            'humidity': 60,
            'weather_condition': 'Clear',
            'weather_description': 'clear sky',
            'wind_speed': 2.0,
            'visibility': 10.0,
            'source': 'fallback',
            'error': str(e)
        }
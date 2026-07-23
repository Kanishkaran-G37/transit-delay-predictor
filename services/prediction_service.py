import joblib
import os
import numpy as np
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, 'ml', 'model.joblib')
ENCODER_PATH = os.path.join(BASE_DIR, 'ml', 'encoders.joblib')

# Load model once when server starts
model = joblib.load(MODEL_PATH)
encoders = joblib.load(ENCODER_PATH)

def predict_delay(weather_condition, temperature, humidity,
                  wind_speed, traffic_level, num_stops,
                  city='Delhi', hour=None, day_of_week=None):
    """Predict bus delay in minutes"""

    now = datetime.now()
    hour = hour if hour is not None else now.hour
    day_of_week = day_of_week if day_of_week is not None else now.weekday()

    # Handle unseen labels safely
    def safe_encode(encoder, value, fallback=0):
        if value in encoder.classes_:
            return encoder.transform([value])[0]
        return fallback

    weather_enc = safe_encode(encoders['weather'], weather_condition)
    traffic_enc = safe_encode(encoders['traffic'], traffic_level)
    city_enc = safe_encode(encoders['city'], city)

    features = [[
        hour,
        day_of_week,
        1 if hour in [8, 9, 10, 17, 18, 19, 20] else 0,
        1 if day_of_week >= 5 else 0,
        weather_enc,
        temperature,
        humidity,
        wind_speed,
        traffic_enc,
        num_stops,
        city_enc
    ]]

    predicted_delay = float(model.predict(features)[0])
    predicted_delay = max(0, round(predicted_delay, 1))

    # Calculate ETA
    now_str = now.strftime('%H:%M')
    eta_minutes = now.minute + int(predicted_delay)
    eta_hour = now.hour + eta_minutes // 60
    eta_min = eta_minutes % 60
    eta_str = f"{eta_hour:02d}:{eta_min:02d}"

    return {
        'predicted_delay_minutes': predicted_delay,
        'current_time': now_str,
        'predicted_eta': eta_str,
        'hour_of_day': hour,
        'day_of_week': day_of_week,
        'is_peak_hour': hour in [8, 9, 10, 17, 18, 19, 20],
        'inputs': {
            'weather_condition': weather_condition,
            'temperature': temperature,
            'humidity': humidity,
            'wind_speed': wind_speed,
            'traffic_level': traffic_level,
            'num_stops': num_stops,
            'city': city
        }
    }
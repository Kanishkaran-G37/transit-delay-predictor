import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import LabelEncoder
import joblib
import os

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, 'ml', 'data')
MODEL_PATH = os.path.join(BASE_DIR, 'ml', 'model.joblib')
ENCODER_PATH = os.path.join(BASE_DIR, 'ml', 'encoders.joblib')

# ── Step 1: Generate Realistic Training Data ────────────────────────────────
def generate_training_data(n=5000):
    print("Generating training data...")
    np.random.seed(42)

    weather_conditions = ['Clear', 'Clouds', 'Rain', 'Fog', 'Haze', 'Thunderstorm']
    traffic_levels = ['low', 'medium', 'high']
    cities = ['Delhi']

    data = []
    for _ in range(n):
        hour = np.random.randint(0, 24)
        day_of_week = np.random.randint(0, 7)  # 0=Monday, 6=Sunday
        weather = np.random.choice(weather_conditions,
                                   p=[0.35, 0.25, 0.15, 0.10, 0.10, 0.05])
        temperature = np.random.normal(28, 8)
        humidity = np.random.randint(30, 95)
        wind_speed = np.random.uniform(0, 20)
        traffic = np.random.choice(traffic_levels,
                                   p=[0.3, 0.4, 0.3])
        num_stops = np.random.randint(5, 40)
        city = 'Delhi'

        # ── Delay calculation (realistic rules) ───────────────────────────
        delay = 2.0  # base delay in minutes

        # Peak hours add delay
        if hour in [8, 9, 10, 17, 18, 19, 20]:
            delay += np.random.uniform(5, 15)
        elif hour in [7, 11, 16, 21]:
            delay += np.random.uniform(2, 7)
        else:
            delay += np.random.uniform(0, 3)

        # Weekday vs weekend
        if day_of_week < 5:  # weekday
            delay += np.random.uniform(1, 4)

        # Weather impact
        weather_delay = {
            'Clear': 0,
            'Clouds': 1,
            'Haze': 2,
            'Fog': np.random.uniform(5, 12),
            'Rain': np.random.uniform(8, 20),
            'Thunderstorm': np.random.uniform(15, 30)
        }
        delay += weather_delay[weather]

        # Traffic impact
        traffic_delay = {
            'low': np.random.uniform(0, 2),
            'medium': np.random.uniform(3, 8),
            'high': np.random.uniform(10, 25)
        }
        delay += traffic_delay[traffic]

        # Temperature extremes (very hot = more delay)
        if temperature > 42:
            delay += np.random.uniform(3, 8)
        elif temperature < 5:
            delay += np.random.uniform(2, 5)

        # More stops = more delay
        delay += num_stops * 0.15

        # Add some noise
        delay += np.random.normal(0, 1.5)
        delay = max(0, round(delay, 2))

        data.append({
            'hour_of_day': hour,
            'day_of_week': day_of_week,
            'is_peak_hour': 1 if hour in [8, 9, 10, 17, 18, 19, 20] else 0,
            'is_weekend': 1 if day_of_week >= 5 else 0,
            'weather_condition': weather,
            'temperature': round(temperature, 1),
            'humidity': humidity,
            'wind_speed': round(wind_speed, 1),
            'traffic_level': traffic,
            'num_stops': num_stops,
            'city': city,
            'delay_minutes': delay
        })

    df = pd.DataFrame(data)
    df.to_csv(os.path.join(DATA_PATH, 'training_data.csv'), index=False)
    print(f"✅ Generated {len(df)} training samples")
    print(f"   Average delay: {df['delay_minutes'].mean():.1f} minutes")
    print(f"   Max delay: {df['delay_minutes'].max():.1f} minutes")
    return df

# ── Step 2: Train the Model ─────────────────────────────────────────────────
def train_model(df):
    print("\nTraining ML model...")

    # Encode categorical columns
    le_weather = LabelEncoder()
    le_traffic = LabelEncoder()
    le_city = LabelEncoder()

    df['weather_encoded'] = le_weather.fit_transform(df['weather_condition'])
    df['traffic_encoded'] = le_traffic.fit_transform(df['traffic_level'])
    df['city_encoded'] = le_city.fit_transform(df['city'])

    # Features
    features = [
        'hour_of_day', 'day_of_week', 'is_peak_hour', 'is_weekend',
        'weather_encoded', 'temperature', 'humidity', 'wind_speed',
        'traffic_encoded', 'num_stops', 'city_encoded'
    ]

    X = df[features]
    y = df['delay_minutes']

    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # Train Model A — Without traffic
    print("\n--- Model A: Without Traffic Features ---")
    features_no_traffic = [f for f in features if 'traffic' not in f]
    X_train_a = X_train[features_no_traffic]
    X_test_a = X_test[features_no_traffic]
    model_a = RandomForestRegressor(n_estimators=100, random_state=42)
    model_a.fit(X_train_a, y_train)
    pred_a = model_a.predict(X_test_a)
    print(f"MAE:  {mean_absolute_error(y_test, pred_a):.2f} minutes")
    print(f"RMSE: {np.sqrt(mean_squared_error(y_test, pred_a)):.2f} minutes")
    print(f"R²:   {r2_score(y_test, pred_a):.3f}")

    # Train Model B — With traffic (MAIN model)
    print("\n--- Model B: With Traffic Features (MAIN MODEL) ---")
    model_b = RandomForestRegressor(n_estimators=100, random_state=42)
    model_b.fit(X_train, y_train)
    pred_b = model_b.predict(X_test)
    mae = mean_absolute_error(y_test, pred_b)
    rmse = np.sqrt(mean_squared_error(y_test, pred_b))
    r2 = r2_score(y_test, pred_b)
    print(f"MAE:  {mae:.2f} minutes")
    print(f"RMSE: {rmse:.2f} minutes")
    print(f"R²:   {r2:.3f}")

    print(f"\n✅ Traffic features improve prediction!")
    print(f"   MAE improvement: {mean_absolute_error(y_test, pred_a) - mae:.2f} minutes")

    # Save model and encoders
    joblib.dump(model_b, MODEL_PATH)
    joblib.dump({
        'weather': le_weather,
        'traffic': le_traffic,
        'city': le_city,
        'features': features
    }, ENCODER_PATH)

    print(f"\n✅ Model saved to {MODEL_PATH}")
    return model_b, features

if __name__ == '__main__':
    df = generate_training_data(5000)
    model, features = train_model(df)
    print("\n🎉 ML model trained and saved!")
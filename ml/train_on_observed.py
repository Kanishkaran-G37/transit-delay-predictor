"""Train the delay model on REAL observed delays (ml/data/observed_delays.csv),
replacing the synthetic model. Saves model.joblib + encoders.joblib in the same
format as train_model.py, so services/prediction_service.py uses it unchanged.

    python ml/train_on_observed.py

Collect data first with ingestion/log_delays.py (run it on a schedule for days).
"""
import os
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import LabelEncoder

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, 'ml', 'data', 'observed_delays.csv')
MODEL_PATH = os.path.join(BASE_DIR, 'ml', 'model.joblib')
ENCODER_PATH = os.path.join(BASE_DIR, 'ml', 'encoders.joblib')

MIN_ROWS = 500  # below this the model isn't worth trusting

# Feature order MUST match services/prediction_service.py.
FEATURES = ['hour_of_day', 'day_of_week', 'is_peak_hour', 'is_weekend',
            'weather_encoded', 'temperature', 'humidity', 'wind_speed',
            'traffic_encoded', 'num_stops', 'city_encoded']


def train(df):
    """Fit the model on an observed-delays dataframe. Returns (model, encoders, metrics)."""
    df = df.copy()
    le_weather, le_traffic, le_city = LabelEncoder(), LabelEncoder(), LabelEncoder()
    df['weather_encoded'] = le_weather.fit_transform(df['weather_condition'].astype(str))
    df['traffic_encoded'] = le_traffic.fit_transform(df['traffic_level'].astype(str))
    df['city_encoded'] = le_city.fit_transform(df['city'].astype(str))

    X, y = df[FEATURES], df['delay_minutes']
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42)

    model = RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    pred = model.predict(X_test)

    metrics = {
        'n': len(df),
        'mae': mean_absolute_error(y_test, pred),
        'rmse': float(np.sqrt(mean_squared_error(y_test, pred))),
        'r2': r2_score(y_test, pred),
    }
    encoders = {'weather': le_weather, 'traffic': le_traffic, 'city': le_city,
                'features': FEATURES}
    return model, encoders, metrics


def main():
    if not os.path.exists(CSV_PATH):
        print(f"No observed data yet at {CSV_PATH}. Run ingestion/log_delays.py first.")
        return
    df = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df):,} observations.")
    if len(df) < MIN_ROWS:
        print(f"WARNING: only {len(df)} rows (< {MIN_ROWS}). Keep logging before "
              "trusting this model.")

    model, encoders, m = train(df)
    print(f"  MAE:  {m['mae']:.2f} min")
    print(f"  RMSE: {m['rmse']:.2f} min")
    print(f"  R2:   {m['r2']:.3f}")

    joblib.dump(model, MODEL_PATH)
    joblib.dump(encoders, ENCODER_PATH)
    print(f"[OK] Saved real-data model -> {MODEL_PATH}")


if __name__ == '__main__':
    main()

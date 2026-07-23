# 🚌 Delhi Transit Journey Planner

A multi-modal (bus + metro) transit journey planner for Delhi, with a live map
and an ML delay estimate. Django REST backend + Streamlit frontend, built on
Delhi Open Transit Data (GTFS).

## Features

- **Journey planning** between any two stops — direct, 1-transfer, and
  2-transfer routes, with real scheduled departure/arrival times.
- **Bus + Metro** — routes over DTC/DIMTS buses (2,403 routes) and the Delhi
  Metro network (36 lines, 262 stations). Pick Bus, Train, or both.
- **Live map** — an embedded Leaflet map that polls bus positions
  (GTFS-Realtime) every few seconds and moves markers *in place*, with no
  page reload.
- **ML delay estimate** — a Random Forest predicts a delay per journey from
  weather + traffic + time-of-day (see "Known limitations").

## Architecture

```
config/          Django project (settings, urls, CORS middleware)
routes/ stops/    GTFS route & stop models + APIs
predictions/      journey, live-vehicles, weather, traffic, prediction APIs
services/         weather, traffic, realtime (GTFS-RT), journey planner, ML predict
ingestion/        load_gtfs.py (DB) + build_journey_index.py (planner index)
ml/               train_model.py + generated model/encoders
frontend/app.py   Streamlit UI (planner + live map)
```

## Setup

```bash
python -m venv venv
venv\Scripts\activate            # Windows;  source venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env             # optional API keys (app works without them)
```

### Data (not committed — download from OTD)

GTFS data is large and under [OTD](https://otd.delhi.gov.in) usage terms, so
it lives outside git.

1. **Buses** — download the DTC/DIMTS static GTFS and extract the `.txt` files
   into `ml/data/`.
2. **Metro** — download the DMRC static GTFS from
   [otd.delhi.gov.in/data/staticDMRC](https://otd.delhi.gov.in/data/staticDMRC/)
   (free usage form) and extract into `ml/data/dmrc/`.

Then build everything:

```bash
python manage.py migrate
python ingestion/load_gtfs.py          # load routes/stops into the DB
python ml/train_model.py               # train the delay model
python ingestion/build_journey_index.py  # build the journey planner index
```

`build_journey_index.py` prints `modes loaded : bus, metro` when both feeds
are present (metro is skipped cleanly if `ml/data/dmrc/` is absent).

## Run

Two terminals (venv activated in each):

```bash
python manage.py runserver           # backend on :8000
streamlit run frontend/app.py        # frontend on :8501
```

> The backend loads the journey index into memory at startup — **restart it
> after rebuilding the index** to pick up new data.

## Making the delay model real (measured delays)

The default delay model is trained on synthetic rules. To train it on *real*
observed delays, we derive schedule adherence ourselves — Delhi OTD publishes
**only** GTFS-Realtime VehiclePositions, with no TripUpdates feed.

> ⚠️ **Prerequisite: a fresh bus GTFS.** The logger can only measure a bus whose
> `trip_id` exists in `ml/data/trips.txt`. With a stale export only ~1% of live
> trips match and the resulting delays are meaningless. Re-download the current
> bus static GTFS from https://otd.delhi.gov.in before collecting data.

1. Set `OTD_API_KEY` in `.env` (free: https://otd.delhi.gov.in).
2. **Collect data** — run the logger on a schedule (e.g. every 5 min) for
   several days so it accumulates thousands of real observations:
   ```bash
   python ingestion/log_delays.py     # appends to ml/data/observed_delays.csv
   ```
3. **Retrain** on the collected data (saves in the same format, so the app
   uses it with no code change):
   ```bash
   python ml/train_on_observed.py
   ```
   Restart the backend to load the new model.

## Known limitations

- **Delay model ships synthetic** — trained on rule-generated data and reused
  for metro. Routing and times are real. The pipeline above replaces it with a
  model trained on measured delays once you've collected enough data.
- **Mixed bus↔metro trips** use short walking transfers between nearby stops
  (≤400m). Walking transfers are cross-mode only; long walks and 3+ leg mixed
  trips aren't modelled.

from __future__ import annotations

import json
import os
from datetime import datetime

from flask import Flask, redirect, jsonify, render_template, request, url_for
from influxdb_client import InfluxDBClient


INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "srh-utility-knife-token"
INFLUX_ORG = "srh"
INFLUX_BUCKET = "production"

WORK_ORDER_FILE = "work_orders.json"

WEAR_LIMIT = 0.10
DEFECT_LIMIT = 0.22

STATIONS = ["Handle", "Blade", "LockSlider", "BeltClip"]

STATE_NAMES = {
    0: "IDLE",
    1: "RUNNING",
    2: "FAULTED",
}

app = Flask(__name__)


def load_work_orders() -> list[dict]:
    if not os.path.exists(WORK_ORDER_FILE):
        return []

    with open(WORK_ORDER_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_work_orders(work_orders: list[dict]) -> None:
    with open(WORK_ORDER_FILE, "w", encoding="utf-8") as file:
        json.dump(work_orders, file, indent=2)


def create_work_order(station: str, reason: str, priority: str, notes: str = "") -> None:
    work_orders = load_work_orders()
    new_id = max([order["id"] for order in work_orders], default=0) + 1

    work_orders.append({
        "id": new_id,
        "station": station,
        "reason": reason,
        "priority": priority,
        "notes": notes,
        "status": "OPEN",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "closed_at": "",
    })

    save_work_orders(work_orders)


def query_latest_field(field: str, station: str | None = None):
    station_filter = ""

    if station is not None:
        station_filter = f'|> filter(fn: (r) => r.station == "{station}")'

    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "line")
  |> filter(fn: (r) => r._field == "{field}")
  {station_filter}
  |> last()
'''

    try:
        with InfluxDBClient(
            url=INFLUX_URL,
            token=INFLUX_TOKEN,
            org=INFLUX_ORG,
        ) as client:
            tables = client.query_api().query(flux, org=INFLUX_ORG)

        for table in tables:
            for record in table.records:
                return record.get_value()

    except Exception as exc:
        print(f"[CMMS] InfluxDB query failed for field={field}: {exc}")

    return None


def get_line_status() -> dict:
    state_value = query_latest_field("state")
    state_num = int(state_value) if state_value is not None else 0

    return {
        "state": STATE_NAMES.get(state_num, "UNKNOWN"),
        "temp_moulding": query_latest_field("temp_moulding"),
        "temp_furnace": query_latest_field("temp_furnace"),
        "parts_produced": query_latest_field("parts_produced"),
        "parts_shipped": query_latest_field("parts_shipped"),
        "parts_rejected": query_latest_field("parts_rejected"),
        "maintenance_count": query_latest_field("maintenance_count"),
    }


def get_station_status() -> list[dict]:
    station_cards = []

    for station in STATIONS:
        wear = query_latest_field("wear", station)
        defect_rate = query_latest_field("defect_rate", station)

        wear = float(wear) if wear is not None else 0.0
        defect_rate = float(defect_rate) if defect_rate is not None else 0.0

        if wear >= WEAR_LIMIT or defect_rate >= DEFECT_LIMIT:
            condition = "MAINTENANCE REQUIRED"
            css_class = "danger"
            priority = "HIGH"
        elif wear >= WEAR_LIMIT * 0.75 or defect_rate >= DEFECT_LIMIT * 0.75:
            condition = "WATCH"
            css_class = "warn"
            priority = "MEDIUM"
        else:
            condition = "OK"
            css_class = "ok"
            priority = "LOW"

        station_cards.append({
            "name": station,
            "wear": wear,
            "wear_pct": wear * 100,
            "defect_rate": defect_rate,
            "defect_pct": defect_rate * 100,
            "condition": condition,
            "css_class": css_class,
            "priority": priority,
        })

    return station_cards


@app.route("/")
def index():
    line = get_line_status()
    stations = get_station_status()
    work_orders = load_work_orders()

    open_orders = [order for order in work_orders if order["status"] == "OPEN"]
    closed_orders = [order for order in work_orders if order["status"] == "CLOSED"]

    return render_template(
        "cmms_dashboard.html",
        line=line,
        stations=stations,
        open_orders=open_orders,
        closed_orders=closed_orders,
        wear_limit=WEAR_LIMIT,
        defect_limit=DEFECT_LIMIT,
    )

@app.route("/api/status")         # creates a small API endpoint that JavaScript can call in the background.
def api_status():
    line = get_line_status()
    stations = get_station_status()

    return jsonify({
        "line": line,
        "stations": stations,
    })


@app.route("/workorder/create", methods=["POST"])
def create_order():
    create_work_order(
        station=request.form["station"],
        reason=request.form["reason"],
        priority=request.form["priority"],
        notes=request.form.get("notes", "").strip(),
    )

    return redirect(url_for("index"))


@app.route("/workorder/close/<int:order_id>", methods=["POST"])
def close_order(order_id: int):
    work_orders = load_work_orders()

    for order in work_orders:
        if order["id"] == order_id:
            order["status"] = "CLOSED"
            order["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break

    save_work_orders(work_orders)

    return redirect(url_for("index"))


@app.route("/workorder/delete/<int:order_id>", methods=["POST"])
def delete_order(order_id: int):
    work_orders = load_work_orders()

    work_orders = [
        order for order in work_orders
        if not (order["id"] == order_id and order["status"] == "CLOSED")
    ]

    save_work_orders(work_orders)

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5050)
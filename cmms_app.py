from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from flask import Flask, jsonify, redirect, render_template, request, url_for
from influxdb_client import InfluxDBClient

from cmms_db import (
    init_db,
    list_spare_parts,
    add_spare_part,
    list_work_orders,
    create_work_order as db_create_work_order,
    close_work_order as db_close_work_order,
    list_schedule,
)


# ─────────────────────────────────────────────────────────────
# InfluxDB settings — must match docker-compose.yml and producer.py
# ─────────────────────────────────────────────────────────────

INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "srh-utility-knife-token"
INFLUX_ORG = "srh"
INFLUX_BUCKET = "production"


# ─────────────────────────────────────────────────────────────
# Local CMMS storage files
# ─────────────────────────────────────────────────────────────

WORK_ORDER_FILE = "work_orders.json"
PARTS_FILE = "parts.json"


# ─────────────────────────────────────────────────────────────
# CMMS thresholds
# ─────────────────────────────────────────────────────────────

WEAR_LIMIT = 0.10
DEFECT_LIMIT = 0.22

WEAR_WARNING = WEAR_LIMIT * 0.75
DEFECT_WARNING = DEFECT_LIMIT * 0.75

STATIONS = ["Handle", "Blade", "LockSlider", "BeltClip"]

STATION_MACHINE_NAMES = {
    "Handle": "Moulding Barrel",
    "Blade": "Heat-Treat Furnace",
    "LockSlider": "Lock Slider Assembly Press",
    "BeltClip": "Belt Clip Forming Press",
}


STATE_NAMES = {
    0: "IDLE",
    1: "RUNNING",
    2: "FAULTED",
}


app = Flask(__name__)


init_db()

# ═════════════════════════════════════════════════════════════
# JSON helpers
# ═════════════════════════════════════════════════════════════

def load_json(path: str, default):
    if not os.path.exists(path):
        return default

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


# ═════════════════════════════════════════════════════════════
# Parts
# ═════════════════════════════════════════════════════════════

def default_parts() -> list[dict]:
    return [
        {
            "id": 1,
            "name": "Handle",
            "description": "Injection-moulded plastic body for the utility knife.",
            "location": "Moulding Barrel / Handle Maker",
            "part_number": "HNDL-001",
        },
        {
            "id": 2,
            "name": "Blade",
            "description": "High-carbon steel blade cartridge, heat-treated before assembly.",
            "location": "Heat-Treat Furnace / Blade Maker",
            "part_number": "BLDE-001",
        },
        {
            "id": 3,
            "name": "Lock Slider",
            "description": "Sliding locking mechanism used to secure the blade position.",
            "location": "Lock Slider Assembly Station",
            "part_number": "SLDR-001",
        },
        {
            "id": 4,
            "name": "Belt Clip",
            "description": "Spring-steel clip mounted to the knife body.",
            "location": "Belt Clip Forming Station",
            "part_number": "CLIP-001",
        },
    ]


def load_parts() -> list[dict]:
    parts = load_json(PARTS_FILE, None)

    if parts is None:
        parts = default_parts()
        save_json(PARTS_FILE, parts)

    return parts


def add_part(name: str, description: str, location: str, part_number: str) -> None:
    parts = load_parts()
    new_id = max([part["id"] for part in parts], default=0) + 1

    parts.append({
        "id": new_id,
        "name": name,
        "description": description,
        "location": location,
        "part_number": part_number,
    })

    save_json(PARTS_FILE, parts)


# ═════════════════════════════════════════════════════════════
# Work orders
# ═════════════════════════════════════════════════════════════

def load_work_orders() -> list[dict]:
    return load_json(WORK_ORDER_FILE, [])


def save_work_orders(work_orders: list[dict]) -> None:
    save_json(WORK_ORDER_FILE, work_orders)


def create_work_order(station: str, reason: str, priority: str) -> None:
    work_orders = load_work_orders()
    new_id = max([order["id"] for order in work_orders], default=0) + 1

    work_orders.append({
        "id": new_id,
        "station": station,
        "reason": reason,
        "priority": priority,
        "status": "OPEN",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "closed_at": "",
    })

    save_work_orders(work_orders)


# ═════════════════════════════════════════════════════════════
# InfluxDB helpers
# ═════════════════════════════════════════════════════════════

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
        wear_value = query_latest_field("wear", station)
        defect_value = query_latest_field("defect_rate", station)

        wear = float(wear_value) if wear_value is not None else 0.0
        defect_rate = float(defect_value) if defect_value is not None else 0.0

        if wear >= WEAR_LIMIT or defect_rate >= DEFECT_LIMIT:
            condition = "MAINTENANCE REQUIRED"
            css_class = "danger"
            priority = "HIGH"
        elif wear >= WEAR_WARNING or defect_rate >= DEFECT_WARNING:
            condition = "WATCH"
            css_class = "warn"
            priority = "MEDIUM"
        else:
            condition = "OK"
            css_class = "ok"
            priority = "LOW"

        station_cards.append({
            "name": station,
            "display_name": STATION_MACHINE_NAMES.get(station, station),

            # IMPORTANT: these two fields are needed by dashboard.html and alerts.html
            "wear": wear,
            "defect_rate": defect_rate,

            # Display values
            "wear_pct": wear * 100,
            "defect_pct": defect_rate * 100,

            "condition": condition,
            "css_class": css_class,
            "priority": priority,
        })

    return station_cards


# ═════════════════════════════════════════════════════════════
# Maintenance schedule
# ═════════════════════════════════════════════════════════════

def get_maintenance_schedule() -> list[dict]:
    today = datetime.now().date()

    schedule_data = [
        {
            "part": "Handle",
            "location": "Moulding Barrel",
            "frequency": "Every 7 days",
            "last_changed": today - timedelta(days=4),
            "next_due": today + timedelta(days=3),
            "changed_by": "Operator",
        },
        {
            "part": "Blade",
            "location": "Heat-Treat Furnace",
            "frequency": "Every 5 days",
            "last_changed": today - timedelta(days=5),
            "next_due": today,
            "changed_by": "Maintenance Team",
        },
        {
            "part": "Lock Slider",
            "location": "Assembly Station",
            "frequency": "Every 10 days",
            "last_changed": today - timedelta(days=6),
            "next_due": today + timedelta(days=4),
            "changed_by": "Operator",
        },
        {
            "part": "Belt Clip",
            "location": "Clip Forming Station",
            "frequency": "Every 14 days",
            "last_changed": today - timedelta(days=8),
            "next_due": today + timedelta(days=6),
            "changed_by": "Maintenance Team",
        },
    ]

    for item in schedule_data:
        days_left = (item["next_due"] - today).days

        if days_left < 0:
            item["status"] = "OVERDUE"
            item["css_class"] = "danger"
        elif days_left == 0:
            item["status"] = "DUE TODAY"
            item["css_class"] = "warn"
        elif days_left <= 3:
            item["status"] = "UPCOMING"
            item["css_class"] = "warn"
        else:
            item["status"] = "OK"
            item["css_class"] = "ok"

        item["last_changed"] = item["last_changed"].strftime("%Y-%m-%d")
        item["next_due"] = item["next_due"].strftime("%Y-%m-%d")

    return schedule_data


# ═════════════════════════════════════════════════════════════
# Alerts
# ═════════════════════════════════════════════════════════════

def get_alerts() -> list[dict]:
    alerts = []

    for station in get_station_status():
        if station["wear"] >= WEAR_LIMIT:
            alerts.append({
                "level": "CRITICAL",
                "station": station["display_name"],
                "message": f"Tool wear is too high: {station['wear_pct']:.2f}%",
                "recommendation": "Create preventive maintenance work order.",
                "css_class": "danger",
            })

        elif station["wear"] >= WEAR_WARNING:
            alerts.append({
                "level": "WARNING",
                "station": station["display_name"],
                "message": f"Tool wear is approaching the limit: {station['wear_pct']:.2f}%",
                "recommendation": "Monitor this station closely.",
                "css_class": "warn",
            })

        if station["defect_rate"] >= DEFECT_LIMIT:
            alerts.append({
                "level": "CRITICAL",
                "station": station["display_name"],
                "message": f"Defect rate is too high: {station['defect_pct']:.1f}%",
                "recommendation": "Inspect process quality and create corrective work order.",
                "css_class": "danger",
            })

        elif station["defect_rate"] >= DEFECT_WARNING:
            alerts.append({
                "level": "WARNING",
                "station": station["display_name"],
                "message": f"Defect rate is approaching the limit: {station['defect_pct']:.1f}%",
                "recommendation": "Check material batch, tooling, and QC results.",
                "css_class": "warn",
            })

    return alerts


# ═════════════════════════════════════════════════════════════
# Routes
# ═════════════════════════════════════════════════════════════


@app.route("/api/status")
def api_status():
    line = get_line_status()
    stations = get_station_status()

    return jsonify({
        "line": line,
        "stations": stations,
    })


@app.route("/")
def dashboard():
    line = get_line_status()
    stations = get_station_status()
    work_orders = list_work_orders()
    schedule = list_schedule()

    open_orders = [order for order in work_orders if order["status"] == "OPEN"]
    overdue = [item for item in schedule if item["status"] == "OVERDUE"]
    upcoming = [item for item in schedule if item["status"] in ["DUE TODAY", "UPCOMING"]]

    return render_template(
        "dashboard.html",
        active_page="dashboard",
        line=line,
        stations=stations,
        open_orders=open_orders,
        total_parts=len(list_spare_parts()),
        overdue_count=len(overdue),
        upcoming_count=len(upcoming),
    )


@app.route("/parts")
def parts():
    return render_template(
        "parts.html",
        active_page="parts",
        parts=list_spare_parts(),
    )


@app.route("/parts/add", methods=["GET", "POST"])
def add_part_route():
    if request.method == "POST":
        add_spare_part(
            name=request.form["name"],
            description=request.form["description"],
            machine=request.form["machine"],
            part_number=request.form["part_number"],
            quantity=int(request.form["quantity"]),
            supplier=request.form["supplier"],
        )

        return redirect(url_for("parts"))

    return render_template(
        "add_part.html",
        active_page="parts",
    )



@app.route("/maintenance")
def maintenance():
    work_orders = list_work_orders()
    schedule = list_schedule()

    open_orders = [order for order in work_orders if order["status"] == "OPEN"]
    closed_orders = [order for order in work_orders if order["status"] == "CLOSED"]

    return render_template(
        "maintenance.html",
        active_page="maintenance",
        schedule=schedule,
        open_orders=open_orders,
        closed_orders=closed_orders,
    )



@app.route("/alerts")
def alerts():
    return render_template(
        "alerts.html",
        active_page="alerts",
        alerts=get_alerts(),
    )


@app.route("/workorder/create", methods=["POST"])
def create_order():
    db_create_work_order(
        machine=request.form["station"],
        reason=request.form["reason"],
        priority=request.form["priority"],
        requested_by=request.form.get("requested_by", "Operator"),
        assigned_to=request.form.get("assigned_to", "Maintenance Team"),
        notes=request.form.get("notes", ""),
    )

    return redirect(request.referrer or url_for("dashboard"))


@app.route("/workorder/close/<int:order_id>", methods=["POST"])
def close_order(order_id: int):
    db_close_work_order(
        order_id=order_id,
        notes=request.form.get("closing_notes", ""),
    )

    return redirect(request.referrer or url_for("maintenance"))


if __name__ == "__main__":
    app.run(debug=True, port=5050)
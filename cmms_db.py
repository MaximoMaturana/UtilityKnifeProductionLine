from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


DB_PATH = Path("cmms.sqlite3")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS spare_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                machine TEXT NOT NULL,
                part_number TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                supplier TEXT,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS work_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine TEXT NOT NULL,
                reason TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                requested_by TEXT,
                assigned_to TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                closed_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS maintenance_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine TEXT NOT NULL,
                task TEXT NOT NULL,
                frequency TEXT NOT NULL,
                last_done TEXT NOT NULL,
                next_due TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                notes TEXT
            )
        """)

        conn.commit()

    seed_defaults()


def seed_defaults() -> None:
    with get_connection() as conn:
        part_count = conn.execute("SELECT COUNT(*) FROM spare_parts").fetchone()[0]
        schedule_count = conn.execute("SELECT COUNT(*) FROM maintenance_schedule").fetchone()[0]

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.now().date()

        if part_count == 0:
            default_parts = [
                (
                    "Heater Cartridge",
                    "Replacement heater cartridge for the moulding barrel.",
                    "Moulding Barrel",
                    "MB-HEAT-001",
                    2,
                    "SRH Demo Supplier",
                    now,
                ),
                (
                    "Thermocouple Sensor",
                    "Temperature sensor used for moulding barrel monitoring.",
                    "Moulding Barrel",
                    "MB-TEMP-001",
                    3,
                    "SRH Demo Supplier",
                    now,
                ),
                (
                    "Furnace Heating Element",
                    "Heating element for the blade heat-treatment furnace.",
                    "Heat-Treat Furnace",
                    "HTF-HEAT-001",
                    1,
                    "SRH Demo Supplier",
                    now,
                ),
                (
                    "Blade Cutting Die",
                    "Precision die used for blade cutting and preparation.",
                    "Blade Cutting Station",
                    "BLD-DIE-001",
                    1,
                    "SRH Demo Supplier",
                    now,
                ),
                (
                    "Slider Press Guide Rail",
                    "Guide rail for the lock slider assembly press.",
                    "Lock Slider Assembly Press",
                    "LSP-GUIDE-001",
                    2,
                    "SRH Demo Supplier",
                    now,
                ),
                (
                    "Clip Forming Spring",
                    "Replacement spring for the belt clip forming press.",
                    "Belt Clip Forming Press",
                    "BCP-SPRING-001",
                    4,
                    "SRH Demo Supplier",
                    now,
                ),
            ]

            conn.executemany("""
                INSERT INTO spare_parts
                (name, description, machine, part_number, quantity, supplier, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, default_parts)

        if schedule_count == 0:
            default_schedule = [
                (
                    "Moulding Barrel",
                    "Inspect heater cartridge and thermocouple sensor.",
                    "Every 7 days",
                    str(today - timedelta(days=4)),
                    str(today + timedelta(days=3)),
                    "Operator",
                    "Check temperature stability and heater response.",
                ),
                (
                    "Heat-Treat Furnace",
                    "Inspect furnace heating element and temperature sensor.",
                    "Every 5 days",
                    str(today - timedelta(days=5)),
                    str(today),
                    "Maintenance Team",
                    "Blade quality depends strongly on furnace stability.",
                ),
                (
                    "Lock Slider Assembly Press",
                    "Check alignment and guide rail wear.",
                    "Every 10 days",
                    str(today - timedelta(days=6)),
                    str(today + timedelta(days=4)),
                    "Operator",
                    "Misalignment can increase assembly rejects.",
                ),
                (
                    "Belt Clip Forming Press",
                    "Inspect forming spring and clip tension.",
                    "Every 14 days",
                    str(today - timedelta(days=8)),
                    str(today + timedelta(days=6)),
                    "Maintenance Team",
                    "Poor clip tension causes final inspection failures.",
                ),
            ]

            conn.executemany("""
                INSERT INTO maintenance_schedule
                (machine, task, frequency, last_done, next_due, changed_by, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, default_schedule)

        conn.commit()


def list_spare_parts() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM spare_parts
            ORDER BY machine, name
        """).fetchall()

    return [dict(row) for row in rows]


def add_spare_part(
    name: str,
    description: str,
    machine: str,
    part_number: str,
    quantity: int,
    supplier: str,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO spare_parts
            (name, description, machine, part_number, quantity, supplier, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, description, machine, part_number, quantity, supplier, now))

        conn.commit()


def list_work_orders() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM work_orders
            ORDER BY
                CASE status WHEN 'OPEN' THEN 0 ELSE 1 END,
                id DESC
        """).fetchall()

    return [dict(row) for row in rows]


def create_work_order(
    machine: str,
    reason: str,
    priority: str,
    requested_by: str,
    assigned_to: str,
    notes: str,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO work_orders
            (machine, reason, priority, status, requested_by, assigned_to, notes, created_at, closed_at)
            VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, NULL)
        """, (machine, reason, priority, requested_by, assigned_to, notes, now))

        conn.commit()


def close_work_order(order_id: int, notes: str | None = None) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        if notes:
            conn.execute("""
                UPDATE work_orders
                SET status = 'CLOSED',
                    closed_at = ?,
                    notes = COALESCE(notes, '') || char(10) || ?
                WHERE id = ?
            """, (now, f"Closing note: {notes}", order_id))
        else:
            conn.execute("""
                UPDATE work_orders
                SET status = 'CLOSED',
                    closed_at = ?
                WHERE id = ?
            """, (now, order_id))

        conn.commit()


def list_schedule() -> list[dict]:
    today = datetime.now().date()

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM maintenance_schedule
            ORDER BY next_due ASC
        """).fetchall()

    schedule = []

    for row in rows:
        item = dict(row)
        next_due = datetime.strptime(item["next_due"], "%Y-%m-%d").date()
        days_left = (next_due - today).days

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

        schedule.append(item)

    return schedule
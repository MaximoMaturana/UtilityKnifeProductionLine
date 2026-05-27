"""
producer.py
===========
Headless telemetry producer for the Utility Knife Production Line.

Runs the production simulation continuously and writes one batch of
InfluxDB points per second.  Also models two thermal zones with a
startup preheat phase and rare mid-run glitches — exactly mirroring
the interlock logic in utility_knife_hmi.py.

Usage
-----
    # Normal mode — streams to InfluxDB (Docker must be running)
    python producer.py

    # Dry-run — prints metrics to console, no InfluxDB needed
    python producer.py --dry-run

Requirements
------------
    pip install influxdb-client

InfluxDB connection (matches docker-compose.yml)
------------------------------------------------
    URL   : http://localhost:8086
    Token : srh-utility-knife-token
    Org   : srh
    Bucket: production

Author : [Your Name]
Course : Advanced Programming — SRH University Berlin
Due    : June 20, 2026
"""
from __future__ import annotations

import argparse
import collections
import random
import sys
import time

from utility_knife_production_line import (
    ComponentMaker,
    QualityControl,
    UtilityKnife,
    Quality,
)

# ── InfluxDB connection settings (must match docker-compose.yml) ──────
INFLUX_URL    = "http://localhost:8086"
INFLUX_TOKEN  = "srh-utility-knife-token"
INFLUX_ORG    = "srh"
INFLUX_BUCKET = "production"

WRITE_INTERVAL = 1.0   # seconds between InfluxDB write batches


# ══════════════════════════════════════════════════════════════════════
#  THERMAL ZONE  (identical model to utility_knife_hmi.py)
# ══════════════════════════════════════════════════════════════════════
class ThermalZone:
    """
    First-order thermal model for one process zone.

    States: COLD → HEATING → OK → (rarely) FAULT
    """
    GLITCH_CHANCE = 0.01
    AMBIENT       = 22.0

    def __init__(self, name: str, setpoint: float, band: float,
                 tau: float = 0.08) -> None:
        self.name     = name
        self.setpoint = setpoint
        self.band     = band
        self._tau     = tau
        self._temp    = self.AMBIENT

    @property
    def temperature(self) -> float:
        return round(self._temp, 1)

    @property
    def status(self) -> str:
        lo, hi = self.setpoint - self.band, self.setpoint + self.band
        if self._temp < lo:
            return "COLD"
        if self._temp > hi:
            return "FAULT"
        if abs(self._temp - self.setpoint) <= 2.0:
            return "OK"
        return "HEATING"

    @property
    def in_band(self) -> bool:
        lo, hi = self.setpoint - self.band, self.setpoint + self.band
        return lo <= self._temp <= hi

    def tick(self) -> None:
        if random.random() < self.GLITCH_CHANCE:
            self._temp += random.uniform(self.band * 1.1, self.band * 1.6)
            return
        noise = random.gauss(0, 0.4)
        self._temp += self._tau * (self.setpoint - self._temp) + noise
        self._temp = max(self.AMBIENT, self._temp)


# ══════════════════════════════════════════════════════════════════════
#  MACHINE STATES
# ══════════════════════════════════════════════════════════════════════
STATE_IDLE    = 0
STATE_RUNNING = 1
STATE_FAULTED = 2

STATE_NAMES = {STATE_IDLE: "IDLE", STATE_RUNNING: "RUNNING",
               STATE_FAULTED: "FAULTED"}


# ══════════════════════════════════════════════════════════════════════
#  HEADLESS LINE RUNNER
# ══════════════════════════════════════════════════════════════════════
class LineRunner:
    """
    Headless production line that exposes telemetry snapshots.
    Designed to be called in a tight loop by the producer.
    """
    BASE_NAMES            = ["Handle", "Blade", "LockSlider", "BeltClip"]
    ASSEMBLY_FAILURE_RATE = 0.02
    BASE_RATES            = {"Handle": 0.03, "Blade": 0.04,
                              "LockSlider": 0.02, "BeltClip": 0.03}

    def __init__(self) -> None:
        self.makers = {n: ComponentMaker(n, r)
                       for n, r in self.BASE_RATES.items()}
        self.qcs    = {n: QualityControl(n) for n in self.BASE_NAMES}
        self.bins   = {n: collections.deque() for n in self.BASE_NAMES}

        self.parts_produced = 0
        self.parts_shipped  = 0
        self.parts_rejected = 0

        # thermal zones
        self.zone_moulding = ThermalZone("Moulding Barrel",
                                         setpoint=230.0, band=15.0)
        self.zone_furnace  = ThermalZone("Heat-Treatment Furnace",
                                         setpoint=820.0, band=40.0)

        self.state = STATE_IDLE

    # ── thermal helpers ────────────────────────────────────────────────
    def _both_in_band(self) -> bool:
        return self.zone_moulding.in_band and self.zone_furnace.in_band

    def _tick_thermal(self) -> None:
        self.zone_moulding.tick()
        self.zone_furnace.tick()

    # ── one production step ────────────────────────────────────────────
    def step(self) -> None:
        """
        Advance the line by one logical step:
          - tick thermal zones
          - update machine state
          - if RUNNING, attempt to fill bins and assemble one knife
        """
        self._tick_thermal()

        # state machine
        if not self._both_in_band():
            self.state = STATE_FAULTED if self.state == STATE_RUNNING \
                         else STATE_IDLE
            return

        self.state = STATE_RUNNING

        # fill each bin until it has at least one part
        for name in self.BASE_NAMES:
            if not self.bins[name]:
                part   = self.makers[name].process()
                passed = self.qcs[name].process(part)
                self.parts_produced += 1
                if passed is None:
                    self.parts_rejected += 1
                else:
                    self.bins[name].append(passed)

        # attempt assembly if all bins are ready
        if not all(self.bins[n] for n in self.BASE_NAMES):
            return

        parts = {n: self.bins[n].popleft() for n in self.BASE_NAMES}
        if random.random() < self.ASSEMBLY_FAILURE_RATE:
            self.parts_rejected += 1
            return

        knife = UtilityKnife(
            handle      = parts["Handle"],
            blade       = parts["Blade"],
            lock_slider = parts["LockSlider"],
            belt_clip   = parts["BeltClip"],
        )
        if knife.is_complete():
            self.parts_shipped += 1
        else:
            self.parts_rejected += 1

    # ── telemetry snapshot ─────────────────────────────────────────────
    def snapshot(self) -> dict:
        """Return a dict of all metrics for this tick."""
        per_station = {
            name: {
                "defect_rate": self.makers[name].current_defect_rate,
                "wear":        self.makers[name].wear,
            }
            for name in self.BASE_NAMES
        }
        return {
            "state":          self.state,
            "temp_moulding":  self.zone_moulding.temperature,
            "temp_furnace":   self.zone_furnace.temperature,
            "parts_produced": self.parts_produced,
            "parts_shipped":  self.parts_shipped,
            "parts_rejected": self.parts_rejected,
            "per_station":    per_station,
        }


# ══════════════════════════════════════════════════════════════════════
#  DRY-RUN PRINTER
# ══════════════════════════════════════════════════════════════════════
def print_snapshot(tick: int, snap: dict) -> None:
    state_name = STATE_NAMES.get(snap["state"], "?")
    print(
        f"[{tick:>4}] {state_name:<8}  "
        f"mould={snap['temp_moulding']:>6.1f}°C  "
        f"furnace={snap['temp_furnace']:>7.1f}°C  "
        f"produced={snap['parts_produced']:<4}  "
        f"shipped={snap['parts_shipped']:<4}  "
        f"rejected={snap['parts_rejected']:<4}"
    )


# ══════════════════════════════════════════════════════════════════════
#  INFLUXDB WRITER
# ══════════════════════════════════════════════════════════════════════
def build_points(snap: dict, timestamp) -> list:
    """
    Convert a snapshot dict into InfluxDB Point objects.

    Measurement: "line"
    Tags        : station (per-station rows)
    Fields      : all numeric metrics
    """
    from influxdb_client import Point

    points = []

    # ── main line metrics ─────────────────────────────────────────────
    p = (
        Point("line")
        .field("state",          snap["state"])
        .field("temp_moulding",  float(snap["temp_moulding"]))
        .field("temp_furnace",   float(snap["temp_furnace"]))
        .field("parts_produced", snap["parts_produced"])
        .field("parts_shipped",  snap["parts_shipped"])
        .field("parts_rejected", snap["parts_rejected"])
        .time(timestamp)
    )
    points.append(p)

    # ── per-station metrics (tagged by station name) ──────────────────
    for station, vals in snap["per_station"].items():
        ps = (
            Point("line")
            .tag("station",    station)
            .field("defect_rate", float(vals["defect_rate"]))
            .field("wear",        float(vals["wear"]))
            .time(timestamp)
        )
        points.append(ps)

    return points


# ══════════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ══════════════════════════════════════════════════════════════════════
def run_producer(dry_run: bool = False) -> None:
    runner = LineRunner()
    tick   = 0

    if dry_run:
        print("── DRY RUN — no InfluxDB connection ──")
        print(f"{'Tick':<6} {'State':<9} {'Moulding':>10} {'Furnace':>10} "
              f"{'Produced':>10} {'Shipped':>8} {'Rejected':>9}")
        print("─" * 70)
        try:
            while True:
                runner.step()
                tick += 1
                if tick % 5 == 0:   # print every 5 ticks to avoid flooding
                    print_snapshot(tick, runner.snapshot())
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nDry run stopped.")
        return

    # ── live InfluxDB mode ────────────────────────────────────────────
    try:
        from influxdb_client import InfluxDBClient
        from influxdb_client.client.write_api import SYNCHRONOUS
        import datetime
    except ImportError:
        print("ERROR: influxdb-client not installed.")
        print("Run:  pip install influxdb-client")
        sys.exit(1)

    print(f"Connecting to InfluxDB at {INFLUX_URL} …")
    client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)
    print("Connected. Streaming metrics — Ctrl+C to stop.\n")

    try:
        while True:
            loop_start = time.monotonic()

            # run several steps per write interval for smoother simulation
            for _ in range(5):
                runner.step()

            tick += 1
            snap = runner.snapshot()
            now  = datetime.datetime.utcnow()

            points = build_points(snap, now)
            try:
                write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG,
                                record=points)
            except Exception as exc:
                print(f"[WARN] InfluxDB write failed: {exc}", file=sys.stderr)

            # console heartbeat every 10 ticks
            if tick % 10 == 0:
                print_snapshot(tick, snap)

            # sleep for the remainder of the write interval
            elapsed = time.monotonic() - loop_start
            time.sleep(max(0.0, WRITE_INTERVAL - elapsed))

    except KeyboardInterrupt:
        print("\nProducer stopped.")
    finally:
        client.close()


# ══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Utility Knife telemetry producer")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print metrics to console instead of InfluxDB")
    args = parser.parse_args()

    random.seed()   # non-reproducible for live telemetry
    run_producer(dry_run=args.dry_run)
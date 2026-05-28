# ⌧ Utility Knife Production Line

> Advanced Programming Project — SRH University Berlin, June 2026  
> Applied Mechatronics

A full-stack manufacturing simulation that models a **utility knife production line** end-to-end: Python backend simulation, Tkinter HMI, live telemetry streamed to InfluxDB, a Grafana dashboard, and a Flask-based CMMS web application — all tied together with Docker.

---

## Table of Contents

1. [What This Project Does](#what-this-project-does)
2. [System Architecture](#system-architecture)
3. [Prerequisites](#prerequisites)
4. [Project Structure](#project-structure)
5. [Step-by-Step Setup](#step-by-step-setup)
   - [1 — Clone the Repository](#1--clone-the-repository)
   - [2 — Install Python](#2--install-python)
   - [3 — Install Python Dependencies](#3--install-python-dependencies)
   - [4 — Install and Start Docker](#4--install-and-start-docker)
   - [5 — Start InfluxDB and Grafana](#5--start-influxdb-and-grafana)
   - [6 — Configure Grafana](#6--configure-grafana)
   - [7 — Run the Producer](#7--run-the-producer)
   - [8 — Run the CMMS Website](#8--run-the-cmms-website)
   - [9 — Run the HMI (optional)](#9--run-the-hmi-optional)
6. [Accessing the System](#accessing-the-system)
7. [How the Production Line Works](#how-the-production-line-works)
8. [CMMS Features](#cmms-features)
9. [Grafana Flux Queries](#grafana-flux-queries)
10. [Troubleshooting](#troubleshooting)
11. [AI Tool Usage](#ai-tool-usage)

---

## What This Project Does

This project simulates a factory that manufactures utility knives. Each knife consists of four components:

| Component | Process |
|-----------|---------|
| **Handle** | Injection-moulded in a barrel heated to 230 °C |
| **Blade** | High-carbon steel, heat-treated in a furnace at 820 °C |
| **Lock Slider** | Assembled on a press station |
| **Belt Clip** | Formed on a spring-steel press |

The simulation models realistic defect rates, tool wear, thermal zones, and maintenance events. All telemetry is streamed live to a database and visualised in dashboards.

---

## System Architecture

```
utility_knife_production_line.py   ← core simulation logic
        ↓
producer.py                        ← headless telemetry producer
        ↓
InfluxDB (Docker, port 8086)       ← time-series database
        ↓                    ↘
Grafana (Docker, port 3000)        Flask CMMS website (port 5050)
(live dashboard)                   (work orders, alerts, schedule)

utility_knife_hmi.py               ← optional desktop HMI (Tkinter)
```

---

## Prerequisites

You need the following installed on your computer before starting. Each item links to its download page.

| Tool | Version | Download |
|------|---------|----------|
| **Python** | 3.11 or newer | https://www.python.org/downloads/ |
| **Docker Desktop** | Latest | https://www.docker.com/products/docker-desktop/ |
| **Git** | Any | https://git-scm.com/downloads |

> **Windows users:** when installing Python, tick **"Add Python to PATH"** on the first installer screen.

> **macOS users:** Docker Desktop requires macOS 12 (Monterey) or later.

---

## Project Structure

```
UtilityKnifeProductionLine/
│
├── producer.py                    # Headless telemetry producer → InfluxDB
├── cmms_app.py                    # Flask CMMS web application
├── cmms.py                        # CMMS maintenance logic
├── cmms_db.py                     # SQLite database layer for the CMMS
├── utility_knife_production_line.py  # Core simulation (backend)
├── utility_knife_hmi.py           # Desktop HMI (Tkinter)
├── docker-compose.yml             # InfluxDB + Grafana services
├── requirements.txt               # Python dependencies
├── README.md                      # This file
│
├── templates/                     # Flask HTML templates
│   ├── base.html
│   ├── dashboard.html
│   ├── maintenance.html
│   ├── parts.html
│   ├── alerts.html
│   └── add_part.html
│
└── static/
    ├── css/
    │   └── cmms.css               # Dark-theme stylesheet
    └── js/
        └── cmms.js                # Live dashboard updater
```

---

## Step-by-Step Setup

Open a terminal (PowerShell on Windows, Terminal on macOS/Linux) and follow every step in order.

### 1 — Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/UtilityKnifeProductionLine.git
cd UtilityKnifeProductionLine
```

> Replace `YOUR_USERNAME` with the actual GitHub username.

---

### 2 — Install Python

Check whether Python is already installed:

```bash
python --version
# or on some systems:
py --version
```

If you see `Python 3.11.x` or newer, skip to step 3. Otherwise download and install it from https://www.python.org/downloads/ and re-run the check.

---

### 3 — Install Python Dependencies

From inside the project folder:

**Windows:**
```powershell
py -m pip install flask influxdb-client
```

**macOS / Linux:**
```bash
pip3 install flask influxdb-client
```

This installs Flask (the web framework) and the InfluxDB client library.

---

### 4 — Install and Start Docker

1. Download Docker Desktop from https://www.docker.com/products/docker-desktop/
2. Install and **launch Docker Desktop** — wait until the whale icon in your taskbar/menu bar is steady (not animated).
3. Verify Docker is running:

```bash
docker --version
```

You should see something like `Docker version 26.x.x`.

---

### 5 — Start InfluxDB and Grafana

From the project folder, run:

```bash
docker compose up -d
```

This downloads the InfluxDB and Grafana images (only on first run — may take a few minutes) and starts both containers in the background.

Verify they are running:

```bash
docker ps
```

You should see two containers listed:

```
utility_knife_influxdb    (port 8086)
utility_knife_grafana     (port 3000)
```

**InfluxDB credentials (already configured by docker-compose.yml):**

| Field | Value |
|-------|-------|
| URL | http://localhost:8086 |
| Username | `admin` |
| Password | `adminpassword` |
| Organisation | `srh` |
| Bucket | `production` |
| Token | `srh-utility-knife-token` |

---

### 6 — Configure Grafana

1. Open http://localhost:3000 in your browser.
2. Log in with username `admin` and password `admin`. Grafana will ask you to set a new password — you can skip this for a local project.
3. Go to **Connections → Data sources → Add new data source**.
4. Choose **InfluxDB**.
5. Fill in the settings exactly as shown:

| Setting | Value |
|---------|-------|
| Query language | **Flux** |
| URL | `http://influxdb:8086` ← use this, not localhost |
| Organisation | `srh` |
| Token | `srh-utility-knife-token` |
| Default bucket | `production` |

6. Click **Save & test** — you should see a green success message.
7. Create a new dashboard and add panels using the Flux queries in the [Grafana Flux Queries](#grafana-flux-queries) section below.

---

### 7 — Run the Producer

The producer streams live telemetry from the simulation into InfluxDB every second. Open a **dedicated terminal** and leave it running.

**Windows:**
```powershell
cd UtilityKnifeProductionLine
py producer.py
```

**macOS / Linux:**
```bash
cd UtilityKnifeProductionLine
python3 producer.py
```

Expected output:
```
Connecting to InfluxDB at http://localhost:8086 …
Connected. Streaming metrics — Ctrl+C to stop.

[  10] RUNNING   mould= 229.8°C  furnace=  819.3°C  produced=47   shipped=12   ...
```

> To test without Docker running, use `py producer.py --dry-run` — this prints metrics to the console only.

---

### 8 — Run the CMMS Website

Open a **second terminal** (keep the producer running in the first one):

**Windows:**
```powershell
cd UtilityKnifeProductionLine
py cmms_app.py
```

**macOS / Linux:**
```bash
cd UtilityKnifeProductionLine
python3 cmms_app.py
```

Expected output:
```
 * Running on http://127.0.0.1:5050
```

Open http://127.0.0.1:5050 in your browser to see the CMMS dashboard.

---

### 9 — Run the HMI (optional)

The HMI is a desktop application that shows the production pipeline visually with animated stages. Open a **third terminal**:

**Windows:**
```powershell
py utility_knife_hmi.py
```

**macOS / Linux:**
```bash
python3 utility_knife_hmi.py
```

A window will open. Press **START** to begin the simulation. The pipeline animates in real time, and the sidebar shows live defect rates and temperatures.

> The HMI runs its own internal simulation and does **not** write to InfluxDB. Use `producer.py` for database telemetry.

---

## Accessing the System

Once everything is running, use these URLs:

| Service | URL | Credentials |
|---------|-----|-------------|
| CMMS Website | http://127.0.0.1:5050 | none |
| Grafana Dashboard | http://localhost:3000 | admin / admin |
| InfluxDB | http://localhost:8086 | admin / adminpassword |

---

## How the Production Line Works

The simulation is built around four stations running in parallel, feeding a central assembly step:

```
Handle Maker → Handle QC  ─┐
Blade Maker  → Blade QC   ─┤
                            ├→ Assembly → Final Inspection → Packaging → Shipped ✓
Slider Maker → Slider QC  ─┤
Clip Maker   → Clip QC    ─┘
```

**Defect model — two types of variation:**

- **Common cause** — a constant base defect rate per component (3–4 %). This is inherent randomness that never goes away.
- **Special cause** — tool wear that grows with every part produced, plus occasional bad material batches. The CMMS monitors these and triggers maintenance when thresholds are exceeded.

**Thermal interlocks:**

Both thermal zones must be within their operating band before production is allowed:

| Zone | Setpoint | Band |
|------|----------|------|
| Moulding Barrel | 230 °C | ±15 °C |
| Heat-Treat Furnace | 820 °C | ±40 °C |

If either zone faults (rare random glitch), the line pauses and waits for recovery.

---

## CMMS Features

The CMMS website (http://127.0.0.1:5050) provides:

- **Dashboard** — live machine state, temperatures, parts counters, station wear and defect rate, open work orders.
- **Alerts** — automatic warnings when wear or defect rate exceeds thresholds.
- **Maintenance Schedule** — planned maintenance tasks with overdue/upcoming status.
- **Work Orders** — create a work order from any station card; close it after maintenance is done.
- **Spare Parts Inventory** — list of machine parts with quantities and supplier info.

**CMMS thresholds:**

| Metric | Warning | Critical |
|--------|---------|----------|
| Tool wear | 7.5 % | 10 % |
| Defect rate | 16.5 % | 22 % |

---

## Grafana Flux Queries

Paste these into Grafana panel editors to visualise production data.

**Machine state:**
```flux
from(bucket: "production")
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "line")
  |> filter(fn: (r) => r._field == "state")
```

**Moulding barrel temperature:**
```flux
from(bucket: "production")
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "line")
  |> filter(fn: (r) => r._field == "temp_moulding")
```

**Heat-treat furnace temperature:**
```flux
from(bucket: "production")
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "line")
  |> filter(fn: (r) => r._field == "temp_furnace")
```

**Parts produced / shipped / rejected:**
```flux
from(bucket: "production")
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "line")
  |> filter(fn: (r) => r._field == "parts_produced" or r._field == "parts_shipped" or r._field == "parts_rejected")
```

**Station wear (all stations):**
```flux
from(bucket: "production")
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "line")
  |> filter(fn: (r) => r._field == "wear")
  |> filter(fn: (r) => exists r.station)
```

**Defect rate by station:**
```flux
from(bucket: "production")
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "line")
  |> filter(fn: (r) => r._field == "defect_rate")
  |> filter(fn: (r) => exists r.station)
```

**Maintenance events:**
```flux
from(bucket: "production")
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "line")
  |> filter(fn: (r) => r._field == "maintenance_count")
```

---

## Troubleshooting

**`No module named flask` or `No module named influxdb_client`**

Run the install command again:
```bash
py -m pip install flask influxdb-client        # Windows
pip3 install flask influxdb-client             # macOS / Linux
```

**`No module named pip`**

```bash
py -m ensurepip --upgrade
py -m pip install flask influxdb-client
```

**InfluxDB write failed / CMMS shows no data**

- Make sure Docker Desktop is running.
- Run `docker ps` and confirm both containers appear.
- If containers are stopped, run `docker compose up -d` again from the project folder.

**CMMS shows old data from a different project (port conflict)**

Another Flask app may be running on port 5000. This project uses port 5050. Stop any other Flask servers with `Ctrl+C`, then restart with `py cmms_app.py`.

**Both the producer and the CMMS stop when I start the second one**

Do not use the VS Code "Run Python File ▶" button for these two scripts — it replaces the running process. Use **two separate terminal tabs** and run each script with `py` commands as shown above.

**Grafana shows "no data" even though the producer is running**

- Check that the Grafana data source URL is `http://influxdb:8086` (not `localhost`).
- Confirm the token and organisation match the values in the table above.
- Wait 10–15 seconds for the first data points to appear.

---

## AI Tool Usage

Parts of this project were developed with the assistance of Claude (Anthropic). AI was used to:

- Design and refine the thermal zone model (`ThermalZone` class)
- Structure the Flask CMMS application and SQLite database layer
- Generate the dark-theme CSS for the CMMS frontend
- Write the Flux queries for Grafana

All AI-generated code was reviewed, tested, and adapted. Specific prompts, AI outputs, and corrections are documented in the project appendix (`utility_knife_cmms_setup_chat.md`).

---

## Stopping Everything

To stop all running processes:

1. In each terminal running a Python script, press `Ctrl+C`.
2. To stop the Docker containers:

```bash
docker compose down
```

Data in InfluxDB and Grafana is stored in Docker volumes and will persist the next time you run `docker compose up -d`.

---

*SRH University Berlin — Advanced Programming, Applied Mechatronics, June 2026*

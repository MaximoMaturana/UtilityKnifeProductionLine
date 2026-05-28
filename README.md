# Utility Knife Production Line

This project simulates a Utility Knife Production Line for the Advanced Programming course at SRH University.

The system includes:

- Python backend production-line simulation
- Live telemetry producer
- InfluxDB database
- Grafana dashboard
- Flask-based CMMS website
- Work order creation and closing
- Docker setup for InfluxDB and Grafana

## Project Structure

```text
UtilityKnifeProductionLine/
├── producer.py
├── cmms_app.py
├── cmms.py
├── utility_knife_production_line.py
├── utility_knife_hmi.py
├── docker-compose.yml
├── requirements.txt
├── README.md
├── templates/
│   └── cmms_dashboard.html
└── static/
    ├── css/
    │   └── cmms.css
    └── js/
        └── cmms.js
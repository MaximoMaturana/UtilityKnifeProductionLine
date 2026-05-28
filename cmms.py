"""
cmms.py
=======
Simple Computerized Maintenance Management System for the
Utility Knife Production Line.

The CMMS monitors station wear and defect rate. When one station
crosses the maintenance threshold, a maintenance event is created.
"""

from dataclasses import dataclass
import time


@dataclass
class MaintenanceEvent:
    station: str
    reason: str
    wear: float
    defect_rate: float
    timestamp: float


class CMMS:
    def __init__(self, wear_limit: float = 0.25, defect_limit: float = 0.20):
        self.wear_limit = wear_limit
        self.defect_limit = defect_limit
        self.events: list[MaintenanceEvent] = []
        self.maintenance_count = 0

    def check_station(self, station: str, wear: float, defect_rate: float):
        if wear >= self.wear_limit:
            return self._create_event(
                station,
                "Preventive maintenance: tool wear limit exceeded",
                wear,
                defect_rate,
            )

        if defect_rate >= self.defect_limit:
            return self._create_event(
                station,
                "Corrective maintenance: defect rate too high",
                wear,
                defect_rate,
            )

        return None

    def _create_event(self, station: str, reason: str, wear: float, defect_rate: float):
        event = MaintenanceEvent(
            station=station,
            reason=reason,
            wear=wear,
            defect_rate=defect_rate,
            timestamp=time.time(),
        )
        self.events.append(event)
        self.maintenance_count += 1
        return event
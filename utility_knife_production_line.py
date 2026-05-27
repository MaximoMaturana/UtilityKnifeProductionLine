"""
utility_knife_production_line.py
=================================
Back-end simulation of a utility knife production line.

Product: Utility Knife
Components (4):
    1. Handle/Body   — injection-moulded plastic shell
    2. Blade         — high-carbon steel blade cartridge
    3. Lock Slider   — blade-locking slide mechanism
    4. Belt Clip     — spring-steel clip attached to the handle

Production flow:
    Makers (x4) → QC Stations (x4) → bins → AssemblyStation
                → FinalInspection → Packaging

Author : [Your Name]
Course : Advanced Programming — SRH University Berlin
Due    : June 20, 2026
"""

from __future__ import annotations

import collections
import random
import dataclasses
from abc import ABC, abstractmethod
from enum import Enum, auto


# ---------------------------------------------------------------------------
# 1.  DOMAIN ENUMS
# ---------------------------------------------------------------------------

class Quality(Enum):
    OK        = auto()
    DEFECTIVE = auto()


# ---------------------------------------------------------------------------
# 2.  DATA CLASSES
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Component:
    """A single manufactured component travelling through the line."""
    name:          str
    serial_number: int
    quality:       Quality = Quality.OK

    def __str__(self) -> str:
        return f"{self.name}#{self.serial_number} [{self.quality.name}]"


@dataclasses.dataclass
class UtilityKnife:
    """
    A fully assembled utility knife consisting of exactly four components.
    Serial number is derived from the handle's serial number.
    """
    handle:      Component
    blade:       Component
    lock_slider: Component
    belt_clip:   Component
    serial_number: int = dataclasses.field(init=False)
    quality:       Quality = Quality.OK

    def __post_init__(self) -> None:
        self.serial_number = self.handle.serial_number

    def is_complete(self) -> bool:
        """True when all four components are present and individually OK."""
        return all(
            c.quality == Quality.OK
            for c in (self.handle, self.blade, self.lock_slider, self.belt_clip)
        )

    def __str__(self) -> str:
        return (
            f"UtilityKnife#{self.serial_number} "
            f"[handle={self.handle.serial_number}, "
            f"blade={self.blade.serial_number}, "
            f"slider={self.lock_slider.serial_number}, "
            f"clip={self.belt_clip.serial_number}]"
        )


# ---------------------------------------------------------------------------
# 3.  ABSTRACT STATION
# ---------------------------------------------------------------------------

class Station(ABC):
    """
    Contract every workstation must honour.
    process() receives one input and returns one output OR None (discard).
    """

    def __init__(self, name: str) -> None:
        self.name            = name
        self.processed_count = 0
        self.rejected_count  = 0

    @abstractmethod
    def process(self, item: object) -> object | None:
        """Transform *item* and return the result, or None to discard it."""

    def _accept(self, item: object) -> object:
        self.processed_count += 1
        return item

    def _reject(self, item: object) -> None:
        self.processed_count += 1
        self.rejected_count  += 1
        return None

    def report(self) -> str:
        return (
            f"  {self.name:<30} processed={self.processed_count:>4}  "
            f"rejected={self.rejected_count:>4}"
        )


# ---------------------------------------------------------------------------
# 4.  COMPONENT MAKER STATIONS
# ---------------------------------------------------------------------------

class ComponentMaker(Station):
    """
    Manufactures one type of component with a realistic, drifting defect rate.

    Defect-rate model
    ──────────────────
        effective_rate = base_rate + wear + batch_penalty   (capped at MAX_RATE)

      • base_rate     — constant common-cause noise floor (never changes)
      • wear          — special-cause drift; grows each part, reset by maintenance
      • batch_penalty — temporary spike from a defective raw-material lot

    This models two kinds of variation seen on real lines:
      - common cause  : the inherent per-part randomness (base_rate)
      - special cause : tool wear (gradual) and bad batches (sudden)

    The CMMS resets accumulated wear by calling perform_maintenance().
    """

    WEAR_PER_PART = 0.0003   # how fast the tool degrades per part produced
    MAX_RATE      = 0.40     # ceiling so the effective rate can't run away
    BATCH_CHANCE  = 0.004    # probability per part that a bad batch begins
    BATCH_LENGTH  = 20       # number of parts affected by one bad batch
    BATCH_PENALTY = 0.15     # extra defect probability during a bad batch

    def __init__(self, component_name: str, base_rate: float = 0.03) -> None:
        super().__init__(f"{component_name}Maker")
        self.component_name   = component_name
        self.base_rate        = base_rate     # common-cause floor
        self.wear             = 0.0           # accumulated tool wear
        self._batch_remaining = 0             # parts left in current bad batch
        self._counter         = 0

    @property
    def current_defect_rate(self) -> float:
        """Live effective defect probability (read by HMI / telemetry / CMMS)."""
        batch = self.BATCH_PENALTY if self._batch_remaining > 0 else 0.0
        return min(self.base_rate + self.wear + batch, self.MAX_RATE)

    def perform_maintenance(self) -> None:
        """Reset accumulated tool wear. Called by the CMMS on a work order."""
        self.wear = 0.0

    def process(self, _ignored: object = None) -> Component:
        self._counter += 1
        self.processed_count += 1

        # 1. tool wears a little with every part produced (special cause)
        self.wear += self.WEAR_PER_PART

        # 2. maybe a defective material batch starts, then counts down
        if self._batch_remaining == 0 and random.random() < self.BATCH_CHANCE:
            self._batch_remaining = self.BATCH_LENGTH
        if self._batch_remaining > 0:
            self._batch_remaining -= 1

        # 3. roll against the *current* effective rate (common + special cause)
        quality = (
            Quality.DEFECTIVE
            if random.random() < self.current_defect_rate
            else Quality.OK
        )
        return Component(
            name          = self.component_name,
            serial_number = self._counter,
            quality       = quality,
        )


# ---------------------------------------------------------------------------
# 5.  QC STATIONS (one per component type)
# ---------------------------------------------------------------------------

class QualityControl(Station):
    """
    Inspects a component and discards it (returns None) if defective.
    Models a real QC gate: the component either passes or is scrapped.
    """

    def __init__(self, component_name: str) -> None:
        super().__init__(f"{component_name}QC")

    def process(self, component: Component) -> Component | None:
        if component.quality == Quality.DEFECTIVE:
            return self._reject(component)
        return self._accept(component)


# ---------------------------------------------------------------------------
# 6.  ASSEMBLY STATION
# ---------------------------------------------------------------------------

class AssemblyStation(Station):
    """
    Takes one component of each type from the four input bins and attempts
    to assemble a UtilityKnife.  Has a small intrinsic failure rate that
    models jig misalignment, operator error, etc.
    """

    ASSEMBLY_FAILURE_RATE = 0.02   # 2 % chance the assembly itself fails

    def __init__(
        self,
        handle_bin:  collections.deque,
        blade_bin:   collections.deque,
        slider_bin:  collections.deque,
        clip_bin:    collections.deque,
    ) -> None:
        super().__init__("AssemblyStation")
        self.handle_bin = handle_bin
        self.blade_bin  = blade_bin
        self.slider_bin = slider_bin
        self.clip_bin   = clip_bin

    def bins_ready(self) -> bool:
        """True when every bin has at least one part available."""
        return all(
            len(b) > 0
            for b in (self.handle_bin, self.blade_bin,
                      self.slider_bin, self.clip_bin)
        )

    def process(self, _ignored: object = None) -> UtilityKnife | None:
        if not self.bins_ready():
            return None   # not enough parts yet — caller must retry

        knife = UtilityKnife(
            handle      = self.handle_bin.popleft(),
            blade       = self.blade_bin.popleft(),
            lock_slider = self.slider_bin.popleft(),
            belt_clip   = self.clip_bin.popleft(),
        )

        # Intrinsic assembly failure (e.g. snap-fit broke during pressing)
        if random.random() < self.ASSEMBLY_FAILURE_RATE:
            knife.quality = Quality.DEFECTIVE
            return self._reject(knife)

        return self._accept(knife)


# ---------------------------------------------------------------------------
# 7.  FINAL INSPECTION
# ---------------------------------------------------------------------------

class FinalInspection(Station):
    """
    End-of-line functional test:
      • blade extension / retraction check
      • lock slider engagement force
      • belt clip spring tension
    Any assembly-level defect is caught here.
    """

    def __init__(self) -> None:
        super().__init__("FinalInspection")

    def process(self, knife: UtilityKnife) -> UtilityKnife | None:
        # Catch knives marked defective by the assembly station
        if knife.quality == Quality.DEFECTIVE or not knife.is_complete():
            return self._reject(knife)
        return self._accept(knife)


# ---------------------------------------------------------------------------
# 8.  PACKAGING
# ---------------------------------------------------------------------------

class Packaging(Station):
    """
    Wraps the knife in a blister pack and marks it as shipped.
    Maintains the shipped-units list for reporting.
    """

    def __init__(self) -> None:
        super().__init__("Packaging")
        self.shipped: list[UtilityKnife] = []

    def process(self, knife: UtilityKnife) -> UtilityKnife:
        self.shipped.append(knife)
        return self._accept(knife)


# ---------------------------------------------------------------------------
# 9.  PRODUCTION LINE ORCHESTRATOR
# ---------------------------------------------------------------------------

class ProductionLine:
    """
    Wires all stations together and runs the simulation.

    Architecture
    ────────────
    Four parallel maker→QC pipelines feed four deque buffers.
    The AssemblyStation draws one part per buffer per cycle.
    Assembled knives proceed through FinalInspection → Packaging.

    The orchestrator follows the Single Responsibility Principle:
    it coordinates but does not implement any station logic.
    """

    # Component definitions: (name, base_defect_rate)
    # These are the common-cause floors; tool wear and bad batches push
    # the effective rate above these values during a run.
    COMPONENTS = [
        ("Handle",     0.03),
        ("Blade",      0.04),   # slightly higher — precision steel cutting
        ("LockSlider", 0.02),
        ("BeltClip",   0.03),
    ]

    def __init__(self) -> None:
        # --- Bins (buffers between QC and Assembly) ---
        self.handle_bin  = collections.deque()
        self.blade_bin   = collections.deque()
        self.slider_bin  = collections.deque()
        self.clip_bin    = collections.deque()

        bins = [self.handle_bin, self.blade_bin,
                self.slider_bin, self.clip_bin]

        # --- Makers & QC stations (one pair per component) ---
        self.makers: list[ComponentMaker]  = []
        self.qc_stations: list[QualityControl] = []
        for (name, rate), bin_ in zip(self.COMPONENTS, bins):
            self.makers.append(ComponentMaker(name, base_rate=rate))
            self.qc_stations.append(QualityControl(name))

        # Keep a reference to bins in order for easy iteration
        self._bins = bins

        # --- Downstream stations ---
        self.assembly         = AssemblyStation(
            self.handle_bin, self.blade_bin,
            self.slider_bin, self.clip_bin,
        )
        self.final_inspection = FinalInspection()
        self.packaging        = Packaging()

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _fill_bins(self) -> None:
        """
        Run each maker→QC pair once and push passing components into bins.
        Called once per main loop iteration so all four bins grow in step.
        """
        for maker, qc, bin_ in zip(self.makers, self.qc_stations, self._bins):
            component = maker.process()
            passed    = qc.process(component)
            if passed is not None:
                bin_.append(passed)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def run(self, target: int = 10, max_iterations: int = 10_000) -> None:
        """
        Run the line until *target* knives are shipped or *max_iterations*
        is reached (safety guard against infinite loops under high defect rates).
        """
        shipped = 0
        iterations = 0

        while shipped < target and iterations < max_iterations:
            iterations += 1

            # 1. Produce and screen one component of each type
            self._fill_bins()

            # 2. Attempt assembly if all bins have parts
            if not self.assembly.bins_ready():
                continue

            knife = self.assembly.process()
            if knife is None:
                continue

            # 3. Final inspection
            knife = self.final_inspection.process(knife)
            if knife is None:
                continue

            # 4. Package and count
            self.packaging.process(knife)
            shipped += 1

        if iterations >= max_iterations:
            print(
                f"[WARNING] Reached max_iterations ({max_iterations}) "
                f"before hitting target ({target}). "
                f"Check defect rates or raise max_iterations."
            )

    def report(self) -> None:
        """Print a formatted production summary to stdout."""
        shipped = len(self.packaging.shipped)
        print("=" * 60)
        print("  UTILITY KNIFE PRODUCTION LINE — RUN REPORT")
        print("=" * 60)

        print("\n── Component Makers ──")
        for s in self.makers:
            print(
                f"{s.report()}  "
                f"base={s.base_rate:.0%}  "
                f"final_rate={s.current_defect_rate:.1%}  "
                f"wear={s.wear:.3f}"
            )

        print("\n── Quality Control ──")
        for s in self.qc_stations:
            print(s.report())

        print("\n── Assembly & Final ──")
        print(self.assembly.report())
        print(self.final_inspection.report())
        print(self.packaging.report())

        total_components = sum(m.processed_count for m in self.makers)
        total_rejected   = sum(q.rejected_count  for q in self.qc_stations)

        print("\n── Summary ──")
        print(f"  Total components manufactured : {total_components}")
        print(f"  Total components rejected (QC): {total_rejected}")
        print(f"  Assembly attempts             : {self.assembly.processed_count + self.assembly.rejected_count}")
        print(f"  Assembly rejections           : {self.assembly.rejected_count}")
        print(f"  Final inspection rejections   : {self.final_inspection.rejected_count}")
        print(f"  ✔  Utility knives shipped     : {shipped}")

        if shipped:
            ratio = total_components / shipped
            print(f"  Components per shipped knife  : {ratio:.1f}")

        print("\n── Shipped Units ──")
        for knife in self.packaging.shipped:
            print(f"  {knife}")
        print("=" * 60)


# ---------------------------------------------------------------------------
# 10.  ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    random.seed(42)          # reproducible run; remove for live randomness
    line = ProductionLine()
    line.run(target=10)
    line.report()
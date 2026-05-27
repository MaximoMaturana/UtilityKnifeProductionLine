"""
utility_knife_hmi.py
=====================
HMI for the Utility Knife Production Line.
Unique dark-green industrial theme with sidebar controls,
live stat cards, animated pipeline, rejection log, and shipped log.

Changes vs v1:
  - Defect rates randomised (2–14%) on every START press
  - Sidebar shows live defect rates updated each run
  - Tabbed log panel: SHIPPED  |  REJECTED

Run:  python utility_knife_hmi.py
Requires utility_knife_production_line.py in the same folder.

Author : [Your Name]
Course : Advanced Programming — SRH University Berlin
Due    : June 20, 2026
"""
from __future__ import annotations
import collections, queue, random, threading, time
import tkinter as tk
from tkinter import ttk
from utility_knife_production_line import ComponentMaker, QualityControl, UtilityKnife, Quality

# ══════════════════════════════════════════════════════════════════════
#  THEME
# ══════════════════════════════════════════════════════════════════════
TH = dict(
    bg          = "#0F1117",
    sidebar     = "#161B27",
    card        = "#1C2333",
    card_border = "#2A3550",
    pipeline_bg = "#141921",
    accent      = "#00FF88",
    accent2     = "#00C4FF",
    warn        = "#FFB800",
    danger      = "#FF4560",
    fg          = "#E2E8F5",
    fg_dim      = "#556075",
    sep         = "#1E2840",
    Handle      = "#3B82F6",
    Blade       = "#94A3B8",
    LockSlider  = "#F59E0B",
    BeltClip    = "#22C55E",
    knife       = "#EF4444",
)

# ══════════════════════════════════════════════════════════════════════
#  PIPELINE LAYOUT
# ══════════════════════════════════════════════════════════════════════
_CW, _CH  = 760, 185
_BHW, _BHH = 28, 13
_LANE_Y = {"Handle": 28, "Blade": 73, "LockSlider": 118, "BeltClip": 163}
_CTR_Y  = (_LANE_Y["Handle"] + _LANE_Y["BeltClip"]) // 2 + 3
_X_MAKE=50; _X_QC=160; _X_BIN=270; _X_ASSM=390
_X_FINSP=490; _X_PACK=590; _X_SHIP=690

STEP_DELAY = 0.38

# ══════════════════════════════════════════════════════════════════════
#  EVENTS
# ══════════════════════════════════════════════════════════════════════
EVT_ASSEMBLED = "assembled"
EVT_REJECTED  = "rejected"
EVT_STAGE     = "stage"
EVT_STATUS    = "status"
EVT_STOPPED   = "stopped"
EVT_RATES     = "rates"   # broadcasts randomised defect rates to sidebar
EVT_STATS     = "stats"   # per-component produced / rejected snapshot
EVT_TEMPS     = "temps"   # live temperature readings for both thermal zones
EVT_FAULT     = "fault"   # thermal zone out of band — production paused

# ══════════════════════════════════════════════════════════════════════
#  THERMAL ZONE  (first-order model, same logic as producer.py)
# ══════════════════════════════════════════════════════════════════════
class ThermalZone:
    """
    First-order thermal model for one process zone.

    The zone starts pre-heated exactly at its setpoint so production can
    begin immediately.  The operator can toggle the heater ON/OFF at any
    time via enable() / disable():

      • Heater ON  → temperature tracks toward setpoint (normal operation)
      • Heater OFF → temperature drifts toward ambient (cooling down)

    A rare heater glitch (1 % / tick) pushes the zone above its upper band
    and triggers a FAULT that pauses production until it cools back in band.

    States
    ------
    COLD    — below  (setpoint − band)   heater off and cooled too far
    HEATING — inside band, still climbing toward setpoint
    OK      — within ±2 °C of setpoint (settled and producing)
    FAULT   — above  (setpoint + band)   glitch or overheated
    OFF     — heater disabled, temperature falling
    """
    GLITCH_CHANCE = 0.008  # 0.8 % per tick that a heater glitch fires
    AMBIENT       = 22.0   # room temperature (°C)
    COOL_TAU      = 0.0002 # cooling time constant — ~60 s to drop out of band,
                           # mimicking real thermal inertia of a moulding barrel

    def __init__(self, name: str, setpoint: float, band: float,
                 tau: float = 0.06) -> None:
        self.name     = name
        self.setpoint = setpoint
        self.band     = band
        self._tau     = tau
        # start pre-heated so production begins immediately
        self._temp    = setpoint + random.gauss(0, 0.5)
        self.enabled  = True          # heater state — operator-controlled

    @property
    def temperature(self) -> float:
        return round(self._temp, 1)

    @property
    def status(self) -> str:
        if not self.enabled:
            return "OFF"
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
        """True when temperature is within the safe band (regardless of heater state).
        Production resumes once temp is back in range even if heater was briefly off."""
        lo, hi = self.setpoint - self.band, self.setpoint + self.band
        return lo <= self._temp <= hi

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    def tick(self) -> None:
        """Advance the thermal model one step."""
        if self.enabled:
            # rare heater glitch — spike above upper band
            if random.random() < self.GLITCH_CHANCE:
                self._temp += random.uniform(self.band * 1.1, self.band * 1.6)
                return
            # normal: ease toward setpoint with small noise
            noise = random.gauss(0, 0.3)
            self._temp += self._tau * (self.setpoint - self._temp) + noise
        else:
            # heater off: cool very slowly toward ambient (like a real oven)
            noise = random.gauss(0, 0.05)
            self._temp += self.COOL_TAU * (self.AMBIENT - self._temp) + noise
        self._temp = max(self.AMBIENT, self._temp)


# ══════════════════════════════════════════════════════════════════════
#  INSTRUMENTED LINE
# ══════════════════════════════════════════════════════════════════════
class InstrumentedLine:
    BASE_NAMES            = ["Handle","Blade","LockSlider","BeltClip"]
    ASSEMBLY_FAILURE_RATE = 0.02

    def __init__(self, q: queue.Queue, stop: threading.Event):
        self._q, self._stop = q, stop

        # ── randomise defect rates 2 %–14 % on every run ──────────────
        rates = {n: round(random.uniform(0.02, 0.14), 3)
                 for n in self.BASE_NAMES}
        self.COMPONENTS = [(n, rates[n]) for n in self.BASE_NAMES]
        self._q.put({"type": EVT_RATES, "rates": rates})   # → sidebar

        self.makers = {n: ComponentMaker(n, r) for n,r in self.COMPONENTS}
        self.qcs    = {n: QualityControl(n)    for n,_ in self.COMPONENTS}
        self.bins   = {n: collections.deque()  for n,_ in self.COMPONENTS}
        self.shipped: list[UtilityKnife] = []

        # ── thermal zones ──────────────────────────────────────────────
        self._zone_moulding = ThermalZone("Moulding Barrel",
                                          setpoint=230.0, band=15.0)
        self._zone_furnace  = ThermalZone("Heat-Treatment Furnace",
                                          setpoint=820.0, band=40.0)

    def _stage(self, key, comp):
        if not self._stop.is_set():
            self._q.put({"type": EVT_STAGE, "stage": key, "component": comp})
            time.sleep(STEP_DELAY)

    def _emit_stats(self):
        """Send a per-component produced / rejected snapshot to the UI."""
        self._q.put({"type": EVT_STATS, "stats": {
            name: {"produced": self.makers[name].processed_count,
                   "rejected": self.qcs[name].rejected_count}
            for name, _ in self.COMPONENTS}})

    def _emit_temps(self):
        """Tick both thermal zones and push a temperature event to the UI."""
        self._zone_moulding.tick()
        self._zone_furnace.tick()
        self._q.put({"type": EVT_TEMPS,
            "moulding": {"temp":   self._zone_moulding.temperature,
                         "status": self._zone_moulding.status,
                         "in_band":self._zone_moulding.in_band},
            "furnace":  {"temp":   self._zone_furnace.temperature,
                         "status": self._zone_furnace.status,
                         "in_band":self._zone_furnace.in_band}})

    def _refill_bins(self):
        for name,_ in self.COMPONENTS:
            while not self.bins[name] and not self._stop.is_set():
                # pause if a thermal fault fires mid-production
                if not self._both_in_band():
                    return   # caller's loop will detect fault and handle it
                self._stage(f"make_{name}", name)
                part = self.makers[name].process()
                self._stage(f"qc_{name}", name)
                passed = self.qcs[name].process(part)
                if passed is None:
                    self._q.put({"type": EVT_REJECTED,
                        "item": f"{name} #{part.serial_number}",
                        "station": f"QC – {name}",
                        "reason": "Failed dimensional / visual inspection"})
                else:
                    self._stage(f"bin_{name}", name)
                    self.bins[name].append(passed)
                self._emit_stats()   # refresh the per-component tab
                self._emit_temps()   # refresh temperature gauges

    def _assemble_one(self):
        if self._stop.is_set(): return None
        self._stage("assembly", "knife")
        parts = {n: self.bins[n].popleft() for n,_ in self.COMPONENTS}
        if random.random() < self.ASSEMBLY_FAILURE_RATE:
            self._q.put({"type": EVT_REJECTED,
                "item": f"Knife (handle #{parts['Handle'].serial_number})",
                "station": "Assembly",
                "reason": "Jig misalignment — snap-fit failure"})
            return None
        knife = UtilityKnife(handle=parts["Handle"], blade=parts["Blade"],
                             lock_slider=parts["LockSlider"],
                             belt_clip=parts["BeltClip"])
        self._stage("final_inspection", "knife")
        if not knife.is_complete():
            self._q.put({"type": EVT_REJECTED,
                "item": f"Knife #{knife.serial_number}",
                "station": "Final Inspection",
                "reason": "Failed blade / lock / clip functional test"})
            return None
        self._stage("packaging", "knife")
        self._stage("shipped", "knife")
        self.shipped.append(knife)
        self._q.put({"type": EVT_ASSEMBLED, "serial": knife.serial_number,
                     "handle": parts["Handle"].serial_number,
                     "blade":  parts["Blade"].serial_number,
                     "slider": parts["LockSlider"].serial_number,
                     "clip":   parts["BeltClip"].serial_number})
        return knife

    def _both_in_band(self) -> bool:
        """Production is allowed only when both heaters are ON and in band."""
        return (self._zone_moulding.enabled and self._zone_moulding.in_band and
                self._zone_furnace.enabled  and self._zone_furnace.in_band)

    def toggle_moulding(self, enable: bool) -> None:
        """Called from the UI thread — safe because bool assignment is atomic."""
        if enable:
            self._zone_moulding.enable()
        else:
            self._zone_moulding.disable()

    def toggle_furnace(self, enable: bool) -> None:
        if enable:
            self._zone_furnace.enable()
        else:
            self._zone_furnace.disable()

    def run_until_stopped(self):
        self._q.put({"type": EVT_STATUS, "msg": "RUNNING", "ok": True})

        while not self._stop.is_set():
            # emit temps every cycle so gauges stay live
            self._emit_temps()

            # mid-run thermal fault or heater-off check
            if not self._both_in_band():
                self._q.put({"type": EVT_STATUS,
                             "msg": "FAULTED — thermal out of band", "ok": False})
                self._q.put({"type": EVT_FAULT,
                             "moulding_ok": self._zone_moulding.in_band,
                             "furnace_ok":  self._zone_furnace.in_band})
                # recovery loop: tick zones so temperature can climb back
                # uses short sleeps so _stop_event is checked frequently
                while not self._both_in_band() and not self._stop.is_set():
                    self._emit_temps()   # this calls tick() on both zones
                    time.sleep(0.15)     # short sleep → responsive to stop + heater toggle
                if not self._stop.is_set():
                    self._q.put({"type": EVT_STATUS, "msg": "RUNNING", "ok": True})
                continue

            self._refill_bins()
            if (not self._stop.is_set()
                    and all(self.bins[n] for n, _ in self.COMPONENTS)):
                self._assemble_one()

        self._q.put({"type": EVT_STATUS,
            "msg": f"STOPPED  •  {len(self.shipped)} knives shipped",
            "ok": False})
        self._q.put({"type": EVT_STOPPED})


# ══════════════════════════════════════════════════════════════════════
#  HMI WINDOW
# ══════════════════════════════════════════════════════════════════════
class HMI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Utility Knife — Production HMI")
        self.configure(bg=TH["bg"])
        self.resizable(True, True)
        self.minsize(1020, 820)
        self.geometry("1100x860")

        self._q           = queue.Queue()
        self._stop_event  = threading.Event()
        self._thread      = None
        self._n_assembled = 0
        self._n_rejected  = 0
        self._active_stage= None
        self._stage_items = {}
        self._blink_state = False
        self._rate_labels      : dict[str, tk.Label]  = {}
        self._temp_val_labels  : dict[str, tk.Label]  = {}
        self._temp_stat_labels : dict[str, tk.Label]  = {}
        self._heater_btns      : dict[str, tk.Button] = {}  # zone → toggle btn
        self._line             : InstrumentedLine | None = None  # running line ref

        self._build_ui()
        self._poll()

    # ── separator ─────────────────────────────────────────────────────
    def _sep(self, parent):
        tk.Frame(parent, bg=TH["sep"], height=1).pack(fill="x")

    # ── header ────────────────────────────────────────────────────────
    def _build_header(self):
        bar = tk.Frame(self, bg=TH["sidebar"])
        bar.pack(fill="x")
        tk.Frame(bar, bg=TH["accent"], width=6).pack(side="left", fill="y")
        tk.Label(bar, text="⌧", bg=TH["sidebar"], fg=TH["accent"],
                 font=("Segoe UI",22,"bold"), padx=12, pady=8).pack(side="left")
        blk = tk.Frame(bar, bg=TH["sidebar"])
        blk.pack(side="left", pady=6)
        tk.Label(blk, text="UTILITY KNIFE  PRODUCTION LINE",
                 bg=TH["sidebar"], fg=TH["fg"],
                 font=("Segoe UI",13,"bold")).pack(anchor="w")
        tk.Label(blk, text="Human–Machine Interface  •  SRH Advanced Programming",
                 bg=TH["sidebar"], fg=TH["fg_dim"],
                 font=("Segoe UI",8)).pack(anchor="w")
        # status pill (right)
        pill = tk.Frame(bar, bg=TH["sidebar"], padx=18)
        pill.pack(side="right")
        self._status_dot = tk.Label(pill, text="●", bg=TH["sidebar"],
                                    fg=TH["fg_dim"], font=("Segoe UI",14))
        self._status_dot.pack(side="left")
        self._status_var = tk.StringVar(value="IDLE")
        tk.Label(pill, textvariable=self._status_var, bg=TH["sidebar"],
                 fg=TH["fg_dim"], font=("Segoe UI",9,"bold")).pack(side="left",padx=(4,0))

    # ── stat card ─────────────────────────────────────────────────────
    def _stat_card(self, parent, label, var, accent, width=148):
        f = tk.Frame(parent, bg=TH["card"],
                     highlightbackground=TH["card_border"],
                     highlightthickness=1, padx=16, pady=10, width=width)
        f.pack(side="left", padx=6, pady=8)
        f.pack_propagate(False)
        tk.Label(f, text=label, bg=TH["card"], fg=TH["fg_dim"],
                 font=("Segoe UI",8,"bold")).pack(anchor="w")
        tk.Label(f, textvariable=var, bg=TH["card"], fg=accent,
                 font=("Segoe UI",32,"bold")).pack(anchor="w")

    # ── sidebar button ────────────────────────────────────────────────
    def _sidebar_btn(self, parent, text, color, command, state="normal"):
        b = tk.Button(parent, text=text, bg=color, fg="#0F1117",
                      activebackground=color, activeforeground="#0F1117",
                      font=("Segoe UI",10,"bold"), relief="flat",
                      cursor="hand2", pady=8, width=14, state=state,
                      command=command, bd=0, highlightthickness=0)
        b.pack(fill="x", pady=4)
        return b

    # ── full UI ───────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_header()
        self._sep(self)
        body = tk.Frame(self, bg=TH["bg"])
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        tk.Frame(body, bg=TH["sep"], width=1).pack(side="left", fill="y")
        self._build_main(body)

    # ── sidebar ───────────────────────────────────────────────────────
    def _build_sidebar(self, parent):
        sb = tk.Frame(parent, bg=TH["sidebar"], width=185, padx=14)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        tk.Label(sb, text="CONTROLS", bg=TH["sidebar"], fg=TH["fg_dim"],
                 font=("Segoe UI",8,"bold")).pack(anchor="w", pady=(16,4))
        self._btn_start = self._sidebar_btn(sb, "▶  START", TH["accent"], self._start)
        self._btn_stop  = self._sidebar_btn(sb, "■  STOP",  TH["danger"], self._stop,
                                             state="disabled")

        tk.Frame(sb, bg=TH["sep"], height=1).pack(fill="x", pady=10)

        tk.Label(sb, text="COMPONENTS", bg=TH["sidebar"], fg=TH["fg_dim"],
                 font=("Segoe UI",8,"bold")).pack(anchor="w", pady=(4,4))
        for name, col in [("Handle","Handle"),("Blade","Blade"),
                           ("Lock Slider","LockSlider"),("Belt Clip","BeltClip")]:
            row = tk.Frame(sb, bg=TH["sidebar"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text="▬", bg=TH["sidebar"], fg=TH[col],
                     font=("Segoe UI",10)).pack(side="left")
            tk.Label(row, text=f"  {name}", bg=TH["sidebar"], fg=TH["fg"],
                     font=("Segoe UI",8)).pack(side="left")

        tk.Frame(sb, bg=TH["sep"], height=1).pack(fill="x", pady=10)

        # ── live defect rates (updated every START) ───────────────────
        tk.Label(sb, text="DEFECT RATES  (this run)",
                 bg=TH["sidebar"], fg=TH["fg_dim"],
                 font=("Segoe UI",8,"bold")).pack(anchor="w", pady=(4,6))

        for name, display in [("Handle","Handle"),("Blade","Blade"),
                               ("LockSlider","LockSlider"),("BeltClip","BeltClip")]:
            row = tk.Frame(sb, bg=TH["sidebar"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=display, bg=TH["sidebar"], fg=TH["fg_dim"],
                     font=("Segoe UI",8), width=10, anchor="w").pack(side="left")
            lbl = tk.Label(row, text="—", bg=TH["sidebar"], fg=TH["warn"],
                           font=("Segoe UI",8,"bold"))
            lbl.pack(side="right")
            self._rate_labels[name] = lbl   # stored for live updates

    # ── main area ─────────────────────────────────────────────────────
    def _build_main(self, parent):
        main = tk.Frame(parent, bg=TH["bg"])
        main.pack(side="left", fill="both", expand=True)

        # ── top info band: stat cards + temp gauges side by side ──────
        top_band = tk.Frame(main, bg=TH["bg"], padx=10)
        top_band.pack(fill="x", side="top")

        self._assembled_var = tk.StringVar(value="0")
        self._rejected_var  = tk.StringVar(value="0")
        self._yield_var     = tk.StringVar(value="—")
        self._stat_card(top_band, "KNIVES SHIPPED", self._assembled_var, TH["accent"])
        self._stat_card(top_band, "TOTAL REJECTS",  self._rejected_var,  TH["danger"])
        self._stat_card(top_band, "YIELD RATE",     self._yield_var,     TH["accent2"])

        # vertical divider between stat cards and temp gauges
        tk.Frame(top_band, bg=TH["sep"], width=1).pack(
            side="left", fill="y", padx=(10, 0), pady=8)

        # temperature gauge cards with heater ON/OFF toggle
        for zone_key, title, sp_text in [
            ("moulding", "MOULDING BARREL",      "SP 230 °C"),
            ("furnace",  "HEAT-TREAT FURNACE",   "SP 820 °C"),
        ]:
            card = tk.Frame(top_band, bg=TH["card"],
                            highlightbackground=TH["card_border"],
                            highlightthickness=1, padx=12, pady=8)
            card.pack(side="left", padx=6, pady=8)

            # header row: title + setpoint
            hdr = tk.Frame(card, bg=TH["card"])
            hdr.pack(fill="x")
            tk.Label(hdr, text=title, bg=TH["card"], fg=TH["fg_dim"],
                     font=("Segoe UI",7,"bold")).pack(side="left")
            tk.Label(hdr, text=sp_text, bg=TH["card"], fg=TH["fg_dim"],
                     font=("Segoe UI",7), padx=8).pack(side="left")

            # live temperature value
            val_lbl = tk.Label(card, text="— °C", bg=TH["card"],
                               fg=TH["accent2"],
                               font=("Segoe UI",20,"bold"), anchor="w")
            val_lbl.pack(anchor="w")

            # bottom row: status word + heater toggle button
            bot = tk.Frame(card, bg=TH["card"])
            bot.pack(fill="x", pady=(2,0))

            stat_lbl = tk.Label(bot, text="READY", bg=TH["card"],
                                fg=TH["accent"],
                                font=("Segoe UI",8,"bold"), anchor="w")
            stat_lbl.pack(side="left")

            # heater toggle — starts ON (zones are pre-heated)
            zk = zone_key   # capture loop variable
            btn = tk.Button(bot, text="🔥 ON", bg=TH["accent"], fg="#0F1117",
                            font=("Segoe UI",7,"bold"), relief="flat",
                            cursor="hand2", padx=6, pady=2, bd=0,
                            highlightthickness=0,
                            command=lambda z=zk: self._toggle_heater(z))
            btn.pack(side="right")

            self._temp_val_labels[zone_key]  = val_lbl
            self._temp_stat_labels[zone_key] = stat_lbl
            self._heater_btns[zone_key]      = btn

        self._sep(main)

        # pipeline
        pipe_hdr = tk.Frame(main, bg=TH["bg"], padx=16, pady=6)
        pipe_hdr.pack(fill="x")
        tk.Label(pipe_hdr, text="PRODUCTION PIPELINE",
                 bg=TH["bg"], fg=TH["fg_dim"],
                 font=("Segoe UI",8,"bold")).pack(side="left")
        tk.Label(pipe_hdr,
                 text="station highlights in real time as work passes through",
                 bg=TH["bg"], fg=TH["fg_dim"],
                 font=("Segoe UI",7)).pack(side="left", padx=10)
        self._build_pipeline(main)
        self._sep(main)

        # ── tabbed log panel ──────────────────────────────────────────
        log_area = tk.Frame(main, bg=TH["bg"], padx=14, pady=6)
        log_area.pack(fill="both", expand=False)

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("X.Treeview",
            background=TH["card"], foreground=TH["fg"],
            fieldbackground=TH["card"], rowheight=24,
            font=("Segoe UI",9), borderwidth=0, relief="flat")
        style.configure("X.Treeview.Heading",
            background=TH["sidebar"], foreground=TH["accent2"],
            font=("Segoe UI",8,"bold"), relief="flat")
        style.map("X.Treeview",
            background=[("selected", TH["accent2"])],
            foreground=[("selected","#000")])
        # notebook tabs
        style.configure("Log.TNotebook",
            background=TH["bg"], borderwidth=0)
        style.configure("Log.TNotebook.Tab",
            background=TH["card"], foreground=TH["fg_dim"],
            font=("Segoe UI",8,"bold"), padding=(14,5))
        style.map("Log.TNotebook.Tab",
            background=[("selected", TH["sidebar"])],
            foreground=[("selected", TH["accent"])])

        nb = ttk.Notebook(log_area, style="Log.TNotebook")
        nb.pack(fill="both", expand=True)

        # ── tab 1 : SHIPPED ───────────────────────────────────────────
        tab_shipped = tk.Frame(nb, bg=TH["bg"])
        nb.add(tab_shipped, text="  ✔  SHIPPED  ")

        shipped_cols = ("#", "Knife S/N", "Handle", "Blade", "Slider", "Clip")
        wrap_s = tk.Frame(tab_shipped, bg=TH["bg"])
        wrap_s.pack(fill="both", expand=True)
        self._tree_shipped = ttk.Treeview(wrap_s, columns=shipped_cols,
                                          show="headings", style="X.Treeview",
                                          height=6)
        for col, w in zip(shipped_cols, (40, 90, 80, 70, 70, 70)):
            self._tree_shipped.heading(col, text=col)
            self._tree_shipped.column(col, width=w, anchor="center")
        sb_s = ttk.Scrollbar(wrap_s, orient="vertical",
                              command=self._tree_shipped.yview)
        self._tree_shipped.configure(yscrollcommand=sb_s.set)
        self._tree_shipped.pack(side="left", fill="both", expand=True)
        sb_s.pack(side="right", fill="y")

        # ── tab 2 : REJECTED ──────────────────────────────────────────
        tab_rejected = tk.Frame(nb, bg=TH["bg"])
        nb.add(tab_rejected, text="  ✕  REJECTED  ")

        rej_cols = ("Item", "Station", "Reason")
        wrap_r = tk.Frame(tab_rejected, bg=TH["bg"])
        wrap_r.pack(fill="both", expand=True)
        self._tree_rej = ttk.Treeview(wrap_r, columns=rej_cols,
                                      show="headings", style="X.Treeview",
                                      height=6)
        for col, w in zip(rej_cols, (175, 185, 300)):
            self._tree_rej.heading(col, text=col)
            self._tree_rej.column(col, width=w, anchor="w")
        sb_r = ttk.Scrollbar(wrap_r, orient="vertical",
                              command=self._tree_rej.yview)
        self._tree_rej.configure(yscrollcommand=sb_r.set)
        self._tree_rej.pack(side="left", fill="both", expand=True)
        sb_r.pack(side="right", fill="y")

        # ── tab 3 : BY COMPONENT (live produced / rejected totals) ────
        tab_stats = tk.Frame(nb, bg=TH["bg"])
        nb.add(tab_stats, text="  ▦  BY COMPONENT  ")

        stat_cols = ("Component", "Produced", "Rejected", "Passed", "Pass Rate")
        wrap_t = tk.Frame(tab_stats, bg=TH["bg"])
        wrap_t.pack(fill="both", expand=True)
        self._tree_stats = ttk.Treeview(wrap_t, columns=stat_cols,
                                        show="headings", style="X.Treeview",
                                        height=6)
        for col, w in zip(stat_cols, (140, 110, 110, 110, 120)):
            self._tree_stats.heading(col, text=col)
            self._tree_stats.column(col, width=w, anchor="center")
        self._tree_stats.column("Component", anchor="w")
        sb_t = ttk.Scrollbar(wrap_t, orient="vertical",
                             command=self._tree_stats.yview)
        self._tree_stats.configure(yscrollcommand=sb_t.set)
        self._tree_stats.pack(side="left", fill="both", expand=True)
        sb_t.pack(side="right", fill="y")

        # pre-create one fixed row per component; updated in place via EVT_STATS
        self._stat_rows = {}
        for display, key in [("Handle","Handle"),("Blade","Blade"),
                             ("Lock Slider","LockSlider"),("Belt Clip","BeltClip")]:
            iid = self._tree_stats.insert("", "end",
                values=(display, 0, 0, 0, "—"))
            self._stat_rows[key] = iid

        tk.Frame(main, bg=TH["bg"], height=8).pack()

    # ── pipeline canvas ───────────────────────────────────────────────
    def _build_pipeline(self, parent):
        c = tk.Canvas(parent, bg=TH["pipeline_bg"], width=_CW, height=_CH,
                      highlightthickness=0)
        c.pack(padx=14, pady=4)
        self._pipe_canvas = c
        abbr = {"Handle":"HNDL","Blade":"BLDE","LockSlider":"SLDR","BeltClip":"CLIP"}

        def box(cx, cy, l1, l2, key):
            x0,y0=cx-_BHW,cy-_BHH; x1,y1=cx+_BHW,cy+_BHH
            r  = c.create_rectangle(x0,y0,x1,y1, fill=TH["pipeline_bg"],
                                    outline=TH["sep"], width=1)
            t  = c.create_text(cx,cy-5, text=l1, fill=TH["fg_dim"],
                               font=("Segoe UI",6,"bold"))
            t2 = c.create_text(cx,cy+6, text=l2, fill=TH["fg_dim"],
                               font=("Segoe UI",6))
            self._stage_items[key] = (r,t,t2)

        def arrow(x1,y1,x2,y2,curved=False):
            if curved:
                mx=(x1+x2)//2
                c.create_line(x1,y1,mx,y1,mx,y2,x2,y2, fill=TH["sep"],
                              width=1, arrow=tk.LAST, arrowshape=(5,7,3),
                              smooth=True)
            else:
                c.create_line(x1,y1,x2,y2, fill=TH["sep"], width=1,
                              arrow=tk.LAST, arrowshape=(5,7,3))

        for name,y in _LANE_Y.items():
            c.create_rectangle(2,y-_BHH,4,y+_BHH, fill=TH[name], outline="")

        for name,y in _LANE_Y.items():
            s=abbr[name]
            box(_X_MAKE,y,"MAKE",s,f"make_{name}")
            box(_X_QC,  y,"QC",  s,f"qc_{name}")
            box(_X_BIN, y,"BIN", s,f"bin_{name}")
            arrow(_X_MAKE+_BHW,y,  _X_QC -_BHW,y)
            arrow(_X_QC +_BHW,y,   _X_BIN-_BHW,y)
            arrow(_X_BIN+_BHW,y,   _X_ASSM-_BHW,_CTR_Y, curved=True)

        box(_X_ASSM, _CTR_Y,"ASSM", "",     "assembly")
        box(_X_FINSP,_CTR_Y,"FINAL","INSP", "final_inspection")
        box(_X_PACK, _CTR_Y,"PACK", "",     "packaging")
        box(_X_SHIP, _CTR_Y,"SHIP", "✓",    "shipped")
        arrow(_X_ASSM +_BHW,_CTR_Y,_X_FINSP-_BHW,_CTR_Y)
        arrow(_X_FINSP+_BHW,_CTR_Y,_X_PACK -_BHW,_CTR_Y)
        arrow(_X_PACK +_BHW,_CTR_Y,_X_SHIP -_BHW,_CTR_Y)

    # ── highlighting ──────────────────────────────────────────────────
    def _highlight_stage(self, stage, component):
        if self._active_stage and self._active_stage in self._stage_items:
            r,t,t2 = self._stage_items[self._active_stage]
            self._pipe_canvas.itemconfig(r,  fill=TH["pipeline_bg"], outline=TH["sep"])
            self._pipe_canvas.itemconfig(t,  fill=TH["fg_dim"])
            self._pipe_canvas.itemconfig(t2, fill=TH["fg_dim"])
        self._active_stage = stage
        if stage not in self._stage_items: return
        color = TH.get(component, TH["accent"])
        r,t,t2 = self._stage_items[stage]
        self._pipe_canvas.itemconfig(r,  fill=color, outline=color)
        self._pipe_canvas.itemconfig(t,  fill="#0F1117")
        self._pipe_canvas.itemconfig(t2, fill="#0F1117")

    def _reset_pipeline(self):
        for r,t,t2 in self._stage_items.values():
            self._pipe_canvas.itemconfig(r,  fill=TH["pipeline_bg"], outline=TH["sep"])
            self._pipe_canvas.itemconfig(t,  fill=TH["fg_dim"])
            self._pipe_canvas.itemconfig(t2, fill=TH["fg_dim"])
        self._active_stage = None

    # ── blink ─────────────────────────────────────────────────────────
    def _blink(self):
        if not self._stop_event.is_set():
            self._blink_state = not self._blink_state
            self._status_dot.config(
                fg=TH["accent"] if self._blink_state else TH["sidebar"])
            self.after(600, self._blink)

    # ── yield helper ──────────────────────────────────────────────────
    def _update_yield(self):
        total = self._n_assembled + self._n_rejected
        self._yield_var.set(f"{int(self._n_assembled/total*100)}%" if total else "—")

    # ── heater toggle ─────────────────────────────────────────────────
    def _toggle_heater(self, zone_key: str) -> None:
        """Flip the heater for the given zone ON↔OFF and update the button."""
        if self._line is None:
            return   # no line running — button does nothing
        btn = self._heater_btns[zone_key]
        currently_on = (btn.cget("text") == "🔥 ON")
        if currently_on:
            # turn OFF
            if zone_key == "moulding":
                self._line.toggle_moulding(False)
            else:
                self._line.toggle_furnace(False)
            btn.config(text="❄  OFF", bg=TH["danger"], fg="#fff")
        else:
            # turn ON
            if zone_key == "moulding":
                self._line.toggle_moulding(True)
            else:
                self._line.toggle_furnace(True)
            btn.config(text="🔥 ON", bg=TH["accent"], fg="#0F1117")

    # ── controls ─────────────────────────────────────────────────────
    def _start(self):
        # if a thread is still alive (stuck in recovery), stop it and wait
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                return   # give up if it won't exit

        self._n_assembled = 0
        self._n_rejected  = 0
        self._assembled_var.set("0")
        self._rejected_var.set("0")
        self._yield_var.set("—")
        self._tree_shipped.delete(*self._tree_shipped.get_children())
        self._tree_rej.delete(*self._tree_rej.get_children())
        for key, iid in self._stat_rows.items():
            display = self._tree_stats.item(iid, "values")[0]
            self._tree_stats.item(iid, values=(display, 0, 0, 0, "—"))
        for lbl in self._rate_labels.values():
            lbl.config(text="—")
        for lbl in self._temp_val_labels.values():
            lbl.config(text="— °C", fg=TH["accent2"])
        for lbl in self._temp_stat_labels.values():
            lbl.config(text="READY", fg=TH["accent"])
        for btn in self._heater_btns.values():
            btn.config(text="🔥 ON", bg=TH["accent"], fg="#0F1117")
        self._reset_pipeline()
        self._stop_event.clear()
        self._line = InstrumentedLine(self._q, self._stop_event)
        self._thread = threading.Thread(
            target=self._line.run_until_stopped, daemon=True)
        self._thread.start()
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._blink()

    def _stop(self):
        self._stop_event.set()
        self._btn_stop.config(state="disabled")
        self._status_dot.config(fg=TH["danger"])

    # ── event pump ────────────────────────────────────────────────────
    def _poll(self):
        try:
            while True:
                evt = self._q.get_nowait()
                t   = evt["type"]

                if t == EVT_RATES:
                    # update sidebar defect rate labels
                    for name, rate in evt["rates"].items():
                        if name in self._rate_labels:
                            pct = f"{rate*100:.1f}%"
                            # colour: green < 5%, amber 5-10%, red > 10%
                            col = (TH["accent"] if rate < 0.05
                                   else TH["warn"] if rate < 0.10
                                   else TH["danger"])
                            self._rate_labels[name].config(text=pct, fg=col)

                elif t == EVT_STATS:
                    # update the BY COMPONENT tab in place
                    for key, vals in evt["stats"].items():
                        iid = self._stat_rows.get(key)
                        if iid is None:
                            continue
                        produced = vals["produced"]
                        rejected = vals["rejected"]
                        passed   = produced - rejected
                        rate = f"{passed/produced*100:.1f}%" if produced else "—"
                        display = self._tree_stats.item(iid, "values")[0]
                        self._tree_stats.item(iid, values=(
                            display, produced, rejected, passed, rate))

                elif t == EVT_ASSEMBLED:
                    self._n_assembled += 1
                    self._assembled_var.set(str(self._n_assembled))
                    self._update_yield()
                    # add row to SHIPPED tab
                    self._tree_shipped.insert("", "end", values=(
                        self._n_assembled,
                        f"#{evt['serial']}",
                        f"#{evt['handle']}",
                        f"#{evt['blade']}",
                        f"#{evt['slider']}",
                        f"#{evt['clip']}",
                    ))
                    self._tree_shipped.yview_moveto(1.0)

                elif t == EVT_REJECTED:
                    self._n_rejected += 1
                    self._rejected_var.set(str(self._n_rejected))
                    self._update_yield()
                    self._tree_rej.insert("", "end", values=(
                        evt["item"], evt["station"], evt["reason"]))
                    self._tree_rej.yview_moveto(1.0)

                elif t == EVT_STAGE:
                    self._highlight_stage(evt["stage"], evt["component"])

                elif t == EVT_STATUS:
                    self._status_var.set(evt["msg"])
                    msg = evt["msg"]
                    if evt.get("ok"):
                        dot_col = TH["accent"]       # green — running
                    elif "HEAT" in msg:
                        dot_col = TH["warn"]         # amber — heating up
                    elif "FAULT" in msg:
                        dot_col = TH["danger"]       # red — faulted
                    else:
                        dot_col = TH["fg_dim"]       # dim — idle/stopped
                    self._status_dot.config(fg=dot_col)

                elif t == EVT_FAULT:
                    # highlight which zone is out of band in the temp cards
                    for zone_key, ok_key in [("moulding","moulding_ok"),
                                             ("furnace","furnace_ok")]:
                        if not evt[ok_key]:
                            self._temp_stat_labels[zone_key].config(
                                text="FAULT", fg=TH["danger"])

                elif t == EVT_STOPPED:
                    self._reset_pipeline()
                    self._line = None
                    for btn in self._heater_btns.values():
                        btn.config(text="🔥 ON", bg=TH["accent"], fg="#0F1117")
                    self._btn_start.config(state="normal")

                elif t == EVT_TEMPS:
                    _status_colour = {
                        "COLD":    TH["fg_dim"],
                        "HEATING": TH["warn"],
                        "OK":      TH["accent"],
                        "FAULT":   TH["danger"],
                        "OFF":     TH["danger"],
                    }
                    for zone_key in ("moulding", "furnace"):
                        data   = evt[zone_key]
                        status = data["status"]
                        col    = _status_colour.get(status, TH["fg_dim"])
                        self._temp_val_labels[zone_key].config(
                            text=f"{data['temp']:.1f} °C", fg=col)
                        self._temp_stat_labels[zone_key].config(
                            text=status, fg=col)

        except queue.Empty:
            pass
        self.after(50, self._poll)


if __name__ == "__main__":
    HMI().mainloop()
"""
utility_knife_hmi.py
=====================
HMI for the Utility Knife Production Line.
Unique dark-green industrial theme with sidebar controls,
live stat cards, animated pipeline, and rejection log.

Run:  python utility_knife_hmi.py
Requires utility_knife_production_line.py in the same folder.

Author : [Your Name]
Course : Advanced Programming — SRH University Berlin
Due    : June 20, 2026
"""
from __future__ import annotations
import collections, queue, random, threading, time
import tkinter as tk
from tkinter import ttk, font as tkfont
from utility_knife_production_line import ComponentMaker, QualityControl, UtilityKnife, Quality

# ══════════════════════════════════════════════════════════════════════
#  THEME  — dark charcoal + neon green accent
# ══════════════════════════════════════════════════════════════════════
TH = dict(
    bg          = "#0F1117",   # near-black background
    sidebar     = "#161B27",   # slightly lighter sidebar
    card        = "#1C2333",   # stat card background
    card_border = "#2A3550",   # card border
    pipeline_bg = "#141921",   # pipeline canvas background
    accent      = "#00FF88",   # neon green — primary accent
    accent2     = "#00C4FF",   # cyan — secondary accent
    warn        = "#FFB800",   # amber warning
    danger      = "#FF4560",   # red danger / reject
    fg          = "#E2E8F5",   # primary text
    fg_dim      = "#556075",   # dimmed text / labels
    sep         = "#1E2840",   # separator lines
    # component colours — vivid so pipeline lights pop
    Handle      = "#3B82F6",   # blue
    Blade       = "#94A3B8",   # steel grey
    LockSlider  = "#F59E0B",   # orange
    BeltClip    = "#22C55E",   # green
    knife       = "#EF4444",   # red for assembled knife
)

# ══════════════════════════════════════════════════════════════════════
#  PIPELINE CANVAS LAYOUT
# ══════════════════════════════════════════════════════════════════════
_CW, _CH  = 760, 185
_BW, _BH  = 56, 26       # box full width / height
_BHW      = _BW // 2
_BHH      = _BH // 2

_LANE_Y = {"Handle": 28, "Blade": 73, "LockSlider": 118, "BeltClip": 163}
_CTR_Y  = (_LANE_Y["Handle"] + _LANE_Y["BeltClip"]) // 2 + 3

_X_MAKE  = 50
_X_QC    = 160
_X_BIN   = 270
_X_ASSM  = 390
_X_FINSP = 490
_X_PACK  = 590
_X_SHIP  = 690

STEP_DELAY = 0.38

# ══════════════════════════════════════════════════════════════════════
#  EVENT TYPES
# ══════════════════════════════════════════════════════════════════════
EVT_ASSEMBLED = "assembled"
EVT_REJECTED  = "rejected"
EVT_STAGE     = "stage"
EVT_STATUS    = "status"
EVT_STOPPED   = "stopped"

# ══════════════════════════════════════════════════════════════════════
#  INSTRUMENTED LINE  (background thread)
# ══════════════════════════════════════════════════════════════════════
class InstrumentedLine:
    COMPONENTS = [("Handle",0.05),("Blade",0.06),("LockSlider",0.04),("BeltClip",0.05)]
    ASSEMBLY_FAILURE_RATE = 0.02

    def __init__(self, q: queue.Queue, stop: threading.Event):
        self._q, self._stop = q, stop
        self.makers = {n: ComponentMaker(n, r) for n,r in self.COMPONENTS}
        self.qcs    = {n: QualityControl(n)    for n,_ in self.COMPONENTS}
        self.bins   = {n: collections.deque()  for n,_ in self.COMPONENTS}
        self.shipped: list[UtilityKnife] = []

    def _stage(self, key, comp):
        if not self._stop.is_set():
            self._q.put({"type": EVT_STAGE, "stage": key, "component": comp})
            time.sleep(STEP_DELAY)

    def _refill_bins(self):
        for name,_ in self.COMPONENTS:
            while not self.bins[name] and not self._stop.is_set():
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
                             lock_slider=parts["LockSlider"], belt_clip=parts["BeltClip"])
        self._stage("final_inspection", "knife")
        if not knife.is_complete():
            self._q.put({"type": EVT_REJECTED,
                "item": f"Knife #{knife.serial_number}",
                "station": "Final Inspection",
                "reason": "Failed blade / lock / clip functional test"})
            return None
        self._stage("packaging", "knife")
        self._stage("shipped",   "knife")
        self.shipped.append(knife)
        self._q.put({"type": EVT_ASSEMBLED, "serial": knife.serial_number})
        return knife

    def run_until_stopped(self):
        self._q.put({"type": EVT_STATUS, "msg": "RUNNING", "ok": True})
        while not self._stop.is_set():
            self._refill_bins()
            if not self._stop.is_set():
                self._assemble_one()
        self._q.put({"type": EVT_STATUS,
            "msg": f"STOPPED  •  {len(self.shipped)} knives shipped", "ok": False})
        self._q.put({"type": EVT_STOPPED})


# ══════════════════════════════════════════════════════════════════════
#  HMI  WINDOW
# ══════════════════════════════════════════════════════════════════════
class HMI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Utility Knife — Production HMI")
        self.configure(bg=TH["bg"])
        self.resizable(False, False)

        self._q          = queue.Queue()
        self._stop_event = threading.Event()
        self._thread     = None
        self._n_assembled = 0
        self._n_rejected  = 0
        self._active_stage= None
        self._stage_items = {}
        self._blink_state = False
        self._start_time  = None

        self._build_ui()
        self._poll()

    # ── helpers ───────────────────────────────────────────────────────
    def _label(self, parent, text, fg=None, bg=None, **kw):
        return tk.Label(parent, text=text,
                        fg=fg or TH["fg"], bg=bg or TH["bg"],
                        **kw)

    def _sep(self, parent, vertical=False):
        if vertical:
            tk.Frame(parent, bg=TH["sep"], width=1).pack(
                fill="y", padx=6, pady=4)
        else:
            tk.Frame(parent, bg=TH["sep"], height=1).pack(fill="x")

    # ── top header bar ────────────────────────────────────────────────
    def _build_header(self):
        bar = tk.Frame(self, bg=TH["sidebar"], pady=0)
        bar.pack(fill="x")

        # left: logo block
        left = tk.Frame(bar, bg=TH["accent"], width=6)
        left.pack(side="left", fill="y")

        tk.Label(bar, text="⌧", bg=TH["sidebar"], fg=TH["accent"],
                 font=("Segoe UI", 22, "bold"), padx=12, pady=8
                 ).pack(side="left")

        title_block = tk.Frame(bar, bg=TH["sidebar"])
        title_block.pack(side="left", pady=6)
        tk.Label(title_block, text="UTILITY KNIFE  PRODUCTION LINE",
                 bg=TH["sidebar"], fg=TH["fg"],
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(title_block, text="Human–Machine Interface  •  SRH Advanced Programming",
                 bg=TH["sidebar"], fg=TH["fg_dim"],
                 font=("Segoe UI", 8)).pack(anchor="w")

        # right: status pill
        self._status_frame = tk.Frame(bar, bg=TH["sidebar"], padx=18)
        self._status_frame.pack(side="right")
        self._status_dot = tk.Label(self._status_frame, text="●",
                                    bg=TH["sidebar"], fg=TH["fg_dim"],
                                    font=("Segoe UI", 14))
        self._status_dot.pack(side="left")
        self._status_var = tk.StringVar(value="IDLE")
        tk.Label(self._status_frame, textvariable=self._status_var,
                 bg=TH["sidebar"], fg=TH["fg_dim"],
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(4,0))

    # ── stat card ─────────────────────────────────────────────────────
    def _stat_card(self, parent, label, var, accent, width=140):
        f = tk.Frame(parent, bg=TH["card"],
                     highlightbackground=TH["card_border"],
                     highlightthickness=1, padx=16, pady=10, width=width)
        f.pack(side="left", padx=6, pady=8)
        f.pack_propagate(False)
        tk.Label(f, text=label, bg=TH["card"], fg=TH["fg_dim"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        tk.Label(f, textvariable=var, bg=TH["card"], fg=accent,
                 font=("Segoe UI", 32, "bold")).pack(anchor="w")
        return f

    # ── sidebar button ────────────────────────────────────────────────
    def _sidebar_btn(self, parent, text, color, command, state="normal"):
        b = tk.Button(parent, text=text, bg=color, fg="#0F1117",
                      activebackground=color, activeforeground="#0F1117",
                      font=("Segoe UI", 10, "bold"),
                      relief="flat", cursor="hand2", pady=8, padx=0,
                      width=14, state=state, command=command,
                      bd=0, highlightthickness=0)
        b.pack(fill="x", pady=4)
        return b

    # ── main layout ───────────────────────────────────────────────────
    def _build_ui(self):
        self._build_header()
        self._sep(self)

        # body  =  sidebar | main content
        body = tk.Frame(self, bg=TH["bg"])
        body.pack(fill="both", expand=True)

        self._build_sidebar(body)
        tk.Frame(body, bg=TH["sep"], width=1).pack(side="left", fill="y")
        self._build_main(body)

    # ── left sidebar ──────────────────────────────────────────────────
    def _build_sidebar(self, parent):
        sb = tk.Frame(parent, bg=TH["sidebar"], width=180, padx=14)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        tk.Label(sb, text="CONTROLS", bg=TH["sidebar"], fg=TH["fg_dim"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(16,4))

        self._btn_start = self._sidebar_btn(
            sb, "▶  START", TH["accent"], self._start)
        self._btn_stop  = self._sidebar_btn(
            sb, "■  STOP",  TH["danger"], self._stop, state="disabled")

        tk.Frame(sb, bg=TH["sep"], height=1).pack(fill="x", pady=10)

        tk.Label(sb, text="COMPONENTS", bg=TH["sidebar"], fg=TH["fg_dim"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(4,6))

        for name, color_key in [("Handle","Handle"),("Blade","Blade"),
                                 ("Lock Slider","LockSlider"),("Belt Clip","BeltClip")]:
            row = tk.Frame(sb, bg=TH["sidebar"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text="▬", bg=TH["sidebar"],
                     fg=TH[color_key], font=("Segoe UI", 10)).pack(side="left")
            tk.Label(row, text=f"  {name}", bg=TH["sidebar"],
                     fg=TH["fg"], font=("Segoe UI", 8)).pack(side="left")

        tk.Frame(sb, bg=TH["sep"], height=1).pack(fill="x", pady=10)
        tk.Label(sb, text="DEFECT RATES", bg=TH["sidebar"], fg=TH["fg_dim"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(4,6))
        for name, rate in [("Handle","5%"),("Blade","6%"),
                            ("Slider","4%"),("Clip","5%")]:
            row = tk.Frame(sb, bg=TH["sidebar"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text=name, bg=TH["sidebar"],
                     fg=TH["fg_dim"], font=("Segoe UI", 8), width=8,
                     anchor="w").pack(side="left")
            tk.Label(row, text=rate, bg=TH["sidebar"],
                     fg=TH["warn"], font=("Segoe UI", 8,
                     "bold")).pack(side="right")

    # ── right main area ───────────────────────────────────────────────
    def _build_main(self, parent):
        main = tk.Frame(parent, bg=TH["bg"])
        main.pack(side="left", fill="both", expand=True)

        # stat cards row
        cards_row = tk.Frame(main, bg=TH["bg"], padx=10)
        cards_row.pack(fill="x")

        self._assembled_var = tk.StringVar(value="0")
        self._rejected_var  = tk.StringVar(value="0")

        self._stat_card(cards_row, "KNIVES SHIPPED",
                        self._assembled_var, TH["accent"])
        self._stat_card(cards_row, "TOTAL REJECTS",
                        self._rejected_var,  TH["danger"])
        # yield rate card (computed)
        self._yield_var = tk.StringVar(value="—")
        self._stat_card(cards_row, "YIELD RATE",
                        self._yield_var, TH["accent2"])
        # throughput rate card
        self._rate_var = tk.StringVar(value="—")
        self._stat_card(cards_row, "KNIVES / MIN",
                        self._rate_var, TH["warn"])

        self._sep(main)

        # pipeline section
        pipe_header = tk.Frame(main, bg=TH["bg"], padx=16, pady=6)
        pipe_header.pack(fill="x")
        tk.Label(pipe_header, text="PRODUCTION PIPELINE",
                 bg=TH["bg"], fg=TH["fg_dim"],
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(pipe_header,
                 text="station highlights in real time as work passes through",
                 bg=TH["bg"], fg=TH["fg_dim"],
                 font=("Segoe UI", 7)).pack(side="left", padx=10)

        self._build_pipeline(main)
        self._sep(main)

        # rejection log
        log_hdr = tk.Frame(main, bg=TH["bg"], padx=16, pady=6)
        log_hdr.pack(fill="x")
        tk.Label(log_hdr, text="REJECTION  LOG",
                 bg=TH["bg"], fg=TH["fg_dim"],
                 font=("Segoe UI", 8, "bold")).pack(side="left")

        log_area = tk.Frame(main, bg=TH["bg"], padx=14, pady=4)
        log_area.pack(fill="both", expand=True)

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("X.Treeview",
            background=TH["card"], foreground=TH["fg"],
            fieldbackground=TH["card"], rowheight=24,
            font=("Segoe UI", 9),
            borderwidth=0, relief="flat")
        style.configure("X.Treeview.Heading",
            background=TH["sidebar"], foreground=TH["accent2"],
            font=("Segoe UI", 8, "bold"), relief="flat")
        style.map("X.Treeview",
            background=[("selected", TH["accent2"])],
            foreground=[("selected","#000")])

        cols = ("Item","Station","Reason")
        wrap = tk.Frame(log_area, bg=TH["bg"])
        wrap.pack(fill="both", expand=True)

        self._tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                  style="X.Treeview", height=7)
        for col, w in zip(cols, (185, 195, 300)):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=w, anchor="w")

        sb2 = ttk.Scrollbar(wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb2.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")
        tk.Frame(main, bg=TH["bg"], height=10).pack()

    # ── pipeline canvas ───────────────────────────────────────────────
    def _build_pipeline(self, parent):
        c = tk.Canvas(parent, bg=TH["pipeline_bg"],
                      width=_CW, height=_CH,
                      highlightthickness=0)
        c.pack(padx=14, pady=4)
        self._pipe_canvas = c

        abbr = {"Handle":"HNDL","Blade":"BLDE",
                "LockSlider":"SLDR","BeltClip":"CLIP"}

        def box(cx, cy, line1, line2, key, dim=False):
            x0,y0 = cx-_BHW, cy-_BHH
            x1,y1 = cx+_BHW, cy+_BHH
            r = c.create_rectangle(x0,y0,x1,y1,
                fill=TH["pipeline_bg"],
                outline=TH["fg_dim"] if dim else TH["sep"],
                width=1)
            t = c.create_text(cx, cy-5, text=line1,
                fill=TH["fg_dim"], font=("Segoe UI",6,"bold"))
            t2= c.create_text(cx, cy+6, text=line2,
                fill=TH["fg_dim"], font=("Segoe UI",6))
            self._stage_items[key] = (r, t, t2)

        def arrow(x1,y1,x2,y2,curved=False):
            if curved:
                # midpoint for slight curve
                mx = (x1+x2)//2
                c.create_line(x1,y1,mx,y1,mx,y2,x2,y2,
                    fill=TH["sep"], width=1,
                    arrow=tk.LAST, arrowshape=(5,7,3), smooth=True)
            else:
                c.create_line(x1,y1,x2,y2,
                    fill=TH["sep"], width=1,
                    arrow=tk.LAST, arrowshape=(5,7,3))

        # draw lane labels on left edge
        for name, y in _LANE_Y.items():
            c.create_rectangle(2, y-_BHH, 4, y+_BHH,
                fill=TH[name], outline="")

        # component lanes
        for name, y in _LANE_Y.items():
            s = abbr[name]
            box(_X_MAKE, y, "MAKE", s,  f"make_{name}")
            box(_X_QC,   y, "QC",   s,  f"qc_{name}")
            box(_X_BIN,  y, "BIN",  s,  f"bin_{name}")
            arrow(_X_MAKE+_BHW, y,   _X_QC -_BHW, y)
            arrow(_X_QC  +_BHW, y,   _X_BIN-_BHW, y)
            # converge to assembly (curved lines)
            arrow(_X_BIN+_BHW, y, _X_ASSM-_BHW, _CTR_Y, curved=True)

        # downstream row
        box(_X_ASSM,  _CTR_Y, "ASSM",  "",      "assembly")
        box(_X_FINSP, _CTR_Y, "FINAL", "INSP",  "final_inspection")
        box(_X_PACK,  _CTR_Y, "PACK",  "",      "packaging")
        box(_X_SHIP,  _CTR_Y, "SHIP",  "✓",     "shipped")

        arrow(_X_ASSM +_BHW, _CTR_Y, _X_FINSP-_BHW, _CTR_Y)
        arrow(_X_FINSP+_BHW, _CTR_Y, _X_PACK -_BHW, _CTR_Y)
        arrow(_X_PACK +_BHW, _CTR_Y, _X_SHIP -_BHW, _CTR_Y)

    # ── stage highlighting ────────────────────────────────────────────
    def _highlight_stage(self, stage, component):
        if self._active_stage and self._active_stage in self._stage_items:
            r,t,t2 = self._stage_items[self._active_stage]
            self._pipe_canvas.itemconfig(r,  fill=TH["pipeline_bg"],
                                         outline=TH["sep"])
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
            self._pipe_canvas.itemconfig(r,  fill=TH["pipeline_bg"],
                                         outline=TH["sep"])
            self._pipe_canvas.itemconfig(t,  fill=TH["fg_dim"])
            self._pipe_canvas.itemconfig(t2, fill=TH["fg_dim"])
        self._active_stage = None

    # ── status dot blink ─────────────────────────────────────────────
    def _blink(self):
        if not self._stop_event.is_set():
            self._blink_state = not self._blink_state
            self._status_dot.config(
                fg=TH["accent"] if self._blink_state else TH["sidebar"])
            self.after(600, self._blink)

    # ── controls ─────────────────────────────────────────────────────
    def _start(self):
        if self._thread and self._thread.is_alive(): return
        self._n_assembled = 0
        self._n_rejected  = 0
        self._assembled_var.set("0")
        self._rejected_var.set("0")
        self._yield_var.set("—")
        self._rate_var.set("—")
        self._start_time  = None
        self._tree.delete(*self._tree.get_children())
        self._reset_pipeline()
        self._stop_event.clear()
        random.seed(42)
        line = InstrumentedLine(self._q, self._stop_event)
        self._thread = threading.Thread(
            target=line.run_until_stopped, daemon=True)
        self._thread.start()
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._blink()

    def _stop(self):
        self._stop_event.set()
        self._btn_stop.config(state="disabled")
        self._status_dot.config(fg=TH["danger"])

    # ── event pump ───────────────────────────────────────────────────
    def _poll(self):
        try:
            while True:
                evt = self._q.get_nowait()
                t = evt["type"]
                if t == EVT_ASSEMBLED:
                    if self._start_time is None:
                        self._start_time = time.monotonic()
                    self._n_assembled += 1
                    self._assembled_var.set(str(self._n_assembled))
                    total = self._n_assembled + self._n_rejected
                    if total:
                        pct = int(self._n_assembled / total * 100)
                        self._yield_var.set(f"{pct}%")
                    elapsed_min = (time.monotonic() - self._start_time) / 60
                    if elapsed_min > 0:
                        rate = self._n_assembled / elapsed_min
                        self._rate_var.set(f"{rate:.1f}")
                elif t == EVT_REJECTED:
                    self._n_rejected += 1
                    self._rejected_var.set(str(self._n_rejected))
                    total = self._n_assembled + self._n_rejected
                    if total:
                        pct = int(self._n_assembled / total * 100)
                        self._yield_var.set(f"{pct}%")
                    self._tree.insert("", "end", values=(
                        evt["item"], evt["station"], evt["reason"]))
                    self._tree.yview_moveto(1.0)
                elif t == EVT_STAGE:
                    self._highlight_stage(evt["stage"], evt["component"])
                elif t == EVT_STATUS:
                    self._status_var.set(evt["msg"])
                    color = TH["accent"] if evt.get("ok") else TH["fg_dim"]
                    self._status_dot.config(fg=color)
                elif t == EVT_STOPPED:
                    self._reset_pipeline()
                    self._btn_start.config(state="normal")
                    self._rate_var.set("—")
        except queue.Empty:
            pass
        self.after(50, self._poll)


if __name__ == "__main__":
    HMI().mainloop()
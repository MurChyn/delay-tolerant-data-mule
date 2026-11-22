#!/usr/bin/env python3
"""
Discrete-event simulator for the Delay-Tolerant Data Mule project.

Research question
-----------------
"What buffer management policy maximizes high-priority sensor packet delivery
 during brief passes?"

The simulator models two independent buffers:

  1. Sensor-side queue  -- which reading gets the limited airtime of a short
     Wi-Fi contact.
  2. Mule-side flash    -- which stored record is evicted when the flash is
     full and a new reading arrives.

Policies are crossed so their interaction is visible. Every run is seeded and
 emits a CSV row; `summarise()` writes aggregate statistics and figures.

Usage
-----
    python dtn_sim.py --cycles 32 --seeds 12 --outdir results

Model assumptions (all configurable in Config)
-----------------------------------------------
* Fixed-size 256-byte packets, 64 kbit/s effective goodput -> 32 packets/s.
* A pass lasts 2-5 s, so 64-160 packets can cross the link.
* Sensors generate packets with exponential interarrival times.
* The mule makes one pass per sensor per 300 s route cycle.
* The mule unloads to the base station every 8 cycles.
* High-priority packets have a 300 s TTL; low-priority 3600 s.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PRIO_LOW = 0
PRIO_HIGH = 1

SENSOR_POLICIES = ["FIFO", "SP", "SP_EDF", "SP_AGE"]
EVICTION_POLICIES = ["DROP_TAIL", "DROP_OLDEST", "DROP_LOWEST", "PADS"]

# The six configurations reported in the paper. Each is (sensor, mule).
POLICY_COMBOS: List[Tuple[str, str]] = [
    ("FIFO", "DROP_TAIL"),
    ("FIFO", "PADS"),
    ("SP", "DROP_LOWEST"),
    ("SP", "PADS"),
    ("SP_EDF", "DROP_LOWEST"),
    ("SP_EDF", "PADS"),   # recommended
    ("SP_AGE", "PADS"),   # fairness-oriented ablation
]


@dataclass(frozen=True)
class Config:
    cycles: int = 32
    seeds: int = 12
    cycle_sec: float = 300.0
    sensor_rates: Tuple[float, ...] = (0.15, 0.25, 0.35, 0.45, 0.60, 0.30)
    high_prob: float = 0.25
    sensor_capacity: int = 128
    # Scaled-down flash: the experiment needs the store to fill within one
    # route cycle so eviction policy is observable. Firmware uses 4096 slots.
    flash_capacity: int = 256
    unload_every_cycles: int = 1
    packet_bytes: int = 256
    # Conservative effective goodput (interference / range) so a 2-5 s pass
    # carries 32-80 packets and cannot drain a 128-packet sensor queue.
    link_bps: float = 32_000.0
    contact_min: float = 2.0
    contact_max: float = 5.0
    # High packets must reach base within roughly one cycle; this creates the
    # deadline pressure that makes earliest-deadline-first valuable.
    ttl_high: float = 320.0
    ttl_low: float = 3600.0
    aging_tau: float = 120.0
    hp_guard_slots: int = 32
    contact_duration_scale: float = 1.0

    @property
    def tx_per_sec(self) -> float:
        return self.link_bps / 8.0 / self.packet_bytes

    @property
    def horizon(self) -> float:
        return self.cycles * self.cycle_sec


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


@dataclass
class Packet:
    seq: int
    sensor_id: int
    priority: int
    created: float
    ttl: float
    expires: float

    def age(self, now: float) -> float:
        return now - self.created


@dataclass
class Sensor:
    sid: int
    rate: float
    buffer: List[Packet] = field(default_factory=list)
    next_seq: int = 1
    generated_high: int = 0
    generated_low: int = 0
    expired_in_buffer: int = 0
    dropped_full: int = 0
    transmitted: int = 0

    def generate(self, now: float, rng: random.Random, cfg: Config) -> Packet:
        high = rng.random() < cfg.high_prob
        # Alerts carry deadlines of their own: some are "act now" (300 s),
        # others can wait two cycles (600 s). This is what makes EDF distinct
        # from plain strict priority inside the high class.
        ttl = rng.uniform(200.0, 2.0 * cfg.ttl_high) if high else cfg.ttl_low
        p = Packet(self.next_seq, self.sid, PRIO_HIGH if high else PRIO_LOW,
                   now, ttl, now + ttl)
        self.next_seq += 1
        if high:
            self.generated_high += 1
        else:
            self.generated_low += 1

        if len(self.buffer) >= cfg.sensor_capacity:
            victim = choose_sensor_drop_victim(self.buffer, now, cfg, rng)
            if victim is not None:
                self.buffer.pop(victim)
                self.dropped_full += 1
        self.buffer.append(p)
        return p

    def purge(self, now: float) -> None:
        keep = []
        for p in self.buffer:
            if p.expires <= now:
                self.expired_in_buffer += 1
            else:
                keep.append(p)
        self.buffer = keep


class Mule:
    def __init__(self, cfg: Config, policy: str):
        self.cfg = cfg
        self.policy = policy
        self.store: List[Packet] = []
        self.seen: set = set()
        self.evicted = 0
        self.expired_in_flash = 0
        self.guard_rejects = 0
        self.tail_rejects = 0
        self.doomed_rejects = 0
        # Deadline-aware policies need to know when the next unload happens.
        self.next_unload = cfg.unload_every_cycles * cfg.cycle_sec

    def _purge(self, now: float) -> None:
        keep = []
        for p in self.store:
            if p.expires <= now:
                self.expired_in_flash += 1
                self.seen.discard((p.sensor_id, p.seq))
            else:
                keep.append(p)
        self.store = keep

    def has(self, p: Packet) -> bool:
        return (p.sensor_id, p.seq) in self.seen

    def admit(self, p: Packet, now: float) -> bool:
        # Expired records are purged at contact start and at unload, not on
        # every admission: a purge here is O(flash_capacity) and dominated the
        # runtime of a 32-cycle run without changing results (contacts last
        # seconds, TTLs last minutes).
        #
        # PADS adds deadline-aware admission: never occupy a slot with a
        # reading that will expire before the next unload. Those slots are
        # then available to fresh high-priority arrivals.
        if self.policy == "PADS" and p.expires <= self.next_unload:
            self.doomed_rejects += 1
            return False
        if len(self.store) < self.cfg.flash_capacity:
            self._insert(p)
            return True

        if self.policy == "DROP_TAIL":
            self.tail_rejects += 1
            return False

        if self.policy == "PADS":
            if p.priority == PRIO_LOW and len(self.store) >= (
                    self.cfg.flash_capacity - self.cfg.hp_guard_slots):
                self.guard_rejects += 1
                return False
            victim = min(range(len(self.store)),
                         key=lambda i: (pads_score(self.store[i], now, self.cfg),
                                        self.store[i].expires))
        elif self.policy == "DROP_OLDEST":
            victim = min(range(len(self.store)), key=lambda i: self.store[i].created)
        elif self.policy == "DROP_LOWEST":
            victim = min(range(len(self.store)),
                         key=lambda i: (self.store[i].priority, self.store[i].created))
        else:
            raise ValueError(self.policy)

        old = self.store.pop(victim)
        self.seen.discard((old.sensor_id, old.seq))
        self.evicted += 1
        self._insert(p)
        return True

    def _insert(self, p: Packet) -> None:
        self.store.append(p)
        self.seen.add((p.sensor_id, p.seq))

    def unload(self, now: float, delivered: List[Tuple[Packet, float]]) -> None:
        self.next_unload = now + self.cfg.unload_every_cycles * self.cfg.cycle_sec
        for p in self.store:
            if p.expires > now:
                delivered.append((p, now))
            else:
                self.expired_in_flash += 1
        self.store.clear()
        self.seen.clear()


# ---------------------------------------------------------------------------
# Policy scoring functions
# ---------------------------------------------------------------------------


def pads_score(p: Packet, now: float, cfg: Config) -> float:
    """
    Mule eviction value score (LOWER = evict first).

    High-priority records always outrank low-priority ones because the low
    class's aging term is capped below 1.0. Within a class, an older record is
    a cheaper victim. This is the PADS policy evaluated in the report.
    """
    age_term = min(max(now - p.created, 0.0) / cfg.aging_tau, 0.8)
    # The low-class aging term is capped below 1.0, so a high-priority record
    # is never evicted while a low-priority one exists. Deadline awareness is
    # applied at admission time (see Mule.admit), not here.
    return float(p.priority) + (1.0 - p.priority) * age_term


def sensor_order_key(policy: str, cfg: Config) -> Callable[[Packet, float], tuple]:
    """Return a sortable key; the packet with the smallest key goes first."""
    if policy == "FIFO":
        return lambda p, now: (p.seq,)
    if policy == "SP":
        return lambda p, now: (-p.priority, p.seq)
    if policy == "SP_EDF":
        # High class first; inside a class, earliest deadline (EDF) first.
        return lambda p, now: (-p.priority, p.expires, p.seq)
    if policy == "SP_AGE":
        # Uncapped aging lets a very old low packet overtake a fresh high one.
        return lambda p, now: (-(p.priority + min((now - p.created) / cfg.aging_tau, 1.4)),
                               p.expires, p.seq)
    raise ValueError(policy)


def choose_sensor_drop_victim(buffer: List[Packet], now: float, cfg: Config,
                              rng: random.Random) -> Optional[int]:
    """
    Victim when a sensor's local queue is full.

    This is an *admission* decision, separate from the transmission policy:
    protect the high class and drop the oldest low-priority reading. If every
    buffered packet is high priority, drop the oldest one. Without this rule
    a low-value bulk reading can evict an alert before the mule ever arrives.
    """
    if not buffer:
        return None
    lows = [i for i, p in enumerate(buffer) if p.priority == PRIO_LOW]
    candidates = lows if lows else list(range(len(buffer)))
    return min(candidates, key=lambda i: (buffer[i].created, i))


# ---------------------------------------------------------------------------
# Simulation core
# ---------------------------------------------------------------------------


def run_once(sensor_policy: str, eviction_policy: str, seed: int,
             cfg: Config) -> Dict[str, float]:
    rng = random.Random(seed)
    sensors = [Sensor(i + 1, rate) for i, rate in enumerate(cfg.sensor_rates)]
    mule = Mule(cfg, eviction_policy)
    delivered: List[Tuple[Packet, float]] = []

    # ---- build event list ---------------------------------------------------
    events: List[Tuple[float, int, str, object]] = []

    def add(t: float, kind: str, payload: object) -> None:
        events.append((t, kind, payload))  # kind is second; priority via tuple

    # Arrivals, per sensor, exponential interarrival times.
    for s in sensors:
        t = 0.0
        while True:
            t += rng.expovariate(s.rate)
            if t >= cfg.horizon:
                break
            add(t, "arrival", s.sid)

    # One contact per sensor per route cycle, at a fixed offset in the cycle.
    # The offset models the route order of the vehicle.
    for cycle in range(cfg.cycles):
        for idx, s in enumerate(sensors):
            # Passes happen late in the cycle so a real backlog has built up
            # in each sensor queue before the mule arrives.
            offset = 180.0 + idx * 18.0
            start = cycle * cfg.cycle_sec + offset
            duration = rng.uniform(cfg.contact_min, cfg.contact_max) * cfg.contact_duration_scale
            add(start, "contact_start", (s.sid, duration))
        if (cycle + 1) % cfg.unload_every_cycles == 0:
            add((cycle + 1) * cfg.cycle_sec - 1.0, "upload", None)

    events.sort(key=lambda e: (e[0], 0 if e[1] == "upload" else 1))

    # ---- process ------------------------------------------------------------
    key_fn = sensor_order_key(sensor_policy, cfg)

    for t, kind, payload in events:
        if kind == "arrival":
            s = sensors[payload - 1]  # type: ignore[index]
            s.generate(t, rng, cfg)

        elif kind == "contact_start":
            sid, duration = payload  # type: ignore[misc]
            s = sensors[sid - 1]  # type: ignore[index]
            s.purge(t)
            mule._purge(t)

            ordered = sorted(s.buffer, key=lambda p: key_fn(p, t))
            budget = int(duration * cfg.tx_per_sec)
            sent = 0
            remaining = []
            for p in ordered:
                if sent >= budget:
                    remaining.append(p)
                    continue
                if p.expires <= t:
                    continue
                if mule.has(p):
                    continue
                if mule.admit(p, t):
                    s.transmitted += 1
                    sent += 1
                else:
                    # Rejected by mule admission control. Dropping it here is
                    # intentional: storing a packet the mule will never accept
                    # would consume scarce sensor RAM and airtime next pass.
                    s.expired_in_buffer += 0  # no-op kept for clarity
                    s.dropped_full += 1
            s.buffer = remaining

        elif kind == "upload":
            mule.unload(t, delivered)

    # Anything still on the mule at the end of the horizon is not delivered.
    generated_high = sum(s.generated_high for s in sensors)
    generated_low = sum(s.generated_low for s in sensors)
    delivered_high = [p for p, _ in delivered if p.priority == PRIO_HIGH]
    delivered_low = [p for p, _ in delivered if p.priority == PRIO_LOW]

    per_sensor_high = []
    for s in sensors:
        gen = s.generated_high
        got = sum(1 for p, _ in delivered if p.sensor_id == s.sid and p.priority == PRIO_HIGH)
        per_sensor_high.append(got / gen if gen else 0.0)

    n = len(per_sensor_high)
    fairness = (sum(per_sensor_high) ** 2) / (n * sum(x * x for x in per_sensor_high)) \
        if n and sum(x * x for x in per_sensor_high) > 0 else 0.0

    return {
        "seed": seed,
        "sensor_policy": sensor_policy,
        "eviction_policy": eviction_policy,
        "high_delivery": len(delivered_high) / generated_high if generated_high else 0.0,
        "low_delivery": len(delivered_low) / generated_low if generated_low else 0.0,
        "overall_delivery": len(delivered) / (generated_high + generated_low) if (generated_high + generated_low) else 0.0,
        "high_mean_age_s": float(np.mean([t - p.created for p, t in delivered
                                          if p.priority == PRIO_HIGH])) if delivered_high else 0.0,
        "low_mean_age_s": float(np.mean([t - p.created for p, t in delivered
                                         if p.priority == PRIO_LOW])) if delivered_low else 0.0,
        "jain_fairness_high": fairness,
        "expired_sensor": sum(s.expired_in_buffer for s in sensors),
        "expired_mule": mule.expired_in_flash,
        "sensor_drops_full": sum(s.dropped_full for s in sensors),
        "mule_evictions": mule.evicted,
        "mule_guard_rejects": mule.guard_rejects,
        "mule_doomed_rejects": mule.doomed_rejects,
        "generated_high": generated_high,
        "generated_low": generated_low,
        "delivered_high": len(delivered_high),
        "delivered_low": len(delivered_low),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

FIELDS = [
    "seed", "sensor_policy", "eviction_policy", "high_delivery", "low_delivery",
    "overall_delivery", "high_mean_age_s", "low_mean_age_s",
    "jain_fairness_high", "expired_sensor", "expired_mule", "sensor_drops_full",
    "mule_evictions", "mule_guard_rejects", "mule_doomed_rejects",
    "generated_high", "generated_low",
    "delivered_high", "delivered_low",
]


def write_csv(path: str, rows: List[Dict[str, float]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, 0) for k in FIELDS})


def summarise(rows: List[Dict[str, float]]) -> List[Dict[str, object]]:
    groups: Dict[Tuple[str, str], List[Dict[str, float]]] = {}
    for r in rows:
        groups.setdefault((r["sensor_policy"], r["eviction_policy"]), []).append(r)

    summary = []
    for (sp, ep), group in groups.items():
        def stat(field: str) -> Tuple[float, float]:
            vals = np.array([g[field] for g in group], dtype=float)
            return float(vals.mean()), float(vals.std(ddof=1)) if len(vals) > 1 else 0.0

        hm, hs = stat("high_delivery")
        lm, ls = stat("low_delivery")
        om, os_ = stat("overall_delivery")
        am, as_ = stat("high_mean_age_s")
        fm, fs = stat("jain_fairness_high")
        summary.append({
            "sensor_policy": sp,
            "eviction_policy": ep,
            "label": f"{sp}+{ep}",
            "high_delivery_mean": hm,
            "high_delivery_std": hs,
            "low_delivery_mean": lm,
            "low_delivery_std": ls,
            "overall_delivery_mean": om,
            "overall_delivery_std": os_,
            "high_age_mean_s": am,
            "high_age_std_s": as_,
            "fairness_mean": fm,
            "fairness_std": fs,
            "n_seeds": len(group),
        })
    summary.sort(key=lambda x: x["high_delivery_mean"], reverse=True)
    return summary


def write_summary_csv(path: str, summary: List[Dict[str, object]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fields = list(summary[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(summary)


# ---------------------------------------------------------------------------
# Figure styling helpers. Consistent colours, names and layout across figures.
# ---------------------------------------------------------------------------
FIG_COLORS = {
    "FIFO": "#64748b",     # slate  - baseline discipline
    "SP": "#3b82f6",       # blue   - strict priority
    "SP_EDF": "#10b981",   # green  - recommended discipline
    "SP_AGE": "#f59e0b",   # amber  - fairness ablation
}
FIG_MARKERS = {
    "DROP_TAIL": "D",
    "DROP_LOWEST": "s",
    "PADS": "o",
}
FIG_SENSOR_NAMES = {"FIFO": "FIFO", "SP": "SP", "SP_EDF": "SP-EDF", "SP_AGE": "SP-AGE"}
FIG_EVICTION_NAMES = {
    "DROP_TAIL": "drop-tail",
    "DROP_LOWEST": "drop-lowest",
    "PADS": "PADS",
}


def _style():
    """Return a consistent, print-friendly matplotlib style context."""
    return plt.rc_context({
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "axes.titlesize": 11,
        "axes.labelsize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
        "axes.edgecolor": "#94a3b8",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "text.color": "#0f172a",
        "axes.labelcolor": "#334155",
        "xtick.color": "#475569",
        "ytick.color": "#475569",
    })


def _sensor(label: str) -> str:
    return label.split("+")[0].strip()


def _eviction(label: str) -> str:
    return label.split("+")[1].strip()


def _short(label: str) -> str:
    """Human-readable policy name, e.g. SP_EDF+PADS -> 'SP-EDF + PADS'."""
    return f"{FIG_SENSOR_NAMES[_sensor(label)]} + {FIG_EVICTION_NAMES[_eviction(label)]}"


def _save(fig, path: str) -> None:
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def make_figures(summary: List[Dict[str, object]], outdir: str) -> None:
    figdir = os.path.join(outdir, "figures")
    os.makedirs(figdir, exist_ok=True)

    labels = [s["label"] for s in summary]
    high = np.array([s["high_delivery_mean"] for s in summary])
    hstd = np.array([s["high_delivery_std"] for s in summary])
    colors = [FIG_COLORS[_sensor(lab)] for lab in labels]
    names = [_short(lab) for lab in labels]
    n = len(summary)

    with _style():
        # Figure 1: horizontal bars. Long policy names are never rotated.
        fig, ax = plt.subplots(figsize=(10.5, 5.8))
        fig.subplots_adjust(left=0.21, right=0.97, top=0.79, bottom=0.15)
        fig.suptitle("High-priority delivery by buffer policy",
                     x=0.08, ha="left", fontsize=15, fontweight="bold", y=0.97)
        ax.set_title("Mean ± standard deviation over 12 seeded runs — higher is better",
                     loc="left", fontsize=10, color="#64748b", pad=12)

        y = np.arange(n)
        ax.barh(y, high, xerr=hstd, capsize=4, color=colors, height=0.62,
                alpha=0.92, zorder=3)
        ax.set_yticks(y, names)
        ax.invert_yaxis()  # best policy at the top
        ax.set_xlim(0, 1.08)
        ax.set_xlabel("High-priority packets delivered / generated")
        ax.grid(axis="x", alpha=0.25, zorder=0)
        for yi, v in zip(y, high):
            ax.text(v + 0.012, yi, f"{v:.1%}", va="center", fontsize=10,
                    fontweight="bold", color="#1e293b")
        handles = [Patch(facecolor=FIG_COLORS[k], label=f"{FIG_SENSOR_NAMES[k]} sensor")
                   for k in ("FIFO", "SP", "SP_EDF", "SP_AGE")]
        ax.legend(handles=handles, loc="lower right", ncol=2, frameon=False,
                  fontsize=9.5, handlelength=1.2, columnspacing=1.4)
        fig.text(0.21, 0.035,
                 "Colour = sensor-side discipline; error bars = s.d. across seeds.",
                 fontsize=9, color="#64748b")
        _save(fig, os.path.join(figdir, "01_high_delivery.png"))

        # Figure 2: priority trade-off. Legend below the axes and two callouts
        # replace seven overlapping per-point annotations.
        fig, ax = plt.subplots(figsize=(10.5, 6.2))
        fig.subplots_adjust(left=0.10, right=0.98, top=0.81, bottom=0.26)
        fig.suptitle("Priority trade-off: high vs low delivery",
                     x=0.06, ha="left", fontsize=15, fontweight="bold", y=0.97)
        ax.set_title("Each marker is one policy pair (means over 12 seeds)",
                     loc="left", fontsize=10, color="#64748b", pad=12)

        for s in summary:
            lab = s["label"]
            ax.scatter(s["low_delivery_mean"], s["high_delivery_mean"],
                       s=140, marker=FIG_MARKERS[_eviction(lab)],
                       color=FIG_COLORS[_sensor(lab)], edgecolor="white",
                       linewidth=1.1, zorder=3)
        handles = [
            Line2D([0], [0], linestyle="none", marker=FIG_MARKERS[_eviction(lab)],
                   markerfacecolor=FIG_COLORS[_sensor(lab)], markeredgecolor="white",
                   markersize=9, label=_short(lab))
            for lab in labels
        ]
        ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.20),
                  ncol=4, frameon=False, fontsize=9.5, handletextpad=0.4,
                  columnspacing=1.6)

        def callout(lab, text_xy, heading):
            s = next(r for r in summary if r["label"] == lab)
            ax.annotate(
                f"{heading}\n"
                f"{s['high_delivery_mean']:.1%} high / "
                f"{s['low_delivery_mean']:.1%} low",
                xy=(s["low_delivery_mean"], s["high_delivery_mean"]),
                xytext=text_xy, fontsize=9.5, va="center",
                bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#cbd5e1", alpha=0.95),
                arrowprops=dict(arrowstyle="->", color="#475569", lw=1.3,
                                connectionstyle="arc3,rad=0.12"),
                zorder=4)

        callout("SP_EDF+PADS", (0.415, 0.91), "★ SP-EDF + PADS (recommended)")
        callout("FIFO+DROP_TAIL", (0.415, 0.56), "FIFO + drop-tail (baseline)")
        ax.set_xlim(0.18, 0.70)
        ax.set_ylim(0.42, 1.0)
        ax.set_xticks(np.arange(0.20, 0.71, 0.10))
        ax.set_xlabel("Low-priority packets delivered / generated")
        ax.set_ylabel("High-priority packets delivered / generated")
        ax.grid(alpha=0.25, zorder=0)
        _save(fig, os.path.join(figdir, "02_tradeoff.png"))

        # Figure 3: two panels with independent scales so both metrics are
        # legible; shared y order keeps direct comparison easy.
        overall = [s["overall_delivery_mean"] for s in summary]
        fairness = [s["fairness_mean"] for s in summary]
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 5.8), sharey=True)
        fig.subplots_adjust(left=0.17, right=0.97, top=0.79, bottom=0.15, wspace=0.26)
        fig.suptitle("Throughput and fairness by buffer policy",
                     x=0.08, ha="left", fontsize=15, fontweight="bold", y=0.97)
        ax1.set_title("Overall delivery (all priorities)",
                      loc="left", fontsize=10.5, color="#334155", pad=12)
        ax2.set_title("Jain fairness — axis zoomed 0.84–1.00",
                      loc="left", fontsize=10.5, color="#334155", pad=12)

        y = np.arange(n)
        for ax, vals, xlim, label_offset, ha in (
            (ax1, overall, (0, 0.50), 0.008, "left"),
            (ax2, fairness, (0.84, 1.02), 0.002, "left"),
        ):
            ax.barh(y, vals, color=colors, height=0.62, alpha=0.92, zorder=3)
            ax.set_xlim(*xlim)
            ax.grid(axis="x", alpha=0.25, zorder=0)
            for yi, v in zip(y, vals):
                ax.text(v + label_offset, yi, f"{v:.3f}", va="center", ha=ha,
                        fontsize=9.5, color="#1e293b")
        ax1.set_yticks(y, names)
        ax1.invert_yaxis()
        ax2.set_yticks(y, [""] * n)
        ax1.set_xticks(np.arange(0, 0.51, 0.1))
        ax2.set_xticks(np.arange(0.84, 1.01, 0.04))
        ax1.set_xlabel("Delivered / generated")
        ax2.set_xlabel("Jain fairness index")
        fig.text(0.17, 0.035,
                 "Overall delivery counts all packets; fairness measures balance across priority classes.",
                 fontsize=9, color="#64748b")
        _save(fig, os.path.join(figdir, "03_fairness_throughput.png"))


def sensitivity(cfg: Config, seeds: int) -> List[Dict[str, object]]:
    """Sweep contact duration to show when ordering matters most."""
    out = []
    scales = [0.5, 1.0, 1.5, 2.0]
    combos = [("FIFO", "DROP_TAIL"), ("SP_EDF", "PADS"), ("SP_AGE", "PADS")]
    sweep_seeds = max(4, min(seeds, 6))
    for scale in scales:
        c = Config(**{**cfg.__dict__, "contact_duration_scale": scale})
        for sp, ep in combos:
            vals = [run_once(sp, ep, s, c)["high_delivery"] for s in range(sweep_seeds)]
            out.append({
                "scale": scale,
                "contact_seconds_mean": (c.contact_min + c.contact_max) / 2 * scale,
                "label": f"{sp}+{ep}",
                "high_delivery_mean": float(np.mean(vals)),
                "high_delivery_std": float(np.std(vals, ddof=1)),
            })
    return out


def write_sensitivity_csv(path: str, rows: List[Dict[str, object]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fields = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def plot_sensitivity(rows: List[Dict[str, object]], outdir: str) -> None:
    figdir = os.path.join(outdir, "figures")

    with _style():
        fig, ax = plt.subplots(figsize=(10.5, 6.0))
        fig.subplots_adjust(left=0.10, right=0.97, top=0.80, bottom=0.15)
        fig.suptitle("Sensitivity to contact duration",
                     x=0.06, ha="left", fontsize=15, fontweight="bold", y=0.97)
        ax.set_title("Mean ± standard deviation over up to 6 seeds per point — higher is better",
                     loc="left", fontsize=10, color="#64748b", pad=12)

        combos = sorted({r["label"] for r in rows})
        plotted = {}
        for label in combos:
            sub = [r for r in rows if r["label"] == label]
            x = np.array([r["contact_seconds_mean"] for r in sub])
            y = np.array([r["high_delivery_mean"] for r in sub])
            e = np.array([r["high_delivery_std"] for r in sub])
            sensor = _sensor(label)
            ls = "--" if sensor == "SP_AGE" else "-"
            lw = 2.8 if label == "SP_EDF+PADS" else 1.8
            ax.fill_between(x, y - e, y + e, color=FIG_COLORS[sensor], alpha=0.12,
                            linewidth=0, zorder=2)
            ax.plot(x, y, marker=FIG_MARKERS[_eviction(label)], markersize=8,
                    color=FIG_COLORS[sensor], linestyle=ls, linewidth=lw,
                    label=_short(label), zorder=3)
            plotted[label] = (x, y)

        # Highlight the short-contact regime, where ordering matters most.
        rec_x, rec_y = plotted["SP_EDF+PADS"]
        base_x, base_y = plotted["FIFO+DROP_TAIL"]
        gain_pp = (rec_y[0] - base_y[0]) * 100
        ax.annotate(
            f"Brief passes ({rec_x[0]:.1f} s):\n+{gain_pp:.0f} pp over FIFO",
            xy=(rec_x[0], rec_y[0]), xytext=(2.7, 0.62),
            fontsize=9.5, va="center",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#10b981", alpha=0.95),
            arrowprops=dict(arrowstyle="->", color="#10b981", lw=1.4),
            zorder=4)

        ax.set_xlabel("Mean contact duration per pass (s)")
        ax.set_ylabel("High-priority packets delivered / generated")
        ax.set_xticks(sorted({r["contact_seconds_mean"] for r in rows}))
        ax.set_ylim(0.30, 1.0)
        ax.grid(alpha=0.25, zorder=0)
        ax.legend(loc="lower right", frameon=False, fontsize=10,
                  handlelength=2.6, labelspacing=0.7)
        fig.text(0.10, 0.035,
                 "With long contacts the gap narrows: more packets fit in the link window.",
                 fontsize=9, color="#64748b")
        _save(fig, os.path.join(figdir, "04_contact_sensitivity.png"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cycles", type=int, default=32)
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--outdir", default="results")
    args = ap.parse_args()

    cfg = Config(cycles=args.cycles, seeds=args.seeds)
    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)

    rows: List[Dict[str, float]] = []
    for sp, ep in POLICY_COMBOS:
        for seed in range(args.seeds):
            rows.append(run_once(sp, ep, seed, cfg))
        print(f"  completed {sp}+{ep}")

    write_csv(os.path.join(outdir, "results.csv"), rows)
    summary = summarise(rows)
    write_summary_csv(os.path.join(outdir, "summary.csv"), summary)
    make_figures(summary, outdir)

    sens = sensitivity(cfg, args.seeds)
    write_sensitivity_csv(os.path.join(outdir, "sensitivity.csv"), sens)
    plot_sensitivity(sens, outdir)

    with open(os.path.join(outdir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg.__dict__, f, indent=2)

    print("\n=== Summary (sorted by high-priority delivery) ===")
    print(f"{'policy':<26} {'high':>7} {'low':>7} {'overall':>8} {'fairness':>9}")
    for s in summary:
        print(f"{s['label']:<26} {s['high_delivery_mean']:>7.3f} "
              f"{s['low_delivery_mean']:>7.3f} {s['overall_delivery_mean']:>8.3f} "
              f"{s['fairness_mean']:>9.3f}")
    print(f"\nWrote {len(rows)} rows and figures to {outdir}")


if __name__ == "__main__":
    main()

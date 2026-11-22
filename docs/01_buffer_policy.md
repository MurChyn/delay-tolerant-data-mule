# Buffer Management Policy — Analysis and Recommendation

## The answer

> **Use strict priority with earliest-deadline-first inside the high class on
> the sensor, combined with priority-aware eviction plus a high-priority guard
> band and deadline-aware admission on the mule.**

We call the combined policy **SP-EDF + PADS**. In the seeded experiment it
delivered **88.6 %** of high-priority packets, versus **48.7 %** for the
baseline FIFO + drop-tail configuration — an **82 % relative improvement** —
while still delivering 24.6 % of low-priority bulk data.

The most important finding is that **the sensor-side queue is the dominant
lever**. Increasing contact time does not rescue a FIFO queue; on the mule,
once the high class fits in flash, eviction policy differences are small but
consistently positive.

---

## 1. Why two buffers?

A mobile mule pass has two independent bottlenecks:

| Buffer | Bottleneck | Wrong decision | Right decision |
|--------|-----------|----------------|----------------|
| Sensor RAM (128 packets) | Airtime: 32 packets/s × 2–5 s = 64–160 packets | A critical alert waits behind hundreds of routine readings and never gets transmitted | Give the high class the airtime, then order by deadline |
| Mule flash (256 slots in experiment, 4096 in firmware) | Storage: the store fills before the next base-station unload | A fresh alert is rejected because the flash is full of old bulk data | Evict expired / low-value records first, reserve slots for alerts |

Optimising only one buffer leaves half the problem unsolved. A sensor that
transmits alerts first is useless if the mule then drops them; a mule that
protects alerts is useless if the sensor never sends them.

## 2. Policies compared

### Sensor side (transmission order)

| Policy | Key |
|--------|-----|
| FIFO | arrival order |
| SP | `(-priority, seq)` — high first |
| **SP-EDF** | `(-priority, expiresAt, seq)` — high first, tightest deadline first |
| SP-AGE | `-(priority + min(age/120, 1.4))` — old low packets may overtake alerts |

### Mule side (flash admission / eviction)

| Policy | Rule |
|--------|------|
| DROP-TAIL | reject new arrival when full |
| DROP-OLDEST | evict oldest record globally |
| DROP_LOWEST | evict low priority first, then oldest |
| **PADS** | (a) purge expired; (b) reject records that cannot survive to the next unload; (c) reserve a guard band of high-priority slots; (d) evict lowest value score |

The PADS value score is

```
score(p, now) = priority(p) + (1 - priority(p)) · min(age / 120, 0.8)
```

Lower score means evict first. Capping the low-class aging term at **0.8**
guarantees a high-priority record always outranks a low-priority one, so an
alert cannot be evicted while bulk data remains.

## 3. Experimental method

* Discrete-event simulation, `simulator/dtn_sim.py`, fully seeded.
* 6 sensors, exponential arrivals, total 2.1 packets/s, 25 % high priority.
* Route cycle 300 s; one pass per sensor per cycle, late in the cycle
  (180–270 s) so a real backlog exists when the mule arrives.
* Pass duration uniform 2–5 s; effective goodput 32 kbit/s (64–160 packets).
* Sensor queue 128 packets; mule flash 256 records; unload once per cycle.
* High-priority deadlines uniformly 200–640 s; low-priority TTL 3600 s.
* 32 cycles × 12 seeds × 7 policy combinations = **84 simulation runs**.

Primary metric: delivered high-priority packets / generated high-priority
packets. Secondary: low-priority delivery, total delivery, mean age at
delivery, Jain fairness across sensors.

## 4. Results

Mean over 12 seeds (± standard deviation where useful):

| Policy | High delivery | Low delivery | Overall | Mean high age (s) | Jain fairness |
|--------|--------------:|-------------:|--------:|------------------:|--------------:|
| **SP-EDF + PADS** | **0.886 ± 0.004** | 0.246 ± 0.004 | **0.405** | 206 ± 2 | **0.998** |
| SP-EDF + DROP_LOWEST | 0.885 ± 0.004 | 0.234 ± 0.004 | 0.397 | 207 ± 3 | 0.998 |
| SP + PADS | 0.883 ± 0.004 | 0.247 ± 0.004 | **0.405** | 205 ± 2 | 0.998 |
| SP + DROP_LOWEST | 0.880 ± 0.005 | 0.236 ± 0.003 | 0.396 | 206 ± 2 | 0.998 |
| SP-AGE + PADS | 0.844 ± 0.005 | **0.259** ± 0.004 | **0.405** | 225 ± 2 | 0.995 |
| FIFO + PADS | 0.688 ± 0.008 | 0.311 ± 0.004 | **0.405** | 273 ± 4 | 0.939 |
| FIFO + DROP_TAIL | 0.487 ± 0.014 | 0.362 ± 0.005 | 0.393 | 319 ± 3 | 0.858 |

Figures: `simulator/results/figures/01_high_delivery.png`,
`02_tradeoff.png`, `03_fairness_throughput.png`,
`04_contact_sensitivity.png`.

### Interpretation

1. **Priority scheduling is worth +0.40 high delivery.** Moving from FIFO +
   drop-tail to SP-EDF + PADS raises high-priority delivery from 0.487 to
   0.886. The gain comes from spending scarce airtime on alerts.
2. **EDF is a small but consistent improvement over SP** (0.886 vs 0.883)
   because some alerts carry tighter deadlines; sending the tightest one first
   avoids expiry inside the sensor queue. Mean age at delivery also falls.
3. **PADS mostly helps low-priority throughput and total delivery** rather
   than high delivery, once SP is in place: 0.246 vs 0.234 low delivery and
   0.405 vs 0.397 overall relative to DROP_LOWEST. Its guard band and
   deadline check stop bulk data from consuming slots that a later alert needs.
   The honest conclusion is that mule-side policy has *diminishing returns*
   when the high class already fits in flash — but it never hurts.
4. **Aging has a measurable fairness cost.** SP-AGE + PADS recovers the highest
   low-priority delivery (0.259) and lowers Jain fairness only slightly
   (0.995), but loses 0.042 high delivery. Use it only if bulk completeness
   matters as much as alerts.
5. **Total delivery is nearly constant at 0.405** for every policy that drains
   flash efficiently. The policies redistribute *which* packets survive; they
   do not create bandwidth. This is an important design insight: optimise for
   value, not raw byte count.

## 5. Sensitivity to pass duration

| Mean contact | FIFO + DROP_TAIL | SP-EDF + PADS | SP-AGE + PADS |
|-------------:|-----------------:|--------------:|--------------:|
| 1.75 s | 0.381 | 0.773 | 0.723 |
| 3.50 s | 0.485 | 0.887 | 0.845 |
| 5.25 s | 0.387 | 0.887 | 0.877 |
| 7.00 s | 0.373 | 0.887 | 0.886 |

The priority policy saturates by 3.5 s: once the backlog fits in the pass, more
airtime adds nothing. FIFO actually *degrades* with longer passes, because the
extra low-priority data fills the mule flash with bulk records and subsequent
alerts are rejected by drop-tail. This is direct evidence that **a longer pass
is not a substitute for a good buffer policy**.

## 6. Mapping to the firmware

| Simulator concept | Firmware location |
|-------------------|-------------------|
| SP-EDF sensor order | `firmware/sensor/SensorQueue.cpp` (`selectNext`, `Policy::SP`) plus the deadline tie-break |
| PADS eviction score | `firmware/mule/BufferManager.cpp` (`valueScore`) |
| High-priority guard band | `HP_GUARD_SLOTS` in `firmware/common/config.h` |
| Deadline-aware admission | `BufferManager::admit` and `expired` purge |
| Store-before-ACK | `firmware/mule/mule.ino` (`onData`) |

## 7. Recommendation

Deploy **SP-EDF + PADS** as the default. Keep `SP-AGE + PADS` available as a
configuration option for deployments where routine data completeness is
equally valued. Do not rely on longer vehicle passes to fix a FIFO design.

## 8. Limitations

* The simulator uses a scaled flash (256 slots) to make eviction observable;
  the firmware uses 4096 slots, so a real deployment will evict less often.
* Wi-Fi is modelled as a constant-goodput pipe; no 802.11 contention, capture
  effect, or association delay is modelled. Handshake overhead is treated as
  a constant ~2.4 % of a pass.
* Mobility is a fixed route with deterministic pass offsets, not a stochastic
  contact process.
* No hardware validation was possible in this project (see `06_analysis.md`).

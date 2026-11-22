# Analysis of Outcomes

## Summary

The project set out to answer which buffer management policy maximises
high-priority sensor packet delivery during brief Wi-Fi passes. A complete
reference system was designed: a five-phase dynamic handshake, a priority
queue on each sensor, a fixed-slot flash store on the mule, and a seeded
discrete-event simulator that evaluates seven policy combinations. The
simulation provides a clear answer; physical hardware validation was not
possible and is recorded as an unmet goal.

## Goals achieved

| Goal | Outcome | Evidence |
|------|---------|----------|
| G1 — dynamic handshake inside a brief pass | **Achieved (design + simulation)** | DHP-1 completes HELLO → SUMMARY → REQ → DATA → ACK/DONE in ~2.4 % of a 4 s contact by design; RSSI-based degradation switches to HIGH-only requests (`docs/03_protocol.md`, `firmware/mule/Handshake.cpp`). |
| G2 — priority-aware buffering on sensor and mule | **Achieved** | Four sensor disciplines and four mule eviction policies implemented in `firmware/sensor/SensorQueue.cpp` and `firmware/mule/BufferManager.cpp`, mirroring the simulator. |
| G3 — quantify the best policy | **Achieved** | 84 seeded runs (7 combinations × 12 seeds). SP-EDF + PADS reaches **0.886 ± 0.004** high-priority delivery vs **0.487 ± 0.014** for FIFO + drop-tail (`simulator/results/summary.csv`). |
| G4 — safe flash persistence | **Partially achieved** | Fixed 128-byte slots, CRC-32 per record, store-before-ACK, and startup index rebuild with repair of torn records are implemented in `FlashStore.cpp`. Power-loss testing awaits hardware. |
| G5 — reproducible documentation | **Achieved** | README, wiring schematic, protocol spec, CAD enclosure, simulator with requirements file, and 12-seed result artefacts are all included. |
| G6 — project walkthrough recording | **Achieved** | A recorded explanation of the problem, design, policies, results and deliverables is linked from `README.md` and `SUBMISSION.md`. |

## Key findings

1. **The sensor queue is the dominant lever.** Moving from FIFO to SP/SP-EDF
   accounts for almost all of the improvement (0.487 → 0.886). Airtime, not
   flash, is the scarce resource during a 2–5 s pass.
2. **EDF adds value only when deadlines vary.** With a constant high-priority
   TTL, EDF is identical to FIFO inside the class. Once alerts were given
   200–640 s deadlines, SP-EDF improved on SP by about 0.003 and reduced mean
   age at delivery.
3. **Mule-side policy has diminishing returns.** PADS improves low-priority
   delivery (0.246 vs 0.234) and total delivery (0.405 vs 0.397) relative to
   DROP_LOWEST, but its high-priority gain is only ~0.001. The honest
   interpretation is that once alerts fit in flash, eviction policy matters
   much less than transmission order.
4. **Aging is a fairness dial, not a free lunch.** SP-AGE + PADS gives the best
   low-priority delivery (0.259) but loses 0.042 high delivery. It is a
   configuration option, not the default.
5. **Longer passes do not fix FIFO.** In the sensitivity sweep, FIFO + drop-tail
   high delivery *fell* from 0.485 at 3.5 s to 0.373 at 7 s, because extra bulk
   traffic fills the flash and later alerts are rejected. SP-EDF + PADS
   saturates at ~0.887 from 3.5 s onward (`sensitivity.csv`).

## Goals not achieved

| Goal | Why not | Impact |
|------|---------|--------|
| Physical ESP32 validation | No hardware, sensors, or vehicle were available in the development environment | Timing, radio association behaviour, and flash wear remain unmeasured. All performance numbers are simulation results, explicitly labelled as such. |
| Power-loss integrity test | Requires a real device that can be reset mid-write | CRC and repair logic is present but untested. |
| Base-station unload field test | Requires a second network and a mobile platform | The unload path is implemented as a compile-time mode but not exercised. |

## What I would change with more time or resources

1. **Hardware-in-the-loop validation.** Flash two ESP32s, log RSSI and pass
   duration from a moving car, and compare measured delivery against the
   simulator. Add a `hardware/` test harness that replays a recorded trace.
2. **Model the radio properly.** Replace the constant-goodput pipe with an
   802.11 model including association delay, contention, and capture effects.
   Association alone could be a large fixed tax on a 2 s pass.
3. **Adaptive aging.** Make `PRIO_AGING_TAU` a function of observed contact
   rate rather than a constant, so the policy self-tunes when vehicle frequency
   changes.
4. **Replication-aware forwarding.** Allow a mule to hand a bundle to a second
   mule at a crossing, which changes the optimal eviction rule (records with
   more remaining replicas should be evicted first).
5. **Real deadlines from the application.** Have each sensor declare its own
   deadline in the packet header rather than deriving it from a priority class;
   the current firmware already reserves a TTL field for this.

## Reflection

The most valuable outcome was discovering that the intuitive "bigger buffer"
answer is wrong. Total delivery is essentially constant across all efficient
policies (0.405); what changes is *which* packets survive. A robotics
engineering solution therefore has to be value-driven: schedule by priority and
deadline at the sensor, protect alerts at the mule, and accept bulk loss as an
explicit engineering trade-off. The absence of hardware is a real limitation,
but the simulator, firmware, and protocol are tightly aligned so that a future
field test is a validation step rather than a redesign.

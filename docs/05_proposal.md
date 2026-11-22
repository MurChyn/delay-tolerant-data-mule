# Original Proposal

## Delay-Tolerant Data Mule Node: Collecting Remote Field Data with Mobile Wi-Fi Nodes

**Submitted:** 2026
**Student:** Murtazaev Chyngys
**Group:** EEAIR-25

---

### 1. Problem statement

Remote environmental sensor deployments are often placed beyond the reach of
continuous network infrastructure. Installing permanent cellular or long-range
radio gateways is expensive, power-hungry, and sometimes physically impossible.
Yet the data those sensors collect — flood levels, soil moisture, air quality,
wildlife activity — is only useful if it eventually reaches a base station.

A **delay-tolerant data mule** solves this by carrying a store-and-forward gateway
on a moving platform (a car, bicycle, boat, or robot). The mule drives or moves
past each sensor, collects buffered readings during a short Wi-Fi contact, stores
them in non-volatile flash, and later unloads them when it returns to the base
station. No end-to-end path ever needs to exist at the same time.

### 2. Research question

> **What buffer management policy maximizes high-priority sensor packet delivery
> during brief passes?**

Two buffers matter:

1. **Sensor-side queue** — which buffered reading gets the airtime when the mule
   is only in range for a few seconds?
2. **Mule-side flash store** — which stored record is evicted when the flash is
   full and a new high-priority reading arrives?

The project compares FIFO, strict priority, and a proposed priority-with-aging
policy across both buffers, using a reproducible discrete-event simulation backed
by a working ESP32 firmware reference implementation.

### 3. Goals

| # | Goal | Success criterion |
|---|------|-------------------|
| G1 | Design a dynamic handshake that completes inside a 2–10 s contact | Handshake completes in < 500 ms at 1 Mbps |
| G2 | Implement priority-aware buffering on sensor and mule | Firmware compiles and passes unit-style tests |
| G3 | Quantify which policy maximizes high-priority delivery | Simulation produces statistically meaningful comparison |
| G4 | Persist data safely in flash across power loss | Records survive a simulated reboot (file integrity test) |
| G5 | Document a reproducible build | README + schematics allow a third party to rebuild |

### 4. Proposed approach

- **Hardware:** ESP32 DevKit V1 (mule) + ESP32 sensor nodes, SPI flash /
  LittleFS for storage, optional GPS and status LEDs.
- **Transport:** ESP32 soft-AP on the mule; sensors associate as stations;
  UDP datagrams carrying a compact binary packet format with CRC-16.
- **Protocol:** five-phase dynamic handshake —
  `DISCOVER → HELLO → SUMMARY → TRANSFER → ACK/DONE`.
  The mule adapts the request list to measured RSSI and estimated time-in-contact.
- **Buffer policy:** strict priority for high-class packets with an aging term
  so low-class packets cannot starve, plus expiry-aware eviction on the mule.
- **Evaluation:** discrete-event simulation over 20 route cycles × 10 seeds,
  measuring high-priority delivery ratio, overall delivery ratio, age at
  delivery, and Jain fairness index.

### 5. Timeline

| Week | Activity |
|------|----------|
| 1 | Literature review, finalise packet format and handshake |
| 2 | Implement sensor firmware and queue policies |
| 3 | Implement mule firmware, flash store, and eviction policies |
| 4 | Build simulator, run first comparison |
| 5 | Tune aging constant, rerun experiments, analyse results |
| 6 | Documentation, schematic, project walkthrough video, final report |

### 6. Expected outcomes

We expect strict priority alone to improve high-priority delivery but to starve
low-priority traffic. We expect the proposed aging policy to retain most of the
high-priority gain while recovering overall throughput and fairness. The final
deliverable will state the measured trade-off rather than assuming it.

### 7. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| No physical hardware available | Full host-side simulator + compile-checked firmware; clearly labelled as simulated validation |
| Wi-Fi association too slow for brief passes | Persistent AP, pre-associated sensors, UDP with no TCP handshake |
| Flash wear from rewriting on eviction | Fixed slots + wear levelling via LittleFS; bounded writes |
| Contact shorter than expected | Adaptive request list truncated to highest-value packets first |

---

*This document records the original proposal. See `docs/06_analysis.md` for the
outcome analysis.*

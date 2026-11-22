# Interactive Demonstration

`interactive_simulator.html` is a **single self-contained HTML file** — no build
step, dependencies, or network access required. Open it in any modern browser
(double-click the file) to:

* watch the mule drive past three field sensor nodes and offload to the sink;
* switch between `FIFO`, `Priority-Preemptive`, and `EDF + Prio` buffer policies;
* inject critical (P0) alerts by clicking a node, or flood the queues with
  low-priority packets;
* trigger a mule pass manually, change pass speed and flash capacity, and
  pause/reset the run;
* watch the five-step dynamic handshake, flash-slot map, eviction log, and
  live KPIs (P0 delivery rate, bytes offloaded, drops, flash wear, RSSI);
* inspect the embedded ESP32 C++ reference sketch.

> This is a **didactic, interactive model**, not the validated experiment. It
> uses three priority classes and three policies; the measured results in
> `docs/01_buffer_policy.md` come from the seeded discrete-event simulator in
> `simulator/dtn_sim.py` (SP-EDF + PADS, 84 runs). The two are consistent in
> their core ideas — priority ordering, deadline awareness, and eviction under
> limited flash — but the HTML demo is simplified for live interaction.

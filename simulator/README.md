# Simulator

`dtn_sim.py` is the evidence engine for the project. It compares sensor-side
transmission disciplines against mule-side flash eviction policies under short
Wi-Fi contacts, and reports high-priority delivery as the primary metric.

## Install

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
python dtn_sim.py --cycles 32 --seeds 12 --outdir results
```

Runtime is a few seconds. Outputs:

| File | Contents |
|------|----------|
| `results/results.csv` | One row per policy × seed (84 rows in the default run) |
| `results/summary.csv` | Means / standard deviations, sorted by high delivery |
| `results/sensitivity.csv` | Pass-duration sweep |
| `results/figures/01_high_delivery.png` | Primary result with error bars |
| `results/figures/02_tradeoff.png` | High vs low delivery scatter |
| `results/figures/03_fairness_throughput.png` | Fairness and total throughput |
| `results/figures/04_contact_sensitivity.png` | Effect of contact length |
| `results/config.json` | Exact parameters used |

## Policies

**Sensor-side (which reading gets airtime):**

| Policy | Rule |
|--------|------|
| `FIFO` | Arrival order |
| `SP` | Strict priority, arrival order within class |
| `SP_EDF` | High first; earliest deadline first within each class **(recommended)** |
| `SP_AGE` | Uncapped priority + age score (fairness-oriented ablation) |

**Mule-side (which flash record is evicted):**

| Policy | Rule |
|--------|------|
| `DROP_TAIL` | Reject new arrival when flash is full |
| `DROP_OLDEST` | Evict the oldest record globally |
| `DROP_LOWEST` | Evict low-priority first, then oldest |
| `PADS` | Purge expired, reserve a high-priority guard band, evict lowest value score with expiry tie-break **(recommended)** |

## Model details

* Six sensors generate packets with exponential interarrival times (total
  2.1 packets/s); priority is Bernoulli with `p = 0.25`.
* One pass per sensor per 300 s cycle, late in the cycle (180–270 s) so a
  backlog exists. Contact duration is uniform in 2–5 s.
* Effective goodput is 32 kbit/s → 16 packets/s, so a pass carries 32–80 packets.
* The local sensor queue holds 128 packets; the mule flash holds 256 records
  (scaled down from the firmware's 4096 so eviction is observable).
* The mule unloads to the base station once per cycle.
* High packets have deadlines uniformly distributed in 200–640 s; low packets
  expire after 3600 s.

See `docs/01_buffer_policy.md` for the interpretation of the results.

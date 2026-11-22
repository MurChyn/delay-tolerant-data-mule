# Blender 3D Simulation

An animated 3D companion to the interactive browser demonstration. The scene
shows the vehicle driving past four field sensors, the short Wi-Fi contact
windows, packet transfer along the link, the sensor backlog draining, and the
mule's flash slots filling with high- and low-priority records.

## Files

| File | Description |
|------|-------------|
| `blender_mule.py` | Scene generator and render driver (Blender Python API) |
| `output/mule_3d.mp4` | Rendered 30 s animation (1280×720, 24 fps) |
| `output/mule_3d.blend` | Editable, fully keyframed Blender scene (scrubs without Python) |
| `output/mule_3d_still.png` | Poster frame extracted from the render |

## Requirements

* Blender 4.x / 5.x (tested target: 5.3)
* ffmpeg on PATH, or Python package `imageio-ffmpeg` (used for MP4 encoding)

## Generate from scratch

```bash
blender -b -P simulation/blender_mule.py -- \
  --out simulation/output/mule_3d.mp4 \
  --blend simulation/output/mule_3d.blend
```

A quick smoke test that renders only 60 frames:

```bash
blender -b -P simulation/blender_mule.py -- --preview \
  --out simulation/output/mule_3d_preview.mp4 \
  --blend simulation/output/mule_3d_preview.blend
```

To regenerate only the `.blend` (skip the ~12 min render):

```bash
blender -b -P simulation/blender_mule.py -- --blend-only \
  --blend simulation/output/mule_3d.blend
```

Optional flags: `--frames 720`, `--fps 24`, `--preview`, `--blend-only`.

## Scene contents

* **Road and vehicle** — a stylised car with a mule antenna and status LED.
* **Four sensor nodes** — each with a backlog bar that grows between passes
  and collapses while the mule is in range.
* **Wi-Fi contact** — a green beam and six travelling packet cubes appear only
  within a 3.2-unit pass radius of a sensor.
* **Flash grid on the roof** — 32 slots: blue = low-priority record,
  red = high-priority record, dark = free. Red slots occur once per group of
  eight, visualising the reserved high-priority capacity from `PADS`.
* **Camera captions** — a running high-priority delivery ratio rises from the
  FIFO baseline (48.7 %) to the measured SP-EDF + PADS result (88.6 %), taken
  from `simulator/results/summary.csv`.

## Editing

Open `output/mule_3d.blend` and scrub the timeline — the car, camera, beams,
packets, backlog bars, flash colours, and captions are all driven by ordinary
Blender keyframes, so no Python handler or "auto-run scripts" preference is
needed. To change the story, edit constants such as `SENSOR_X`, `PASS_RADIUS`,
`FLASH_COLORS`, or the `apply_state()` function in `blender_mule.py`, then
regenerate with `--blend-only`.

> Blender cannot keyframe a text object's `body` or an object's material index.
> The captions are therefore pre-built as 12 ratio variants plus 5 contact
> variants, selected by keyframed `hide_render`; each flash slot owns a
> material whose node colour is keyframed instead of swapping materials.

> This is a schematic animation, not a photograph or a hardware capture. The
> project had no physical ESP32 hardware available; see `docs/06_analysis.md`.

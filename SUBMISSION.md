# Submission Contents

**Student:** Murtazaev Chyngys
**Group:** EEAIR-25

## Artefacts

| Artefact | Location |
|----------|----------|
| Project walkthrough video | [Google Drive](https://drive.google.com/file/d/1kPUErmg06S_vVMQRKt5njrpGF7Z_qzOo/view) |
| Interactive browser demo | `demo/interactive_simulator.html` |
| Blender 3D animation and editable scene | `simulation/output/mule_3d.mp4`, `simulation/output/mule_3d.blend` |
| Original proposal and final analysis | `proposal_analysis.pdf` |
| Project documentation | `README.md`, `docs/` |
| ESP32 firmware | `firmware/` |
| Simulator, results and figures | `simulator/` |

## Checks already performed

- All Markdown links resolve locally (0 broken links).
- `simulation/output/mule_3d.mp4`: 30 s, 720 frames, 1280×720, 24 fps.
- `simulation/output/mule_3d.blend`: fully keyframed; timeline scrubs without Python handlers.
- `demo/interactive_simulator.html`: self-contained, no external dependencies; controls verified in a browser.
- `python dtn_sim.py --cycles 32 --seeds 12 --outdir results` reproduces the 84-run comparison and all four figures.

## Reproducing the results

```bash
cd simulator
python -m pip install -r requirements.txt
python dtn_sim.py --cycles 32 --seeds 12 --outdir results
```

# Visual assets

This folder contains the diagrams used in the README and documentation.

| File | Description | Origin |
|------|-------------|--------|
| `system_overview.png` | Architecture infographic (vehicle, sensors, pipeline) | Generated with `make_overview.py` |
| `hardware_setup.png` | Stylised top-down board layout | Generated with `make_overview.py` |
| `wiring_diagram.png` / `.svg` | Pin-level wiring schematic | Generated with `make_wiring.py` |
| `make_overview.py`, `make_wiring.py` | Generators (matplotlib) | Source code |

**These are rendered schematic illustrations, not photographs.** The project
was developed without physical hardware, so no photographs of a built system
exist. They are labelled as renders everywhere they appear. For a future
hardware build, these can be replaced with real photographs; the wiring diagram
remains valid.

Regenerate with:

```bash
python docs/images/make_overview.py
python docs/images/make_wiring.py
```

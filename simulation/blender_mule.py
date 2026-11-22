#!/usr/bin/env python3
"""
Scripted Blender 3D simulation of the delay-tolerant data mule.

Run headless:
  blender -b -P simulation/blender_mule.py -- \
      --out simulation/output/mule_3d.mp4 \
      --blend simulation/output/mule_3d.blend

What it shows
-------------
* A vehicle drives along a road past four field sensor nodes.
* Wi-Fi beams and animated packet cubes appear during each 2-5 s pass.
* A backlog bar above each sensor grows between passes and drains during one.
* A 32-cell grid on the car roof represents mule flash slots: blue = low
  priority, red = high priority, dark = free. Red cells recur once per group
  of eight, visualising the reserved high-priority capacity.
* A camera-locked caption reports the running high-priority delivery ratio,
  which rises from the FIFO baseline (~0.49) to the measured SP-EDF + PADS
  result (~0.89), matching simulator/results/summary.csv.

All motion is baked into ordinary keyframes before the .blend is saved, so the
scene animates correctly when scrubbed in the Blender timeline with no Python
handler or auto-run-scripts setting required.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import bpy
from mathutils import Vector

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", default="simulation/output/mule_3d.mp4")
ap.add_argument("--blend", default="simulation/output/mule_3d.blend")
ap.add_argument("--frames", type=int, default=720)
ap.add_argument("--fps", type=int, default=24)
ap.add_argument("--preview", action="store_true",
                help="render only 60 frames for a smoke test")
ap.add_argument("--blend-only", action="store_true",
                help="bake and save the .blend without rendering the MP4")
args = ap.parse_args(argv)

if args.preview:
    args.frames = 60

END = args.frames
FPS = args.fps
SENSOR_X = (-12.0, -4.0, 4.0, 12.0)
SENSOR_Y = -7.5
CAR_START, CAR_END = -18.0, 18.0
PASS_RADIUS = 3.2

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_MP4 = os.path.abspath(os.path.join(ROOT, args.out))
OUT_BLEND = os.path.abspath(os.path.join(ROOT, args.blend))
os.makedirs(os.path.dirname(OUT_MP4), exist_ok=True)
os.makedirs(os.path.dirname(OUT_BLEND), exist_ok=True)

# ---------------------------------------------------------------------------
# Scene reset and rendering configuration
# ---------------------------------------------------------------------------
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = END
scene.render.fps = FPS
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
if scene.world is None:
    scene.world = bpy.data.worlds.new("world")
scene.world.color = (0.05, 0.07, 0.11)

for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
    try:
        scene.render.engine = engine
        break
    except TypeError:
        continue
# Headless Eevee with 64 TAA samples costs ~9 s/frame without GPU. Eight
# samples plus no shadows/raytracing keeps this stylised scene crisp enough
# while making the full render practical on CPU-only machines.
if hasattr(scene, "eevee"):
    scene.eevee.taa_render_samples = 8
    scene.eevee.use_shadows = False
    if hasattr(scene.eevee, "use_raytracing"):
        scene.eevee.use_raytracing = False
print(f"[3D] engine={scene.render.engine}, frames={END}")


def material(name, rgb, emission=0.0, rough=0.45):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*rgb, 1.0)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = rough
        if emission and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (*rgb, 1.0)
            bsdf.inputs["Emission Strength"].default_value = emission
    return m


MAT = {
    "road": material("road", (0.10, 0.12, 0.16)),
    "ground": material("ground", (0.09, 0.18, 0.12)),
    "line": material("line", (0.85, 0.85, 0.72), 0.25),
    "car": material("car", (0.95, 0.75, 0.10), 0.10, 0.3),
    "car_dark": material("car_dark", (0.06, 0.07, 0.09)),
    "glass": material("glass", (0.18, 0.35, 0.45), 0.10, 0.15),
    "sensor": material("sensor", (0.18, 0.24, 0.32)),
    "metal": material("metal", (0.55, 0.60, 0.65)),
    "high": material("high", (0.92, 0.18, 0.14), 1.6),
    "low": material("low", (0.12, 0.55, 0.95), 1.4),
    "empty": material("empty", (0.10, 0.13, 0.17)),
    "wifi": material("wifi", (0.15, 0.95, 0.55), 2.0),
    "backlog": material("backlog", (0.95, 0.45, 0.10), 0.8),
}


def cube(name, loc, scale, mat, parent=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = scale
    o.data.materials.append(mat)
    if parent:
        o.parent = parent
    return o


def cylinder(name, loc, radius, depth, mat, parent=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=radius,
                                        depth=depth, location=loc)
    o = bpy.context.object
    o.name = name
    o.data.materials.append(mat)
    if parent:
        o.parent = parent
    return o


def sphere(name, loc, radius, mat, parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8,
                                         radius=radius, location=loc)
    o = bpy.context.object
    o.name = name
    o.data.materials.append(mat)
    if parent:
        o.parent = parent
    return o


def text_obj(name, body, size, loc, mat, parent=None, align="CENTER"):
    curve = bpy.data.curves.new(name, type="FONT")
    curve.body = body
    curve.size = size
    curve.align_x = align
    o = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(o)
    o.location = loc
    o.data.materials.append(mat)
    if parent:
        o.parent = parent
    return o


# ---------------------------------------------------------------------------
# World geometry
# ---------------------------------------------------------------------------
cube("ground", (0, 0, -0.35), (80, 60, 0.4), MAT["ground"])
cube("road", (0, 0, -0.12), (80, 7.5, 0.15), MAT["road"])
for x in range(-38, 40, 4):
    cube(f"lane_{x}", (x, 0, -0.03), (2.0, 0.10, 0.02), MAT["line"])

# Sensor nodes
sensors = []
for i, sx in enumerate(SENSOR_X):
    cube(f"sensor_{i}_box", (sx, SENSOR_Y, 0.45), (1.2, 0.9, 0.9), MAT["sensor"])
    cylinder(f"sensor_{i}_pole", (sx, SENSOR_Y, 1.15), 0.05, 1.2, MAT["metal"])
    led = sphere(f"sensor_{i}_led", (sx, SENSOR_Y, 2.0), 0.14, MAT["high"])
    bar = cube(f"sensor_{i}_backlog", (sx, SENSOR_Y + 1.6, 0.5),
               (0.5, 0.5, 1.0), MAT["backlog"])
    label = text_obj(f"sensor_{i}_label", f"S{i+1}", 0.55,
                     (sx, SENSOR_Y - 1.1, 1.5), MAT["line"])
    label.rotation_euler = (0, 0, 0)
    sensors.append({"x": sx, "led": led, "bar": bar})

# Vehicle
car = bpy.data.objects.new("car_root", None)
bpy.context.collection.objects.link(car)
cube("car_body", (0, 0, 0.55), (4.0, 1.9, 0.9), MAT["car"], car)
cube("car_cabin", (-0.25, 0, 1.25), (2.1, 1.7, 0.75), MAT["glass"], car)
for wx in (-1.3, 1.3):
    for wy in (-1.0, 1.0):
        wheel = cylinder("wheel", (wx, wy, 0.12), 0.38, 0.22, MAT["car_dark"], car)
        wheel.rotation_euler = (1.5708, 0, 0)
cube("mule_antenna", (1.4, 0.6, 1.35), (0.08, 0.08, 0.9), MAT["metal"], car)

# Wi-Fi beams: one per sensor, endpoints updated each frame.
beams = []
for i in range(len(SENSOR_X)):
    b = cylinder(f"wifi_{i}", (0, 0, 0), 0.035, 1.0, MAT["wifi"])
    beams.append(b)

# Animated packet cubes travelling along each beam.
packets = []
for i in range(len(SENSOR_X)):
    group = []
    for k in range(6):
        p = cube(f"packet_{i}_{k}", (0, 0, 0), (0.18, 0.18, 0.18),
                 MAT["high"] if k % 3 == 0 else MAT["low"])
        group.append(p)
    packets.append(group)

# Flash grid on the car roof (8 x 4 = 32 slots; one HP pair per group of 8).
# Each slot gets its own material instance so its Base Color can be keyframed
# (Blender cannot keyframe an object's material index or a text object's body).
FLASH_COLORS = {
    "empty": (0.10, 0.13, 0.17),
    "high": (0.92, 0.18, 0.14),
    "low": (0.12, 0.55, 0.95),
}
flash = []
for r in range(4):
    for c in range(8):
        m = material(f"flash_mat_{r}_{c}", FLASH_COLORS["empty"], 1.2)
        s = cube(f"flash_{r}_{c}",
                 (1.3 - c * 0.32, -0.55 + r * 0.34, 1.72),
                 (0.24, 0.24, 0.08), m, car)
        flash.append({"obj": s,
                      "color": m.node_tree.nodes["Principled BSDF"]
                               .inputs["Base Color"]})

# HUD labels in world space.
text_obj("hud_title", "SP-EDF + PADS", 0.8, (-17, 9, 4.5), MAT["line"])
text_obj("hud_high", "HIGH  (red)   packet class", 0.45, (-17, 9, 3.7), MAT["high"])
text_obj("hud_low", "LOW  (blue)   bulk class", 0.45, (-17, 9, 3.1), MAT["low"])
text_obj("hud_flash", "MULE FLASH — 32 slots / 4 reserved", 0.40,
         (-17, 9, 2.5), MAT["line"])

# ---------------------------------------------------------------------------
# Camera and lighting
# ---------------------------------------------------------------------------
cam_data = bpy.data.cameras.new("camera")
cam = bpy.data.objects.new("camera", cam_data)
bpy.context.collection.objects.link(cam)
cam.location = (0, -30, 15)
cam_data.lens = 42
scene.camera = cam

target = bpy.data.objects.new("camera_target", None)
bpy.context.collection.objects.link(target)
track = cam.constraints.new(type="TRACK_TO")
track.target = target
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"

# Camera-locked captions. Text bodies cannot be keyframed, so pre-build one
# text object per state and keyframe hide_render to select the active one.
CAPTION_COUNT = 12
SUB_STATES = ["FIFO 48.7% -> SP-EDF+PADS 88.6%  |  IN TRANSIT"] + [
    f"FIFO 48.7% -> SP-EDF+PADS 88.6%  |  CONTACT S{i + 1}"
    for i in range(len(SENSOR_X))
]
captions = [
    text_obj(f"caption_{k:02d}",
             f"HIGH-PRIORITY DELIVERY  {ratio:.1%}", 0.26,
             (0, 1.55, -9.0), MAT["line"], cam)
    for k, ratio in enumerate(
        0.487 + (0.886 - 0.487) * min(1.0, (k / (CAPTION_COUNT - 1)) * 1.15)
        for k in range(CAPTION_COUNT))
]
subcaptions = [
    text_obj(f"subcaption_{k:02d}", body, 0.17,
             (0, 1.15, -9.0), MAT["line"], cam)
    for k, body in enumerate(SUB_STATES)
]

bpy.ops.object.light_add(type="SUN", location=(6, -8, 20))
sun = bpy.context.object
sun.data.energy = 2.2
sun.rotation_euler = (0.5, -0.4, -0.3)

bpy.ops.object.light_add(type="AREA", location=(-6, -12, 12))
area = bpy.context.object
area.data.energy = 1600
area.data.size = 14

# ---------------------------------------------------------------------------
# Deterministic per-frame state (applied directly and then baked to keyframes)
# ---------------------------------------------------------------------------
def aim_cylinder(obj, start: Vector, end: Vector) -> None:
    delta = end - start
    obj.location = (start + end) * 0.5
    obj.rotation_euler = delta.to_track_quat("Z", "Y").to_euler()
    obj.scale.z = max(delta.length, 0.01) * 0.5


def apply_state(frame: int) -> None:
    p = (frame - 1) / max(END - 1, 1)
    car_x = CAR_START + (CAR_END - CAR_START) * p
    car.location.x = car_x

    cam.location.x = -4.0 + 8.0 * p
    target.location = (car_x * 0.25, -2.0, 1.4)

    active = None
    for i, s in enumerate(sensors):
        dist = abs(car_x - s["x"])
        in_contact = dist < PASS_RADIUS
        s["led"].hide_render = not in_contact

        # Backlog grows between passes and drains during a pass.
        local = (frame - 1) % 180
        center = 40 + i * 32
        if local < center:
            backlog = 0.18 + 0.78 * (local / max(center, 1))
        else:
            backlog = 0.18 + 0.78 * max(0.0, 1.0 - (local - center) / 28.0)
        if in_contact:
            backlog *= 0.35
        s["bar"].scale.z = max(0.05, backlog * 2.2)
        s["bar"].location.z = 0.5 + s["bar"].scale.z * 0.5

        beam = beams[i]
        beam.hide_render = not in_contact
        start = Vector((s["x"], SENSOR_Y, 2.0))
        end = Vector((car_x + 1.3, 0.5, 1.8))
        if in_contact:
            active = i
            aim_cylinder(beam, start, end)
            for k, pkt in enumerate(packets[i]):
                u = ((frame * 0.035) + k / 6.0) % 1.0
                pkt.hide_render = False
                pkt.location = start.lerp(end, u)
                pkt.rotation_euler = (frame * 0.04 + k, frame * 0.03, 0)
        else:
            for pkt in packets[i]:
                pkt.hide_render = True

    # Flash grid fills over the run; every 8th cell is a high-priority record.
    # Colour is stored on a per-slot material so it can be keyframed.
    fill = min(1.0, 0.18 + 0.78 * p)
    filled = int(len(flash) * fill)
    for idx, slot in enumerate(flash):
        if idx >= filled:
            key = "empty"
        elif idx % 8 in (0, 1):
            key = "high"
        else:
            key = "low"
        slot["color"].default_value = (*FLASH_COLORS[key], 1.0)

    # Select the pre-built caption variant matching the current ratio/contact.
    ratio_step = min(CAPTION_COUNT - 1,
                     int(min(1.0, p * 1.15) * (CAPTION_COUNT - 1)))
    sub_step = 0 if active is None else active + 1
    for k, obj in enumerate(captions):
        obj.hide_render = k != ratio_step
    for k, obj in enumerate(subcaptions):
        obj.hide_render = k != sub_step


# ---------------------------------------------------------------------------
# Bake every animated property into ordinary keyframes. This makes the saved
# .blend fully scrubbable with no Python handler or auto-run preference.
# ---------------------------------------------------------------------------
def bake_keyframes() -> None:
    samples = list(range(1, END + 1, 3))
    if samples[-1] != END:
        samples.append(END)
    for f in samples:
        apply_state(f)
        car.keyframe_insert("location", frame=f)
        cam.keyframe_insert("location", frame=f)
        target.keyframe_insert("location", frame=f)
        for s in sensors:
            s["led"].keyframe_insert("hide_render", frame=f)
            s["bar"].keyframe_insert("scale", frame=f)
            s["bar"].keyframe_insert("location", frame=f)
        for beam in beams:
            beam.keyframe_insert("hide_render", frame=f)
            beam.keyframe_insert("location", frame=f)
            beam.keyframe_insert("rotation_euler", frame=f)
            beam.keyframe_insert("scale", frame=f)
        for group in packets:
            for pkt in group:
                pkt.keyframe_insert("hide_render", frame=f)
                pkt.keyframe_insert("location", frame=f)
                pkt.keyframe_insert("rotation_euler", frame=f)
        for slot in flash:
            slot["color"].keyframe_insert("default_value", frame=f)
        for obj in captions + subcaptions:
            obj.keyframe_insert("hide_render", frame=f)
    print(f"[3D] baked {len(samples)} keyframe samples")


bake_keyframes()
scene.frame_set(1)

# ---------------------------------------------------------------------------
# Save editable scene
# ---------------------------------------------------------------------------
bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)
print(f"[3D] saved {OUT_BLEND}")

if args.blend_only:
    print("[3D] --blend-only: skipping render")
    sys.exit(0)

# ---------------------------------------------------------------------------
# Render frames, then encode with ffmpeg
# ---------------------------------------------------------------------------
tmpdir = tempfile.mkdtemp(prefix="mule3d_", dir=tempfile.gettempdir())
scene.render.filepath = os.path.join(tmpdir, "frame_")
print(f"[3D] rendering {END} frames to {tmpdir}")
bpy.ops.render.render(animation=True)

def find_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    # winget installs ffmpeg outside PATH; search its package cache.
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft",
                        "WinGet", "Packages")
    if os.path.isdir(base):
        for root, _dirs, files in os.walk(base):
            if "ffmpeg.exe" in files:
                return os.path.join(root, "ffmpeg.exe")
    return None


ffmpeg = find_ffmpeg()
if not ffmpeg:
    raise RuntimeError("ffmpeg is required to encode the MP4")

cmd = [
    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
    "-framerate", str(FPS), "-i", os.path.join(tmpdir, "frame_%04d.png"),
    "-c:v", "libx264", "-preset", "medium", "-crf", "21",
    "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT_MP4,
]
subprocess.run(cmd, check=True)
shutil.rmtree(tmpdir, ignore_errors=True)
print(f"[3D] wrote {OUT_MP4}")

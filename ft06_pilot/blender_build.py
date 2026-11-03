"""Build/render a separate FT06 scene using Blender's own Python runtime.

blender --background --python blender_build.py -- --state active_run.json
    --output FT06_Pilot.blend --preview FT06_Pilot.png
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


# =========================================================
# SEPARATE FT06 SCENE MATERIALS AND CONCEPTUAL FACTORY GEOMETRY
# =========================================================
JOB_COLORS = [(0.13, 0.64, 1.0, 1), (1.0, 0.38, 0.18, 1),
              (0.35, 0.9, 0.51, 1), (0.79, 0.41, 1.0, 1),
              (1.0, 0.79, 0.18, 1), (0.18, 0.86, 0.83, 1)]


def material(name, color, metallic=0, roughness=0.5, emission=0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    node = mat.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = color
    node.inputs["Metallic"].default_value = metallic
    node.inputs["Roughness"].default_value = roughness
    node.inputs["Emission Color"].default_value = color
    node.inputs["Emission Strength"].default_value = emission
    return mat


def box(name, location, scale, mat, bevel=0.06):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    if bevel:
        modifier = obj.modifiers.new("Soft industrial edges", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
        obj.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
    return obj


def text(name, body, location, size, mat, rotation=None):
    curve = bpy.data.curves.new(name, type="FONT")
    curve.body = body
    curve.size = size
    curve.extrude = 0.001
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    if rotation:
        obj.rotation_euler = rotation
    obj.data.materials.append(mat)
    return obj


def area_light(name, location, power, size, color):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = power
    data.shape = "DISK"
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (Vector((0, 0, 0)) - obj.location).to_track_quat("-Z", "Y").to_euler()


def create_geometry(state, bridge):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "TwinOps FT06 Pilot"
    scene["ft06_mode"] = "ft06"
    scene["ft06_frames_per_unit"] = 6
    scene["ft06_layout"] = "Conceptual six-station layout; not measured factory geometry"
    scene["ft06_replay_note"] = "Baked product movement and one-unit clock; no auto-run needed. FT06_Bridge explicitly refreshes manually replaced JSON"
    scene["ft06_transport"] = "Zero transport time: constant interpolation jumps between exact sampled states"
    floor = material("Floor graphite", (0.035, 0.045, 0.063, 1), roughness=0.75)
    panel = material("Panel dark", (0.055, 0.083, 0.115, 1), roughness=0.65)
    housing = material("Machine satin", (0.23, 0.32, 0.40, 1), 0.35, 0.32)
    glass = material("Machine glass", (0.05, 0.12, 0.17, 1), 0.55, 0.2)
    accent = material("TwinOps cyan", (0.12, 0.72, 0.85, 1), emission=0.7)
    white = material("Typography white", (0.87, 0.93, 1.0, 1), emission=0.45)
    muted = material("Typography muted", (0.49, 0.64, 0.76, 1), emission=0.35)
    green = material("Output mint", (0.20, 0.80, 0.57, 1), emission=0.5)
    box("FT06_Floor", (0, 0, -0.12), (27, 21, 0.24), floor, 0.18)
    for x in range(-12, 13, 2):
        box(f"Grid x{x}", (x, 0, 0.012), (0.012, 20, 0.006), panel, 0)
    for y in range(-10, 11, 2):
        box(f"Grid y{y}", (0, y, 0.012), (26, 0.012, 0.006), panel, 0)
    box("Header panel", (0, 8.2, 0.04), (23, 2.8, 0.06), panel)
    text("FT06_Title", "TWINOPS  /  FT06", (-11, 8.65, 0.09), 0.72, white)
    text("FT06_Subtitle", "PUBLISHED BENCHMARK  /  ABSTRACT TIME UNITS  /  CONCEPTUAL LAYOUT",
         (-11, 7.85, 0.09), 0.23, muted)
    text("FT06_Run_Identity", "SCENARIO", (-11, 7.28, 0.09), 0.22, accent)
    cards = [(-8, "MAKESPAN", "FT06_KPI_Makespan", str(state["makespan"])),
             (-1, "DISPATCH / SOLVER", "FT06_KPI_Policy", state["policy"]),
             (6, "JOBS / OPERATIONS", "FT06_KPI_Count", "6 / 36")]
    for x, caption, name, value in cards:
        box(name + "_Card", (x + 1.1, 5.95, 0.045), (6.1, 1.6, 0.07), panel)
        text(name + "_Caption", caption, (x - 1.45, 6.34, 0.10), 0.2, muted)
        text(name, value, (x - 1.45, 5.63, 0.10), 0.4 if name.endswith("Policy") else 0.6, white)
    for machine in sorted(state["machines"]):
        x, y = bridge["station_xy"](machine)
        box(f"FT06_StationPad_{machine}", (x, y - 0.20, 0.04), (5.3, 4.2, 0.05), panel)
        obj = box(f"FT06_Machine_{machine}", (x, y, 0.42), (2.4, 1.6, 0.74), housing)
        obj["machine"] = machine
        box(f"FT06_Housing_{machine}", (x, y + 0.42, 1.24), (1.8, 0.7, 1.15), housing)
        box(f"FT06_Display_{machine}", (x, y + 0.045, 1.36), (1.35, 0.05, 0.58), glass)
        box(f"FT06_Accent_{machine}", (x, y - 0.82, 0.69), (2.0, 0.05, 0.07), accent, 0.01)
        box(f"FT06_Worktop_{machine}", (x, y - 0.32, 0.89), (2.5, 1.0, 0.13), glass)
        # Front labels avoid both machine-housing occlusion and KPI-card overlap.
        text(f"FT06_Label_{machine}", machine, (x - 2.35, y - 1.25, 0.15), 0.28, white)
        text(f"FT06_Stats_{machine}", "UTIL", (x - 2.35, y - 2.80, 0.15), 0.20, muted)
        box(f"FT06_QueueStripe_{machine}", (x, y - 1.94, 0.12), (3.5, 0.68, 0.06), glass)
        text(f"FT06_QueueLabel_{machine}", "WAIT", (x - 2.35, y - 2.03, 0.15), 0.18, muted)
    box("Output lane", (0, -7.5, 0.1), (7.7, 1.4, 0.12), panel)
    text("Output title", "COMPLETED", (-3.55, -6.85, 0.2), 0.25, green)
    text("FT06_Clock", "TIME", (-11, -9.0, 0.1), 0.48, white)
    text("Replay explanation", "PLAY TIMELINE TO REPLAY  /  ZERO TRANSPORT TIME  /  COLORED CUBES ARE JOBS",
         (-11, -9.65, 0.1), 0.23, muted)
    for index, color in enumerate(JOB_COLORS):
        job = f"J{index + 1}"
        job_mat = material(f"Job {job}", color, metallic=0.15, roughness=0.28)
        obj = box(f"FT06_Product_{job}", (0, 0, 1), (0.40, 0.40, 0.45), job_mat, 0.04)
        obj["job"] = job
        label = text(f"FT06_ProductLabel_{job}", job, (0, 0, 0), 0.16, white)
        label.parent = obj
        label.location = (-0.14, -0.205, -0.04)
        label.rotation_euler = (math.pi / 2, 0, 0)
        box(f"Legend_{job}", (-11.6, 3.75 - index * 0.85, 0.25), (0.35, 0.35, 0.35), job_mat)
        text(f"LegendLabel_{job}", job, (-11.15, 3.62 - index * 0.85, 0.12), 0.28, white)
    world = bpy.data.worlds.new("FT06 studio")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.10, 0.14, 0.20, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.45
    area_light("Key softbox", (0, -6, 17), 2400, 13, (0.85, 0.93, 1.0))
    area_light("Rim softbox", (8, 9, 12), 1800, 10, (0.45, 0.75, 1.0))
    camera_data = bpy.data.cameras.new("FT06 Overview Camera")
    camera = bpy.data.objects.new("FT06 Overview Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (12, -23, 31)
    camera.rotation_euler = (Vector((0, 0.1, 0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 30.5
    scene.camera = camera
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 1440
    scene.render.resolution_y = 1120
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.fps = 24
    scene.view_settings.view_transform = "AgX"
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"
                area.spaces.active.shading.type = "MATERIAL"
    return scene


# =========================================================
# BACKGROUND BUILD, EMBEDDED REFRESH SCRIPT, AND REAL SCENE VERIFICATION
# =========================================================
def build(state_path, output_path, preview_path=None):
    state_path, output_path = Path(state_path).resolve(), Path(output_path).resolve()
    if output_path.suffix.lower() != ".blend" or output_path.name != "FT06_Pilot.blend":
        raise ValueError("The separate scene must be named FT06_Pilot.blend")
    if state_path.parent != output_path.parent:
        raise ValueError("active_run.json and FT06_Pilot.blend must share one runtime folder")
    source = Path(__file__).with_name("blender_bridge.py").read_text(encoding="utf-8")
    namespace = {"__name__": "ft06_embedded_bridge"}
    exec(compile(source, "FT06_Bridge", "exec"), namespace)
    state = namespace["load_state"](state_path)
    scene = create_geometry(state, namespace)
    embedded = bpy.data.texts.new("FT06_Bridge")
    embedded.write(source)
    readme = bpy.data.texts.new("FT06_README")
    readme.write("TWINOPS FT06 PILOT\n\nSeparate published benchmark scene, not measured factory geometry.\n"
                 "The adjacent active_run.json is the only data source.\n"
                 "Play the timeline for baked product motion, clock, DONE and WAIT counts; no auto-run permission required.\n"
                 "The clock displays one-unit steps and operation boundaries, not continuous fractional time.\n"
                 "Only to refresh manually replaced adjacent JSON: open Scripting > FT06_Bridge and Run Script.\n"
                 "Alternatively use TwinOps 'Build Blender scene' after applying a new run.\n"
                 "Instant station jumps represent the declared zero transport time.\n"
                 "Original TwinOps.blend and its synthetic A/B/C bridge are untouched.\n")
    result = namespace["apply_state"](state, state_path, bake=True)
    preview_time = min(state["makespan"] * 0.38, state["makespan"])
    scene.frame_set(int(round(preview_time * scene["ft06_frames_per_unit"])) + 1)
    namespace["update_frame"](scene)
    # Verify the actual constructed objects/animation against the consumed run.
    for timestamp in (0, state["makespan"] / 2, state["makespan"]):
        frame = int(round(timestamp * scene["ft06_frames_per_unit"])) + 1
        scene.frame_set(frame)
        exact_time = (frame - 1) / scene["ft06_frames_per_unit"]
        expected = namespace["snapshot_at"](state, exact_time)
        for job, snap in expected.items():
            obj = bpy.data.objects[f"FT06_Product_{job}"]
            if (obj.location - Vector(snap["position"])).length > 1e-5 or obj["status"] != snap["status"]:
                raise AssertionError(f"Scene replay mismatch for {job} at {exact_time}")
    scene.frame_set(int(round(preview_time * scene["ft06_frames_per_unit"])) + 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path), check_existing=False)
    if preview_path:
        preview_path = Path(preview_path).resolve()
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(preview_path)
        bpy.ops.render.render(write_still=True)
    result.update({"scene": str(output_path), "preview": str(preview_path) if preview_path else None,
                   "preview_time": scene["ft06_replay_time"],
                   "machines": 6, "products": 6, "baked_animation": True,
                   "baked_clock_steps": scene["ft06_baked_clock_steps"], "clock_requires_auto_run": False,
                   "independent_scene_checks": "passed at start, midpoint, and completion"})
    (output_path.parent / "blender_build_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("FT06_BUILD_RESULT=" + json.dumps(result))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--preview")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    build(args.state, args.output, args.preview)


if __name__ == "__main__":
    main()

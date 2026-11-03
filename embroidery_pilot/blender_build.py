"""Build an isolated, baked embroidery scene using preserved FT06 geometry helpers."""
from pathlib import Path
import argparse
import json
import math
import sys

import bpy
from mathutils import Vector

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from ft06_pilot.blender_build import material, box, text, area_light
from ft06_pilot.blender_bridge import constant_animation
from embroidery_pilot.blender_bridge import load_state, snapshot_at, station_xy

PHASE_COLORS = {'hoop_prepare': (0.2, 0.6, 1, 1), 'embroidery': (0.2, 0.86, 0.66, 1),
                'attach_embroidery': (1, 0.65, 0.16, 1), 'chenille_change': (0.6, 0.35, 1, 1),
                'chenille': (1, 0.37, 0.23, 1), None: (0.12, 0.2, 0.26, 1)}

# =========================================================
# FT06 GEOMETRY REUSE AND CONCEPTUAL FOUR MACHINE FACTORY
# =========================================================
def geometry(state):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = 'TwinOps Embroidery Pilot'
    s = state['scenario']
    dark = material('Graphite', (0.025, 0.04, 0.06, 1), roughness=0.8)
    panel = material('Panels', (0.047, 0.078, 0.105, 1))
    metal = material('Machine satin', (0.25, 0.37, 0.42, 1), 0.45, 0.32)
    white = material('Type white', (0.85, 0.94, 1, 1), emission=0.6)
    muted = material('Type muted', (0.42, 0.6, 0.7, 1), emission=0.5)
    cyan = material('Barudan accent', (0.1, 0.8, 0.8, 1), emission=0.5)
    amber = material('Tajima accent', (1, 0.5, 0.17, 1), emission=0.5)
    box('Factory floor', (0, 0, -0.15), (30, 26, 0.3), dark)
    for x in range(-14, 15, 2):
        box(f'GridX{x}', (x, -1, 0.01), (0.012, 22, 0.01), panel, 0)
    for y in range(-12, 13, 2):
        box(f'GridY{y}', (0, y, 0.01), (28, 0.012, 0.01), panel, 0)
    box('Header panel', (0, 9.3, 0.03), (28, 5, 0.06), panel)
    text('Title', 'TWINOPS / EMBROIDERY', (-13.2, 10.5, 0.1), 0.85, white)
    text('Evidence label', f"{s['data_kind'].upper()} INPUTS  /  UNVERIFIED SPEEDS  /  CONCEPTUAL LAYOUT", (-13.2, 9.6, 0.1), 0.28, amber)
    text('Policy', f"{state['policy'].upper()}   /   {state['status']}   /   {state['run_id'][:12]}", (-13.2, 8.7, 0.1), 0.36, cyan)
    text('Summary', f"{len(s['machines'])} MACHINES     {sum(m['heads'] for m in s['machines'])} HEADS     {s['workers']} OPERATORS     09:00 - 17:00", (-13.2, 7.65, 0.1), 0.38, white)
    for m in s['machines']:
        x, y = station_xy(m['id'], s)
        accent = amber if 'chenille' in m['capabilities'] else cyan
        box(f"Pad_{m['id']}", (x, y - 0.35, 0.03), (10.9, 4.8, 0.06), panel)
        body = box(f"Machine_{m['id']}", (x, y, 0.6), (9.7, 1.25, 1.0), metal)
        body['machine_id'], body['head_count'] = m['id'], m['heads']
        box(f"Bed_{m['id']}", (x, y - 0.5, 1.1), (9.8, 1.0, 0.1), dark)
        box(f"Beam_{m['id']}", (x, y + 0.3, 1.88), (9.7, 0.3, 0.3), metal)
        for h in range(m['heads']):
            hx = x + (h - (m['heads'] - 1) / 2) * 0.48
            head = box(f"Head_{m['id']}_{h+1:02d}", (hx, y + 0.13, 1.55), (0.32, 0.5, 0.7), accent, 0.03)
            head['machine_id'], head['head_index'] = m['id'], h + 1
            box(f"Needle_{m['id']}_{h+1:02d}", (hx, y - 0.1, 1.2), (0.025, 0.025, 0.2), white, 0)
            garment = box(f"Garment_{m['id']}_{h+1:02d}", (hx, y - 0.5, 1.17), (0.35, 0.43, 0.035), white, 0.02)
            garment['machine_id'], garment['head_index'] = m['id'], h + 1
        text(f"Label_{m['id']}", f"{m['id']} / {'TAJIMA' if m['id']=='M4' else 'BARUDAN'} / {m['heads']} HEADS", (x - 4.85, y - 1.35, 0.11), 0.38, white)
        detail = 'ATTACH > CHANGE > CHENILLE / ONE BATCH' if 'chenille' in m['capabilities'] else 'SYNCHRONIZED BATCH / STANDARD EMBROIDERY'
        text(f"Detail_{m['id']}", detail, (x - 4.85, y - 1.95, 0.11), 0.21, accent)
    for i, e in enumerate(state['events']):
        mat = material(f"Batch color {i}", (0.95, 0.5, 0.2, 1) if e['machine'] == 'M4' else (0.12, 0.74, 0.83, 1))
        obj = box(e['batch'], (0, 0, 0.3), (0.38, 0.38, 0.2), mat, 0.03)
        obj['pieces'], obj['order'] = e['pieces'], e['order']
    text('Output label', 'COMPLETED BATCHES', (-4.2, -8.35, 0.1), 0.28, cyan)
    box('Output lane', (1, -9.2, 0.05), (11.8, 1.1, 0.1), panel)
    text('Interpretation', 'ONE TOKEN = ONE BATCH / GARMENTS SHOW LOADED HEADS / PLAY TIMELINE', (-13.2, -11.2, 0.1), 0.27, muted)
    text('Limitations', 'NO MEASURED FACTORY LAYOUT OR COMMERCIAL RESULT / 1 FRAME = 1 WALL MINUTE', (-13.2, -11.8, 0.1), 0.24, amber)
    world = bpy.data.worlds.new('Embroidery studio')
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0.12, 0.17, 0.23, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = 0.45
    area_light('Key softbox', (0, -6, 20), 3500, 18, (0.83, 0.94, 1))
    area_light('Rim softbox', (8, 10, 12), 2200, 12, (0.4, 0.8, 1))
    camdata = bpy.data.cameras.new('Embroidery overview')
    camera = bpy.data.objects.new('Embroidery overview', camdata)
    bpy.context.collection.objects.link(camera)
    camera.location = (9, -23, 43)
    camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camdata.type, camdata.ortho_scale = 'ORTHO', 35
    scene.camera = camera
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1400
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.fps = 24
    scene.view_settings.view_transform = 'AgX'
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
                area.spaces.active.shading.type = 'MATERIAL'
    return scene, white


# =========================================================
# BAKED TIMELINE PHASES LOADED HEADS AND RESOURCE HUD
# =========================================================
def bake(state, scene, white):
    scene.frame_start, scene.frame_end = 1, state['makespan'] + 1
    scene['run_id'], scene['scenario_id'] = state['run_id'], state['scenario_id']
    scene['frames_per_minute'] = 1
    boundaries = sorted({0, state['makespan']} | {p[k] for e in state['events'] for p in e['phases'] for k in ('start', 'end')})
    for t in boundaries:
        snap = snapshot_at(state, t)
        for batch, info in snap['batches'].items():
            obj = bpy.data.objects[batch]
            obj.location = info['position']
            obj.keyframe_insert(data_path='location', frame=t + 1)
        for m in state['scenario']['machines']:
            active = next((e for e in state['events'] if e['machine'] == m['id'] and e['start'] <= t < e['end']), None)
            for h in range(m['heads']):
                obj = bpy.data.objects[f"Garment_{m['id']}_{h+1:02d}"]
                obj.hide_render = obj.hide_viewport = not active or h >= active['pieces']
                obj.keyframe_insert(data_path='hide_render', frame=t + 1)
                obj.keyframe_insert(data_path='hide_viewport', frame=t + 1)
        title = f"EVENT {snap['clock'].replace('Gün', 'DAY')}  |  DONE {snap['completed_pieces']}/{state['completed_pieces']}  |  OPERATORS {snap['operators']}/{state['scenario']['workers']}  |  HOOPS {snap['hoops']}/{state['scenario']['hoops']}"
        hud = text(f'Clock_{t}', title, (-13.2, -10.45, 0.1), 0.37, white)
        for k in ('hide_render', 'hide_viewport'):
            setattr(hud, k, True)
            hud.keyframe_insert(data_path=k, frame=1)
            setattr(hud, k, False)
            hud.keyframe_insert(data_path=k, frame=t + 1)
            next_time = next((u for u in boundaries if u > t), state['makespan'] + 1)
            setattr(hud, k, True)
            hud.keyframe_insert(data_path=k, frame=next_time + 1)
        for m in state['scenario']['machines']:
            x, y = station_xy(m['id'], state['scenario'])
            active = next((e for e in state['events'] if e['machine'] == m['id'] and e['start'] <= t < e['end']), None)
            phase = next((p['phase'] for p in active['phases'] if p['start'] <= t < p['end']), None) if active else None
            lamp_mat = material(f'Phase {m["id"]} {t}', PHASE_COLORS[phase], emission=0.7)
            lamp = box(f'Phase_{m["id"]}_{t}', (x, y - 2.25, 0.15), (9.6, 0.1, 0.04), lamp_mat, 0)
            for k in ('hide_render', 'hide_viewport'):
                setattr(lamp, k, True)
                lamp.keyframe_insert(data_path=k, frame=1)
                setattr(lamp, k, False)
                lamp.keyframe_insert(data_path=k, frame=t + 1)
                setattr(lamp, k, True)
                lamp.keyframe_insert(data_path=k, frame=next_time + 1)
    for obj in bpy.data.objects:
        constant_animation(obj)
    scene['clock_note'] = 'Event boundary snapshots; label holds until next event. 1 frame = 1 minute.'
    return boundaries


# =========================================================
# ACTUAL SCENE REPLAY AND OPENUSD IMPORT VERIFICATION
# =========================================================
def build(state_path, output, preview):
    output, preview = Path(output).resolve(), Path(preview).resolve()
    if output.name != 'Embroidery_Pilot.blend' or output.parent != Path(state_path).resolve().parent:
        raise ValueError('Ayrı Embroidery_Pilot.blend ve active_run.json aynı koşu klasöründe olmalı.')
    state = load_state(state_path)
    scene, white = geometry(state)
    boundaries = bake(state, scene, white)
    checks = []
    for t in boundaries:
        scene.frame_set(t + 1)
        snap = snapshot_at(state, t)
        for bid, data in snap['batches'].items():
            if (bpy.data.objects[bid].location - Vector(data['position'])).length > 1e-5:
                raise AssertionError('Baked batch motion mismatch')
        visible = [o for o in bpy.data.objects if o.name.startswith('Clock_') and not o.hide_render]
        if len(visible) != 1:
            raise AssertionError('Clock must have exactly one visible label')
        for m in state['scenario']['machines']:
            loaded = sum(not bpy.data.objects[f"Garment_{m['id']}_{h+1:02d}"].hide_render for h in range(m['heads']))
            expected = sum(e['pieces'] for e in state['events'] if e['machine'] == m['id'] and e['start'] <= t < e['end'])
            if loaded != expected:
                raise AssertionError('Loaded head count mismatch')
        checks.append(t)
    scene.frame_set(31)
    readme = bpy.data.texts.new('EMBROIDERY_README')
    readme.write(f"Input kind: {state['data_kind']}. Geometry reuses FT06 helpers. Machines and heads are conceptual.\n"
                 'Play timeline; baked animation requires no auto-run. Each token represents one batch.\n'
                 'All time values are wall minutes since day 1 09:00. HUD holds event boundary snapshots.\n'
                 'Refresh by rebuilding from the Streamlit 3D tab. See adjacent active_run.json and embroidery.usda.\n')
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    scene.render.filepath = str(preview)
    bpy.ops.render.render(write_still=True)
    # Import the actual exported USD in a disposable scene; original saved scene is intact.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.usd_import(filepath=str(output.parent / 'embroidery.usda'), import_cameras=False, import_lights=False)
    imported = {o.name for o in bpy.data.objects}
    for bid in [e['batch'] for e in state['events']]:
        if bid not in imported:
            raise AssertionError('USD import missing batch: ' + bid)
    report = {'run_id': state['run_id'], 'scenario_id': state['scenario_id'], 'machine_count': len(state['scenario']['machines']),
              'head_count': sum(m['heads'] for m in state['scenario']['machines']), 'batch_count': len(state['events']),
              'checked_timeline_boundaries': checks, 'baked_scene_checks': 'passed', 'usd_import': 'passed',
              'usd_objects': len(imported), 'preview_time': 30, 'requires_auto_run': False}
    (output.parent / 'scene_validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('EMBROIDERY_SCENE=' + json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--preview', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    build(args.state, args.output, args.preview)

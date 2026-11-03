"""Reuse FT06 atomic JSON export; write only isolated embroidery artifacts."""
from pathlib import Path
import json
import subprocess
from ft06_pilot.export import atomic_json, find_blender
from .engine import validate_result
from .blender_bridge import snapshot_at, station_xy

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT.parent / 'runtime'

# =========================================================
# IMMUTABLE RUN EXPORT AND OPENUSD TIME SAMPLES
# =========================================================
def write_usd(state, path):
    s = state['scenario']
    # Boundary samples hold positions until 0.001 minute before a route jump.
    # USD viewers may linearly interpolate over this last 0.001 minute (0.06s).
    # Blender uses CONSTANT baked keyframes at exact integer minutes.
    times = {0, state['makespan']}
    for e in state['events']:
        for p in e['phases']:
            for t in (p['start'], p['end']):
                times.add(t)
                if t > 0:
                    times.add(t - 0.001)
    lines = ['#usda 1.0', '(', '    defaultPrim = "Embroidery"', '    upAxis = "Z"',
             '    metersPerUnit = 1', '    timeCodesPerSecond = 24',
             f'    startTimeCode = 1', f'    endTimeCode = {1 + state["makespan"]}', ')',
             'def Xform "Embroidery" {', f'    custom string run_id = "{state["run_id"]}"',
             f'    custom string data_label = "{s["data_kind"].upper()} INPUTS / UNVERIFIED SPEEDS / FORECAST"',
             '    def Cube "Floor" {', '        double size = 1', '        double3 xformOp:scale = (30, 25, 0.15)',
             '        uniform token[] xformOpOrder = ["xformOp:scale"]', '        color3f[] primvars:displayColor = [(0.035, 0.05, 0.075)]', '    }']
    for m in s['machines']:
        x, y = station_xy(m['id'], s)
        lines += [f'    def Xform "{m["id"]}" {{', f'        custom int heads = {m["heads"]}',
                  f'        double3 xformOp:translate = ({x}, {y}, 0)', '        uniform token[] xformOpOrder = ["xformOp:translate"]',
                  '        def Cube "Bed" {', '            double size = 1', '            double3 xformOp:translate = (0, 0, 0.7)',
                  '            double3 xformOp:scale = (9.5, 1.4, 0.65)',
                  '            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]',
                  '            color3f[] primvars:displayColor = [(0.18, 0.29, 0.34)]', '        }']
        for i in range(m['heads']):
            hx = (i - (m['heads'] - 1) / 2) * 0.48
            lines += [f'        def Cube "Head_{i+1:02d}" {{', '            double size = 1',
                      f'            double3 xformOp:translate = ({hx}, 0.25, 1.5)', '            double3 xformOp:scale = (0.32, 0.55, 0.8)',
                      '            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]',
                      '            color3f[] primvars:displayColor = [(0.12, 0.72, 0.75)]', '        }']
        lines.append('    }')
    for e in state['events']:
        lines += [f'    def Cube "{e["batch"]}" {{', '        double size = 0.35',
                  f'        custom int pieces = {e["pieces"]}', '        color3f[] primvars:displayColor = [(0.95, 0.55, 0.22)]',
                  '        double3 xformOp:translate.timeSamples = {']
        for t in sorted(times):
            pos = snapshot_at(state, t)['batches'][e['batch']]['position']
            lines.append(f'            {t+1:.3f}: ({pos[0]}, {pos[1]}, {pos[2]}),')
        lines += ['        }', '        uniform token[] xformOpOrder = ["xformOp:translate"]', '    }']
    lines.append('}')
    Path(path).write_text('\n'.join(lines), encoding='utf-8')


def export_run(s, result, runtime=RUNTIME):
    validate_result(s, result)
    folder = Path(runtime) / 'runs' / result['run_id']
    state = dict(result, scenario=s)
    atomic_json(folder / 'active_run.json', state)
    write_usd(state, folder / 'embroidery.usda')
    atomic_json(Path(runtime) / 'active_run.json', state)
    return folder


# =========================================================
# SEPARATE BLENDER SCENE BUILD WITH MATCHED RUN MANIFEST
# =========================================================
def build_blender(s, result, runtime=RUNTIME):
    folder = export_run(s, result, runtime)
    cmd = [find_blender(), '--background', '--python', str(ROOT / 'blender_build.py'), '--',
           '--state', str(folder / 'active_run.json'), '--output', str(folder / 'Embroidery_Pilot.blend'),
           '--preview', str(folder / 'preview.png')]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
    (folder / 'blender_build.log').write_text(p.stdout + p.stderr, encoding='utf-8')
    if p.returncode or not (folder / 'preview.png').is_file() or not (folder / 'Embroidery_Pilot.blend').is_file():
        raise RuntimeError('Blender oluşturulamadı: ' + str(folder / 'blender_build.log'))
    manifest = {'run_id': result['run_id'], 'scenario_id': result['scenario_id'],
                'blend': str(folder / 'Embroidery_Pilot.blend'), 'preview': str(folder / 'preview.png'),
                'usd': str(folder / 'embroidery.usda')}
    atomic_json(Path(runtime) / 'scene_manifest.json', manifest)
    return manifest

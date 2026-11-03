"""Validated run artifacts isolated from the synthetic USD/Blender state."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import threading
import uuid

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'runtime'
_LOCK = threading.RLock()


# =========================================================
# ATOMIC FT06 RUN EXPORT AND SCENARIO IDENTITY
# =========================================================

def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep atomic-write names short enough for nested Windows checkouts.
    temp = path.with_name('.' + uuid.uuid4().hex[:16] + '.tmp')
    try:
        with temp.open('w', encoding='utf-8', newline='\n') as file:
            json.dump(payload, file, indent=2, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def export_run(scenario, result, runtime=RUNTIME):
    from ft06_pilot.engine import validate_result
    validate_result(scenario, result)
    payload = dict(result, scenario=scenario)
    with _LOCK:
        run_dir = Path(runtime) / 'runs' / result['run_id']
        atomic_json(run_dir / 'active_run.json', payload)
        atomic_json(Path(runtime) / 'active_run.json', payload)
    return run_dir


# =========================================================
# SEPARATE BLENDER BUILD AND STALE PREVIEW PROTECTION
# =========================================================

def find_blender():
    configured = os.environ.get('TWINOPS_BLENDER')
    candidates = [configured, shutil.which('blender'),
                  r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise FileNotFoundError('Blender bulunamadı. TWINOPS_BLENDER ile blender.exe yolunu belirtin.')


def build_blender(scenario, result, runtime=RUNTIME):
    with _LOCK:
        run_dir = export_run(scenario, result, runtime)
        blend = run_dir / 'FT06_Pilot.blend'
        preview = run_dir / 'preview.png'
        command = [find_blender(), '--background', '--python', str(ROOT / 'blender_build.py'),
                   '--', '--state', str(run_dir / 'active_run.json'), '--output', str(blend),
                   '--preview', str(preview)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                       errors='replace', timeout=180)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('Blender oluşturma süresi aşıldı; önceki sahne korunuyor.') from error
        (run_dir / 'blender_build.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
        if completed.returncode or not blend.is_file() or not preview.is_file():
            raise RuntimeError('Blender sahnesi oluşturulamadı; ayrıntı: ' + str(run_dir / 'blender_build.log'))
        # Keep a convenient latest scene, together with its exact adjacent state.
        shutil.copy2(blend, Path(runtime) / 'FT06_Pilot.blend')
        shutil.copy2(preview, Path(runtime) / 'preview.png')
        atomic_json(Path(runtime) / 'scene_manifest.json', {
            'run_id': result['run_id'], 'scenario_id': result['scenario_id'],
            'blend': str(blend), 'preview': str(preview),
        })
    return {'blend': blend, 'preview': preview, 'run_id': result['run_id']}

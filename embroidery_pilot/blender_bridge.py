"""Pure replay shared by USD, Streamlit and Blender; no UI process or global handler."""
from pathlib import Path
import json
from .engine import validate_result
from .model import clock

# =========================================================
# VALIDATED STATE AND EXACT HALF-OPEN TIMELINE SNAPSHOTS
# =========================================================
def load_state(path):
    p = Path(path)
    if p.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('Sahne girdisi 8 MiB sınırını aşıyor.')
    state = json.loads(p.read_text(encoding='utf-8'))
    validate_result(state['scenario'], state)
    return state


def station_xy(machine_id, s):
    index = next(i for i, m in enumerate(s['machines']) if m['id'] == machine_id)
    return ((index % 2) * 12 - 6, 2.8 - (index // 2) * 6.0)


def snapshot_at(state, timestamp):
    s = state['scenario']
    snapshots, done = {}, 0
    for i, e in enumerate(state['events']):
        if timestamp < e['start']:
            status, phase = 'waiting', None
            position = (-12 + (i % 5) * 0.52, 5 - (i // 5) * 0.6, 0.25)
        elif timestamp >= e['end']:
            status, phase = 'done', None
            position = (-4 + (i % 15) * 0.52, -9 - (i // 15) * 0.55, 0.25)
            done += e['pieces']
        else:
            p = next(p for p in e['phases'] if p['start'] <= timestamp < p['end'])
            status, phase = 'active', p['phase']
            x, y = station_xy(e['machine'], s)
            position = (x, y - 0.4, 1.25)
        snapshots[e['batch']] = {'position': position, 'status': status, 'phase': phase, 'pieces': e['pieces']}
    return {'batches': snapshots, 'completed_pieces': done, 'clock': clock(timestamp),
            'operators': sum(p['workers'] for e in state['events'] for p in e['phases'] if p['start'] <= timestamp < p['end']),
            'hoops': sum(e['pieces'] for e in state['events'] if e['start'] <= timestamp < e['end'])}

"""Batch input contract; physical heads are synchronized, never independent servers."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# =========================================================
# FACTORY FACTS AND EXPLICIT SCENARIO ASSUMPTIONS
# =========================================================
def integer(value, label, minimum=0, maximum=1000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label}: {minimum}–{maximum} arasında tamsayı gerekli.')
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}', value):
        raise ValueError('Kimlikler harfle başlamalı; harf, rakam ve alt çizgi içermeli (en fazla 40).')
    return value


def load_scenario(path=None):
    return validate_scenario(json.loads(Path(path or ROOT / 'demo_synthetic.json').read_text(encoding='utf-8-sig')))


def validate_scenario(raw):
    if not isinstance(raw, dict) or raw.get('schema_version') != 1 or raw.get('mode') != 'embroidery':
        raise ValueError('embroidery şema sürümü 1 gerekli.')
    s = copy.deepcopy(raw)
    if s.get('data_kind') not in ('synthetic', 'measured'):
        raise ValueError('Veri türü synthetic veya measured olmalı.')
    if not isinstance(s.get('source'), str) or not s['source'].strip():
        raise ValueError('Veri kaynağı açıklanmalı.')
    if not isinstance(s.get('name'), str) or not s['name'].strip():
        raise ValueError('Senaryo adı gerekli.')
    integer(s.get('days'), 'Plan ufku (gün)', 1, 14)
    integer(s.get('workers'), 'Operatör', 1, 20)
    integer(s.get('hoops'), 'Eşzamanlı kasnak stoku', 1, 500)
    if type(s.get('attend_running')) is not bool:
        raise ValueError('Çalışma boyunca operatör ayarı bool olmalı.')
    if s.get('shift_start') != '09:00' or s.get('shift_minutes') != 480:
        raise ValueError('Bu pilotta mesai 09:00–17:00 (480 dakika).')
    machines = s.get('machines')
    if not isinstance(machines, list) or not 1 <= len(machines) <= 10:
        raise ValueError('1–10 makine gerekli.')
    ids = set()
    for m in machines:
        if not isinstance(m, dict):
            raise ValueError('Her makine JSON nesnesi olmalı.')
        mid = identifier(m.get('id'))
        if mid in ids:
            raise ValueError('Tekrarlı makine kimliği.')
        ids.add(mid)
        integer(m.get('heads'), 'Kafa sayısı', 1, 50)
        if not isinstance(m.get('capabilities'), list) or not m['capabilities'] or not set(m['capabilities']) <= {'standard', 'chenille'}:
            raise ValueError('Geçersiz makine uygunluğu.')
        for key in ('standard_spm', 'attach_spm', 'chenille_spm'):
            integer(m.get(key), key, 1, 3000)
        if m.get('rate_basis') != 'scenario_assumption':
            raise ValueError('Bu sürümde hızlar doğrulanmamış senaryo varsayımıdır.')
    orders = s.get('orders')
    if not isinstance(orders, list) or not 1 <= len(orders) <= 30:
        raise ValueError('1–30 sipariş gerekli.')
    seen = set()
    for o in orders:
        if not isinstance(o, dict):
            raise ValueError('Her sipariş JSON nesnesi olmalı.')
        oid = identifier(o.get('id'))
        if oid in seen:
            raise ValueError('Tekrarlı sipariş kimliği.')
        seen.add(oid)
        if o.get('kind') not in ('standard', 'chenille'):
            raise ValueError('Ürün türü standard veya chenille olmalı.')
        integer(o.get('quantity'), 'Adet', 1, 2000)
        integer(o.get('batch_size'), 'Parti büyüklüğü', 1, 50)
        integer(o.get('release'), 'Hazır olma', 0, s['days'] * 1440 - 1)
        integer(o.get('due'), 'Termin', 0, s['days'] * 1440)
        if o['due'] < o['release']:
            raise ValueError('Termin hazır olma zamanından önce olamaz.')
        for k in ('prep_minutes', 'change_minutes'):
            integer(o.get(k), k, 1, 120)
        for k in ('stitches', 'attach_stitches', 'chenille_stitches'):
            integer(o.get(k), k, 1, 200000)
        if not isinstance(o.get('eligible'), list) or not o['eligible'] or len(set(o['eligible'])) != len(o['eligible']) or not set(o['eligible']) <= ids:
            raise ValueError('Sipariş uygun makine listesi geçersiz.')
    if not isinstance(s.get('assumptions'), list) or any(not isinstance(v, str) for v in s['assumptions']):
        raise ValueError('Varsayımlar metin listesi olmalı.')
    try:
        json.dumps(s, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise ValueError('Sonlu JSON değerleri gerekli.') from e
    batches = make_batches(s)
    if len(batches) > 120:
        raise ValueError('Etkileşimli pilot en fazla 120 parti destekler.')
    for batch in batches:
        if batch['pieces'] > s['hoops']:
            raise ValueError(f"{batch['id']}: kasnak stoku yetersiz; parti boyunu küçültün.")
        if not alternatives(s, batch):
            raise ValueError(f"{batch['id']}: kabiliyet/kafa/mesai sınırına uygun makine yok.")
    return s


# =========================================================
# SYNCHRONIZED BATCHES AND CONTIGUOUS TAJIMA PHASES
# =========================================================
def make_batches(s):
    batches = []
    for rank, o in enumerate(s['orders']):
        left, index = o['quantity'], 1
        while left:
            pieces = min(left, o['batch_size'])
            batches.append({'id': f"{o['id']}_B{index:03d}", 'order': o['id'], 'pieces': pieces,
                            'release': o['release'], 'due': o['due'], 'rank': rank, 'index': index})
            left -= pieces
            index += 1
    return batches


def order_for(s, batch):
    return next(o for o in s['orders'] if o['id'] == batch['order'])


def phase_spec(s, batch, machine):
    o = order_for(s, batch)
    phases = [('hoop_prepare', o['prep_minutes'], 1)]
    if o['kind'] == 'standard':
        phases += [('embroidery', math.ceil(o['stitches'] / machine['standard_spm']), int(s['attend_running']))]
    else:
        phases += [('attach_embroidery', math.ceil(o['attach_stitches'] / machine['attach_spm']), int(s['attend_running'])),
                   ('chenille_change', o['change_minutes'], 1),
                   ('chenille', math.ceil(o['chenille_stitches'] / machine['chenille_spm']), int(s['attend_running']))]
    offset, result = 0, []
    for name, duration, workers in phases:
        result.append({'phase': name, 'offset': offset, 'duration': duration, 'workers': workers})
        offset += duration
    return result


def alternatives(s, batch):
    o = order_for(s, batch)
    return [m for m in s['machines'] if m['id'] in o['eligible'] and o['kind'] in m['capabilities']
            and batch['pieces'] <= m['heads']
            and sum(p['duration'] for p in phase_spec(s, batch, m)) <= s['shift_minutes']]


def phases_at(s, batch, machine, start):
    return [dict(p, start=start + p['offset'], end=start + p['offset'] + p['duration'])
            for p in phase_spec(s, batch, machine)]


def digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()[:20]


def scenario_hash(s):
    return digest(validate_scenario(s))


def clock(minutes):
    day, minute = divmod(int(minutes), 1440)
    hours, minute = divmod(minute + 540, 60)
    if hours >= 24:
        day, hours = day + 1, hours - 24
    return f'Gün {day + 1} · {hours:02d}:{minute:02d}'

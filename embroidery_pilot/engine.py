"""FIFO list scheduling, independent checks, and real SimPy resource execution.

Extends the FT06 plan -> validate -> SimPy replay -> validated result contract.
"""
from __future__ import annotations

from collections import defaultdict
import math

from .model import (alternatives, digest, integer, make_batches, phases_at,
                    scenario_hash, validate_scenario)

# =========================================================
# FIFO EARLIEST FEASIBLE BATCH DISPATCH WITH SHARED RESOURCES
# =========================================================
def capacity_ok(intervals, capacity):
    changes = defaultdict(int)
    for start, end, demand in intervals:
        changes[start] += demand
        changes[end] -= demand
    active = 0
    for t in sorted(changes):
        active += changes[t]
        if active > capacity or active < 0:
            return False
    return active == 0


def event_for(s, b, m, start):
    phases = phases_at(s, b, m, start)
    return {'batch': b['id'], 'order': b['order'], 'pieces': b['pieces'], 'machine': m['id'],
            'start': start, 'end': phases[-1]['end'], 'phases': phases}


def fits(s, event, reserved):
    if any(e['machine'] == event['machine'] and e['start'] < event['end'] and event['start'] < e['end'] for e in reserved):
        return False
    all_events = reserved + [event]
    if not capacity_ok([(e['start'], e['end'], e['pieces']) for e in all_events], s['hoops']):
        return False
    return capacity_ok([(p['start'], p['end'], p['workers']) for e in all_events for p in e['phases']], s['workers'])


def fifo_schedule(s):
    reserved = []
    for batch in sorted(make_batches(s), key=lambda b: (b['release'], b['rank'], b['index'])):
        choices = []
        for machine in alternatives(s, batch):
            duration = event_for(s, batch, machine, 0)['end']
            found = None
            for day in range(s['days']):
                first = max(batch['release'], day * 1440)
                last = day * 1440 + s['shift_minutes'] - duration
                for start in range(first, last + 1):
                    event = event_for(s, batch, machine, start)
                    if fits(s, event, reserved):
                        found = event
                        break
                if found:
                    break
            if found:
                choices.append(found)
        if not choices:
            raise ValueError(f"FIFO: {batch['id']} plan ufkuna sığmadı; ufku uzatın veya yükü azaltın.")
        reserved.append(min(choices, key=lambda e: (e['end'], e['start'], e['machine'])))
    return sorted(reserved, key=lambda e: (e['start'], e['machine'], e['batch']))


# =========================================================
# INDEPENDENT BATCH CONSERVATION SHIFT PRECEDENCE AND CAPACITY CHECKS
# =========================================================
def validate_schedule(s, events):
    s = validate_scenario(s)
    batches = {b['id']: b for b in make_batches(s)}
    machines = {m['id']: m for m in s['machines']}
    seen, work = {}, defaultdict(list)
    if not isinstance(events, list):
        raise ValueError('Olay listesi gerekli.')
    for e in events:
        bid = e.get('batch')
        if bid not in batches or bid in seen:
            raise ValueError('Eksik, fazla veya tekrarlı parti.')
        b = batches[bid]
        if e.get('machine') not in {m['id'] for m in alternatives(s, b)}:
            raise ValueError('Makine kabiliyeti veya kafa kapasitesi ihlali.')
        integer(e.get('start'), 'Başlangıç')
        integer(e.get('end'), 'Bitiş')
        expected = event_for(s, b, machines[e['machine']], e['start'])
        if digest(e) != digest(expected):
            raise ValueError('Parti adedi, fazlar veya süreler kaynak girdiye uymuyor.')
        if e['start'] < b['release']:
            raise ValueError('Hazır olmadan üretim başladı.')
        day = e['start'] // 1440
        if day >= s['days'] or e['end'] > day * 1440 + s['shift_minutes']:
            raise ValueError('Mesai sınırı ihlali.')
        seen[bid] = e
        work[e['machine']].append(e)
    if set(seen) != set(batches):
        raise ValueError('Parti korunumu ihlali: bütün işler planlanmalı.')
    for seq in work.values():
        ordered = sorted(seq, key=lambda e: e['start'])
        if any(a['end'] > b['start'] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('Aynı makinede çakışan partiler (Tajima fazları dahil).')
    ops = [(p['start'], p['end'], p['workers']) for e in events for p in e['phases']]
    if not capacity_ok(ops, s['workers']):
        raise ValueError('Operatör kapasitesi ihlali.')
    if not capacity_ok([(e['start'], e['end'], e['pieces']) for e in events], s['hoops']):
        raise ValueError('Kasnak stoku ihlali.')
    summaries = []
    for o in s['orders']:
        relevant = [e for e in events if e['order'] == o['id']]
        completion = max(e['end'] for e in relevant)
        summaries.append({'order': o['id'], 'quantity': sum(e['pieces'] for e in relevant),
                          'completion': completion, 'due': o['due'], 'tardiness': max(0, completion - o['due'])})
    shift_capacity = s['days'] * s['shift_minutes']
    return {'makespan': max(e['end'] for e in events),
            'total_tardiness': sum(o['tardiness'] for o in summaries),
            'completed_pieces': sum(e['pieces'] for e in events),
            'first_shift_pieces': sum(e['pieces'] for e in events if e['end'] <= s['shift_minutes']),
            'orders': summaries,
            'operator_minutes': sum((end - start) * demand for start, end, demand in ops),
            'machine_metrics': {m['id']: {
                'occupied_minutes': sum(e['end'] - e['start'] for e in work[m['id']]),
                'processing_minutes': sum(p['duration'] for e in work[m['id']] for p in e['phases'] if not p['workers'] or p['phase'] in ('embroidery', 'attach_embroidery', 'chenille')),
                'occupied_fraction_of_horizon_shifts': sum(e['end'] - e['start'] for e in work[m['id']]) / shift_capacity}
                for m in s['machines']}}


# =========================================================
# SIMPY MACHINE OPERATOR AND HOOP RESOURCE REPLAY
# =========================================================
def replay(s, planned):
    import simpy
    validate_schedule(s, planned)
    env = simpy.Environment()
    machines = {m['id']: simpy.Resource(env, capacity=1) for m in s['machines']}
    workers = simpy.Container(env, capacity=s['workers'], init=s['workers'])
    hoops = simpy.Container(env, capacity=s['hoops'], init=s['hoops'])
    actual = []

    def execute(e):
        yield env.timeout(e['start'])
        with machines[e['machine']].request() as req:
            yield req
            yield hoops.get(e['pieces'])
            if env.now != e['start']:
                raise RuntimeError('SimPy makine/kasnak başlangıcı çizelgeden ayrıldı.')
            for p in e['phases']:
                if p['workers']:
                    yield workers.get(p['workers'])
                if env.now != p['start']:
                    raise RuntimeError('SimPy operatör başlangıcı çizelgeden ayrıldı.')
                yield env.timeout(p['duration'])
                if p['workers']:
                    yield workers.put(p['workers'])
                if env.now != p['end']:
                    raise RuntimeError('SimPy faz bitişi çizelgeden ayrıldı.')
            yield hoops.put(e['pieces'])
            actual.append(e)
    # End releases at a shared boundary are processed before queued gets can advance.
    for e in sorted(planned, key=lambda e: (e['start'], e['machine'], e['batch'])):
        env.process(execute(e))
    env.run()
    if len(actual) != len(planned) or workers.level != s['workers'] or hoops.level != s['hoops']:
        raise RuntimeError('SimPy kaynak veya ürün korunumu başarısız.')
    return sorted(actual, key=lambda e: (e['start'], e['machine'], e['batch']))


# =========================================================
# REPRODUCIBLE RESULT IDENTITY AND VERIFIED METRICS
# =========================================================
def validate_result(s, result):
    if result.get('schema_version') != 1 or result.get('mode') != 'embroidery' or result.get('scenario_id') != scenario_hash(s):
        raise ValueError('Koşu başka senaryoya ait veya şeması geçersiz.')
    if result.get('policy') not in ('fifo', 'optimized') or result.get('status') not in ('FEASIBLE', 'OPTIMAL', 'FIFO_FALLBACK'):
        raise ValueError('Geçersiz plan politikası veya durum.')
    metrics = validate_schedule(s, result['events'])
    if digest({k:result.get(k) for k in metrics}) != digest(metrics):
        raise ValueError('Raporlanan metrik olaylardan hesaplanan değerle uyuşmuyor.')
    if result.get('run_id') != digest({'scenario_id': result['scenario_id'], 'policy': result['policy'], 'events': result['events']}):
        raise ValueError('Koşu kimliği olaylarla uyuşmuyor.')
    if result.get('data_kind') != s['data_kind'] or result.get('financial_value') is not None:
        raise ValueError('Veri etiketi/ekonomik kanıt sözleşmesi ihlali.')
    if result['policy'] == 'fifo' and result['status'] != 'FEASIBLE':
        raise ValueError('FIFO planı optimum iddiası taşıyamaz.')
    if result['policy'] == 'optimized' and result['status'] != 'FIFO_FALLBACK':
        weight = (s['days'] - 1) * 1440 + s['shift_minutes'] + 1
        objective = metrics['total_tardiness'] * weight + metrics['makespan']
        bound = result.get('objective_bound')
        if type(bound) not in (int,float) or not math.isfinite(bound) or not 0 <= bound <= objective:
            raise ValueError('CP-SAT kanıt alt sınırı geçersiz.')
        if result.get('objective_value') != objective or result.get('objective_weight') != weight:
            raise ValueError('CP-SAT amaç değeri metriklerle uyuşmuyor.')
        if result['status'] == 'OPTIMAL' and not math.isclose(bound, objective, abs_tol=1e-6):
            raise ValueError('Optimum iddiası alt sınırla doğrulanmıyor.')
    return True


def run_scenario(scenario, policy='fifo', time_limit=10):
    s = validate_scenario(scenario)
    metadata = {}
    if policy == 'optimized':
        from .optimizer import solve_schedule
        solved = solve_schedule(s, time_limit)
        planned = solved.pop('events')
        metadata = solved
    elif policy == 'fifo':
        planned = fifo_schedule(s)
    else:
        raise ValueError('Politika fifo veya optimized olmalı.')
    events = replay(s, planned)
    sid = scenario_hash(s)
    result = {'schema_version': 1, 'mode': 'embroidery', 'scenario_id': sid,
              'policy': policy, 'status': 'FEASIBLE', 'data_kind': s['data_kind'],
              'financial_value': None, 'economic_status': 'Potansiyel senaryo; doğrulanmış fiyat/maliyet ve satış verisi yok.',
              'simulation': 'SimPy machine + operator + hoop replay', 'events': events,
              **validate_schedule(s, events), **metadata}
    result['run_id'] = digest({'scenario_id': sid, 'policy': policy, 'events': events})
    validate_result(s, result)
    return result

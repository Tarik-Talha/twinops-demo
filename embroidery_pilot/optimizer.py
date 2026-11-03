"""Alternative machine/day CP-SAT intervals and cumulative preparation resources."""
import math
from .model import alternatives, make_batches, phase_spec, validate_scenario

# =========================================================
# CP-SAT CONTIGUOUS BATCH ALTERNATIVES AND SHIFT WINDOWS
# =========================================================
def solve_schedule(scenario, time_limit=10):
    from ortools.sat.python import cp_model
    from .engine import event_for, fifo_schedule, validate_schedule
    s = validate_scenario(scenario)
    if type(time_limit) not in (int, float) or not math.isfinite(time_limit) or not 0 < time_limit <= 120:
        raise ValueError('Çözüm süresi 0–120 saniye arasında sonlu olmalı.')
    # A feasible FIFO schedule is both a warm start and a conservative incumbent.
    try:
        baseline = fifo_schedule(s)
    except ValueError:
        baseline = None
    horizon = (s['days'] - 1) * 1440 + s['shift_minutes']
    model = cp_model.CpModel()
    machine_intervals = {m['id']: [] for m in s['machines']}
    operator_intervals, hoop_intervals, hoop_demands = [], [], []
    variables = {}
    batches = make_batches(s)
    hints = {e['batch']: e for e in baseline or []}
    for b in batches:
        start = model.new_int_var(b['release'], horizon, 'start_' + b['id'])
        end = model.new_int_var(b['release'], horizon, 'end_' + b['id'])
        options = []
        for m in alternatives(s, b):
            specs = phase_spec(s, b, m)
            duration = sum(p['duration'] for p in specs)
            for day in range(s['days']):
                if max(b['release'], day * 1440) + duration > day * 1440 + s['shift_minutes']:
                    continue
                label = f"{b['id']}_{m['id']}_{day}"
                present = model.new_bool_var('use_' + label)
                interval = model.new_optional_interval_var(start, duration, end, present, label)
                model.add(start >= day * 1440).only_enforce_if(present)
                model.add(end <= day * 1440 + s['shift_minutes']).only_enforce_if(present)
                machine_intervals[m['id']].append(interval)
                hoop_intervals.append(interval)
                hoop_demands.append(b['pieces'])
                for p in specs:
                    if p['workers']:
                        phase = model.new_optional_fixed_size_interval_var(start + p['offset'], p['duration'], present, label + p['phase'])
                        operator_intervals.append(phase)
                options.append((present, m))
                if b['id'] in hints:
                    hint = hints[b['id']]
                    model.add_hint(present, int(hint['machine'] == m['id'] and hint['start'] // 1440 == day))
        if not options:
            raise ValueError(f"{b['id']}: kalan mesai penceresine sığan alternatif yok.")
        model.add_exactly_one(p for p, _ in options)
        if b['id'] in hints:
            model.add_hint(start, hints[b['id']]['start'])
            model.add_hint(end, hints[b['id']]['end'])
        variables[b['id']] = (start, end, options)
    for intervals in machine_intervals.values():
        model.add_no_overlap(intervals)
    model.add_cumulative(operator_intervals, [1] * len(operator_intervals), s['workers'])
    model.add_cumulative(hoop_intervals, hoop_demands, s['hoops'])

    # Break interchangeable full-batch symmetry within one order.
    for left, right in zip(batches, batches[1:]):
        if left['order'] == right['order'] and left['pieces'] == right['pieces']:
            model.add(variables[left['id']][0] <= variables[right['id']][0])

    # Exact lexicographic objective: first sum(order tardiness), then makespan.
    tardiness = []
    for o in s['orders']:
        completion = model.new_int_var(0, horizon, 'completion_' + o['id'])
        model.add_max_equality(completion, [variables[b['id']][1] for b in batches if b['order'] == o['id']])
        late = model.new_int_var(0, horizon, 'late_' + o['id'])
        model.add_max_equality(late, [0, completion - o['due']])
        tardiness.append(late)
    makespan = model.new_int_var(0, horizon, 'makespan')
    model.add_max_equality(makespan, [v[1] for v in variables.values()])
    weight = horizon + 1
    objective = sum(tardiness) * weight + makespan
    if baseline:
        bm = validate_schedule(s, baseline)
        model.add(objective <= bm['total_tardiness'] * weight + bm['makespan'])
    model.minimize(objective)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if baseline is not None and status == cp_model.UNKNOWN:
            return {'events': baseline, 'status': 'FIFO_FALLBACK', 'solver_status': solver.status_name(status),
                    'objective': 'sum_tardiness_then_makespan', 'objective_value': None,
                    'objective_bound': None, 'wall_seconds': solver.wall_time}
        raise ValueError(f'CP-SAT uygulanabilir plan bulamadı: {solver.status_name(status)}')
    events = []
    for b in batches:
        start, end, opts = variables[b['id']]
        m = next(m for present, m in opts if solver.value(present))
        events.append(event_for(s, b, m, solver.value(start)))
    validate_schedule(s, events)
    return {'events': events, 'status': solver.status_name(status), 'solver_status': solver.status_name(status),
            'objective': 'sum_tardiness_then_makespan', 'objective_weight': weight,
            'objective_value': solver.objective_value, 'objective_bound': solver.best_objective_bound,
            'wall_seconds': solver.wall_time}

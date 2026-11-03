"""CP-SAT scheduling for explicit routes; no fabricated financial objective."""

from __future__ import annotations

import math

from .model import validate_scenario


# =========================================================
# CONSTRAINED MAKESPAN OPTIMIZATION WITH A REPORTED PROOF BOUND
# =========================================================

def solve_schedule(scenario: dict, time_limit: float = 10) -> dict:
    from ortools.sat.python import cp_model

    scenario = validate_scenario(scenario)
    if isinstance(time_limit, bool) or not isinstance(time_limit, (int, float)) or not math.isfinite(time_limit) or not 0 < time_limit <= 120:
        raise ValueError("Optimization time limit must be finite and from above 0 to 120 seconds.")
    horizon = max(job["release"] for job in scenario["jobs"]) + sum(
        op["duration"] for job in scenario["jobs"] for op in job["operations"])
    model = cp_model.CpModel()
    intervals = {machine["id"]: [] for machine in scenario["machines"]}
    variables, final_ends = {}, []
    for job in scenario["jobs"]:
        previous = None
        for index, operation in enumerate(job["operations"]):
            key = (job["id"], index)
            start = model.new_int_var(job["release"], horizon, f"start_{job['id']}_{index}")
            end = model.new_int_var(job["release"], horizon, f"end_{job['id']}_{index}")
            interval = model.new_interval_var(start, operation["duration"], end, f"op_{job['id']}_{index}")
            if previous is not None:
                model.add(start >= previous)
            previous = end
            intervals[operation["machine"]].append(interval)
            variables[key] = (start, end)
        final_ends.append(previous)
    for machine in scenario["machines"]:
        work = intervals[machine["id"]]
        if machine["capacity"] == 1:
            model.add_no_overlap(work)
        else:
            model.add_cumulative(work, [1] * len(work), machine["capacity"])
    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, final_ends)
    model.minimize(makespan)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"No validated feasible schedule was obtained: {solver.status_name(status)}")
    events = []
    for job in scenario["jobs"]:
        ready = job["release"]
        for index, operation in enumerate(job["operations"]):
            start, end = variables[(job["id"], index)]
            event = {"job": job["id"], "operation": index, "machine": operation["machine"],
                     "start": solver.value(start), "end": solver.value(end),
                     "duration": operation["duration"], "ready": ready}
            ready = event["end"]
            events.append(event)
    capacities = {machine["id"]: machine["capacity"] for machine in scenario["machines"]}
    slot_ends = {name: [0] * capacity for name, capacity in capacities.items()}
    for event in sorted(events, key=lambda item: (item["start"], item["end"], item["job"], item["operation"])):
        available = [index for index, end in enumerate(slot_ends[event["machine"]]) if end <= event["start"]]
        if not available:
            raise RuntimeError("Solver schedule could not be assigned to a physical capacity slot.")
        event["slot"] = min(available)
        slot_ends[event["machine"]][event["slot"]] = event["end"]
    return {"events": events, "status": solver.status_name(status),
            "bound": solver.best_objective_bound, "solver_wall_time": solver.wall_time}


def optimize_scenario(scenario: dict, time_limit: float = 10) -> dict:
    """Return the same independently checked SimPy-replayed contract as the UI."""
    from .engine import run_scenario
    return run_scenario(scenario, policy="optimized", time_limit=time_limit)


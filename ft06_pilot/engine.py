"""Competing-job dispatch, independent schedule checks and actual SimPy replay."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections import defaultdict

import simpy

from .model import scenario_hash, validate_scenario


# =========================================================
# SIMPY DISPATCH OF MIXED JOB ROUTES AND MACHINE CAPACITY SLOTS
# =========================================================

def _event_order(event: dict) -> tuple:
    return event["start"], event["machine"], event["slot"], event["job"], event["operation"]


def _dispatch(scenario: dict, policy: str) -> list[dict]:
    env = simpy.Environment()
    jobs = scenario["jobs"]
    job_by_id = {job["id"]: job for job in jobs}
    job_order = {job["id"]: index for index, job in enumerate(jobs)}
    queues = {machine["id"]: [] for machine in scenario["machines"]}
    free = {machine["id"]: set(range(machine["capacity"])) for machine in scenario["machines"]}
    arrivals = sorted((job["release"], job_order[job["id"]], job["id"]) for job in jobs)
    active, events = [], []

    def enqueue(job_id: str, operation_index: int):
        operation = job_by_id[job_id]["operations"][operation_index]
        queues[operation["machine"]].append({"job": job_id, "operation": operation_index,
                                              "machine": operation["machine"], "duration": operation["duration"],
                                              "ready": env.now})

    def coordinator():
        completed_jobs, arrival_index, ticket = 0, 0, 0
        while completed_jobs < len(jobs):
            while active and active[0][0] == env.now:
                _, _, event = heapq.heappop(active)
                free[event["machine"]].add(event["slot"])
                following = event["operation"] + 1
                if following < len(job_by_id[event["job"]]["operations"]):
                    enqueue(event["job"], following)
                else:
                    completed_jobs += 1
            while arrival_index < len(arrivals) and arrivals[arrival_index][0] == env.now:
                enqueue(arrivals[arrival_index][2], 0)
                arrival_index += 1
            for machine in scenario["machines"]:
                queue = queues[machine["id"]]
                if policy == "spt":
                    queue.sort(key=lambda event: (event["duration"], event["ready"], job_order[event["job"]], event["operation"]))
                else:
                    queue.sort(key=lambda event: (event["ready"], job_order[event["job"]], event["operation"]))
                while queue and free[machine["id"]]:
                    event = queue.pop(0)
                    slot = min(free[machine["id"]])
                    free[machine["id"]].remove(slot)
                    event.update(start=env.now, end=env.now + event["duration"], slot=slot)
                    events.append(event)
                    ticket += 1
                    heapq.heappush(active, (event["end"], ticket, event))
            if completed_jobs == len(jobs):
                break
            next_times = ([active[0][0]] if active else [])
            if arrival_index < len(arrivals):
                next_times.append(arrivals[arrival_index][0])
            if not next_times or min(next_times) <= env.now:
                raise RuntimeError("Simulation made no forward progress.")
            yield env.timeout(min(next_times) - env.now)

    env.process(coordinator())
    env.run()
    return events


def _serial(scenario: dict) -> list[dict]:
    events, cursor = [], 0
    for job in scenario["jobs"]:
        ready = job["release"]
        for index, operation in enumerate(job["operations"]):
            start = max(cursor, ready)
            cursor = start + operation["duration"]
            events.append({"job": job["id"], "operation": index, "machine": operation["machine"],
                           "start": start, "end": cursor, "duration": operation["duration"],
                           "ready": ready, "slot": 0})
            ready = cursor
    return events


# =========================================================
# INDEPENDENT DURATION PRECEDENCE CAPACITY AND METRIC VALIDATION
# =========================================================

def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number.")
    return value


def _same(actual: object, expected: float, label: str):
    if not math.isclose(_finite(actual, label), expected, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError(f"{label} does not match the independent calculation.")


def validate_schedule(scenario: dict, events: list[dict]) -> dict:
    """Recalculate every constraint and metric from input and emitted events."""
    scenario = validate_scenario(scenario)
    if not isinstance(events, list):
        raise ValueError("Events must be a list.")
    expected = {(job["id"], index): operation for job in scenario["jobs"]
                for index, operation in enumerate(job["operations"])}
    machine_by_id = {machine["id"]: machine for machine in scenario["machines"]}
    observed, by_machine, by_slot = {}, defaultdict(list), defaultdict(list)
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Every event must be an object.")
        operation_index = event.get("operation")
        if isinstance(operation_index, bool) or not isinstance(operation_index, int):
            raise ValueError("Operation indices must be integers.")
        key = (event.get("job"), operation_index)
        if key not in expected or key in observed:
            raise ValueError("An operation is unknown or appears more than once.")
        operation = expected[key]
        if event.get("machine") != operation["machine"]:
            raise ValueError("An operation used the wrong machine.")
        for name in ("start", "end", "duration", "ready"):
            if _finite(event.get(name), name) < 0:
                raise ValueError("Operation times cannot be negative.")
        _same(event["duration"], operation["duration"], "Operation duration")
        _same(event["end"] - event["start"], operation["duration"], "Elapsed duration")
        slot = event.get("slot")
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < machine_by_id[event["machine"]]["capacity"]:
            raise ValueError("The machine capacity slot is invalid.")
        observed[key] = event
        by_machine[event["machine"]].append(event)
        by_slot[(event["machine"], slot)].append(event)
    if set(observed) != set(expected):
        raise ValueError("Operation conservation failed: missing or extra work.")
    job_summary = []
    for job in scenario["jobs"]:
        ready, wait = job["release"], 0
        for index in range(len(job["operations"])):
            event = observed[(job["id"], index)]
            _same(event["ready"], ready, "Operation ready time")
            if event["start"] < ready:
                raise ValueError("Release or job precedence constraint was violated.")
            wait += event["start"] - ready
            ready = event["end"]
        job_summary.append({"job": job["id"], "release": job["release"], "completion": ready, "wait": wait})
    for work in by_slot.values():
        ordered = sorted(work, key=lambda event: (event["start"], event["end"]))
        if any(previous["end"] > following["start"] for previous, following in zip(ordered, ordered[1:])):
            raise ValueError("Machine slot overlap: capacity constraint was violated.")
    makespan = max(event["end"] for event in events)
    machines = {}
    for machine in scenario["machines"]:
        work = by_machine[machine["id"]]
        changes = defaultdict(int)
        queue_changes = defaultdict(int)
        for event in work:
            changes[event["start"]] += 1
            changes[event["end"]] -= 1
            queue_changes[event["ready"]] += 1
            queue_changes[event["start"]] -= 1
        running, queued, max_queue = 0, 0, 0
        for time in sorted(changes):
            running += changes[time]
            if not 0 <= running <= machine["capacity"]:
                raise ValueError("Total concurrent operations exceeded machine capacity.")
        for time in sorted(queue_changes):
            queued += queue_changes[time]
            if queued < 0:
                raise ValueError("Queue conservation failed.")
            max_queue = max(max_queue, queued)
        if running != 0 or queued != 0:
            raise ValueError("Work did not leave all queues and capacity slots.")
        busy_time = sum(event["duration"] for event in work)
        machines[machine["id"]] = {
            "capacity": machine["capacity"], "busy_time": busy_time,
            "utilization": busy_time / (makespan * machine["capacity"]),
            "average_wait": sum(event["start"] - event["ready"] for event in work) / len(work) if work else 0,
            "max_queue": max_queue,
        }
    return {"makespan": makespan, "throughput": len(scenario["jobs"]),
            "machines": machines, "job_summary": job_summary}


def validate_result(scenario: dict, result: dict) -> bool:
    if not isinstance(result, dict) or result.get("schema_version") != 2 or result.get("mode") != "ft06":
        raise ValueError("Invalid FT06 result contract.")
    if result.get("policy") not in {"fifo", "spt", "serial", "optimized"}:
        raise ValueError("Unknown result scheduling policy.")
    if result.get("status") not in {"FEASIBLE", "OPTIMAL"}:
        raise ValueError("A result must contain a feasible schedule.")
    if result.get("scenario_id") != scenario_hash(scenario):
        raise ValueError("Result belongs to another scenario.")
    expected = validate_schedule(scenario, result.get("events"))
    for field in ("makespan", "throughput"):
        _same(result.get(field), expected[field], field)
    if set(result.get("machines", {})) != set(expected["machines"]):
        raise ValueError("Result machine inventory is incomplete.")
    for identifier, metrics in expected["machines"].items():
        for field, expected_value in metrics.items():
            _same(result["machines"][identifier].get(field), expected_value, f"{identifier} {field}")
    actual_jobs = result.get("job_summary")
    if not isinstance(actual_jobs, list) or len(actual_jobs) != len(expected["job_summary"]):
        raise ValueError("Result job inventory is incomplete.")
    mapping = {job.get("job"): job for job in actual_jobs}
    if len(mapping) != len(actual_jobs):
        raise ValueError("Duplicate result job summary.")
    for job in expected["job_summary"]:
        if job["job"] not in mapping:
            raise ValueError("Missing job summary.")
        for field in ("release", "completion", "wait"):
            _same(mapping[job["job"]].get(field), job[field], f"{job['job']} {field}")
    if result.get("run_id") != _run_hash(result["scenario_id"], result.get("policy"), result["events"]):
        raise ValueError("Result event identity is inconsistent.")
    if result.get("time_unit") != scenario["time_unit"] or result.get("name") != scenario["name"]:
        raise ValueError("Result source name or time unit is inconsistent.")
    if result.get("source") != scenario.get("source") or result.get("assumptions") != scenario.get("assumptions", []):
        raise ValueError("Result source or assumptions were changed.")
    if result["policy"] == "optimized":
        bound = _finite(result.get("bound"), "Solver lower bound")
        if not 0 <= bound <= expected["makespan"]:
            raise ValueError("The optimizer lower bound is inconsistent.")
        if result["status"] == "OPTIMAL":
            _same(bound, expected["makespan"], "Proved optimum lower bound")
        if _finite(result.get("solver_wall_time"), "Solver wall time") < 0:
            raise ValueError("Solver wall time cannot be negative.")
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("Result metadata must contain finite, JSON-compatible values.") from error
    return True


# =========================================================
# ACTUAL SIMPY RESOURCE REPLAY AND ONE CONSISTENT RUN CONTRACT
# =========================================================

def _replay(scenario: dict, planned: list[dict]) -> list[dict]:
    """Execute all releases, resource acquisitions and operation completions in SimPy."""
    validate_schedule(scenario, planned)
    env, actual = simpy.Environment(), []
    resources = {(machine["id"], slot): simpy.Resource(env, capacity=1)
                 for machine in scenario["machines"] for slot in range(machine["capacity"])}
    lookup = {(event["job"], event["operation"]): event for event in planned}

    def product(job: dict):
        yield env.timeout(job["release"])
        for index, operation in enumerate(job["operations"]):
            planned_event = lookup[(job["id"], index)]
            ready = env.now
            yield env.timeout(planned_event["start"] - env.now)
            with resources[(operation["machine"], planned_event["slot"])].request() as request:
                yield request
                start = env.now
                if start != planned_event["start"]:
                    raise RuntimeError("SimPy resource replay diverged from the checked schedule.")
                yield env.timeout(operation["duration"])
                actual.append({"job": job["id"], "operation": index, "machine": operation["machine"],
                               "start": start, "end": env.now, "duration": operation["duration"],
                               "ready": ready, "slot": planned_event["slot"]})

    for job in scenario["jobs"]:
        env.process(product(job))
    env.run()  # Running until idle also executes completions at the exact makespan.
    return sorted(actual, key=_event_order)


def _run_hash(scenario_id: str, policy: str, events: list[dict]) -> str:
    payload = json.dumps({"scenario_id": scenario_id, "policy": policy,
                          "events": sorted(events, key=_event_order)}, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def run_scenario(scenario: dict, policy: str = "fifo", time_limit: float = 10) -> dict:
    scenario = validate_scenario(scenario)
    if policy not in {"fifo", "spt", "serial", "optimized"}:
        raise ValueError("Policy must be fifo, spt, serial or optimized.")
    solver_metadata = {}
    if policy == "optimized":
        from .optimizer import solve_schedule
        solved = solve_schedule(scenario, time_limit=time_limit)
        planned, status = solved["events"], solved["status"]
        solver_metadata = {"solver": "OR-Tools CP-SAT", "bound": solved["bound"],
                           "solver_wall_time": solved["solver_wall_time"]}
    else:
        planned = _serial(scenario) if policy == "serial" else _dispatch(scenario, policy)
        status = "FEASIBLE"
    events = _replay(scenario, planned)
    metrics = validate_schedule(scenario, events)
    identity = scenario_hash(scenario)
    result = {"schema_version": 2, "mode": "ft06", "scenario_id": identity,
              "run_id": _run_hash(identity, policy, events), "policy": policy, "status": status,
              "name": scenario["name"], "time_unit": scenario["time_unit"],
              "kind": scenario.get("kind", "published benchmark, not measured factory"),
              "source": scenario.get("source"), "assumptions": scenario.get("assumptions", []),
              "events": events, "simulation": "SimPy resource replay",
              "validation": {"duration": True, "precedence": True, "release": True,
                             "capacity": True, "conservation": True, "metrics": True},
              **metrics, **solver_metadata}
    validate_result(scenario, result)
    return result


"""Explicit job routes and scenario validation for the isolated FT06 pilot."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


# =========================================================
# PUBLISHED FT06 INPUT AND EXPLICIT SCENARIO ASSUMPTIONS
# =========================================================

DEFAULT_INSTANCE = Path(__file__).resolve().parents[1] / "assessment" / "ft06_instance.json"


def load_instance(path: str | Path | None = None) -> dict:
    """Read the acquired source without treating benchmark units as real minutes."""
    raw = json.loads(Path(path or DEFAULT_INSTANCE).read_text(encoding="utf-8-sig"))
    if raw.get("schema_version") == 2:
        return validate_scenario(raw)
    durations, routes = raw["durations"], raw["machines"]
    releases, capacities = raw["release_times"], raw["machine_capacities"]
    if len(durations) != len(routes) or len(durations) != len(releases):
        raise ValueError("Source job, route and release arrays have different lengths.")
    jobs = []
    for index, (times, route) in enumerate(zip(durations, routes)):
        if len(times) != len(route):
            raise ValueError(f"Source job {index + 1} has mismatched operation arrays.")
        if any(isinstance(machine, bool) or not isinstance(machine, int) for machine in route):
            raise ValueError("Source machine indices must be integers.")
        jobs.append({"id": f"J{index + 1}", "release": releases[index], "operations": [
            {"machine": f"M{machine + 1}", "duration": duration}
            for machine, duration in zip(route, times)
        ]})
    scenario = {
        "schema_version": 2, "name": raw["name"], "time_unit": raw["time_unit"],
        "kind": raw["kind"], "source": raw["source"], "jobs": jobs,
        "machines": [{"id": f"M{index + 1}", "capacity": capacity}
                     for index, capacity in enumerate(capacities)],
        "assumptions": [
            "Published benchmark; not measurements of a real factory.",
            "Abstract benchmark time units; no conversion to minutes or hours.",
            "Machines are available throughout the run; operations are non-preemptive.",
            "Unlimited waiting buffers; zero setup and transport times.",
            "Each operation requires one slot on its named machine; no worker constraint.",
            "Identical parallel slots when a machine capacity is increased.",
            "No breakdown, energy, cost, physical layout or real-factory calibration data.",
        ],
    }
    return validate_scenario(scenario)


# =========================================================
# STRICT JOB ROUTE VALIDATION AND REPRODUCIBLE SCENARIO IDENTITY
# =========================================================

def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} to {maximum}.")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise ValueError(f"{label} must be a nonempty string of at most 80 characters.")
    return value


def validate_scenario(scenario: dict) -> dict:
    """Validate supported rules and return a defensive copy, without filling gaps."""
    if not isinstance(scenario, dict) or scenario.get("schema_version") != 2:
        raise ValueError("The FT06 pilot requires scenario schema_version 2.")
    _identifier(scenario.get("name"), "Scenario name")
    _identifier(scenario.get("time_unit"), "Time unit")
    machines, jobs = scenario.get("machines"), scenario.get("jobs")
    if not isinstance(machines, list) or not 1 <= len(machines) <= 100:
        raise ValueError("A scenario must contain 1 to 100 machines.")
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 100:
        raise ValueError("A scenario must contain 1 to 100 jobs.")
    machine_ids = set()
    for machine in machines:
        if not isinstance(machine, dict):
            raise ValueError("Each machine must be an object.")
        identifier = _identifier(machine.get("id"), "Machine ID")
        if identifier in machine_ids:
            raise ValueError(f"Duplicate machine ID: {identifier}")
        machine_ids.add(identifier)
        _integer(machine.get("capacity"), f"{identifier} capacity", 1, 3)
    job_ids, operation_count = set(), 0
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("Each job must be an object.")
        identifier = _identifier(job.get("id"), "Job ID")
        if identifier in job_ids:
            raise ValueError(f"Duplicate job ID: {identifier}")
        job_ids.add(identifier)
        _integer(job.get("release"), f"{identifier} release", 0, 1000000)
        operations = job.get("operations")
        if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
            raise ValueError(f"{identifier} must have 1 to 100 operations.")
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("machine") not in machine_ids:
                raise ValueError(f"{identifier} contains an unknown machine.")
            _integer(operation.get("duration"), f"{identifier} duration", 1, 10000)
        operation_count += len(operations)
    if operation_count > 1000:
        raise ValueError("The interactive pilot is limited to 1000 operations.")
    assumptions = scenario.get("assumptions", [])
    if not isinstance(assumptions, list) or any(not isinstance(item, str) for item in assumptions):
        raise ValueError("Assumptions must be a list of strings.")
    try:
        json.dumps(scenario, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("Scenario metadata must contain finite, JSON-compatible values.") from error
    return copy.deepcopy(scenario)


def scenario_hash(scenario: dict) -> str:
    valid = validate_scenario(scenario)
    payload = json.dumps(valid, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


"""Self-contained FT06 replay bridge, embedded into the separate pilot scene.

Run this text inside Blender only to refresh a manually replaced adjacent
``active_run.json``. Product motion and the clock work without auto-run.
"""
import hashlib
import json
import math
from pathlib import Path

import bpy


# =========================================================
# FT06 STATE VALIDATION AND SAFE LOCAL REFRESH
# =========================================================
_STATE = None
_BRIDGE_HANDLER_TAG = "twinops_ft06_replay_v1"


def load_state(path):
    """Reject mismatched or infeasible event data before modifying the scene."""
    path = Path(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("FT06 state exceeds the 4 MiB limit")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("mode") != "ft06" or state.get("schema_version") != 2:
        raise ValueError("This scene accepts only FT06 schema version 2")
    if not state.get("scenario_id") or not state.get("run_id"):
        raise ValueError("Missing scenario/run identity")
    scenario = state.get("scenario")
    if not isinstance(scenario, dict) or scenario.get("schema_version") != 2:
        raise ValueError("Missing source scenario")
    scenario_payload = json.dumps(scenario, sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=False, allow_nan=False).encode("utf-8")
    if hashlib.sha256(scenario_payload).hexdigest()[:20] != state["scenario_id"]:
        raise ValueError("Scenario identity does not match its source inputs")
    run_payload = json.dumps({"scenario_id": state["scenario_id"], "policy": state["policy"],
                              "events": sorted(state["events"], key=lambda event: (
                                  event["start"], event["machine"], event["slot"],
                                  event["job"], event["operation"]))}, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    if hashlib.sha256(run_payload).hexdigest()[:20] != state["run_id"]:
        raise ValueError("Run identity does not match its operation events")
    if any(state.get(key) != scenario.get(key) for key in ("name", "time_unit", "assumptions", "kind", "source")):
        raise ValueError("Run provenance does not match its source scenario")
    machines = state.get("machines", {})
    if set(machines) != {f"M{i}" for i in range(1, 7)}:
        raise ValueError("FT06 requires machines M1..M6")
    for stats in machines.values():
        capacity = stats.get("capacity")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 3:
            raise ValueError("Machine capacity must be an integer from 1 to 3")
        utilization = stats.get("utilization")
        if not isinstance(utilization, (int, float)) or not math.isfinite(utilization) or not 0 <= utilization <= 1:
            raise ValueError("Machine utilization must be a finite fraction 0..1")
    makespan = state.get("makespan")
    if not isinstance(makespan, (int, float)) or not math.isfinite(makespan) or not 0 < makespan <= 4999:
        raise ValueError("Invalid makespan or replay exceeds the 30,000-frame limit")
    events = state.get("events", [])
    if len(events) != 36:
        raise ValueError("FT06 requires all 36 operations")
    by_job = {}
    intervals = {}
    for event in events:
        if event["machine"] not in machines:
            raise ValueError("Unknown event machine")
        numbers = [event[key] for key in ("start", "end", "duration", "ready")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or value < 0 for value in numbers):
            raise ValueError("Invalid or negative operation time")
        start, end, duration, ready = numbers
        if duration <= 0 or abs(end - start - duration) > 1e-6 or ready > start + 1e-6:
            raise ValueError("Invalid operation duration/readiness")
        slot = event["slot"]
        capacity = machines[event["machine"]]["capacity"]
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < capacity:
            raise ValueError("Operation exceeds machine capacity")
        intervals.setdefault((event["machine"], slot), []).append((start, end))
        by_job.setdefault(event["job"], []).append(event)
    if set(by_job) != {f"J{i}" for i in range(1, 7)}:
        raise ValueError("FT06 requires jobs J1..J6")
    source_jobs = {job["id"]: job for job in scenario.get("jobs", [])}
    source_machines = {machine["id"]: machine for machine in scenario.get("machines", [])}
    if len(scenario.get("jobs", [])) != 6 or set(source_jobs) != set(by_job):
        raise ValueError("Missing or duplicate source job")
    if len(scenario.get("machines", [])) != 6 or set(source_machines) != set(machines):
        raise ValueError("Missing or duplicate source machine")
    if any(source_machines[machine]["capacity"] != stats["capacity"] for machine, stats in machines.items()):
        raise ValueError("Run capacity differs from its source scenario")
    summaries = {entry["job"]: entry for entry in state["job_summary"]}
    if len(state["job_summary"]) != 6 or set(summaries) != set(by_job):
        raise ValueError("Duplicate or missing job summary")
    for summary in summaries.values():
        if any(not isinstance(summary.get(key), (int, float))
               or not math.isfinite(summary[key]) or summary[key] < 0 for key in ("release", "completion")):
            raise ValueError("Invalid job release/completion timestamp")
    for job, operations in by_job.items():
        operations.sort(key=lambda event: event["operation"])
        if [event["operation"] for event in operations] != list(range(6)):
            raise ValueError("Duplicate or missing job operation")
        source_job = source_jobs[job]
        if source_job["release"] != summaries[job]["release"] or len(source_job["operations"]) != 6:
            raise ValueError("Run release/route differs from its source scenario")
        for event in operations:
            source_operation = source_job["operations"][event["operation"]]
            if source_operation["machine"] != event["machine"] or source_operation["duration"] != event["duration"]:
                raise ValueError("Run operation differs from its source scenario")
        previous_end = summaries[job]["release"]
        for event in operations:
            if abs(event["ready"] - previous_end) > 1e-6 or event["start"] < previous_end - 1e-6:
                raise ValueError("Job precedence or ready timestamp mismatch")
            previous_end = event["end"]
        if abs(previous_end - summaries[job]["completion"]) > 1e-6:
            raise ValueError("Job completion mismatch")
        observed_wait = sum(event["start"] - event["ready"] for event in operations)
        if abs(observed_wait - summaries[job]["wait"]) > 1e-6:
            raise ValueError("Job waiting-time summary mismatch")
    for sequence in intervals.values():
        sequence.sort()
        if any(left[1] > right[0] + 1e-6 for left, right in zip(sequence, sequence[1:])):
            raise ValueError("Machine slot contains overlapping operations")
    if abs(max(event["end"] for event in events) - state["makespan"]) > 1e-6:
        raise ValueError("Makespan mismatch")
    if state.get("throughput") != len(by_job):
        raise ValueError("Completed-job count mismatch")
    for machine, stats in machines.items():
        operations = [event for event in events if event["machine"] == machine]
        busy = sum(event["duration"] for event in operations)
        utilization = busy / (state["makespan"] * stats["capacity"])
        wait = sum(event["start"] - event["ready"] for event in operations) / len(operations) if operations else 0
        boundaries = {value for event in operations for value in (event["ready"], event["start"])}
        max_queue = max((sum(event["ready"] <= timestamp < event["start"] for event in operations)
                         for timestamp in boundaries), default=0)
        for field, observed in (("busy_time", busy), ("utilization", utilization), ("average_wait", wait), ("max_queue", max_queue)):
            value = stats.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value - observed) > 1e-6:
                raise ValueError(f"Machine {machine} {field} does not match its operation events")
    return state


def station_xy(machine):
    index = int(machine[1:]) - 1
    return ((index % 3 - 1) * 7.0, 2.7 if index < 3 else -2.7)


# =========================================================
# EXACT EVENT REPLAY AND BAKED PORTABLE PRODUCT MOTION
# =========================================================
def snapshot_at(state, timestamp):
    """Half-open processing intervals; zero transport time means exact jumps."""
    by_job = {}
    summaries = {entry["job"]: entry for entry in state["job_summary"]}
    for event in state["events"]:
        by_job.setdefault(event["job"], []).append(event)
    snapshots = {}
    waiting = {}
    for job in sorted(by_job):
        operations = sorted(by_job[job], key=lambda event: event["operation"])
        if timestamp < summaries[job]["release"]:
            snapshots[job] = {"status": "not_released", "machine": None, "operation": None}
            continue
        for event in operations:
            if timestamp < event["end"]:
                status = "waiting" if timestamp < event["start"] else "processing"
                snapshots[job] = {"status": status, "machine": event["machine"],
                                  "operation": event["operation"], "slot": event["slot"]}
                if status == "waiting":
                    waiting.setdefault(event["machine"], []).append((event["ready"], job))
                break
        else:
            snapshots[job] = {"status": "done", "machine": None, "operation": None}
    for machine, queue in waiting.items():
        for rank, (_, job) in enumerate(sorted(queue)):
            snapshots[job]["queue_rank"] = rank
    for job, snapshot in snapshots.items():
        index = int(job[1:]) - 1
        status = snapshot["status"]
        if status == "not_released":
            position = (-1.5 + index * 0.6, 7.0, 0.5)
        elif status == "done":
            position = (-1.5 + index * 0.6, -7.5, 0.6)
        else:
            x, y = station_xy(snapshot["machine"])
            if status == "waiting":
                position = (x - 1.25 + snapshot["queue_rank"] * 0.5, y - 1.9, 0.47)
            else:
                capacity = state["machines"][snapshot["machine"]]["capacity"]
                position = (x + (snapshot["slot"] - (capacity - 1) / 2) * 0.4, y - 0.12, 1.32)
        snapshot["position"] = position
    return snapshots


def update_frame(scene, *unused):
    if _STATE is None:
        return
    timestamp = max(0.0, (scene.frame_current - 1) / scene["ft06_frames_per_unit"])
    snapshots = snapshot_at(_STATE, timestamp)
    done = 0
    for job, snapshot in snapshots.items():
        obj = bpy.data.objects.get(f"FT06_Product_{job}")
        if obj is not None:
            obj.location = snapshot["position"]
            obj["status"] = snapshot["status"]
            obj["machine"] = snapshot["machine"] or ""
            obj["operation"] = -1 if snapshot["operation"] is None else snapshot["operation"]
        done += snapshot["status"] == "done"
    clock = bpy.data.objects.get("FT06_Clock")
    if clock is not None:
        clock.data.body = f"TIME {timestamp:06.1f}  /  {_STATE['makespan']:g}   |   DONE {done}/6"
    scene["ft06_replay_time"] = timestamp
    scene["ft06_completed_jobs"] = done


update_frame._ft06_tag = _BRIDGE_HANDLER_TAG


def constant_animation(obj):
    animation = obj.animation_data
    if animation and animation.action:
        for layer in animation.action.layers:
            for strip in layer.strips:
                for channelbag in strip.channelbags:
                    for curve in channelbag.fcurves:
                        for point in curve.keyframe_points:
                            point.interpolation = "CONSTANT"


# =========================================================
# BAKED CLOCK, COMPLETION COUNTS, AND QUEUE COUNTS WITHOUT AUTO-RUN
# =========================================================
def bake_clock(scene, state):
    """Bake one-unit labels plus event boundaries; one label is visible per frame."""
    for obj in list(bpy.data.objects):
        if obj.name.startswith("FT06_BakedClock_"):
            data = obj.data
            action = obj.animation_data.action if obj.animation_data else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if data.users == 0:
                bpy.data.curves.remove(data)
            if action is not None and action.users == 0:
                bpy.data.actions.remove(action)
    base = bpy.data.objects["FT06_Clock"]
    base.hide_viewport = True
    base.hide_render = True
    scene["ft06_clock_resolution"] = "1 benchmark unit; also includes operation boundaries"
    # Map boundaries to actual replay frames, retaining the last reached step.
    time_points = {float(value) for value in range(int(math.floor(state["makespan"])) + 1)}
    time_points.add(float(state["makespan"]))
    time_points.update(float(event[field]) for event in state["events"]
                       for field in ("ready", "start", "end"))
    at_frame = {}
    for timestamp in sorted(time_points):
        frame = int(math.ceil(timestamp * scene["ft06_frames_per_unit"] - 1e-9)) + 1
        at_frame[frame] = timestamp
    clock_steps = sorted(at_frame.items())
    for index, (start_frame, timestamp) in enumerate(clock_steps):
        snapshots = snapshot_at(state, timestamp)
        done = sum(snapshot["status"] == "done" for snapshot in snapshots.values())
        queued = sum(snapshot["status"] == "waiting" for snapshot in snapshots.values())
        obj = base.copy()
        obj.data = base.data.copy()
        obj.name = f"FT06_BakedClock_{index:04d}"
        obj.data.name = obj.name
        obj.data.body = f"TIME STEP {timestamp:05.1f}  /  {state['makespan']:g}   |   DONE {done}/6   |   WAIT {queued}"
        obj["clock_time"] = timestamp
        obj["completed_jobs"] = done
        obj["queued_jobs"] = queued
        bpy.context.collection.objects.link(obj)
        obj.animation_data_clear()
        for field in ("hide_viewport", "hide_render"):
            setattr(obj, field, True)
            obj.keyframe_insert(data_path=field, frame=scene.frame_start)
            setattr(obj, field, False)
            obj.keyframe_insert(data_path=field, frame=start_frame)
            if index + 1 < len(clock_steps):
                setattr(obj, field, True)
                obj.keyframe_insert(data_path=field, frame=clock_steps[index + 1][0])
        constant_animation(obj)
    scene["ft06_baked_clock_steps"] = len(clock_steps)


def apply_state(state, source_path, bake=True):
    """Update the pilot only, then bake motion so no auto-execution is required."""
    global _STATE
    scene = bpy.context.scene
    if scene.get("ft06_mode") != "ft06":
        raise ValueError("Refresh must run inside the separate FT06 pilot scene")
    _STATE = state
    scene["ft06_scenario_id"] = state["scenario_id"]
    scene["ft06_run_id"] = state["run_id"]
    scene["ft06_policy"] = state["policy"]
    scene["ft06_makespan"] = float(state["makespan"])
    scene["ft06_source_path"] = "//" + Path(source_path).name
    scene["ft06_time_unit"] = state["time_unit"]
    scene.frame_start = 1
    scene.frame_end = int(math.ceil(state["makespan"] * scene["ft06_frames_per_unit"])) + 1
    if scene.frame_end > 30000:
        raise ValueError("FT06 replay would exceed 30,000 frames")
    for machine, stats in state["machines"].items():
        obj = bpy.data.objects[f"FT06_Machine_{machine}"]
        obj["capacity"] = stats["capacity"]
        obj["utilization"] = float(stats["utilization"])
        obj["max_queue"] = stats["max_queue"]
        bpy.data.objects[f"FT06_Label_{machine}"].data.body = (
            f"{machine}  |  {stats['capacity']} SLOT{'S' if stats['capacity'] != 1 else ''}")
        bpy.data.objects[f"FT06_Stats_{machine}"].data.body = (
            f"UTIL {stats['utilization'] * 100:.1f}%   /   QUEUE MAX {stats['max_queue']}")
    bpy.data.objects["FT06_KPI_Makespan"].data.body = f"{state['makespan']:g}"
    bpy.data.objects["FT06_KPI_Policy"].data.body = str(state["policy"]).upper()[:22]
    bpy.data.objects["FT06_Run_Identity"].data.body = (
        f"SCENARIO {state['scenario_id'][:12]}   |   RUN {state['run_id'][:12]}")
    handlers = bpy.app.handlers.frame_change_post
    for handler in list(handlers):
        if getattr(handler, "_ft06_tag", None) == _BRIDGE_HANDLER_TAG:
            handlers.remove(handler)
    # Temporarily remove our frame handler while inserting baked animation.
    if bake:
        products = [bpy.data.objects[f"FT06_Product_J{i}"] for i in range(1, 7)]
        for obj in products:
            action = obj.animation_data.action if obj.animation_data else None
            obj.animation_data_clear()
            if action is not None and action.users == 0:
                bpy.data.actions.remove(action)
        for frame in range(scene.frame_start, scene.frame_end + 1):
            timestamp = (frame - 1) / scene["ft06_frames_per_unit"]
            snapshots = snapshot_at(state, timestamp)
            for obj in products:
                obj.location = snapshots[obj["job"]]["position"]
                obj.keyframe_insert(data_path="location", frame=frame)
        # Integer-frame step sampling reflects the declared zero transport time.
        for obj in products:
            constant_animation(obj)
        bake_clock(scene, state)
    handlers.append(update_frame)
    scene.frame_set(min(scene.frame_end, max(1, scene.frame_current)))
    update_frame(scene)
    return {"scenario_id": state["scenario_id"], "run_id": state["run_id"],
            "frames": scene.frame_end, "events": len(state["events"])}


def refresh():
    """Explicit refresh of the local adjacent JSON; never modifies original scene."""
    scene = bpy.context.scene
    source = Path(bpy.path.abspath(scene.get("ft06_source_path", "//active_run.json")))
    state = load_state(source)
    result = apply_state(state, source)
    print("FT06 refresh complete:", result)
    return result


# =========================================================
# EXPLICIT BLENDER TEXT EXECUTION ENTRY POINT
# =========================================================
if __name__ == "__main__":
    refresh()

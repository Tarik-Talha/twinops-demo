"""Recreate the disclosed demo and optionally build the verified Blender scene."""
from pathlib import Path
import argparse
import json
from .model import load_scenario
from .engine import run_scenario
from .export import RUNTIME, atomic_json, export_run, build_blender

# =========================================================
# REPRODUCIBLE SYNTHETIC PILOT COMPARISON
# =========================================================
def main():
    p = argparse.ArgumentParser()
    p.add_argument('--scenario',type=Path)
    p.add_argument('--build-blender',action='store_true')
    args = p.parse_args()
    s = load_scenario(args.scenario)
    results = {policy:run_scenario(s,policy) for policy in ('fifo','optimized')}
    for r in results.values():
        export_run(s,r)
    summary = {'data_kind':s['data_kind'], 'source':s['source'], 'financial_value':None,
               'comparison':{policy:{k:r.get(k) for k in ('run_id','scenario_id','status','makespan','total_tardiness',
                                                         'completed_pieces','first_shift_pieces','operator_minutes',
                                                         'objective_value','objective_bound')}
                             for policy,r in results.items()}}
    if args.build_blender:
        summary['scene'] = build_blender(s,results['optimized'])
    atomic_json(RUNTIME/'comparison.json',summary)
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__ == '__main__':
    main()

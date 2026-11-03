"""Constraint regressions and an exhaustive small-instance optimality oracle."""
import copy
import itertools
import json
import tempfile
import unittest
from pathlib import Path

from .model import alternatives, load_scenario, make_batches, validate_scenario
from .engine import (event_for, fifo_schedule, replay, run_scenario,
                     validate_result, validate_schedule)
from .export import export_run
from .blender_bridge import load_state, snapshot_at

def small():
    s = load_scenario()
    s['days'], s['workers'], s['hoops'] = 1, 1, 18
    s['machines'] = [s['machines'][3]]
    base = s['orders'][3]
    s['orders'] = [dict(base, id='DEMO_A', quantity=18, prep_minutes=1, change_minutes=1, attach_stitches=400, chenille_stitches=750, due=20),
                   dict(base, id='DEMO_B', quantity=18, prep_minutes=1, change_minutes=1, attach_stitches=400, chenille_stitches=250, due=5)]
    return s

# =========================================================
# MEANINGFUL RESOURCE CALENDAR AND MULTIHEAD REGRESSIONS
# =========================================================
class PilotTests(unittest.TestCase):
    def test_heads_are_one_synchronized_batch(self):
        s = small()
        s['orders'] = [dict(s['orders'][0], quantity=37)]
        b = make_batches(s)
        self.assertEqual([x['pieces'] for x in b], [18,18,1])
        r = run_scenario(s)
        self.assertEqual(r['completed_pieces'],37)
        self.assertEqual(r['makespan'],18) # 3 full six-minute cycles, not 37 / (18*SPM).

    def test_partial_batch_duration_is_full_cycle(self):
        s = small()
        batches = make_batches(s)
        m = s['machines'][0]
        self.assertEqual(event_for(s,dict(batches[0],pieces=1),m,0)['end'],event_for(s,batches[0],m,0)['end'])

    def test_tajima_phases_are_contiguous_and_serial(self):
        s = small()
        events = fifo_schedule(s)
        self.assertEqual([p['phase'] for p in events[0]['phases']], ['hoop_prepare','attach_embroidery','chenille_change','chenille'])
        self.assertTrue(all(a['end']==b['start'] for a,b in zip(events[0]['phases'], events[0]['phases'][1:])))
        bad = copy.deepcopy(events)
        bad[1] = event_for(s, make_batches(s)[1], s['machines'][0], 1)
        with self.assertRaises(ValueError): validate_schedule(s,bad)

    def test_machine_eligibility(self):
        s = load_scenario()
        s['orders'][0]['eligible'] = ['M4']
        with self.assertRaises(ValueError): validate_scenario(s)

    def test_head_limit(self):
        s = load_scenario()
        s['orders'][0].update(batch_size=18,eligible=['M1'])
        with self.assertRaises(ValueError): validate_scenario(s)

    def test_release_and_exact_shift_end(self):
        s = small()
        s['days'] = 2
        s['orders'] = [dict(s['orders'][0],release=474,due=1920)]
        r = run_scenario(s)
        self.assertEqual(r['makespan'],480)
        self.assertEqual(snapshot_at(dict(r,scenario=s),480)['completed_pieces'],18)
        s['orders'][0]['release'] = 475
        self.assertEqual(run_scenario(s)['events'][0]['start'],1440)
        self.assertEqual(run_scenario(s,'optimized',2)['events'][0]['start'],1440)

    def test_overnight_crossing_rejected(self):
        s = small()
        b = make_batches(s)
        events = [event_for(s,b[0],s['machines'][0],478),event_for(s,b[1],s['machines'][0],0)]
        with self.assertRaises(ValueError): validate_schedule(s,events)

    def test_too_long_batch_rejected(self):
        s = small()
        s['orders'][0]['chenille_stitches'] = 200000
        with self.assertRaises(ValueError): validate_scenario(s)

    def test_operator_and_hoop_caps_in_both_plans(self):
        s = load_scenario()
        s['workers'],s['hoops'],s['attend_running'] = 1,18,True
        s['orders'] = [dict(s['orders'][0],quantity=15),dict(s['orders'][2],quantity=15)]
        for policy in ('fifo','optimized'):
            r = run_scenario(s,policy,2)
            self.assertTrue(validate_result(s,r))
            ev = sorted(r['events'],key=lambda e:e['start'])
            self.assertGreaterEqual(ev[1]['start'],ev[0]['end'])

    def test_validator_detects_worker_and_hoop_violation(self):
        s = load_scenario()
        s['workers'],s['hoops'] = 1,20
        s['orders'] = [dict(s['orders'][0],quantity=15),dict(s['orders'][2],quantity=15)]
        batches = make_batches(s)
        events = [event_for(s,batches[0],s['machines'][0],0),event_for(s,batches[1],s['machines'][1],0)]
        with self.assertRaises(ValueError): validate_schedule(s,events)
        s['workers'] = 4
        with self.assertRaises(ValueError): validate_schedule(s,events)

    def test_corrupt_counts_identity_phases_and_bounds(self):
        s = small()
        r = run_scenario(s,'optimized',2)
        for field,value in [('completed_pieces',999),('scenario_id','wrong'),('objective_bound',999999),('financial_value',100)]:
            bad = copy.deepcopy(r)
            bad[field] = value
            with self.assertRaises(ValueError): validate_result(s,bad)
        bad = copy.deepcopy(r['events'])
        bad[0]['phases'][0]['duration'] = True
        with self.assertRaises(ValueError): validate_schedule(s,bad)
        with self.assertRaises(ValueError): validate_schedule(s,r['events'][:-1])

    def test_malformed_inputs(self):
        for field,value in [('workers',True),('hoops',0),('days',1.5),('attend_running',1)]:
            s = small(); s[field]=value
            with self.assertRaises(ValueError): validate_scenario(s)

    def test_cp_sat_matches_exhaustive_permutations(self):
        s = small()
        # Single machine, no release: enumerating both left-justified permutations
        # gives an independent optimum for regular tardiness/makespan objectives.
        scores = []
        for ordering in itertools.permutations(make_batches(s)):
            end, events = 0, []
            for b in ordering:
                e = event_for(s,b,s['machines'][0],end)
                end = e['end']; events.append(e)
            m = validate_schedule(s,events)
            scores.append((m['total_tardiness'],m['makespan']))
        r = run_scenario(s,'optimized',3)
        self.assertEqual(r['status'],'OPTIMAL')
        self.assertEqual((r['total_tardiness'],r['makespan']),min(scores))

    def test_alternative_machine_duration_and_preparation_are_real(self):
        s = load_scenario()
        s['orders'] = [dict(s['orders'][0],quantity=15)]
        r = run_scenario(s,'optimized',2)
        self.assertEqual(r['events'][0]['machine'],'M3')
        self.assertEqual(r['makespan'],56) # 12 preparation + ceil(24000/550)=44.

    def test_no_solution_does_not_invent_output(self):
        s = small()
        s['orders'][0]['quantity'] = 1800
        s['orders'][1]['quantity'] = 180
        # 110 batches x >=4 minutes cannot all fit with the long jobs.
        with self.assertRaises(ValueError): run_scenario(s)

    def test_demo_comparison_and_export_roundtrip(self):
        s = load_scenario()
        a,b = run_scenario(s),run_scenario(s,'optimized',5)
        self.assertEqual(a['completed_pieces'],b['completed_pieces'])
        self.assertLessEqual((b['total_tardiness'],b['makespan']),(a['total_tardiness'],a['makespan']))
        self.assertIsNone(b['financial_value'])
        scratch = Path(__file__).resolve().parents[1] / '.test-artifacts'
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp:
            folder = export_run(s,b,temp)
            state = load_state(folder/'active_run.json')
            self.assertEqual(state['run_id'],b['run_id'])
            self.assertEqual(snapshot_at(state,b['makespan'])['completed_pieces'],261)
            self.assertTrue((folder/'embroidery.usda').read_text().startswith('#usda 1.0'))

if __name__ == '__main__':
    unittest.main()

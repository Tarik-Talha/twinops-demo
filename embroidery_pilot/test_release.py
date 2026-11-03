"""Portable-release checks for separate visitors and optional rendering."""
from pathlib import Path
import json
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from embroidery_pilot.export import RUNTIME

APP = Path(__file__).with_name('app.py')
ROOT = APP.parent


# =========================================================
# INDEPENDENT BROWSER SESSIONS AND OPTIONAL BLENDER DEPENDENCY
# =========================================================
class ReleaseTests(unittest.TestCase):
    def test_two_visitors_have_separate_artifacts_and_plan_selections(self):
        first = AppTest.from_file(str(APP),default_timeout=30).run()
        second = AppTest.from_file(str(APP),default_timeout=30).run()
        self.assertFalse(first.exception)
        self.assertFalse(second.exception)
        first_id = first.session_state['emb_session_id']
        second_id = second.session_state['emb_session_id']
        self.assertNotEqual(first_id,second_id)
        run = first.session_state['emb_fifo']['run_id']
        first_file = RUNTIME/first_id/'runs'/run/'active_run.json'
        second_file = RUNTIME/second_id/'runs'/run/'active_run.json'
        self.assertTrue(first_file.is_file() and second_file.is_file())
        before = second_file.read_bytes()
        next(b for b in first.button if b.label=='CP-SAT planını hesapla').click().run()
        self.assertFalse(first.exception)
        self.assertEqual(first.radio[0].value,'CP-SAT planı')
        self.assertEqual(second.radio[0].value,'FIFO referans')
        self.assertIsNone(second.session_state['emb_optimized'])
        self.assertEqual(second_file.read_bytes(),before)

    def test_unavailable_blender_does_not_break_planning_or_exports(self):
        with patch('embroidery_pilot.export.find_blender',side_effect=FileNotFoundError('not installed')):
            app = AppTest.from_file(str(APP),default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            build = next(b for b in app.button if b.label=='Bu plan için Blender sahnesi oluştur')
            self.assertTrue(build.disabled)
            next(b for b in app.button if b.label=='CP-SAT planını hesapla').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[2].value,'0 dk')
            run = app.session_state['emb_optimized']['run_id']
            folder = RUNTIME/app.session_state['emb_session_id']/'runs'/run
            payload = json.loads((folder/'active_run.json').read_text(encoding='utf-8'))
            self.assertEqual(payload['completed_pieces'],261)
            self.assertTrue((folder/'embroidery.usda').is_file())


if __name__=='__main__':
    unittest.main()

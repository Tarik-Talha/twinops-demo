"""Streamlit form, stale comparison and active-plan regressions."""
from pathlib import Path
import unittest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).with_name('app.py')

# =========================================================
# STREAMLIT EXPLICIT APPLY AND SAME-SCENARIO COMPARISON
# =========================================================
class UITests(unittest.TestCase):
    def test_initial_fifo_and_optimization_are_consistent(self):
        app = AppTest.from_file(str(APP)).run(timeout=30)
        self.assertEqual(len(app.exception),0)
        next(b for b in app.button if b.label=='CP-SAT planını hesapla').click().run(timeout=30)
        self.assertEqual(len(app.exception),0)
        s = app.session_state
        self.assertEqual(s['emb_fifo']['scenario_id'],s['emb_optimized']['scenario_id'])
        self.assertEqual(s['emb_optimized']['total_tardiness'],0)
        self.assertEqual(app.radio[0].value,'CP-SAT planı')
        app.radio[0].set_value('FIFO referans').run(timeout=30)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.metric[2].value,'234 dk')

    def test_applied_changes_clear_old_optimization(self):
        app = AppTest.from_file(str(APP)).run(timeout=30)
        next(b for b in app.button if b.label=='CP-SAT planını hesapla').click().run(timeout=30)
        before = app.session_state['emb_fifo']['scenario_id']
        next(n for n in app.number_input if n.label=='Operatör havuzu').set_value(1)
        next(b for b in app.button if b.label=='Değişiklikleri uygula ve FIFO çalıştır').click().run(timeout=30)
        self.assertEqual(len(app.exception),0)
        self.assertIsNone(app.session_state['emb_optimized'])
        self.assertNotEqual(before, app.session_state['emb_fifo']['scenario_id'])
        self.assertEqual(app.session_state['emb_scenario']['workers'],1)

    def test_invalid_form_retains_known_valid_result(self):
        app = AppTest.from_file(str(APP)).run(timeout=30)
        before = app.session_state['emb_fifo']['run_id']
        next(n for n in app.number_input if n.label=='Kasnak stoku (adet)').set_value(1)
        next(b for b in app.button if b.label=='Değişiklikleri uygula ve FIFO çalıştır').click().run(timeout=30)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(before,app.session_state['emb_fifo']['run_id'])
        self.assertTrue(any('uygulanmadı' in e.value for e in app.error))

if __name__ == '__main__':
    unittest.main()

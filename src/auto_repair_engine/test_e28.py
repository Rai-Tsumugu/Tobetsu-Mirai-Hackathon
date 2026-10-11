import unittest
from .contract import approved_common_scenario_fixture
from .e07 import run as canonical
from .e28 import ENGINE_ID, run

class E28Tests(unittest.TestCase):
    def test_recomputes_and_accepts_matching_version_pinned_proposal(self):
        s=approved_common_scenario_fixture(); expected=canonical(s)
        result=run(s, {'rule_version':s['rule_version'],'client_proposal':{'rule_version':s['rule_version'],'labor':expected['labor']}})
        self.assertEqual(result['engine_id'],ENGINE_ID); self.assertEqual(result['labor'],expected['labor'])
        self.assertTrue(result['trace'][0]['client_proposal_checked'])
    def test_tampered_proposal_and_old_version_stop(self):
        s=approved_common_scenario_fixture()
        for pack in ({'rule_version':s['rule_version'],'client_proposal':{'rule_version':s['rule_version'],'labor':{'person_hours':{'typical':999}}}}, {'rule_version':'old'}):
            r=run(s,pack); self.assertEqual(r['status'],'missing-required')
            self.assertEqual(r['labor']['person_hours'],{'low':None,'typical':None,'high':None})

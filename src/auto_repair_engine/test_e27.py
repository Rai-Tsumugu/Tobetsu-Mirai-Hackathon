import copy, unittest
from .contract import approved_common_scenario_fixture, common_scenario_fixture
from .e07 import run as canonical
from .e27 import ENGINE_ID, run

class E27Tests(unittest.TestCase):
    def test_server_bridge_matches_browser_ranges_and_does_not_mutate(self):
        s=approved_common_scenario_fixture(); before=copy.deepcopy(s); expected=canonical(s)
        r=run(s, {'client_proposal': {'rule_version': s['rule_version'], 'labor': expected['labor']}})
        self.assertEqual(s,before); self.assertEqual(r['engine_id'],ENGINE_ID); self.assertEqual(r['status'],'proposed')
        self.assertEqual(r['labor']['person_hours'], {'low':1.88,'typical':2.13,'high':2.38})
        self.assertTrue(r['trace'][0]['client_proposal_checked'])
    def test_tampered_client_result_and_version_mismatch_stop(self):
        s=approved_common_scenario_fixture()
        bad=run(s, {'client_proposal': {'rule_version':s['rule_version'],'labor':{'person_hours':{'typical':999}}}})
        self.assertEqual(bad['status'],'missing-required'); self.assertIn('parity_validation_failed',bad['labor']['unknowns'][0])
        mismatch=run(s, {'rule_version':'wrong'})
        self.assertEqual(mismatch['status'],'missing-required')
    def test_explicit_nonobject_rule_pack_stops(self):
        result=run(approved_common_scenario_fixture(), 'invalid')
        self.assertEqual(result['status'],'missing-required')
        self.assertIn('rule_pack:object_required',result['labor']['unknowns'])
    def test_unconfirmed_rotor_stays_blocked(self):
        r=run(common_scenario_fixture()); self.assertEqual(r['status'],'missing-required')
        self.assertTrue(any('rotor' in x for x in r['labor']['unknowns']))

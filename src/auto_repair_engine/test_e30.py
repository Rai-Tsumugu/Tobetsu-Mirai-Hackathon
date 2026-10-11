import copy, unittest
from .contract import approved_common_scenario_fixture
from .e30 import ENGINE_ID, run

class E30Tests(unittest.TestCase):
    def test_missing_basis_uses_fictional_approved_process_baseline(self):
        s=approved_common_scenario_fixture(); before=copy.deepcopy(s); r=run(s)
        self.assertEqual(s,before); self.assertEqual(r['status'],'proposed'); self.assertEqual(r['engine_id'],ENGINE_ID)
        self.assertEqual(r['labor']['person_hours'],{'low':1.88,'typical':2.13,'high':2.38})
        self.assertEqual(r['trace'][0]['mode'],'approved_process_fallback')
    def test_manual_person_hour_basis_changes_labor(self):
        s=approved_common_scenario_fixture(); pack={'engine_id':ENGINE_ID,'rule_version':s['rule_version'],'manual_basis':{'value':2.0,'unit':'person_hour','definition':'Fictional service time excluding included carry.','source':'fictional_manual_entry','permission_status':'fictional_only'}}
        r=run(s,pack); self.assertEqual(r['status'],'proposed'); self.assertEqual(r['labor']['person_hours'],{'low':2.18,'typical':2.43,'high':2.68})
    def test_explicit_empty_pack_and_wrong_version_stop(self):
        s=approved_common_scenario_fixture()
        self.assertEqual(run(s, {}).get('status'),'missing-required')
        p={'rule_version':'stale','manual_basis':{'value':2,'unit':'person_hour','definition':'manual','source':'source','permission_status':'fictional_only'}}
        self.assertIn('version_mismatch', ' '.join(run(s,p)['labor']['unknowns']))
    def test_points_or_unconfirmed_permissions_stop(self):
        s=approved_common_scenario_fixture()
        for unit,permission in [('points','fictional_only'),('person_hour','unconfirmed')]:
            p={'engine_id':ENGINE_ID,'rule_version':s['rule_version'],'manual_basis':{'value':2,'unit':unit,'definition':'manual','source':'source','permission_status':permission}}
            r=run(s,p); self.assertEqual(r['status'],'missing-required')
            self.assertTrue(any('unit' in x or 'permission' in x for x in r['labor']['unknowns']))

import unittest
from copy import deepcopy
from .contract import approved_common_scenario_fixture, common_scenario_fixture
from .e21 import RULE_VERSION as E21_VERSION
from .integrated import ENGINE_ID, run

class IntegratedTests(unittest.TestCase):
    def test_approved_fixture_composes_schema_validation_rules_and_trace(self):
        s=approved_common_scenario_fixture(); before=deepcopy(s); r=run(s)
        self.assertEqual(s,before); self.assertEqual(r['engine_id'],ENGINE_ID); self.assertEqual(r['status'],'proposed')
        self.assertEqual(r['labor']['person_hours'],{'low':1.88,'typical':2.13,'high':2.38})
        self.assertEqual(r['labor']['elapsed_hours'],{'low':2.53,'typical':2.78,'high':3.03})
        stages=[x['stage'] for x in r['trace']]
        self.assertIn('schema_and_pipeline_validation',stages);self.assertIn('approved_rules',stages);self.assertIn('e18_applied_row_trace_tree',stages)
    def test_missing_schema_condition_stops_with_questions(self):
        r=run(common_scenario_fixture());self.assertEqual(r['status'],'missing-required');self.assertEqual(r['labor']['person_hours'],{'low':None,'typical':None,'high':None})
        self.assertIn('rotor_relevance:schema_confirmation_required',r['labor']['unknowns'])
    def test_wait_unknown_retains_person_hours_and_nulls_elapsed(self):
        s=approved_common_scenario_fixture(); next(x for x in s['operations'] if x['operation_id']=='snow_melt')['elapsed_hours']=None
        r=run(s);self.assertEqual(r['status'],'partial');self.assertEqual(r['labor']['person_hours'],{'low':1.88,'typical':2.13,'high':2.38})
        self.assertEqual(r['labor']['elapsed_hours'],{'low':None,'typical':None,'high':None})
    def test_evidence_requires_approval_and_changes_labor_when_approved(self):
        s=approved_common_scenario_fixture(); base=run(s)
        item={'operation_id':'inspection_extra','hours':0.1,'duration_hours':0.1,'person_count':1,'unit':'person_hour','source':'fictional_photo_note','old_value':None}
        item['approval']={'actor':'fictional_owner','reason':'approved inspection evidence','old_value':None,
            'new_value':{'hours':0.1,'unit':'person_hour','source':'fictional_photo_note'},'rule_version':E21_VERSION}
        r=run(s,{'evidence_additions':[item]});self.assertEqual(r['labor']['person_hours']['typical'],base['labor']['person_hours']['typical']+0.1)
        self.assertEqual(r['labor']['elapsed_hours']['typical'],base['labor']['elapsed_hours']['typical']+0.1)
        item['approval']['actor']=''; blocked=run(s,{'evidence_additions':[item]});self.assertEqual(blocked['status'],'missing-required')
        item['approval']['actor']='fictional_owner'; item.pop('duration_hours'); item.pop('person_count'); partial=run(s,{'evidence_additions':[item]})
        self.assertEqual(partial['status'],'partial'); self.assertEqual(partial['labor']['elapsed_hours'],{'low':None,'typical':None,'high':None})
    def test_client_tamper_and_wrong_rule_version_stop(self):
        s=approved_common_scenario_fixture();r=run(s,{'client_proposal':{'rule_version':s['rule_version'],'labor':{'person_hours':{'low':0}}}})
        self.assertEqual(r['status'],'missing-required')
        self.assertEqual(run(s,{'rule_version':'stale'})['status'],'missing-required')

    def test_non_object_client_labor_stops_without_exception(self):
        s=approved_common_scenario_fixture()
        for value in ('bad', [1], 9, True):
            with self.subTest(value=value):
                r=run(s,{'client_proposal':{'rule_version':s['rule_version'],'labor':value}})
                self.assertEqual(r['status'],'missing-required')
                self.assertIn('client_proposal:server_recomputation_mismatch',r['labor']['unknowns'])

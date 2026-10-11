"""Verify the selected ideas compose into one coherent, versioned workflow."""
from copy import deepcopy
import unittest
from fastapi.testclient import TestClient

from . import api
from .fixtures import demo_inputs
from .store import QuoteStore
from .workflow import preview


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.original_store = api.store
        api.store = QuoteStore()
        self.client = TestClient(api.app)

    def tearDown(self):
        self.client.close()
        api.store.close()
        api.store = self.original_store

    def post(self, path, body):
        response = self.client.post('/api'+path, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_preview_has_one_snapshot_and_no_automatic_selection_or_save(self):
        inputs = demo_inputs()
        original = deepcopy(inputs)
        result = preview(inputs)
        self.assertEqual(inputs, original)
        self.assertEqual(result['next_action'], 'select_band')
        self.assertTrue(result['can_confirm'])
        self.assertIsNone(result['quote']['selected_band'])
        self.assertEqual(result['summary']['amount'], result['quote']['total'])
        for comparison in result['band_comparison']:
            self.assertEqual(comparison['amount'], result['quote']['total'][comparison['band']])
        self.assertEqual(api.store.list_quotes(), [])

    def test_missing_prices_and_unapproved_markup_produce_questions_not_zero(self):
        for mutate in (lambda inputs: inputs['items'][0].update(unit_price=None),
                       lambda inputs: inputs['items'][0].update(price_type='仕入', markup=None)):
            inputs = demo_inputs()
            mutate(inputs)
            result = self.post('/workflow/preview', {'inputs':inputs})
            self.assertEqual(result['next_action'], 'resolve_conditions')
            self.assertFalse(result['can_confirm'])
            self.assertFalse(result['questions']['can_calculate'])
            self.assertTrue(result['questions']['questions'])
            self.assertIsNone(result['summary']['amount'])
            self.assertEqual(result['band_comparison'], [])
            self.assertTrue(all(amount is None for amount in result['quote']['total'].values()))

    def test_manual_final_amount_is_consistent_across_every_customer_view(self):
        inputs = self.client.get('/api/demo').json()
        preview_result = self.post('/workflow/preview', {'inputs':inputs})
        quote = preview_result['quote']
        confirmed = self.post('/quotes/confirm', {
            'inputs':inputs, 'quote_id':quote['quote_id'], 'quote_version':1,
            'selected_band':'typical', 'confirmed_by':'operator-demo-01',
            'final_amount':15000, 'override_reason':'架空:担当者調整',
        })
        self.post('/communications', {
            'quote_id':quote['quote_id'], 'quote_version':1, 'selected_band':'typical',
            'operator':'operator-demo-01', 'condition_note':'架空:追加時に再連絡',
            'customer_ref':inputs['customer_ref'], 'vehicle_ref':inputs['vehicle_ref'],
        })
        result = self.client.get('/api/workflow/'+quote['quote_id']+'?quote_version=1').json()
        self.assertEqual(result['next_action'], 'review_history')
        self.assertEqual(result['quote'], confirmed)
        self.assertEqual(result['summary']['amount'],15000)
        self.assertEqual(result['document']['final_amount'],15000)
        self.assertEqual(result['communications'][0]['communicated_amount'],15000)
        self.assertEqual(result['document']['selected_total'],14300)
        for patch in ({'selected_band':'low'}, {'communicated_amount':100}):
            response = self.client.post('/api/communications', json={
                'quote_id':quote['quote_id'], 'quote_version':1, 'selected_band':'typical',
                'operator':'operator-demo-01', 'condition_note':'架空:追加時に再連絡',
                'customer_ref':inputs['customer_ref'], 'vehicle_ref':inputs['vehicle_ref'], **patch,
            })
            self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(len(api.store.list_communications(quote['quote_id'])),1)

    def test_revision_keeps_parent_and_old_snapshot_and_filters_version_events(self):
        inputs = self.client.get('/api/demo').json()
        quote_id = inputs['quote_id']
        self.post('/quotes/confirm', {'inputs':inputs,'quote_id':quote_id,'quote_version':1,
                  'selected_band':'low','confirmed_by':'operator-demo-01'})
        self.post('/communications', {'quote_id':quote_id,'quote_version':1,'selected_band':'low',
            'operator':'operator-demo-01','condition_note':'架空:旧版',
            'customer_ref':inputs['customer_ref'],'vehicle_ref':inputs['vehicle_ref']})
        changed = deepcopy(inputs)
        changed['items'][0]['unit_price'] = 2000
        revised = self.post('/quotes/revise', {'inputs':changed,'quote_id':quote_id,'from_version':1})
        saved = self.post('/quotes/confirm', {'inputs':revised['metadata']['input_snapshot'],
            'quote_id':quote_id,'quote_version':2,'selected_band':'high','confirmed_by':'operator-demo-01'})
        self.assertEqual(saved['parent_version'],1)
        latest = self.client.get('/api/workflow/'+quote_id).json()
        old = self.client.get('/api/workflow/'+quote_id+'?quote_version=1').json()
        self.assertEqual(latest['communications'],[])
        self.assertEqual(latest['document']['final_amount'],24200)
        self.assertEqual(old['document']['final_amount'],9900)
        self.assertEqual(len(old['communications']),1)

    def test_invalid_communication_rolls_back_new_proposal(self):
        inputs = self.client.get('/api/demo').json()
        response = self.client.post('/api/communications',json={
            'inputs':inputs,'quote_id':inputs['quote_id'],'quote_version':1,'selected_band':'low',
            'operator':'operator-demo-01','condition_note':'連絡先 090-1234-5678',
            'customer_ref':inputs['customer_ref'],'vehicle_ref':inputs['vehicle_ref'],
        })
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(api.store.list_quotes(),[])

    def test_invalid_change_rolls_back_new_version(self):
        inputs = self.client.get('/api/demo').json()
        quote_id = inputs['quote_id']
        self.post('/quotes/confirm', {'inputs':inputs,'quote_id':quote_id,'quote_version':1,
                  'selected_band':'low','confirmed_by':'operator-demo-01'})
        response = self.client.post('/api/changes',json={
            'inputs':inputs,'quote_id':quote_id,'from_version':1,'to_version':2,
            'trigger_ref':'OBS-DEMO-01','operator':'operator-demo-01',
            'condition_note':'架空:未記録の了承','ack_status':'accepted',
        })
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(len(api.store.list_quotes()),1)

    def test_mismatched_rate_evidence_blocks_preview(self):
        inputs = demo_inputs()
        inputs['labor_rate']['basis'][0]['value'] = 10
        result = preview(inputs)
        self.assertFalse(result['can_confirm'])
        self.assertIsNone(result['summary']['amount'])

    def test_malformed_item_and_labor_shapes_are_confirmation_blocks(self):
        for patch in ({'items':[None]}, {'items':None}, {'labor':None}, {'labor_rate':[]}):
            inputs = demo_inputs()
            inputs.update(patch)
            result = self.post('/workflow/preview', {'inputs':inputs})
            self.assertFalse(result['can_confirm'])
            self.assertIsNone(result['summary']['amount'])

    def test_mixed_rate_units_cannot_bypass_the_shared_unit_gate(self):
        inputs = demo_inputs()
        inputs['labor_rate']['basis'].append({'label':'架空:年間家賃','value':100000,'unit':'円/年'})
        self.assertFalse(preview(inputs)['can_confirm'])

"""Exercise the real HTTP boundary with isolated SQLite state."""
import unittest
from fastapi.testclient import TestClient
from . import api
from .store import QuoteStore

class ApiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.original_store = api.store
        api.store = QuoteStore()
        self.client = TestClient(api.app)

    def tearDown(self):
        api.store.close()
        api.store = self.original_store
        self.client.close()

    def post(self, path, body):
        response = self.client.post('/api'+path, json=body)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_calculation_confirm_communication_and_document_use_same_amount(self):
        inputs = self.client.get('/api/demo').json()
        self.assertTrue(self.client.get('/api/jobs?query=パッド').json())
        quote = self.post('/quotes/calculate', inputs)
        body = {'inputs':inputs,'quote_id':quote['quote_id'],'quote_version':1,
                'selected_band':'typical','confirmed_by':'operator-demo-01',
                'final_amount':15000,'override_reason':'架空:担当者調整'}
        confirmed = self.post('/quotes/confirm', body)
        self.assertEqual(confirmed['final_amount'],15000)
        self.assertEqual(confirmed['total']['typical'],14300)
        record = self.post('/communications', {'quote_id':quote['quote_id'],'quote_version':1,
            'selected_band':'typical','operator':'operator-demo-01','condition_note':'架空:現車確認後に追加連絡',
            'customer_ref':'C-DEMO-01','vehicle_ref':'V-DEMO-01'})
        self.assertEqual(record['communicated_amount'],15000)
        ledger = self.client.get('/api/quotes/'+quote['quote_id']+'/communications').json()
        self.assertEqual(ledger[0]['communicated_amount'],15000)
        document_response = self.client.get('/api/quotes/'+quote['quote_id']+'/document')
        self.assertEqual(document_response.status_code,200,document_response.text)
        document = document_response.json()
        self.assertEqual(document['final_amount'],15000)
        self.assertEqual(document['selected_band'],'typical')

    def test_communicated_proposal_is_immutable_and_confirmation_creates_next_version(self):
        inputs = self.client.get('/api/demo').json()
        quote = self.post('/quotes/calculate', inputs)
        self.post('/communications', {'quote_id':quote['quote_id'],'quote_version':1,'inputs':inputs,
            'selected_band':'low','operator':'operator-demo-01','condition_note':'架空:概算の前提',
            'customer_ref':'C-DEMO-01','vehicle_ref':'V-DEMO-01'})
        confirmed = self.post('/quotes/confirm',{'inputs':inputs,'quote_id':quote['quote_id'],
            'quote_version':1,'selected_band':'high','confirmed_by':'operator-demo-01'})
        self.assertEqual(confirmed['quote_version'],2)
        self.assertEqual(api.store.get_quote(quote['quote_id'],1)['status'],'proposed')
        self.assertEqual(api.store.list_communications(quote['quote_id'])[0]['communicated_amount'],9900)

    def test_blocked_missing_input_cannot_be_confirmed(self):
        inputs = self.client.get('/api/demo').json()
        inputs['items'][0]['unit_price'] = None
        quote = self.post('/quotes/calculate', inputs)
        self.assertEqual(quote['status'],'blocked')
        response = self.client.post('/api/quotes/confirm',json={'inputs':inputs,'quote_id':quote['quote_id'],
            'quote_version':1,'selected_band':'typical','confirmed_by':'operator-demo-01'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(api.store.list_quotes(),[])

    def test_draft_and_preset_are_real_http_paths(self):
        inputs = self.post('/presets/load',{'preset_id':'PRESET-DEMO-01'})
        self.post('/drafts/save',{'draft_id':'D-DEMO-01','inputs':inputs,'step':2})
        resumed = self.post('/drafts/resume',{'draft_id':'D-DEMO-01','resume_mode':'snapshot'})
        self.assertEqual(resumed['inputs'],inputs)
        quick = self.post('/quotes/quick',{'preset_id':'PRESET-DEMO-01','vehicle_ref':'V-DEMO-01'})
        self.assertTrue(quick['shortcut_available'])
        self.assertEqual(quick['quote']['status'],'proposed')

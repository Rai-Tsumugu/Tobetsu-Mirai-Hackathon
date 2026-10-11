"""FastAPI Simulator adapter. Quotes are always recalculated on the server."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import os
import sqlite3
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from .fixtures import demo_inputs, demo_presets
from .pipeline import calculate, json_ready
from .store import QuoteStore

app = FastAPI(title='Auto Repair Quote Simulator')
store = QuoteStore(os.environ.get('AUTO_REPAIR_QUOTE_DB', str(Path(__file__).with_name('quotes.sqlite3'))))

@app.post('/api/workflow/preview')
def workflow_preview(body: dict):
    from .workflow import preview
    return preview(body['inputs'])

@app.get('/api/workflow/{quote_id}')
def workflow_snapshot(quote_id: str, quote_version: int | None = None):
    from .workflow import saved_workflow
    return saved_workflow(store, quote_id, quote_version)

@app.exception_handler(ValueError)
async def validation_error(request, error):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={'detail':str(error)})

@app.exception_handler(sqlite3.IntegrityError)
async def duplicate_error(request, error):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={'detail':'既存の見積版またはイベントIDです。上書きせず新しい版を作成してください。'})

@app.exception_handler(KeyError)
async def missing_key(request, error):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={'detail':'必須項目がありません: '+str(error)})

@app.post('/api/forms/state')
def form_state(body: dict):
    from .p13 import form_state
    return form_state(body['inputs'], body.get('step', 0), body.get('quote'))

@app.post('/api/questions')
def questions(body: dict):
    from .p22 import question_guide
    return question_guide(body['inputs'], body.get('required_fields'))

@app.post('/api/prices/compare')
def prices(body: dict):
    from .p24 import price_comparison
    return price_comparison(body['history'], body['item_id'])

@app.post('/api/quotes/combine')
def combine(body: dict):
    from .p25 import combine_quotes
    return combine_quotes(body['quotes'], body.get('accepted_dedup_refs'), body.get('approved_by'))

@app.post('/api/changes')
def change_event(body: dict):
    with store.transaction():
        from .p29 import record_change
        try:
            store.get_quote(body['quote_id'], body['to_version'])
        except ValueError:
            inputs = deepcopy(body['inputs'])
            inputs.update(quote_id=body['quote_id'], quote_version=body['to_version'])
            proposed = calculate(inputs)
            if proposed['status'] == 'blocked':
                raise ValueError('blocked changes cannot be recorded as a calculated quote')
            proposed['parent_version'] = body['from_version']
            store.save_quote(proposed)
        return record_change(store, body)


@app.get('/api/quotes/{quote_id}/changes')
def changes(quote_id: str):
    return store.list_change_events(quote_id)

@app.get('/api/demo')
def get_demo():
    result = demo_inputs()
    result.update(quote_id='Q-'+uuid4().hex[:10], customer_ref='C-DEMO-01', vehicle_ref='V-DEMO-01', job_ref='JOB-DEMO-01')
    return result

@app.get('/api/jobs')
def jobs(query: str = ''):
    from .p20 import search_jobs
    return search_jobs(demo_presets(), query)

@app.post('/api/presets/load')
def load_preset(body: dict):
    from .p19 import load_preset
    result = load_preset(demo_presets(), body['preset_id'])
    result['inputs']['quote_id'] = 'Q-'+uuid4().hex[:10]
    return result['inputs']

@app.post('/api/quotes/quick')
def quick_quote(body: dict):
    from .p16 import quick_quote
    return quick_quote(demo_presets(), body['preset_id'], body.get('vehicle_ref'))

@app.post('/api/quotes/calculate')
def calculate_quote(body: dict):
    return calculate(body)

@app.post('/api/quotes/confirm')
def confirm_quote(body: dict):
    with store.transaction():
        from .p14 import confirm_quote
        from .p27 import save_snapshot
        inputs = deepcopy(body['inputs'])
        inputs.update(quote_id=body['quote_id'], quote_version=body['quote_version'])
        try:
            previous = store.get_quote(body['quote_id'], body['quote_version'])
        except ValueError:
            previous = None
        if previous is not None:
            if previous.get('status') == 'confirmed':
                raise ValueError('already confirmed: create a new version first')
            inputs['parent_version'] = body['quote_version']
            inputs['quote_version'] = store.get_quote(body['quote_id'])['quote_version'] + 1
        quote = calculate(inputs)
        quote = confirm_quote(quote, body['selected_band'], body['confirmed_by'], body.get('final_amount'), body.get('override_reason'))
        return save_snapshot(store, quote)


@app.get('/api/quotes')
def quotes(customer_ref: str | None = None, vehicle_ref: str | None = None):
    from .p21 import search_quotes
    return search_quotes(store, customer_ref, vehicle_ref)

@app.post('/api/quotes/revise')
def revise_quote(body: dict):
    from .p15 import revise_quote
    inputs = deepcopy(body['inputs'])
    inputs['quote_id'] = body['quote_id']
    return revise_quote(store, body['quote_id'], body['from_version'], inputs, calculate)

@app.post('/api/drafts/save')
def save_draft(body: dict):
    from .p17 import save_draft
    return save_draft(store, body['draft_id'], body['inputs'], body.get('step', 0))

@app.post('/api/drafts/resume')
def resume_draft(body: dict):
    from .p17 import resume_draft
    return resume_draft(store, body['draft_id'], body['resume_mode'], demo_inputs())

@app.post('/api/communications')
def communicate(body: dict):
    with store.transaction():
        from .p18 import record_communication
        # A proposed quote must have a persisted version before the FK event exists.
        try:
            quote = store.get_quote(body['quote_id'], body['quote_version'])
        except ValueError:
            inputs = deepcopy(body['inputs'])
            inputs.update(quote_id=body['quote_id'], quote_version=body['quote_version'])
            quote = calculate(inputs)
            if quote['status'] == 'blocked':
                raise ValueError('blocked quote cannot be communicated')
            store.save_quote(json_ready(quote))
        return record_communication(store, quote, body)


@app.get('/api/quotes/{quote_id}/communications')
def communication_ledger(quote_id: str):
    from .p28 import communication_ledger
    return communication_ledger(store, quote_id)

@app.post('/api/quotes/summary')
def summary(body: dict):
    from .p12 import customer_summary
    return customer_summary(body['quote'], body.get('selected_band'))

@app.post('/api/quotes/compare-bands')
def compare_bands(body: dict):
    from .p23 import compare_bands
    return compare_bands(body['quote'])

@app.post('/api/quotes/diff')
def quote_diff(body: dict):
    from .p26 import compare_versions
    return compare_versions(body['from_quote'], body['to_quote'])

@app.get('/api/quotes/{quote_id}/document')
def document(quote_id: str, quote_version: int | None = None):
    from .p30 import document_payload
    return document_payload(store.get_quote(quote_id, quote_version))

@app.get('/api/quotes/{quote_id}')
def quote_version(quote_id: str, quote_version: int | None = None):
    return store.get_quote(quote_id, quote_version)

@app.get('/api/teams')
def team_progress():
    import json
    return json.loads(Path(__file__).with_name('teams.json').read_text())

web_path = Path(__file__).with_name('dist')
if web_path.exists():
    app.mount('/', StaticFiles(directory=web_path, html=True), name='web')

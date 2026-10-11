"""Generate golden outputs for the TypeScript port of src/auto_repair_items.

Run from the repository root (or the worktree root):

    PYTHONPATH=src python3 src/web-app/tests/systems/items/golden/generate.py [m05 integrated ...]

Reads scenarios/<name>.json and writes <name>.json (the expected result of each step, in order) next to this file.
The TypeScript test reads the inputs from scenarios/<name>.json itself, so
Decimal inputs keep their exact JSON spelling. With no
arguments every scenario file is processed. The original Python code is only
imported and executed; nothing under src/auto_repair_items is modified.

Scenario format (shared with golden.test.ts):

    {"scenarios": [{"name": "...", "steps": [STEP, ...]}]}

Each scenario uses a fresh in-memory Store. STEP is one of

    {"op": "seed_demo"}
    {"op": "specs"}                      # registry.specifications()
    {"op": "run", "module": "M05" | "INTEGRATED", "payload": {...}}
    {"op": "add_price", "item": {...}, "confirmed_by": "...", "kwargs": {...}}
    {"op": "put", "namespace": "...", "record": {...}, "record_id": "..."}
    {"op": "records", "namespace": "...", "record_id": "..."}
    {"op": "latest", "namespace": "...", "record_id": "..."}
    {"op": "price_versions", "item_id": ..., "price_type": ..., "supplier_id": ...}
    {"op": "get_price", "item_id": "...", "price_type": "...", "kwargs": {...}}

Any string "$ref:<step>.<path>" inside a step is replaced by a value from an
earlier step's result, e.g. "$ref:0.staged_rows.0.record_id". Numbers with a
fraction or exponent are read as Decimal (like the HTTP server's
parse_float=Decimal). Every step runs under localcontext(prec=120), which is the
context app.py uses around module.run.
"""
from decimal import Decimal, localcontext
import importlib
import json
from pathlib import Path
import sys

from auto_repair_items.core import Store, ValidationError, dumps, seed_demo

HERE = Path(__file__).resolve().parent


def module_for(name):
    if name == 'INTEGRATED':
        return importlib.import_module('auto_repair_items.integrated')
    return importlib.import_module(f'auto_repair_items.{name.lower()}')


def resolve(value, results):
    if isinstance(value, str) and value.startswith('$ref:'):
        parts = value[5:].split('.')
        current = results[int(parts[0])]
        for part in parts[1:]:
            current = current[int(part)] if isinstance(current, list) else current[part]
        return current
    if isinstance(value, list):
        return [resolve(entry, results) for entry in value]
    if isinstance(value, dict):
        return {key: resolve(entry, results) for key, entry in value.items()}
    return value


def execute(step, store):
    op = step['op']
    if op == 'specs':
        return importlib.import_module('auto_repair_items.registry').specifications()
    if op == 'seed_demo':
        seed_demo(store)
        return None
    if op == 'run':
        return module_for(step['module']).run(step['payload'], store)
    if op == 'add_price':
        return store.add_price(step['item'], step['confirmed_by'], **step.get('kwargs', {}))
    if op == 'put':
        return store.put(step['namespace'], step['record'], step.get('record_id'))
    if op == 'records':
        return store.records(step['namespace'], step.get('record_id'))
    if op == 'latest':
        return store.latest(step['namespace'], step['record_id'])
    if op == 'price_versions':
        return store.price_versions(step.get('item_id'), step.get('price_type'), step.get('supplier_id'))
    if op == 'get_price':
        return store.get_price(step['item_id'], step.get('price_type', '販売'), **step.get('kwargs', {}))
    raise ValueError(f'unknown op {op}')


def run_scenario(scenario):
    store = Store()
    results = []
    expected_list = []
    try:
        for step in scenario['steps']:
            resolved = resolve(step, results)
            try:
                with localcontext() as context:
                    context.prec = 120
                    result = execute(resolved, store)
                expected = {'ok': json.loads(dumps(result))}
                results.append(result)
            except ValidationError as error:
                expected = {'error': 'ValidationError', 'message': str(error)}
                results.append(None)
            except Exception as error:  # noqa: BLE001 - record the original failure kind
                expected = {'error': type(error).__name__, 'message': str(error)}
                results.append(None)
            expected_list.append(expected)
    finally:
        store.close()
    return {'name': scenario['name'], 'expected': expected_list}


def main(names):
    files = [HERE / 'scenarios' / f'{name}.json' for name in names] if names else sorted((HERE / 'scenarios').glob('*.json'))
    for path in files:
        spec = json.loads(path.read_text(encoding='utf-8'), parse_float=Decimal)
        output = {'source': f'scenarios/{path.name}', 'scenarios': [run_scenario(s) for s in spec['scenarios']]}
        target = HERE / path.name
        target.write_text(json.dumps(json.loads(dumps(output)), ensure_ascii=False, indent=1) + '\n',
                          encoding='utf-8')
        print(f'wrote {target.relative_to(HERE)}')


if __name__ == '__main__':
    main(sys.argv[1:])

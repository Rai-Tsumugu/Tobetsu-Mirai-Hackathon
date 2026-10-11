import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { calculate } from './browser.mjs';
import { calculate as calculateTs } from './browser.ts';
function python(expression) {
  const code = `import json; from auto_repair_engine.contract import approved_common_scenario_fixture, common_scenario_fixture; x=${expression}; print(json.dumps(x))`;
  const r = spawnSync('python3', ['-c', code], { encoding: 'utf8', env: { ...process.env, PYTHONPATH: 'src' } });
  assert.equal(r.status, 0, r.stderr); return JSON.parse(r.stdout);
}
test('browser approved fixture matches Python canonical ranges', () => {
  const scenario = python('approved_common_scenario_fixture()');
  const server = spawnSync('python3', ['-c', "import json; from auto_repair_engine.contract import approved_common_scenario_fixture; from auto_repair_engine.e07 import run; print(json.dumps(run(approved_common_scenario_fixture())))"], {encoding:'utf8', env:{...process.env,PYTHONPATH:'src'}});
  assert.equal(server.status, 0, server.stderr);
  const browser = calculate(scenario); const canonical = JSON.parse(server.stdout);
  assert.deepEqual(browser.labor.person_hours, canonical.labor.person_hours);
  assert.deepEqual(browser.labor.elapsed_hours, canonical.labor.elapsed_hours);
  assert.deepEqual(scenario, python('approved_common_scenario_fixture()'));
});
test('unknown rotor stops; unknown wait retains person-hours and nulls elapsed', () => {
  const scenario = python('common_scenario_fixture()');
  assert.equal(calculate(scenario).status, 'missing-required');
  scenario.fields.rotor_relevance = { value: 'unrelated', status: 'confirmed' };
  scenario.operations.find(x => x.operation_id === 'snow_melt').elapsed_hours = null;
  const result = calculate(scenario);
  assert.equal(result.status, 'partial');
  assert.deepEqual(result.labor.elapsed_hours, {low:null,typical:null,high:null});
  assert.deepEqual(result.labor.person_hours, {low:1.88,typical:1.88,high:1.88});
});
test('version mismatch blocks a browser calculation', () => {
  const scenario = python('approved_common_scenario_fixture()');
  assert.equal(calculate(scenario, {rule_version:'wrong'}).status, 'missing-required');
});

test('browser.ts type-stripped build matches browser.mjs', () => { const s=python('approved_common_scenario_fixture()'); const a=calculate(s); const b=calculateTs(s); assert.deepEqual(a.labor.person_hours,b.labor.person_hours); assert.deepEqual(a.labor.elapsed_hours,b.labor.elapsed_hours); });

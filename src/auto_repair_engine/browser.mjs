/** E27 browser pure function: deterministic fictional labor calculation. */
export function calculate(scenario_input, rule_pack = null) {
  const scenario = structuredClone(scenario_input);
  const version = scenario?.rule_version ?? 'fictional-rule-v1';
  const nullRange = { low: null, typical: null, high: null };
  const fail = (...unknowns) => ({ engine_id: 'e27_browser_pure_function', rule_version: version,
    status: 'missing-required', labor: { person_hours: { ...nullRange }, elapsed_hours: { ...nullRange }, breakdown: [], unknowns }, trace: [], operation_keys: [], approvals: [] });
  if (!scenario || typeof scenario !== 'object' || Array.isArray(scenario)) return fail('scenario_input:object_required');
  if (rule_pack && rule_pack.rule_version && rule_pack.rule_version !== version) return fail('rule_pack:version_mismatch');
  if (scenario.basis_unit !== 'person_hour' || !scenario.basis_definition?.trim()) return fail('basis_unit_or_definition:required');
  const fields = scenario.fields || {};
  const ops = Object.fromEntries((scenario.operations || []).map((op) => [op.operation_id, op]));
  const scope = fields.work_scope;
  const included = fields.included_operations;
  if (!scope || !['confirmed', 'declared'].includes(scope.status) || scope.value !== scenario.job_id) return fail('work_scope:confirmed_match_required');
  if (!included || !['confirmed', 'declared'].includes(included.status) || !Array.isArray(included.value) || !included.value.includes('remove_install')) return fail('included_operations:required');
  const base = ops.base_service, carry = ops.included_carry, replacement = ops.replacement_carry, wash = ops.wash;
  if (!base || base.deduplicated !== true || !Number.isFinite(base.hours) || base.hours < 0) return fail('base_service:deduplicated_hours_required');
  if (!carry || carry.included_in_base !== true || !Number.isFinite(carry.hours) || !replacement || replacement.replaces_operation_id !== 'included_carry' || !Number.isInteger(replacement.person_count) || replacement.person_count < 1 || !Number.isFinite(replacement.hours_per_person)) return fail('included_carry:replacement_required');
  if (!wash || !Number.isFinite(wash.hours)) return fail('wash:person_hour_duration_required');
  const rotorObs = fields.rotor_relevance;
  const rotorValue = fields.rotor_seizure_hours;
  let rotor = { low: 0, typical: 0, high: 0 };
  if (rotorObs?.value === 'relevant') {
    const v = rotorValue?.value; const approval = scenario.metadata?.approved_condition_widths?.rotor_seizure_hours;
    if (!v || !approval || !approval.actor?.trim() || !approval.reason?.trim() || approval.old_value !== null || JSON.stringify(approval.new_value) !== JSON.stringify(v)) return fail('rotor_seizure_hours:human_approval_required');
    if (!(Number.isFinite(v.low) && v.low <= v.typical && v.typical <= v.high)) return fail('rotor_seizure_hours:range_invalid');
    rotor = structuredClone(v);
  } else if (rotorObs?.value !== 'unrelated' || !['confirmed', 'declared'].includes(rotorObs.status)) return fail('rotor_relevance:human_confirmation_required');
  const waits = ['snow_melt', 'penetrant_wait', 'parts_wait'];
  const elapsedWaits = []; const unknowns = [];
  for (const id of waits) {
    const op = ops[id];
    if (!op) return fail(`${id}:required_operation_missing`);
    if (id === 'parts_wait' && op.stock_checked !== true) return fail('parts_wait:stock_confirmation_required');
    const value = op.elapsed_hours ?? op.duration_hours ?? (id === 'parts_wait' ? op.hours : undefined);
    if (value == null) { elapsedWaits.push(null); unknowns.push(`${id}:elapsed_duration_unknown`); }
    else if (!Number.isFinite(value) || value < 0) return fail(`${id}:elapsed_duration_invalid`);
    else elapsedWaits.push(value);
  }
  const netBase = base.hours - carry.hours;
  if (netBase < 0) return fail('included_transport:exceeds_base');
  const handling = replacement.hours_per_person * replacement.person_count;
  const person = Object.fromEntries(['low', 'typical', 'high'].map(k => [k, Number((netBase + handling + wash.hours + rotor[k]).toFixed(10))]));
  const elapsed = unknowns.length ? { ...nullRange } : Object.fromEntries(['low', 'typical', 'high'].map(k => [k, Number((netBase + replacement.hours_per_person + wash.hours + elapsedWaits.reduce((a,b)=>a+b,0) + rotor[k]).toFixed(10))]));
  return { engine_id: 'e27_browser_pure_function', rule_version: version, status: unknowns.length ? 'partial' : 'proposed',
    labor: { person_hours: person, elapsed_hours: elapsed, breakdown: [], unknowns }, trace: [{ stage: 'browser_pure_calculation', immutable_input: true }], operation_keys: Object.keys(ops), approvals: [] };
}

const DB_NAME = 'auto-repair-e29-snapshots';
function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${stableJson(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
}
async function snapshotDigest(value) {
  const bytes = new TextEncoder().encode(stableJson(value));
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, '0')).join('');
}
export async function verifyOfflineSnapshot(snapshot) {
  return Boolean(snapshot && snapshot.scenario_input && snapshot.input_sha256
    && await snapshotDigest(snapshot.scenario_input) === snapshot.input_sha256);
}
export async function queueOfflineSnapshot(snapshot) {
  if (!globalThis.indexedDB) throw new Error('IndexedDB unavailable');
  const copy = structuredClone(snapshot);
  const input_sha256 = await snapshotDigest(copy.scenario_input);
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore('snapshots', { keyPath: 'snapshot_id' });
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result; const tx = db.transaction('snapshots', 'readwrite');
      tx.objectStore('snapshots').add({ ...copy, input_sha256, status: 'pending' });
      tx.oncomplete = () => { db.close(); resolve(copy.snapshot_id); };
      tx.onerror = () => { db.close(); reject(tx.error); };
    };
  });
}
export function readOfflineSnapshots() {
  if (!globalThis.indexedDB) return Promise.reject(new Error('IndexedDB unavailable'));
  return new Promise((resolve, reject) => { const req = indexedDB.open(DB_NAME, 1);
    req.onsuccess = () => { const db = req.result; const tx = db.transaction('snapshots', 'readonly');
      const all = tx.objectStore('snapshots').getAll(); all.onsuccess = () => { resolve(all.result); db.close(); };
      all.onerror = () => reject(all.error); }; req.onerror = () => reject(req.error); });
}
export async function syncOfflineSnapshot(snapshot, server_rule_version, decision = null) {
  if (!(await verifyOfflineSnapshot(snapshot))) return { ...structuredClone(snapshot), status: 'snapshot_integrity_error' };
  return resolveOfflineConflict(snapshot, server_rule_version, decision);
}
export function resolveOfflineConflict(snapshot, server_rule_version, decision) {
  if (snapshot.rule_version === server_rule_version) return { ...structuredClone(snapshot), status: 'ready_to_recompute' };
  if (!decision || !decision.actor?.trim() || !decision.reason?.trim() || !['keep_snapshot','rebase_to_server'].includes(decision.choice))
    return { ...structuredClone(snapshot), status: 'version_conflict', server_rule_version };
  const result = structuredClone(snapshot); result.status = decision.choice === 'rebase_to_server' ? 'ready_to_recompute' : 'ready_with_pinned_version';
  result.resolution = { ...decision, old_version: snapshot.rule_version, new_version: server_rule_version };
  if (decision.choice === 'rebase_to_server') result.rule_version = server_rule_version;
  return result;
}

/** E27 browser pure calculation contract. Kept dependency-free for native Node 24 type stripping. */
export type Range = { low: number | null; typical: number | null; high: number | null };
export type EngineResult = { engine_id: string; rule_version: string; status: string; labor: { person_hours: Range; elapsed_hours: Range; breakdown: unknown[]; unknowns: string[] }; trace: unknown[]; operation_keys: string[]; approvals: unknown[] };
export function calculate(scenario_input: Record<string, any>, rule_pack: Record<string, any> | null = null): EngineResult {
  const scenario = structuredClone(scenario_input); const version = scenario.rule_version ?? 'fictional-rule-v1';
  const nil: Range = {low:null, typical:null, high:null};
  const fail = (...unknowns: string[]): EngineResult => ({engine_id:'e27_browser_pure_function',rule_version:version,status:'missing-required',labor:{person_hours:{...nil},elapsed_hours:{...nil},breakdown:[],unknowns},trace:[],operation_keys:[],approvals:[]});
  if (!scenario || typeof scenario !== 'object' || Array.isArray(scenario)) return fail('scenario_input:object_required');
  if (rule_pack?.rule_version && rule_pack.rule_version !== version) return fail('rule_pack:version_mismatch');
  if (scenario.basis_unit !== 'person_hour' || !scenario.basis_definition?.trim()) return fail('basis_unit_or_definition:required');
  const fields = scenario.fields ?? {}; const ops = Object.fromEntries((scenario.operations ?? []).map((op: any) => [op.operation_id, op]));
  const scope = fields.work_scope; const included = fields.included_operations;
  if (!scope || !['confirmed','declared'].includes(scope.status) || scope.value !== scenario.job_id) return fail('work_scope:confirmed_match_required');
  if (!included || !['confirmed','declared'].includes(included.status) || !Array.isArray(included.value) || !included.value.includes('remove_install')) return fail('included_operations:required');
  const base=ops.base_service, carry=ops.included_carry, replacement=ops.replacement_carry, wash=ops.wash;
  if (!base || base.deduplicated !== true || !Number.isFinite(base.hours) || base.hours < 0) return fail('base_service:deduplicated_hours_required');
  if (!carry || carry.included_in_base !== true || !Number.isFinite(carry.hours) || !replacement || replacement.replaces_operation_id !== 'included_carry' || !Number.isInteger(replacement.person_count) || replacement.person_count < 1 || !Number.isFinite(replacement.hours_per_person)) return fail('included_carry:replacement_required');
  if (!wash || !Number.isFinite(wash.hours)) return fail('wash:person_hour_duration_required');
  const rotorObs=fields.rotor_relevance; const rotorValue=fields.rotor_seizure_hours; let rotor: any={low:0,typical:0,high:0};
  if (rotorObs?.value === 'relevant') { const v=rotorValue?.value; const a=scenario.metadata?.approved_condition_widths?.rotor_seizure_hours;
    if (!v || !a || !a.actor?.trim() || !a.reason?.trim() || a.old_value !== null || JSON.stringify(a.new_value)!==JSON.stringify(v)) return fail('rotor_seizure_hours:human_approval_required');
    if (!(Number.isFinite(v.low) && v.low<=v.typical && v.typical<=v.high)) return fail('rotor_seizure_hours:range_invalid'); rotor=structuredClone(v);
  } else if (rotorObs?.value !== 'unrelated' || !['confirmed','declared'].includes(rotorObs.status)) return fail('rotor_relevance:human_confirmation_required');
  const waits=['snow_melt','penetrant_wait','parts_wait']; const elapsedWaits: number[]=[]; const unknowns:string[]=[];
  for (const id of waits) { const op=ops[id]; if (!op) return fail(`${id}:required_operation_missing`); if (id==='parts_wait' && op.stock_checked!==true) return fail('parts_wait:stock_confirmation_required');
    const value=op.elapsed_hours ?? op.duration_hours ?? (id==='parts_wait'?op.hours:undefined);
    if (value==null) {elapsedWaits.push(0);unknowns.push(`${id}:elapsed_duration_unknown`);} else if (!Number.isFinite(value)||value<0) return fail(`${id}:elapsed_duration_invalid`); else elapsedWaits.push(value);
  }
  const netBase=base.hours-carry.hours; if(netBase<0)return fail('included_transport:exceeds_base');
  const handling=replacement.hours_per_person*replacement.person_count;
  const person:Range=Object.fromEntries(['low','typical','high'].map(k=>[k,Number((netBase+handling+wash.hours+rotor[k]).toFixed(10))])) as Range;
  const elapsed:Range=unknowns.length?{...nil}:Object.fromEntries(['low','typical','high'].map(k=>[k,Number((netBase+replacement.hours_per_person+wash.hours+elapsedWaits.reduce((a,b)=>a+b,0)+rotor[k]).toFixed(10))])) as Range;
  return {engine_id:'e27_browser_pure_function',rule_version:version,status:unknowns.length?'partial':'proposed',labor:{person_hours:person,elapsed_hours:elapsed,breakdown:[],unknowns},trace:[{stage:'browser_pure_calculation',immutable_input:true}],operation_keys:Object.keys(ops),approvals:[]};
}

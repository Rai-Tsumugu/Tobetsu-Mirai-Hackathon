"""Unified fictional estimate workflow composed from validated existing modules."""
from __future__ import annotations
from copy import deepcopy
import hashlib, json
from typing import Any
from . import e02, e06, e07, e13, e18, e21

ENGINE_ID = "integrated"
RULE_VERSION = "integrated-workflow-v1"
NOTICE = "統合版も架空Simulatorです。実測工数・実価格・実車検証ではありません。"
_NULL = {"low": None, "typical": None, "high": None}


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    version = scenario.get("rule_version", RULE_VERSION)
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else {}
    trace = []
    if not isinstance(scenario_input, dict):
        return _stop(version, ["scenario_input:object_required"], trace)
    if rule_pack is not None and not isinstance(rule_pack, dict):
        return _stop(version, ["rule_pack:object_required"], trace)
    if pack and pack.get("rule_version") not in (None, version):
        return _stop(version, ["rule_pack:version_mismatch"], trace)
    schema = e13.render_form(scenario, pack.get("form_rule_pack"))
    validation = e07.validate_stage(scenario)
    unknown_wait_ids=[]
    for op in scenario.get("operations",[]):
        if isinstance(op,dict) and op.get("operation_id") in {"snow_melt","penetrant_wait","parts_wait"}:
            duration=op.get("elapsed_hours",op.get("duration_hours",op.get("hours")))
            if duration is None: unknown_wait_ids.append(op["operation_id"])
    gaps=[issue for issue in validation.issues if not any(issue.startswith(f"{op_id}:") and "elapsed_hours_required" in issue for op_id in unknown_wait_ids)]
    questions = schema.get("questions", [])
    if questions:
        gaps.extend(f"{q['field']}:schema_confirmation_required" for q in questions)
    trace.append({"stage":"schema_and_pipeline_validation", "schema":schema["schema"],
                  "questions":deepcopy(questions), "issues":list(dict.fromkeys(gaps)),
                  "input_hash":validation.input_hash})
    if gaps:
        return _stop(version, gaps, trace)
    approved_pack = pack.get("approved_rule_pack")
    if approved_pack is None:
        result = e06.run(scenario)
        trace.append({"stage":"approved_rules", "engine_id":"e06_approval_rules",
                      "source":"fictional_approved_baseline", "approval_trace":deepcopy(result.get("trace", []))})
    else:
        result = e02.run(scenario, approved_pack)
        trace.append({"stage":"approved_rules", "engine_id":"e02_versioned_json",
                      "source":"explicit_approved_rule_pack", "approval_trace":deepcopy(result.get("trace", []))})
    if result.get("status") == "missing-required":
        return _stop(version, list(result["labor"].get("unknowns", [])), trace)
    labor = deepcopy(result["labor"])
    if unknown_wait_ids:
        labor["elapsed_hours"] = dict(_NULL)
        labor["unknowns"] = list(dict.fromkeys(labor.get("unknowns",[])+[f"{op_id}:elapsed_duration_unknown" for op_id in unknown_wait_ids]))
        for row in labor.get("breakdown",[]):
            if row.get("operation_id") in unknown_wait_ids:
                row["elapsed_hours"] = dict(_NULL)
        result["status"]="partial"
    additions = pack.get("evidence_additions", [])
    evidence_ids=[]
    evidence_elapsed_unknowns=[]
    if additions:
        evidence = e21.run(scenario, {"additions": additions})
        trace.append({"stage":"evidence_gate", "engine_id":"e21_evidence_additions",
                      "accepted":deepcopy(evidence.get("evidence_additions", {}).get("accepted", [])),
                      "issues":deepcopy(evidence.get("evidence_additions", {}).get("issues", []))})
        if evidence.get("status") == "missing-required":
            return _stop(version, list(evidence["labor"].get("unknowns", [])), trace)
        requested_by_id = {item.get("operation_id"): item for item in additions if isinstance(item, dict)}
        for addition in evidence["evidence_additions"]["accepted"]:
            evidence_ids.append(addition["operation_id"])
            requested = requested_by_id.get(addition["operation_id"], {})
            for band in ("low", "typical", "high"):
                labor["person_hours"][band] = round(labor["person_hours"][band] + addition["hours"], 10)
            duration=requested.get("duration_hours")
            count=requested.get("person_count")
            if isinstance(duration,(int,float)) and not isinstance(duration,bool) and duration>=0 and isinstance(count,int) and not isinstance(count,bool) and count>0:
                addition_elapsed={k:float(duration) for k in ("low","typical","high")}
                for band in ("low","typical","high"):
                    if labor["elapsed_hours"][band] is not None:
                        labor["elapsed_hours"][band] = round(labor["elapsed_hours"][band] + float(duration), 10)
            else:
                addition_elapsed=dict(_NULL); evidence_elapsed_unknowns.append(f"{addition['operation_id']}:elapsed_duration_unknown")
            labor["breakdown"].append({"operation":addition["operation_id"],"operation_id":addition["operation_id"],
                "hours":{k:addition["hours"] for k in ("low","typical","high")},"elapsed_hours":addition_elapsed,
                "person_count":count,"reason":addition["approval"]["reason"],"status":"conditional","source":addition["source"],
                "approval":deepcopy(addition["approval"])})
    client = pack.get("client_proposal")
    if client is not None:
        if (not isinstance(client, dict) or not isinstance(client.get("labor"), dict) or client.get("rule_version") != version
                or (client.get("labor") or {}).get("person_hours") != labor.get("person_hours")
                or (client.get("labor") or {}).get("elapsed_hours") != labor.get("elapsed_hours")):
            return _stop(version, ["client_proposal:server_recomputation_mismatch"], trace)
        trace.append({"stage":"server_recompute", "client_proposal_checked":True, "match":True})
    if evidence_elapsed_unknowns:
        labor["elapsed_hours"]=dict(_NULL)
        labor["unknowns"]=list(dict.fromkeys(labor.get("unknowns",[])+evidence_elapsed_unknowns))
    input_hash = hashlib.sha256(json.dumps(scenario,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
    applied_rows=[]
    for row in labor.get("breakdown", []):
        applied_rows.append({"operation_id":row.get("operation_id"),"operation":row.get("operation"),
            "hours":deepcopy(row.get("hours")),"elapsed_hours":deepcopy(row.get("elapsed_hours")),
            "status":row.get("status"),"source":row.get("source"),"reason":row.get("reason")})
    leaves=[]
    replacement=next((op for op in scenario.get("operations",[]) if op.get("operation_id")=="replacement_carry"),{})
    for index,row in enumerate(labor.get("breakdown",[])):
        person=deepcopy(row.get("hours",dict(_NULL)))
        if row.get("status")=="wait":
            elapsed=deepcopy(row.get("elapsed_hours",dict(_NULL)))
            person={k:0.0 for k in ("low","typical","high")}
        elif row.get("operation_id")=="replacement_carry":
            count=replacement.get("person_count")
            elapsed={k:(row.get("hours",{}).get(k)/count if isinstance(count,int) and count>0 else None) for k in ("low","typical","high")}
        elif row.get("operation_id")=="wash":
            wash_op=next((op for op in scenario.get("operations",[]) if op.get("operation_id")=="wash"),{})
            count=wash_op.get("person_count",1)
            elapsed={k:(person[k]/count if isinstance(count,int) and count>0 else None) for k in ("low","typical","high")}
        elif row.get("operation_id") in evidence_ids:
            elapsed=deepcopy(row.get("elapsed_hours",dict(_NULL)))
        else:
            elapsed=deepcopy(row.get("elapsed_hours") or person)
        leaves.append({"node_id":f"row-{index}","rule":"operation_contribution","children":[],
                       "result":{"person_hours":person,"elapsed_hours":elapsed},"operation_id":row.get("operation_id"),
                       "source":row.get("source"),"status":row.get("status"),"reason":row.get("reason")})
    tree={"node_id":"integrated-root","rule":"sum_children","children":leaves}
    evaluated=e18.evaluate_tree(tree)
    expected={"person_hours":deepcopy(labor["person_hours"]),"elapsed_hours":deepcopy(labor["elapsed_hours"])}
    trace.append({"stage":"e18_applied_row_trace_tree","engine_id":"e18_calculation_trace_tree",
                  "rule_version":version,"input_sha256":input_hash,"tree":tree,"evaluated":evaluated})
    if evaluated != expected:
        return _stop(version,["trace_tree:applied_rows_do_not_reproduce_labor"],trace)
    trace.append({"stage":"offline_replay", "engine_id":"e29_offline_snapshot",
                  "rule_version_pinned":version,"conflict_policy":"explicit_human_resolution"})
    final_status="partial" if unknown_wait_ids or evidence_elapsed_unknowns else result.get("status","proposed")
    return {"engine_id":ENGINE_ID,"rule_version":version,"status":final_status,
            "labor":labor,"trace":trace,
            "operation_keys":list(dict.fromkeys(row.get("operation_id",row.get("operation","")) for row in labor.get("breakdown",[]))),
            "approvals":deepcopy(result.get("approvals",[])),"simulator_notice":NOTICE}


def _stop(version: str, issues: list[str], trace: list[dict[str, Any]]) -> dict[str, Any]:
    return {"engine_id":ENGINE_ID,"rule_version":version,"status":"missing-required",
            "labor":{"person_hours":dict(_NULL),"elapsed_hours":dict(_NULL),"breakdown":[],"unknowns":list(dict.fromkeys(issues))},
            "trace":trace,"operation_keys":[],"approvals":[],"simulator_notice":NOTICE}

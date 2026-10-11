"""Local-only FastAPI surface shared by the isolated R01-R30 strategies."""
from __future__ import annotations

import math
from datetime import date

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .models import ApprovalRequest, ProposalCreate, RateProposal
from .shared import discover_module_routers
from . import store

app = FastAPI(title="自動車整備工場 工賃単価 Simulator", version="0.1.0")
shared_api = APIRouter(prefix="/api/auto-repair-rate")


def _safe_validation_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_validation_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_validation_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


@app.exception_handler(RequestValidationError)
async def validation_error_response(_request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": _safe_validation_value(exc.errors())})


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "local_simulator", "external_network": False}


@shared_api.post("/proposals")
def post_proposal(body: ProposalCreate):
    if body.proposal.module_id != "R15":
        raise HTTPException(422, "this module must use its dedicated server-side calculation endpoint")
    try:
        return store.create_proposal(body.proposal)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@shared_api.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    result = store.get_proposal(proposal_id)
    if result is None:
        raise HTTPException(404, "rate proposal not found")
    return result


@shared_api.get("/proposals")
def recent_proposals(limit: int = 30):
    return store.list_proposals(limit)


@shared_api.post("/proposals/{proposal_id}/approval")
def approve(proposal_id: str, body: ApprovalRequest):
    try:
        result = store.approve(proposal_id, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "rate proposal not found")
    return result


@shared_api.get("/labor-rates")
@app.get("/api/labor-rates", include_in_schema=False)
def labor_rates(rate_scope: str | None = None, rate_type: str | None = None):
    return store.list_rates(rate_scope=rate_scope, rate_type=rate_type)


@shared_api.get("/labor-rates/active")
def active_factory_rate(as_of: date | None = None):
    """Return only the approved customer-facing factory-standard rate valid as of a day."""
    effective_date = as_of or date.today()
    return store.get_rate_as_of(effective_date, rate_scope="factory_standard", rate_type="customer")


@shared_api.get("/modules")
def rate_modules():
    module_titles = {
        "R01": "年間原価積上げ単価", "R02": "粗利目標逆算単価", "R03": "給与倍率目安単価",
        "R04": "根拠付き相場参照単価", "R05": "原価下限＋目標利益単価",
        "R06": "稼働率シナリオ単価", "R07": "部門別費用プール単価", "R08": "年間固定費配賦",
        "R09": "冬季費用の季節別配賦", "R10": "月次費用平準化", "R11": "季節変動費シナリオ",
        "R12": "変動費更新イベント", "R13": "3分入力ウィザード", "R14": "CSV費用取込",
        "R15": "金額だけの年次入力", "R16": "人員・稼働時間入力", "R17": "給与と家族労務の分離入力",
        "R18": "不明項目つき仮単価", "R19": "工場標準単価", "R20": "作業者別原価単価",
        "R21": "作業カテゴリ別単価", "R22": "請求区分別単価", "R23": "定期見直しカレンダー",
        "R24": "閾値トリガー再計算", "R25": "社長承認・履歴管理", "R26": "目標差分モニター",
        "R27": "原価内訳ウォーターフォール", "R28": "年間・冬季シナリオ比較",
        "R29": "現行単価と必要単価の差額表示", "R30": "根拠カード・確信度表示",
    }
    modules_by_id = {"R15": {"module_id": "R15", "title": module_titles["R15"],
                             "description": "金額・期間総労働人時・u_periodから比較候補を算出"}}
    for module_id, router in discover_module_routers():
        tag = router.tags[0] if router.tags else "独立した単価方式"
        description = tag.removeprefix(f"{module_id} ").strip() or tag
        modules_by_id[module_id] = {"module_id": module_id,
                                    "title": module_titles.get(module_id, description),
                                    "description": description}
    return list(modules_by_id.values())


app.include_router(shared_api)
for module_id, router in discover_module_routers():
    app.include_router(router, prefix=f"/api/auto-repair-rate/{module_id}")

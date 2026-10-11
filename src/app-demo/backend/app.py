"""Repair estimate demo with an offline simulator and attributed Gemini research."""
import json
import hashlib
import time
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from statistics import median
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv
try:
    from . import gemini
except ImportError:
    import gemini

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
DB_PATH = Path(os.environ.get("REPAIR_DB_PATH", str(ROOT / "demo.sqlite3")))
TAX_RATE = Decimal("0.10")
MODELS = [
    ("ホンダ", "シビック", "FL4", "e:HEV（デモ仕様）"),
    ("ホンダ", "シビック", "FL1", "ガソリン（デモ仕様）"),
    ("トヨタ", "プリウス", "ZVW50", "ハイブリッド（デモ仕様）"),
    ("トヨタ", "プリウス", "MXWH60", "ハイブリッド（デモ仕様）"),
    ("トヨタ", "アクア", "NHP10", "ハイブリッド（デモ仕様）"),
    ("トヨタ", "アクア", "MXPK11", "ハイブリッド（デモ仕様）"),
    ("スズキ", "ジムニー", "JB64W", "4WD（デモ仕様）"),
    ("ホンダ", "N-BOX", "JF3", "軽自動車（デモ仕様）"),
    ("ホンダ", "N-BOX", "JF5", "軽自動車（デモ仕様）"),
]
JOBS = [
    {"id": "brake", "category": "ブレーキ", "name": "フロントブレーキパッド交換", "description": "前輪左右・パッド持込なし", "base": 6000},
    {"id": "oil", "category": "消耗品", "name": "エンジンオイル交換", "description": "オイル交換のみ・フィルター別", "base": 2000},
    {"id": "battery", "category": "電装", "name": "補機バッテリー交換", "description": "補機用・バッテリー持込なし", "base": 4000},
    {"id": "filter", "category": "消耗品", "name": "エアコンフィルター交換", "description": "フィルター交換のみ", "base": 1500},
    {"id": "bumper", "category": "外装", "name": "フロントバンパー交換", "description": "脱着交換・塗装と補修は別", "base": 16000},
]


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS vehicles(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS repair_jobs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS estimates(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, search_text TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS estimate_items(id TEXT PRIMARY KEY, estimate_id TEXT NOT NULL REFERENCES estimates(id), repair_job_id TEXT NOT NULL REFERENCES repair_jobs(id), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS price_sources(id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES estimate_items(id), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_cache(id TEXT PRIMARY KEY, cache_key TEXT NOT NULL, created_at REAL NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS research_cache_key ON research_cache(cache_key, created_at);
            CREATE TABLE IF NOT EXISTS selected_sources(item_id TEXT NOT NULL REFERENCES estimate_items(id), source_id TEXT NOT NULL REFERENCES price_sources(id), PRIMARY KEY(item_id, source_id));
        ''')
        for maker, model, code, grade in MODELS:
            data = dict(id=code, maker=maker, model=model, model_code=code,
                        years=list(range(2015, 2027)), grades=[grade, "その他（要確認）"],
                        length_mm=None, width_mm=None, height_mm=None, powertrain="未確認",
                        source_name="simulator", source_url=None, verified_at=None,
                        note="年式の選択肢・仕様はデモ用です。実車への適合・諸元は未確認です。")
            db.execute("INSERT OR IGNORE INTO vehicles VALUES (?, ?)", (code, json.dumps(data, ensure_ascii=False)))
        for job in JOBS:
            db.execute("INSERT OR IGNORE INTO repair_jobs VALUES (?, ?)", (job['id'], json.dumps(job, ensure_ascii=False)))


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(title="整備見積 Simulator", lifespan=lifespan)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManualVehicle(StrictModel):
    maker: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=80)
    model_code: str = Field(min_length=1, max_length=40)
    year: int = Field(ge=1900, le=2100)
    grade: str = Field(min_length=1, max_length=80)


def vehicle_by_id(vehicle_id):
    with connect() as db:
        row = db.execute("SELECT data FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
    if not row:
        raise HTTPException(404, "車両が見つかりません")
    return json.loads(row['data'])


@app.get("/api/vehicles")
def vehicles(query: str = "", origin: str = "all"):
    with connect() as db:
        rows = db.execute("SELECT data FROM vehicles").fetchall()
    return [v for row in rows if (v := json.loads(row['data'])) and query.casefold().strip() in (v['maker'] + v['model'] + v['model_code']).casefold() and (origin != 'live' or v['source_name'] != 'simulator')]


@app.get("/api/config")
def config():
    return {"gemini_configured": gemini.configured(), "gemini_model": gemini.MODEL}


def cached_investigation(kind, target, schema, extract):
    cache_key = hashlib.sha256(json.dumps({"kind": kind, "target": target, "model": gemini.MODEL}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with connect() as db:
        row = db.execute("SELECT data FROM research_cache WHERE cache_key=? AND created_at>? ORDER BY created_at DESC LIMIT 1", (cache_key, time.time() - 86400)).fetchone()
    if row:
        return {**json.loads(row['data']), 'cached': True}
    result = gemini.investigate(target, schema)
    values = extract(result)
    result.pop('data', None)
    result.update(values=values, context=target, kind=kind, research_id=uuid4().hex, cached=False)
    result['warnings'] = list(dict.fromkeys(result['warnings']))
    with connect() as db:
        if kind == 'vehicles':
            for vehicle in values:
                db.execute("INSERT INTO vehicles VALUES (?, ?)", (vehicle['id'], json.dumps(vehicle, ensure_ascii=False)))
        db.execute("INSERT INTO research_cache VALUES (?, ?, ?, ?)", (result['research_id'], cache_key, time.time(), json.dumps(result, ensure_ascii=False)))
    return result


class VehicleSearch(StrictModel):
    query: str = Field(min_length=2, max_length=160)


@app.post("/api/vehicle-research")
def vehicle_research(body: VehicleSearch):
    if not body.query.strip():
        raise HTTPException(422, "メーカー・車種または型式を入力してください")
    return cached_investigation('vehicles', {"query": body.query.strip()}, gemini.VehicleRecords.model_json_schema(), gemini.extract_vehicles)


@app.get("/api/vehicles/{vehicle_id}")
def vehicle_detail(vehicle_id: str):
    return vehicle_by_id(vehicle_id)


@app.post("/api/vehicles", status_code=201)
def manual_vehicle(body: ManualVehicle):
    if not all(s.strip() for s in [body.maker, body.model, body.model_code, body.grade]):
        raise HTTPException(422, "車両情報を入力してください")
    data = dict(id="manual-" + uuid4().hex[:12], maker=body.maker.strip(), model=body.model.strip(),
                model_code=body.model_code.strip(), years=[body.year], grades=[body.grade.strip()],
                length_mm=None, width_mm=None, height_mm=None, powertrain="未確認",
                source_name="manual", source_url=None, verified_at=None, note="手入力の暫定登録。適合・諸元は未確認です。")
    with connect() as db:
        db.execute("INSERT INTO vehicles VALUES (?, ?)", (data['id'], json.dumps(data, ensure_ascii=False)))
    return data


@app.get("/api/repair-jobs")
def jobs():
    return JOBS


class Research(StrictModel):
    vehicle_id: str
    year: int
    grade: str
    job_ids: list[str] = Field(min_length=1, max_length=5)
    mode: str = Field(default="simulator", pattern="^(simulator|live)$")


def validate_context(vehicle_id, year, grade, job_ids):
    vehicle = vehicle_by_id(vehicle_id)
    if year not in vehicle['years'] or grade not in vehicle['grades']:
        raise HTTPException(422, "年式・仕様を選択してください")
    if len(job_ids) != len(set(job_ids)) or any(j not in {job['id'] for job in JOBS} for j in job_ids):
        raise HTTPException(422, "作業が重複しているか、未登録の作業です")
    return vehicle


def sources_for(job):
    base = job['base']
    return [dict(id=f"{job['id']}-{i}", source_title=f"サンプル整備記録 {label}", source_url=None,
                 mode="simulator", retrieved_at="2026-10-11", currency="JPY", verified=False,
                 labor_price=price if i < 3 else None, parts_price=None if i < 3 else base * 2,
                 total_price=None if i < 3 else base * 4, tax_included=i == 1,
                 vehicle_match_level="型式一致（架空）" if i < 3 else "別仕様（架空）",
                 work_conditions=job['description'] if i < 3 else "別仕様・追加工程あり・工賃内訳不明",
                 extraction_notes="サンプル／実価格ではない",
                 normalized_labor=int((Decimal(price) / Decimal('1.1')).quantize(Decimal('1'), rounding=ROUND_FLOOR)) if i == 1 else price if i < 3 else None)
            for i, (label, price) in enumerate([('A', base - 1000), ('B', int(Decimal(base) * Decimal('1.1'))), ('C', base + 2000), ('D', base * 4)])]


@app.post("/api/price-research")
def research(body: Research):
    vehicle = validate_context(body.vehicle_id, body.year, body.grade, body.job_ids)
    if body.mode == 'simulator':
        return {job['id']: sources_for(job) for job in JOBS if job['id'] in body.job_ids}
    target = dict(vehicle_id=vehicle['id'], maker=vehicle['maker'], model=vehicle['model'], model_code=vehicle['model_code'], year=body.year, grade=body.grade,
                  jobs=[{k: job[k] for k in ('id', 'name', 'description')} for job in JOBS if job['id'] in body.job_ids])
    result = cached_investigation('prices', target, gemini.Prices.model_json_schema(), lambda r: gemini.extract_prices(r, body.job_ids))
    return {**result, 'sources': result['values']}



class Item(StrictModel):
    job_id: str
    selected_source_ids: list[str] = Field(max_length=4)
    labor_price: int = Field(ge=0, le=10000000, strict=True)
    parts_price: int = Field(ge=0, le=10000000, strict=True)
    conditions: str = Field(default="", max_length=1000)
    adjustment_reason: str = Field(default="", max_length=1000)


class Estimate(StrictModel):
    mode: str = Field(default="simulator", pattern="^(simulator|live)$")
    research_id: str | None = None
    vehicle_id: str
    year: int
    grade: str
    items: list[Item] = Field(min_length=1, max_length=5)
    notes: str = Field(default="", max_length=2000)


@app.post("/api/estimates", status_code=201)
def save_estimate(body: Estimate):
    vehicle = validate_context(body.vehicle_id, body.year, body.grade, [i.job_id for i in body.items])
    research = {}
    live_sources = None
    if body.mode == 'live':
        with connect() as db:
            row = db.execute("SELECT data FROM research_cache WHERE id=?", (body.research_id,)).fetchone()
        if not row:
            raise HTTPException(422, '参照したWeb調査が見つかりません。再検索してください。')
        research = json.loads(row['data'])
        context = research['context']
        if research['kind'] != 'prices' or context['vehicle_id'] != body.vehicle_id or context['year'] != body.year or context['grade'] != body.grade or {j['id'] for j in context['jobs']} != {i.job_id for i in body.items}:
            raise HTTPException(422, 'Web調査時と車両・年式・仕様・作業が異なります。再検索してください。')
        live_sources = research['values']
    elif body.research_id is not None:
        raise HTTPException(422, 'SimulatorにWeb調査を混ぜることはできません。')
    records = []
    for item in body.items:
        job = next(j for j in JOBS if j['id'] == item.job_id)
        sources = live_sources[item.job_id] if live_sources is not None else sources_for(job)
        ids = item.selected_source_ids
        if len(ids) != len(set(ids)) or any(s not in [p['id'] for p in sources] for s in ids):
            raise HTTPException(422, "参照候補を確認してください")
        labor = [s['normalized_labor'] for s in sources if s['id'] in ids and s['normalized_labor'] is not None]
        calculated = int(median(labor)) if labor else None
        if (calculated is None or calculated != item.labor_price) and not item.adjustment_reason.strip():
            raise HTTPException(422, "工賃の手入力・調整理由を入力してください")
        records.append(dict(**item.model_dump(), name=job['name'], category=job['category'],
                            calculated_labor_price=calculated, sources=sources))
    subtotal = sum(i['labor_price'] + i['parts_price'] for i in records)
    tax = int((Decimal(subtotal) * TAX_RATE).quantize(Decimal('1'), rounding=ROUND_FLOOR))
    result = dict(id=uuid4().hex[:12], created_at=datetime.now(timezone.utc).isoformat(), status="confirmed",
                  mode=body.mode, research_id=body.research_id, search_suggestions=research.get('search_suggestions', ''), vehicle=vehicle, year=body.year, grade=body.grade, items=records,
                  notes=body.notes, labor_total=sum(i['labor_price'] for i in records),
                  parts_total=sum(i['parts_price'] for i in records), tax_rate=float(TAX_RATE),
                  subtotal=subtotal, tax_amount=tax, total_amount=subtotal + tax)
    with connect() as db:
        search_text = ' '.join([vehicle['maker'], vehicle['model'], vehicle['model_code'], str(body.year), body.grade] + [i['name'] for i in records])
        db.execute("INSERT INTO estimates VALUES (?, ?, ?, ?)", (result['id'], result['created_at'], search_text, json.dumps(result, ensure_ascii=False)))
        for record in records:
            item_id = uuid4().hex
            db.execute("INSERT INTO estimate_items VALUES (?, ?, ?, ?)", (item_id, result['id'], record['job_id'], json.dumps(record, ensure_ascii=False)))
            for source in record['sources']:
                source_id = item_id + '-' + source['id']
                db.execute("INSERT INTO price_sources VALUES (?, ?, ?)", (source_id, item_id, json.dumps(source, ensure_ascii=False)))
                if source['id'] in record['selected_source_ids']:
                    db.execute("INSERT INTO selected_sources VALUES (?, ?)", (item_id, source_id))
    return result


@app.get("/api/estimates")
def estimates(query: str = ""):
    # Escape LIKE wildcard characters so searches are literal partial matches.
    escaped = query.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    with connect() as db:
        rows = db.execute("SELECT data FROM estimates WHERE search_text LIKE ? ESCAPE '\\' ORDER BY created_at DESC", ('%' + escaped + '%',)).fetchall()
    return [json.loads(r['data']) for r in rows]


@app.get("/api/estimates/{estimate_id}")
def estimate_detail(estimate_id: str):
    with connect() as db:
        row = db.execute("SELECT data FROM estimates WHERE id=?", (estimate_id,)).fetchone()
    if not row:
        raise HTTPException(404, "見積もりが見つかりません")
    return json.loads(row['data'])


if (ROOT / "dist").exists():
    app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="frontend")

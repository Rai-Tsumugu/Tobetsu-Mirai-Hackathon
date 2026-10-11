/* eslint-disable @typescript-eslint/no-explicit-any */
// 工数エンジン30案の保存先（元: src/auto_repair_engine/store.py の AutoRepairStore）。
// 見積・冪等キー・観察イベント・実績の訂正・オフラインスナップショット・ルールの版を engine_ 表に保存する。
import { PyKeyError, PyValueError, isStr, item, pyJsonDumps, sha256Hex, type Dict } from "../../systems/engine/py";
import { queryOne, queryRows, transaction, type Database } from "../queryable";

/** 元の json.dumps(result, ensure_ascii=False, sort_keys=True) と同じ形の正準 JSON。 */
export const canonicalJson = (value: unknown): string => pyJsonDumps(value, { sortKeys: true, ensureAscii: false });
export const canonicalHash = (value: unknown): string => sha256Hex(canonicalJson(value));

/** SQLite の CURRENT_TIMESTAMP と同じ形（UTC の 'YYYY-MM-DD HH:MM:SS'）で時刻を返す列式。 */
const TS = (column: string) => `to_char(${column} AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')`;

/** 保存先の読み書き（サービス層はこのインターフェースだけに依存する）。 */
export interface EngineStore {
  saveEstimate(estimateId: string, result: Dict, idempotencyKey: string | null): Promise<string>;
  getEstimate(estimateId: string): Promise<Dict | null>;
  listEstimates(limit: number): Promise<Dict[]>;
  recordEvent(eventId: string, scenarioId: string, eventType: any, body: Dict, operationId: any): Promise<void>;
  eventsFor(scenarioId: string): Promise<Dict[]>;
}

export async function saveEstimate(db: Database, estimateId: string, result: Dict, idempotencyKey: string | null = null): Promise<string> {
  const body = canonicalJson(result);
  const bodyHash = sha256Hex(body);
  return transaction(db, async (tx) => {
    if (idempotencyKey) {
      // 元の BEGIN IMMEDIATE に当たる直列化: 同じ冪等キーの保存を同時に走らせない。
      await tx.query("SELECT pg_advisory_xact_lock(hashtext($1))", [`engine.idempotency:${idempotencyKey}`]);
      const existing = await queryOne<{ estimate_id: string; body_hash: string }>(
        tx, "SELECT estimate_id, body_hash FROM engine_estimate_idempotency WHERE idempotency_key = $1", [idempotencyKey],
      );
      if (existing) {
        if (existing.body_hash !== bodyHash) throw new PyValueError("idempotency_key_conflict");
        return existing.estimate_id;
      }
    }
    await tx.query(
      "INSERT INTO engine_estimates(estimate_id, scenario_id, engine_id, rule_version, status, body, body_hash) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)",
      [estimateId, item(result, "scenario_id"), item(result, "engine_id"), item(result, "rule_version"), item(result, "status"), body, bodyHash],
    );
    if (idempotencyKey) {
      await tx.query("INSERT INTO engine_estimate_idempotency(idempotency_key, estimate_id, body_hash) VALUES ($1, $2, $3)", [idempotencyKey, estimateId, bodyHash]);
    }
    return estimateId;
  });
}

export async function getEstimate(db: Database, estimateId: string): Promise<Dict | null> {
  const row = await queryOne<{ body: Dict }>(db, "SELECT body FROM engine_estimates WHERE estimate_id = $1", [estimateId]);
  return row ? row.body : null;
}

export async function listEstimates(db: Database, limit = 100): Promise<Dict[]> {
  const rows = await queryRows<{ estimate_id: string; body: Dict; created_at: string }>(
    db,
    `SELECT estimate_id, body, ${TS("created_at")} AS created_at FROM engine_estimates ORDER BY engine_estimates.created_at DESC, seq DESC LIMIT $1`,
    [Math.max(1, Math.min(limit, 500))],
  );
  return rows.map((row) => ({ estimate_id: row.estimate_id, created_at: row.created_at, ...row.body }));
}

export async function recordEvent(db: Database, eventId: string, scenarioId: string, eventType: any, body: Dict, operationId: any = null): Promise<void> {
  await db.query(
    "INSERT INTO engine_observation_events(event_id, scenario_id, operation_id, event_type, body) VALUES ($1, $2, $3, $4, $5::jsonb)",
    [eventId, scenarioId, operationId, eventType, pyJsonDumps(body, { ensureAscii: false })],
  );
}

export async function eventsFor(db: Database, scenarioId: string): Promise<Dict[]> {
  const rows = await queryRows<Dict>(
    db,
    `SELECT event_id, operation_id, event_type, body, ${TS("created_at")} AS created_at FROM engine_observation_events WHERE scenario_id = $1 ORDER BY engine_observation_events.created_at, seq`,
    [scenarioId],
  );
  return rows.map((r) => ({ event_id: r.event_id, operation_id: r.operation_id, event_type: r.event_type, body: r.body, created_at: r.created_at }));
}

/** ルールの版は変えられない。同じ内容の再保存は何もせず、違う内容は拒否する。 */
export async function saveRulePack(db: Database, pack: Dict): Promise<void> {
  const body = canonicalJson(pack);
  const bodyHash = sha256Hex(body);
  await transaction(db, async (tx) => {
    const engineId = item(pack, "engine_id");
    const ruleVersion = item(pack, "rule_version");
    await tx.query("SELECT pg_advisory_xact_lock(hashtext($1))", [`engine.rule_pack:${engineId}:${ruleVersion}`]);
    const existing = await queryOne<{ body_hash: string }>(tx, "SELECT body_hash FROM engine_rule_packs WHERE engine_id = $1 AND rule_version = $2", [engineId, ruleVersion]);
    if (existing) {
      if (existing.body_hash !== bodyHash) throw new PyValueError("a rule_version is immutable; create a new rule_version for changes");
      return;
    }
    await tx.query(
      "INSERT INTO engine_rule_packs(engine_id, rule_version, body, body_hash, approved_by, effective_from, status) VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7)",
      [engineId, ruleVersion, body, bodyHash, pack.approved_by ?? null, pack.effective_from ?? null, pack.status ?? "unknown"],
    );
  });
}

export async function getRulePack(db: Database, engineId: string, ruleVersion: string): Promise<Dict | null> {
  const row = await queryOne<{ body: Dict }>(db, "SELECT body FROM engine_rule_packs WHERE engine_id = $1 AND rule_version = $2", [engineId, ruleVersion]);
  return row ? row.body : null;
}

export async function saveSnapshot(db: Database, snapshotId: string, scenarioId: string, ruleVersion: string, body: Dict): Promise<void> {
  await db.query("INSERT INTO engine_offline_snapshots(snapshot_id, scenario_id, rule_version, body) VALUES ($1, $2, $3, $4::jsonb)", [
    snapshotId, scenarioId, ruleVersion, pyJsonDumps(body, { ensureAscii: false }),
  ]);
}

export async function listPendingSnapshots(db: Database): Promise<Dict[]> {
  const rows = await queryRows<{ body: Dict }>(db, "SELECT body FROM engine_offline_snapshots WHERE sync_status = 'pending' ORDER BY created_at, seq");
  return rows.map((r) => r.body);
}

/** 同じ版のときだけ同期済みにする。版が違えば version_conflict のまま残す。 */
export async function markSnapshotSynced(db: Database, snapshotId: string, serverRuleVersion: string, accepted: boolean): Promise<string> {
  const row = await queryOne<{ rule_version: string }>(db, "SELECT rule_version FROM engine_offline_snapshots WHERE snapshot_id = $1", [snapshotId]);
  if (!row) throw new PyKeyError(snapshotId);
  if (row.rule_version !== serverRuleVersion) {
    await db.query("UPDATE engine_offline_snapshots SET sync_status = 'version_conflict' WHERE snapshot_id = $1", [snapshotId]);
    return "version_conflict";
  }
  const status = accepted ? "synced" : "rejected";
  await db.query("UPDATE engine_offline_snapshots SET sync_status = $1 WHERE snapshot_id = $2", [status, snapshotId]);
  return status;
}

/** 実績の訂正は理由つきで追記し、古い記録は更新しない。 */
export async function appendRevision(db: Database, revisionId: string, estimateId: string, supersedesRevisionId: string | null, reason: string, body: Dict): Promise<void> {
  if (!isStr(reason) || !reason.trim()) throw new PyValueError("revision reason is required");
  await db.query(
    "INSERT INTO engine_estimate_revisions(revision_id, estimate_id, supersedes_revision_id, reason, body) VALUES ($1, $2, $3, $4, $5::jsonb)",
    [revisionId, estimateId, supersedesRevisionId, reason, pyJsonDumps(body, { ensureAscii: false })],
  );
}

export async function listRevisions(db: Database, estimateId: string): Promise<Dict[]> {
  const rows = await queryRows<Dict>(
    db,
    `SELECT revision_id, supersedes_revision_id, reason, body, ${TS("created_at")} AS created_at FROM engine_estimate_revisions WHERE estimate_id = $1 ORDER BY engine_estimate_revisions.created_at, seq`,
    [estimateId],
  );
  return rows.map((r) => ({ revision_id: r.revision_id, supersedes_revision_id: r.supersedes_revision_id, reason: r.reason, body: r.body, created_at: r.created_at }));
}

/** 接続を束ねて EngineStore として使う。 */
export function engineStore(db: Database): EngineStore {
  return {
    saveEstimate: (id, result, key) => saveEstimate(db, id, result, key),
    getEstimate: (id) => getEstimate(db, id),
    listEstimates: (limit) => listEstimates(db, limit),
    recordEvent: (eventId, scenarioId, eventType, body, operationId) => recordEvent(db, eventId, scenarioId, eventType, body, operationId),
    eventsFor: (scenarioId) => eventsFor(db, scenarioId),
  };
}

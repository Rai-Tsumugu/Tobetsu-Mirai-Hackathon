// 統合版 工数見積もりエンジン（30案の良いところを1本の流れにまとめた決定版）。
// 元: src/30-algorithm/integrated/estimator.py（処理の順序・丸め・エラーメッセージを変えずに移した）
//
// 値の置き場所（このファイルは数値リテラルを持たない）:
// - 過去の実績 / 工場パラメータ / 基準工数 / 今回の入力 は引数で受け取る（JSON でも DB でもよい。man-hours-store.ts）
// - constants.ts      定義で決まる定数（和暦の起点、丸め桁、状態の選択肢など）
// - python-compat.ts  Python の sum / statistics / decimal の再現
//
// 全案共通のガードレール（docs/man-hours/system-ideas-30.md §1）:
// - 年式・走行距離・地域・季節だけで人時を増やさない。人時は観察した状態と工程に対応づける
// - 未確認を0として確定しない。typical に入れず high（上限）に入れる
// - 待機は経過時間にだけ入れる。暖房費・材料費は人時に足さない
// - 方式を平均しない。計算は提案で、確定は整備士・見積もり担当者が行う

import * as C from "./constants";
import {
  has,
  maxBy,
  pyFloatStr,
  pyInt,
  pyMean,
  pyMedian,
  pyRepr,
  pySum,
  quantizeToFloat,
  quantizeToInt,
  roundingMode,
  sortedBy,
  ValueError,
  type Obj,
  type RoundingMode,
} from "./python-compat";

export { ValueError };
export type { Obj };

const ERA_PATTERN = /^(\D+?)(\d+|元)年(\d+)月$/;

// ---------------------------------------------------------------- 共通の小道具

type RoundingKind = "hours" | "yen" | "percent";
const ROUNDING: Partial<Record<RoundingKind, { decimals: number; mode: RoundingMode }>> = {};

/** 丸め方は工場に確認する事項なので shop_params.rounding（変数）から読む。 */
function setRounding(params: Obj): void {
  const cfg = params.rounding;
  ROUNDING.hours = { decimals: cfg.hours_decimals, mode: roundingMode(cfg.hours_mode) };
  ROUNDING.yen = { decimals: cfg.yen_decimals, mode: roundingMode(cfg.yen_mode) };
  ROUNDING.percent = { decimals: cfg.percent_decimals, mode: roundingMode(cfg.percent_mode) };
}

function rounding(kind: RoundingKind): { decimals: number; mode: RoundingMode } {
  const found = ROUNDING[kind];
  if (!found) {
    throw new ValueError("丸め方が設定されていない");
  }
  return found;
}

function hours(value: number): number {
  const { decimals, mode } = rounding("hours");
  return quantizeToFloat(value, decimals, mode);
}

function yen(value: number): number {
  const { decimals, mode } = rounding("yen");
  return quantizeToInt(value, decimals, mode);
}

function percent(value: number): number {
  const { decimals, mode } = rounding("percent");
  return quantizeToFloat(value, decimals, mode);
}

function perBand<T>(fn: (band: C.BandName) => T): Record<C.BandName, T> {
  return { [C.LOW]: fn(C.LOW), [C.TYPICAL]: fn(C.TYPICAL), [C.HIGH]: fn(C.HIGH) } as Record<C.BandName, T>;
}

function roundedBands(values: Obj, rounder: (value: number) => number = hours): Record<C.BandName, number> {
  return perBand((band) => rounder(values[band]));
}

/** 先頭が _ の説明用キーを除く。 */
function publicEntries(mapping: Obj): [string, any][] { // eslint-disable-line @typescript-eslint/no-explicit-any
  return Object.entries(mapping).filter(([key]) => !key.startsWith("_"));
}

function publicKeys(mapping: Obj): string[] {
  return publicEntries(mapping).map(([key]) => key);
}

function first<T>(items: Iterable<T>): T {
  const next = items[Symbol.iterator]().next();
  if (next.done) {
    throw new ValueError("StopIteration");
  }
  return next.value;
}

function nonEmpty(items: { length: number } | null | undefined): boolean {
  return items !== null && items !== undefined && items.length > C.NO_COUNT;
}

function isIntegerValue(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function isNumberValue(value: unknown): value is number {
  return typeof value === "number";
}

function requireThat(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new ValueError(message);
  }
}

function isSubset<T>(subset: Iterable<T>, superset: Iterable<T>): boolean {
  const all = new Set(superset);
  return [...subset].every((item) => all.has(item));
}

function codePointLength(text: string): number {
  return [...text].length;
}

function normalizeState(text: unknown, params: Obj): string {
  /** 入力の先頭が状態の名前（shop_params.state_labels）と一致すれば、その状態の ID を返す。 */
  const labels = Object.fromEntries(publicEntries(params.state_labels)) as Record<string, string>;
  for (const stateId of sortedBy(Object.keys(labels), (key) => codePointLength(labels[key]), true)) {
    if (String(text).startsWith(labels[stateId])) {
      return stateId;
    }
  }
  throw new ValueError(`現車状態の選択肢にない値: ${text}`);
}

function stateLabel(stateId: string, params: Obj): string {
  return has(params.state_labels, stateId) ? params.state_labels[stateId] : stateId;
}

/** 辞書の `.get(key)`。ないときは None（null）。 */
function getOrNull(mapping: Obj, key: string): any { // eslint-disable-line @typescript-eslint/no-explicit-any
  return has(mapping, key) ? mapping[key] : null;
}

function validate(params: Obj, records: Obj, catalog: Obj, caseData: Obj): void {
  /** 変数ファイルと入力の整合を確かめる。書き間違いを黙って別の扱いにしないため。 */
  const jobs = new Set(Object.keys(catalog.jobs));
  const areas = new Set<string>(
    Object.values<Obj>(catalog.jobs).flatMap((job) => (has(job, "work_areas") ? job.work_areas : [])),
  );
  requireThat(nonEmpty(caseData.jobs), "今回の作業（jobs）が空");
  requireThat(isSubset(caseData.jobs, jobs), `今回の作業が基準工数にない: ${pyRepr(caseData.jobs)}`);
  for (const fastener of caseData.condition.fasteners) {
    requireThat(jobs.has(fastener.job), `締結部の作業が基準工数にない: ${fastener.id} ${fastener.job}`);
    requireThat(
      isIntegerValue(fastener.count) && fastener.count > C.NO_COUNT,
      `締結部の本数（count）が正の整数でない: ${fastener.id}`,
    );
  }
  const underbody = params.underbody;
  for (const [area, grade] of publicEntries(caseData.condition.underbody_rust_grade)) {
    requireThat(underbody.areas.includes(area), `下回りの部位名が未知: ${area}`);
    requireThat(
      grade === null || (isIntegerValue(grade) && underbody.grade_min <= grade && grade <= underbody.grade_max),
      `錆グレードは ${underbody.grade_min}〜${underbody.grade_max} の整数か null（未確認）にする: ${area} ${pyRepr(grade)}`,
    );
  }
  requireThat(isSubset(areas, underbody.areas), "基準工数の作業部位が下回りの部位名にない");
  const weight = caseData.vehicle.tire_with_wheel_weight_kg.value;
  requireThat(isNumberValue(weight), `タイヤ重量は数値にする: ${pyRepr(weight)}`);
  const ids = new Set(C.STATE_IDS);
  const sameSet = (keys: string[]) => keys.length === ids.size && keys.every((key) => ids.has(key));
  requireThat(sameSet(publicKeys(params.state_labels)), "state_labels の ID が constants.STATE_IDS と一致しない");
  requireThat(sameSet(publicKeys(params.state_treatment)), "state_treatment の ID が constants.STATE_IDS と一致しない");
  const tire = params.tire_handling;
  requireThat(
    isSubset(Object.values<string>(tire.weight_status_to_state), ids),
    "tire_handling.weight_status_to_state に未知の状態 ID がある",
  );

  const ops: Obj = params.provisional_rates_v1.ops;
  for (const rule of params.condition_rules) {
    requireThat(C.RULE_KINDS.includes(rule.kind), `condition_rules の kind が未知: ${rule.kind}`);
    requireThat(has(ops, rule.op), `condition_rules の op が暫定値にない: ${rule.op}`);
    requireThat(!has(rule, "job") || jobs.has(rule.job), `condition_rules の job が基準工数にない: ${rule.id} ${pyRepr(getOrNull(rule, "job"))}`);
    requireThat(
      !has(rule, "area") || areas.has(rule.area),
      `condition_rules の area が作業部位にない: ${rule.id} ${pyRepr(getOrNull(rule, "area"))}`,
    );
    if (rule.kind === C.RULE_SIDE_STATE && caseData.jobs.includes(rule.job)) {
      const sides = Object.keys(catalog.jobs[rule.job].sides);
      requireThat(
        isSubset(sides, Object.keys(caseData.condition[rule.path])),
        `左右の状態が足りない: ${rule.path} に ${pyRepr([...sides].sort())} が必要`,
      );
    }
  }
  for (const [tag, mapping] of publicEntries(params.tag_to_op)) {
    requireThat(C.TAG_UNITS.includes(mapping.unit), `tag_to_op の unit が未知: ${tag} ${mapping.unit}`);
    requireThat(has(ops, mapping.op), `tag_to_op の op が暫定値にない: ${tag} ${mapping.op}`);
    const entries: Obj[] = records.historical_records.filter((r: Obj) => has(r.tags, tag)).map((r: Obj) => r.tags[tag]);
    const counted = entries.filter((e) => has(e, "count"));
    requireThat(
      counted.every((e) => isIntegerValue(e.count) && e.count > C.NO_COUNT),
      `実績の count は正の整数にする: ${tag}`,
    );
    if (mapping.unit === C.TAG_UNIT_COUNT) {
      requireThat(counted.length === entries.length, `tag_to_op の unit は count だが、count のない実績がある: ${tag}`);
    } else {
      requireThat(!nonEmpty(counted), `tag_to_op の unit は visit だが、count のある実績がある: ${tag}`);
    }
  }
  requireThat(
    Object.values<string>(records.other_shop_tag_to_op).every((op) => has(ops, op)),
    "other_shop_tag_to_op の op が暫定値にない",
  );
  const treatment: Obj = Object.fromEntries(publicEntries(params.fastener_treatment));
  requireThat(
    isSubset(Object.values<string>(Object.fromEntries(publicEntries(params.fastener_rust_classes))), Object.keys(treatment)),
    "fastener_rust_classes のリスク区分が fastener_treatment にない",
  );
  requireThat(
    Object.values<Obj>(treatment).every((plan) =>
      C.BANDS.every((band) => plan[band].every(([op]: [string, string]) => has(ops, op))),
    ),
    "fastener_treatment の工程が暫定値にない",
  );
  const waits = params.waits;
  requireThat(
    Object.values<string>(waits.by_op).every((key) => has(waits.hours, key)),
    "waits.by_op の待機が waits.hours にない",
  );
  requireThat(C.RATE_TABLES.includes(params.adopted_rate_table), `adopted_rate_table が不正: ${params.adopted_rate_table}`);
  const similar = params.similar_case;
  requireThat(isSubset(similar.conditions, C.SIMILAR_CONDITIONS), "similar_case.conditions に未知の条件がある");
  requireThat(isSubset(similar.exclude_if_differs, similar.conditions), "exclude_if_differs が conditions にない");

  const rate = params.labor_rate;
  requireThat(
    [C.RATE_MODE_ANNUAL, C.RATE_MODE_SEASONAL].includes(rate.mode),
    `labor_rate.mode が不正: ${rate.mode}`,
  );
  requireThat(rate.cost_keys.includes(rate.heating_key), "labor_rate.heating_key が cost_keys に含まれていない");
  requireThat(rate.heating_winter_yen <= rate.cost_yen[rate.heating_key], "冬季の暖房費が年間の暖房費を超えている");
  const billable = rate.billable_hours;
  requireThat(
    billable.winter + billable.non_winter === billable.annual,
    "labor_rate.billable_hours の冬季＋冬季以外が年間と一致しない",
  );
}

// ---------------------------------------------------------------- 1. 車両情報（S26）

function parseYearMonth(text: unknown): [number, number] {
  const [yearText, monthText] = String(text).split(C.DATE_SEPARATOR);
  if (yearText === undefined || monthText === undefined) {
    throw new ValueError("not enough values to unpack");
  }
  return [pyInt(yearText), pyInt(monthText)];
}

function parseWareki(text: string): [number, number] {
  const match = ERA_PATTERN.exec(text);
  if (!match) {
    throw new ValueError(`初度登録年月を読めない: ${text}`);
  }
  const [, era, year, month] = match;
  const eraYear = year === C.ERA_FIRST_YEAR_LABEL ? C.ERA_FIRST_YEAR_NUMBER : pyInt(year);
  if (!has(C.ERA_START_YEAR, era)) {
    throw new ValueError(`未知の元号: ${era}`);
  }
  return [C.ERA_START_YEAR[era] + eraYear - C.ERA_YEAR_OFFSET, pyInt(month)];
}

function seasonOf(month: number, params: Obj): string {
  return params.season.winter_months.includes(month) ? C.SEASON_WINTER : C.SEASON_OTHER;
}

function vehicleInfo(caseData: Obj, params: Obj): Obj {
  const [regYear, regMonth] = parseWareki(caseData.e_shakensho["初度登録年月"]);
  const [inYear, inMonth] = parseYearMonth(caseData.intake.date);
  const months = (inYear - regYear) * C.MONTHS_PER_YEAR + (inMonth - regMonth);
  const firstRegistration = `${regYear}${C.DATE_SEPARATOR}${String(regMonth).padStart(C.MONTH_DIGITS, C.ZERO_PAD)}`;
  return {
    first_registration: firstRegistration,
    // 同一車両の照合キーは手入力にせず、電子車検証の型式と初度登録から作る（表記揺れを防ぐ）
    vehicle_key: `${caseData.e_shakensho["型式"]}${C.VEHICLE_KEY_SEPARATOR}${firstRegistration}`,
    elapsed_months: months,
    elapsed_years: Math.floor(months / C.MONTHS_PER_YEAR),
    odometer_km: caseData.vehicle.odometer_km,
    season: seasonOf(inMonth, params),
    imported: Object.fromEntries(
      Object.entries(caseData.e_shakensho).filter(([key]) => !params.e_shakensho_excluded.includes(key)),
    ),
    note: "初度登録年月は製造年ではない。使用者の情報は取り込まない",
  };
}

// ---------------------------------------------------------------- 2. 基準工数と重複排除（S17）

function baseEstimate(jobIds: string[], catalog: Obj, rates: Obj): Obj {
  const jobs: Obj[] = jobIds.map((jobId) => catalog.jobs[jobId]);
  const gross = pySum(jobs.map((job) => job.base_labor_hours));
  const shared = new Map<string, Obj[]>();
  for (const job of jobs) {
    for (const op of job.included_operations) {
      if (op.shared) {
        shared.set(op.op, [...(shared.get(op.op) ?? []), op]);
      }
    }
  }
  const deductions: Obj[] = [];
  for (const [opId, occurrences] of shared) {
    const repeats = occurrences.length - C.COUNTED_ONCE;
    if (repeats > C.NO_COUNT) {
      const sample = first(occurrences);
      deductions.push({ op: opId, name: sample.name, jobs: occurrences.length, deducted_hours: hours(sample.hours * repeats) });
    }
  }
  const deducted = pySum(deductions.map((d) => d.deducted_hours));
  const perVisitOps = Object.entries<Obj>(rates)
    .filter(([, rate]) => Boolean(rate.per_visit))
    .map(([opId]) => opId);
  const avoided = pySum(perVisitOps.map((opId) => rates[opId][C.TYPICAL])) * (jobIds.length - C.COUNTED_ONCE);
  return {
    jobs: jobIds.map((jobId) => ({
      id: jobId,
      name: catalog.jobs[jobId].name,
      base_labor_hours: catalog.jobs[jobId].base_labor_hours,
    })),
    gross_hours: hours(gross),
    deductions,
    base_hours: hours(gross - deducted),
    per_visit_ops: perVisitOps,
    per_visit_double_count_avoided_typical: hours(avoided),
    per_visit_note: "前処理を作業ごとに重ねた場合との差（参考）。前処理は入庫1回だけ計上しているので差し引きはしない",
    catalog_version: catalog.version,
  };
}

// ---------------------------------------------------------------- 4. 単価（S11・S12・S13）

function tagSamples(records: Obj[], tag: string, unit: string): number[] {
  const samples: number[] = [];
  for (const record of records) {
    const entry = getOrNull(record.tags, tag);
    // Python の `if entry:`（空の辞書は偽）
    if (entry && Object.keys(entry).length > C.NO_COUNT) {
      samples.push(unit === C.TAG_UNIT_COUNT ? entry.hours / entry.count : entry.hours);
    }
  }
  return samples;
}

const STATISTICS: Record<string, (values: number[]) => number> = {
  min: (values) => Math.min(...values),
  median: pyMedian,
  max: (values) => Math.max(...values),
};

function rateTables(params: Obj, records: Obj): [string, Obj, string, Obj, Obj[]] {
  const v1: Obj = params.provisional_rates_v1.ops;
  const rule = params.rate_update_rule;
  const v2: Obj = Object.fromEntries(
    Object.entries<Obj>(v1).map(([opId, rate]) => [opId, { ...rate, source: `暫定値（${C.RATE_TABLE_V1}）` }]),
  );
  const evidence: Obj[] = [];
  for (const [tag, mapping] of publicEntries(params.tag_to_op)) {
    const opId = mapping.op;
    const samples = tagSamples(records.historical_records, tag, mapping.unit);
    const enough = samples.length >= rule.min_records;
    const found = nonEmpty(samples);
    evidence.push({
      tag,
      op: opId,
      n: samples.length,
      min: found ? hours(Math.min(...samples)) : null,
      median: found ? hours(pyMedian(samples)) : null,
      max: found ? hours(Math.max(...samples)) : null,
      used_for_v2: enough,
    });
    if (enough) {
      v2[opId] = {
        ...v1[opId],
        ...Object.fromEntries(C.BANDS.map((band) => [band, STATISTICS[rule[band]](samples)])),
        source: `実績 ${samples.length} 件`,
      };
    }
  }
  const adoptedName: string = params.adopted_rate_table;
  const adopted = adoptedName === C.RATE_TABLE_V1 ? v1 : v2;
  const candidateName = adoptedName === C.RATE_TABLE_V1 ? C.RATE_TABLE_V2 : C.RATE_TABLE_V1;
  const candidate = adoptedName === C.RATE_TABLE_V1 ? v2 : v1;
  return [adoptedName, adopted, candidateName, candidate, evidence];
}

function otherShopBands(records: Obj, adopted: Obj): Obj[] {
  const bands: Obj[] = [];
  for (const [key, opId] of Object.entries<string>(records.other_shop_tag_to_op)) {
    const medians: number[] = Object.values<Obj>(records.other_shops)
      .filter((shop) => has(shop, key))
      .map((shop) => shop[key].median);
    if (!nonEmpty(medians)) {
      continue;
    }
    const own = adopted[opId][C.TYPICAL];
    bands.push({
      op: opId,
      other_shops_min: Math.min(...medians),
      other_shops_max: Math.max(...medians),
      own_typical: own,
      inside: Math.min(...medians) <= own && own <= Math.max(...medians),
      note: "参照幅だけに使う。他工場の値を自工場の値にしない",
    });
  }
  return bands;
}

// ---------------------------------------------------------------- 3. 工程の展開（S01・S02・S03・S05・S07・S15・S22）

function itemFromLevels(
  itemId: string,
  label: string,
  rule: Obj,
  state: string,
  quantity: number,
  opId: string,
  levels: Obj,
  rates: Obj,
): Obj {
  return {
    id: itemId,
    group: itemId,
    label,
    factor: getOrNull(rule, "factor"),
    from: getOrNull(rule, "from"),
    state_id: state,
    quantity,
    billable: rates[opId].billable,
    hours: perBand((band) => (levels[band] ? rates[opId][levels[band]] * quantity : C.NO_HOURS)),
    op_units: perBand((band) => (levels[band] ? { [opId]: quantity } : {})),
    elapsed_adjust: perBand(() => C.NO_HOURS),
  };
}

function ruleQuantity(rule: Obj, condition: Obj, catalog: Obj): number {
  const kind = rule.quantity;
  if (kind === C.QUANTITY_PER_VISIT) {
    return C.ONE_UNIT;
  }
  if (kind === C.QUANTITY_SIDES) {
    return Object.keys(catalog.jobs[rule.job].sides).length;
  }
  return condition[rule.path][kind]; // 観察した数（例: 氷塊のあるホイールハウスの数）
}

function workAreaGrades(jobIds: string[], catalog: Obj, condition: Obj): Record<string, number | null> {
  const grades = condition.underbody_rust_grade;
  const areas: string[] = jobIds.flatMap((jobId) => catalog.jobs[jobId].work_areas ?? []);
  return Object.fromEntries(areas.map((area) => [area, getOrNull(grades, area)]));
}

function gradeState(grade: number | null, minGrade: number): string {
  if (grade === null) {
    return C.STATE_UNCONFIRMED;
  }
  return grade >= minGrade ? C.STATE_PROBLEM : C.STATE_NOT_OBSERVED;
}

function conditionItems(caseData: Obj, params: Obj, catalog: Obj, rates: Obj, excluded?: string[]): Obj[] {
  const condition = caseData.condition;
  const jobIds: string[] = caseData.jobs;
  const treatment = params.state_treatment;
  const items: Obj[] = [];
  for (const rule of params.condition_rules) {
    if (rule.job && !jobIds.includes(rule.job)) {
      excluded?.push(
        `規則 ${rule.id}（${rates[rule.op].name}）: 作業 ${rule.job} が今回の作業に含まれないため計算から除外`,
      );
      continue;
    }
    const opId: string = rule.op;
    const name: string = rates[opId].name;
    if (rule.kind === C.RULE_SIDE_STATE) {
      for (const [sideKey, sideLabel] of Object.entries<string>(catalog.jobs[rule.job].sides)) {
        const state = normalizeState(condition[rule.path][sideKey], params);
        items.push(
          itemFromLevels(`${rule.id}:${sideKey}`, `${name}（${sideLabel}）`, rule, state, C.ONE_UNIT, opId, treatment[state], rates),
        );
      }
      continue;
    }
    let state: string;
    if (rule.kind === C.RULE_STATE) {
      state = normalizeState(condition[rule.path].state, params);
    } else if (rule.kind === C.RULE_AREA_GRADE) {
      state = gradeState(getOrNull(condition.underbody_rust_grade, rule.area), rule.min_grade);
    } else if (rule.kind === C.RULE_WORK_AREA_GRADE) {
      // 作業部位のうち最も進んだ錆。未確認の部位があれば上限に入れる
      const grades = Object.values(workAreaGrades(jobIds, catalog, condition));
      const known = grades.filter((g): g is number => g !== null);
      if (nonEmpty(known) && Math.max(...known) >= rule.min_grade) {
        state = C.STATE_PROBLEM;
      } else if (known.length < grades.length) {
        state = C.STATE_UNCONFIRMED;
      } else {
        state = C.STATE_NOT_OBSERVED;
      }
    } else {
      throw new ValueError(`condition_rules の kind が未知: ${rule.kind}`);
    }
    const quantity = ruleQuantity(rule, condition, catalog);
    items.push(itemFromLevels(rule.id, name, rule, state, quantity, opId, treatment[state], rates));
  }
  return items;
}

function fastenerClass(rustText: unknown, params: Obj): string {
  for (const [prefix, risk] of publicEntries(params.fastener_rust_classes)) {
    if (String(rustText).startsWith(prefix)) {
      return risk;
    }
  }
  throw new ValueError(`締結部の錆の区分にない値: ${rustText}`);
}

function fastenerItems(caseData: Obj, params: Obj, rates: Obj, excluded?: string[]): Obj[] {
  const items: Obj[] = [];
  const label = params.fastener_treatment._label;
  for (const fastener of caseData.condition.fasteners) {
    if (!caseData.jobs.includes(fastener.job)) {
      excluded?.push(`${fastener.name}: 作業 ${fastener.job} が今回の作業に含まれないため計算から除外`);
      continue;
    }
    const risk = fastenerClass(fastener.rust, params);
    const plan = params.fastener_treatment[risk];
    const count = fastener.count;
    items.push({
      id: `fastener:${fastener.id}`,
      group: `締結部（${risk}）`,
      label: fastener.name,
      factor: label.factor,
      from: label.from,
      state_id: risk,
      quantity: count,
      billable: C.BANDS.every((band) => plan[band].every(([op]: [string, string]) => rates[op].billable)),
      hours: perBand((band) => pySum(plan[band].map(([op, level]: [string, string]) => rates[op][level])) * count),
      op_units: perBand((band) => Object.fromEntries(plan[band].map(([op]: [string, string]) => [op, count]))),
      elapsed_adjust: perBand(() => C.NO_HOURS),
    });
  }
  return items;
}

function tireItem(caseData: Obj, params: Obj, catalog: Obj, unknowns: string[]): Obj | null {
  /** タイヤ重量で運搬の人数が変わる分（S07）。基準は1人運搬を前提にしている。 */
  const carrying: Obj[] = caseData.jobs.map((jobId: string) => catalog.jobs[jobId].tire_carry).filter(Boolean);
  if (!nonEmpty(carrying)) {
    return null;
  }
  const base = first(carrying);
  const rule = params.tire_handling;
  const weight = caseData.vehicle.tire_with_wheel_weight_kg;
  if (weight.value <= base.basis_max_wheel_kg) {
    return null;
  }
  if (weight.value <= rule.one_person_max_wheel_kg) {
    unknowns.push(
      `タイヤ（ホイール付き ${weight.value}kg）は基準の前提（${base.basis_max_wheel_kg}kg 以下）を超えるが、` +
        `1人で扱える範囲（${rule.one_person_max_wheel_kg}kg 以下）。運搬時間の差は未設定`,
    );
    return null;
  }
  const matches = Object.entries<string>(rule.weight_status_to_state)
    .filter(([prefix]) => String(weight.status).startsWith(prefix))
    .map(([, state]) => state);
  if (!nonEmpty(matches)) {
    throw new ValueError(`tire_handling.weight_status_to_state にない重量の状態: ${weight.status}`);
  }
  const state = first(matches);
  let labor: number;
  let elapsed: number;
  let how: string;
  if (rule.has_lifter) {
    if (rule.lifter_labor_hours === null) {
      unknowns.push("タイヤリフターを使う運搬の人時が未設定（shop_params.tire_handling.lifter_labor_hours）");
      return null;
    }
    labor = rule.lifter_labor_hours;
    elapsed = rule.lifter_labor_hours;
    how = "機材（タイヤリフター）";
  } else {
    const two = rule.two_person;
    labor = two.persons * two.hours_each;
    elapsed = two.hours_each;
    how = `${two.persons}人作業`;
  }
  const levels = params.state_treatment[state];
  const laborDelta = labor - base.labor_hours;
  const elapsedDelta = elapsed - base.labor_hours / base.persons;
  return {
    id: "tire_carry",
    group: "tire_carry",
    label: `タイヤ運搬を${how}にする差分（ホイール付き ${weight.value}kg）`,
    factor: rule.factor,
    from: rule.from,
    state_id: state,
    quantity: C.ONE_UNIT,
    billable: rule.billable,
    elapsed_reason: `${how}は運搬を同時に行うので、経過時間は1人あたりの時間になる（重量は${weight.status}）`,
    hours: perBand((band) => (levels[band] ? laborDelta : C.NO_HOURS)),
    op_units: perBand(() => ({})),
    elapsed_adjust: perBand((band) => (levels[band] ? elapsedDelta : C.NO_HOURS)),
  };
}

function outOfScopeUnknowns(caseData: Obj, params: Obj, catalog: Obj): string[] {
  const inScope = new Set(Object.keys(workAreaGrades(caseData.jobs, catalog, caseData.condition)));
  const notes: string[] = [];
  for (const [area, grade] of Object.entries(caseData.condition.underbody_rust_grade)) {
    if (area.startsWith("_") || inScope.has(area) || grade !== null) {
      continue;
    }
    notes.push(`${area}: 未確認。${has(params.out_of_scope_areas, area) ? params.out_of_scope_areas[area] : "作業範囲外"}`);
  }
  return notes;
}

// ---------------------------------------------------------------- 5. 3点見積もりと経過時間（S18・S19）

function totals(baseHours: number, items: Obj[], params: Obj, season: string): [Record<C.BandName, number>, Record<C.BandName, number>, Record<C.BandName, Obj>] {
  const labor = perBand((band) => baseHours + pySum(items.map((item) => item.hours[band])));
  const waitsCfg = params.waits;
  const variant = season === C.SEASON_WINTER ? C.WAIT_VARIANT_WINTER : C.WAIT_VARIANT_DEFAULT;

  const waitsFor = (band: C.BandName): Obj => {
    const ops = new Set<string>();
    for (const item of items) {
      for (const [op, units] of Object.entries<number>(item.op_units[band])) {
        if (units > C.NO_COUNT) {
          ops.add(op);
        }
      }
    }
    const keys = sortedBy(
      new Set([...ops].filter((op) => has(waitsCfg.by_op, op)).map((op) => waitsCfg.by_op[op] as string)),
      (key) => key,
    );
    const table = waitsCfg.hours;
    return Object.fromEntries(
      keys.map((key) => [key, has(table[key], variant) ? table[key][variant] : table[key][C.WAIT_VARIANT_DEFAULT]]),
    );
  };

  const waits = perBand(waitsFor);
  const elapsed = perBand(
    (band) =>
      labor[band] + pySum(items.map((i) => i.elapsed_adjust[band])) + pySum(Object.values<number>(waits[band])),
  );
  return [labor, elapsed, waits];
}

// ---------------------------------------------------------------- 6. 方式Bの類似実績（S08）

function ageBand(age: number, thresholds: number[]): number {
  return thresholds.filter((threshold) => age >= threshold).length;
}

const DIFF_LABELS: Record<string, string> = { [C.DIFF_MATCH]: "一致", [C.DIFF_DIFFERENT]: "相違", [C.DIFF_UNKNOWN]: "条件不明" };

function compareCondition(recordValue: unknown, caseValue: unknown): string {
  if (recordValue === null || recordValue === undefined || caseValue === null || caseValue === undefined) {
    return C.DIFF_UNKNOWN;
  }
  return recordValue === caseValue ? C.DIFF_MATCH : C.DIFF_DIFFERENT;
}

function sameVehicleRecordIds(vinfo: Obj, records: Obj): Set<string> {
  return new Set(
    records.vehicle_history.filter((h: Obj) => h.vehicle_key === vinfo.vehicle_key).map((h: Obj) => h.record_id as string),
  );
}

function similarCases(caseData: Obj, params: Obj, records: Obj, vinfo: Obj): Obj {
  const jobSet = new Set<string>(caseData.jobs);
  const cfg = params.similar_case;
  const thresholds: number[] = params.diff_log_age_bands;
  const ownRecords = sameVehicleRecordIds(vinfo, records);
  const now: Obj = {
    [C.CONDITION_BRAKE_RUST]: getOrNull(caseData.condition.underbody_rust_grade, cfg.rust_area),
    [C.CONDITION_AGE_BAND]: ageBand(vinfo.elapsed_years, thresholds),
    [C.CONDITION_SEASON]: vinfo.season,
  };
  const rows: Obj[] = [];
  const sameVehicleRows: Obj[] = [];
  for (const record of records.historical_records) {
    const recordJobs = new Set<string>(record.jobs);
    if (recordJobs.size !== jobSet.size || ![...recordJobs].every((job) => jobSet.has(job))) {
      continue;
    }
    const [, month] = parseYearMonth(record.date);
    const then: Obj = {
      [C.CONDITION_BRAKE_RUST]: record.brake_rust,
      [C.CONDITION_AGE_BAND]: ageBand(record.age_years, thresholds),
      [C.CONDITION_SEASON]: seasonOf(month, params),
    };
    const codes: Record<string, string> = Object.fromEntries(
      (cfg.conditions as string[]).map((key) => [key, compareCondition(then[key], now[key])]),
    );
    const row: Obj = {
      id: record.id,
      actual: record.actual,
      conditions: Object.fromEntries(
        Object.keys(codes).map((key) => [key, { result: DIFF_LABELS[codes[key]], record: then[key], now: now[key] }]),
      ),
    };
    if (cfg.exclude_same_vehicle && (record.same_vehicle || ownRecords.has(record.id))) {
      sameVehicleRows.push(row);
      continue;
    }
    const excluded = (cfg.exclude_if_differs as string[]).filter((key) => codes[key] === C.DIFF_DIFFERENT);
    rows.push({ ...row, adopted: !nonEmpty(excluded), excluded_by: excluded });
  }
  const actuals: number[] = rows.filter((row) => row.adopted).map((row) => row.actual);
  const enough = actuals.length >= cfg.min_records;
  let summary: Obj = perBand(() => null);
  if (nonEmpty(actuals)) {
    summary = { [C.LOW]: Math.min(...actuals), [C.TYPICAL]: pyMedian(actuals), [C.HIGH]: Math.max(...actuals) };
  }
  return {
    method: C.METHOD_B,
    n: actuals.length,
    enough_records: enough,
    labor_hours: nonEmpty(actuals) ? roundedBands(summary) : summary,
    cases: rows,
    same_vehicle_cases: sameVehicleRows,
    note:
      "実績には雪下ろし等すべての要因が含まれる。件数が足りなければ参考扱い。" +
      "同一車両の前回実績は集計に入れず別に示す（車の状態が変わっているため）",
  };
}

// ---------------------------------------------------------------- 7. 確認（S04・S06・S09・S16・S21・S23・S24）

function tierPoints(value: number, tiers: Obj[]): number {
  const points = tiers.filter((tier) => value >= tier.min).map((tier) => tier.points as number);
  return nonEmpty(points) ? Math.max(...points) : C.NO_POINTS;
}

function checks(caseData: Obj, params: Obj, catalog: Obj, records: Obj, vinfo: Obj, items: Obj[], outOfScope: string[]): Obj {
  const condition = caseData.condition;
  const intensityCfg = params.check_intensity;
  const strong = vinfo.elapsed_years >= intensityCfg.age_years || vinfo.odometer_km >= intensityCfg.odometer_km;

  const weatherCfg = params.weather_prompt;
  const forecast = caseData.weather_forecast;
  const weatherPrompt =
    forecast.min_temp_c <= weatherCfg.min_temp_c_le || forecast.snowfall_forecast_cm >= weatherCfg.snowfall_cm_ge;

  const history: Obj[] = records.vehicle_history.filter((h: Obj) => h.vehicle_key === vinfo.vehicle_key);
  const latest: Obj | null = nonEmpty(history) ? maxBy(history, (h) => parseYearMonth(h.date)) : null;

  const scoreCfg = params.priority_score;
  const grades = Object.values(workAreaGrades(caseData.jobs, catalog, condition)).filter((g): g is number => g !== null);
  const unconfirmed = items.filter((i) => i.hours[C.TYPICAL] === C.NO_HOURS && i.hours[C.HIGH] > C.NO_HOURS);
  const breakdown: Record<string, number> = {
    経過年数: tierPoints(vinfo.elapsed_years, scoreCfg.age_years),
    走行距離: tierPoints(vinfo.odometer_km, scoreCfg.odometer_km),
    作業部位の錆グレード: nonEmpty(grades) ? tierPoints(Math.max(...grades), scoreCfg.work_area_rust_grade) : C.NO_POINTS,
    未確認の部位あり: nonEmpty(unconfirmed) || nonEmpty(outOfScope) ? scoreCfg.unconfirmed_area_exists : C.NO_POINTS,
    防錆施工歴: condition.rustproof_undercoat.value ? scoreCfg.rustproof_coat_history : C.NO_POINTS,
    前回の固着記録:
      latest && nonEmpty(latest.observed.seized_fasteners) ? scoreCfg.previous_seizure_record : C.NO_POINTS,
  };
  const score = pySum(Object.values(breakdown));
  const band = maxBy(
    (scoreCfg.bands as Obj[]).filter((b) => score >= b.min),
    (b) => b.min,
  );

  const checklist = sortedBy(
    unconfirmed.map((i) => ({
      item: i.label,
      state: i.state,
      high_only_hours: hours(i.hours[C.HIGH] - i.hours[C.TYPICAL]),
    })),
    (row) => row.high_only_hours,
    true,
  );

  const required: string[] = caseData.jobs.flatMap((jobId: string) =>
    has(params.photo_required_shots, jobId) ? params.photo_required_shots[jobId] : [],
  );
  const taken = required.filter((shot) => caseData.photos.taken.includes(shot));
  const aiRows: Obj[] = caseData.photos.ai_items.filter(
    (row: Obj) => row.ai_grade !== null && row.mechanic_grade !== null,
  );
  const aiAgree = aiRows.filter((row) => row.ai_grade === row.mechanic_grade);

  let sameVehicle: Obj | null = null;
  if (latest) {
    const compareAreas: Obj = Object.fromEntries(publicEntries(params.vehicle_history_compare));
    const fasteners: Obj = Object.fromEntries(condition.fasteners.map((f: Obj) => [f.id, f]));
    sameVehicle = {
      previous_record: latest.record_id,
      previous_date: latest.date,
      km_since_previous: vinfo.odometer_km - latest.odometer_km,
      grades: Object.fromEntries(
        Object.entries<string>(compareAreas).map(([key, area]) => [
          key,
          { previous: latest.observed[key], now: getOrNull(condition.underbody_rust_grade, area) },
        ]),
      ),
      previously_seized_now: (latest.observed.seized_fasteners as string[])
        .filter((fid) => has(fasteners, fid))
        .map((fid) => ({ id: fid, now: fastenerClass(fasteners[fid].rust, params) })),
      note: "前回の実績値はそのまま使わない。前回固着した箇所と錆の進行を確認箇所として示す",
    };
  }

  return {
    check_intensity: {
      level: strong ? "強" : "通常",
      extra_items: strong ? intensityCfg.extra_items : [],
      note: "経過年数・走行距離は確認の強さだけに使い、人時は増やさない",
    },
    weather_prompt: {
      prompt: weatherPrompt,
      forecast,
      note: "気象は確認を促すだけ。前処理の人時は入庫時の現車確認で決める",
    },
    priority: {
      score,
      breakdown,
      band: band.name,
      when: band.when,
      note: "確認の順番と時期に使う。人時には変換しない",
    },
    checklist,
    out_of_scope: outOfScope,
    photos: {
      required: required.length,
      taken: taken.length,
      coverage_percent: nonEmpty(required) ? percent((taken.length / required.length) * C.PERCENT) : null,
      missing: Object.fromEntries(
        required
          .filter((shot) => !taken.includes(shot))
          .map((shot) => [shot, has(caseData.photos.missing_reason, shot) ? caseData.photos.missing_reason[shot] : ""]),
      ),
    },
    ai_classification: {
      compared: aiRows.length,
      agree: aiAgree.length,
      disagree: aiRows.filter((row) => !aiAgree.includes(row)).map((row) => row.area),
      note: "計算には整備士の確定値だけを使う",
    },
    same_vehicle: sameVehicle,
  };
}

// ---------------------------------------------------------------- 8. 金額・条件付き・顧客向け（S20・S22・S27・S28・S29）

function laborRates(params: Obj, season: string): [Obj, number] {
  const cfg = params.labor_rate;
  const totalCost = pySum((cfg.cost_keys as string[]).map((key) => cfg.cost_yen[key] as number));
  const billable = cfg.billable_hours;
  const annual = totalCost / billable.annual;
  const heating = cfg.cost_yen[cfg.heating_key];
  const withoutHeating = (totalCost - heating) / billable.annual;
  const winter = withoutHeating + cfg.heating_winter_yen / billable.winter;
  const nonWinter = withoutHeating + (heating - cfg.heating_winter_yen) / billable.non_winter;
  let applied: number;
  if (cfg.mode === C.RATE_MODE_ANNUAL) {
    applied = annual;
  } else {
    applied = season === C.SEASON_WINTER ? winter : nonWinter;
  }
  return [
    {
      mode: cfg.mode,
      applied_yen_per_hour: yen(applied),
      annual_yen_per_hour: yen(annual),
      seasonal_winter_yen_per_hour: yen(winter),
      seasonal_non_winter_yen_per_hour: yen(nonWinter),
      note: "暖房費は人時に足さず、時間単価の側で扱う。配賦方法は工場の経営判断",
    },
    applied,
  ];
}

function materials(params: Obj, items: Obj[]): Record<C.BandName, number> {
  const cfg = params.materials;
  const prices = cfg.prices;

  const cost = (band: C.BandName): number => {
    let total: number = C.NO_YEN;
    for (const item of items) {
      for (const [op, units] of Object.entries<number>(item.op_units[band])) {
        for (const material of has(cfg.by_op, op) ? (cfg.by_op[op] as string[]) : []) {
          const price = prices[material];
          total += (price.price_yen / price.uses) * units;
        }
      }
    }
    return total;
  };

  return roundedBands(perBand(cost), yen);
}

function isConditional(item: Obj): boolean {
  /** 発生するかどうか分からない追加: typical にない工程が high で加わるもの（未確認・折れ込み等）。 */
  const typicalOps = new Set(Object.keys(item.op_units[C.TYPICAL]));
  const onlyHigh = Object.keys(item.op_units[C.HIGH]).filter((op) => !typicalOps.has(op));
  return nonEmpty(onlyHigh) || (item.hours[C.TYPICAL] === C.NO_HOURS && item.hours[C.HIGH] > C.NO_HOURS);
}

function conditionalQuote(items: Obj[], params: Obj, rate: number): Obj {
  const threshold = params.contact_threshold;
  const groups = new Map<string, Obj[]>();
  for (const item of items.filter(isConditional)) {
    groups.set(item.group, [...(groups.get(item.group) ?? []), item]);
  }
  const rows: Obj[] = [];
  for (const [group, members] of groups) {
    const extra = pySum(members.map((i) => i.hours[C.HIGH] - i.hours[C.TYPICAL]));
    const extraYen =
      pySum(members.filter((i) => i.billable).map((i) => i.hours[C.HIGH] - i.hours[C.TYPICAL])) * rate;
    const label = members.length > C.ONE_UNIT ? group : first(members).label;
    rows.push({
      condition: label,
      items: members.map((i) => i.label),
      state: first(members).state,
      extra_hours: hours(extra),
      extra_yen: yen(extraYen),
      contact_before_work: extra > threshold.labor_hours_gt || extraYen > threshold.yen_gt,
    });
  }
  const sortedRows = sortedBy(rows, (row) => row.extra_hours, true);
  return {
    confirmed_typical_basis: "typical に入っている工程は見積もりに含める。追加金額は請求する工程の分だけ",
    conditions: sortedRows,
    all_conditions_extra_hours: hours(pySum(sortedRows.map((row) => row.extra_hours))),
    note: "条件が発生したら記録し、作業前連絡が「要」なら顧客の了承を得てから作業する",
  };
}

function companionParts(params: Obj, items: Obj[]): Obj {
  const cfg = params.companion_parts;
  const estimatedOps = new Set<string>(items.flatMap((item) => C.BANDS.flatMap((band) => Object.keys(item.op_units[band]))));
  const shown: Obj[] = [];
  const reference: Obj[] = [];
  for (const [name, part] of Object.entries<Obj>(cfg.items)) {
    const row = {
      part: name,
      freq: part.freq,
      same_op_in_estimate: has(part, "op") && estimatedOps.has(part.op),
      labor_hours_each: getOrNull(part, "labor_hours_each"),
      note: has(part, "note") ? part.note : "",
    };
    (part.freq >= cfg.display_threshold ? shown : reference).push(row);
  }
  return {
    shown,
    reference_below_threshold: reference,
    note: "候補は見積もり本体に入れない。観察で必要が分かったものだけ工程として入る",
  };
}

function customerSheet(base: Obj, items: Obj[]): Obj[] {
  const lines: Obj[] = (base.jobs as Obj[]).map((job) => ({
    line: `基準作業: ${job.name}`,
    typical: job.base_labor_hours,
    high: job.base_labor_hours,
    basis: "基準工数",
  }));
  for (const d of base.deductions as Obj[]) {
    lines.push({ line: `共通工程の重複分: ${d.name}`, typical: -d.deducted_hours, high: -d.deducted_hours, basis: "同時作業で1回だけ計上" });
  }
  for (const item of items) {
    const basis = { basis: `現車の状態: ${item.state}`, billed: item.billable };
    if (item.hours[C.TYPICAL] > C.NO_HOURS) {
      const upper = isConditional(item) ? item.hours[C.TYPICAL] : item.hours[C.HIGH];
      lines.push({ line: `見込む追加: ${item.label}`, typical: hours(item.hours[C.TYPICAL]), high: hours(upper), ...basis });
    }
    if (isConditional(item)) {
      lines.push({
        line: `発生した場合だけの追加: ${item.label}`,
        typical: C.NO_HOURS,
        high: hours(item.hours[C.HIGH] - item.hours[C.TYPICAL]),
        ...basis,
      });
    }
  }
  return lines;
}

// ---------------------------------------------------------------- 9. 記録の分析（S10・S14・S25）

function diffLog(params: Obj, records: Obj): Obj {
  const thresholds: number[] = params.diff_log_age_bands;
  const groups = new Map<string, { season: string; bandIndex: number; members: Obj[] }>();
  for (const record of records.historical_records) {
    const [, month] = parseYearMonth(record.date);
    const season = seasonOf(month, params);
    const bandIndex = ageBand(record.age_years, thresholds);
    const key = JSON.stringify([season, bandIndex]);
    const group = groups.get(key) ?? { season, bandIndex, members: [] };
    group.members.push(record);
    groups.set(key, group);
  }
  const rows: Obj[] = [];
  for (const { season, bandIndex, members } of sortedBy(groups.values(), (g) => [g.season, g.bandIndex])) {
    const diffs = members.map((r) => r.actual - r.estimate);
    const tags = new Map<string, number>();
    for (const record of members) {
      for (const [tag, entry] of Object.entries<Obj>(record.tags)) {
        tags.set(tag, (tags.get(tag) ?? C.NO_HOURS) + entry.hours);
      }
    }
    rows.push({
      season,
      age_band: bandIndex,
      n: members.length,
      mean_diff: hours(pyMean(diffs)),
      median_diff: hours(pyMedian(diffs)),
      tag_hours: Object.fromEntries([...tags].map(([tag, value]) => [tag, hours(value)])),
    });
  }
  return {
    age_band_thresholds_years: thresholds,
    rows,
    note: "区分ごとの差を人時に足すと季節・年式による一律加算になるので、単価の更新（v2）の元データとしてだけ使う",
  };
}

function tapLogSummary(records: Obj): Obj {
  const out: Obj = {};
  for (const [logId, steps] of Object.entries<Obj[]>(records.tap_logs)) {
    const work = steps.filter((s) => !s.wait);
    out[logId] = {
      labor_hours: hours(pySum(work.map((s) => s.persons * s.hours))),
      wait_hours: hours(pySum(steps.filter((s) => s.wait).map((s) => s.hours))),
      elapsed_hours: hours(pySum(steps.map((s) => s.hours))),
    };
  }
  return out;
}

function voiceMemoTags(params: Obj, memo: string): Obj {
  const dictionary = publicEntries(params.voice_memo_tags) as [string, string[]][];
  const rows: Obj[] = [];
  for (const sentence of memo
    .split(C.SENTENCE_DELIMITER)
    .map((s) => s.trim())
    .filter((s) => s)) {
    let remaining = sentence;
    const tags: string[] = [];
    for (const [tag, words] of dictionary) {
      for (const word of words) {
        if (remaining.includes(word)) {
          tags.push(tag);
          remaining = remaining.replaceAll(word, "");
        }
      }
    }
    rows.push({ sentence, tags });
  }
  return { rows, note: "振り分けは候補。整備士が確認してから実績（records.json）に記録する" };
}

// ---------------------------------------------------------------- 全体

export type EstimateInputs = { case: Obj; params: Obj; catalog: Obj; records: Obj };

/**
 * 見積もりを計算する。入力は変更しない。
 * 同期処理で、丸め方はこの呼び出しの間だけモジュール内に保持する。
 */
export function estimate(caseData: Obj, params: Obj, catalog: Obj, records: Obj): Obj {
  validate(params, records, catalog, caseData);
  setRounding(params);
  const vinfo = vehicleInfo(caseData, params);
  const [adoptedName, rates, candidateName, candidate, rateEvidence] = rateTables(params, records);
  const base = baseEstimate(caseData.jobs, catalog, rates);

  const unknowns: string[] = [];
  const excluded: string[] = [];
  const items = [...conditionItems(caseData, params, catalog, rates, excluded), ...fastenerItems(caseData, params, rates, excluded)];
  const tire = tireItem(caseData, params, catalog, unknowns);
  if (tire) {
    items.push(tire);
  }
  for (const item of items) {
    item.state = stateLabel(item.state_id, params);
  }
  const outOfScope = outOfScopeUnknowns(caseData, params, catalog);
  unknowns.push(...outOfScope);

  const [labor, elapsed, waits] = totals(base.base_hours, items, params, vinfo.season);
  const candidateItems = [...conditionItems(caseData, params, catalog, candidate), ...fastenerItems(caseData, params, candidate)];
  const [candidateLabor] = totals(base.base_hours, [...candidateItems, ...(tire ? [tire] : [])], params, vinfo.season);

  const [rateInfo, appliedRate] = laborRates(params, vinfo.season);
  const billed = perBand((band) => labor[band] - pySum(items.filter((i) => !i.billable).map((i) => i.hours[band])));
  return {
    case_id: caseData.case_id,
    status: "提案（未確定）。確定は整備士・見積もり担当者が行い、修正理由を残す",
    vehicle: vinfo,
    estimate: {
      method: C.METHOD_A_C,
      labor_hours: roundedBands(labor),
      billed_hours: roundedBands(billed),
      elapsed_hours: roundedBands(elapsed),
      waits_hours: perBand((band) => Object.fromEntries(Object.entries(waits[band]).map(([k, v]) => [k, hours(v)]))),
      rate_table: adoptedName,
      note: "typical は観察済みの状態から見込む値。high はこの見積もりの範囲での上限で、未確認項目の上限を含む",
    },
    base,
    items: items.map((item) => ({
      ...item,
      hours: roundedBands(item.hours),
      elapsed_adjust: roundedBands(item.elapsed_adjust),
    })),
    method_comparison: {
      a_c: { labor_hours: roundedBands(labor), basis: "基準工数＋現車の状態から展開した工程" },
      b: similarCases(caseData, params, records, vinfo),
      note: "方式を平均しない。担当者が選ぶか手で入力し、理由を残す",
    },
    rates: {
      adopted: adoptedName,
      candidate: candidateName,
      candidate_labor_hours: roundedBands(candidateLabor),
      evidence: rateEvidence,
      other_shops: otherShopBands(records, rates),
      note: "候補の版は自動で適用しない。整備士が承認した版を shop_params.adopted_rate_table に書く",
    },
    checks: checks(caseData, params, catalog, records, vinfo, items, outOfScope),
    conditional_quote: conditionalQuote(items, params, appliedRate),
    money: {
      labor_rate: rateInfo,
      labor_yen: roundedBands(perBand((band) => billed[band] * appliedRate), yen),
      labor_yen_basis: "請求人時（請求しない工程を除く）× 時間単価",
      materials_yen: materials(params, items),
      note: "材料費・部品代は工賃と別に記載する",
    },
    companion_parts: companionParts(params, items),
    customer_sheet: customerSheet(base, items),
    analysis: {
      diff_log: diffLog(params, records),
      tap_logs: tapLogSummary(records),
      voice_memo: voiceMemoTags(params, has(caseData, "voice_memo") ? caseData.voice_memo : ""),
    },
    unknowns,
    excluded_from_this_job: excluded,
    data_versions: {
      shop_params: params.version,
      job_catalog: catalog.version,
      records: records.historical_records.length,
    },
  };
}

/**
 * estimate を呼び、入力の形が違って起きた TypeError などを、画面に出せる日本語の ValueError にして投げ直す。
 * ValueError（元の Python の ValueError と同じ条件）はそのまま通す。
 */
export function estimateSafely(caseData: Obj, params: Obj, catalog: Obj, records: Obj): Obj {
  try {
    return estimate(caseData, params, catalog, records);
  } catch (error) {
    if (error instanceof ValueError) {
      throw error;
    }
    const detail = error instanceof Error ? error.message : String(error);
    throw new ValueError(`入力 JSON の形式が正しくありません（必要な項目がないか、値の型が違います）: ${detail}`);
  }
}

/** 補正表 v1（暫定値）と v2（実績から作った候補）。承認で DB に作る候補の元になる。 */
export function buildRateTables(params: Obj, records: Obj): { v1: Obj; v2: Obj } {
  setRounding(params);
  const [, , , candidate] = rateTables({ ...params, adopted_rate_table: C.RATE_TABLE_V1 }, records);
  return { v1: params.provisional_rates_v1.ops, v2: candidate };
}

/** Python の str(値)。None・float を元の表記にそろえる（Markdown の表で使う）。 */
function cell(value: unknown): string {
  if (value === null || value === undefined) {
    return "None";
  }
  return String(value);
}

function floatCell(value: unknown): string {
  return typeof value === "number" ? pyFloatStr(value) : cell(value);
}

export function toMarkdown(result: Obj): string {
  const est = result.estimate;
  const b = result.method_comparison.b;
  const bands = (values: Obj, format: (value: unknown) => string) => C.BANDS.map((k) => format(values[k])).join(" | ");
  const rows: string[] = [
    `# 見積もり結果 ${result.case_id}（${result.status}）`,
    "",
    `- 車両: 初度登録 ${result.vehicle.first_registration}（${result.vehicle.elapsed_years}年）、` +
      `${result.vehicle.odometer_km}km、${result.vehicle.season}`,
    `- 基準: ${floatCell(result.base.gross_hours)} 人時 → 重複控除後 ${floatCell(result.base.base_hours)} 人時（基準 ${result.base.catalog_version}）`,
    "",
    "| 区分 | low | typical | high |",
    "|---|---|---|---|",
    `| 人時（${est.method}） | ${bands(est.labor_hours, floatCell)} |`,
    `| 請求人時（請求しない工程を除く） | ${bands(est.billed_hours, floatCell)} |`,
    `| 経過時間 | ${bands(est.elapsed_hours, floatCell)} |`,
    `| 人時（${b.method}、${b.n}件） | ${bands(b.labor_hours, floatCell)} |`,
    `| 工賃（円） | ${bands(result.money.labor_yen, cell)} |`,
    `| 材料費（円） | ${bands(result.money.materials_yen, cell)} |`,
    "",
    "## 内訳",
    "",
    "| 項目 | 状態 | low | typical | high | 案 |",
    "|---|---|---|---|---|---|",
  ];
  for (const i of result.items as Obj[]) {
    rows.push(`| ${i.label} | ${i.state} | ${bands(i.hours, floatCell)} | ${cell(i.from)} |`);
  }
  rows.push("", "## 作業前に連絡する条件", "", "| 条件 | 追加人時 | 追加金額 | 作業前連絡 |", "|---|---|---|---|");
  for (const q of result.conditional_quote.conditions as Obj[]) {
    rows.push(`| ${q.condition} | ${floatCell(q.extra_hours)} | ${cell(q.extra_yen)} | ${q.contact_before_work ? "要" : "不要"} |`);
  }
  rows.push("", "## 未確認・範囲外", "");
  for (const u of result.unknowns as string[]) {
    rows.push(`- ${u}`);
  }
  return `${rows.join("\n")}\n`;
}

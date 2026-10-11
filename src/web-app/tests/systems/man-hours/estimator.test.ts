// 統合版エンジンのテスト（元: src/30-algorithm/integrated/test_estimator.py）。
// 期待値（2.35 など）は data/ の架空値から手計算した値。計算式はテストのコメントに書く。
/* eslint-disable @typescript-eslint/no-explicit-any -- JSON データを辞書として書き換えるテスト */
import { describe, expect, it } from "vitest";
import * as C from "../../../lib/systems/man-hours/constants";
import { estimate, estimateSafely, ValueError, type Obj } from "../../../lib/systems/man-hours/estimator";
import { loadJsonData } from "../../../lib/systems/man-hours/json-data";

type Data = ReturnType<typeof loadJsonData>;

/** 同梱の JSON を複製し、書き換えてから計算する。 */
function run(mutate?: (data: Data) => void): Obj {
  const data = loadJsonData();
  mutate?.(data);
  return estimate(data.case, data.params, data.catalog, data.records);
}

const result = run();
const itemsById = (r: Obj): Record<string, any> => Object.fromEntries(r.items.map((i: Obj) => [i.id, i]));

describe("手計算した値", () => {
  it("基準工数の重複排除", () => {
    // 0.6 + 1.4 = 2.0、共通工程（リフト 0.1、前2輪 0.2）を1回分控除して 1.7
    expect(result.base.gross_hours).toBe(2.0);
    expect(result.base.base_hours).toBe(1.7);
  });

  it("人時（3点見積もり）", () => {
    // low  = 1.7 + 前処理(0.10+0.10+0.15) + 重2本×0.05 + ハブ2×0.05 + 左ブーツ0.10 = 2.35
    // typ  = 1.7 + 前処理(0.15+0.16+0.20) + 重中4本×0.15 + ハブ2×0.10 + 左ブーツ0.15 + 運搬0.08 = 3.24
    // high = 1.7 + 前処理(0.25+0.30+0.30) + 重2×(0.30+1.50+0.50) + 中2×0.30 + 未確認4×0.30
    //        + ハブ2×0.15 + ローター2×0.40 + ブーツ2×0.20 + 運搬0.08 = 10.53
    expect(result.estimate.labor_hours).toEqual({ low: 2.35, typical: 3.24, high: 10.53 });
  });

  it("経過時間", () => {
    // 待機 = 融解0.5 + 浸透0.25 + 防錆乾燥（冬季）0.3 = 1.05。2人運搬で経過は 0.12→0.10（-0.02）
    expect(result.estimate.elapsed_hours).toEqual({ low: 3.4, typical: 4.27, high: 11.56 });
  });

  it("方式Bは平均しない", () => {
    const b = result.method_comparison.b;
    // J1+J2 の実績 R08 2.3, R09 3.0, R10 2.4。同一車両の前回 R11（1.9）は集計に入れず別に示す
    expect(b.n).toBe(3);
    expect(b.labor_hours).toEqual({ low: 2.3, typical: 2.4, high: 3.0 });
    expect(b.same_vehicle_cases.map((row: Obj) => row.id)).toEqual(["R11"]);
    expect(JSON.stringify(result.method_comparison)).not.toContain("average");
  });

  it("請求しない洗浄は人時だが請求人時に入らない", () => {
    // 下回り洗浄（請求しない）0.15 / 0.20 / 0.30 だけ請求人時が少ない
    expect(result.estimate.billed_hours).toEqual({ low: 2.2, typical: 3.04, high: 10.23 });
    // 工賃 = 請求人時 × 8,000
    expect(result.money.labor_yen).toEqual({ low: 17600, typical: 24320, high: 81840 });
  });

  it("時間単価", () => {
    const rate = result.money.labor_rate;
    // 年間経費 28,800,000 円 ÷ 年間請求人時 3,600 = 8,000 円/人時
    expect(rate.annual_yen_per_hour).toBe(8000);
    // 冬季だけに暖房費を配賦: 27,000,000/3,600 + 1,700,000/1,450 = 8,672.4
    expect(rate.seasonal_winter_yen_per_hour).toBe(8672);
  });

  it("材料費は四捨五入", () => {
    // low = 浸透剤・ガス (98+30)×2 + 防錆 206.25×2 + ブーツ 1,200 = 1,868.5 → 四捨五入で 1,869
    expect(result.money.materials_yen.low).toBe(1869);
  });

  it("実績から補正表の候補を作る", () => {
    const evidence = Object.fromEntries(result.rates.evidence.map((row: Obj) => [row.tag, row]));
    // 固着対応の1本あたり実績 8件の中央値 0.15
    expect(evidence["固着対応"].n).toBe(8);
    expect(evidence["固着対応"].median).toBe(0.15);
    expect(evidence["ボルト折れ"].used_for_v2).toBe(false); // 1件しかない
  });

  it("和暦から経過年数", () => {
    expect(result.vehicle.first_registration).toBe("2014-01");
    expect(result.vehicle.elapsed_years).toBe(13);
  });

  it("確認優先度", () => {
    // 経過年数2 + 走行1 + 錆グレード3 + 未確認1 + 防錆1 + 前回固着2 = 10 → 高
    expect(result.checks.priority.score).toBe(10);
    expect(result.checks.priority.band).toBe("高");
  });
});

describe("変数（data/）を書き換えると結果が変わる", () => {
  it("新しい実績で方式Bと候補が変わり、採用中の補正表は変わらない", () => {
    const before = run();
    const after = run((d) => {
      d.records.historical_records.push({
        id: "R13", date: "2027-02", body: "SUV", drive: "4WD", age_years: 13, km: 130000, brake_rust: 3,
        jobs: ["J1", "J2"], estimate: 1.7, actual: 4.0, tags: { ボルト折れ: { hours: 0.9, count: 1 } },
      });
    });
    expect(before.method_comparison.b.labor_hours).not.toEqual(after.method_comparison.b.labor_hours);
    expect(before.estimate.labor_hours).toEqual(after.estimate.labor_hours);
  });

  it("v2 を採用すると実績から作った候補の値になる", () => {
    const adopted = run((d) => {
      d.params.adopted_rate_table = C.RATE_TABLE_V2;
    });
    expect(adopted.estimate.labor_hours).toEqual(run().rates.candidate_labor_hours);
  });

  it("暫定値を変えると人時が変わる", () => {
    const changed = run((d) => {
      d.params.provisional_rates_v1.ops["PRE-SNOW"].typical += 0.1;
    });
    expect(changed.estimate.labor_hours.typical).toBeCloseTo(run().estimate.labor_hours.typical + 0.1, 2);
  });

  it("丸め方は変数", () => {
    const floored = run((d) => {
      d.params.rounding.yen_mode = "ROUND_FLOOR";
    });
    expect(floored.money.materials_yen.low).toBe(1868); // 1,868.5 円 → 切り捨て
  });

  it("方式Bの除外条件", () => {
    const b = run((d) => {
      d.params.similar_case.exclude_if_differs = ["brake_rust"];
    }).method_comparison.b;
    // ブレーキ周りの錆が相違する R08 を除くと R09・R10 の2件で、最小件数3に届かない
    expect(b.n).toBe(2);
    expect(b.enough_records).toBe(false);
  });

  it("基準工数の版", () => {
    const changed = run((d) => {
      d.catalog.jobs.J2.base_labor_hours = 1.5;
    });
    expect(changed.base.base_hours).toBe(1.8);
  });
});

describe("書き間違いは黙って別の扱いにせずエラーにする", () => {
  const rejected = (name: string, mutate: (data: Data) => void) =>
    it(name, () => {
      expect(() => run(mutate)).toThrow(ValueError);
    });

  rejected("未知の規則の種類", (d) => {
    d.params.condition_rules[C.NO_COUNT].kind = "stat";
  });
  rejected("未知の実績タグの単位", (d) => {
    d.params.tag_to_op["固着対応"].unit = "per_bolt";
  });
  rejected("暖房費のキーが経費の一覧にない", (d) => {
    const keys: string[] = d.params.labor_rate.cost_keys;
    keys.splice(keys.indexOf(d.params.labor_rate.heating_key), C.ONE_UNIT);
  });
  rejected("未知の補正表", (d) => {
    d.params.adopted_rate_table = "V2";
  });
  rejected("現車状態の選択肢にない値", (d) => {
    d.case.condition.snow_on_body.state = "多い";
  });
  rejected("タイヤ重量の状態が未知", (d) => {
    d.case.vehicle.tire_with_wheel_weight_kg.status = "目視";
  });
  rejected("規則の作業が基準工数にない", (d) => {
    d.params.condition_rules.find((r: Obj) => r.job).job = "J3";
  });
  rejected("締結部の作業が基準工数にない", (d) => {
    d.case.condition.fasteners[C.NO_COUNT].job = "J3";
  });
  rejected("規則の部位が作業部位にない", (d) => {
    d.params.condition_rules.find((r: Obj) => r.area).area = "wheel_hubb";
  });
  rejected("実績の単位と本数の有無が矛盾する", (d) => {
    d.params.tag_to_op["固着対応"].unit = C.TAG_UNIT_VISIT;
  });
  rejected("錆グレードは整数か null", (d) => {
    d.case.condition.underbody_rust_grade.brake_area = "3";
  });
  rejected("実績の count は正", (d) => {
    d.records.historical_records.find((r: Obj) => "固着対応" in r.tags).tags["固着対応"].count = C.NO_COUNT;
  });
  rejected("左右の状態が足りない", (d) => {
    delete d.case.condition.slide_pin_boots.right;
  });
  rejected("下回りの部位名が未知", (d) => {
    const grades = d.case.condition.underbody_rust_grade;
    grades.brake_are = grades.brake_area;
    delete grades.brake_area;
  });
  rejected("錆グレードが範囲外", (d) => {
    d.case.condition.underbody_rust_grade.muffler = 7;
  });
  rejected("実績の count が文字列", (d) => {
    d.records.historical_records.find((r: Obj) => "固着対応" in r.tags).tags["固着対応"].count = "2";
  });
  rejected("タイヤ重量が文字列", (d) => {
    d.case.vehicle.tire_with_wheel_weight_kg.value = "23";
  });
  rejected("作業が空", (d) => {
    d.case.jobs = [];
  });
  rejected("請求人時の内訳が合わない", (d) => {
    d.params.labor_rate.billable_hours.winter = C.ONE_UNIT;
  });
});

describe("入力の形が違うとき", () => {
  it("項目が足りない入力は日本語の ValueError にする", () => {
    const data = loadJsonData();
    delete data.case.condition;
    expect(() => estimateSafely(data.case, data.params, data.catalog, data.records)).toThrow(/入力 JSON の形式が正しくありません/);
    expect(() => estimateSafely(data.case, data.params, data.catalog, data.records)).toThrow(ValueError);
  });

  it("元の ValueError はそのまま通す", () => {
    const data = loadJsonData();
    data.case.jobs = [];
    expect(() => estimateSafely(data.case, data.params, data.catalog, data.records)).toThrow("今回の作業（jobs）が空");
  });
});

describe("ガードレール", () => {
  it("年式・走行距離だけでは人時を増やさない", () => {
    const newer = run((d) => {
      d.case.e_shakensho["初度登録年月"] = "令和元年5月";
      d.case.vehicle.odometer_km = 40000;
    });
    // 令和元年 = 2019年。経過7年・4万kmで確認強度は「通常」に下がるが、人時は変わらない
    expect(newer.vehicle.first_registration).toBe("2019-05");
    expect(newer.checks.check_intensity.level).toBe("通常");
    expect(newer.estimate.labor_hours).toEqual(result.estimate.labor_hours);
  });

  it("未確認は typical に入れず high に入れる", () => {
    const items = itemsById(result);
    for (const id of ["rotor", "boot:right", "fastener:F-L-SLD-1"]) {
      expect(items[id].hours.typical).toBe(0);
      expect(items[id].hours.high).toBeGreaterThan(0);
    }
  });

  it("待機は経過時間だけを変える", () => {
    const after = run((d) => {
      d.params.waits.hours.thaw.default += 1.0;
    });
    expect(after.estimate.labor_hours).toEqual(result.estimate.labor_hours);
    expect(after.estimate.elapsed_hours).not.toEqual(result.estimate.elapsed_hours);
  });

  it("暖房費は時間単価だけを変える", () => {
    const after = run((d) => {
      d.params.labor_rate.cost_yen.heating_yen *= 2;
    });
    expect(after.estimate.labor_hours).toEqual(result.estimate.labor_hours);
    expect(after.money.labor_rate.annual_yen_per_hour).toBeGreaterThan(result.money.labor_rate.annual_yen_per_hour);
  });

  it("作業部位に未確認があれば high に入れる", () => {
    const wash = itemsById(
      run((d) => {
        Object.assign(d.case.condition.underbody_rust_grade, { brake_area: null, wheel_hub: 0, front_suspension: 0 });
      }),
    ).wash;
    expect(wash.state_id).toBe(C.STATE_UNCONFIRMED);
    expect(wash.state).toBe("未確認");
    expect(wash.hours.typical).toBe(0);
    expect(wash.hours.high).toBeGreaterThan(0);
  });

  it("タイヤ重量が未確認なら typical に入れない", () => {
    const tire = itemsById(
      run((d) => {
        d.case.vehicle.tire_with_wheel_weight_kg.status = "未確認";
      }),
    ).tire_carry;
    expect(tire.hours.typical).toBe(0);
    expect(tire.hours.high).toBeGreaterThan(0);
  });

  it("基準と1人で扱える上限の間の重量は未設定として報告する", () => {
    const between = run((d) => {
      d.case.vehicle.tire_with_wheel_weight_kg.value = 19;
    });
    expect(itemsById(between)).not.toHaveProperty("tire_carry");
    expect(between.unknowns.some((u: string) => u.includes("基準の前提"))).toBe(true);
  });

  it("結果は提案として示す", () => {
    expect(result.status.startsWith("提案")).toBe(true);
  });

  it("請求しない工程は追加金額が 0", () => {
    const quote = run((d) => {
      Object.assign(d.case.condition.underbody_rust_grade, { brake_area: null, wheel_hub: 0, front_suspension: 0 });
    }).conditional_quote;
    const row = quote.conditions.find((r: Obj) => r.condition === "下回り洗浄");
    expect(row.extra_hours).toBeGreaterThan(0);
    expect(row.extra_yen).toBe(0);
  });

  it("同一車両は履歴から見つかる（フラグがなくても）", () => {
    const b = run((d) => {
      for (const record of d.records.historical_records) delete record.same_vehicle;
    }).method_comparison.b;
    expect(b.same_vehicle_cases.map((row: Obj) => row.id)).toEqual(["R11"]);
  });

  it("車両キーは電子車検証から作る", () => {
    expect(result.vehicle.vehicle_key).toBe("ABC-XYZ10/2014-01");
    const other = run((d) => {
      d.case.e_shakensho["型式"] = "DEF-UVW20";
      for (const record of d.records.historical_records) delete record.same_vehicle;
    });
    // 型式が違えば別の車なので、R11 は類似実績の集計に入る
    expect(other.method_comparison.b.n).toBe(4);
  });

  it("今回の作業にない締結部は除外を報告する", () => {
    const excluded: string[] = run((d) => {
      d.case.jobs = ["J2"];
      d.case.condition.fasteners[C.NO_COUNT].job = "J1";
    }).excluded_from_this_job;
    // ホイールナット（J1）と書き換えた1本。J1 の規則はないので規則の除外はない
    expect(excluded.filter((e) => !e.startsWith("規則"))).toHaveLength(2);
  });

  it("今回の作業にない規則は除外を報告する", () => {
    const excluded: string[] = run((d) => {
      d.case.jobs = ["J1"];
    }).excluded_from_this_job;
    // J2 の規則（ハブ錆落とし、ローター、ブーツ）が記録される
    expect(excluded.filter((e) => e.startsWith("規則"))).toHaveLength(3);
  });

  it("顧客向けの明細は条件付き見積もりと一致する", () => {
    const sheet = result.customer_sheet
      .filter((line: Obj) => line.line.startsWith("発生した場合だけの追加"))
      .reduce((sum: number, line: Obj) => sum + line.high, 0);
    expect(sheet).toBeCloseTo(result.conditional_quote.all_conditions_extra_hours, 2);
  });

  it("作業範囲外の部位は報告するだけで足さない", () => {
    expect(result.unknowns.some((u: string) => u.startsWith("subframe"))).toBe(true);
  });
});

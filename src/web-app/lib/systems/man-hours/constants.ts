// 定数（意味が定義で決まり、実績や最新の情報では変わらない値）。
// 元: src/30-algorithm/integrated/constants.py
//
// 工場・実績・今回の入力によって変わる値はここに置かない。それらは data/ の JSON
// （変数）から読む。estimator.ts は数値リテラルを持たず、数値はすべてこのファイルの
// 名前付き定数か data/ の変数から来る（tests/systems/man-hours/no-magic-numbers.test.ts で検査する）。

// 見積もりの3つの値。low=少ない場合、typical=観察から見込む値、high=この見積もりの範囲での上限
export const LOW = "low";
export const TYPICAL = "typical";
export const HIGH = "high";
export const BANDS = [LOW, TYPICAL, HIGH] as const;
export type BandName = (typeof BANDS)[number];

// 数量の単位。「入庫1回につき1回」「片側1つ」「締結部1本」は、どれも1単位として数える
export const ONE_UNIT = 1;
// 丸めの刻みの基準。刻み = ROUNDING_BASE × 10^(-桁数)
export const ROUNDING_BASE = 1;
// 同じ共通工程が複数の作業に含まれていても、見積もり全体では1回だけ計上する
export const COUNTED_ONCE = 1;
// 足し合わせの起点（何も加えていない状態）
export const NO_HOURS = 0.0;
export const NO_COUNT = 0;
export const NO_POINTS = 0;
export const NO_YEN = 0.0;

// 暦
export const MONTHS_PER_YEAR = 12;
export const DATE_SEPARATOR = "-";
export const VEHICLE_KEY_SEPARATOR = "/"; // 同一車両の照合キー「型式/初度登録年月」の区切り
export const MONTH_DIGITS = 2; // 月を2桁で表示する（2014-01）
export const ZERO_PAD = "0"; // zfill 相当の埋め文字

// 和暦の元年が西暦の何年か（定義で決まる）。西暦 = 元年の西暦 + 和暦年 - ERA_YEAR_OFFSET
export const ERA_START_YEAR: Readonly<Record<string, number>> = { 令和: 2019, 平成: 1989, 昭和: 1926 };
export const ERA_FIRST_YEAR_LABEL = "元";
export const ERA_FIRST_YEAR_NUMBER = 1;
export const ERA_YEAR_OFFSET = 1;

// 表示（丸め桁と丸め方は工場に確認する事項なので shop_params.rounding に置く）
export const PERCENT = 100;

// 現車状態の内部 ID。画面や入力に出る名前（「問題あり」など）は docs/man-hours/README.md §3 の暫定選択肢なので、
// shop_params.state_labels（変数）に置き、コードはこの ID で分岐する
export const STATE_PROBLEM = "problem";
export const STATE_ASSUMED = "assumed";
export const STATE_UNCONFIRMED = "unconfirmed";
export const STATE_NOT_OBSERVED = "not_observed";
export const STATE_IDS: readonly string[] = [STATE_PROBLEM, STATE_ASSUMED, STATE_UNCONFIRMED, STATE_NOT_OBSERVED];

// 状態に応じた工程の展開規則（condition_rules）の種類と数量の決め方
export const RULE_STATE = "state";
export const RULE_SIDE_STATE = "side_state";
export const RULE_AREA_GRADE = "area_grade";
export const RULE_WORK_AREA_GRADE = "work_area_grade";
export const RULE_KINDS: readonly string[] = [RULE_STATE, RULE_SIDE_STATE, RULE_AREA_GRADE, RULE_WORK_AREA_GRADE];
export const QUANTITY_PER_VISIT = "per_visit";
export const QUANTITY_SIDES = "sides";

// 実績タグの数え方。count=実績の count で割って1単位あたりにする、visit=入庫1回あたり
export const TAG_UNIT_COUNT = "count";
export const TAG_UNIT_VISIT = "visit";
export const TAG_UNITS: readonly string[] = [TAG_UNIT_COUNT, TAG_UNIT_VISIT];

// 方式Bの比較条件と、その判定結果の内部コード
export const CONDITION_BRAKE_RUST = "brake_rust";
export const CONDITION_AGE_BAND = "age_band";
export const CONDITION_SEASON = "season";
export const SIMILAR_CONDITIONS: readonly string[] = [CONDITION_BRAKE_RUST, CONDITION_AGE_BAND, CONDITION_SEASON];
export const DIFF_MATCH = "match";
export const DIFF_DIFFERENT = "different";
export const DIFF_UNKNOWN = "unknown";

// 季節
export const SEASON_WINTER = "冬季";
export const SEASON_OTHER = "冬季以外";
export const WAIT_VARIANT_DEFAULT = "default";
export const WAIT_VARIANT_WINTER = "winter";

// 方式（README の A・B・C）
export const METHOD_A_C = "A/C: 基準＋状態に応じた工程の積み上げ";
export const METHOD_B = "B: 類似実績の参照";

// 料金の配賦方法
export const RATE_MODE_ANNUAL = "annual";
export const RATE_MODE_SEASONAL = "seasonal";

// 補正表の版
export const RATE_TABLE_V1 = "v1";
export const RATE_TABLE_V2 = "v2";
export const RATE_TABLES: readonly string[] = [RATE_TABLE_V1, RATE_TABLE_V2];

// 文の区切り（音声メモの振り分け）
export const SENTENCE_DELIMITER = "。";

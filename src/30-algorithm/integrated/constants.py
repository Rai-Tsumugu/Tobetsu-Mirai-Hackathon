"""定数（意味が定義で決まり、実績や最新の情報では変わらない値）。

工場・実績・今回の入力によって変わる値はここに置かない。それらは data/ の JSON
（変数）から読む。estimator.py は数値リテラルを持たず、数値はすべてこのファイル
の名前付き定数か data/ の変数から来る（test_estimator.py で検査する）。
"""

# 見積もりの3つの値。low=少ない場合、typical=観察から見込む値、high=この見積もりの範囲での上限
LOW = "low"
TYPICAL = "typical"
HIGH = "high"
BANDS = (LOW, TYPICAL, HIGH)

# 数量の単位。「入庫1回につき1回」「片側1つ」「締結部1本」は、どれも1単位として数える
ONE_UNIT = 1
# 丸めの刻みの基準。刻み = ROUNDING_BASE × 10^(-桁数)
ROUNDING_BASE = 1
# 同じ共通工程が複数の作業に含まれていても、見積もり全体では1回だけ計上する
COUNTED_ONCE = 1
# 足し合わせの起点（何も加えていない状態）
NO_HOURS = 0.0
NO_COUNT = 0
NO_POINTS = 0
NO_YEN = 0.0

# 暦
MONTHS_PER_YEAR = 12
DATE_SEPARATOR = "-"
VEHICLE_KEY_SEPARATOR = "/"  # 同一車両の照合キー「型式/初度登録年月」の区切り
MONTH_DIGITS = 2  # 月を2桁で表示する（2014-01）

# 和暦の元年が西暦の何年か（定義で決まる）。西暦 = 元年の西暦 + 和暦年 - ERA_YEAR_OFFSET
ERA_START_YEAR = {"令和": 2019, "平成": 1989, "昭和": 1926}
ERA_FIRST_YEAR_LABEL = "元"
ERA_FIRST_YEAR_NUMBER = 1
ERA_YEAR_OFFSET = 1

# 表示（丸め桁と丸め方は工場に確認する事項なので shop_params.rounding に置く）
PERCENT = 100
JSON_INDENT = 2  # 出力 JSON の字下げ幅

# 現車状態の内部 ID。画面や入力に出る名前（「問題あり」など）は docs/man-hours/README.md §3 の暫定選択肢なので、
# shop_params.state_labels（変数）に置き、コードはこの ID で分岐する
STATE_PROBLEM = "problem"
STATE_ASSUMED = "assumed"
STATE_UNCONFIRMED = "unconfirmed"
STATE_NOT_OBSERVED = "not_observed"
STATE_IDS = (STATE_PROBLEM, STATE_ASSUMED, STATE_UNCONFIRMED, STATE_NOT_OBSERVED)

# 状態に応じた工程の展開規則（condition_rules）の種類と数量の決め方
RULE_STATE = "state"
RULE_SIDE_STATE = "side_state"
RULE_AREA_GRADE = "area_grade"
RULE_WORK_AREA_GRADE = "work_area_grade"
RULE_KINDS = (RULE_STATE, RULE_SIDE_STATE, RULE_AREA_GRADE, RULE_WORK_AREA_GRADE)
QUANTITY_PER_VISIT = "per_visit"
QUANTITY_SIDES = "sides"

# 実績タグの数え方。count=実績の count で割って1単位あたりにする、visit=入庫1回あたり
TAG_UNIT_COUNT = "count"
TAG_UNIT_VISIT = "visit"
TAG_UNITS = (TAG_UNIT_COUNT, TAG_UNIT_VISIT)

# 方式Bの比較条件と、その判定結果の内部コード
CONDITION_BRAKE_RUST = "brake_rust"
CONDITION_AGE_BAND = "age_band"
CONDITION_SEASON = "season"
SIMILAR_CONDITIONS = (CONDITION_BRAKE_RUST, CONDITION_AGE_BAND, CONDITION_SEASON)
DIFF_MATCH = "match"
DIFF_DIFFERENT = "different"
DIFF_UNKNOWN = "unknown"

# 季節
SEASON_WINTER = "冬季"
SEASON_OTHER = "冬季以外"
WAIT_VARIANT_DEFAULT = "default"
WAIT_VARIANT_WINTER = "winter"

# 方式（README の A・B・C）
METHOD_A_C = "A/C: 基準＋状態に応じた工程の積み上げ"
METHOD_B = "B: 類似実績の参照"

# 料金の配賦方法
RATE_MODE_ANNUAL = "annual"
RATE_MODE_SEASONAL = "seasonal"

# 補正表の版
RATE_TABLE_V1 = "v1"
RATE_TABLE_V2 = "v2"
RATE_TABLES = (RATE_TABLE_V1, RATE_TABLE_V2)

# 文の区切り（音声メモの振り分け）
SENTENCE_DELIMITER = "。"

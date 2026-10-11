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
MONTH_DIGITS = 2  # 月を2桁で表示する（2014-01）

# 和暦の元年が西暦の何年か（定義で決まる）。西暦 = 元年の西暦 + 和暦年 - ERA_YEAR_OFFSET
ERA_START_YEAR = {"令和": 2019, "平成": 1989, "昭和": 1926}
ERA_FIRST_YEAR_LABEL = "元"
ERA_FIRST_YEAR_NUMBER = 1
ERA_YEAR_OFFSET = 1

# 表示（丸め桁と丸め方は工場に確認する事項なので shop_params.rounding に置く）
PERCENT = 100
JSON_INDENT = 2  # 出力 JSON の字下げ幅

# 現車状態の選択肢（README §3 の暫定選択肢と「仮定」）
STATE_PROBLEM = "問題あり"
STATE_ASSUMED = "仮定"
STATE_UNCONFIRMED = "未確認"
STATE_NOT_OBSERVED = "問題を観察していない"
STATE_PREFIX_ORDER = (STATE_NOT_OBSERVED, STATE_PROBLEM, STATE_ASSUMED, STATE_UNCONFIRMED)

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

# 文の区切り（音声メモの振り分け）
SENTENCE_DELIMITER = "。"

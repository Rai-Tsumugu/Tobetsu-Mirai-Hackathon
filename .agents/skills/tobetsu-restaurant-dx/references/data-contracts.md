# Aの入力・出力と受入例

以下はアプリ内部で使う提案仕様。外部データの実際の列名ではない。選択した機能の仕様だけ採用し、提供データに合わせる。

## SNS下書き

| 入力 | 扱い |
| --- | --- |
| menu_name, price_jpy, tax_basis | 店が確認した商品名・価格・税表記 |
| availability_start, availability_end, opening_hours | 日本時間。欠けた情報は書かず、確認項目へ |
| tone, audience, photo_permission | 店の口調・対象・写真の利用許可 |
| factual_notes | 店が認めた特徴。未確認の効能やアレルゲン情報を足さない |

出力はdraft_text、evidence_fields、needs_confirmation。例示の商品「デモコーヒー／税込500円／提供日入力なし」では500円を保ち、提供日を創作しない。確認済み価格がなければ価格を含めない案と確認項目を返す。

## 原価

| 入力 | 単位・条件 |
| --- | --- |
| ingredient_id, purchase_price_jpy, purchase_qty, purchase_unit | 購入金額・量・単位。同じ税基準で計算 |
| usage_qty, usage_unit | 1食の使用量。gとkg等は変換し、mlとgは密度なしで変換しない |
| yield_ratio | 0より大きく1以下。使用量が可食部か購入重量かを記録。適用しない場合は1 |
| packaging_cost_jpy, target_margin | 1食の包装費、0以上1未満の目標粗利率 |
| price_as_of, tax_basis, rounding_rule | 単価日、税区分、売価の丸め規則 |

歩留まりを適用する例：1,000gを税抜1,200円で購入、可食部歩留まり0.8、可食部を1食80g使用なら材料費120円。包装20円、目標粗利率0.6なら費用140円、丸め前売価350円。人件費・固定費はこの例では含まない。購入重量ベースの使用量なら歩留まりを再適用しない。

出力はcost_breakdown、total_cost、suggested_price_before_rounding、suggested_price、excluded_costs、assumptions。未知単価、購入量0、目標率1、未定義の単位変換は該当箇所と計算不能理由を返す。欠損を0円にしない。

## 教育資料

入力はutterance_id、speaker_alias、text、該当する既存手順ID。出力は変更候補、根拠発言ID、矛盾、確認担当、review_status。

境界例：発言「以前はX、次からはYかもしれない」は決定として既存手順を書き換えない。温度や時間が不明なら要確認を残す。人の確認前はdraft。

## 出典の記録

出典ID、提供者、実際の取得URL、取得日時、基準日・期間、地域・地点、単位、許諾条件、加工内容、原本のSHA256を取得時に記録する。事業者データは公開URLの代わりに許可範囲と匿名の提供記録を使う。例示データはdata_kind=syntheticで区別する。

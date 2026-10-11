# 30案の演算アルゴリズム：比較表

[system-ideas-30.md](../../docs/man-hours/system-ideas-30.md) の S01〜S30 を、共通の入力 [scenario.json](scenario.json) で計算した結果。**数値はすべて架空値**で、補正率・人時の実測ではない。共通ルールは [SPEC.md](SPEC.md)。この README は `build_table.py` で生成する。

## 共通シナリオ

- 車両: 架空SUV-X（4WD、寒冷地仕様）、初度登録 2014-01、走行 128,000km、タイヤ 225/65R17（ホイール付き約23kg、仮定）
- 入庫: 2027-01-20（冬季、外気 -8℃）。車体に積雪15cm、前輪ホイールハウスに氷塊2か所
- 作業: J1 冬タイヤ交換（基準0.6人時）＋ J2 フロントブレーキパッド・ローター交換（基準1.4人時）。共通工程の重複控除後 **1.7人時** を全案の出発点にする（S17のみ 2.0 から控除を計算）
- 状態: ブレーキ周り錆グレード3、ハブ2、左ブラケットボルト錆「重」2本・右「中」2本、スライドボルト4本とローター固着・サブフレームは未確認、左ブーツ硬化
- 各案は**自分が扱う要因だけ**を反映するため、最終工数の差は「その案が何を見ているか」の差である。合算・平均はしない

## 比較表

最終的な工数は「人時 low / **typical** / high」。経過時間は待機（融解・浸透・乾燥）を含む納車側の時間で、人時とは別。3重チェック欄の ✓／✗ は Haiku 3体（算術の独立再計算／仕様・解釈の統一／入力整合・再現性）の最終判定。「裁定済み」は、Haiku の指摘がオーケストレーターの個別指示と食い違うもので、指示どおりの実装を残した。理由は末尾の各案の節に書く。「要確認」は人時の値に影響しない不足が残っているもの。

| No | 案名 | 入力内容 | 重要な途中計算数値 | 最終的な工数 | 3重チェック |
|---|---|---|---|---|---|
| S01 | 状態チェックリスト加算型（A） | base_totals.deduplicated_base: 1.7<br>condition.fasteners(J2): 重2・中2・未確認4（確認済み/未確認混在）<br>condition.underbody_rust_grade.wheel_hub: 2<br>condition.rotor_hub_seizure: 未確認（不明）<br>condition.slide_pin_boots: 左: 問題あり（硬化） / 右: 未確認（左 確認済み・右 不明）<br>condition.modification: 社外アルミホイール（ハブ径リングあり）（申告） | チェック項目の数（問題あり／未確認／観察せず）: **6／6／3** 項目<br>問題あり項目の追加 low / typical / high: **0.30 / 0.95 / 5.70** 人時<br>重2本の折れ込み・ねじ山修正（high のみ）: **4** 人時<br>未確認項目の上限（high のみ）: **2.2** 人時<br>追加合計 low / typical / high: **0.30 / 0.95 / 7.90** 人時<br>待機（浸透＋防錆乾燥）low / typical / high: **0.55 / 0.55 / 0.55** 時間（人時に含めない） | 人時 2.00 / **2.65** / 9.60<br>経過 2.55 / **3.20** / 10.15<br>追加の可能性あり（未確認項目・high にのみ含む）: max_additional_labor_hours 2.2、items 左スライドボルト1（未確… 人時<br>チェック項目の内訳: 0 / 0 / 0 / 0 / 0 / 0 / 0.05 / 0.15 / 2.3 / 0.05 … 一覧 | 合格 ✓✓✓ |
| S02 | 部位別の腐食グレード入力（A） | condition.underbody_rust_grade.front_suspension: 2<br>condition.underbody_rust_grade.brake_area: 3<br>condition.underbody_rust_grade.wheel_hub: 2<br>condition.underbody_rust_grade.rear_suspension: 1<br>condition.underbody_rust_grade.subframe: 未確認(null)（不明(J1/J2に関係しないため未使用)）<br>condition.underbody_rust_grade.muffler: 2（確認済み(J1/J2に関係しないため未使用)）<br>base_totals.deduplicated_base: 1.7 | 作業に関係する部位のグレード: **wheel_hub 2、rear_suspension 1、brake_area 3、front_suspension…** グレード<br>ローター固着の片側数(typical): **1** 片側<br>ハブ錆落としの片側数(typical): **2** 片側<br>部位別の追加人時(typical): **wheel_hub 0.2、rear_suspension 0、brake_area 0.2、front_suspen…** 人時<br>追加人時合計(low/typical/high): **0.05 / 0.4 / 1.1** 人時<br>グレード3の部位数: **1** 部位<br>未確認の関係部位: **** 部位<br>防錆乾燥の待機(low/typical/high): **0.3 / 0.3 / 0.3** 時間 | 人時 1.75 / **2.10** / 2.80<br>経過 2.05 / **2.40** / 3.10<br>グレード3の部位(層状剥離・欠損。穴あき等AG04の有無は現物確認): brake_area 部位<br>AG04の可能性の確認が要る関係部位(グレード3または範囲内の未確認): brake_area 部位<br>顧客連絡の目安(AG04: 見積もりを変えて了承を得る必要がありうる): はい 真偽<br>顧客連絡の目安(追加typicalが連絡しきい値を超える): いいえ 真偽 | 合格 ✓✓✓ |
| S03 | 締結部ごとの固着リスク表（A/C） | base_totals.deduplicated_base: 1.7<br>condition.fasteners: [{"id": "F-L-BRK-1", "rust": "重（頭部腐食）", "risk": "折れ込みの可能性", "count": …（申告）<br>condition.fastener_risk_rule: {"_source": "整備士の暫定ルール（架空）", "重": "折れ込みの可能性", "中": "固着対応の可能性", "軽": "…（仮定）<br>mechanic_provisional_add_ops.FX-SEIZE/FX-BROKEN/FX-THREAD: {"FX-SEIZE": {"low": 0.05, "typical": 0.15, "high": 0.3}, "FX-BROKEN"…（仮定）<br>elapsed_waits.penetrant_soak_wait_hours: 0.25（仮定） | リスク区分別本数（通常/固着対応/折れ込み/不明）: **通常 20、固着対応の可能性 2、折れ込みの可能性 2、不明 4** 本<br>固着対応(FX-SEIZE)の人時（low/typical/high）: **0.1 / 0.6 / 2.4** 人時<br>FX-BROKEN の人時（high のみ）: **3** 人時<br>FX-THREAD の人時（high のみ）: **1** 人時<br>追加人時合計（low/typical/high）: **0.1 / 0.6 / 6.4** 人時<br>浸透待ち（経過時間のみ）: **0.25 / 0.25 / 0.25** 時間 | 人時 1.80 / **2.30** / 8.10<br>経過 2.05 / **2.55** / 8.35<br>リスク区分別本数: 通常 20、固着対応の可能性 2、折れ込みの可能性 2、不明 4 本 | 合格 ✓✓✓ |
| S04 | 経過年数・走行距離による確認強度の切替（共通基準（重複控除後 1.7 人時）） | vehicle.first_registration: 2014-01<br>intake.date: 2027-01-20<br>vehicle.odometer_km: 128000<br>shop_policy.check_intensity_threshold: 10年 / 100000km（仮定）<br>condition.fasteners（未確認）: 4（不明）<br>condition.rotor_hub_seizure: 未確認（不明）<br>condition.slide_pin_boots（未確認側）: ["right"]（不明）<br>condition.underbody_rust_grade（未確認）: ["subframe"]（不明） | 初度登録からの経過年数: **13** 年<br>年数のしきい値判定: **はい** 真偽<br>走行距離のしきい値判定: **はい** 真偽<br>確認強度: **強** -<br>追加確認項目数: **3** 項目<br>未確認の項目数: **8** 項目<br>未確認項目の high 加算（上限の幅）: **2.2** 人時<br>high の経過時間（浸透待ち込み）: **4.15** 時間<br>基準に対する typical の増分: **0** 人時 | 人時 1.70 / **1.70** / 3.90<br>経過 1.70 / **1.70** / 4.15<br>確認強度: 強 -<br>追加確認項目: 下回りの撮影（錆グレード） / 締結部の観察（スライドボルト・ブラケットボルト） / ゴム部品の状… - | 裁定済み ✓✓✗ |
| S05 | 冬季の前処理モジュール（A） | base_totals.deduplicated_base: 1.7（仮定）<br>condition.snow_on_body: 問題あり（屋根・ボンネットに約15cm）<br>condition.ice_in_wheel_house: 問題あり（2か所）<br>mechanic_provisional_add_ops.PRE-SNOW/PRE-ICE/PRE-WASH: 整備士の暫定値（仮定）<br>elapsed_waits.thaw_wait_hours: 0.5（仮定）<br>shop_policy.pre_processing_billing: 雪下ろし・氷塊除去は入庫1回分を請求。下回り洗浄は請求しない（仮置き）（仮定）<br>condition.fasteners / underbody_rust_grade 等: S05では使わない（不明） | 雪下ろし（入庫1回）: **0.1 / 0.15 / 0.25** 人時 (low/typical/high)<br>氷塊除去（ホイールハウス）: **0.1 / 0.16 / 0.3** 人時 (low/typical/high)<br>前処理の請求人時（洗浄を除く）: **0.2 / 0.31 / 0.55** 人時 (low/typical/high)<br>下回り洗浄（実施するが請求しない）: **0.15 / 0.2 / 0.3** 人時 (low/typical/high)<br>融解待ち（経過時間のみ）: **0.5 / 0.5 / 0.5** 時間 (low/typical/high)<br>請求人時（typical、other_outputs）: **2.01** 人時<br>実作業人時（typical、labor_hours）: **2.21** 人時<br>経過時間（typical）: **2.71** 時間 | 人時 2.05 / **2.21** / 2.55<br>経過 2.55 / **2.71** / 3.05<br>請求人時（下回り洗浄を除く）low/typical/high: 1.9 / 2.01 / 2.25 人時<br>請求しない人時（下回り洗浄）low/typical/high: 0.15 / 0.2 / 0.3 人時<br>前処理の請求人時 low/typical/high: 0.2 / 0.31 / 0.55 人時 | 合格 ✓✓✓ |
| S06 | 入庫日の気象に連動した前処理の確認（共） | weather_forecast_for_intake_day.min_temp_c: -12（仮定）<br>weather_forecast_for_intake_day.snowfall_forecast_cm: 15（仮定）<br>weather_forecast_for_intake_day.snowfall_previous_day_cm: 10（仮定）<br>shop_policy.weather_prompt_threshold: {"min_temp_c_le": -5, "snowfall_cm_ge": 5, "_note": "どちらかを満たせば前処理の確認を…（仮定）<br>condition.snow_on_body: {"state": "問題あり", "detail": "屋根・ボンネットに約15cm"}<br>condition.ice_in_wheel_house: {"state": "問題あり", "locations": 2, "detail": "前輪ホイールハウス2か所。後輪は少量で除去不要"}<br>base_totals.deduplicated_base: 1.7 | 気象による確認促し: **あり**<br>気象が決める人時: **0** 人時<br>現車確認による雪下ろし: **0.15** 人時<br>現車確認による氷塊除去: **0.16** 人時<br>前処理の合計（typical）: **0.31** 人時<br>融解待ち（経過時間のみ）: **0.5** 時間<br>気象と現車確認の役割の違い: **気象=予約段階の注意喚起 / 現車=人時の根拠**<br>前日降雪（参考表示）: **10** cm | 人時 1.90 / **2.01** / 2.25<br>経過 2.40 / **2.51** / 2.75<br>気象による確認促し表示: 【確認を促す】入庫日は低温または降雪の予報です。雪下ろし・氷塊除去の要否を入庫時に現車で確認してく…<br>請求対象の前処理人時（typical）: 0.31 人時 | 合格 ✓✓✓ |
| S07 | 車格・タイヤ重量による作業負担区分（A/C） | vehicle.body_class: 普通車SUV（scenarioに記載(区分の判定に使用)）<br>vehicle.tire_size: 225/65R17（scenarioに記載(区分の判定に使用)）<br>vehicle.tire_with_wheel_weight_kg: 23（仮定）<br>tire_handling.rule: ホイール付き1本20kg超は2人作業または機材（工場の暫定ルール、架空）（仮定）<br>tire_handling.shop_has_tire_lifter: False（scenarioに記載）<br>shop_policy.workers_available: 2（scenarioに記載）<br>base_totals.deduplicated_base: 1.7 | 車格・タイヤサイズの目安: **大型側**<br>作業負担区分: **2人作業**<br>タイヤ運搬 1人の場合: **0.12** 人時<br>タイヤ運搬 2人の場合: **0.2** 人時<br>運搬の人時差分(typical/high): **0.08** 人時<br>運搬工程の経過時間の差(2人並行): **-0.02** 時間 | 人時 1.70 / **1.78** / 1.78<br>作業負担区分: 2人作業<br>必要作業者数(運搬時): 2 人<br>4本合計重量(参考): 92 kg | 要確認 ✓✓✗ |
| S08 | 類似事例の検索と条件差の表示（B） | jobs: J1+J2<br>condition.underbody_rust_grade.brake_area: 3<br>elapsed_years: 13<br>intake.season: 冬季（11〜3月）<br>vehicle.body_class: 普通車SUV<br>shop_policy.min_records_for_reference: 3 | 今回の経過年数: **13** 年<br>作業範囲(J1+J2)で一致した候補数: **4** 件<br>採用事例数: **4** 件<br>採用事例の実作業人時 中央値: **2.35** 人時<br>採用事例の実作業人時 範囲: **1.90〜3.00** 人時<br>中央値と基準の差: **0.65** 人時<br>経過時間に足す待機: **0.75** 時間（人時に含めない）<br>条件不明の事例: **R10**<br>採用事例に含まれる他の要因の人時（平均）: **0.28** 人時 | 人時 1.90 / **2.35** / 3.00<br>経過 2.65 / **3.10** / 3.75<br>採用事例数: 4 件<br>参考扱い: いいえ<br>実績の中央値・範囲: median 2.35、min 1.9、max 3、n 4 人時<br>事例ごとの条件差（車格は表示のみ）: id R08、date 2025-11、actual 2.3、conditions 錆・固着の状態…<br>条件不明の事例: R10<br>同一車両の前回事例: id R11、actual 1.9、conditions 錆・固着の状態 相違、経過年数 一致、季… | 裁定済み ✓✓✗ |
| S09 | 同一車両の経年履歴の追跡（B） | previous_visit_same_vehicle: {"record_id": "R11", "date": "2025-01-15", "odometer_km": 112000, "es…<br>intake.date / vehicle.odometer_km: ["2027-01-20", 128000]<br>condition.underbody_rust_grade.wheel_hub: 2<br>condition.fasteners（ブラケット/スライド）: [{"id": "F-L-BRK-1", "rust": "重（頭部腐食）"}, {"id": "F-L-BRK-2", "rust": …（申告）<br>mechanic_provisional_add_ops（FX-BROKEN/FX-THREAD/FX-HUBCLEAN の high）: [1.5, 0.5, 0.15]（仮定）<br>elapsed_waits: [0.25, 0.3]（仮定）<br>condition.rotor_hub_seizure: 未確認（不明） | 前回からの経過年数: **2.01** 年<br>固着対応の単価（前回の同一車両実績）: **0.25** 人時/本<br>固着対応の本数（low / typical / high）: **2 / 4 / 8** 本<br>固着対応の人時（low / typical / high）: **0.5 / 1 / 2** 人時<br>折れ込み＋ねじ山修正（high のみ）: **4** 人時<br>ハブ錆の進行に伴う錆落とし（high のみ）: **0.3** 人時<br>待機（経過時間のみ、low / typical / high）: **0.25 / 0.25 / 0.55** 時間<br>前回の実績（履歴表示のみ）: **1.9** 人時<br>前回の見積もり（履歴表示のみ）: **1.5** 人時 | 人時 2.20 / **2.70** / 8.00<br>経過 2.45 / **2.95** / 8.55<br>初度登録からの経過年数(前回→今回): 11.04 / 13.05 年<br>履歴の時系列（見積もり→実績→今回の見積もり typical）: date 2025-01-15、record R11、estimate 1.5、actual 1.… 人時<br>前回からの走行距離の差: 16,000 km<br>今回確認すべき箇所（前回の観察との対応）: place 左キャリパーブラケットボルト、prev 前回: 固着の観察あり、now 今回: 重（頭… リスト | 裁定済み ✓✗✗ |
| S10 | 見積もりと実績の差分ログ（B） | base_totals.deduplicated_base: 1.7（仮定）<br>intake.date / season: 2027-01-20 / 冬季（11〜3月）<br>vehicle.first_registration: 2014-01<br>経過年数 (計算): 13年<br>jobs: J1+J2<br>historical_records: 12件 (架空の実績)。参照 4件（仮定）<br>shop_policy.min_records_for_reference: 3（仮定）<br>condition.fasteners / underbody_rust_grade 等: S10では使わない（不明） | 今回の区分 (診断表示用。範囲の計算には使わない): **冬季・10年以上（13年）・J1+J2** 区分<br>参照した実績の件数: **4** 件<br>J1+J2 の季節別の差の中央値: **冬季 0.65 (n=4) / 冬季以外 n=0 (記録なし)** 人時<br>タグ別の平均追加人時 (参照区分): **固着対応0.25(3件) / その他0.23(3件) / 雪下ろし0.16(4件) / ローター固着0.08(1件) …** 人時/件<br>タグで説明できない差の平均: **0** 人時<br>区分別の差の集計 (冬季/冬季以外 x 経過年数、全作業): **冬季・10年未満 n=2 平均-0.05 中央値-0.05 範囲-0.1〜0.0 / 冬季・10年以上 n=8 平均0…** 人時<br>工数 low / typical / high: **1.7 / 1.7 / 1.7** 人時 | 人時 1.70 / **1.70** / 1.70<br>区分別の差の集計 (平均/中央値/最小/最大/件数): 区分 冬季・10年未満、全作業 n 2、mean -0.05、median -0.05、min -… 人時<br>区分別の原因タグ内訳 (冬季/冬季以外 x 経過年数。タグ別hours合計・件…: 区分 冬季・10年未満、件数 2、差の合計 -0.1、タグ別 、説明できない差の合計 -0.1 /… 人時<br>月別の差の一覧 (月は昇順、月内は差の大きい順の実績と主な原因タグ): 月 2025-01、件数 1、差の合計 0.4、差の最大 0.4、実績 id R11、作業 J1+… 人時<br>参照区分のタグ別平均追加人時: その他 0.23、ローター固着 0.08、固着対応 0.25、氷塊除去 0.04、雪下ろし 0.16 人時/件<br>参照区分の説明できない差の平均: 0 人時<br>同一車両の前回実績 (R11) の差: 0.4 人時 | 合格 ✓✓✓ |
| S11 | 原因タグ別の追加人時の実績表（C） | base_totals.deduplicated_base: 1.7<br>historical_records（タグ付き実績）: 12件（申告）<br>shop_policy.min_records_for_reference: 3（仮定）<br>condition.fasteners: {"中": 2, "重": 2, "未確認": 4}（確認済み/未確認混在）<br>condition.ice_in_wheel_house.locations: 2<br>condition.snow_on_body: 問題あり<br>condition.rotor_hub_seizure: 未確認（不明）<br>elapsed_waits.thaw/penetrant: [0.5, 0.25]（仮定） | 固着対応の単位あたり人時（実績 low/中央値/high）: **0.12 / 0.15 / 0.25** 人時/本<br>固着対応の本数（low / typical / high）: **2 / 4 / 8** 本<br>固着対応の追加人時: **0.23 / 0.6 / 2** 人時<br>ローター固着の追加人時（未確認2側は high のみ）: **0 / 0 / 0.6** 人時<br>雪下ろしの追加人時: **0.15 / 0.15 / 0.2** 人時<br>氷塊除去の追加人時（n<3 のため暫定値）: **0.1 / 0.16 / 0.3** 人時<br>ボルト折れ+ねじ山の追加人時（high のみ、暫定値）: **0 / 0 / 4** 人時<br>追加人時合計: **0.48 / 0.91 / 7.1** 人時 | 人時 2.18 / **2.61** / 8.80<br>経過 2.93 / **3.36** / 9.55<br>タグ別の実績表（単位あたり人時。n は記録レコード数で、本数・か所数の合計では…: tag 固着対応、unit 本、n 8、n_unit レコード、median 0.15、min 0… 人時/単位<br>整備士暫定値へフォールバックしたタグ: ボルト折れ / 氷塊除去 | 合格 ✓✓✓ |
| S12 | 整備士の暫定値を実績で更新する補正表（A/B） | base_totals.deduplicated_base: 1.7<br>mechanic_provisional_add_ops（今回使う工程）: {"AG-BOOT": {"low": 0.1, "typical": 0.15, "high": 0.2}, "FX-BROKEN": …（仮定）<br>condition.underbody_rust_grade（wheel_hub / 作業部位の最大）: [2, 3]<br>historical_records（タグ付き工程の件数）: {"FX-SEIZE": 8, "FX-BROKEN": 1, "FX-ROTOR": 3, "PRE-SNOW": 4, "PRE-IC…<br>condition.fasteners（中/重/未確認の本数）: {"中": 2, "重": 2, "未確認": 4}（申告）<br>condition.ice_in_wheel_house.locations: 2<br>condition.underbody_rust_grade.subframe: 未確認（対応する追加工程なし。数量に入れていない）（不明）<br>condition.rotor_hub_seizure: 未確認（不明）<br>condition.slide_pin_boots: 左: 問題あり（硬化） / 右: 未確認 | 実績から更新候補になった工程数: **3** 工程<br>FX-SEIZE 実績の件数と中央値: **8 / 0.15** 件, 人時/本<br>FX-SEIZE typical（v1 -> v2）: **0.15 / 0.15** 人時/本<br>FX-SEIZE の本数（low/typical/high）: **2 / 4 / 8** 本<br>追加人時 v1 暫定（low/typical/high）: **0.65 / 1.46 / 8.75** 人時<br>v2 - v1 の差（low/typical/high）: **0.18 / 0 / -0.65** 人時<br>採用値の人時（v1・暫定値）: **2.35 / 3.16 / 10.45** 人時<br>経過時間の待機（low/typical/high）: **1.05 / 1.05 / 1.05** 時間 | 人時 2.35 / **3.16** / 10.45<br>経過 3.40 / **4.21** / 11.50<br>補正表 v1/v2 の比較（実績件数つき）: op FX-SEIZE、name 固着した締結部の対応（浸透剤＋加熱）、n 8、status 更新… 人時/単位<br>v2 候補を当てた場合の人時（採用しない）: 2.53 / 3.16 / 9.8 人時<br>採用した補正表の版: rule_version S12-table-v1、kind 整備士の暫定値（未承認）、appro…<br>この案の範囲外としたもの: サブフレーム（J1・J2 で外さない作業範囲外。腐食があれば AG04 として見積もり変更）<br>実績タグがなく v1 の暫定値のまま使う工程: FX-THREAD / FX-HUBCLEAN / PRE-WASH<br>請求しない工程の人時（下回り洗浄）: 0.15 / 0.2 / 0.3 人時 | 再検証後に修正 ✗✗✓ |
| S13 | 道内の整備工場間で匿名化した実績の共有（B） | base_totals.deduplicated_base: 1.7<br>historical_records（自工場）: 12件<br>other_shops_anonymized: {"shop_X": {"固着対応_per_bolt": {"median": 0.18, "n": 25}, "ボルト折れ_per_bo…（申告）<br>condition.fasteners: {"通常": 20, "固着対応の可能性": 2, "折れ込みの可能性": 2, "不明": 4}（申告）<br>condition.rotor_hub_seizure: 未確認（不明）<br>shop_policy.min_records_for_reference: 3（仮定） | 自工場の固着対応 単価（low/typical/high）: **0.12 / 0.15 / 0.18** 人時/本<br>他工場の固着対応 参照幅: **0.12 / 0.18** 人時/本<br>自工場typicalと他工場参照幅の位置関係: **参照幅内**<br>ボルト折れ 採用単価（実績不足のため暫定値）: **0.5 / 0.8 / 1.5** 人時/本<br>ローター固着 採用単価（自工場実績）: **0.2 / 0.25 / 0.3** 人時/側<br>追加人時合計（low/typical/high）: **0.23 / 0.6 / 6.07** 人時<br>参考: 他工場参照幅の単価で積んだ場合の typical: **2.18 / 2.42** 人時<br>参考: 他工場参照幅の単価で積んだ場合の high: **5.42 / 6.38** 人時 | 人時 1.93 / **2.30** / 7.77<br>経過 2.18 / **2.55** / 8.02<br>タグ別の自工場採用値と他工場参照幅: 固着対応 自工場の採用値 0.12 / 0.15 / 0.18、採用元 自工場実績、自工場の実績件…<br>他工場の参照幅で積んだ typical: 2.18 / 2.42 人時 | 合格 ✓✓✓ |
| S14 | 工程別の作業時間を計測するアプリ（B/C） | tap_log_R09.steps: 16工程（待機2件）（申告）<br>condition.snow_on_body: 問題あり<br>condition.ice_in_wheel_house.locations: 2<br>condition.fasteners(J2) 重: 2<br>condition.fasteners(J2) 中: 2<br>condition.fasteners(J2) 未確認: 4（不明）<br>condition.rotor_hub_seizure: 未確認（不明）<br>elapsed_waits.thaw_wait_hours: 0.5（仮定）<br>elapsed_waits.penetrant_soak_wait_hours: 0.25（仮定） | R09 の工程ログ集計 人時: **3** 人時<br>基準工程の実測人時（基準 1.7 との照合）: **1.7** 人時<br>固着対応 1本あたり: **0.18** 人時/本<br>折れ込み対応 1本あたり（R02 実測）: **0.85** 人時/本<br>ねじ山の修正 1か所あたり（FX-THREAD high）: **0.5** 人時/か所<br>今回の追加人時（typical）: **1.08** 人時<br>今回の経過時間（typical）: **3.43** 時間 | 人時 2.42 / **2.78** / 6.82<br>経過 3.07 / **3.43** / 7.47<br>実測の参照件数: 1 件（最小 3 件に不足）<br>待機（人時に含めない）: 0.75 時間 | 合格 ✓✓✓ |
| S15 | 状態に応じて分岐する工程テンプレート（C） | jobs[J1,J2].included_operations: ["OP-LIFT", "OP-WHEEL-F2", "OP-WHEEL-R2", "OP-CHECK-TIRE", "OP-CALIPE…（仮定）<br>base_totals.deduplicated_base: 1.7<br>condition.underbody_rust_grade.wheel_hub: 2<br>condition.fasteners (J2): {"F-L-BRK-1": "重（頭部腐食）", "F-L-BRK-2": "重（頭部腐食）", "F-R-BRK-1": "中", "F…（確認済み（スライドボルトは不明））<br>condition.slide_pin_boots: {"left": "問題あり（硬化）", "right": "未確認"}（確認済み（右は不明））<br>condition.rotor_hub_seizure: 未確認（不明）<br>condition.underbody_rust_grade.subframe: None（不明）<br>mechanic_provisional_add_ops: {"FX-HUBCLEAN": {"low": 0.05, "typical": 0.1, "high": 0.15}, "FX-SEIZ…（仮定） | テンプレート基本工程の合計（共通工程は1回）: **1.7** 人時<br>発火した分岐 / 判定不能の分岐: **4 / 4** 件<br>待機時間（浸透待ち+防錆乾燥、low/typical/high）: **0.55 / 0.55 / 0.55** 時間<br>FX-SEIZE の人時（low/typical/high）: **0.1 / 0.6 / 2.4** 人時<br>折れ込み候補 FX-BROKEN+FX-THREAD（high のみ）: **4** 人時<br>FX-HUBCLEAN + AG-BOOT + FX-ROTOR の人時（low/typical/…: **0.4 / 0.75 / 1.5** 人時<br>追加工程の人時合計（low/typical/high）: **0.5 / 1.35 / 7.9** 人時<br>展開後の工程合計（low/typical/high）: **2.2 / 3.05 / 9.6** 人時 | 人時 2.20 / **3.05** / 9.60<br>経過 2.75 / **3.60** / 10.15<br>分岐判定: id B1、condition ハブ錆グレード >= 2 -> FX-ROTOR + FX-HUB…<br>展開後の工程一覧: branch template、op OP-LIFT、name リフトアップ、qty 1、per …<br>展開後の工程数: 17 行 | 合格 ✓✓✓ |
| S16 | 質問形式の工程展開（C） | vehicle.first_registration / intake.date: 2014-01 → 2027-01-20(約13.0年)<br>vehicle.odometer_km: 128000<br>intake.season / outside_temp_c: 冬季（11〜3月） / -8度<br>condition.snow_on_body: 問題あり(約15cm)<br>condition.ice_in_wheel_house: 2か所<br>condition.underbody_rust_grade.brake_area: 3<br>condition.underbody_rust_grade.subframe: None（不明）<br>condition.fasteners(J2): ブラケット重2・中2、スライド未確認4（一部未確認）<br>condition.rotor_hub_seizure: 未確認（不明）<br>condition.slide_pin_boots: 左=問題あり、右=未確認（一部未確認）<br>condition.modification: 社外アルミホイール（ハブ径リングあり）（申告）<br>condition.rustproof_undercoat: True（申告）<br>previous_visit_same_vehicle: 2025-01-15 左ブラケットボルト1本固着 | 季節と確認強度(S04連動): **冬季 / 強**<br>出した質問数: **16** 問<br>展開された工程: **9** 工程<br>展開された確認事項: **7** 件<br>追加人時(low/typical/high): **0.65 / 1.46 / 9.65** 人時<br>待機時間(経過のみ。low/typical/high): **1.05 / 1.05 / 1.05** h<br>typical 人時: **3.16** 人時 | 人時 2.35 / **3.16** / 11.35<br>経過 3.40 / **4.21** / 12.40<br>請求人時(下回り洗浄を除く。low/typical/high): 2.2 / 2.96 / 11.05 人時<br>質問数(常時のみ): 11 問<br>質問数(今回・冬季かつ強): 16 問<br>展開された質問と回答(自動導出: scenario.json の condit…: Q01 屋根・ボンネットに雪があるか → あり(約15cm) / Q02 ホイールハウスに氷塊があ…<br>展開された工程・確認事項: Q01 雪下ろし / Q02 氷塊除去(2か所。融解待ちは経過時間のみ) / Q03 下回り洗浄(… | 合格 ✓✓✓ |
| S17 | 同時作業での共通工程の重複排除（A/C） | jobs.J1.base_labor_hours: 0.6（仮定）<br>jobs.J2.base_labor_hours: 1.4（仮定）<br>jobs.included_operations(shared): ["OP-LIFT 0.1", "OP-WHEEL-F2 0.2"]（仮定）<br>mechanic_provisional_add_ops.PRE-SNOW（low/typical/high）: [0.1, 0.15, 0.25]（仮定）<br>mechanic_provisional_add_ops.PRE-WASH（low/typical/high・請求しない方針）: [0.15, 0.2, 0.3]（仮定） | 重複控除前の総和: **2** 人時<br>共通工程の控除額（OP-LIFT・OP-WHEEL-F2）: **0.3** 人時<br>重複控除後: **1.7** 人時<br>前処理（雪下ろし＋下回り洗浄）を1回だけ計上: **0.35** 人時<br>前処理を作業ごとに重ねた場合との差（typical からは引かない仮想の差）: **0.35** 人時<br>重ねた場合との差の合計（リフト等の控除＋前処理の仮想の差）: **0.65** 人時<br>typical: **2.05** 人時<br>low / high: **1.95 / 2.55** 人時 | 人時 1.95 / **2.05** / 2.55<br>控除の内訳: J2からOP-LIFT 0.1人時を控除（J1に計上） / J2からOP-WHEEL-F2 0.2…<br>J1/J2 の控除後の配分: J1 0.6、J2 1.1 人時<br>請求人時（下回り洗浄は請求しない方針）: 1.85 人時（実作業人時 labor_hours.typical から PRE-WASH typical を除く）<br>作業ごとに重ねた場合との差（前処理分は typical からは引かない仮想の差）: リフト等の共通工程 0.3、前処理（雪下ろし・下回り洗浄） 0.35、合計 0.65 人時 | 要確認 ✓✓✗ |
| S18 | 人時と経過時間・納期の分離計算（C） | base_totals.deduplicated_base: 1.7（仮定）<br>condition.snow_on_body: 問題あり<br>condition.ice_in_wheel_house: 問題あり（2か所）<br>mechanic_provisional_add_ops: PRE-SNOW / PRE-ICE / FX-SEIZE / FX-BROKEN / FX-THREAD / FX-HUBCLEAN（整…（仮定）<br>condition.fasteners: 重2本・中2本・未確認4本（スライドボルト。ブーツに隠れて見えない）（重・中は確認済み、スライドボルトは不明）<br>elapsed_waits: 融解 0.5 / 浸透 0.25 / 防錆乾燥 0.3（冬季仮説値） / 部品待ち 0.0（仮定）<br>condition.rustproof_undercoat: 施工歴あり（顧客申告）。ハブ錆落とし・防錆の要否の判定に使う（申告）<br>condition.underbody_rust_grade.wheel_hub: 2<br>shop_policy.workers_available: 2（仮定） | 基準の検算（共通工程の重複なし）: **1.7** 人時<br>前処理の人時（雪下ろし + 氷塊除去）: **0.2 / 0.31 / 0.55** 人時 (low/typical/high)<br>ハブ錆落とし・防錆（HK07）: **0.1 / 0.2 / 0.3** 人時 (low/typical/high)<br>締結部の追加人時（U3）: **0.1 / 0.6 / 6.4** 人時 (low/typical/high)<br>人時（請求の根拠）: **2.1 / 2.81 / 8.95** 人時 (low/typical/high)<br>待機の合計（人時0）: **1.05 / 1.05 / 1.05** 時間 (low/typical/high)<br>経過時間（2人作業）: **2.4 / 3.03 / 9.0** 時間 (low/typical/high)<br>経過時間（1人作業）/ 2人化の短縮（typical）: **2.85 / 3.21 / 9.25 / 短縮 0.18** 時間 (low/typical/high / typical の差) | 人時 2.10 / **2.81** / 8.95<br>経過 2.40 / **3.03** / 9.00<br>経過時間（1人作業）low/typical/high: 2.85 / 3.21 / 9.25 時間<br>待機の合計（人時に入れない）low/typical/high: 1.05 / 1.05 / 1.05 時間<br>納車見込み（部品待ち込み）low/typical/high: 2.4 / 3.03 / 9 時間<br>typical の工程表（2人作業）: id ICE1、step 氷塊除去（前輪ホイールハウス1）、persons 1、hours 0.0… 時間<br>high の工程表（2人作業。折れ込み・未確認の固着対応を含む）: id ICE1、step 氷塊除去（前輪ホイールハウス1）、persons 1、hours 0.1… 時間 | 裁定済み ✗✗✗ |
| S19 | 3点見積もり（少ない・標準・多い）（共） | base_totals.deduplicated_base: 1.7<br>condition.fasteners(ブラケット重/中): {"重": 2, "中": 2}（申告）<br>condition.fasteners(スライド): 未確認4本（不明）<br>condition.rotor_hub_seizure: 未確認（不明）<br>condition.slide_pin_boots: {"left": "問題あり（硬化）", "right": "未確認"}（確認済み(左)/不明(右)）<br>mechanic_provisional_add_ops: {"FX-SEIZE": 0.15, "FX-BROKEN": 0.8, "FX-THREAD": 0.3, "FX-ROTOR": 0.…（仮定） | 前提「少ない：固着は重のみ軽微」の追加工程: **FX-SEIZEx2・AG-BOOTx1**<br>前提「標準：一部固着」の固着本数: **4** 本<br>前提「多い：固着が多く、ボルト折れあり」の内訳: **FX-SEIZEx8・FX-BROKENx2・FX-THREADx2・FX-ROTORx2・AG-BOOTx2**<br>追加人時（少ない/標準/多い）: **0.25 / 0.75 / 7.6** 人時<br>標準の人時: **2.45** 人時<br>多いの人時: **9.3** 人時<br>幅（多い - 少ない）: **7.35** 人時<br>浸透待ち（経過時間のみ）: **0.25** 時間 | 人時 1.95 / **2.45** / 9.30<br>経過 2.20 / **2.70** / 9.55<br>前提「少ない：固着は重のみ軽微」の人時(単価 low〜high): 1.9 / 1.95 / 2.5 人時<br>前提「標準：一部固着」の人時(単価 low〜high): 2 / 2.45 / 3.1 人時<br>前提「多い：固着が多く、ボルト折れあり」の人時(単価 low〜high): 3.9 / 9.3 / 9.3 人時 | 裁定済み ✓✗✓ |
| S20 | 条件付き見積書（追加発生時の連絡基準）（共） | base_totals.deduplicated_base: 1.7<br>condition.slide_pin_boots.left: 問題あり（硬化）<br>condition.slide_pin_boots.right: 未確認（不明）<br>condition.fasteners(J2: 重/中/未確認): 2/2/4 本<br>condition.rotor_hub_seizure: 未確認（不明）<br>condition.underbody_rust_grade(subframe): None（不明）<br>elapsed_waits.rustproof_dry_wait_hours: 0.3（仮定）<br>shop_policy.contact_threshold: 0.5人時 / 5000円超（仮定）<br>cost_data_S27: 年間経費合計 28800000円 / 3600人時（申告） | 確定分（観察済みの問題あり）: **0.15** 人時<br>条件付き追加の件数（連絡判定の対象）: **7** 条件<br>時間単価（年間配賦）: **8,000** 円/人時<br>折れ込み C1 の1本あたり追加（low〜high）: **0.70〜2.00** 人時/本<br>ローター固着 C4 の最大追加（両側 high）: **1.1** 人時<br>条件付き追加の合計（全条件が上限で発生）: **7.7** 人時<br>経過時間 high の内訳: **10.1** 時間<br>作業前連絡の対象になる条件: **5** 条件 | 人時 1.95 / **2.45** / 9.55<br>経過 2.20 / **2.70** / 10.10<br>時間単価（年間配賦）: 8,000 円/人時<br>確定分の金額（typical）: 1,200 円<br>条件付き追加の金額（全条件が上限）: 61,600 円<br>金額基準を人時に直した値: 0.63 人時（5000円 / 時間単価）<br>連絡基準: 追加が 0.5人時 または 5000円 を超えうるなら作業前に連絡<br>ブレーキホース取り寄せ待ち（C6 発生時のみ）: 24 時間（暦時間）<br>C1 左ブラケットボルト（頭部腐食）が折れた場合 [観察（重）] 要連絡（1回…: 0.70〜2.00（最大2本、上限合計 4.00人時・約32000円） 人時/本<br>C2 ブラケットボルトが固着した場合 [観察（重・中）] 要連絡（累積で超える）: 0.05〜0.30（最大4本、上限合計 1.20人時・約9600円） 人時/本<br>C3 スライドボルトが固着した場合 [未確認（ブーツに隠れて見えない）] 要連…: 0.05〜0.30（最大4本、上限合計 1.20人時・約9600円） 人時/本<br>C4 ローターがハブに固着していた場合 [未確認（ハブ錆グレード2）] 要連絡…: 0.15〜0.55（最大2片側、上限合計 1.10人時・約8800円） 人時/片側<br>C5 右スライドピンブーツが硬化していた場合 [未確認] 連絡不要（記録のみ）: 0.10〜0.20（最大1片側、上限合計 0.20人時・約1600円） 人時/片側<br>C6 ブレーキホースの劣化が見つかった場合 [未観察] 参考（U8・range…: 0.60〜1.00（最大1左右一式、上限合計 1.00人時・約8000円） 人時/左右一式<br>C7 腐食による作業範囲の拡大 [未確認部位: brake_area、subf…: 数値化しない（見積もり変更と顧客の了承が必要） | 合格 ✓✓✓ |
| S21 | 固着・腐食の確認優先度スコア（共通基準（重複控除後 1.7 人時）） | vehicle.first_registration / intake.date: 2014-01 / 2027-01-20<br>vehicle.odometer_km: 128000<br>condition.underbody_rust_grade（作業部位）: {"brake_area": 3, "wheel_hub": 2, "front_suspension": 2}<br>condition.underbody_rust_grade.subframe: None（不明）<br>condition.rustproof_undercoat: True（申告）<br>previous_visit_same_vehicle.observations: 固着あり（左前ブラケットボルト1本）<br>condition.fasteners（スライドボルト未確認・重の締結部）: 未確認4本・重2本（確認済み／不明）<br>condition.rotor_hub_seizure / slide_pin_boots: ローター未確認・右ブーツ['right']（不明）<br>shop_policy.priority_score_table_S21: 工場承認の加点表（架空）（仮定） | 初度登録からの経過年数: **13** 年<br>優先度スコア（加点の内訳つき）: **10** 点<br>帯: **高** -<br>確認の順番: **1. スライドボルト（ブーツ内）の錆 > 2. ローターとハブの固着（左右） > 3. 右スライドピンブーツの硬化 >…** -<br>帯ごとの high: **低 2.9 / 中 3.9 / 高 8.5** 人時<br>上限への加算（今回の帯）: **6.8** 人時<br>high: **8.5** 人時 | 人時 1.70 / **1.70** / 8.50<br>経過 1.70 / **1.70** / 8.75<br>優先度スコア: 10 点<br>優先度の帯: 高 -<br>確認の順番: 1. スライドボルト（ブーツ内）の錆 > 2. ローターとハブの固着（左右） > 3. 右スライド… -<br>確認の緊急度: 見積もり確定前に必ず確認 -<br>帯ごとの high: 低 2.9、中 3.9、高 8.5 人時 | 裁定済み ✗✗✓ |
| S22 | 付随作業・連鎖交換の候補リスト（C） | base_totals.deduplicated_base: 1.7<br>shop_policy.companion_parts_catalog_S22（頻度）: {"スライドピンブーツ": 0.3, "キャリパーブラケットボルト交換": 0.2, "パッド摩耗センサー": 0.1, "ブレーキホース…（仮定）<br>shop_policy.companion_parts_catalog_S22.display_threshold_freq: 0.15（仮定）<br>condition.slide_pin_boots.left: 問題あり（硬化）<br>condition.slide_pin_boots.right: 未確認（不明）<br>condition.fasteners（ブラケットボルト）: {"重": 2, "中": 2}<br>mechanic_provisional_add_ops.AG-BOOT: {"low": 0.1, "typical": 0.15, "high": 0.2}（仮定）<br>companion_parts_catalog_S22.キャリパーブラケットボルト交換.labor_hours_each: 0.0（仮定） | 表示する候補の数（頻度がしきい値以上）: **2** 件<br>左ブーツ（硬化を観察）を本体に入れる人時（typical）: **0.15** 人時<br>右ブーツ（未確認）の発生時の人時（high にだけ加算）: **0.2** 人時<br>ブラケットボルト交換の人時（人時に足さない）: **0** 人時<br>ブラケットボルト部品代（重＋中の全数交換した場合）: **1,800** 円<br>候補の期待人時の合計（参考。本体に入れない）: **0.09** 人時 | 人時 1.80 / **1.85** / 2.10<br>別記する候補リスト（仮定の頻度順。実績ではない。顧客への事前説明用。しきい値未…: part スライドピンブーツ、freq 0.3、freq_basis 整備士の見込み（架空・実績未… リスト<br>ブラケットボルト交換の部品代（候補。人時は固着対応に含み、見積もり本体には含め…: 1,800 円<br>右ブーツ交換の部品代（候補）: 1,200 円<br>左ブーツ交換の部品代（本体）: 1,200 円 | 裁定済み ✓✓✗ |
| S23 | 写真記録とAIによる一次分類（共） | photo_ai_S23.brake_area.mechanic_grade: 3<br>photo_ai_S23.brake_area.ai_grade(信頼度): 3(0.72)（仮定(AIは未検証。工数には使わない)）<br>photo_ai_S23.wheel_hub.mechanic_grade: 2<br>photo_ai_S23.wheel_hub.ai_grade(信頼度): 1(0.55)（仮定(AIは未検証。工数には使わない)）<br>photo_ai_S23.front_suspension.mechanic_grade: 2<br>photo_ai_S23.front_suspension.ai_grade(信頼度): 2(0.81)（仮定(AIは未検証。工数には使わない)）<br>photo_ai_S23.subframe.mechanic_grade: 未確認(写真なし)（不明）<br>photo_ai_S23.subframe.ai_grade(信頼度): なし（不明）<br>condition.underbody_rust_grade.rear_suspension: 1（確認済み(写真なし・目視値)）<br>condition.fasteners(J2, 錆=未確認): ["F-L-SLD-1", "F-L-SLD-2", "F-R-SLD-1", "F-R-SLD-2"]（不明(ブーツに隠れて見えない)）<br>condition.rotor_hub_seizure: 未確認（不明）<br>base_totals.deduplicated_base: 1.7 | 未確認の締結部(J2)の本数: **4** 本<br>固着対応の本数(low/typical/high): **1 / 2 / 7** 本<br>AI候補と整備士確定値の一致率: **0.67** 比<br>不一致の部位: **area wheel_hub、ai 1、mechanic 2、diff -1、ai_confidence 0.55** 部位<br>写真なし(未確認)の部位: **subframe** 部位<br>確定値での追加人時(low/typical/high): **0.1 / 0.7 / 5.2** 人時<br>AI候補のままの追加人時(low/typical/high): **0.05 / 0.5 / 4.9** 人時<br>AI候補採用との差(typical, 確定 - AI): **0.2** 人時<br>AI信頼度が0.6未満の不一致部位: **wheel_hub** 部位 | 人時 1.80 / **2.40** / 6.90<br>経過 2.35 / **2.95** / 7.45<br>AG04(穴あき等)の可能性がある部位: brake_area 部位<br>顧客連絡の目安(追加typicalが連絡しきい値を超える): はい 真偽<br>AI候補のまま計算した場合の labor_hours(参考、採用しない): 1.75 / 2.2 / 6.6 人時 | 裁定済み ✓✗✓ |
| S24 | 下回り撮影ガイド（A） | photo_guide_S24.required_shots_for_J2: ["左ブラケット", "右ブラケット", "左ハブ", "右ハブ", "左スライドピンブーツ", "右スライドピンブーツ", "サブフレー…<br>photo_guide_S24.taken: ["右ハブ", "右ブラケット", "左スライドピンブーツ", "左ハブ", "左ブラケット", "左ローター裏"]<br>photo_guide_S24.missing_reason: {"右スライドピンブーツ": "泥と氷で撮影不可", "サブフレーム前部": "アンダーカバーで見えない"}<br>condition.rustproof_undercoat: True（申告）<br>condition.underbody_rust_grade.subframe: None（不明） | 撮影率: **0.75** 割合<br>未撮影部位: **右スライドピンブーツ / サブフレーム前部** 部位<br>撮影で状態を確認できる対象: **左ブラケットボルト2本 / 右ブラケットボルト2本 / 左スライドピンブーツ / 左ハブ当たり面の錆 / 右ハブ当たり…** 対象<br>撮影しても確認できない対象: **スライドボルト4本（ブーツに隠れる） / ローター・ハブの固着（分解前は外観から判断できない）** 対象<br>high に入れる撮影漏れの暫定人時: **0.2** 人時<br>人時(low/typical/high): **1.7 / 1.7 / 1.9** 人時 | 人時 1.70 / **1.70** / 1.90<br>撮影率: 0.75 割合<br>未撮影部位: 右スライドピンブーツ / サブフレーム前部 部位<br>確認項目: 防錆コートの上からは腐食が見えにくい可能性（HK07、仮説）。防錆コートあり（申告）。撮影済み部位… 文<br>撮影ガイド(位置と枚数): position 左ブラケット、shots 1、purpose 左ブラケットボルト2本の頭部腐食、… 位置別<br>撮影の再依頼: 右スライドピンブーツ（泥と氷の除去後） / サブフレーム前部（リフトアップ・カバー取り外しが可能か… 部位<br>他案への入力: 撮影率と未撮影部位を S02・S23・S29 に渡す 文 | 合格 ✓✓✓ |
| S25 | 音声入力による作業メモ（共） | voice_memo_S25.text: 左前、ブラケットボルト2本とも固着。1本は加熱で外れた、もう1本も外れた。左ローター固着、叩いて外した。右前は普通に外れた。右ブーツも硬化…<br>base_totals.deduplicated_base: 1.7<br>condition.fasteners(F-L-SLD-1,F-L-SLD-2,F-R-SLD-1,F-R-SLD-2): ["未確認（ブーツに隠れて見えない）"]（不明）<br>condition.slide_pin_boots.left: 問題あり（硬化）<br>memo.未確認の節: ["サブフレームは見てない"]（不明） | 振り分けた原因タグ（件数）: **固着対応 2、ローター固着 1、ブーツ交換 1、ボルト折れ 0** 本/側<br>部位と側の振り分け（行数。原因タグ件数の合計とは別）: **左前 キャリパーブラケットボルト -> 固着対応 x2 / 左前 ローター -> ローター固着 x1 / 右前 スライ…**<br>固着対応の追加人時: **0.1 / 0.6 / 2.4** 人時<br>ローター固着の追加人時: **0.1 / 0.2 / 0.8** 人時<br>ブーツ交換の追加人時（メモ外の左ブーツ観察分は typical・high のみ）: **0.1 / 0.3 / 0.4** 人時<br>状態タグ（HK01 錆・腐食）: **メモに「錆」の記載なし**<br>追加人時合計: **0.3 / 1.1 / 3.6** 人時<br>浸透待ち（経過時間のみ）: **0.25 / 0.25 / 0.25** 時間 | 人時 2.00 / **2.80** / 5.30<br>経過 2.25 / **3.05** / 5.55<br>メモから振り分けた固着対応本数: 2 本<br>加熱の記載: あり<br>整備士確認待ちの振り分け行数（部位と側の行。原因タグ件数の合計 4 とは別の数…: 3 行 | 裁定済み ✓✗✗ |
| S26 | 電子車検証の取込による車両情報の自動入力（共通基準（重複控除後 1.7 人時）） | e_shakensho_sample.車名: 架空メーカーA（申告）<br>e_shakensho_sample.型式: ABC-XYZ10（申告）<br>e_shakensho_sample.原動機の型式: 1AB（申告）<br>e_shakensho_sample.初度登録年月: 平成26年1月（申告）<br>e_shakensho_sample.車両重量: 1600kg（申告）<br>intake.date: 2027-01-20<br>vehicle.odometer_km: 128000<br>shop_policy.check_intensity_threshold: 10年 / 100000km（仮定）<br>shop_policy.priority_score_table_S21（年数・走行距離）: 年数10年以上=2、15年以上=3、10万km以上=1、15万km以上=2（仮定） | 初度登録（西暦）: **2014-01** 年-月<br>初度登録からの経過: **13年0か月** 年・月<br>経過年数（小数）: **13** 年<br>S04 へ渡す確認強度: **強** -<br>S21 へ渡す年数加点: **2** 点<br>S21 へ渡す走行距離加点: **1** 点<br>S21 へ渡す加点（車検証・走行分の小計）: **3** 点<br>車検証と vehicle の不一致: **0** 項目 | 人時 1.70 / **1.70** / 1.70<br>S04 へ渡す確認強度: 強 -<br>S21 へ渡す加点（年数＋走行距離）: 3 点<br>初度登録からの経過: 13年0か月 年・月 | 合格 ✓✓✓ |
| S27 | 暖房費等を配賦する時間単価計算機（共） | base_totals.deduplicated_base: 1.7<br>cost_data_S27.heating_yen: 1800000（申告）<br>cost_data_S27.heating_winter_months_yen: 1700000（申告）<br>cost_data_S27.annual_billable_hours: 3600（申告）<br>cost_data_S27.winter_billable_hours: 1450（申告）<br>cost_data_S27.target_profit_yen: 3000000（仮定） | 年間総コスト: **28,200,000** 円<br>年間配賦の時間単価: **7,833** 円/人時<br>うち暖房費の寄与（年間配賦）: **500** 円/人時<br>暖房以外の経費の単価: **7,333** 円/人時<br>冬季だけ配賦する暖房費の単価: **1,172** 円/人時<br>冬季の時間単価: **8,534** 円/人時<br>非冬季の時間単価: **7,361** 円/人時<br>加重平均の検算: **7,833** 円/人時 | 人時 1.70 / **1.70** / 1.70<br>時間単価（年間配賦）: 7,833 円/人時<br>時間単価（冬季）: 8,534 円/人時<br>時間単価（非冬季）: 7,361 円/人時<br>参考工賃（1.7人時 x 年間配賦単価）: 13,317 円<br>参考工賃（1.7人時 x 冬季単価）: 14,507 円<br>参考工賃（1.7人時 x 非冬季単価）: 12,514 円 | 合格 ✓✓✓ |
| S28 | 錆対応の材料・消耗品の別建て（共） | condition.fasteners (J2): 重2本 / 中2本 / 未確認4本（確認済み（スライドボルト4本は未確認））<br>condition.underbody_rust_grade.wheel_hub: 2<br>materials_S28: 浸透剤・加熱ガス・ハブ防錆・ボルト・ねじ山部材の単価（ブーツ単価は使わない）（仮定（架空の単価））<br>base_totals.deduplicated_base: 1.7 | 固着対応の候補本数: **2 / 4 / 8** 本<br>浸透剤＋加熱ガスの1本あたり: **128** 円/本<br>ハブ防錆の側数: **2 / 2 / 2** 側<br>交換ブラケットボルト数（折れ込み）: **0 / 0 / 2** 本<br>ねじ山修正部材: **0 / 0 / 2** か所<br>材料費合計: **668.5 / 924.5 / 6,736** 円<br>待機（経過時間のみ）: **0.55 / 0.55 / 0.55** h | 人時 1.70 / **1.70** / 1.70<br>経過 2.25 / **2.25** / 2.25<br>材料費合計（low）: 668.5 円<br>材料費合計（typical）: 924.5 円<br>材料費合計（high）: 6,736 円<br>ボルト・ナット・クリップの別記: ブラケットボルトは本数×単価で計上。ナット・クリップは数量・単価とも未確定のため金額なし（工場の単…<br>材料費内訳（low）: 浸透剤 196、加熱ガス 60、ハブ防錆剤 412.5、交換ボルト 0、ねじ山修正部材 0 円<br>材料費内訳（typical）: 浸透剤 392、加熱ガス 120、ハブ防錆剤 412.5、交換ボルト 0、ねじ山修正部材 0 円<br>材料費内訳（high）: 浸透剤 784、加熱ガス 240、ハブ防錆剤 412.5、交換ボルト 900、ねじ山修正部材 4,… 円<br>付随部品の候補（材料費の本体に入れない）: キャリパーブラケットボルト交換: freq 0.2、price_yen_each 450 円/本 | 再検証後に修正 ✓✗✓ |
| S29 | 顧客向けの説明シート（A） | base_totals.deduplicated_base: 1.7<br>condition.snow_on_body: 屋根・ボンネットに約15cm<br>condition.ice_in_wheel_house.locations: 2<br>condition.fasteners（ブラケット重/中）: 重2・中2<br>condition.fasteners（スライドボルト）: 未確認（ブーツに隠れて見えない）（不明）<br>condition.rotor_hub_seizure: 未確認（不明）<br>condition.slide_pin_boots: 左: 問題あり（硬化） / 右: 未確認<br>condition.underbody_rust_grade.subframe: None（不明）<br>photo_guide_S24.taken: 6/8 枚<br>condition.rustproof_undercoat: 2022年に下回り全体へ施工（顧客申告）。コートの上から腐食が見えにくい可能性（申告） | 顧客向けの行数（確定 / 可能性 / 未確認）。確定には基準作業（観察不要）を含む: **5 / 1 / 3** 行<br>写真つきの根拠がある行: **3** 行<br>確定行の追加人時（typical）: **0.66** 人時<br>固着の可能性行（typical / high）: **0.6 / 5.2** 人時<br>未確認行が high に足す人時: **2.2** 人時<br>追加人時の範囲（基準 1.7 を除く）: **0.5 / 1.26 / 8.45** 人時<br>経過時間に入れる待機: **1.05 / 1.05 / 1.05** 時間（low / typical / high） | 人時 2.35 / **3.16** / 10.45<br>経過 3.40 / **4.21** / 11.50<br>顧客向け見積もり行（根拠つき）: group A 基準作業、name 冬タイヤ交換＋フロントブレーキパッド・ローター交換（重複控除後… リスト<br>付随部品の候補（別記。頻度がしきい値以上。スライドピンブーツは確定行・未確認行…: part キャリパーブラケットボルト交換、freq 0.2 リスト<br>ブラケットボルト交換の部品代（候補。重・中の全数 4 本を交換する場合の最大額…: 1,800 円<br>作業前に顧客へ連絡する範囲（追加が0.5人時超）: typical / high 範囲<br>上限に含まれない未算入項目（人時0ではなく、人時を置けないため合計外）: 防錆アンダーコートの下に隠れた腐食（顧客申告。人時を置けず未算入。ブラケットボルト・サブフレーム周… リスト（合計に含まない）<br>labor_hours の定義: 実作業人時。範囲内の下回り洗浄を含む（SPEC U7）。請求人時は別項目 注記<br>請求人時（下回り洗浄を除く）: 2.2 / 2.96 / 10.15 人時<br>下回り洗浄（実施するが請求しない。labor_hours には含む）: 0.15 / 0.2 / 0.3 人時（請求外） | 要確認 ✓✗✓ |
| S30 | 3方式の根拠を並べる比較画面（A/B/C 併記） | base_totals.deduplicated_base: 1.7（仮定）<br>condition.fasteners (J2): 重2 / 中2 / 未確認4<br>condition.ice_in_wheel_house.locations: 2<br>condition.snow_on_body: 屋根・ボンネットに約15cm<br>condition.slide_pin_boots: 左: 問題あり（硬化） / 右: 未確認<br>condition.rotor_hub_seizure: 未確認（不明）<br>condition.underbody_rust_grade.wheel_hub: 2<br>condition.underbody_rust_grade.subframe: None（不明）<br>historical_records (J1+J2): ["R08", "R09", "R10", "R11"]（申告）<br>vehicle.first_registration: 2014-01（確認済み（この案では未使用: 年式だけで工数を増やさない…<br>vehicle.odometer_km: 128000（確認済み（この案では未使用: 走行距離だけで工数を増やさ… | 案A 締結部の補正（typical）: **0.6** 人時<br>案A 人時: **2.3** 人時<br>案B 類似実績の件数: **4** 件<br>案B 実績 actual の中央値: **2.35** 人時<br>案C 共有工程の重複控除後の工程合計: **1.7** 人時<br>案C 人時: **3.16** 人時<br>案C 経過時間の待機（typical）: **1.05** 時間<br>提示範囲（3方式の low の最小〜high の最大）: **1.8〜10.45** 人時 | 人時 1.80 / **2.30** / 10.45<br>経過 2.05 / **2.55** / 11.50<br>3方式の比較（根拠・不足情報・錆と固着の反映）: column 案A 基準＋締結部の補正、labor_hours 1.8 / 2.3 / 8.1、e… A/B/C の3列<br>3方式の typical の幅（比較用）: 2.3 / 3.16 人時<br>感度: 重の2本を折れ込みとして typical に入れた場合の typical: 案A 3.9、案C 4.76 人時<br>案C 請求人時（下回り洗浄を除く）: 2.2 / 2.96 / 10.15 人時<br>下回り洗浄（請求しない）: 工場方針で請求しない（前処理として実施はする）<br>担当者の選択と理由: 未選択（担当者が A/B/C のいずれか、または手入力を選び、理由を残す） | 合格 ✓✓✓ |

## 最終工数の一覧（typical の昇順）

| No | 案名 | low | typical | high | 備考 |
|---|---|---|---|---|---|
| S04 | 経過年数・走行距離による確認強度の切替 | 1.70 | 1.70 | 3.90 | typical は変えない（low=typical=1.7、SPEC 共通ルール10）。経過年数・走行距離は何を確認すべきかの切替にだけ使い、人時の根拠にしない（ルール5）。上限の幅は docs の S04 の仕組みに基づく（確認しなかった項目は未確認として上限の幅に反映する）… |
| S10 | 見積もりと実績の差分ログ | 1.70 | 1.70 | 1.70 | S10 は工数を算出しない案のため、U9 により low = typical = high = 基準 1.7 人時とする。区分別の差を人時に足すと季節・年式による一律加算になるため据え置き、S11・S12 の元データとして使う。参照実績「J1+J2 の全実績 (季節・年式では絞… |
| S21 | 固着・腐食の確認優先度スコア | 1.70 | 1.70 | 8.50 | 工数は変えない（typical=1.7）。スコアは確認の順番・緊急度と、上限に含める範囲を決めるために使い、人時へ直接変換しない。この案の範囲での上限（high）は、帯「高」の範囲として、未確認のスライドボルト4本・ローター2側・右ブーツ1側に加え、重の締結部2本の折れ込み抜き… |
| S24 | 下回り撮影ガイド | 1.70 | 1.70 | 1.90 | typical・low は 1.7 のまま。S24 は撮影位置と枚数の案内、撮影漏れの「未確認」表示、コート下の確認項目を出す入力支援で、typical には人時を足さない。SPEC 第2版 U2 の例外により、撮影漏れの未確認だけを上限の幅に反映し、右スライドピンブーツ（泥と… |
| S26 | 電子車検証の取込による車両情報の自動入力 | 1.70 | 1.70 | 1.70 | 工数は変えない。車検証の取込は入力の手間と転記ミスを減らす支援で、追加工程を生まない。経過年数は確認の強さと加点の入力に使うだけで、工数の倍率にしない。所有者・使用者の情報は取り込んでいない。 |
| S27 | 暖房費等を配賦する時間単価計算機 | 1.70 | 1.70 | 1.70 | 工数は変えない。暖房費は人時ではなく時間単価の側で扱うため、基準 1.7 人時を据え置く。季節別単価は選択肢として示すだけで、採用は工場の経営判断。 |
| S28 | 錆対応の材料・消耗品の別建て | 1.70 | 1.70 | 1.70 | 工数は変えない（SPEC U9: low=typical=high=1.7人時に据え置く）。経過時間は SPEC U5 に従い、人時 1.7 に浸透待ち0.25hと防錆乾燥0.3h（冬季仮説値）を足した値。S28 は固着対応・ハブ処置の作業人時を入れないので、この経過時間は過小… |
| S07 | 車格・タイヤ重量による作業負担区分 | 1.70 | 1.78 | 1.78 | [typical/high は仮定重量 23kg に基づく暫定値] 車格・タイヤサイズ・重量から区分を「2人作業」とし、運搬を2人作業にした分 +0.08 人時だけを反映。low は重量が20kg以下と確認できた場合の基準 1.7 人時。high はこの案の範囲での上限で、ty… |
| S22 | 付随作業・連鎖交換の候補リスト | 1.80 | 1.85 | 2.10 | 見積もり本体に入れるのは、観察で必要が分かっている左ブーツ交換だけ（low/typical/high）。右ブーツ（未確認）は、この案の範囲での上限として high にだけ加える。ブラケットボルト交換は catalog で工数 0（固着対応に含む）。これは固着対応を計上する他案が… |
| S06 | 入庫日の気象に連動した前処理の確認 | 1.90 | 2.01 | 2.25 | 前処理の人時は現車確認で決め、気象は確認を促すためだけに使う。 |
| S17 | 同時作業での共通工程の重複排除 | 1.95 | 2.05 | 2.55 | この案は、リフトアップ・前2輪脱着に加え、雪下ろし（PRE-SNOW）と下回り洗浄（PRE-WASH）も入庫1回の共通工程として、見積もり全体で1回だけ計上する。typical は 2.0 から控除 0.3 を引き、前処理 typical を足した値。low は各 low、hi… |
| S02 | 部位別の腐食グレード入力 | 1.75 | 2.10 | 2.80 | 関係部位のグレードだけから、錆落とし(HK01)とローター固着除去の追加工程を出した。high はこの案の範囲での上限で、範囲内に未確認の部位は無い。固着対応(浸透剤・加熱。AG01)は S03 の領域なので扱わない。サブフレームは J1・J2 では外さないため作業範囲外とし、… |
| S05 | 冬季の前処理モジュール | 2.05 | 2.21 | 2.55 | labor_hours は下回り洗浄を含む実作業人時。請求人時（洗浄を除く）は other_outputs に別掲。下回り洗浄を請求する方針なら請求人時は typical で 0.2 人時増える（未確定事項: 前処理を請求するか）。氷塊除去は PRE-ICE の単位（ホイールハ… |
| S03 | 締結部ごとの固着リスク表 | 1.80 | 2.30 | 8.10 | この案の範囲での上限を high とする。SPEC U3 の表どおり、中は low 0・typical/high で FX-SEIZE、重は全範囲で FX-SEIZE（high のみ FX-BROKEN と FX-THREAD を上乗せ）、未確認は high のみ FX-SEI… |
| S13 | 道内の整備工場間で匿名化した実績の共有 | 1.93 | 2.30 | 7.77 | 採用値は自工場の実績（足りないタグは整備士暫定値）。他工場の値は参照幅としてだけ示し、自工場値には使っていない。自工場typicalが参照幅の外のタグ: ローター固着。設備・技量・課金方針の差があるため、外れても自動では直さず整備士が理由を確認する。 |
| S30 | 3方式の根拠を並べる比較画面 | 1.80 | 2.30 | 10.45 | 担当者が方式を選ぶ前の「提示範囲」。low は3方式の low の最小、high は3方式の high の最大（この3方式の範囲での上限）で、typical には案Aを置いた（3方式を平均していない）。案Aは基準＋締結部（U3）、案Bは S08 と同じ類似実績、案Cは前処理を含… |
| S08 | 類似事例の検索と条件差の表示 | 1.90 | 2.35 | 3.00 | 採用 4 件は閾値 3 件以上。typical=実作業人時の中央値 2.35、low=最小 1.90、high=最大 3.00 とした（この案の範囲での上限は実績の最大）。作業範囲が J1+J2 の事例 R08〜R11 をすべて採用した。条件の記録がない事例（R10 の錆）は除… |
| S23 | 写真記録とAIによる一次分類 | 1.80 | 2.40 | 6.90 | 工数は整備士の確定値だけで計算した。AIは wheel_hub を 1(確定は 2)と低く出し、信頼度も 0.55 と低かったため、AI値のままだとハブ錆落としが抜けて過小になる。AI候補は一次分類と写真の記録に使う。J2 のスライドボルト4本は未確認(ブーツに隠れて見えない)… |
| S19 | 3点見積もり（少ない・標準・多い） | 1.95 | 2.45 | 9.30 | low/typical/high は『前提の違い』。high は『多い』前提（U3 の high、単価も high）でのこの案の範囲での上限。標準が最頻値かは実績で確かめる。前提の内容を見積書に併記する。 |
| S20 | 条件付き見積書（追加発生時の連絡基準） | 1.95 | 2.45 | 9.55 | 見積書は『確定 1.85人時（基準1.7+確定分）＋条件付き追加』の形で示す。low は重のボルトの固着対応 low のみ、typical は重・中のブラケットボルト4本の固着対応を見込み、high はこの案の範囲での上限として、折れ込み・ローター固着・未確認ボルト・右ブーツを… |
| S11 | 原因タグ別の追加人時の実績表 | 2.18 | 2.61 | 8.80 | 実績で置き換えられたのは n≥3 のタグだけ。ボルト折れ・氷塊除去は実績が1件のため参考にとどめ、暫定値を使った。経過時間は1人作業で直列とした簡易値。 |
| S01 | 状態チェックリスト加算型 | 2.00 | 2.65 | 9.60 | 基準 1.7 に、問題ありの項目の追加工程を加算。未確認 6 項目（スライドボルト4本・ローター左右・右ブーツ）は typical に入れず、この案の範囲での上限である high にだけ入れた（最大 +2.20 人時、「追加の可能性あり」として別表示も残す）。high には重2… |
| S09 | 同一車両の経年履歴の追跡 | 2.20 | 2.70 | 8.00 | 前回 R11 の固着対応の単価 0.25 人時/本を今回の締結部に当てはめて工数を算出した。本数は SPEC U3 に従い、low=重2本、typical=重2+中2本、high=さらに未確認スライドボルト4本と、重2本の折れ込み・ねじ山修正、ハブ錆進行の錆落とし。high は… |
| S14 | 工程別の作業時間を計測するアプリ | 2.42 | 2.78 | 6.82 | R09 の工程ログ1件（n=1）の換算による暫定の見積もり。high はこの案の範囲での上限（折れ込み＋ねじ山を含む）。参照件数が最小件数に満たないため、実績が3件以上になるまで参考値として扱う。 |
| S25 | 音声入力による作業メモ | 2.00 | 2.80 | 5.30 | 【参考試算】docs §4.5 の S25 の仕組みは、文字起こしを S10 の原因タグとメモに振り分けるところまで（入力支援）で、人時の算出は S11/S12 の実績表・暫定値の役割。ここの labor_hours・elapsed_hours は、振り分け結果が人時にどう響く… |
| S18 | 人時と経過時間・納期の分離計算 | 2.10 | 2.81 | 8.95 | 人時は請求の根拠、経過時間は納車予定。待機は作業者を拘束しない前提で人時に入れない。S18 は工程の前後関係から人時と経過時間を分ける案なので、依頼元の S18 実装指示（SPEC 外の例外）として U3 で typical に入る追加工程（雪下ろし、氷塊除去、中・重の固着対応… |
| S15 | 状態に応じて分岐する工程テンプレート | 2.20 | 3.05 | 9.60 | テンプレートは重複排除後 1.7 人時。この案の範囲での上限として、未確認の分岐は high にだけ入れ、typical に確定しない。錆「中」は low=0、「重」は low から固着対応、折れ込みは観察がないため high のみ（SPEC U3）。サブフレームは作業範囲外（… |
| S12 | 整備士の暫定値を実績で更新する補正表 | 2.35 | 3.16 | 10.45 | v2 は実績の中央値・範囲で更新した候補で、整備士の承認までは使わない。採用値は暫定値 v1 に今回の観察を当てた値。範囲は補正表にある追加工程のうち今回の観察で必要になるもので、実績タグのない工程（ねじ山修正、ハブ錆落とし、下回り洗浄）は v1 の暫定値のまま使う。high … |
| S16 | 質問形式の工程展開 | 2.35 | 3.16 | 11.35 | 冬季なら雪・氷の質問、確認強度「強」なら錆・ゴム部品の追加質問を出すが、強で増える追加分は人時0の確認事項で、経過年数・走行距離は工数を変えない。工程を展開する質問は季節・強度にかかわらず出すので、同じ観察なら同じ人時になる。締結部は U3 の表、待機は U5 に従った。未確認… |
| S29 | 顧客向けの説明シート | 2.35 | 3.16 | 10.45 | 範囲の幅は、確定した追加と、写真つきの可能性と、未確認の3区分に分けて顧客に見せるためのもの。high はこの案の範囲での上限（重のブラケットボルトの折れ込み抜き取り・ねじ山修正、未確認項目の上限を含む）。サブフレーム前部は作業範囲外（腐食があれば作業範囲の拡大として見積もりを… |

## 各案の手順・仮定・未確認

### S01 状態チェックリスト加算型

スクリプト: 同フォルダの `s01_*.py`。仮定・未確認の全文は [results/S01.json](results/S01.json)

1. 手順1: 重複控除後の基準 1.7 人時を出発点にする
2. 手順2: J1/J2 の錆・固着・損傷・改造のチェック項目を現車状態から作る
3. 手順3: 各項目を 未確認／問題を観察していない／問題あり に分ける
4. 手順4: 問題あり → 追加工程の人時を加算。締結部は U3 の表（中: low 0・typical FX-SEIZE typical・high FX-SEIZE high、重: low FX-SEIZE low・typical FX-SEIZE typical・high FX-SEIZE high + FX-BROKEN high + FX-THREAD high）
5. 手順5: 未確認（スライドボルト4本・ローター左右・右ブーツ）は typical に入れず、high にだけ追加工程の high を加算する。「追加の可能性あり」の別表示と unknowns も残す
6. 手順6: 浸透待ち 0.25 を FX-SEIZE を含む区分、防錆乾燥 0.3（冬季仮説値）を FX-HUBCLEAN を含む区分の経過時間にだけ足す。融解待ち・冬季前処理は S05 の領分のため扱わない

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格

### S02 部位別の腐食グレード入力

スクリプト: 同フォルダの `s02_*.py`。仮定・未確認の全文は [results/S02.json](results/S02.json)

1. 手順1: 基準 1.7 人時(重複控除後)から始める
2. 手順2: J1/J2 に関係する部位(brake_area, wheel_hub, front_suspension, rear_suspension)だけグレードを読む。subframe は外さないので作業範囲外
3. 手順3: グレード→追加工程・数量の対応表(仮定)と整備士暫定値で low/typical/high の追加人時を出す
4. 手順4: ローター固着は部位間の最大、ハブ錆落としは前2輪1回で二重加算を避ける
5. 手順5: 範囲内の関係部位が未確認なら typical に入れず high にグレード3相当を入れる(現在は該当なし)。subframe は high に入れず unknowns に記録する
6. 手順6: グレード3または範囲内で未確認の関係部位は AG04 の可能性として見積変更の要否確認を促す(工数には足さない)。固着対応(FX-SEIZE)・浸透待ちは S03 の領域のため扱わない
7. 手順7: 経過時間 = 人時 + (FX-HUBCLEAN を含む case のみ)防錆乾燥の待機。待機は人時に入れない

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格

### S03 締結部ごとの固着リスク表

スクリプト: 同フォルダの `s03_*.py`。仮定・未確認の全文は [results/S03.json](results/S03.json)

1. 手順1: 基準 1.7 人時を出発点にする
2. 手順2: condition.fasteners を1本ずつ列挙（ホイールナットは count 分）
3. 手順3: fastener_risk_rule で 通常/固着対応の可能性/折れ込みの可能性/不明 に判定
4. 手順4: 区分ごとの本数を数える
5. 手順5: SPEC U3 の表で当てる（中: 0/typ/high、重: low/typ/high＋high のみ折れ込み・ねじ山、未確認: high のみ FX-SEIZE）
6. 手順6: 本数 x 単価を積み上げて追加人時（作業全体の倍率は使わない）
7. 手順7: 人時 = 1.7 + 追加人時
8. 手順8: FX-SEIZE を含む範囲の経過時間にだけ浸透待ちを足す（U5）

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格

### S04 経過年数・走行距離による確認強度の切替

スクリプト: 同フォルダの `s04_*.py`。仮定・未確認の全文は [results/S04.json](results/S04.json)

1. 手順1: first_registration と intake.date から初度登録からの経過年数を月単位で計算する
2. 手順2: 経過年数と走行距離を check_intensity_threshold（年数・距離）と比べる。どちらか満たせば確認強度「強」
3. 手順3: 強なら追加確認項目（下回りの撮影、締結部の観察、ゴム部品の状態）を出す
4. 手順4: 追加確認項目のうち condition が「未確認」のものを数える
5. 手順5: typical は増やさない。low = typical = 基準 1.7 人時
6. 手順6: 強のとき未確認の追加確認項目（スライドボルト・ローター・ブーツ）を FX-SEIZE / FX-ROTOR / AG-BOOT の high 値で high にだけ加える。サブフレームは作業範囲外として unknowns に残す（U4）
7. 手順7: high に FX-SEIZE を含めるので、high の経過時間にだけ浸透待ちを足す（U5）

- 3重チェック: 算術: 合格、入力: 合格、仕様: 不合格 (2) U1 違反。high に加えているローター固着の未確認（FX-ROTOR 2側 = 0.8人時）は、docs §4 S04 の仕組みが挙げる追加確認項目（下回りの撮影、締結部の観察、ゴム部品の状態）に含まれない。ローター固着は U1 の『§3 の主に扱う要因（AG07）と §4 の仕組みの工程』の範囲外。S0…（初回不合格 → Sonnet が修正 → 再検証）
- 裁定済み: ローター固着を high に含めたのはオーケストレーターの個別指示（docs の「未確認は上限の幅に反映」を、追加確認項目の対象部位に広げた）。

### S05 冬季の前処理モジュール

スクリプト: 同フォルダの `s05_*.py`。仮定・未確認の全文は [results/S05.json](results/S05.json)

1. 手順1: 重複控除後の基準 1.7 人時を出発点にする
2. 手順2: 屋根・ボンネットの雪を確認し、雪下ろしを入庫1回だけ付ける
3. 手順3: ホイールハウスの氷のある箇所数（前輪2）× 氷塊除去を付ける
4. 手順4: 氷があれば融解待ちを経過時間にだけ入れる（人時0）。雪・氷が未確認なら 0 で確定せず high にだけ入れる
5. 手順5: 下回り洗浄は実施するが請求しない。実作業人時には入れ（labor_hours）、請求人時（洗浄を除く）は other_outputs に別に出す
6. 手順6: 前処理はJ1・J2に分けず見積もり全体に1回だけ付ける
7. 手順7: low/typical/high を暫定値の同名列で合計する。labor_hours は実作業人時、前処理以外の要因は加算しない

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格

### S06 入庫日の気象に連動した前処理の確認

スクリプト: 同フォルダの `s06_*.py`。仮定・未確認の全文は [results/S06.json](results/S06.json)

1. 手順1: 入庫日の予報を shop_policy.weather_prompt_threshold と比べ、どちらか満たせば前処理の確認を促す表示を出す
2. 手順2: 気象からは人時を決めない。入庫時の現車確認（雪の状態、ホイールハウスの氷の箇所数）で決める
3. 手順3: 雪下ろし＝入庫1回分、氷塊除去＝箇所数×単価。未確認は high のみに含める
4. 手順4: 重複控除後の基準1.7人時に low/typical/high の前処理を加える
5. 手順5: 融解待ち（U5）は氷塊除去を含む low/typical/high それぞれの経過時間にだけ足す。請求対象は雪下ろし・氷塊除去

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格

### S07 車格・タイヤ重量による作業負担区分

スクリプト: 同フォルダの `s07_*.py`。仮定・未確認の全文は [results/S07.json](results/S07.json)

1. 手順1: 重複控除後の基準 1.7 人時を出発点にする(基準は1人運搬 0.12 人時を含む)
2. 手順2: 車格「普通車SUV」とタイヤサイズ「225/65R17」から 大型側 と見る(軽でなく 17インチ)。これは2人運搬の可能性を見る目安で、数値基準は仮定
3. 手順3: ホイール付き1本 23kg(仮定)を 閾値 20kg 超・1人運搬の上限 18kg と比べる。タイヤリフターはなし、作業可能人数 2 人。区分は「2人作業」
4. 手順4: OP-TIRE-CARRY を 人数x時間 で再計算する: 2人 2x0.1 = 0.2 人時、1人 0.12 人時。差分 +0.08 人時
5. 手順5: typical = high = 基準 + 差分 = 1.78 人時。low は重量が20kg以下と確認できた場合の基準 1.7 人時
6. 手順6: 経過時間は算出しない(null)。運搬工程だけの経過時間の差は intermediates に出す

- 3重チェック: 算術: 合格、入力: 合格、仕様: 不合格 仕組みと実装の不一致。docs §4 S07 は「車格・タイヤサイズから『1人／2人または機材』の区分を出し」とするが、s07_tire_weight_load_class.py は区分を重量 weight だけで決めている（cls は weight と LIMIT_1P/LIMIT_2P のみで分岐）。large_…／SPEC U2 違反（high の定義）。S07 の範囲内の未確認は『OP-TIRE-CARRY が4本セットか1本ごとか』で、unknowns 自身が『1本ごとなら差分は最大4倍（+0.32人時）』と書いている。U2 は範囲内の未確認の上限を high に含めるよう定めるが、high = typical = 1.7…／出力 JSON の elapsed_hours を null にしている。SPEC の出力 JSON 仕様は、null にしてよいのは『待機や2人作業を扱わない案』だけとしている。S07 は 2人作業を扱うので、null の根拠がない。スクリプトは運搬工程の経過時間差 -0.02 時間を intermediates …（初回不合格 → Sonnet が修正 → 再検証）
- 要確認: 車格・タイヤサイズを判定に使う個別指示に対し、実装は区分を重量で決めており、車格は表示にとどまる。人時の値（＋0.08）は変わらない。

### S08 類似事例の検索と条件差の表示

スクリプト: 同フォルダの `s08_*.py`。仮定・未確認の全文は [results/S08.json](results/S08.json)

1. 手順1: 作業範囲（J1+J2）が同一の実績 R08〜R11 をすべて候補にする（同一車両 R11 を含む）
2. 手順2: 候補ごとに 錆・固着の状態、経過年数、季節 を 一致/相違/条件不明 で比較して表示（車格は表示のみ）
3. 手順3: 条件の相違や記録なしがあっても除外せず、候補をすべて採用する
4. 手順4: 採用事例の実作業人時の中央値・件数・範囲を出す
5. 手順5: 件数が min_records_for_reference 以上なら typical=中央値、low=最小、high=最大（未満なら基準 1.7 据え置き）

- 3重チェック: 入力: 合格、算術: 合格、仕様: 不合格 チェック(3) U2 違反。S08 は範囲を「全般」（U1）としているのに、high を実績の最大値 3.00 だけにしている。U2 の high は「その案の範囲での上限。範囲内の未確認項目の上限を含める」。範囲内の未確認（F-L-SLD-1/2、F-R-SLD-1/2 のスライドボルト、ローターのハブ固着、ハブ当…／チェック(5) U5 違反（経過時間）。S08 の範囲は全般（U1）で、ハブ錆グレード2・FX-HUBCLEAN（ハブ当たり面の錆落とし・防錆）を含むため、U5 により防錆乾燥 0.3 時間（冬季仮説値）を経過時間に足すべきだが、script は浸透待ち 0.25 と融解待ち 0.5 の 0.75 時間だけを足してい…（初回不合格 → Sonnet が修正 → 再検証）
- 裁定済み: 方式Bの high は類似実績の最大値とする個別指示に従った。観察項目からの上乗せは方式A・C側の役割。

### S09 同一車両の経年履歴の追跡

スクリプト: 同フォルダの `s09_*.py`。仮定・未確認の全文は [results/S09.json](results/S09.json)

1. 手順1: 基準 1.7 人時を出発点にする
2. 手順2: 前回と今回を並べる（経過年数・走行距離の差、ハブ錆の変化）
3. 手順3: 前回 R11 の観察から固着対応の単価 0.25 人時/本を取る
4. 手順4: SPEC U3 の表で今回の締結部に本数を割り当て、単価を掛ける（重は high に折れ込み・ねじ山修正を足す）
5. 手順5: 前回なかった変化（ハブ錆の進行）は確認箇所に出し、範囲内の錆落としを high に入れる
6. 手順6: 待機（浸透待ち・防錆乾燥）を経過時間にだけ足す。雪下ろし・氷塊は範囲外

- 3重チェック: 入力: 合格、算術: 不合格 U3 の単価割り当てと食い違う。S09 は固着対応の単価を R11 の 0.25 人時/本で全レンジに一律に使っているが、U3 の表は締結部ごとに FX-SEIZE の low 0.05 / typical 0.15 / high 0.30 を割り当てる規定で、S09 は S11〜S14 のような『単価を自分の実績に…、仕様: 不合格 U3 違反: S09 は FX-SEIZE の代わりに前回 R11 の単価 0.25 人時/本を low / typical / high の全レンジに使っている。SPEC U3 が単価の置き換えを認めているのは S11〜S14 だけで、S09 は対象外。U3 の表どおりなら、締結部の単価は FX-SEIZE low…／U2 違反: high は『この案の範囲での上限』でなければならないが、固定単価 0.25 は FX-SEIZE high 0.30 より低いため、high が上限になっていない。範囲内の未確認スライドボルト4本とブラケット重・中の本数はすべて high に入るので、その分だけ high が過小になる。S09.jso…（初回不合格 → Sonnet が修正 → 再検証）
- 裁定済み: 同一車両の前回実績の単価 0.25 人時/本を使う個別指示に従った（S09 の仕組みは同一車両の履歴を使うこと）。

### S10 見積もりと実績の差分ログ

スクリプト: 同フォルダの `s10_*.py`。仮定・未確認の全文は [results/S10.json](results/S10.json)

1. 手順1: 重複控除後の基準 1.7 人時を出発点にする
2. 手順2: 今回の区分 (冬季 / 初度登録から13年 / J1+J2) を決める。診断表示用で、人時の計算には使わない
3. 手順3: 実績ごとに 差 = actual - estimate と、原因タグ hours の合計・説明できない差を出す
4. 手順4: 冬季/冬季以外 x 経過年数区分と月別で、件数・差の平均・中央値・最小・最大・原因タグの内訳を集計する (S11・S12 の元データ)
5. 手順5: 参照実績は同じ作業構成 (J1+J2) の全実績。件数が足りなければ全作業を参考扱い。差の大きさを示す診断に使う
6. 手順6: U9 により low = typical = high = 基準 1.7 人時。区分別の差を足すと季節・年式による一律加算になるため据え置く
7. 手順7: 参照区分のタグ別平均と説明できない差を並べて、延びの原因を示す
8. 手順8: 今回車両の個別状態 (固着・腐食等) は加算しない

- 3重チェック: 算術: 合格、入力: 合格、仕様: 合格（初回不合格 → Sonnet が修正 → 再検証）

### S11 原因タグ別の追加人時の実績表

スクリプト: 同フォルダの `s11_*.py`。仮定・未確認の全文は [results/S11.json](results/S11.json)

1. 手順1: 基準 1.7 人時を出発点にする
2. 手順2: 実績のタグを単位あたり人時（本・片側・か所・入庫1回）に正規化
3. 手順3: タグごとに件数・中央値・範囲の表を作る
4. 手順4: 件数が 3 以上は実績（low=最小, typical=中央値, high=最大）、未満は整備士暫定値にフォールバック
5. 手順5: 今回の観察を単位数に変換（U3: 重は low から、中は typical から、未確認は high のみ。折れ込み・ねじ山は high のみ）
6. 手順6: 単位数 x 単位あたり人時を積み上げ（作業全体の倍率は使わない）
7. 手順7: 人時 = 1.7 + 追加人時
8. 手順8: 融解待ち・浸透待ちは該当する範囲の経過時間にだけ足す（U5）

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格

### S12 整備士の暫定値を実績で更新する補正表

スクリプト: 同フォルダの `s12_*.py`。仮定・未確認の全文は [results/S12.json](results/S12.json)

1. 手順1: 基準 1.7 人時を出発点にする
2. 手順2: 補正表 v1 = 整備士の暫定値（仮定。承認の記録なし）
3. 手順3: 実績の原因タグを追加工程に対応づけ、1本・1側・1か所あたり人時にする
4. 手順4: 工程ごとに件数・中央値・最小・最大を求める（3件未満は参考のみ）
5. 手順5: n>=3 の工程は実績の中央値と範囲（最小・最大）で補正表 v2 候補を作る（自動適用しない）
6. 手順6: 今回の観察を追加工程の数量に変換（締結部は U3: 重は low も固着対応、high に折れ込み+ねじ山修正、未確認は high のみ。サブフレームは作業範囲外）
7. 手順7: 同じ数量に v1 と v2 を当てはめ、追加人時を比べる
8. 手順8: 暫定値 v1 を採用値とし、人時 = 1.7 + v1の追加人時
9. 手順9: 経過時間 = 人時 + 融解待ち（氷塊除去を含む範囲）+ 浸透待ち（FX-SEIZE を含む範囲）+ 防錆乾燥（FX-HUBCLEAN を含む範囲）。下回り洗浄は請求しないが実作業なので人時に入れる

- 3重チェック: 算術: 不合格 範囲の定義（実績タグのある工程のみ）と、タグのない FX-THREAD を high に入れる実装が食い違う。FX-HUBCLEAN と PRE-WASH を外す根拠がない、仕様: 不合格 FX-HUBCLEAN を範囲外とする根拠が U1 にも裁定にもない、入力: 合格（初回不合格 → Sonnet が修正 → 再検証）
- 再検証後に修正: 再検証（Haiku 3体）で範囲の不整合を指摘された。範囲を「補正表にある追加工程のうち今回の観察で必要になるもの」にそろえ、ハブ錆落としと下回り洗浄（請求しないが実作業）を入れ、防錆乾燥の待機を足した。人時は 2.35/3.16/10.45、経過時間は 3.40/4.21/11.50 になり、再検証の算術担当の概算と一致する。修正後の再検証はしていない。

### S13 道内の整備工場間で匿名化した実績の共有

スクリプト: 同フォルダの `s13_*.py`。仮定・未確認の全文は [results/S13.json](results/S13.json)

1. 手順1: 基準 1.7 人時を出発点にする
2. 手順2: 自工場の実績から、タグ別に1本（ローターは1側）あたりの人時を hours/count で求める。固着対応は現車と同じブレーキ周り腐食グレードの記録に絞る
3. 手順3: 実績が3件以上ならその最小/中央値/最大を採用、足りなければ整備士暫定値を採用
4. 手順4: 他工場（shop_X, shop_Y）の中央値を並べて参照幅と件数加重平均を出す。採用はしない
5. 手順5: 現車の締結部を fastener_risk_rule で 通常/固着対応/折れ込み/不明 に分類
6. 手順6: 採用単価で U3 の表どおりに積み上げ（中は low 0・typical/high 固着対応。重は全区分で固着対応、high のみ さらに折れ+ねじ山。未確認と ローター固着は high のみ）
7. 手順7: 人時 = 1.7 + 追加人時
8. 手順8: 浸透待ち（U5）は固着対応を含む区分の経過時間にだけ足す
9. 手順9: 他工場の参照幅で同じ積み上げをした参考人時を並べ、自工場値の妥当性を確認する

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格

### S14 工程別の作業時間を計測するアプリ

スクリプト: 同フォルダの `s14_*.py`。仮定・未確認の全文は [results/S14.json](results/S14.json)

1. 手順1: scenario.json を読み、出発点を重複控除後の基準 1.7 人時にする
2. 手順2: tap_log_R09 を集計する。工程の人時=人数x時間、待機は人時0で経過時間にだけ入れる。R09 の実績 3.0 人時を再現して確かめる
3. 手順3: 工程を基準工程と追加工程（雪下ろし・氷塊・固着対応・ローター固着・その他）に分け、基準工程が 1.7 人時と一致することを assert で確かめる
4. 手順4: 追加工程の実測を換算単価にする（氷塊=1か所、固着対応=1本、ローター固着=片側あたり）
5. 手順5: SPEC U3 の表に沿って本数を数える。中2本は low 0・typical/high 固着対応、重2本は low/typical 固着対応・high は固着対応＋折れ込み（R02 実測 0.85 人時/本）＋ねじ山（FX-THREAD high）、未確認スライドボルト4本は high にだけ固着対応。ローター固着2側も high にだけ入れる。R09 の「その他」は範囲外なので入れない
6. 手順6: 1.7 + 追加人時 を low / typical / high で出す。年式・地域からは加算しない
7. 手順7: 経過時間 = 基準工程の実測時間 + 追加工程の時間 + 待機（U5: 氷塊除去を含めれば融解待ち、固着対応があれば浸透待ちを足す）
8. 手順8: 実測が1件だけで最小参照件数(3)に満たないことを unknowns に記録する

- 3重チェック: 算術: 合格、入力: 合格、仕様: 合格（初回不合格 → Sonnet が修正 → 再検証）

### S15 状態に応じて分岐する工程テンプレート

スクリプト: 同フォルダの `s15_*.py`。仮定・未確認の全文は [results/S15.json](results/S15.json)

1. 手順1: scenario.json を読む
2. 手順2: J1・J2 の included_operations をテンプレートにし、op ID が同じ共通工程は1回だけ数える（合計 1.7 人時）
3. 手順3: condition の各状態を分岐条件 B1〜B8 に当てて 発火 / 未発火 / 判定不能 を判定
4. 手順4: 発火した分岐は追加工程を全範囲に、判定不能（未確認）は high にだけ展開（数量 x 単価）
5. 手順5: 人時 = 1.7 + 追加工程の合計（他案の要因・地域・年式・走行距離は加えない）
6. 手順6: 経過時間に待機を足す（FX-SEIZE を含む範囲に浸透待ち 0.25、FX-HUBCLEAN を含む範囲に防錆乾燥 0.3。人時には入れない）
7. 手順7: SPEC の形で出力

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格

### S16 質問形式の工程展開

スクリプト: 同フォルダの `s16_*.py`。仮定・未確認の全文は [results/S16.json](results/S16.json)

1. 手順1: 基準 1.7 人時から始める(前処理は S16 の範囲なので手順3の質問から展開して足す)
2. 手順2: 季節(冬季か)と、経過年数・走行距離から確認強度(通常/強)を決める。工数は変えない
3. 手順3: 作業ごとの質問バンクから質問を選ぶ。工程を展開する質問は常に出す。冬季なら雪・氷の質問、強なら錆・ゴム部品の追加質問が増える(追加分は人時0の確認事項)
4. 手順4: scenario の condition から各質問の回答(問題あり/なし/未確認)を導く
5. 手順5: 回答ごとに工程を展開する。締結部は U3 の表(中=固着対応、重=固着対応＋high に折れ込み・ねじ山、未確認=high に固着対応のみ)。サブフレームは U4 により作業範囲外
6. 手順6: 展開工程の人時を low/typical/high で合計して基準に足す
7. 手順7: U5 に従い、FX-SEIZE を含む水準に浸透待ち、FX-HUBCLEAN を含む水準に防錆乾燥、氷塊除去を含む水準に融解待ちを、経過時間にだけ足す

- 3重チェック: 入力: 合格、算術: 合格、仕様: 合格（初回不合格 → Sonnet が修正 → 再検証）

### S17 同時作業での共通工程の重複排除

スクリプト: 同フォルダの `s17_*.py`。仮定・未確認の全文は [results/S17.json](results/S17.json)

1. 手順1: 各作業の基準人時を合計して重複控除前の総和を出す（S17 は 2.0 から開始）
2. 手順2: 各作業の included_operations の合計が基準人時と一致するか検算する
3. 手順3: op ID ごとに出現する作業を集め、shared=true で2作業以上に現れる op（リフトアップ・前2輪の脱着）を共通工程とする
4. 手順4: 共通工程を最初の作業に1回だけ残し、2回目以降の作業から hours を控除して控除後（1.7）を出し、scenario の deduplicated_base と検算する
5. 手順5: shared=false の op は控除しない。控除の可否は整備士が確認する
6. 手順6: 雪下ろし（PRE-SNOW）と下回り洗浄（PRE-WASH）も入庫1回の共通工程として、見積もり全体で1回だけ加える。手順3の検出対象はリフトアップ・前2輪脱着だけで、前処理は included_operations から検出せず mechanic_provisional_add_ops の暫定値を固定で加える
7. 手順7: typical = 控除後 + PRE-SNOW typical + PRE-WASH typical。low は控除後 + 各 low、high は控除なし（控除を整備士が認めない場合）+ 各 high
8. 手順8: 作業ごとに重ねた場合との差を intermediates に出す（前処理分は typical から引かず、仮想の差として示す）。下回り洗浄は実作業人時として入れ、請求人時は別に示す

- 3重チェック: 算術: 合格、入力: 合格、仕様: 不合格 前処理（PRE-SNOW・PRE-WASH）を観察と結びつけずに固定で加算している。s17_shared_operation_dedup.py は scenario の condition.snow_on_body（問題あり）を読まず、mechanic_provisional_add_ops の typical 0.…／U2 の high に、範囲内の未確認項目の上限が入っていない疑いがある。unknowns は『J1 と J2 を同じ入庫で続けて作業できるか』を未確認として挙げ、『別入庫なら前処理2回分（約3.10）』を『範囲外』として high から外している。しかし『見積もり全体で1回計上』は S17 の仕組みそのものであり、…（初回不合格 → Sonnet が修正 → 再検証）
- 要確認: 雪下ろし・下回り洗浄の加算を、入庫時の観察（車体の積雪あり）に結びつけていない。今回のシナリオでは値は同じ。

### S18 人時と経過時間・納期の分離計算

スクリプト: 同フォルダの `s18_*.py`。仮定・未確認の全文は [results/S18.json](results/S18.json)

1. 手順1: 重複控除後の基準 1.7 人時を、工程の和として検算する
2. 手順2: S18 の実装指示（工程の前後関係から人時と経過時間を分ける案なので追加工程を工程表に載せる、という依頼元の指示。SPEC の U1〜U9 とは別に受けた例外）として、U3 で typical に入る追加工程（雪下ろし、氷塊除去、中・重の固着対応 FX-SEIZE、ハブ錆落とし FX-HUBCLEAN）を工程表に載せる。high は U3 の high（重の折れ込み FX-BROKEN・FX-THREAD、未確認の FX-SEIZE）を足す
3. 手順3: 雪下ろし->リフト、氷塊除去->融解待ち->リフト（雪下ろしは融解待ちの前提にしない。氷塊の融解は雪下ろしと独立に進む）->前輪->浸透待ち->固着対応->ブレーキ->組付け->試運転の依存グラフを作る。後輪は前輪・ブレーキと並行可。ハブ錆落としはローター脱着後にパッド交換と並行可
4. 手順4: 融解待ち 0.5・浸透待ち 0.25（固着対応を含む水準）・防錆乾燥 0.3 を経過時間にだけ入れる（U5）。部品待ちは 0
5. 手順5: 作業者2人で依存順に割り当て、経過時間を求める（1人の場合も別掲）
6. 手順6: 経過時間 + 部品待ちを納車見込みとして出す。人時は作業者数で変わらない

- 3重チェック: 算術: 不合格 U1 scope deviation: S18 includes PRE-SNOW (雪下ろし, 0.10/0.15/0.25 人時) and adds HK01/HK02 to factors. U1 defines the scope as docs §3 主に扱う要因 (HK03, HK07 for S18) …、仕様: 不合格 U1 違反（範囲外の要因を人時に入れている）。SPEC U1 の範囲は docs §3 の『主に扱う要因』（S18 は HK03・HK07）と §4 S18 の『仕組み』の工程。§4 の仕組みは工程の前後関係と待機（融解・浸透・乾燥・部品待ち）だけを挙げ、雪下ろし（HK02）も固着した締結部の対応（HK01）の作業時…、入力: 不合格 再現性の確認が成立しない。s18_labor_vs_elapsed.py は実行時に results/S18.json を自分で上書きする（末尾の write_text）。実行前の S18.json は git 未追跡（?? 状態）でベースラインがなく、実行前の内容と比較できないまま上書きされた。現在のファイルは標準…（初回不合格 → Sonnet が修正 → 再検証）
- 裁定済み: 工程表に U3 の typical の追加工程を載せるのは、S18 の仕組み（工程の前後関係から人時と経過時間を分けて計算）による例外として個別指示した。

### S19 3点見積もり（少ない・標準・多い）

スクリプト: 同フォルダの `s19_*.py`。仮定・未確認の全文は [results/S19.json](results/S19.json)

1. 手順1: 基準 1.7 人時を出発点にする
2. 手順2: 観察（ブラケット重2・中2、スライド未確認4、ローター未確認、左ブーツ硬化）を数える
3. 手順3: 「固着は重のみ軽微」「一部固着」「固着が多く、ボルト折れあり」の3前提を、観察に対応づけた追加工程の数で定義。「多い」は U3 の high（重=固着対応+折れ込み+ねじ山、未確認スライド=固着対応）。観察済みの左ブーツ交換は全前提に入れる（硬化した部品は外すと壊れる付随部品として AG02 に当てる）
4. 手順4: 追加人時 = 工程数 x 暫定単価。少ないの FX-SEIZE は low、他の少ない・標準は typical、多いは high 単価。low/typical/high は3前提に対応
5. 手順5: 人時 = 1.7 + 追加人時（倍率や地域・年式からの加算はしない）
6. 手順6: 単価を low/high に振った幅を参考に併記
7. 手順7: U5 に従い、浸透待ち0.25時間を FX-SEIZE を含む前提（少ない・標準・多い）の経過時間に加算。人時には入れない

- 3重チェック: 入力: 合格、算術: 不合格 多い（high）の追加人時 7.6 に含まれる FX-ROTOR 2側（0.80 人時）が、S19 の手順3の定義（「多い」＝U3 の high。重・中・未確認スライドの締結部だけ）にも U3 の表にも載っていない。ローターは締結部ではなく、§4 の仕組みにも明記されていない。assumptions の『U2 の未確…、仕様: 合格（初回不合格 → Sonnet が修正 → 再検証）
- 裁定済み: 未確認のローター固着を「多い」の前提に含めるのは U2（範囲内の未確認を上限に含める）による。

### S20 条件付き見積書（追加発生時の連絡基準）

スクリプト: 同フォルダの `s20_*.py`。仮定・未確認の全文は [results/S20.json](results/S20.json)

1. 手順1: 重複控除後の基準 1.7 人時から始める
2. 手順2: 観察済みで問題ありの項目（左ブーツ硬化）だけを確定分として加算する
3. 手順2b: 経過年数・走行距離は工数にも条件数にも使わない。確認強度で未確認の条件を消さず、常に条件表と high に載せる（AG07、U2・U3）
4. 手順3: 固着・折れ込み・ローター固着・右ブーツ・ホース等を『発生条件・件数・追加人時の範囲』として条件化する（C1〜C6）。ホース C6 は U8 により参考のみ。数値化できない範囲拡大は C7（サブフレームは作業範囲外のため人時に入れない、U4）
5. 手順4: 年間配賦の時間単価を算出し、金額基準を人時に直す（仮定）
6. 手順5: 条件ごとに、1回あたりまたは最大件数ぶんの上限が 0.5人時／5000円 を超えうるかで連絡要否を判定する
7. 手順6（U3）: low=基準+確定分+重ボルトの FX-SEIZE low、typical=確定分+重・中ボルトの FX-SEIZE typical、high=重・中の FX-SEIZE high+重の折れ込み(FX-BROKEN+FX-THREAD)+未確認ボルト・ローター・右ブーツの上限（ホースは含めない）
8. 手順7（U5）: 浸透待ちを FX-SEIZE を含む low/typical/high の経過時間に足す。high は C4 を含むので防錆乾燥待ちも足す

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格（初回不合格 → Sonnet が修正 → 再検証）

### S21 固着・腐食の確認優先度スコア

スクリプト: 同フォルダの `s21_*.py`。仮定・未確認の全文は [results/S21.json](results/S21.json)

1. 手順1: 初度登録と入庫日から経過年数を月単位で計算する
2. 手順2: 加点表で 経過年数・走行距離・作業部位の最大錆グレード・未確認の有無・防錆施工歴・前回の固着記録 を加点する
3. 手順3: 合計点を帯（低/中/高）に分け、加点の内訳を出す
4. 手順4: 未確認項目を上限加算の大きい順に並べて確認の順番にする（サブフレームは U4 により範囲外）
5. 手順5: 帯で確認の緊急度（低=作業中 / 中=分解前 / 高=見積もり確定前）と上限に含める範囲を決める。低=未確認の締結部だけ、中=未確認項目だけ、高=未確認項目＋重の締結部の折れ込み・ねじ山（U3）。帯ごとの high を出し、今回の帯の値を採用する
6. 手順6: low = typical = 1.7 人時。high = 1.7 + 今回の帯の範囲の追加工程の high 値。観察済みの中のボルト・左ブーツ硬化は S21 の範囲外。スコアは人時に変換しない
7. 手順7: 経過時間は U5 により、FX-SEIZE を high に含めるので high にだけ浸透待ち 0.25 を足す。サブフレームは U4 により unknowns に記録する

- 3重チェック: 算術: 不合格 U3 の割り当て違い（high）: 右ブラケット（F-R-BRK-1/2、錆「中」）の FX-SEIZE high 0.3 x 2本 = 0.6 人時が high に入っていない。U3 の表は「中」行で FX-SEIZE high を指定し、S21 は U3 が適用される案として名指しされている。結果の note は…／U3 の割り当て違い（low / typical）: 締結部の U3 行を S21 に適用すると、low と typical に表の値が入るが、結果は『工数は変えない（1.7固定）』として U3 の値を足していない。内訳は、重ブラケット2本の FX-SEIZE low 0.05 x 2 = 0.1（low）、中ブラケ…、仕様: 不合格 U3 違反（締結部の割り当てが欠落）。(a) 重の締結部（F-L-BRK-1/2）の low・typical（FX-SEIZE low 0.05 / typical 0.15 を各2本）と、中の締結部（F-R-BRK-1/2、観察済み）の typical（FX-SEIZE typical 0.15 x 2）・high…／U3・U2 違反（重の折れ込み・ねじ山の high が帯で切り替わる）。FX-BROKEN と FX-THREAD を含めるかどうかが優先度スコアの帯（高 8点以上のみ）で決まる。U3 の表では、重の締結部の high は帯や点数に関係なく FX-SEIZE high + FX-BROKEN high + FX-TH…／地域・年式・走行距離で工数を増やしている（ガードレール5・rule 5 の趣旨違反）。経過年数（+2）と走行距離（+1）は点数にだけ効くが、その点数が帯を決め、帯が重の折れ込み分（4.6 人時）の有無を決める。年式・走行距離を除くと 7 点（中）になり high は 3.9 に下がる。加算は観察した状態と追加工程に対…／U1 違反（範囲外の要因を人時に入れている）。右スライドピンブーツの硬化（AG-BOOT、high 0.20）を high に加算している。ブーツ硬化は AG03 で、S21 の §3 の主な要因（HK01, AG01, AG07）にも §4 の仕組み（経過年数・走行距離・錆の観察・防錆施工歴・前回の固着）にも入らな…、入力: 合格（初回不合格 → Sonnet が修正 → 再検証）
- 裁定済み: docs の S21「スコアは確認の順番と上限の幅を決めるためだけに使う」に従い、帯で上限の幅を切り替える個別指示を出した。typical は 1.7 に据え置き。

### S22 付随作業・連鎖交換の候補リスト

スクリプト: 同フォルダの `s22_*.py`。仮定・未確認の全文は [results/S22.json](results/S22.json)

1. 手順1: 基準 1.7 人時を出発点にする
2. 手順2: 付随部品カタログから頻度 0.15 以上の候補だけを表示する
3. 手順3: 候補ごとに工程人時と期待人時（頻度 x 単位数 x 人時）を参考値として計算する
4. 手順4: 現車の観察と突き合わせる。観察で問題あり（左ブーツ）は必要が分かっているので本体の low/typical/high に入れる。未確認（右ブーツ）は high にだけ加える
5. 手順4b: 候補カタログは作業 J2（前ブレーキ）用の1種類。対象作業が変わる場合は、その作業用のカタログに差し替える（この実装では切り替え未対応）
6. 手順5: ブラケットボルト交換は catalog で工数 0（固着対応に含む）なので人時を足さず、部品代として other_outputs に別記。パッドセンサー・ブレーキホース（しきい値未満）も other_outputs に参考として出し、high に入れない（U8）
7. 手順5b: 人時 = 1.7 + 左ブーツ。high にだけ未確認の右ブーツを加算。期待人時は typical に混ぜない
8. 手順6: 地域・年式・走行距離からは加算しない。他案の要因は加えない
9. 手順7: 待機・2人作業は扱わないので経過時間は null

- 3重チェック: 算術: 合格、入力: 合格、仕様: 不合格 U1・U2 違反（範囲内の未確認項目が high に入っていない）。docs §4.4 S22 の仕組みと AG03（system-ideas-30.md 2章）は、ブッシュ・クリップを候補の対象に含めている。scenario.json の mechanic_provisional_add_ops には AG-CLI…（初回不合格 → Sonnet が修正 → 再検証）
- 裁定済み: 樹脂クリップは個数の観察値がなく、付随部品の候補一覧（catalog）にもないため、unknowns に残す判断を認めた。

### S23 写真記録とAIによる一次分類

スクリプト: 同フォルダの `s23_*.py`。仮定・未確認の全文は [results/S23.json](results/S23.json)

1. 手順1: 基準 1.7 人時(重複控除後)から始める
2. 手順2: 部位ごとに AI候補・信頼度・整備士確定値を取り、写真なしは未確認として扱う
3. 手順3: AI候補と確定値の一致率と不一致の部位を出して記録する(工数には入れない)
4. 手順4: 確定値だけで、J1/J2 に関係する部位のグレード→追加工程(仮定の対応表×整備士暫定値)から追加人時を出す
5. 手順5: 関係部位と J2 の未確認の締結部(スライドボルト4本)は typical に入れず high に固着対応(FX-SEIZE high)だけを入れる(U3)。subframe は範囲外(U4)で入れない
6. 手順6: AI候補のまま計算した場合の人時を参考に出し、確定値との差を示す
7. 手順7: 固着対応があれば浸透待ち0.25、ハブ錆落としがあれば防錆乾燥0.3を経過時間にだけ足す(人時に入れない)。AIの分類そのものは計算せず scenario の ai_grade を入力として読む。グレード3は AG04 として顧客連絡を促す

- 3重チェック: 算術: 合格、仕様: 不合格 U2・U3 違反（high が範囲の上限になっていない）。scenario.json の condition.fasteners で、ブレーキ部は F-L-BRK-1/2 が「重（頭部腐食）」、F-R-BRK-1/2 が「中」と観察済みだが、スクリプトは部位単位のグレード3を area 対応表（brake g3: S…、入力: 合格（初回不合格 → Sonnet が修正 → 再検証）
- 裁定済み: S23 の仕組みは写真から部位ごとの腐食グレードを分類することなので、締結部単位の U3 ではなく部位グレードで数える方式を認めた。

### S24 下回り撮影ガイド

スクリプト: 同フォルダの `s24_*.py`。仮定・未確認の全文は [results/S24.json](results/S24.json)

1. 手順1: 基準 1.7 人時を出発点にする
2. 手順2: 必要撮影と撮影済みを照合し、撮影率と未撮影部位を出す
3. 手順3: 撮影位置ごとの案内（位置・枚数・目的）を出し、未撮影は「未確認として残す」
4. 手順4: 撮影で確認できる対象と、撮影しても確認できない対象を分けて記録する
5. 手順5: 防錆コート上からの見えにくさを確認項目に出す（工数は足さない）
6. 手順6: low・typical は基準 1.7。high は撮影漏れの未確認（右スライドピンブーツ）に AG-BOOT high を足す（U2 の例外）。サブフレーム前部は U4 により high に入れない

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格

### S25 音声入力による作業メモ

スクリプト: 同フォルダの `s25_*.py`。仮定・未確認の全文は [results/S25.json](results/S25.json)

1. 手順1: 基準 1.7 人時を出発点にする
2. 手順2: 文字起こしを文・節に分け、「左前」「右前」の側を文をまたいで持ち回る
3. 手順3: キーワード規則で節を原因タグ（固着対応・ローター固着・ブーツ交換・ボルト折れ）と部位に振り分ける。錆・腐食は HK01 の状態タグ（人時なし）
4. 手順4: 「普通に外れた」は問題を観察していない側、「見てない」は未確認として分け、未確認は0にしない
5. 手順5: メモで確定した分は low/typical/high すべてに加える。メモにない候補のうち、観察済みの左ブーツは typical・high、未確認の左右スライドボルト4本の FX-SEIZE high は high のみに加える（U3 の未確認の行）。折れ込み（FX-BROKEN）は仮置きしない。サブフレームは U4 により作業範囲外
6. 手順6: 再見積もり人時 = 1.7 + Σ（単位数 x 単位あたり人時）。地域・年式・走行距離からは加算しない
7. 手順7（U5）: 経過時間 = 人時 + 浸透待ち 0.25（固着対応を含む low/typical/high それぞれ。複数本でも1回）。1人・直列作業の前提で、workers_available による短縮は扱わない
8. 手順8: 振り分け結果、スライドボルト等の未確認、サブフレーム（U4: 範囲外、AG04 の注記）を unknowns に出す

- 3重チェック: 入力: 合格、算術: 不合格 U3 の割り当て違い（左ブラケット折れ込み）: scenario の左キャリパーブラケットボルト F-L-BRK-1/2 は錆「重（頭部腐食）」。SPEC U3 の「重」行は high に FX-SEIZE high ＋ FX-BROKEN high ＋ FX-THREAD high を入れると定めている。S25 の…、仕様: 不合格 U3 違反（締結部・錆「重」の行）: scenario の左キャリパーブラケットボルト2本は rust「重（頭部腐食）」で、fastener_risk_rule では「折れ込みの可能性」。SPEC U3 の表では「重」の high は FX-SEIZE high に加えて FX-BROKEN high と FX-TH…／仕組みの範囲外の人時: docs §4 の S25 の仕組みは「文字起こしを S10 の原因タグとメモに振り分ける」までで、人時は S11/S12 の実績表・暫定値の役割と書かれている。それでも result.labor_hours を、音声メモに無い scenario の観察値（右ブラケット2本、右ローター未確認、…（初回不合格 → Sonnet が修正 → 再検証）
- 裁定済み: 分解後の音声メモで左ブラケットボルト2本は外れており、折れなかったことが分かっている。このため折れ込みを high に入れない個別指示に従った（U3 は分解前の見積もりの規則）。

### S26 電子車検証の取込による車両情報の自動入力

スクリプト: 同フォルダの `s26_*.py`。仮定・未確認の全文は [results/S26.json](results/S26.json)

1. 手順1: e_shakensho_sample から 車名・型式・原動機の型式・初度登録年月・車両重量 の5項目だけを取り込む（使用者は取り込まない）
2. 手順2: 和暦の初度登録年月を西暦に変換する（平成の元年=1989、西暦 = 1989 + 年 - 1）
3. 手順3: 取込値を vehicle の値と照合し、不一致があれば unknowns に記録する
4. 手順4: intake.date と初度登録年月から経過年数を月単位で計算する
5. 手順5: S04 へ渡す確認強度を、年数または走行距離がしきい値以上かで決める
6. 手順6: S21 へ渡す加点を、年数・走行距離の区分から決める（年数の中・走行距離の中ではそれぞれ上位の区分だけを採り、年数と走行距離は別要素として合算する。錆・未確認・防錆歴・前回固着は含まない）
7. 手順7: 寒冷地仕様・4WD・後付け装備は車検証で確定できないので、現車確認の項目として記録する
8. 手順8: 工数は変えない。low = typical = high = 基準 1.7 人時

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格

### S27 暖房費等を配賦する時間単価計算機

スクリプト: 同フォルダの `s27_*.py`。仮定・未確認の全文は [results/S27.json](results/S27.json)

1. 手順1: 重複控除後の基準 1.7 人時を据え置く（金額の案なので工数は変えない）
2. 手順2: 人件費・家賃・暖房費・設備費・目標利益を合計して年間総コストを出す
3. 手順3: 年間総コスト / 年間請求人時 = 年間配賦の時間単価
4. 手順4: 暖房費を冬季分と残りに分け、冬季分だけ冬季請求人時で配賦して冬季/非冬季の単価を出す
5. 手順5: 冬季・非冬季の加重平均が年間単価に一致するか検算する
6. 手順6: 参考として 1.7 人時 x 各単価の工賃を出す（暖房費は人時に足さない）

- 3重チェック: 算術: 合格、仕様: 合格、入力: 合格

### S28 錆対応の材料・消耗品の別建て

スクリプト: 同フォルダの `s28_*.py`。仮定・未確認の全文は [results/S28.json](results/S28.json)

1. 手順1: 工数は重複控除後の基準1.7人時のまま据え置く（SPEC U9: low=typical=high=1.7）。
2. 手順2: J2の締結部を fastener_risk_rule で 重/中/未確認 に区分する（ホイールナットは対象外）。
3. 手順3: 固着対応（浸透剤・加熱ガス）の本数を SPEC U3 に合わせ low=重 / typical=重+中 / high=重+中+未確認 とする。
4. 手順4: 折れ込みは重の high のみ。交換ボルトは low・typical 0、high=重の本数。
5. 手順5: ねじ山修正部材も同じ割り当て（low・typical 0、high=重の本数）。
6. 手順6: ハブ錆グレード2以上なら防錆剤を両側（2側）に使う。
7. 手順7: ローター・ハブ固着、サブフレーム（U4 作業範囲外）、ブーツ（AG03/S22）は材料に含めず unknowns に記録する。
8. 手順8: 材料単価（按分または1個単価）で金額化し、合計を other_outputs に別記する。人時に足さない。

- 3重チェック: 算術: 合格、仕様: 不合格 待機を扱う案なのに elapsed_hours が null（SPEC は null を待機を扱わない案に限る）／表示しきい値以上の付随部品（ブラケットボルト）を材料費から外す根拠が SPEC にない、入力: 合格（初回不合格 → Sonnet が修正 → 再検証）
- 再検証後に修正: 経過時間を S12 と同じく人時＋待機（2.25 時間）で出し、作業人時を入れないので過小になりうると note に書いた。付随部品のボルトは S22 の扱いに合わせて材料費の本体に入れず、単価を候補として別に示した。待機時間は scenario.json から読むようにした。修正後の再検証はしていない。

### S29 顧客向けの説明シート

スクリプト: 同フォルダの `s29_*.py`。仮定・未確認の全文は [results/S29.json](results/S29.json)

1. 手順1: 重複控除後の基準 1.7 人時を A 行に置く
2. 手順2: 入庫時の観察から雪下ろし・氷塊除去（問題ありのホイールハウス数）の確定行を作る
3. 手順3: 写真つきで錆を観察した重/中のブラケットボルトを「可能性」行にする（SPEC U3: 重は low=固着対応、high=固着対応＋折れ込み抜き取り＋ねじ山修正。中は low 0、typical・high は固着対応）
4. 手順4: 観察も写真もない締結部・ローター・右ブーツを「未確認」行にし、high にだけ入れる。サブフレームは作業範囲外（U4）で unknowns に記録
5. 手順5: 左ブーツ硬化（観察・写真あり）を確定行に、付随部品の候補は頻度がしきい値以上のものを別記する
6. 手順6: 各行に写真の有無と観察/未確認の根拠を付け、合計の人時範囲と人時（下回り洗浄を含む）と経過時間（人時＋待機: 融解0.5・浸透0.25・防錆乾燥0.3 を含む範囲に足す。待機は人時に入れない）を出す
7. 手順7: 追加分が連絡基準を超える範囲に、作業前連絡の注記を付ける

- 3重チェック: 算術: 合格、仕様: 不合格 U8 違反: 表示しきい値 0.15 未満の付随部品候補（パッド摩耗センサー freq 0.10、ブレーキホース freq 0.05）を other_outputs に参考として出していない。other_outputs の付随部品候補は freq 0.20 のキャリパーブラケットボルトのみ。labor_hours に…、入力: 合格（初回不合格 → Sonnet が修正 → 再検証）
- 要確認: 表示しきい値未満の付随部品（パッドセンサー、ブレーキホース）が other_outputs に出ていない。人時には影響しない。

### S30 3方式の根拠を並べる比較画面

スクリプト: 同フォルダの `s30_*.py`。仮定・未確認の全文は [results/S30.json](results/S30.json)

1. 手順1: scenario.json を読み、基準 1.7 人時を出発点にする。
2. 手順2: 案A = 1.7 + 締結部の補正（U3 の typical / high）。未確認の締結部は high のみ。
3. 手順3: 案B = S08 と同じ規則。J1+J2 の類似実績（R08〜R11 の4件、同一車両を含む）の actual の中央値・最小・最大。
4. 手順4: 案C = 重複控除後の工程 1.7 + 前処理 + 締結部（U3）+ ハブ錆落とし + ブーツ。待機（U5）は経過時間のみ。
5. 手順5: 3方式を平均しない。提示範囲 = 3方式の low の最小〜high の最大、typical は案A。
6. 手順6: 各列に根拠・不足情報・錆と固着の反映状態を付けて並べる。担当者が選び理由を残す。

- 3重チェック: 算術: 合格、入力: 合格、仕様: 合格（初回不合格 → Sonnet が修正 → 再検証）

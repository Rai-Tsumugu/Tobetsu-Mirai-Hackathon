# ④ 共通実装契約

Simulator専用。数値・日付・匿名IDは架空。設計原文は変更しない。
全てのAPI変数名はsnake_case。帯はlow/typical/high。金額・数量は帯ごとに保持。
Python package: src.auto_repair_quote。実装P01〜P30はp01.py〜p30.py。
共有common.pyのBANDS, number, range_value, money_range, make_lineを利用。
見積行: line_id, kind(labor/parts/materials/adjustment/discount), category,
description, quantity_range, unit, unit_price_range, amount, source_system,
source_ref, snapshot, reason, status。amountの別名amount_rangeは禁止。
見積: quote_id, quote_version, lines, subtotal, tax, total, reasons, conditions,
selected_band, confirmed_by, override_reason, status, metadata.input_snapshot。
人時のみ課金しelapsed_hoursは表示専用。未確認・負数・非有限は停止。
販売価格には掛率を重ねない。原本入力・旧版をdeepcopyで保存。
税設定は架空Simulatorの明示設定で、本番税率を意味しない。
通信と変更イベントは見積版を参照しappend-only保存。
個人情報は匿名customer_ref/vehicle_ref/operatorのみ。
実装担当と別のLuna確認担当が各P案を要件・実行の二段階で検査。

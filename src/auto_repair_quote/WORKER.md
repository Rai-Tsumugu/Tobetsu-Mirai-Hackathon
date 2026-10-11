# Luna 実装・確認担当の共通指示

作業場所は本ファイルのフォルダ。共有コードベースで他者の変更を戻さない。
実装担当所有はpXX.pyとtest_pXX.py（このフォルダ内）だけ。rootファイル禁止。
Git操作禁止。仕様はdesign_snapshot.mdの担当ID、共通名はCONTRACT.md。
Python標準ライブラリのみで機能を実装、金額はDecimalで計算、snake_case。
原本・旧版・入力を変えずdeepcopyする。未知値をゼロにしない。
common.pyのBANDS/number/range_value/money_rangeを利用する。
testは unittest、package importは .pXX、実行はrepo rootから
python3 -m unittest src.auto_repair_quote.test_pXX -v
レビュー担当は読み取り専用で、要件照合＋実行と独立境界例の二重チェックを行う。
レビューは正確なコード根拠と再現例を報告。設計にない要件を捏造しない。
store.py QuoteStoreはSQLite永続化共有契約。save_quote/get_quote/list_quotes、
append_communication/list_communications、append_change_event/list_change_events、
save_draft/get_draft/list_drafts、save_price/list_prices、transaction/closeを使用可。
各完成時API関数名とテスト結果を主担当へ報告して終了する。

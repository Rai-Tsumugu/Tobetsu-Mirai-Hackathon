# 統合版 UI 独立確認

担当: gpt-6-luna / integration_ui_check

Chrome、検証専用の一時SQLiteデータベースで確認。
- 材料登録と checked_at 保存後の「確認済み」表示を確認。
- 数量2・単価105円の見積が小計210円で保存される。
- 保存済み見積IDで同じ行・金額を再表示できる。
- 画面表示は textContent / createTextNode を使用。
- app + integrated テスト9件通過。

検出した checked_at の入力・保存不一致は修正後に再確認済み。
この確認は統合版の確認であり、各30案の二重チェック完了を意味しない。

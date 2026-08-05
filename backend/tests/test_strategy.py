from app.strategy import banned_violations, load_strategy


def test_load_strategy_and_gate(tmp_path):
    p = tmp_path / "strategy.yaml"
    p.write_text(
        "voice: v\naudiences: [a]\nbanned_words: [รับประกันสอบติด]\nplatform_notes: {x: n}\n",
        encoding="utf-8",
    )
    s = load_strategy(str(p))
    assert s.voice == "v"
    assert banned_violations(s, ["เรารับประกันสอบติดแน่นอน"]) == ["รับประกันสอบติด"]
    assert banned_violations(s, ["ข้อความปกติ"]) == []

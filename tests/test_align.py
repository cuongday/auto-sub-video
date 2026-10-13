from autosub.asr.align import align_tokens

def test_equal_counts():
    ws = align_tokens("你好，世界。", [[0, 200], [200, 400], [500, 700], [700, 900]])
    assert [w.text for w in ws] == ["你", "好，", "世", "界。"]
    assert ws[2].start == 0.5 and ws[3].end == 0.9

def test_english_word_is_one_token():
    ws = align_tokens("我用iPhone拍", [[0, 100], [100, 200], [200, 500], [500, 600]])
    assert [w.text for w in ws] == ["我", "用", "iPhone", "拍"]

def test_mismatch_is_monotonic():
    ws = align_tokens("一二三四五六", [[0, 100], [100, 200], [200, 300]])
    assert len(ws) == 6
    starts = [w.start for w in ws]
    assert starts == sorted(starts)

def test_empty():
    assert align_tokens("", []) == []
    assert align_tokens("你好", []) == []

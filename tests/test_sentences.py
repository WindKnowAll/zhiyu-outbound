from zhiyu.pipeline.sentences import SentenceSplitter


def test_strong_punctuation_splits_immediately():
    splitter = SentenceSplitter()
    assert splitter.push("书已经到了。") == ["书已经到了。"]
    assert splitter.push("今天方便吗？") == ["今天方便吗？"]


def test_token_can_split_across_calls():
    splitter = SentenceSplitter()
    assert splitter.push("书已经") == []
    assert splitter.push("到了。今天") == ["书已经到了。"]
    assert splitter.flush() == ["今天"]


def test_short_comma_is_kept_until_a_real_break():
    splitter = SentenceSplitter(soft_min=8)
    assert splitter.push("嗯，好") == []
    assert splitter.flush() == ["嗯，好"]


def test_long_clause_splits_on_comma():
    splitter = SentenceSplitter(soft_min=8)
    pieces = splitter.push("您预约的图书已经到馆，今天下午可以来取。")
    assert pieces[0].endswith("，")
    assert "可以来取。" in pieces[-1]


def test_hard_max_flushes_a_run_on():
    splitter = SentenceSplitter(hard_max=4)
    assert splitter.push("一二三四五") == ["一二三四"]
    assert splitter.flush() == ["五"]

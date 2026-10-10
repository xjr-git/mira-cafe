"""Unit self-test for llm.py incremental say-extraction + sentence flush."""
import sys
sys.path.insert(0, r"D:\2026-10-10-09-41-11\mira-cafe\backend")
from app.providers.llm import _extract_say_partial, _unescape, _flush_sentences

# 1) incomplete JSON with an ESCAPED quote inside the say value
buf = '{"say": "今天雨真大。你要热咖啡吗？还有 \\" 特别的事想告诉你'
done, raw = _extract_say_partial(buf)
assert not done, f"should be incomplete, got done={done} raw={raw!r}"
t = _unescape(raw)
assert t == '今天雨真大。你要热咖啡吗？还有 " 特别的事想告诉你', repr(t)
sents, rest = _flush_sentences(t, final=False)
assert sents == ["今天雨真大。", "你要热咖啡吗？"], sents
assert rest == '还有 " 特别的事想告诉你', repr(rest)

# 2) complete JSON
buf2 = '{"say": "第一句。第二句！", "directives": []}'
done2, raw2 = _extract_say_partial(buf2)
assert done2 and _unescape(raw2) == "第一句。第二句！"

# 3) bare ellipsis fragment dropped, short fragment held and merged
s3, r3 = _flush_sentences("……雨夜。雨停了", final=False)
assert s3 == ["雨夜。"], s3            # "……" dropped, "雨夜。" emitted
assert r3 == "雨停了", repr(r3)

# 4) incomplete trailing escape -> wait for more chunks
buf4 = '{"say": "下雨了。\\'
d4, raw4 = _extract_say_partial(buf4)
assert not d4, (d4, raw4)

# 5) say not first key still works (search by key name)
buf5 = '{"directives": [], "say": "晚点开始。"}'
d5, raw5 = _extract_say_partial(buf5)
assert d5 and _unescape(raw5) == "晚点开始。", (d5, raw5)

# 6) final flush emits remainder once
s6, r6 = _flush_sentences("结尾这句没有标点", final=True)
assert s6 == ["结尾这句没有标点"] and r6 == ""

print("UNIT_OK")

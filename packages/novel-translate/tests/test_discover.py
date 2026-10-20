import random

from novel_translate.discover import candidates

# Ordinary characters for filler text, and words any chapter is full of.
FILLER = "山水风云天地日月花草木石金银铜铁春夏秋冬东西南北红黄蓝白黑青紫长短高低远近快慢冷热明暗新旧大小多少"
COMMON = ["他们", "一个", "这个", "我们", "自己", "什么"]


def chapters(planted: str, times: int, n: int = 20, seed: int = 7) -> list[str]:
    """`n` chapters of random filler and common words, with `planted` occurring `times` in all."""
    rng = random.Random(seed)
    texts = []
    for i in range(n):
        parts = []
        for _ in range(300):
            parts.append("".join(rng.choice(FILLER) for _ in range(rng.randint(1, 4))))
            if rng.random() < 0.3:
                parts.append(rng.choice(COMMON))
            if rng.random() < 0.2:
                parts.append("，")
        for _ in range(times // n):
            parts.insert(rng.randrange(len(parts)), planted)
        texts.append("".join(parts) + "。")
    return texts


def test_a_planted_name_is_found_and_common_words_are_not():
    found = [c.zh for c in candidates(chapters("玄天剑宗", 20), known=set())]
    assert "玄天剑宗" in found
    assert not set(found) & set(COMMON)
    assert not {"玄天剑", "天剑宗", "玄天", "剑宗"} & set(found)  # parts of the name it always comes with


def test_known_names_are_not_proposed_again():
    found = [c.zh for c in candidates(chapters("玄天剑宗", 20), known={"玄天剑宗"})]
    assert "玄天剑宗" not in found


def test_counts_are_reported_and_rare_strings_left_out():
    found = {c.zh: c.count for c in candidates(chapters("玄天剑宗", 20) + ["青云门。" * 9], known=set())}
    assert found["玄天剑宗"] == 20
    assert "青云门" not in found  # 9 times is too rare


def test_no_chapters_means_no_candidates():
    assert candidates([], known=set()) == []

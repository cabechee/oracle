"""agent.memory 3요소 검색 단위 테스트.

순수 로직(recency 감쇠·importance 매핑·min-max)과 search()의 저널+record 합집합 랭킹을
Mongo/Nest 없이 monkeypatch로 검증.
"""

from datetime import datetime, timedelta

import pytest

from agent import memory


# ── 순수 헬퍼 ────────────────────────────────────────────────

def test_recency_monotonic_decay():
    now = datetime.now()
    r_now = memory._recency(now, now, 30.0)
    r_old = memory._recency(now - timedelta(days=30), now, 30.0)
    r_older = memory._recency(now - timedelta(days=90), now, 30.0)
    assert r_now == pytest.approx(1.0, abs=1e-6)
    assert r_now > r_old > r_older >= 0.0
    # 비-datetime은 0
    assert memory._recency("nope", now, 30.0) == 0.0


def test_record_importance_ordering():
    imp = memory._record_importance
    assert imp({"reaction": "useful"}) > imp({"reaction": "interesting"})
    assert imp({"reaction": "interesting"}) > imp({})           # none=baseline
    assert imp({}) > imp({"reaction": "skip"})                  # baseline > skip


def test_journal_importance_grows_and_caps():
    base = memory._journal_importance({})
    more = memory._journal_importance({"reaction_signal": {"useful": 2, "interesting": 1}})
    assert more > base
    huge = memory._journal_importance({"reaction_signal": {"useful": 100}})
    assert huge <= 1.0


def test_minmax():
    assert memory._minmax([1.0, 3.0, 5.0]) == [0.0, 0.5, 1.0]
    # 전부 동일 → 중립 0.5
    assert memory._minmax([2.0, 2.0]) == [0.5, 0.5]
    assert memory._minmax([]) == []


# ── search() 합집합 랭킹 ──────────────────────────────────────

class _FakeCol:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *_args, **_kw):
        return list(self._docs)


@pytest.fixture
def patched(monkeypatch):
    now = datetime.now()
    records = [
        {"_id": "A", "embedding": [1.0, 0.0], "ts": now, "reaction": "useful"},
        {"_id": "B", "embedding": [0.0, 1.0], "ts": now - timedelta(days=40), "reaction": "skip"},
    ]
    journals = [
        {"_id": "day-J", "kind": "day", "embedding": [0.7, 0.7],
         "period_end": now - timedelta(days=1), "period_start": now - timedelta(days=1),
         "date": "2026-06-06", "reaction_signal": {"useful": 1}},
    ]
    monkeypatch.setattr(memory.embedding_mod, "embed_text", lambda q: {"embedding": [1.0, 0.0]})
    monkeypatch.setattr(memory.db, "records", lambda: _FakeCol(records))
    monkeypatch.setattr(memory.db, "journals", lambda: _FakeCol(journals))
    return now


def test_search_unions_and_ranks(patched):
    res = memory.search("아무 질문", top_k=10)
    assert res is not None
    ids = [r["id"] for r in res]
    kinds = {r["kind"] for r in res}
    # 저널 + record 둘 다 후보에 들어옴
    assert kinds == {"record", "journal"}
    # A: 유사도1 + 최신 + useful → 최상위. B: 유사도0 + 오래됨 + skip → 최하위.
    assert ids[0] == "A"
    assert ids[-1] == "B"
    # 저널은 A와 B 사이 어딘가 (유사도 ~0.7)
    assert "day-J" in ids
    # 스코어 내림차순
    scores = [r["score"] for r in res]
    assert scores == sorted(scores, reverse=True)


def test_search_none_when_no_embedding(monkeypatch):
    monkeypatch.setattr(memory.embedding_mod, "embed_text", lambda q: None)
    assert memory.search("q") is None

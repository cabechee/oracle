#!/usr/bin/env python3
"""위치 판정 점검 — 동선/방문 실데이터로 임계값 튜닝·갭 진단.

거점평균+히스테리시스 재설계(2026-06-28) 이후, 실제 돌아다닌 날의 데이터로
  - 드리프트 쪼개짐(인접 방문이 따로 잡힘)
  - 도보/이동 분류(moving 비율)
  - 동선 갭(정착·Doze로 track이 비는 구간)
이 어떤지 본다. LEAVE_RADIUS·MOVE_MPS 등을 조정하기 전에 근거를 잡는 용도.

실행(chocolat 또는 Mongo 접근 가능한 곳):
  python scripts/loc_check.py                # 오늘
  python scripts/loc_check.py 2026-06-29     # 특정일
  python scripts/loc_check.py 2026-06-28 2026-06-30   # 범위(시작~끝)
"""

import math
import os
import sys
from collections import Counter
from datetime import date, datetime, time as dtime, timedelta

from pymongo import MongoClient

# 수집기 LocationCollector.kt 의 현재 임계값(참고용 — 여기 숫자와 비교해 조정)
LEAVE_RADIUS = 250.0   # 거점 이탈 반경(m)
STAY_RADIUS = 150.0    # 흡수 반경(m)
MOVE_MPS = 2.5         # 도보/이동 경계(m/s ≈ 9km/h)


def hav(a, b):
    R = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def report(db, d: date):
    lo = datetime.combine(d, dtime.min)
    hi = datetime.combine(d, dtime.max)
    print(f"\n{'=' * 52}\n {d}  (LEAVE={LEAVE_RADIUS:.0f}m STAY={STAY_RADIUS:.0f}m MOVE={MOVE_MPS}m/s)\n{'=' * 52}")

    # ── 동선(tracks) ──────────────────────────────────────────────
    tr = list(db.tracks.find({"ts": {"$gte": lo, "$lte": hi}}).sort("ts", 1))
    mv = sum(1 for t in tr if t.get("moving"))
    still = sum(1 for t in tr if t.get("moving") is False)
    print(f"tracks: {len(tr)}pts  moving={mv} still={still} unk={len(tr) - mv - still}")
    if tr:
        # 시간대별 + 최대 갭(정착/Doze 구멍 탐지)
        hh = Counter(t["ts"].strftime("%Hh") for t in tr)
        spark = " ".join(f"{h}:{hh.get(h, 0)}" for h in (f"{i:02d}h" for i in range(24)) if hh.get(h))
        print(f"  시간대: {spark}")
        max_gap, gap_at = timedelta(0), None
        for a, b in zip(tr, tr[1:]):
            g = b["ts"] - a["ts"]
            if g > max_gap:
                max_gap, gap_at = g, a["ts"]
        mins = max_gap.total_seconds() / 60
        flag = "  ⚠️ 큰 동선 갭(정착/Doze 의심)" if mins > 15 else ""
        print(f"  최대 갭: {mins:.0f}분 @ {gap_at.strftime('%H:%M') if gap_at else '-'}{flag}")

    # ── 방문(visits) — 드리프트 쪼개짐 ────────────────────────────
    vs = list(db.visits.find({"start": {"$gte": lo, "$lte": hi}}).sort("start", 1))
    print(f"visits: {len(vs)}건")
    prev = None
    splits = 0
    for v in vs:
        c = (v.get("lat"), v.get("lng")) if v.get("lat") is not None else None
        st = v.get("start"); en = v.get("end")
        sts = st.strftime("%H:%M") if isinstance(st, datetime) else "?"
        ens = en.strftime("%H:%M") if isinstance(en, datetime) else "?"
        name = v.get("place") or v.get("area") or v.get("label") or "어떤 곳"
        tag = ""
        if c and prev:
            dd = hav(prev, c)
            if dd < LEAVE_RADIUS:
                tag = f"  ⚠️ 앞 방문과 {dd:.0f}m(<{LEAVE_RADIUS:.0f}) — 드리프트 쪼개짐?"
                splits += 1
            else:
                tag = f"  ({dd:.0f}m from prev)"
        coord = f"({c[0]:.4f},{c[1]:.4f})" if c else "(no-coord)"
        print(f"  {sts}-{ens} {v.get('minutes', '?')}분  {name}  {coord}{tag}")
        if c:
            prev = c
    if vs:
        print(f"  → 드리프트 쪼개짐 의심: {splits}건 (0이면 거점평균 판정 정상)")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(args) >= 2:
        d0, d1 = date.fromisoformat(args[0]), date.fromisoformat(args[1])
    elif len(args) == 1:
        d0 = d1 = date.fromisoformat(args[0])
    else:
        d0 = d1 = date.today()

    db = MongoClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"))[
        os.getenv("MONGO_DB", "oracle")]
    d = d0
    while d <= d1:
        report(db, d)
        d += timedelta(days=1)


if __name__ == "__main__":
    main()

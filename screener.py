# -*- coding: utf-8 -*-
"""
ai3 screener — 텐베거 100점 스코어링
================================================================
철학: "저평가 + 이익 체력 + 작은 시총"은 텐베거의 필요조건이지만,
거래량(수급)이 붙기 전까지는 만년 저평가로 방치될 수 있다.
그래서 '시장이 발견하기 시작했다'는 거래량 시그널을 점수에 직접 넣는다.

배점 (총 100점)
  가치        30  : 저PER(15) + 섹터대비 할인(8) + 저PBR(7)
  수익성/체력  30  : ROE(12) + 영업이익률(10) + 저부채(8)
  수급/거래량  25  : 거래량 배수(15) + 거래대금 절대수준(10)
  사이즈/구조  15  : 시총 구간(10) + 52주 고점대비 낙폭(5)

필수 관문 (하나라도 탈락 시 제외)
  - 흑자: 영업이익 > 0, 순이익 > 0, PER > 0
  - 유동성: 20일 평균 거래대금 >= 3억
  - 재무: 부채비율 < 200%
  - 데이터: 거래량 배수 계산 가능

사용: python screener.py  →  data/screened.csv
"""
import os

import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ----------------------------- 필수 관문 -----------------------------
MIN_AMT_AVG20 = 3e8          # 20일 평균 거래대금 3억
MAX_DEBT_PCT = 200           # 부채비율 200% 미만
MIN_MCAP = 500e8
MAX_MCAP = 3e12


def _scale(x: pd.Series, lo: float, hi: float, max_pts: float) -> pd.Series:
    """lo에서 0점, hi에서 만점이 되는 선형 점수 (역방향은 lo>hi로)."""
    return ((x - lo) / (hi - lo)).clip(0, 1) * max_pts


def score(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()

    # ---------- 필수 관문 ----------
    # 금융·투자회사 제외: 트레일링 PER이 평가이익으로 왜곡되는 유형
    fin_name = d["name"].str.contains(
        "인베스트|기술투자|벤처|창업투자|캐피탈|증권|보험|은행|금융|저축", na=False
    )
    fin_sector = d["sectorName"].fillna("").str.contains("금융|증권|보험|은행")

    gate = (
        (d["per"] > 0)
        & (d["operatingProfit"] > 0)
        & (d["netIncome"] > 0)
        & (d["amt_avg20"] >= MIN_AMT_AVG20)
        & (d["debt_pct"] < MAX_DEBT_PCT)
        & d["vol_mult"].notna()
        & (d["marketCap"].between(MIN_MCAP, MAX_MCAP))
        & ~fin_name
        & ~fin_sector
    )
    d = d[gate].copy()
    if d.empty:
        return d

    # ---------- 가치 30 ----------
    d["s_per"] = _scale(d["per"], 15, 4, 15)                  # PER 15→0점, 4 이하→만점
    sector_disc = (1 - d["per"] / d["sectorPer"]).where(d["sectorPer"] > 0)
    d["s_sector"] = _scale(sector_disc.fillna(0), 0, 0.6, 8)  # 섹터 대비 60% 할인이면 만점
    d["s_pbr"] = _scale(d["pbr"], 3, 0.5, 7)

    # ---------- 수익성/체력 30 ----------
    d["s_roe"] = _scale(d["roe"], 5, 25, 12)
    d["s_opm"] = _scale(d["op_margin"], 3, 20, 10)
    d["s_debt"] = _scale(d["debt_pct"], 200, 30, 8)

    # ---------- 수급/거래량 25 ----------
    # vol_mult_max5: 최근 5일 내 최대 거래량 배수. 1.0x→0점, 4.0x 이상→만점.
    # "조용히 싸기만 한" 종목은 여기서 점수를 못 받는다 → 마냥 기다리는 종목 배제.
    d["s_vol"] = _scale(d["vol_mult_max5"], 1.0, 4.0, 15)
    d["s_amt"] = _scale(np.log10(d["amt_avg20"]), np.log10(3e8), np.log10(3e10), 10)

    # ---------- 사이즈/구조 15 ----------
    # 텐베거 통계상 시총 500억~3000억 출신이 가장 많다 → 구간별 점수
    mc = d["marketCap"]
    d["s_size"] = np.select(
        [mc < 3000e8, mc < 7000e8, mc < 1.5e12, mc <= 3e12],
        [10, 8, 5, 2],
        default=0,
    ).astype(float)
    d["s_dip"] = _scale(-d["off_high_pct"], 10, 50, 5)        # 고점대비 -50% 이상이면 만점

    score_cols = [c for c in d.columns if c.startswith("s_")]
    d["total"] = d[score_cols].sum(axis=1).round(1)

    # 시그널 태그: 사람이 한눈에 보게
    d["signal"] = np.where(
        (d["vol_mult_max5"] >= 2.0) & (d["total"] >= 60), "🔥발견시작",
        np.where(d["total"] >= 60, "💤저평가대기", "")
    )

    keep = [
        "code", "name", "market", "sectorName", "tradePrice", "marketCap",
        "per", "sectorPer", "pbr", "roe", "debt_pct", "op_margin",
        "vol_mult", "vol_mult_max5", "amt_avg20", "ret_60d", "ret_6m",
        "off_high_pct", "foreignRatio", "total", "signal", "naver_url",
    ] + score_cols
    d = d[keep].sort_values("total", ascending=False).reset_index(drop=True)
    return d


def main():
    src = os.path.join(DATA_DIR, "latest.csv")
    df = pd.read_csv(src, dtype={"code": str})
    out = score(df)
    out.to_csv(os.path.join(DATA_DIR, "screened.csv"), index=False, encoding="utf-8-sig")
    print(f"[screener] 관문 통과 {len(out)}종목 → data/screened.csv")
    if len(out):
        print(out[["name", "per", "roe", "vol_mult_max5", "total", "signal"]].head(15).to_string(index=False))


if __name__ == "__main__":
    main()

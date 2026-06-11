# -*- coding: utf-8 -*-
"""
ai3 collector — 다음(Daum) 금융 API 기반 전종목 데이터 수집기
================================================================
ai2(네이버 크롤링)의 후속. 다음 API는 호출 1번에 펀더멘털 전체를 내려줘서
페이지 크롤링 없이 종목당 2콜(상세 + 일봉)로 끝난다.

출력: data/latest.csv (+ data/snapshot_YYYYMMDD.csv)
사용: python collector.py [--limit N]   # --limit은 테스트용
"""
import argparse
import datetime as dt
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

# ----------------------------- 설정 -----------------------------
MCAP_MIN = 500e8        # 시총 하한 500억 (이보다 작으면 유동성/신뢰성 문제)
MCAP_MAX = 3e12         # 시총 상한 3조 (텐베거는 작은 데서 나온다)
DAYS_LOOKBACK = 130     # 일봉 수집 길이 (약 6개월)
VOL_AVG_WINDOW = 20     # 거래량 배수 기준 이동평균 일수
MAX_WORKERS = 8         # 병렬 수집 스레드 (과하면 차단 위험)
RETRY = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "referer": "https://finance.daum.net",
}

DETAIL_FIELDS = [
    "name", "market", "tradePrice", "marketCap", "per", "pbr", "eps", "bps",
    "debtRatio", "sales", "operatingProfit", "netIncome",
    "sectorName", "sectorPer", "wicsSectorName",
    "high52wPrice", "low52wPrice", "foreignRatio", "listedShareCount",
]

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


# ----------------------------- 유니버스 -----------------------------
def build_universe() -> pd.DataFrame:
    """FinanceDataReader로 KRX 전종목 → 보통주/시총 사전 필터."""
    import FinanceDataReader as fdr

    df = fdr.StockListing("KRX")
    df = df[df["Market"].isin(["KOSPI", "KOSDAQ"])]
    df = df[(df["Marcap"] >= MCAP_MIN) & (df["Marcap"] <= MCAP_MAX)]
    df = df[df["Code"].str.endswith("0")]                      # 보통주만
    df = df[~df["Name"].str.contains("스팩|리츠|ETN|홀딩스", na=False)]
    return df[["Code", "Name", "Market"]].reset_index(drop=True)


# ----------------------------- 수집 -----------------------------
def _get(session: requests.Session, url: str):
    for attempt in range(RETRY + 1):
        try:
            r = session.get(url, timeout=8)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(0.5 * (attempt + 1))
    return None


def fetch_one(session: requests.Session, code: str) -> dict | None:
    """종목 1개: 상세(펀더멘털) + 일봉(거래량/모멘텀) 수집."""
    detail = _get(session, f"https://finance.daum.net/api/quotes/A{code}")
    if not detail:
        return None
    row = {k: detail.get(k) for k in DETAIL_FIELDS}
    row["code"] = code

    days_js = _get(
        session,
        f"https://finance.daum.net/api/quote/A{code}/days"
        f"?symbolCode=A{code}&page=1&perPage={DAYS_LOOKBACK}",
    )
    candles = (days_js or {}).get("data", [])
    # 장중/개장전 당일 행은 accTradeVolume=0 으로 내려옴 → 제외
    candles = [c for c in candles if c.get("accTradeVolume", 0) > 0]
    if len(candles) >= VOL_AVG_WINDOW + 1:
        vols = [c["accTradeVolume"] for c in candles]          # 최신순
        closes = [c["tradePrice"] for c in candles]
        amts = [c.get("accTradePrice", 0) for c in candles]

        row["vol_today"] = vols[0]
        row["vol_avg20"] = sum(vols[1 : VOL_AVG_WINDOW + 1]) / VOL_AVG_WINDOW
        row["vol_mult"] = row["vol_today"] / row["vol_avg20"] if row["vol_avg20"] else None
        row["amt_avg20"] = sum(amts[1 : VOL_AVG_WINDOW + 1]) / VOL_AVG_WINDOW
        row["ret_60d"] = (closes[0] / closes[min(60, len(closes) - 1)] - 1) * 100
        row["ret_6m"] = (closes[0] / closes[-1] - 1) * 100
        # 거래량 배수 5일 최대값: "최근 발견 시그널" — 오늘 하루 조용해도 잡아낸다
        row["vol_mult_max5"] = max(
            v / row["vol_avg20"] for v in vols[:5]
        ) if row["vol_avg20"] else None
    return row


def collect(limit: int | None = None) -> pd.DataFrame:
    uni = build_universe()
    if limit:
        uni = uni.head(limit)
    print(f"[collector] 유니버스 {len(uni)}종목 수집 시작")

    session = requests.Session()
    session.headers.update(HEADERS)

    rows, done = [], 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_one, session, c): c for c in uni["Code"]}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                rows.append(r)
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(uni)}")

    df = pd.DataFrame(rows)
    num_cols = [
        "tradePrice", "marketCap", "per", "pbr", "eps", "bps", "debtRatio",
        "sales", "operatingProfit", "netIncome", "sectorPer",
        "high52wPrice", "low52wPrice", "foreignRatio",
        "vol_today", "vol_avg20", "vol_mult", "vol_mult_max5", "amt_avg20",
        "ret_60d", "ret_6m",
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # 파생 지표
    df["roe"] = df["eps"] / df["bps"] * 100
    df["op_margin"] = df["operatingProfit"] / df["sales"] * 100
    df["debt_pct"] = df["debtRatio"] * 100                     # 다음 API는 배수로 내려줌
    df["off_high_pct"] = (df["tradePrice"] / df["high52wPrice"] - 1) * 100
    df["naver_url"] = "https://finance.naver.com/item/main.naver?code=" + df["code"]

    os.makedirs(DATA_DIR, exist_ok=True)
    today = dt.date.today().strftime("%Y%m%d")
    df.to_csv(os.path.join(DATA_DIR, f"snapshot_{today}.csv"), index=False, encoding="utf-8-sig")
    df.to_csv(os.path.join(DATA_DIR, "latest.csv"), index=False, encoding="utf-8-sig")
    print(f"[collector] 완료: {len(df)}종목 → data/latest.csv")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="테스트용 종목 수 제한")
    args = ap.parse_args()
    collect(limit=args.limit)

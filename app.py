# -*- coding: utf-8 -*-
"""
ai3 — 텐베거 발굴 대시보드 (Streamlit)
실행: streamlit run app.py
데이터: GitHub Actions가 매일 갱신하는 data/screened.csv
"""
import os

import pandas as pd
import streamlit as st

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

st.set_page_config(page_title="ai3 텐베거 스크리너", page_icon="🔭", layout="wide")
st.title("🔭 ai3 — 텐베거 발굴 스크리너")
st.caption("저평가 × 이익체력 × 작은시총 × **거래량 동반** | 데이터: 다음 금융 API (일 1회 갱신)")


@st.cache_data(ttl=3600)
def load():
    path = os.path.join(DATA_DIR, "screened.csv")
    if not os.path.exists(path):
        return None
    return pd.read_csv(path, dtype={"code": str})


df = load()
if df is None or df.empty:
    st.warning("data/screened.csv 가 없습니다. collector.py → screener.py 를 먼저 실행하세요.")
    st.stop()

# ----------------------------- 사이드바 필터 -----------------------------
with st.sidebar:
    st.header("필터")
    min_score = st.slider("최소 총점", 0, 100, 55, 5)
    min_volmult = st.slider("최근 5일 최대 거래량 배수 (이상)", 1.0, 10.0, 1.0, 0.5)
    only_fire = st.checkbox("🔥발견시작 시그널만", value=False)
    markets = st.multiselect("시장", ["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"])
    mcap_max = st.number_input("시총 상한 (억)", value=30000, step=1000)

view = df[
    (df["total"] >= min_score)
    & (df["vol_mult_max5"] >= min_volmult)
    & (df["market"].isin(markets))
    & (df["marketCap"] <= mcap_max * 1e8)
].copy()
if only_fire:
    view = view[view["signal"] == "🔥발견시작"]

# ----------------------------- 상단 요약 -----------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("관문 통과", f"{len(df)}종목")
c2.metric("필터 결과", f"{len(view)}종목")
c3.metric("🔥발견시작", f"{(df['signal'] == '🔥발견시작').sum()}종목")
c4.metric("💤저평가대기", f"{(df['signal'] == '💤저평가대기').sum()}종목")

# ----------------------------- 메인 테이블 -----------------------------
show = view[[
    "signal", "name", "market", "sectorName", "tradePrice", "marketCap",
    "per", "pbr", "roe", "debt_pct", "op_margin",
    "vol_mult_max5", "amt_avg20", "ret_60d", "off_high_pct", "total", "naver_url",
]].rename(columns={
    "signal": "시그널", "name": "종목명", "market": "시장", "sectorName": "섹터",
    "tradePrice": "현재가", "marketCap": "시총", "roe": "ROE%",
    "debt_pct": "부채비율%", "op_margin": "영업이익률%",
    "vol_mult_max5": "거래량배수(5일max)", "amt_avg20": "평균거래대금",
    "ret_60d": "60일수익률%", "off_high_pct": "고점대비%",
    "total": "총점", "naver_url": "네이버",
})
show["시총"] = (show["시총"] / 1e8).round(0).astype("Int64").astype(str) + "억"
show["평균거래대금"] = (show["평균거래대금"] / 1e8).round(1).astype(str) + "억"
for c in ["per", "pbr", "ROE%", "부채비율%", "영업이익률%", "거래량배수(5일max)", "60일수익률%", "고점대비%"]:
    show[c] = pd.to_numeric(show[c], errors="coerce").round(1)

st.dataframe(
    show,
    use_container_width=True,
    height=600,
    column_config={"네이버": st.column_config.LinkColumn("네이버", display_text="📎")},
    hide_index=True,
)

st.divider()
st.caption(
    "⚠️ PER 등 펀더멘털은 트레일링 기준. 텐베거의 마지막 조건인 "
    "'미래 이익 우상향'은 자동화 불가 — 상위 종목은 반드시 DART 분기보고서로 "
    "이익 방향·수주잔고·오버행(CB/유증)을 확인할 것. 본 도구는 투자 판단의 보조 자료다."
)

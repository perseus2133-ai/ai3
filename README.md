# ai3 — 텐베거 발굴 스크리너 🔭

> **ai2의 후속.** 데이터소스를 네이버 크롤링 → **다음(Daum) 금융 API**로 교체하고,
> "저평가 발굴" 가치 필터에 **거래량 동반 시그널**을 결합했다.
> 목표: 만년 저평가가 아니라, **시장이 발견하기 시작한 텐베거 후보**를 잡는 것.

## 핵심 아이디어

텐베거의 필요조건 3가지에 타이밍 조건 1가지를 더했다.

| 축 | 배점 | 내용 |
|---|---|---|
| 가치 | 30 | 저PER(15) + 섹터PER 대비 할인(8) + 저PBR(7) |
| 수익성/체력 | 30 | ROE(12) + 영업이익률(10) + 저부채(8) |
| **수급/거래량** | **25** | **최근 5일 최대 거래량 배수(15)** + 거래대금 절대수준(10) |
| 사이즈/구조 | 15 | 시총 구간(10, 500~3000억 만점) + 52주 고점대비 낙폭(5) |

- 🔥**발견시작**: 총점 60+ 그리고 거래량 배수 2.0x 이상 → 우선 검토 대상
- 💤**저평가대기**: 총점 60+ 인데 거래량이 아직 조용함 → 워치리스트

필수 관문(탈락 시 제외): 흑자(영업이익·순이익 > 0), 20일 평균 거래대금 3억+,
부채비율 200% 미만, 시총 500억~3조.

## 구조 (ai2와 동일한 Actions + CSV 패턴)

```
collector.py   다음 API로 전종목 수집 (종목당 2콜: 상세 + 일봉130개)
   └→ data/latest.csv, data/snapshot_YYYYMMDD.csv
screener.py    100점 스코어링 + 시그널 태깅
   └→ data/screened.csv
app.py         Streamlit 대시보드 (screened.csv 표시)
.github/workflows/daily.yml   평일 16:40 KST 자동 수집·커밋
```

## 다음 API 메모

- 상세: `https://finance.daum.net/api/quotes/A{종목코드}`
  → per, pbr, eps, bps, debtRatio(배수!), sales, operatingProfit, netIncome,
    sectorPer, high52wPrice, foreignRatio 등 한 번에 제공
- 일봉: `https://finance.daum.net/api/quote/A{code}/days?symbolCode=A{code}&page=1&perPage=130`
  → tradePrice, accTradeVolume, accTradePrice (최신순)
- **필수 헤더**: `referer: https://finance.daum.net` + 일반 User-Agent
- 장중 당일 행은 `accTradeVolume=0` → collector가 자동 스킵
- 비공식 API: 차단/변경 가능성 있음. MAX_WORKERS=8 이하 권장.
  (pykrx는 2026년 KRX 로그인 인증 도입으로 사용 불가, 네이버는 환경에 따라 차단)

## 로컬 실행

```bash
pip install -r requirements.txt
python collector.py --limit 100   # 테스트 (100종목)
python collector.py               # 전체 (~1,200종목, 5~10분)
python screener.py
streamlit run app.py
```

## ⚠️ 한계 (중요)

PER·ROE 등은 **트레일링(과거 실적)** 기준이다. 텐베거의 마지막 조건인
"3개년 이익 우상향"은 자동화되지 않는다. 상위 종목은 반드시 DART 분기보고서로
① 최근 4분기 이익 방향 ② 수주잔고/전방시장 ③ CB·유상증자 오버행 을 확인할 것.
본 도구는 후보를 좁혀주는 1차 깔때기이며, 투자 판단의 보조 자료다.

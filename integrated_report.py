#!/usr/bin/env python3
"""
매체별 RAW 탭(메타·구글·네이버 검색광고) → 통합 리포트 탭 (일별·주간·월간)

각 매체 스크립트가 같은 시트에 쌓아 둔 RAW 탭을 읽어, 매체 공통 지표로 맞춘 뒤
아래 탭을 매번 통째로 다시 씁니다. RAW 탭은 읽기만 합니다. (GFA 미포함)

  통합_일별 : 날짜 × 매체 × 캠페인
  통합_주간 : 주(월~일) × 매체, 매체 합계, 전주 대비
  통합_월간 : 월 × 매체, 매체 합계, 전월 대비
  통합_대시보드 : 핵심 지표·매체별 이번 달 성과와 월말 예상·최근 30일 추이·검색어 효율 (dashboard.py)

브랜드검색은 계약 선결제라 API 비용이 0원입니다. 네이버 리포트가 비즈머니 소진 내역에서 '브랜드검색_결제' 탭에
결제액을 적어 두면, 계약 시작일·종료일(비우면 결제일부터 30일)에 하루 같은 금액으로 나눠 네이버 비용에 넣습니다.

공통 지표
  광고비 · 노출수 · 클릭수 · 전환수 · 전환매출 → CTR · CPC · CPA · ROAS · 전환율
  메타: 링크클릭·구매·구매가치 / 구글: 클릭·전환·전환가치 / 네이버: 클릭·구매완료 전환·전환매출
  금액은 원화(KRW)로 통일: 달러 등 외화 계정은 USD_KRW 환율(기본 1,350원)로 환산.
  광고비는 VAT 포함 기준으로 통일: 메타·구글(VAT 별도) 광고비에 1.1을 곱함. 네이버 총비용은 원래 VAT 포함.
  SPEND_VAT=별도 이면 반대로 네이버 총비용을 1.1로 나눠 VAT 별도 기준으로 맞춤. 전환매출은 그대로.

환경변수
  GCP_SA_KEY, SHEET_ID : 매체 스크립트와 같은 시트
  SHEET_TAB / GOOGLE_SHEET_TAB / NAVER_RAW_PREFIX : 매체 스크립트와 같은 탭 이름 설정
  REPORT_TAB_PREFIX    : 통합 탭 이름 앞부분 (기본 통합)
  USD_KRW              : 원화 환산 환율 (기본 1350)
  SPEND_VAT            : 광고비 기준 포함|별도 (기본 포함)

사용법
  python integrated_report.py                # 시트 RAW → 통합 탭 갱신
  python integrated_report.py --dry-run      # 시트 읽기·집계만, 결과는 CSV로
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
MEDIA_ORDER = ["Meta", "Google", "Naver SA"]
SUMS = ["광고비", "노출수", "클릭수", "전환수", "전환매출"]
VAT = 1.1


def env(name, default=None):
    value = os.getenv(name, "").strip()
    return value or default


def num(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


# ───────────────────────── RAW → 공통 행 ─────────────────────────
def to_krw(value, currency):
    cur = str(currency or "KRW").upper()
    if cur == "KRW":
        return value
    if cur == "USD":
        return value * float(env("USD_KRW", "1350"))
    raise ValueError(f"환율 미설정 통화: {cur} (USD·KRW만 지원)")


def vat_included():
    return env("SPEND_VAT", "포함") != "별도"


def spend_from_net(value):
    """메타·구글처럼 VAT 별도 금액 → 리포트 기준."""
    return value * VAT if vat_included() else value


def spend_from_gross(value):
    """네이버처럼 VAT 포함 금액 → 리포트 기준."""
    return value if vat_included() else value / VAT


def from_meta(r):
    return {"날짜": str(r.get("날짜", "")), "매체": "Meta", "계정": r.get("계정명") or r.get("계정ID", ""),
            "캠페인유형": "", "캠페인": r.get("캠페인명", ""),
            "광고비": spend_from_net(to_krw(num(r.get("광고비")), r.get("통화"))),
            "노출수": num(r.get("노출수")), "클릭수": num(r.get("링크클릭수")),
            "전환수": num(r.get("구매")), "전환매출": to_krw(num(r.get("구매가치")), r.get("통화"))}


def from_google(r):
    return {"날짜": str(r.get("날짜", "")), "매체": "Google", "계정": r.get("계정명") or r.get("계정ID", ""),
            "캠페인유형": r.get("캠페인유형", ""), "캠페인": r.get("캠페인명", ""),
            "광고비": spend_from_net(to_krw(num(r.get("광고비")), r.get("통화"))),
            "노출수": num(r.get("노출수")), "클릭수": num(r.get("클릭수")),
            "전환수": num(r.get("전환수")), "전환매출": to_krw(num(r.get("전환가치")), r.get("통화"))}


def from_naver(r):
    return {"날짜": str(r.get("일별", "")), "매체": "Naver SA", "계정": str(r.get("계정ID", "")),
            "캠페인유형": r.get("캠페인 유형", ""), "캠페인": r.get("캠페인", ""), "광고비": spend_from_gross(num(r.get("총비용"))),
            "노출수": num(r.get("노출수")), "클릭수": num(r.get("클릭수")),
            "전환수": num(r.get("구매완료 전환수")), "전환매출": num(r.get("구매완료 전환매출액"))}


def brk(base, r):
    base.update({"차원": r.get("차원", ""), "값": r.get("값", "")})
    return base


def from_naver_media(r):
    row = from_naver(r)
    row.update({"차원": "기기", "값": r.get("PC/모바일 매체", "") or "기타"})
    return row


def loose_day(value):
    """시트에 사람이 적은 날짜(2026-09-21, 2026. 9. 21, 2026/9/21, 날짜 일련번호) → ISO. 못 읽으면 ''."""
    s = str(value or "").strip().rstrip(".")
    if not s:
        return ""
    try:
        if s.replace(".", "", 1).isdigit() and float(s) > 20000:
            return (date(1899, 12, 30) + timedelta(days=int(float(s)))).isoformat()
        parts = [p for p in s.replace("/", "-").replace(".", "-").replace(" ", "").split("-") if p]
        return date(*map(int, parts[:3])).isoformat()
    except (ValueError, TypeError):
        return ""


def brand_search_rows(charges, rows):
    """브랜드검색 계약 결제액을 계약 기간에 하루 같은 금액으로 나눠 네이버 검색광고 비용으로 넣는다.
    기간을 적지 않은 결제는 결제일부터 BRAND_SEARCH_DAYS일(기본 30). 리포트 데이터 기간(첫날~마지막 날) 밖의 몫은 넣지 않음."""
    if not charges or not rows:
        return [], []
    first, last = min(r["날짜"] for r in rows), max(r["날짜"] for r in rows)
    default_days = int(env("BRAND_SEARCH_DAYS", "30"))
    # 비용을 붙일 캠페인: 그 계정·날짜에 노출된 브랜드검색 캠페인이 하나면 그 캠페인, 아니면 '브랜드검색'
    shown = defaultdict(set)
    for r in rows:
        if r["매체"] == "Naver SA" and r["캠페인유형"] == "브랜드검색" and r["노출수"] > 0:
            shown[(r["계정"], r["날짜"])].add(r["캠페인"])
    out, notes = [], []
    for c in charges:
        paid, amount = loose_day(c.get("결제일")), num(c.get("결제금액(VAT포함)"))
        if not paid or not amount:
            continue
        start = loose_day(c.get("계약 시작일")) or paid
        end = loose_day(c.get("계약 종료일")) or (date.fromisoformat(start) + timedelta(days=default_days - 1)).isoformat()
        if end < start:
            notes.append(f"브랜드검색 {paid} 결제: 종료일이 시작일보다 빨라 건너뜀")
            continue
        n = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
        account = str(c.get("계정ID", ""))
        for i in range(n):
            d = (date.fromisoformat(start) + timedelta(days=i)).isoformat()
            if d > last:
                break
            if d < first:
                continue
            names = shown.get((account, d), set())
            camp = str(c.get("캠페인") or "") or (next(iter(names)) if len(names) == 1 else "브랜드검색")
            out.append({"날짜": d, "매체": "Naver SA", "계정": account, "캠페인유형": "브랜드검색", "캠페인": camp,
                        "광고비": spend_from_gross(amount / n), "노출수": 0.0, "클릭수": 0.0, "전환수": 0.0, "전환매출": 0.0})
        notes.append(f"브랜드검색 {paid} 결제 {amount:,.0f}원: {start}~{end} ({n}일) 배분")
    return out, notes


def sources():
    return [
        (env("SHEET_TAB", "meta_daily"), from_meta),
        (env("GOOGLE_SHEET_TAB", "google_daily"), from_google),
        (env("NAVER_RAW_PREFIX", "naver_raw") + "_campaign", from_naver),
    ]


def breakdown_sources():
    """성별·연령·기기 (대시보드 분석용, 합계에는 넣지 않음). 네이버 검색광고는 기기만 제공."""
    return [
        (env("META_BREAKDOWN_TAB", "meta_breakdown"), lambda r: brk(from_meta(r), r)),
        (env("GOOGLE_BREAKDOWN_TAB", "google_breakdown"), lambda r: brk(from_google(r), r)),
        (env("NAVER_RAW_PREFIX", "naver_raw") + "_media", from_naver_media),
    ]


def term(base, product, text):
    base.update({"상품": product, "검색어": str(text)})
    return base


def search_term_sources():
    """검색어 효율 (대시보드 분석용, 합계에는 넣지 않음). 파워링크는 검색어별 전환을 API가 주지 않아 등록 키워드 기준."""
    naver = env("NAVER_RAW_PREFIX", "naver_raw")
    return [
        (naver + "_keyword", lambda r: term(from_naver(r), "파워링크", r.get("키워드", ""))),
        (naver + "_search", lambda r: term(from_naver(r), "쇼핑검색", r.get("검색어", ""))
            if r.get("캠페인 유형") == "쇼핑검색" else None),
        (env("GOOGLE_SEARCH_TERM_TAB", "google_search_terms"),
         lambda r: term(from_google(r), "구글 검색광고", r.get("검색어", ""))),
    ]


def ratios(r):
    s, imp, clk, conv, rev = (r[k] for k in SUMS)
    r["CTR(%)"] = round(clk / imp * 100, 2) if imp else ""
    r["CPC"] = round(s / clk) if clk else ""
    r["전환율(%)"] = round(conv / clk * 100, 2) if clk else ""
    r["CPA"] = round(s / conv) if conv else ""
    r["ROAS(%)"] = round(rev / s * 100, 1) if s else ""
    for k in SUMS:
        r[k] = round(r[k], 2) if k == "전환수" else round(r[k])
    return r


def media_rank(m):
    return MEDIA_ORDER.index(m) if m in MEDIA_ORDER else len(MEDIA_ORDER)


# ───────────────────────── 집계 ─────────────────────────
def week_start(d):
    day = date.fromisoformat(d)
    return (day - timedelta(days=day.weekday())).isoformat()


def daily(rows):
    agg = {}
    for r in rows:
        key = (r["날짜"], r["매체"], r["계정"], r["캠페인유형"], r["캠페인"])
        a = agg.setdefault(key, dict(zip(["날짜", "매체", "계정", "캠페인유형", "캠페인"], key), **{k: 0.0 for k in SUMS}))
        for k in SUMS:
            a[k] += r[k]
    out = [ratios(a) for a in agg.values()]
    out.sort(key=lambda a: (a["날짜"], -media_rank(a["매체"]), a["광고비"]), reverse=True)
    return out


def period(rows, label, keyfn, offset):
    """기간 × 매체 + 합계. 증감은 직전 기간의 같은 일차까지와 비교(진행 중인 주·월도 공정하게)."""
    by_day = defaultdict(lambda: {k: 0.0 for k in SUMS})
    for r in rows:
        for m in (r["매체"], "합계"):
            for k in SUMS:
                by_day[(r["날짜"], m)][k] += r[k]
    days = defaultdict(set)
    for d, _ in by_day:
        days[keyfn(d)].add(d)

    def total(p, m, offsets=None):
        t = {k: 0.0 for k in SUMS}
        for d in days.get(p, ()):
            if (d, m) in by_day and (offsets is None or offset(d) in offsets):
                for k in SUMS:
                    t[k] += by_day[(d, m)][k]
        return t

    out = []
    periods = sorted(days)
    for i, p in enumerate(periods):
        prev = periods[i - 1] if i else None
        offsets = {offset(d) for d in days[p]}
        whole = total(p, "합계")
        for m in sorted({m for d, m in by_day if keyfn(d) == p}, key=lambda m: (m == "합계", media_rank(m))):
            cur = total(p, m)
            row = {label: p, "매체": m, "집계일수": len(days[p]), **cur}
            row["광고비 비중(%)"] = round(cur["광고비"] / whole["광고비"] * 100, 1) if whole["광고비"] else ""
            before = total(prev, m, offsets) if prev else None
            for k in ("광고비", "전환매출"):
                row[f"{k} 증감(%)"] = round((cur[k] / before[k] - 1) * 100, 1) if before and before[k] else ""
            ratios(row)
            if before and before["광고비"] and row["ROAS(%)"] != "":
                row["ROAS 증감(%p)"] = round(row["ROAS(%)"] - before["전환매출"] / before["광고비"] * 100, 1)
            else:
                row["ROAS 증감(%p)"] = ""
            out.append(row)
    rank = {p: i for i, p in enumerate(periods)}
    out.sort(key=lambda r: (-rank[r[label]], r["매체"] == "합계", media_rank(r["매체"])))
    return out


DAILY_COLS = ["날짜", "매체", "계정", "캠페인유형", "캠페인"] + SUMS + ["CTR(%)", "CPC", "전환율(%)", "CPA", "ROAS(%)"]


def period_cols(label):
    return [label, "매체", "집계일수"] + SUMS + ["광고비 비중(%)", "CTR(%)", "CPC", "전환율(%)", "CPA", "ROAS(%)",
                                            "광고비 증감(%)", "전환매출 증감(%)", "ROAS 증감(%p)"]


def build(rows):
    return {
        "일별": (DAILY_COLS, daily(rows)),
        "주간": (period_cols("주 시작(월)"), period(rows, "주 시작(월)", week_start, lambda d: date.fromisoformat(d).weekday())),
        "월간": (period_cols("월"), period(rows, "월", lambda d: d[:7], lambda d: d[8:])),
    }


# ───────────────────────── 시트 입출력 ─────────────────────────
def read_sources(sh, gspread, specs=None):
    rows, notes = [], []
    for tab, fn in specs or sources():
        try:
            values = sh.worksheet(tab).get_values(value_render_option="UNFORMATTED_VALUE")
        except gspread.WorksheetNotFound:
            notes.append(f"{tab}: 탭 없음, 건너뜀")
            continue
        if not values:
            notes.append(f"{tab}: 비어 있음")
            continue
        header = values[0]
        got = [fn(dict(zip(header, v))) for v in values[1:] if any(v)]
        got = [r for r in got if r and len(r["날짜"]) == 10]
        rows += got
        notes.append(f"{tab}: {len(got)}행")
    return rows, notes


def write_tab(sh, gspread, title, cols, data):
    grid = [cols] + [[r.get(c, "") for c in cols] for r in data]
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=max(len(grid), 2), cols=len(cols))
    ws.clear()
    ws.resize(rows=max(len(grid), 2), cols=len(cols))
    for start in range(0, len(grid), 3000):
        ws.update(range_name=f"A{start + 1}", values=grid[start:start + 3000], value_input_option="RAW")
    ws.freeze(rows=1, cols=2)


def write_csv(path, cols, data):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(data)


def step_summary(tabs, notes):
    path = env("GITHUB_STEP_SUMMARY")
    if not path:
        return
    cols, weekly = tabs["주간"]
    lines = ["### 통합 리포트", "", *[f"- {n}" for n in notes], ""]
    if weekly:
        latest = weekly[0][cols[0]]
        lines += [f"최근 주 ({latest} 시작)", "", "| 매체 | 광고비 | 전환매출 | ROAS | 광고비 증감 |", "|---|---:|---:|---:|---:|"]
        for r in weekly:
            if r[cols[0]] == latest:
                lines.append(f"| {r['매체']} | {r['광고비']:,} | {r['전환매출']:,} | {r['ROAS(%)']}% | {r['광고비 증감(%)']}% |")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="집계 결과를 CSV로만 저장, 통합 탭은 건드리지 않음")
    args = p.parse_args()

    import gspread
    key, sheet_id = env("GCP_SA_KEY"), env("SHEET_ID")
    if not key or not sheet_id:
        sys.exit("[오류] GCP_SA_KEY, SHEET_ID 환경변수가 필요합니다.")
    sh = gspread.service_account_from_dict(json.loads(key)).open_by_key(sheet_id)

    rows, notes = read_sources(sh, gspread)
    try:
        charges = sh.worksheet(env("BRAND_SEARCH_TAB", "브랜드검색_결제")).get_all_records(
            value_render_option="UNFORMATTED_VALUE")
    except gspread.WorksheetNotFound:
        charges = []
    brand, brand_notes = brand_search_rows(charges, rows)
    rows += brand
    notes += brand_notes
    breakdown, brk_notes = read_sources(sh, gspread, breakdown_sources())
    notes += brk_notes
    terms, term_notes = read_sources(sh, gspread, search_term_sources())
    notes += term_notes
    notes.append(f"기준: 원화, USD {env('USD_KRW', '1350')}원 환산, 광고비 VAT {'포함' if vat_included() else '별도'}")
    for n in notes:
        print(n)
    if not rows:
        sys.exit("[오류] 읽은 RAW 행이 없습니다. 매체 리포트가 먼저 실행됐는지 확인하세요.")

    tabs = build(rows)
    outdir = Path("reports") / f"integrated_{datetime.now(KST):%Y%m%dT%H%M%S}"
    outdir.mkdir(parents=True, exist_ok=True)
    prefix = env("REPORT_TAB_PREFIX", "통합")
    for name, (cols, data) in tabs.items():
        write_csv(outdir / f"{name}.csv", cols, data)
        if not args.dry_run:
            write_tab(sh, gspread, f"{prefix}_{name}", cols, data)
        print(f"{prefix}_{name}: {len(data)}행{' (dry-run, 시트 미변경)' if args.dry_run else ''}")
    import dashboard
    basis = f"비용 VAT {'포함' if vat_included() else '별도'} · 원화(USD {env('USD_KRW', '1350')}원)"
    board = dashboard.build(rows, breakdown, basis, datetime.now(KST).strftime("%Y-%m-%d %H:%M"), terms)
    with open(outdir / "대시보드.csv", "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(board.grid())
    if not args.dry_run:
        dashboard.write(sh, gspread, f"{prefix}_대시보드", board)
    print(f"{prefix}_대시보드: 갱신{' (dry-run, 시트 미변경)' if args.dry_run else ''}")
    step_summary(tabs, notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())

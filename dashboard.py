"""
통합 대시보드 탭 (구글 시트). integrated_report.py가 넘겨주는 공통 행으로 값·서식·차트를 만들고 매번 다시 그립니다.

  1. 핵심 지표 카드     : 기준일 값, 전일 대비·전주 같은 요일 대비 증감률과 증감액
  2. 매체별 성과        : 기준일(전일·전주 대비 증감액), 최근 7일(직전 7일 대비), 이번 달 누적·월말 예상
  3. 일자별 추이        : 최근 30일 매체별 비용 누적 막대 + ROAS 선, 일자별 히트맵 표
  4. 요일별             : 최근 4주 요일별 일평균과 ROAS
  5. 성별·연령          : 최근 30일 (메타·구글. 네이버 검색광고는 API 미제공)
  6. PC/모바일          : 최근 30일 매체별 기기 비중과 성과
  7. 검색어 효율        : 최근 30일 파워링크(등록 키워드)·쇼핑검색·구글 검색광고 검색어를 고효율·보통·저효율로

수식 없이 값만 씁니다. 탭은 유지(링크 그대로)하고 값·서식·병합·조건부서식·차트만 지운 뒤 다시 그립니다.
"""
import calendar
from collections import defaultdict
from datetime import date, timedelta

SUMS = ["광고비", "노출수", "클릭수", "전환수", "전환매출"]
MEDIA_LABEL = {"Meta": "메타", "Google": "구글", "Naver SA": "네이버검색"}
MEDIA_ORDER = ["메타", "구글", "네이버검색"]
GOOGLE_PRODUCT = {"SEARCH": "검색광고", "PERFORMANCE_MAX": "실적최대화", "DEMAND_GEN": "디맨드젠",
                  "DISPLAY": "디스플레이", "VIDEO": "동영상", "SHOPPING": "쇼핑"}
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
AGE_ORDER = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+", "알수없음"]
GENDER_ORDER = ["여성", "남성", "알수없음"]
DEVICE_ORDER = ["모바일", "PC", "태블릿", "TV", "기타"]
TREND_THRESHOLD = 0.10  # 최근7일 ROAS가 직전7일 대비 ±10% 이상이면 ▲/▼
CHANGE_THRESHOLD = 0.05  # 증감 색칠 기준 ±5%
TERM_PRODUCTS = ["파워링크", "쇼핑검색", "구글 검색광고"]
TERM_TIERS = ["고효율", "보통", "저효율"]
TERM_LOW_RATIO = 0.5  # 상품 평균 ROAS의 50% 미만(전환 없음 포함)이면 저효율
TERM_TOP_N = 10  # 등급마다 비용 상위 몇 개를 보여줄지
COLS = 15  # 핵심 지표 카드 4개 × (3열 + 간격 1열) − 마지막 간격

FORMATS = {"won": "#,##0", "int": "#,##0", "dec": "#,##0.0", "pct": "0%", "pct2": "0.00%",
           "chg": "+0%;-0%;0%", "delta": "+#,##0;-#,##0;0", "pp": '+0"%p";-0"%p";0"%p"'}


def rgb(hex_):
    hex_ = hex_.lstrip("#")
    return {"red": int(hex_[0:2], 16) / 255, "green": int(hex_[2:4], 16) / 255, "blue": int(hex_[4:6], 16) / 255}


NAVY, WHITE, INK, MUTED = rgb("1F3864"), rgb("FFFFFF"), rgb("222222"), rgb("7A7A7A")
CARD_BG, CARD_LINE, PAGE_LINE = rgb("F3F7FC"), rgb("C9D7EA"), rgb("DDDDDD")
GOOD_BG, BAD_BG, TOTAL_BG = rgb("D6F0DC"), rgb("FBD3D7"), rgb("D9E1F2")
GOOD_TXT, BAD_TXT = rgb("1E8E3E"), rgb("D93025")
HEAT = {"cost": rgb("F4B183"), "rev": rgb("FFD966"), "rate": rgb("9DC3E6"), "cnt": rgb("F8CBAD")}
MEDIA_COLOR = {"메타": rgb("4C78A8"), "구글": rgb("F2A33A"), "네이버검색": rgb("54A24B")}

# 카드·표 지표: 이름, 계산, 서식, 좋아지는 방향(+1 클수록 좋음, -1 작을수록 좋음, 0 중립)
KPIS = [
    ("비용", lambda t: t["광고비"], "won", 0),
    ("전환매출", lambda t: t["전환매출"], "won", 1),
    ("ROAS", lambda t: div(t["전환매출"], t["광고비"]), "pct", 1),
    ("전환수", lambda t: t["전환수"], "dec", 1),
    ("CPA", lambda t: div(t["광고비"], t["전환수"]), "won", -1),
    ("클릭수", lambda t: t["클릭수"], "int", 1),
    ("CTR", lambda t: div(t["클릭수"], t["노출수"]), "pct2", 1),
    ("CPC", lambda t: div(t["광고비"], t["클릭수"]), "won", -1),
]


def div(a, b):
    return a / b if b else ""


def chg(cur, before):
    if cur == "" or before in ("", 0):
        return ""
    return cur / before - 1


def pp(a, b):
    """비율 차이를 %p 숫자로."""
    return (a - b) * 100 if a != "" and b != "" else ""


def zero():
    return {k: 0.0 for k in SUMS}


def add(t, r):
    for k in SUMS:
        t[k] += r[k]


def product(r):
    if r["매체"] == "Meta":
        return "메타"
    if r["매체"] == "Google":
        t = str(r.get("캠페인유형") or "")
        return GOOGLE_PRODUCT.get(t, t.title() or "기타")
    return r.get("캠페인유형") or "기타"


def total(series, days):
    t = zero()
    for d in days:
        if d in series:
            add(t, series[d])
    return t


def span(end, n):
    return [(end - timedelta(days=i)).isoformat() for i in range(n)]


def change_text(label, cur, before, kind):
    """카드용 '전일 ▲ 12% (+52,300)' 문구. 비율 지표는 증감액 대신 %p."""
    c = chg(cur, before)
    if c == "":
        return f"{label} -", ""
    arrow = "▲" if c > 0 else ("▼" if c < 0 else "–")
    if kind in ("pct", "pct2"):
        diff = f"{(cur - before) * 100:+.{2 if kind == 'pct2' else 0}f}%p"
    else:
        diff = f"{cur - before:+,.{1 if kind == 'dec' else 0}f}"
    return f"{label} {arrow} {abs(c) * 100:.0f}% ({diff})", c


class Sheet:
    """값 격자 + 서식·차트 지시를 모으는 레이아웃 도우미 (0부터 시작하는 행·열)."""

    def __init__(self):
        self.cells, self.fmt, self.charts, self.heights = {}, [], [], {}
        self.row = 0

    def put(self, r, c, v):
        self.cells[(r, c)] = v

    def style(self, r, c, nr, nc, kind, value=None):
        self.fmt.append((r, c, nr, nc, kind, value))

    def grid(self):
        if not self.cells:
            return []
        rows = max(r for r, _ in self.cells) + 1
        return [[self.cells.get((r, c), "") for c in range(COLS)] for r in range(rows)]

    def section(self, title, note=None):
        self.row += 1
        self.put(self.row, 0, title)
        self.style(self.row, 0, 1, 1, "section")
        self.heights[self.row] = 30
        if note:
            self.put(self.row, 4, note)
            self.style(self.row, 4, 1, 1, "note")
        self.row += 1

    def sub(self, text):
        self.put(self.row, 0, text)
        self.style(self.row, 0, 1, 1, "sub")
        self.row += 1

    def table(self, header, body, kinds, total_row=None, colors=None, signs=None, heat=None):
        """현재 행부터 표를 씀. colors: {(i,j): 배경}, signs: {(i,j): +1/-1 글자색}, heat: {j: 색}. (top, 본문 행 수) 반환."""
        top = self.row
        for j, h in enumerate(header):
            self.put(top, j, h)
        self.style(top, 0, 1, len(header), "header")
        rows = body + ([total_row] if total_row else [])
        for i, values in enumerate(rows, start=1):
            for j, v in enumerate(values):
                self.put(top + i, j, v)
        for j, k in enumerate(kinds):
            if k:
                self.style(top + 1, j, len(rows), 1, "number", FORMATS[k])
        for (i, j), color in (colors or {}).items():
            self.style(top + 1 + i, j, 1, 1, "bg", color)
        for (i, j), sign in (signs or {}).items():
            self.style(top + 1 + i, j, 1, 1, "fg", GOOD_TXT if sign > 0 else BAD_TXT)
        for j, color in (heat or {}).items():
            if body:
                self.style(top + 1, j, len(body), 1, "heat", color)
        if total_row:
            self.style(top + len(rows), 0, 1, len(header), "total")
        if rows:
            self.style(top + 1, 0, len(rows), len(header), "rowlines")
        self.row = top + len(rows) + 1
        return top, len(body)

    def chart(self, spec, row, col, width, height):
        self.charts.append({"spec": spec, "row": row, "col": col, "w": width, "h": height})


def term_tier(roas, avg):
    """상품 평균 ROAS 이상 고효율, 평균의 TERM_LOW_RATIO 이상 보통, 그 밖(전환 없음 포함) 저효율."""
    if roas == "" or not roas:
        return "저효율"
    if avg and roas >= avg:
        return "고효율"
    return "보통" if avg and roas >= avg * TERM_LOW_RATIO else "저효율"


def build(rows, breakdown, basis_note, updated_at, terms=()):
    by_day = defaultdict(zero)
    by_media_day = defaultdict(lambda: defaultdict(zero))
    by_prod = defaultdict(lambda: defaultdict(zero))
    for r in rows:
        media = MEDIA_LABEL.get(r["매체"], r["매체"])
        add(by_day[r["날짜"]], r)
        add(by_media_day[media][r["날짜"]], r)
        add(by_prod[(media, product(r))][r["날짜"]], r)

    s = Sheet()
    s.put(0, 0, "광고 대시보드")
    s.style(0, 0, 1, 1, "title")
    s.heights[0] = 40
    if not by_day:
        s.put(1, 0, "데이터 없음")
        return s

    base = date.fromisoformat(max(by_day))
    b, b1, b7 = base.isoformat(), (base - timedelta(days=1)).isoformat(), (base - timedelta(days=7)).isoformat()
    recent, prior = span(base, 7), span(base - timedelta(days=7), 7)
    last30 = sorted(span(base, 30))
    month_days = [d for d in by_day if d[:7] == b[:7] and d <= b]
    days_left = calendar.monthrange(base.year, base.month)[1] - base.day
    s.put(1, 0, f"기준일 {b} ({WEEKDAYS[base.weekday()]}, 데이터 마지막 날) · {basis_note} · "
                f"전환은 매체 기본 전환 · 갱신 {updated_at}")
    s.style(1, 0, 1, 1, "note")

    # 1. 핵심 지표 카드 (4개씩 2줄, 카드당 3열 + 간격 1열)
    s.row = 2
    s.section("1. 핵심 지표", f"기준일 {b} · 전일 {b1} · 전주 같은 요일 {b7}")
    cur, prev, wk = by_day[b], by_day.get(b1, zero()), by_day.get(b7, zero())
    for n, (name, fn, kind, good) in enumerate(KPIS):
        top, c = s.row + (n // 4) * 5, (n % 4) * 4
        s.put(top, c, name)
        s.put(top + 1, c, fn(cur))
        s.style(top, c, 4, 3, "card")
        s.style(top + 1, c, 1, 1, "number", FORMATS[kind])
        for k, (label, before) in enumerate((("전일", fn(prev)), ("전주", fn(wk)))):
            text, value = change_text(label, fn(cur), before, kind)
            s.put(top + 2 + k, c, text)
            color = MUTED
            if good and value != "" and abs(value) >= CHANGE_THRESHOLD:
                color = GOOD_TXT if value * good > 0 else BAD_TXT
            s.style(top + 2 + k, c, 1, 3, "cardline", color)
        for i in range(4):
            s.style(top + i, c, 1, 3, "merge")
        s.heights[top + 1] = 38
    s.row += 9

    # 2. 매체별 성과
    s.section("2. 매체별 성과", "증감액 = 기준 기간 − 비교 기간 · ROAS 증감은 %p")
    prods = sorted(by_prod, key=lambda k: (-total(by_prod[k], recent)["광고비"], k))
    rows_src = [(m, p, by_prod[(m, p)]) for m, p in prods] + [("합계", "", by_day)]

    # 2-1. 기준일 vs 전일·전주 같은 요일
    s.sub(f"2-1. 기준일 {b} · 전일·전주 같은 요일 대비")
    body, signs = [], {}
    for i, (m, p, series) in enumerate(rows_src):
        t0, t1, t7 = (series.get(d, zero()) for d in (b, b1, b7))
        roas = [div(t["전환매출"], t["광고비"]) for t in (t0, t1, t7)]
        line = [m, p, t0["광고비"], t0["광고비"] - t1["광고비"], t0["광고비"] - t7["광고비"],
                t0["전환매출"], t0["전환매출"] - t1["전환매출"], t0["전환매출"] - t7["전환매출"],
                roas[0], pp(roas[0], roas[1]), pp(roas[0], roas[2]), t0["전환수"], div(t0["광고비"], t0["전환수"])]
        for j in (6, 7, 9, 10):
            if line[j] not in ("", 0):
                signs[(i, j)] = 1 if line[j] > 0 else -1
        body.append(line)
    total_line = body.pop()
    s.table(["매체", "상품", "비용", "전일 대비", "전주 대비", "전환매출", "전일 대비", "전주 대비",
             "ROAS", "전일 대비", "전주 대비", "전환수", "CPA"], body,
            [None, None, "won", "delta", "delta", "won", "delta", "delta", "pct", "pp", "pp", "dec", "won"],
            total_row=total_line, signs=signs)
    s.row += 1

    # 2-2. 최근 7일 vs 직전 7일
    s.sub(f"2-2. 최근 7일 ({recent[-1]} ~ {b}) · 직전 7일 대비")
    body, colors = [], {}
    for i, (m, p, series) in enumerate(rows_src):
        r7, p7 = total(series, recent), total(series, prior)
        roas7, roasp = div(r7["전환매출"], r7["광고비"]), div(p7["전환매출"], p7["광고비"])
        line = [m, p, r7["광고비"], r7["광고비"] - p7["광고비"], chg(r7["광고비"], p7["광고비"]),
                r7["전환매출"], r7["전환매출"] - p7["전환매출"], chg(r7["전환매출"], p7["전환매출"]),
                roas7, roasp, r7["전환수"], div(r7["광고비"], r7["전환수"]), div(p7["광고비"], p7["전환수"])]
        for j, v in ((7, line[7]), (8, chg(roas7, roasp))):
            if v != "" and abs(v) >= CHANGE_THRESHOLD:
                colors[(i, j)] = GOOD_BG if v > 0 else BAD_BG
        body.append(line)
    total_line = body.pop()
    s.table(["매체", "상품", "비용", "증감액", "증감률", "전환매출", "증감액", "증감률", "ROAS", "직전 ROAS",
             "전환수", "CPA", "직전 CPA"], body,
            [None, None, "won", "delta", "chg", "won", "delta", "chg", "pct", "pct", "dec", "won", "won"],
            total_row=total_line, colors=colors)
    s.row += 1

    # 2-3. 이번 달 누적·월말 예상
    s.sub(f"2-3. 이번 달 누적 ({b[:7]}) · 월말 예상 = 누적 + 최근 7일 일평균 × 남은 {days_left}일")
    body, colors = [], {}
    month_rows = [(m, p, se) for m, p, se in rows_src if m == "합계" or any(total(se, month_days).values())]
    for i, (m, p, series) in enumerate(month_rows):
        mtd, r7, p7 = total(series, month_days), total(series, recent), total(series, prior)
        fc = {k: mtd[k] + r7[k] / 7 * days_left for k in SUMS}
        roas7, roasp = div(r7["전환매출"], r7["광고비"]), div(p7["전환매출"], p7["광고비"])
        delta = chg(roas7, roasp)
        trend = "" if m == "합계" else ("—" if delta == "" or abs(delta) < TREND_THRESHOLD else ("▲" if delta > 0 else "▼"))
        if trend in ("▲", "▼"):
            colors[(i, 11)] = GOOD_BG if trend == "▲" else BAD_BG
        body.append([m, p, mtd["광고비"], mtd["전환매출"], div(mtd["전환매출"], mtd["광고비"]),
                     div(mtd["광고비"], mtd["전환수"]), fc["광고비"], fc["전환매출"], div(fc["전환매출"], fc["광고비"]),
                     roas7, roasp, trend])
    total_line = body.pop()
    top, n = s.table(["매체", "상품", "누적 비용", "누적 매출", "누적 ROAS", "CPA", "예상 월 비용", "예상 월 매출",
                      "예상 ROAS", "최근7일 ROAS", "직전7일 ROAS", "추세"], body,
                     [None, None, "won", "won", "pct", "won", "won", "won", "pct", "pct", "pct", None],
                     total_row=total_line, colors=colors)
    s.style(top + 1, 11, n + 1, 1, "center")

    # 3. 일자별 추이: 차트 + 히트맵 표
    s.section("3. 일자별 추이 (최근 30일)", "막대 = 매체별 비용, 선 = ROAS")
    chart_row = s.row
    s.row += 20
    body = []
    for d in last30:
        t = by_day.get(d, zero())
        body.append([d, WEEKDAYS[date.fromisoformat(d).weekday()], t["광고비"]]
                    + [by_media_day[m].get(d, zero())["광고비"] for m in MEDIA_ORDER]
                    + [t["전환매출"], div(t["전환매출"], t["광고비"]), t["전환수"], div(t["광고비"], t["전환수"]),
                       t["클릭수"], div(t["클릭수"], t["노출수"]), div(t["전환수"], t["클릭수"])])
    t30 = total(by_day, last30)
    total_line = (["합계", "", t30["광고비"]] + [total(by_media_day[m], last30)["광고비"] for m in MEDIA_ORDER]
                  + [t30["전환매출"], div(t30["전환매출"], t30["광고비"]), t30["전환수"], div(t30["광고비"], t30["전환수"]),
                     t30["클릭수"], div(t30["클릭수"], t30["노출수"]), div(t30["전환수"], t30["클릭수"])])
    top, n = s.table(["날짜", "요일", "비용"] + [f"{m} 비용" for m in MEDIA_ORDER] +
                     ["전환매출", "ROAS", "전환수", "CPA", "클릭수", "CTR", "전환율"], body,
                     [None, None, "won", "won", "won", "won", "won", "pct", "dec", "won", "int", "pct2", "pct2"],
                     total_row=total_line,
                     heat={2: HEAT["cost"], 6: HEAT["rev"], 7: HEAT["rate"], 8: HEAT["cnt"], 10: HEAT["cnt"],
                           11: HEAT["rate"], 12: HEAT["rate"]})
    s.style(top + 1, 1, n + 1, 1, "center")
    s.chart({"kind": "combo_stacked", "title": "일자별 매체 비용 · ROAS", "top": top, "rows": n,
             "domain": 0, "columns": [3, 4, 5], "line": 7,
             "colors": [MEDIA_COLOR[m] for m in MEDIA_ORDER]}, chart_row, 0, 1180, 400)

    # 4. 요일별 (최근 4주)
    days28 = span(base, 28)
    s.section("4. 요일별 (최근 4주 일평균)", f"{days28[-1]} ~ {b}")
    wk_days = defaultdict(list)
    for d in days28:
        wk_days[date.fromisoformat(d).weekday()].append(d)
    body = []
    for w in range(7):
        t, n_days = total(by_day, wk_days[w]), max(len(wk_days[w]), 1)
        body.append([WEEKDAYS[w], t["광고비"] / n_days, t["전환매출"] / n_days, div(t["전환매출"], t["광고비"]),
                     t["전환수"] / n_days, div(t["광고비"], t["전환수"]), div(t["전환수"], t["클릭수"])])
    top, n = s.table(["요일", "일평균 비용", "일평균 매출", "ROAS", "일평균 전환", "CPA", "전환율"], body,
                     [None, "won", "won", "pct", "dec", "won", "pct2"],
                     heat={1: HEAT["cost"], 2: HEAT["rev"], 3: HEAT["rate"], 4: HEAT["cnt"], 6: HEAT["rate"]})
    s.style(top + 1, 0, n, 1, "center")
    s.chart({"kind": "combo", "title": "요일별 일평균 비용 · ROAS", "top": top, "rows": n, "domain": 0,
             "columns": [1], "line": 3, "colors": [NAVY]}, top, 8, 560, 260)
    s.row = max(s.row, top + 14)

    # 5·6. 성별·연령 / PC·모바일 (분석용 breakdown 행)
    brk = defaultdict(lambda: defaultdict(zero))  # (차원, 값) → 매체 → 합계
    last30_set = set(last30)
    for r in breakdown:
        if r["날짜"] in last30_set:
            add(brk[(r["차원"], str(r["값"]))][MEDIA_LABEL.get(r["매체"], r["매체"])], r)

    def values_of(dim, order):
        return sorted({v for d, v in brk if d == dim}, key=lambda v: (order.index(v) if v in order else 99, v))

    def dim_table(dim, order, title, chart_kind):
        s.sub(title)
        values = values_of(dim, order)
        if not values:
            s.put(s.row, 0, f"{dim} 데이터 없음 (아직 수집 전이거나 매체가 제공하지 않음)")
            s.style(s.row, 0, 1, 1, "note")
            s.row += 2
            return
        sums = {v: zero() for v in values}
        all_t = zero()
        for v in values:
            for t in brk[(dim, v)].values():
                add(sums[v], t)
                add(all_t, t)
        line = lambda v, t: [v, t["광고비"], div(t["광고비"], all_t["광고비"]), t["전환매출"],
                             div(t["전환매출"], t["광고비"]), t["전환수"], div(t["광고비"], t["전환수"]),
                             div(t["클릭수"], t["노출수"])]
        top, n = s.table([dim, "비용", "비용 비중", "전환매출", "ROAS", "전환수", "CPA", "CTR"],
                         [line(v, sums[v]) for v in values],
                         [None, "won", "pct", "won", "pct", "dec", "won", "pct2"], total_row=line("합계", all_t),
                         heat={2: HEAT["cost"], 4: HEAT["rate"]})
        title_ = f"{dim}별 비용 비중" if chart_kind == "pie" else f"{dim}별 비용 · ROAS"
        s.chart({"kind": chart_kind, "title": title_, "top": top, "rows": n, "domain": 0, "columns": [1], "line": 4,
                 "colors": [NAVY]}, top - 1, 9, 440, 240)
        s.row = max(s.row, top + 13)

    s.section("5. 성별 · 연령 (최근 30일)", "메타·구글 기준 · 네이버 검색광고는 API에서 성별·연령 미제공 · 구글 실적최대화 제외")
    dim_table("성별", GENDER_ORDER, "5-1. 성별", "pie")
    dim_table("연령", AGE_ORDER, "5-2. 연령대", "combo")

    s.section("6. PC / 모바일 (최근 30일)", "매체 내 비중 = 해당 매체 비용 중 기기별 비율")
    dim_table("기기", DEVICE_ORDER, "6-1. 전체", "pie")
    devices = values_of("기기", DEVICE_ORDER)
    if devices:
        s.sub("6-2. 매체별")
        body = []
        for m in MEDIA_ORDER:
            media_total = sum(brk[("기기", v)].get(m, zero())["광고비"] for v in devices)
            for v in devices:
                t = brk[("기기", v)].get(m)
                if not t or not any(t.values()):
                    continue
                body.append([m, v, t["광고비"], div(t["광고비"], media_total), t["전환매출"],
                             div(t["전환매출"], t["광고비"]), t["전환수"], div(t["광고비"], t["전환수"]),
                             div(t["클릭수"], t["노출수"]), div(t["전환수"], t["클릭수"])])
        s.table(["매체", "기기", "비용", "매체 내 비중", "전환매출", "ROAS", "전환수", "CPA", "CTR", "전환율"], body,
                [None, None, "won", "pct", "won", "pct", "dec", "won", "pct2", "pct2"],
                heat={3: HEAT["cost"], 5: HEAT["rate"]})

    # 7. 검색어 효율: 상품별로 검색어를 합친 뒤 상품 평균 ROAS와 비교해 등급을 매김
    by_term = defaultdict(zero)
    camps = defaultdict(lambda: defaultdict(float))
    for r in terms:
        if r["날짜"] in last30_set:
            k = (r["상품"], r["검색어"])
            add(by_term[k], r)
            camps[k][r["캠페인"]] += r["광고비"]
    by_term = {k: t for k, t in by_term.items() if t["광고비"] > 0}
    low = f"{TERM_LOW_RATIO:.0%}"
    s.section("7. 검색어 효율 (최근 30일)",
              f"상품 평균 ROAS 이상 = 고효율 · 평균의 {low} 이상 = 보통 · 평균의 {low} 미만(전환 없음 포함) = 저효율 · "
              "비용이 있는 검색어만 · 파워링크는 검색어별 전환을 API가 주지 않아 등록 키워드 기준")
    products = [p for p in TERM_PRODUCTS if any(k[0] == p for k in by_term)]
    if not products:
        s.put(s.row, 0, "검색어 데이터 없음 (아직 수집 전)")
        s.style(s.row, 0, 1, 1, "note")
        return s
    tier_bg = {"고효율": GOOD_BG, "저효율": BAD_BG}
    graded = {}
    for p in products:
        p_total = zero()
        for (prod, _), t in by_term.items():
            if prod == p:
                add(p_total, t)
        avg = div(p_total["전환매출"], p_total["광고비"])
        graded[p] = (p_total, avg, sorted(
            ((term_tier(div(t["전환매출"], t["광고비"]), avg), text, t)
             for (prod, text), t in by_term.items() if prod == p),
            key=lambda x: (TERM_TIERS.index(x[0]), -x[2]["광고비"], x[1])))

    s.sub("7-1. 등급별 요약")
    body, colors = [], {}
    for p in products:
        p_total, avg, items = graded[p]
        for tier in TERM_TIERS:
            t, n = zero(), 0
            for g, _, v in items:
                if g == tier:
                    add(t, v)
                    n += 1
            colors[(len(body), 1)] = tier_bg.get(tier)
            body.append([p, tier, n, t["광고비"], div(t["광고비"], p_total["광고비"]), t["전환매출"],
                         div(t["전환매출"], p_total["전환매출"]), div(t["전환매출"], t["광고비"]), t["전환수"],
                         div(t["광고비"], t["전환수"])])
    top, n = s.table(["상품", "등급", "검색어 수", "비용", "비용 비중", "전환매출", "매출 비중", "ROAS", "전환수", "CPA"],
                     body, [None, None, "int", "won", "pct", "won", "pct", "pct", "dec", "won"],
                     colors={k: v for k, v in colors.items() if v})
    s.style(top + 1, 1, n, 1, "center")
    s.row += 1

    for i, p in enumerate(products, start=2):
        p_total, avg, items = graded[p]
        label = "키워드" if p == "파워링크" else "검색어"
        s.sub(f"7-{i}. {p} · 평균 ROAS {avg:.0%} · 등급마다 비용 상위 {TERM_TOP_N}개" if avg != ""
              else f"7-{i}. {p} · 전환 없음 · 비용 상위 {TERM_TOP_N}개")
        body, colors, shown = [], {}, defaultdict(int)
        for tier, text, t in items:
            if shown[tier] >= TERM_TOP_N:
                continue
            shown[tier] += 1
            camp = max(camps[(p, text)].items(), key=lambda x: x[1])[0]
            if len(camps[(p, text)]) > 1:
                camp += f" 외 {len(camps[(p, text)]) - 1}"
            if tier in tier_bg:
                colors[(len(body), 0)] = tier_bg[tier]
            body.append([tier, text, camp, t["광고비"], div(t["광고비"], p_total["광고비"]), t["클릭수"],
                         div(t["클릭수"], t["노출수"]), div(t["광고비"], t["클릭수"]), t["전환수"], t["전환매출"],
                         div(t["전환매출"], t["광고비"]), div(t["광고비"], t["전환수"])])
        top, n = s.table(["등급", label, "캠페인", "비용", "비용 비중", "클릭수", "CTR", "CPC", "전환수", "전환매출",
                          "ROAS", "CPA"], body,
                         [None, None, None, "won", "pct", "int", "pct2", "won", "dec", "won", "pct", "won"],
                         colors=colors)
        s.style(top + 1, 0, n, 1, "center")
        s.row += 1
    return s


# ───────────────────────── 시트 반영 ─────────────────────────
def _range(sid, r, c, nr, nc):
    return {"sheetId": sid, "startRowIndex": r, "endRowIndex": r + nr, "startColumnIndex": c, "endColumnIndex": c + nc}


def _cell(sid, r, c, nr, nc, fmt, fields):
    return {"repeatCell": {"range": _range(sid, r, c, nr, nc), "cell": {"userEnteredFormat": fmt}, "fields": fields}}


def _chart(sid, ch):
    sp = ch["spec"]

    def src(col):
        return {"sourceRange": {"sources": [_range(sid, sp["top"], col, sp["rows"] + 1, 1)]}}

    if sp["kind"] == "pie":
        spec = {"title": sp["title"], "pieChart": {"legendPosition": "RIGHT_LEGEND", "pieHole": 0.5,
                                                    "domain": src(sp["domain"]), "series": src(sp["columns"][0])}}
    else:
        series = [{"series": src(c), "type": "COLUMN", "targetAxis": "LEFT_AXIS", "colorStyle": {"rgbColor": color}}
                  for c, color in zip(sp["columns"], sp["colors"])]
        series.append({"series": src(sp["line"]), "type": "LINE", "targetAxis": "RIGHT_AXIS",
                       "colorStyle": {"rgbColor": BAD_TXT}})
        spec = {"title": sp["title"], "basicChart": {
            "chartType": "COMBO", "legendPosition": "BOTTOM_LEGEND", "headerCount": 1,
            "stackedType": "STACKED" if sp["kind"] == "combo_stacked" else "NOT_STACKED",
            "axis": [{"position": "LEFT_AXIS", "title": "비용"}, {"position": "RIGHT_AXIS", "title": "ROAS"}],
            "domains": [{"domain": src(sp["domain"])}], "series": series}}
    return {"addChart": {"chart": {"spec": spec, "position": {"overlayPosition": {
        "anchorCell": {"sheetId": sid, "rowIndex": ch["row"], "columnIndex": ch["col"]},
        "widthPixels": ch["w"], "heightPixels": ch["h"]}}}}}


def requests(sid, sheet):
    n_rows = len(sheet.grid()) + 5
    reqs = [{"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"hideGridlines": True}},
                                       "fields": "gridProperties.hideGridlines"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0,
                                                     "endIndex": COLS},
                                           "properties": {"pixelSize": 92}, "fields": "pixelSize"}},
            _cell(sid, 0, 0, n_rows, COLS, {"textFormat": {"fontSize": 10, "foregroundColor": INK},
                                            "verticalAlignment": "MIDDLE"},
                  "userEnteredFormat(textFormat,verticalAlignment)")]
    for r, h in sheet.heights.items():
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": r,
                                                             "endIndex": r + 1},
                                                   "properties": {"pixelSize": h}, "fields": "pixelSize"}})
    line = {"style": "SOLID", "color": PAGE_LINE}
    text = "userEnteredFormat.textFormat"
    for r, c, nr, nc, kind, value in sheet.fmt:
        rng = _range(sid, r, c, nr, nc)
        if kind == "title":
            reqs.append(_cell(sid, r, c, nr, nc, {"textFormat": {"bold": True, "fontSize": 18, "foregroundColor": NAVY}}, text))
        elif kind == "section":
            reqs.append(_cell(sid, r, c, nr, nc, {"textFormat": {"bold": True, "fontSize": 13, "foregroundColor": NAVY}}, text))
        elif kind == "sub":
            reqs.append(_cell(sid, r, c, nr, nc, {"textFormat": {"bold": True, "fontSize": 10, "foregroundColor": INK}}, text))
        elif kind == "note":
            reqs.append(_cell(sid, r, c, nr, nc, {"textFormat": {"italic": True, "fontSize": 9, "foregroundColor": MUTED}}, text))
        elif kind == "header":
            reqs.append(_cell(sid, r, c, nr, nc, {"backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                                                  "wrapStrategy": "WRAP",
                                                  "textFormat": {"bold": True, "foregroundColor": WHITE}},
                              "userEnteredFormat(backgroundColor,horizontalAlignment,wrapStrategy,textFormat)"))
        elif kind == "number":
            reqs.append(_cell(sid, r, c, nr, nc, {"numberFormat": {"type": "NUMBER", "pattern": value},
                                                  "horizontalAlignment": "RIGHT"},
                              "userEnteredFormat(numberFormat,horizontalAlignment)"))
        elif kind == "bg":
            reqs.append(_cell(sid, r, c, nr, nc, {"backgroundColor": value}, "userEnteredFormat.backgroundColor"))
        elif kind == "fg":
            reqs.append(_cell(sid, r, c, nr, nc, {"textFormat": {"foregroundColor": value, "bold": True}},
                              "userEnteredFormat(textFormat.foregroundColor,textFormat.bold)"))
        elif kind == "total":
            reqs.append(_cell(sid, r, c, nr, nc, {"backgroundColor": TOTAL_BG, "textFormat": {"bold": True}},
                              "userEnteredFormat(backgroundColor,textFormat.bold)"))
        elif kind == "center":
            reqs.append(_cell(sid, r, c, nr, nc, {"horizontalAlignment": "CENTER"}, "userEnteredFormat.horizontalAlignment"))
        elif kind == "rowlines":
            reqs.append({"updateBorders": {"range": rng, "bottom": line, "innerHorizontal": line}})
        elif kind == "merge":
            reqs.append({"mergeCells": {"range": rng, "mergeType": "MERGE_ALL"}})
        elif kind == "card":
            box = {"style": "SOLID", "color": CARD_LINE}
            reqs.append(_cell(sid, r, c, nr, nc, {"backgroundColor": CARD_BG, "horizontalAlignment": "LEFT"},
                              "userEnteredFormat(backgroundColor,horizontalAlignment)"))
            reqs.append(_cell(sid, r, c, 1, nc, {"textFormat": {"fontSize": 10, "foregroundColor": MUTED}}, text))
            reqs.append(_cell(sid, r + 1, c, 1, nc, {"textFormat": {"fontSize": 20, "bold": True, "foregroundColor": INK},
                                                     "horizontalAlignment": "LEFT"},
                              "userEnteredFormat(textFormat,horizontalAlignment)"))
            reqs.append({"updateBorders": {"range": rng, "top": box, "bottom": box, "left": box, "right": box}})
        elif kind == "cardline":
            reqs.append(_cell(sid, r, c, nr, nc, {"textFormat": {"fontSize": 9, "bold": True, "foregroundColor": value}}, text))
        elif kind == "heat":
            reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {"ranges": [rng], "gradientRule": {
                "minpoint": {"type": "MIN", "color": WHITE}, "maxpoint": {"type": "MAX", "color": value}}}}})
    reqs += [_chart(sid, ch) for ch in sheet.charts]
    return reqs


def write(sh, gspread, title, sheet):
    """탭은 유지(링크 그대로)하고 값·서식·병합·조건부서식·차트를 지운 뒤 다시 그림. 없으면 맨 앞에 만듦."""
    grid = sheet.grid()
    rows = max(len(grid) + 10, 60)
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=rows, cols=COLS, index=0)
    ws.resize(rows=rows, cols=COLS)
    reset = []
    for meta in sh.fetch_sheet_metadata().get("sheets", []):
        if meta["properties"]["sheetId"] == ws.id:
            reset += [{"deleteEmbeddedObject": {"objectId": c["chartId"]}} for c in meta.get("charts", [])]
            reset += [{"deleteConditionalFormatRule": {"sheetId": ws.id, "index": 0}}
                      for _ in meta.get("conditionalFormats", [])]
    reset += [{"unmergeCells": {"range": {"sheetId": ws.id}}},
              {"updateCells": {"range": {"sheetId": ws.id}, "fields": "userEnteredValue,userEnteredFormat"}},
              {"updateBorders": {"range": {"sheetId": ws.id}, "top": {"style": "NONE"}, "bottom": {"style": "NONE"},
                                 "left": {"style": "NONE"}, "right": {"style": "NONE"},
                                 "innerHorizontal": {"style": "NONE"}, "innerVertical": {"style": "NONE"}}},
              {"updateDimensionProperties": {"range": {"sheetId": ws.id, "dimension": "ROWS"},
                                             "properties": {"pixelSize": 21}, "fields": "pixelSize"}}]
    sh.batch_update({"requests": reset})
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    sh.batch_update({"requests": requests(ws.id, sheet)})

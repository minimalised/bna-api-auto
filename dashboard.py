"""
통합 대시보드 탭: 핵심 지표(전일·최근 7일·이번 달·월말 예상), 매체·상품별 이번 달 성과, 최근 30일 일별 추이.

integrated_report.py가 공통 행(날짜·매체·캠페인유형·광고비·노출수·클릭수·전환수·전환매출)을 넘겨주면
값 격자와 서식을 만들고, 탭을 새로 만들어 씁니다. 수식 없이 값만 쓰므로 매 실행마다 통째로 갱신됩니다.
"""
import calendar
from collections import defaultdict
from datetime import date, timedelta

SUMS = ["광고비", "노출수", "클릭수", "전환수", "전환매출"]
MEDIA_LABEL = {"Meta": "메타", "Google": "구글", "Naver SA": "네이버검색"}
GOOGLE_PRODUCT = {"SEARCH": "검색광고", "PERFORMANCE_MAX": "실적최대화", "DEMAND_GEN": "디맨드젠",
                  "DISPLAY": "디스플레이", "VIDEO": "동영상", "SHOPPING": "쇼핑"}
TREND_THRESHOLD = 0.10  # 최근7일 ROAS가 직전7일 대비 ±10% 이상 변하면 ▲/▼
CHANGE_THRESHOLD = 0.05  # 핵심 지표 증감 색칠 기준 ±5%

# 지표명, 계산, 서식, 좋아지는 방향(+1 클수록 좋음, -1 작을수록 좋음, 0 색 없음)
KPIS = [
    ("비용", lambda t: t["광고비"], "won", 0),
    ("전환매출", lambda t: t["전환매출"], "won", 1),
    ("ROAS", lambda t: div(t["전환매출"], t["광고비"]), "pct", 1),
    ("전환수", lambda t: t["전환수"], "int", 1),
    ("CPA", lambda t: div(t["광고비"], t["전환수"]), "won", -1),
    ("클릭수", lambda t: t["클릭수"], "int", 1),
    ("CTR", lambda t: div(t["클릭수"], t["노출수"]), "pct2", 1),
    ("전환율", lambda t: div(t["전환수"], t["클릭수"]), "pct2", 1),
    ("CPC", lambda t: div(t["광고비"], t["클릭수"]), "won", -1),
]
FORMATS = {"won": "#,##0", "int": "#,##0", "pct": "0%", "pct2": "0.00%", "chg": "+0%;-0%;0%"}

NAVY = {"red": 0.12, "green": 0.22, "blue": 0.39}
WHITE = {"red": 1, "green": 1, "blue": 1}
GOOD = {"red": 0.78, "green": 0.94, "blue": 0.81}
BAD = {"red": 1.0, "green": 0.78, "blue": 0.81}
TOTAL_BG = {"red": 0.85, "green": 0.88, "blue": 0.95}
GRAY = {"red": 0.45, "green": 0.45, "blue": 0.45}


def div(a, b):
    return a / b if b else ""


def chg(cur, before):
    if cur == "" or before in ("", 0):
        return ""
    return cur / before - 1


def product(r):
    if r["매체"] == "Meta":
        return "메타"
    if r["매체"] == "Google":
        t = str(r.get("캠페인유형") or "")
        return GOOGLE_PRODUCT.get(t, t.title() or "기타")
    return r.get("캠페인유형") or "기타"


def total(by_day, days):
    t = {k: 0.0 for k in SUMS}
    for d in days:
        for k in SUMS:
            t[k] += by_day.get(d, {}).get(k, 0.0)
    return t


def span(end, n):
    return [(end - timedelta(days=i)).isoformat() for i in range(n)]


class Sheet:
    """값 격자 + 서식 지시를 모아 두는 작은 레이아웃 도우미 (0부터 시작하는 행·열)."""

    def __init__(self):
        self.cells = {}
        self.fmt = []  # (row, col, nrows, ncols, kind, value)
        self.row = 0

    def put(self, r, c, v):
        self.cells[(r, c)] = v

    def style(self, r, c, nr, nc, kind, value=None):
        self.fmt.append((r, c, nr, nc, kind, value))

    def grid(self):
        if not self.cells:
            return []
        rows = max(r for r, _ in self.cells) + 1
        cols = max(c for _, c in self.cells) + 1
        return [[self.cells.get((r, c), "") for c in range(cols)] for r in range(rows)]

    def table(self, header, body, kinds, total_row=None, colors=None):
        top = self.row
        for c, h in enumerate(header):
            self.put(top, c, h)
        self.style(top, 0, 1, len(header), "header")
        rows = body + ([total_row] if total_row else [])
        for i, values in enumerate(rows, start=1):
            for c, v in enumerate(values):
                self.put(top + i, c, v)
        for c, k in enumerate(kinds):
            if k:
                self.style(top + 1, c, len(rows), 1, "number", FORMATS[k])
        for (i, c), color in (colors or {}).items():
            self.style(top + 1 + i, c, 1, 1, "bg", color)
        if total_row:
            self.style(top + len(rows), 0, 1, len(header), "total")
        self.style(top + 1, 0, len(rows), len(header), "rowlines")
        self.row = top + len(rows) + 1
        return top


def build(rows, basis_note, updated_at):
    by_day = defaultdict(lambda: {k: 0.0 for k in SUMS})
    by_prod = defaultdict(lambda: defaultdict(lambda: {k: 0.0 for k in SUMS}))
    for r in rows:
        for k in SUMS:
            by_day[r["날짜"]][k] += r[k]
            by_prod[(MEDIA_LABEL.get(r["매체"], r["매체"]), product(r))][r["날짜"]][k] += r[k]

    s = Sheet()
    if not by_day:
        s.put(0, 0, "광고 대시보드")
        s.put(1, 0, "데이터 없음")
        return s, None

    base = date.fromisoformat(max(by_day))
    month_days = [d for d in by_day if d[:7] == base.isoformat()[:7] and d <= base.isoformat()]
    days_left = calendar.monthrange(base.year, base.month)[1] - base.day
    recent, prior = span(base, 7), span(base - timedelta(days=7), 7)

    def periods(series):
        cur, prev = total(series, [base.isoformat()]), total(series, [(base - timedelta(days=1)).isoformat()])
        r7, p7, mtd = total(series, recent), total(series, prior), total(series, month_days)
        fc = {k: mtd[k] + r7[k] / 7 * days_left for k in SUMS}
        return cur, prev, r7, p7, mtd, fc

    s.put(0, 0, "광고 대시보드")
    s.style(0, 0, 1, 1, "title")
    s.put(1, 0, f"기준일 {base.isoformat()} (데이터 마지막 날) · {basis_note} · 전환은 매체 기본 전환 · 갱신 {updated_at}")
    s.style(1, 0, 1, 1, "note")

    # 1. 핵심 지표
    s.row = 3
    s.put(s.row, 0, "1. 핵심 지표")
    s.style(s.row, 0, 1, 1, "section")
    s.row += 1
    cur, prev, r7, p7, mtd, fc = periods(by_day)
    body, colors = [], {}
    for i, (name, fn, kind, good) in enumerate(KPIS):
        a, b, c, d = fn(cur), fn(prev), fn(r7), fn(p7)
        d1, d7 = chg(a, b), chg(c, d)
        body.append([name, a, b, d1, c, d, d7, fn(mtd), fn(fc)])
        for col, v in ((3, d1), (6, d7)):
            if good and v != "" and abs(v) >= CHANGE_THRESHOLD:
                colors[(i, col)] = GOOD if v * good > 0 else BAD
    s.table(["지표", "기준일", "전일", "증감", "최근 7일", "직전 7일", "증감", "이번 달 누적", "월말 예상"], body,
            [None, None, None, "chg", None, None, "chg", None, None], colors=colors)
    # 지표마다 서식이 달라서 숫자 열은 행 단위로 다시 지정
    top = s.row - len(body)
    for i, (_, _, kind, _) in enumerate(KPIS):
        for col in (1, 2, 4, 5, 7, 8):
            s.style(top + i, col, 1, 1, "number", FORMATS[kind])
    s.put(s.row, 0, f"월말 예상 = 이번 달 누적 + 최근 7일 일평균 × 남은 {days_left}일")
    s.style(s.row, 0, 1, 1, "note")

    # 2. 매체·상품별 이번 달
    s.row += 2
    s.put(s.row, 0, "2. 매체별 이번 달 성과와 월말 예상")
    s.style(s.row, 0, 1, 1, "section")
    s.row += 1
    body, colors, sums = [], {}, {"mtd": {k: 0.0 for k in SUMS}, "fc": {k: 0.0 for k in SUMS},
                                   "r7": {k: 0.0 for k in SUMS}, "p7": {k: 0.0 for k in SUMS}}
    items = []
    for (media, prod), series in by_prod.items():
        _, _, r7, p7, mtd, fc = periods(series)
        if not any(mtd[k] for k in SUMS):
            continue
        for name, t in (("mtd", mtd), ("fc", fc), ("r7", r7), ("p7", p7)):
            for k in SUMS:
                sums[name][k] += t[k]
        items.append((media, prod, mtd, fc, r7, p7))
    items.sort(key=lambda x: -x[2]["광고비"])
    for i, (media, prod, mtd, fc, r7, p7) in enumerate(items):
        roas7, roasp = div(r7["전환매출"], r7["광고비"]), div(p7["전환매출"], p7["광고비"])
        delta = chg(roas7, roasp)
        trend = "—" if delta == "" or abs(delta) < TREND_THRESHOLD else ("▲" if delta > 0 else "▼")
        if trend != "—":
            colors[(i, 11)] = GOOD if trend == "▲" else BAD
        body.append([media, prod, mtd["광고비"], mtd["전환매출"], div(mtd["전환매출"], mtd["광고비"]),
                     div(mtd["광고비"], mtd["전환수"]), fc["광고비"], fc["전환매출"],
                     div(fc["전환매출"], fc["광고비"]), roas7, roasp, trend])
    t = sums
    total_row = ["합계", "", t["mtd"]["광고비"], t["mtd"]["전환매출"], div(t["mtd"]["전환매출"], t["mtd"]["광고비"]),
                 div(t["mtd"]["광고비"], t["mtd"]["전환수"]), t["fc"]["광고비"], t["fc"]["전환매출"],
                 div(t["fc"]["전환매출"], t["fc"]["광고비"]), div(t["r7"]["전환매출"], t["r7"]["광고비"]),
                 div(t["p7"]["전환매출"], t["p7"]["광고비"]), ""]
    s.table(["매체", "상품", "누적 비용", "누적 매출", "누적 ROAS", "CPA", "예상 월 비용", "예상 월 매출",
             "예상 ROAS", "최근7일 ROAS", "직전7일 ROAS", "추세"], body,
            [None, None, "won", "won", "pct", "won", "won", "won", "pct", "pct", "pct", None],
            total_row=total_row, colors=colors)
    s.style(s.row - len(body) - 1, 11, len(body) + 1, 1, "center")

    # 3. 일별 추이
    s.row += 1
    s.put(s.row, 0, "3. 일별 추이 (최근 30일, 전체 매체)")
    s.style(s.row, 0, 1, 1, "section")
    s.row += 1
    body = []
    for d in sorted(span(base, 30)):
        t = by_day.get(d, {k: 0.0 for k in SUMS})
        body.append([d, t["광고비"], t["전환매출"], div(t["전환매출"], t["광고비"]), t["전환수"],
                     div(t["광고비"], t["전환수"]), t["클릭수"]])
    top = s.table(["날짜", "비용", "전환매출", "ROAS", "전환수", "CPA", "클릭수"], body,
                  [None, "won", "won", "pct", "int", "won", "int"])
    chart = {"top": top, "rows": len(body)}
    return s, chart


# ───────────────────────── 시트 반영 ─────────────────────────
def _range(sid, r, c, nr, nc):
    return {"sheetId": sid, "startRowIndex": r, "endRowIndex": r + nr, "startColumnIndex": c, "endColumnIndex": c + nc}


def _cell(sid, r, c, nr, nc, fmt, fields):
    return {"repeatCell": {"range": _range(sid, r, c, nr, nc), "cell": {"userEnteredFormat": fmt}, "fields": fields}}


def requests(sid, sheet, chart):
    reqs = [{"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"hideGridlines": True}},
                                       "fields": "gridProperties.hideGridlines"}}]
    widths = [110, 120] + [105] * 10
    for i, w in enumerate(widths):
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": i,
                                                             "endIndex": i + 1},
                                                   "properties": {"pixelSize": w}, "fields": "pixelSize"}})
    base_font = {"textFormat": {"fontSize": 10}}
    reqs.append(_cell(sid, 0, 0, 200, 14, base_font, "userEnteredFormat.textFormat.fontSize"))
    for r, c, nr, nc, kind, value in sheet.fmt:
        if kind == "title":
            reqs.append(_cell(sid, r, c, nr, nc, {"textFormat": {"bold": True, "fontSize": 15}}, "userEnteredFormat.textFormat"))
        elif kind == "section":
            reqs.append(_cell(sid, r, c, nr, nc, {"textFormat": {"bold": True, "fontSize": 12, "foregroundColor": NAVY}},
                              "userEnteredFormat.textFormat"))
        elif kind == "note":
            reqs.append(_cell(sid, r, c, nr, nc, {"textFormat": {"italic": True, "fontSize": 9, "foregroundColor": GRAY}},
                              "userEnteredFormat.textFormat"))
        elif kind == "header":
            reqs.append(_cell(sid, r, c, nr, nc, {"backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                                                  "textFormat": {"bold": True, "foregroundColor": WHITE}},
                              "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"))
        elif kind == "number":
            reqs.append(_cell(sid, r, c, nr, nc, {"numberFormat": {"type": "NUMBER", "pattern": value},
                                                  "horizontalAlignment": "RIGHT"},
                              "userEnteredFormat(numberFormat,horizontalAlignment)"))
        elif kind == "bg":
            reqs.append(_cell(sid, r, c, nr, nc, {"backgroundColor": value}, "userEnteredFormat.backgroundColor"))
        elif kind == "total":
            reqs.append(_cell(sid, r, c, nr, nc, {"backgroundColor": TOTAL_BG, "textFormat": {"bold": True}},
                              "userEnteredFormat(backgroundColor,textFormat.bold)"))
        elif kind == "center":
            reqs.append(_cell(sid, r, c, nr, nc, {"horizontalAlignment": "CENTER"}, "userEnteredFormat.horizontalAlignment"))
        elif kind == "rowlines":
            line = {"style": "SOLID", "color": {"red": 0.85, "green": 0.85, "blue": 0.85}}
            reqs.append({"updateBorders": {"range": _range(sid, r, c, nr, nc), "bottom": line, "innerHorizontal": line}})
    if chart:
        top, n = chart["top"], chart["rows"]

        def src(col):
            return {"sourceRange": {"sources": [_range(sid, top, col, n + 1, 1)]}}

        reqs.append({"addChart": {"chart": {
            "spec": {"title": "일별 비용 · ROAS", "basicChart": {
                "chartType": "COMBO", "legendPosition": "BOTTOM_LEGEND", "headerCount": 1,
                "axis": [{"position": "LEFT_AXIS", "title": "비용"}, {"position": "RIGHT_AXIS", "title": "ROAS"}],
                "domains": [{"domain": src(0)}],
                "series": [{"series": src(1), "type": "COLUMN", "targetAxis": "LEFT_AXIS"},
                           {"series": src(3), "type": "LINE", "targetAxis": "RIGHT_AXIS"}]}},
            "position": {"overlayPosition": {"anchorCell": {"sheetId": sid, "rowIndex": top, "columnIndex": 8},
                                             "widthPixels": 620, "heightPixels": 360}}}}})
    return reqs


def write(sh, gspread, title, sheet, chart):
    """탭은 유지(링크 그대로)하고 값·서식·차트만 지운 뒤 다시 그림. 없으면 맨 앞에 만듦."""
    grid = sheet.grid()
    rows = max(len(grid) + 20, 60)
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=rows, cols=14, index=0)
    reset = []
    for meta in sh.fetch_sheet_metadata().get("sheets", []):
        if meta["properties"]["sheetId"] == ws.id:
            reset += [{"deleteEmbeddedObject": {"objectId": c["chartId"]}} for c in meta.get("charts", [])]
    reset.append({"updateCells": {"range": {"sheetId": ws.id}, "fields": "userEnteredValue,userEnteredFormat"}})
    reset.append({"updateBorders": {"range": {"sheetId": ws.id}, "top": {"style": "NONE"}, "bottom": {"style": "NONE"},
                                    "innerHorizontal": {"style": "NONE"}}})
    sh.batch_update({"requests": reset})
    ws.resize(rows=rows, cols=14)
    ws.update(range_name="A1", values=grid, value_input_option="RAW")
    sh.batch_update({"requests": requests(ws.id, sheet, chart)})

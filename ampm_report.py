"""AMPM 네이버 검색광고 리포트 시트 갱신 (조회만 하고 광고는 바꾸지 않음)

GitHub Actions(ampm-report.yml)에서 매일 실행. 공개 저장소이므로 로그에는 행 수만 출력하고
캠페인명·금액 등 데이터는 출력하거나 파일로 남기지 않는다.

환경 변수: AMPM_NAVER_API_KEY, AMPM_NAVER_SECRET_KEY, AMPM_NAVER_CUSTOMER_ID, GCP_SA_KEY, AMPM_SHEET_ID
  (AMPM_ 키가 비어 있으면 NAVER_API_KEY / NAVER_SECRET_KEY 를 사용)
사용: python ampm_report.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--dry-run]
기본 기간: KST 기준 어제까지 8일.

시트 탭 (1행 헤더 유지, 2행부터 씀, 비용은 VAT 포함 x1.1):
  Naver_일별_캠페인  A날짜 B유형 C캠페인 D기기 E광고비용 F노출수 G(빈칸) H클릭수 I~K(빈칸) L전환수 M전환매출액
  Naver_일별_광고그룹 A날짜 B유형 C캠페인 D기기 E광고그룹 F노출수 G클릭수 H광고비용 I전환수 J전환매출액
  Naver_일별_전환유형 A날짜 B유형 C캠페인 D기기 E광고그룹 F전환방식 G전환코드 H전환수 I전환매출액
  위 세 탭은 가져온 날짜만 교체하고 나머지 날짜는 유지.
  Naver_월별 (2026-01부터 월 x 캠페인), Naver_캠페인_상태 는 덮어쓰기.
"""
import argparse, base64, csv, datetime as dt, hashlib, hmac, io, json, os, sys, time
import urllib.error, urllib.parse, urllib.request
from collections import defaultdict

BASE = "https://api.searchad.naver.com"
KST = dt.timezone(dt.timedelta(hours=9))
MONTH_SINCE = dt.date(2026, 1, 1)
TP = {"WEB_SITE": "파워링크", "SHOPPING": "쇼핑검색", "BRAND_SEARCH": "브랜드검색",
      "POWER_CONTENTS": "파워컨텐츠", "PLACE": "플레이스"}
FIELDS = json.dumps(["impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt"])


def env(*names):
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    raise SystemExit(f"환경 변수 없음: {names[0]}")


class Api:
    def __init__(self):
        self.key = env("AMPM_NAVER_API_KEY", "NAVER_API_KEY")
        self.secret = env("AMPM_NAVER_SECRET_KEY", "NAVER_SECRET_KEY")
        self.cid = env("AMPM_NAVER_CUSTOMER_ID")

    def _headers(self, method, path):
        ts = str(int(time.time() * 1000))
        sig = base64.b64encode(hmac.new(self.secret.encode(), f"{ts}.{method}.{path}".encode(),
                                        hashlib.sha256).digest()).decode()
        return {"Content-Type": "application/json; charset=UTF-8", "X-Timestamp": ts,
                "X-API-KEY": self.key, "X-Customer": self.cid, "X-Signature": sig}

    def req(self, method, path, params=None, body=None, raw_url=None):
        url = raw_url or BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        # 서명된 주소·헤더·응답 본문은 출력하지 않는다.
        for attempt in range(5):
            r = urllib.request.Request(url, data=data, method=method, headers=self._headers(method, path))
            try:
                with urllib.request.urlopen(r, timeout=60) as resp:
                    content = resp.read()
                if raw_url:
                    return content
                return json.loads(content) if content else None
            except urllib.error.HTTPError as e:
                if e.code != 429 and e.code < 500:
                    raise RuntimeError(f"{method} {path}: HTTP {e.code}") from None
                reason = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                reason = "network/timeout"
            if attempt == 4:
                raise RuntimeError(f"{method} {path}: 재시도 초과 ({reason})")
            time.sleep(min(2 ** (attempt + 1), 20))

    def report(self, tp, day):
        job = self.req("POST", "/stat-reports", body={"reportTp": tp, "statDt": day.strftime("%Y%m%d")})
        jid = job["reportJobId"]
        try:
            for _ in range(300):
                st = self.req("GET", f"/stat-reports/{jid}")
                s = str(st.get("status", "")).upper()
                if s in ("BUILT", "DONE"):
                    u = urllib.parse.urlsplit(st["downloadUrl"])
                    if u.scheme != "https" or u.path != "/report-download":
                        raise RuntimeError("예상하지 못한 다운로드 주소")
                    raw = self.req("GET", u.path, raw_url=st["downloadUrl"])
                    try:
                        text = raw.decode("utf-8-sig")
                    except UnicodeDecodeError:
                        text = raw.decode("cp949")
                    return [c for c in csv.reader(io.StringIO(text), delimiter="\t") if c and any(c)]
                if s == "NONE":
                    return []
                if "ERROR" in s:
                    raise RuntimeError(f"{tp} {day} 보고서 오류 {s}")
                time.sleep(2)
            raise RuntimeError(f"{tp} {day} 보고서 시간 초과")
        finally:
            try:
                self.req("DELETE", f"/stat-reports/{jid}")
            except Exception:
                pass


def dev(v):
    return "MO" if v.strip().upper().startswith("M") else "PC"


def num(v):
    try:
        return float(v or 0)
    except ValueError:
        return 0.0


def name_dev(n):
    return "PC" if "PC" in n and "MO" not in n else ("MO" if "MO" in n and "PC" not in n else "전체")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    today = dt.datetime.now(KST).date()
    until = dt.date.fromisoformat(a.until) if a.until else today - dt.timedelta(days=1)
    since = dt.date.fromisoformat(a.since) if a.since else until - dt.timedelta(days=7)
    stamp = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    api = Api()

    camps = api.req("GET", "/ncc/campaigns") or []
    cmap = {c["nccCampaignId"]: c for c in camps}
    gmap = {}
    for c in camps:
        for g in api.req("GET", "/ncc/adgroups", {"nccCampaignId": c["nccCampaignId"]}) or []:
            gmap[g["nccAdgroupId"]] = g
    print(f"캠페인 {len(camps)}개, 광고그룹 {len(gmap)}개", flush=True)
    ctp = lambda cid: TP.get(cmap.get(cid, {}).get("campaignTp", ""), cmap.get(cid, {}).get("campaignTp", ""))
    cname = lambda cid: cmap.get(cid, {}).get("name", cid)
    gname = lambda gid: gmap.get(gid, {}).get("name", gid)

    agg = defaultdict(lambda: [0.0] * 5)   # (date,cid,gid,dev) imp clk cost conv amt
    cvt = defaultdict(lambda: [0.0, 0.0])  # (date,cid,gid,dev,method,type)
    dates = []
    day = since
    while day <= until:
        ad, cv = api.report("AD", day), api.report("AD_CONVERSION", day)
        for r in ad:  # 2 campaign, 3 adgroup, 8 PC/M, 9 imp, 10 clk, 11 cost
            v = agg[(day.isoformat(), r[2], r[3], dev(r[8]))]
            v[0] += num(r[9]); v[1] += num(r[10]); v[2] += num(r[11])
        for r in cv:  # 8 PC/M, 9 method, 10 type, 11 count, 12 sales
            k = (day.isoformat(), r[2], r[3], dev(r[8]))
            v = agg[k]
            v[3] += num(r[11]); v[4] += num(r[12])
            t = cvt[k + (r[9].strip(), r[10].strip())]
            t[0] += num(r[11]); t[1] += num(r[12])
        print(f"{day}: AD {len(ad)}행, 전환 {len(cv)}행", flush=True)
        dates.append(day.isoformat())
        day += dt.timedelta(days=1)

    camp_sum = defaultdict(lambda: [0.0] * 5)
    grp = []
    for (d, cid, gid, dv), v in agg.items():
        s = camp_sum[(d, ctp(cid), cname(cid), dv)]
        for i in range(5):
            s[i] += v[i]
        grp.append([d, ctp(cid), cname(cid), dv, gname(gid), int(v[0]), int(v[1]), round(v[2] * 1.1),
                    int(v[3]), round(v[4])])
    camp = [[k[0], k[1], k[2], k[3], round(v[2] * 1.1), int(v[0]), "", int(v[1]), "", "", "", int(v[3]), round(v[4])]
            for k, v in camp_sum.items()]
    conv = [[d, ctp(cid), cname(cid), dv, gname(gid), {"1": "직접", "2": "간접"}.get(m, m), t, int(v[0]), round(v[1])]
            for (d, cid, gid, dv, m, t), v in cvt.items()]

    # 월별 (/stats 일별을 월로 합침, 92일 제한이라 89일씩)
    month = defaultdict(lambda: [0.0] * 5)
    for c in camps:
        s = MONTH_SINCE
        while s <= until:
            e = min(s + dt.timedelta(days=88), until)
            r = api.req("GET", "/stats", {"id": c["nccCampaignId"], "fields": FIELDS, "timeIncrement": "1",
                                          "timeRange": json.dumps({"since": s.isoformat(), "until": e.isoformat()})})
            for d in (r or {}).get("data", []):
                m = month[(d["dateStart"][:7], c["nccCampaignId"])]
                for i, f in enumerate(["impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt"]):
                    m[i] += d.get(f) or 0
            s = e + dt.timedelta(days=1)
            time.sleep(0.2)
    mon = [[mo, ctp(cid), cname(cid), name_dev(cname(cid)), round(v[2] * 1.1), int(v[0]), int(v[1]), int(v[3]), round(v[4])]
           for (mo, cid), v in sorted(month.items()) if any(v)]

    state = []
    for x in sorted(camps, key=lambda x: x["nccCampaignId"]):
        bud = x.get("dailyBudget") if x.get("useDailyBudget") else "제한 없음"
        if x.get("sharedBudgetId"):
            bud = "공유예산"
        state.append([x["nccCampaignId"], ctp(x["nccCampaignId"]), name_dev(x["name"]), x["name"],
                      "OFF" if x.get("userLock") else "ON", bud, x.get("status", ""), stamp,
                      "게재중" if x.get("status") == "ELIGIBLE" else "중지"])

    print(f"새 행: 캠페인 {len(camp)}, 광고그룹 {len(grp)}, 전환유형 {len(conv)}, 월별 {len(mon)}, 상태 {len(state)}", flush=True)
    if a.dry_run:
        print("dry-run: 시트는 바꾸지 않음")
        return

    import gspread
    sh = gspread.service_account_from_dict(json.loads(env("GCP_SA_KEY"))).open_by_key(env("AMPM_SHEET_ID"))
    dset = set(dates)

    def write(tab, last_col, rows, keep_old):
        ws = sh.worksheet(tab)
        if keep_old:
            old = ws.get(f"A2:{last_col}", value_render_option="UNFORMATTED_VALUE",
                         date_time_render_option="FORMATTED_STRING")
            old = [r for r in old if r and str(r[0]) not in dset and str(r[0]).strip()]
            rows = old + rows
        width = ord(last_col) - ord("A") + 1
        rows = [list(r) + [""] * (width - len(r)) for r in rows]
        rows.sort(key=lambda r: tuple(str(x) for x in r[:5]))
        ws.batch_clear([f"A2:{last_col}"])
        if rows:
            if ws.row_count < len(rows) + 1:
                ws.add_rows(len(rows) + 1 - ws.row_count)
            ws.update(values=rows, range_name=f"A2:{last_col}{len(rows) + 1}", value_input_option="USER_ENTERED")
        print(f"{tab}: {len(rows)}행", flush=True)

    write("Naver_일별_캠페인", "M", camp, True)
    write("Naver_일별_광고그룹", "J", grp, True)
    write("Naver_일별_전환유형", "I", conv, True)
    write("Naver_월별", "I", mon, False)
    write("Naver_캠페인_상태", "I", state, False)
    print(f"완료 {since}~{until}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 데이터가 섞인 메시지가 나오지 않도록 짧게
        print(f"::error::{type(exc).__name__}: {str(exc)[:200]}", flush=True)
        sys.exit(1)

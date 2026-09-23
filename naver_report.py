#!/usr/bin/env python3
"""
네이버 검색광고 캠페인 성과 → 구글 시트 적재 (최근 N일 upsert) + CSV 백업

환경변수
  NAVER_API_KEY       : 액세스 라이선스
  NAVER_SECRET_KEY    : 비밀키
  NAVER_CUSTOMER_ID   : 키를 발급한 계정의 CUSTOMER_ID
  NAVER_CUSTOMER_IDS  : 조회할 광고주 CUSTOMER_ID, 쉼표 구분 (비우면 NAVER_CUSTOMER_ID)
  GCP_SA_KEY, SHEET_ID: 메타·구글과 동일
  NAVER_SHEET_TAB     : 기본 naver_daily

사용법
  python naver_report.py                       # 최근 14일(어제까지) 재조회 → 시트 덮어쓰기
  python naver_report.py --since 2026-09-01 --until 2026-09-22
  python naver_report.py --list-accounts       # 권한 위임받은 광고주 계정 목록
"""
import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.naver.com"
KST = timezone(timedelta(hours=9))
LOOKBACK_DAYS = 20  # 계정의 전환 기여 기간 설정에 맞춰 조정
STAT_FIELDS = ["impCnt", "clkCnt", "salesAmt", "avgRnk", "ccnt", "convAmt"]


def get_env(name, required=True, default=""):
    value = os.getenv(name, "").strip() or default
    if required and not value:
        sys.exit(f"[오류] 환경변수 {name} 가 비어 있습니다.")
    return value


API_KEY = get_env("NAVER_API_KEY")
SECRET_KEY = get_env("NAVER_SECRET_KEY")
OWNER_ID = get_env("NAVER_CUSTOMER_ID")


# ───────────────────────── 인증·호출 ─────────────────────────
def headers(method, uri, customer_id):
    ts = str(int(time.time() * 1000))
    msg = f"{ts}.{method}.{uri}"
    sig = base64.b64encode(hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()).decode()
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Timestamp": ts,
        "X-API-KEY": API_KEY,
        "X-Customer": str(customer_id),
        "X-Signature": sig,
    }


def api_get(uri, customer_id, params=None, max_retry=5):
    for attempt in range(max_retry):
        r = requests.get(BASE_URL + uri, params=params, headers=headers("GET", uri, customer_id), timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            wait = 5 * (attempt + 1)
            print(f"  ↻ {r.status_code} → {wait}초 후 재시도")
            time.sleep(wait)
            continue
        if not r.ok:
            try:
                err = r.json()
                msg = f"{err.get('code')} {err.get('title') or err.get('message')}"
            except ValueError:
                msg = r.text[:300]
            raise RuntimeError(f"HTTP {r.status_code}: {msg}")
        return r.json()
    raise RuntimeError("재시도 횟수 초과")


# ───────────────────────── 수집 ─────────────────────────
def list_accounts():
    print("\n[접근 가능한 광고주 계정]")
    print(f"  {OWNER_ID}  (키 발급 계정)")
    try:
        links = api_get("/customer-links", OWNER_ID, {"type": "MYCLIENTS"})
    except Exception as e:
        print(f"  권한 위임 목록 조회 실패: {e}")
        return
    if not links:
        print("  위임받은 계정 없음")
    for c in links:
        cid = c.get("clientCustomerId") or c.get("customerId")
        name = c.get("clientLoginId") or c.get("clientName") or c.get("name") or ""
        print(f"  {cid}  {name}")


def get_campaigns(customer_id):
    data = api_get("/ncc/campaigns", customer_id)
    return {c["nccCampaignId"]: c for c in data}


def get_stats(customer_id, ids, day):
    out = []
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        res = api_get("/stats", customer_id, {
            "ids": json.dumps(chunk),
            "fields": json.dumps(STAT_FIELDS),
            "timeRange": json.dumps({"since": day, "until": day}),
        })
        out.extend(res.get("data", []))
    return out


def daterange(since, until):
    d, end = date.fromisoformat(since), date.fromisoformat(until)
    while d <= end:
        yield d.isoformat()
        d += timedelta(days=1)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fetch_account(customer_id, since, until):
    campaigns = get_campaigns(customer_id)
    if not campaigns:
        return []
    ids = list(campaigns)
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    rows = []
    for day in daterange(since, until):
        for s in get_stats(customer_id, ids, day):
            imp, clk = int(num(s.get("impCnt"))), int(num(s.get("clkCnt")))
            cost, conv, val = round(num(s.get("salesAmt"))), num(s.get("ccnt")), round(num(s.get("convAmt")))
            if not (imp or cost or conv):
                continue
            c = campaigns.get(s.get("id"), {})
            rows.append({
                "날짜": day,
                "계정ID": str(customer_id),
                "계정명": str(customer_id),
                "캠페인ID": s.get("id"),
                "캠페인명": c.get("name", ""),
                "캠페인유형": c.get("campaignTp", ""),
                "통화": "KRW",
                "노출수": imp,
                "클릭수": clk,
                "CTR(%)": round(clk / imp * 100, 2) if imp else 0,
                "광고비": cost,
                "CPC": round(cost / clk) if clk else 0,
                "평균순위": round(num(s.get("avgRnk")), 1),
                "전환수": int(conv),
                "전환가치": val,
                "ROAS(%)": round(val / cost * 100, 1) if cost else 0,
                "CPA": round(cost / conv) if conv else 0,
                "수집시각": now,
            })
    return rows


# ───────────────────────── 시트 ─────────────────────────
def upsert_sheet(new_rows, since, until, done_ids):
    import gspread

    gc = gspread.service_account_from_dict(json.loads(get_env("GCP_SA_KEY")))
    sh = gc.open_by_key(get_env("SHEET_ID"))
    tab = get_env("NAVER_SHEET_TAB", required=False, default="naver_daily")
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=1000, cols=30)

    values = ws.get_values(value_render_option="UNFORMATTED_VALUE")
    old_header = values[0] if values else []
    old_rows = [dict(zip(old_header, v)) for v in values[1:]] if values else []
    kept = [r for r in old_rows
            if not (since <= str(r.get("날짜", "")) <= until and str(r.get("계정ID", "")) in done_ids)]
    removed = len(old_rows) - len(kept)

    header = list(new_rows[0].keys()) if new_rows else old_header
    for h in old_header:
        if h and h not in header:
            header.append(h)
    merged = kept + new_rows
    merged.sort(key=lambda r: (str(r.get("날짜", "")), num(r.get("광고비"))), reverse=True)
    out = [header] + [[r.get(h, "") for h in header] for r in merged]
    ws.resize(rows=max(len(out), 2), cols=max(len(header), 1))
    ws.update(out, "A1", value_input_option="RAW")
    ws.freeze(rows=1)
    print(f"\n시트 적재 완료: '{tab}' 탭 / 교체 {removed}행 → 신규 {len(new_rows)}행 / 전체 {len(merged)}행")


def write_summary(rows, since, until):
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path or not rows:
        return
    agg = defaultdict(lambda: {"광고비": 0, "클릭수": 0, "전환수": 0, "전환가치": 0})
    for r in rows:
        a = agg[r["계정ID"]]
        for k in a:
            a[k] += r[k]
    lines = [f"### 네이버 검색광고 리포트 {since} ~ {until}", "",
             "| 계정 | 광고비 | 클릭 | 전환 | 전환매출 | ROAS |", "|---|---:|---:|---:|---:|---:|"]
    for name, a in agg.items():
        roas = f"{a['전환가치'] / a['광고비'] * 100:.0f}%" if a["광고비"] else "-"
        lines.append(f"| {name} | {a['광고비']:,} | {a['클릭수']:,} | {a['전환수']:,} | {a['전환가치']:,} | {roas} |")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ───────────────────────── 실행 ─────────────────────────
def main():
    today = datetime.now(KST).date()
    p = argparse.ArgumentParser()
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--list-accounts", action="store_true")
    args = p.parse_args()

    if args.list_accounts:
        list_accounts()
        return

    since = args.since or (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    until = args.until or (args.since if args.since else (today - timedelta(days=1)).isoformat())
    targets = [c.strip() for c in get_env("NAVER_CUSTOMER_IDS", required=False, default=OWNER_ID).split(",") if c.strip()]
    print(f"기간 {since} ~ {until} / 계정 {len(targets)}개")

    rows, done, failed = [], set(), []
    for cid in targets:
        try:
            r = fetch_account(cid, since, until)
            rows.extend(r)
            done.add(cid)
            print(f"  ✓ {cid}: {len(r)}행")
        except Exception as e:
            failed.append(cid)
            print(f"  ✗ {cid}: {e}")

    if rows:
        Path("reports").mkdir(exist_ok=True)
        out = Path("reports") / f"naver_{since}_{until}.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV 저장: {out} ({len(rows)}행)")
        write_summary(rows, since, until)

    if get_env("SHEET_ID", required=False) and done:
        upsert_sheet(rows, since, until, done)

    if failed:
        sys.exit(f"실패 계정: {', '.join(failed)}")


if __name__ == "__main__":
    main()

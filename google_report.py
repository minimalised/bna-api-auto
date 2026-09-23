#!/usr/bin/env python3
"""
Google Ads 캠페인 성과 → 구글 시트 적재 (최근 N일 upsert) + CSV 백업

환경변수
  GOOGLE_ADS_DEVELOPER_TOKEN     : MCC API 센터의 개발자 토큰
  GOOGLE_ADS_CLIENT_ID           : OAuth 클라이언트 ID
  GOOGLE_ADS_CLIENT_SECRET       : OAuth 클라이언트 보안 비밀
  GOOGLE_ADS_REFRESH_TOKEN       : OAuth 갱신 토큰
  GOOGLE_ADS_LOGIN_CUSTOMER_ID   : MCC 고객 ID (하이픈 없이)
  GOOGLE_ADS_CUSTOMER_IDS        : 조회할 광고계정 ID, 쉼표 구분 (하이픈 있어도 됨)
  GCP_SA_KEY, SHEET_ID           : 메타와 동일한 시트 사용
  GOOGLE_SHEET_TAB               : 기본 google_daily

사용법
  python google_report.py                     # 최근 30일(어제까지) 재조회 → 시트 덮어쓰기
  python google_report.py --since 2026-09-01 --until 2026-09-22
  python google_report.py --list-accounts     # MCC 하위 계정 ID 목록 확인
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

KST = timezone(timedelta(hours=9))
LOOKBACK_DAYS = 30  # 구글 기본 전환 추적 기간(30일) 동안 전환이 클릭일로 소급 반영됨
ZERO_DECIMAL = {"KRW", "JPY", "VND", "TWD", "CLP", "ISK", "HUF"}

QUERY = """
SELECT
  customer.id, customer.descriptive_name, customer.currency_code,
  campaign.id, campaign.name, campaign.advertising_channel_type,
  segments.date,
  metrics.impressions, metrics.clicks, metrics.cost_micros,
  metrics.conversions, metrics.conversions_value
FROM campaign
WHERE segments.date BETWEEN '{since}' AND '{until}'
  AND metrics.impressions > 0
"""

ACCOUNTS_QUERY = """
SELECT customer_client.id, customer_client.descriptive_name,
       customer_client.currency_code, customer_client.status
FROM customer_client
WHERE customer_client.manager = false
"""


def get_env(name, required=True):
    value = os.getenv(name, "").strip()
    if required and not value:
        sys.exit(f"[오류] 환경변수 {name} 가 비어 있습니다.")
    return value


def clean_id(cid):
    return cid.replace("-", "").strip()


def make_client():
    return GoogleAdsClient.load_from_dict({
        "developer_token": get_env("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": get_env("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": get_env("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": get_env("GOOGLE_ADS_REFRESH_TOKEN"),
        "login_customer_id": clean_id(get_env("GOOGLE_ADS_LOGIN_CUSTOMER_ID")),
        "use_proto_plus": True,
    })


def explain(ex):
    msgs = [e.message for e in ex.failure.errors]
    return f"{'; '.join(msgs)} (request_id {ex.request_id})"


def money(value, currency):
    return round(value) if currency in ZERO_DECIMAL else round(value, 2)


def list_accounts(client):
    svc = client.get_service("GoogleAdsService")
    mcc = clean_id(get_env("GOOGLE_ADS_LOGIN_CUSTOMER_ID"))
    print("\n[MCC 하위 광고계정]")
    for row in svc.search(customer_id=mcc, query=ACCOUNTS_QUERY):
        c = row.customer_client
        print(f"  {c.id}  {c.currency_code}  {c.status.name:<10} {c.descriptive_name}")


def fetch(client, customer_id, since, until):
    svc = client.get_service("GoogleAdsService")
    rows = []
    stream = svc.search_stream(customer_id=customer_id, query=QUERY.format(since=since, until=until))
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    for batch in stream:
        for r in batch.results:
            cur = r.customer.currency_code
            cost = r.metrics.cost_micros / 1_000_000
            clicks = r.metrics.clicks
            imps = r.metrics.impressions
            conv = r.metrics.conversions
            val = r.metrics.conversions_value
            rows.append({
                "날짜": r.segments.date,
                "계정ID": str(r.customer.id),
                "계정명": r.customer.descriptive_name,
                "캠페인ID": str(r.campaign.id),
                "캠페인명": r.campaign.name,
                "캠페인유형": r.campaign.advertising_channel_type.name,
                "통화": cur,
                "노출수": imps,
                "클릭수": clicks,
                "CTR(%)": round(clicks / imps * 100, 2) if imps else 0,
                "광고비": money(cost, cur),
                "CPC": money(cost / clicks, cur) if clicks else 0,
                "전환수": round(conv, 2),
                "전환가치": money(val, cur),
                "ROAS(%)": round(val / cost * 100, 1) if cost else 0,
                "CPA": money(cost / conv, cur) if conv else 0,
                "수집시각": now,
            })
    return rows


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def upsert_sheet(new_rows, since, until, done_ids):
    import gspread

    gc = gspread.service_account_from_dict(json.loads(get_env("GCP_SA_KEY")))
    sh = gc.open_by_key(get_env("SHEET_ID"))
    tab = os.getenv("GOOGLE_SHEET_TAB", "google_daily").strip() or "google_daily"
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
        a = agg[f"{r['계정명'] or r['계정ID']} ({r['통화']})"]
        for k in a:
            a[k] += r[k]
    lines = [f"### Google Ads 리포트 {since} ~ {until}", "",
             "| 계정 | 광고비 | 클릭 | 전환 | 전환가치 | ROAS |",
             "|---|---:|---:|---:|---:|---:|"]
    for name, a in agg.items():
        roas = f"{a['전환가치'] / a['광고비'] * 100:.0f}%" if a["광고비"] else "-"
        lines.append(f"| {name} | {a['광고비']:,.2f} | {a['클릭수']:,} | "
                     f"{a['전환수']:,.1f} | {a['전환가치']:,.2f} | {roas} |")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    today = datetime.now(KST).date()
    p = argparse.ArgumentParser()
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--list-accounts", action="store_true")
    args = p.parse_args()
    since = args.since or (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    until = args.until or (args.since if args.since else (today - timedelta(days=1)).isoformat())

    try:
        client = make_client()
    except Exception as ex:
        sys.exit(f"[인증 실패] 클라이언트 ID/보안 비밀/갱신 토큰을 확인하세요: {ex}")

    if args.list_accounts:
        try:
            list_accounts(client)
        except GoogleAdsException as ex:
            sys.exit(f"[계정 목록 조회 실패] {explain(ex)}")
        return

    ids = [clean_id(c) for c in get_env("GOOGLE_ADS_CUSTOMER_IDS").split(",") if c.strip()]
    print(f"기간 {since} ~ {until} / 계정 {len(ids)}개")

    rows, done, failed = [], set(), []
    for cid in ids:
        try:
            r = fetch(client, cid, since, until)
            rows.extend(r)
            done.add(cid)
            print(f"  ✓ {cid}: {len(r)}행")
        except GoogleAdsException as ex:
            failed.append(cid)
            print(f"  ✗ {cid}: {explain(ex)}")
        except Exception as ex:
            failed.append(cid)
            print(f"  ✗ {cid}: {ex}")

    if rows:
        Path("reports").mkdir(exist_ok=True)
        out = Path("reports") / f"google_{since}_{until}.csv"
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

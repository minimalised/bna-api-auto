#!/usr/bin/env python3
"""
Google Ads 캠페인 성과 + Google Channel Purchase 구매 → 구글 시트 적재 (최근 N일 upsert) + CSV 백업

환경변수
  GOOGLE_ADS_DEVELOPER_TOKEN     : MCC API 센터의 개발자 토큰
  GOOGLE_ADS_CLIENT_ID           : OAuth 클라이언트 ID
  GOOGLE_ADS_CLIENT_SECRET       : OAuth 클라이언트 보안 비밀
  GOOGLE_ADS_REFRESH_TOKEN       : OAuth 갱신 토큰
  GOOGLE_ADS_LOGIN_CUSTOMER_ID   : MCC 고객 ID (하이픈 없이)
  GOOGLE_ADS_CUSTOMER_IDS        : 조회할 광고계정 ID, 쉼표 구분 (하이픈 있어도 됨)
  GCP_SA_KEY, SHEET_ID           : 메타와 동일한 시트 사용
  GOOGLE_SHEET_TAB               : 기본 google_purchase_daily

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
LOOKBACK_DAYS = 30  # 재조회 기본값. 실제 계정의 전환 기간과 지연에 맞춰 조정.
ZERO_DECIMAL = {"KRW", "JPY", "VND", "TWD", "CLP", "ISK", "HUF"}

from google_purchase import fetch_purchase

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
    return fetch_purchase(client, customer_id, since, until)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def upsert_sheet(new_rows, since, until, done_ids):
    import gspread

    gc = gspread.service_account_from_dict(json.loads(get_env("GCP_SA_KEY")))
    sh = gc.open_by_key(get_env("SHEET_ID"))
    tab = os.getenv("GOOGLE_SHEET_TAB", "google_purchase_daily").strip() or "google_purchase_daily"
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=1000, cols=30)

    values = ws.get_values(value_render_option="UNFORMATTED_VALUE")
    old_header = values[0] if values else []
    if old_header and "구매전환리소스" not in old_header:
        raise ValueError("기존 전체 전환 탭에 구매 데이터를 혼합할 수 없습니다. 새 탭을 사용하세요.")
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
    # Grow before writing; clear obsolete trailing rows only after a successful write.
    ws.resize(rows=max(ws.row_count, len(out), 2), cols=max(ws.col_count, len(header), 1))
    ws.update(out, "A1", value_input_option="RAW")
    if len(values) > len(out):
        end_cell = gspread.utils.rowcol_to_a1(len(values), len(header))
        ws.batch_clear([f"A{len(out)+1}:{end_cell}"])
    ws.freeze(rows=1)
    print(f"\n시트 적재 완료: '{tab}' 탭 / 교체 {removed}행 → 신규 {len(new_rows)}행 / 전체 {len(merged)}행")


def write_summary(rows, since, until):
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path or not rows:
        return
    agg = defaultdict(lambda: {"광고비": 0, "클릭수": 0, "구매수": 0, "구매매출": 0})
    for r in rows:
        a = agg[f"{r['계정명'] or r['계정ID']} ({r['통화']})"]
        for k in a:
            a[k] += r[k]
    lines = [f"### Google Ads 리포트 {since} ~ {until}", "",
             "| 계정 | 광고비 | 클릭 | 구매 | 구매매출 | ROAS |",
             "|---|---:|---:|---:|---:|---:|"]
    for name, a in agg.items():
        roas = f"{a['구매매출'] / a['광고비'] * 100:.0f}%" if a["광고비"] else "-"
        lines.append(f"| {name} | {a['광고비']:,.2f} | {a['클릭수']:,} | "
                     f"{a['구매수']:,.1f} | {a['구매매출']:,.2f} | {roas} |")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    today = datetime.now(KST).date()
    p = argparse.ArgumentParser()
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--list-accounts", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="API 조회와 CSV만 생성, 시트 변경 없음")
    args = p.parse_args()
    since = args.since or (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    until = args.until or (args.since if args.since else (today - timedelta(days=1)).isoformat())

    if not args.list_accounts:
        try:
            since = datetime.strptime(since, "%Y-%m-%d").date().isoformat()
            until = datetime.strptime(until, "%Y-%m-%d").date().isoformat()
        except ValueError:
            p.error("날짜는 YYYY-MM-DD 형식이어야 합니다.")
        if since > until or until >= today.isoformat():
            p.error("시작일 ≤ 종료일 < 오늘(KST)이어야 합니다.")

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
        out = Path("reports") / f"google_purchase_{since}_{until}.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV 저장: {out} ({len(rows)}행)")
        write_summary(rows, since, until)

    if not args.dry_run and get_env("SHEET_ID", required=False) and done:
        upsert_sheet(rows, since, until, done)

    if failed:
        sys.exit(f"실패 계정: {', '.join(failed)}")


if __name__ == "__main__":
    main()

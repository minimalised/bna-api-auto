#!/usr/bin/env python3
"""
Meta Ads 인사이트 → CSV 리포트 (GitHub Actions용)

환경변수
  META_ACCESS_TOKEN  : 시스템 유저 토큰 (필수)
  META_ACCOUNT_IDS   : 광고계정 ID, 쉼표 구분. act_ 생략 가능 (필수)
  META_API_VERSION   : 기본 v24.0

사용법
  python meta_report.py                          # 어제(KST) 데이터
  python meta_report.py --since 2026-09-01 --until 2026-09-22
  python meta_report.py --list-actions           # 계정에 실제로 잡히는 action_type 확인
"""
import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API_VERSION = os.getenv("META_API_VERSION", "v24.0")
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"
KST = timezone(timedelta(hours=9))

# 리포트에 넣을 전환 이벤트 (컬럼명: action_type)
# 계정마다 실제 값이 다를 수 있으니 --list-actions 결과를 보고 수정하세요.
CONVERSIONS = {
    "구매": "offsite_conversion.fb_pixel_purchase",
    "장바구니": "offsite_conversion.fb_pixel_add_to_cart",
    "리드": "offsite_conversion.fb_pixel_lead",
    "랜딩페이지조회": "landing_page_view",
}
PURCHASE_VALUE_TYPE = "offsite_conversion.fb_pixel_purchase"

FIELDS = [
    "account_id", "account_name", "account_currency", "campaign_id", "campaign_name",
    "date_start", "date_stop",
    "impressions", "reach", "frequency",
    "inline_link_clicks", "inline_link_click_ctr",
    "spend", "cpm", "actions", "action_values",
]

# 호출 제한·일시 오류 → 재시도
RETRY_CODES = {1, 2, 4, 17, 32, 613, 80000, 80003, 80004}


def get_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"[오류] 환경변수 {name} 가 비어 있습니다.")
    return value


def normalize_account(acc):
    acc = acc.strip()
    return acc if acc.startswith("act_") else f"act_{acc}"


def api_get(url, params=None, max_retry=5):
    for attempt in range(max_retry):
        r = requests.get(url, params=params, timeout=90)
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.ok and "error" not in data:
            return data
        err = data.get("error", {})
        code = err.get("code")
        if code in RETRY_CODES and attempt < max_retry - 1:
            wait = 30 * (attempt + 1)
            print(f"  ↻ 호출 제한/일시 오류(code {code}) → {wait}초 후 재시도")
            time.sleep(wait)
            continue
        msg = err.get("error_user_msg") or err.get("message") or r.text[:300]
        raise RuntimeError(f"API 오류 (code {code}): {msg}")
    raise RuntimeError("재시도 횟수 초과")


def fetch_insights(account_id, token, since, until):
    url = f"{BASE_URL}/{account_id}/insights"
    params = {
        "access_token": token,
        "level": "campaign",
        "fields": ",".join(FIELDS),
        "time_range": f'{{"since":"{since}","until":"{until}"}}',
        "time_increment": 1,  # 일자별
        "action_attribution_windows": '["7d_click","1d_view"]',
        "limit": 500,
    }
    rows = []
    while url:
        data = api_get(url, params)
        rows.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = None  # next URL에 파라미터가 이미 포함됨
    return rows


def num(value, cast=float):
    try:
        return cast(float(value))
    except (TypeError, ValueError):
        return cast(0)


def pick(action_list, action_type):
    if not action_list:
        return 0.0
    return sum(num(a.get("value")) for a in action_list if a.get("action_type") == action_type)


ZERO_DECIMAL = {"KRW", "JPY", "VND", "TWD", "CLP", "ISK", "HUF"}


def money(value, currency):
    return round(value) if currency in ZERO_DECIMAL else round(value, 2)


def build_row(d):
    cur = d.get("account_currency") or ""
    spend = num(d.get("spend"))
    clicks = num(d.get("inline_link_clicks"), int)
    purchases = pick(d.get("actions"), CONVERSIONS["구매"])
    purchase_value = pick(d.get("action_values"), PURCHASE_VALUE_TYPE)

    row = {
        "날짜": d.get("date_start"),
        "계정ID": d.get("account_id"),
        "계정명": d.get("account_name"),
        "캠페인ID": d.get("campaign_id"),
        "캠페인명": d.get("campaign_name"),
        "통화": cur,
        "노출수": num(d.get("impressions"), int),
        "도달수": num(d.get("reach"), int),
        "빈도": round(num(d.get("frequency")), 2),
        "링크클릭수": clicks,
        "링크CTR(%)": round(num(d.get("inline_link_click_ctr")), 2),
        "광고비": money(spend, cur),
        "CPM": money(num(d.get("cpm")), cur),
        "링크CPC": money(spend / clicks, cur) if clicks else 0,
    }
    for col, action_type in CONVERSIONS.items():
        row[col] = int(pick(d.get("actions"), action_type))
    row["구매가치"] = money(purchase_value, cur)
    row["ROAS(%)"] = round(purchase_value / spend * 100, 1) if spend else 0
    row["구매CPA"] = money(spend / purchases, cur) if purchases else 0
    return row


def list_actions(raw_rows):
    counts = defaultdict(float)
    for d in raw_rows:
        for a in d.get("actions") or []:
            counts[a.get("action_type")] += num(a.get("value"))
    print("\n[action_type 목록] (합계 내림차순)")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {v:>12,.0f}  {k}")


def write_summary(rows, since, until):
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path or not rows:
        return
    agg = defaultdict(lambda: {"광고비": 0, "링크클릭수": 0, "구매": 0, "구매가치": 0})
    for r in rows:
        a = agg[f"{r['계정명'] or r['계정ID']} ({r['통화']})"]
        for k in a:
            a[k] += r[k]
    lines = [f"### Meta 리포트 {since} ~ {until}", "",
             "| 계정 | 광고비 | 링크클릭 | 구매 | 구매가치 | ROAS |",
             "|---|---:|---:|---:|---:|---:|"]
    for name, a in agg.items():
        roas = f"{a['구매가치'] / a['광고비'] * 100:.0f}%" if a["광고비"] else "-"
        lines.append(f"| {name} | {a['광고비']:,.2f} | {a['링크클릭수']:,} | "
                     f"{a['구매']:,} | {a['구매가치']:,.2f} | {roas} |")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    yesterday = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=yesterday)
    p.add_argument("--until", default=None)
    p.add_argument("--list-actions", action="store_true")
    args = p.parse_args()
    since, until = args.since, args.until or args.since

    token = get_env("META_ACCESS_TOKEN")
    accounts = [normalize_account(a) for a in get_env("META_ACCOUNT_IDS").split(",") if a.strip()]
    print(f"기간 {since} ~ {until} / 계정 {len(accounts)}개 / API {API_VERSION}")

    raw_all, rows, failed = [], [], []
    for acc in accounts:
        try:
            raw = fetch_insights(acc, token, since, until)
            raw_all.extend(raw)
            rows.extend(build_row(d) for d in raw)
            print(f"  ✓ {acc}: {len(raw)}행")
        except Exception as e:
            failed.append(acc)
            print(f"  ✗ {acc}: {e}")

    if args.list_actions:
        list_actions(raw_all)

    if rows:
        out_dir = Path("reports")
        out_dir.mkdir(exist_ok=True)
        out = out_dir / f"meta_{since}_{until}.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
        print(f"\n저장 완료: {out} ({len(rows)}행)")
        write_summary(rows, since, until)
    else:
        print("\n저장할 데이터가 없습니다.")

    if failed:
        sys.exit(f"실패 계정: {', '.join(failed)}")


if __name__ == "__main__":
    main()

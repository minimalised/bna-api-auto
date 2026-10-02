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
  GOOGLE_SHEET_TAB               : 새 RAW v2 탭 사용

사용법
  python google_report.py                     # 전일자 수집 → RAW 추가/갱신
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
LOOKBACK_DAYS = 1  # 재조회 기본값. 실제 계정의 전환 기간과 지연에 맞춰 조정.
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


from raw_store import period, summary, save, day_scopes, SUMMARY_HEADER, SUMMARY_DIMS


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--since')
    p.add_argument('--until')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--list-accounts', action='store_true')
    args = p.parse_args()
    since, until = period(args.since, args.until)
    client = make_client()
    if args.list_accounts:
        list_accounts(client)
        return
    rows, done, failures = [], [], []
    for cid in dict.fromkeys(clean_id(x) for x in get_env('GOOGLE_ADS_CUSTOMER_IDS').split(',') if x.strip()):
        try:
            collected = fetch(client, cid, since, until)
            rows.extend(collected)
            done.append(cid)
        except Exception as ex:
            failures.append(cid)
            print(f'계정 수집 실패: {type(ex).__name__}')
    # Stable header also handles a successful empty date range.
    header = ['날짜','계정ID','계정명','캠페인ID','캠페인명','캠페인유형','통화','계정시간대',
              '노출수','클릭수','비용','전환수','전환매출액','구매전환명','구매전환리소스',
              '구매전환상태','전환지표기준','일자기준','수집시각']
    scopes = day_scopes(done, since, until)
    outdir = Path('reports') / f'google_v2_{since}_{until}'
    normalized = [dict(r, 매체='google', 광고상품=r['캠페인유형'], 전환기준='구매', 클릭기준='클릭') for r in rows]
    errors = []
    for tab, h, data, keys in [
        ('google_campaign_daily_v2', header, rows, ['계정ID','날짜','캠페인ID']),
        ('google_summary_daily_v2', SUMMARY_HEADER, summary(normalized), SUMMARY_DIMS),
    ]:
        try:
            save(tab,h,data,scopes,keys,args.dry_run,outdir)
        except Exception as e:
            errors.append(tab)
            print(f'{tab}: 저장 실패 ({type(e).__name__})')
    print(f'{since} ~ {until}: 캠페인 {len(rows)}행, dry_run={args.dry_run}')
    if failures or errors:
        raise SystemExit('일부 수집/저장 실패. 실패 범위는 재조회가 필요합니다.')


if __name__ == '__main__':
    main()

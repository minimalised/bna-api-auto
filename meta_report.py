#!/usr/bin/env python3
"""
Meta Ads 인사이트 → 구글 시트 적재 (최근 N일 upsert) + CSV 백업

환경변수
  META_ACCESS_TOKEN  : 시스템 유저 토큰 (필수)
  META_ACCOUNT_IDS   : 광고계정 ID, 쉼표 구분. act_ 생략 가능 (필수)
  GCP_SA_KEY         : 서비스 계정 JSON 키 내용 (시트 적재 시 필수)
  SHEET_ID           : 구글 시트 ID (없으면 CSV만 저장)
  SHEET_TAB          : 적재할 탭 이름 (새 RAW v2 탭 사용)
  META_API_VERSION   : 기본 v24.0

사용법
  python meta_report.py                          # 전일자 수집 → RAW 추가/갱신
  python meta_report.py --since 2026-09-01 --until 2026-09-22   # 과거 기간 백필
  python meta_report.py --list-actions           # 실제 action_type 확인
"""
import argparse
import csv
import json
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
LOOKBACK_DAYS = 1  # 7일 클릭 어트리뷰션 소급 반영 기간

# 리포트에 넣을 전환 이벤트 (컬럼명: action_type)
# --list-actions 결과를 보고 광고관리자 숫자와 맞는 이름으로 수정하세요.
CONVERSIONS = {'구매': 'offsite_conversion.fb_pixel_purchase'}
PURCHASE_VALUE_TYPE = CONVERSIONS['구매']
FIELDS = ['account_id','account_name','account_currency','campaign_id','campaign_name',
          'date_start','date_stop','impressions','inline_link_clicks','spend','actions','action_values']

RETRY_CODES = {1, 2, 4, 17, 32, 613, 80000, 80003, 80004}
ZERO_DECIMAL = {"KRW", "JPY", "VND", "TWD", "CLP", "ISK", "HUF"}


# ───────────────────────── Meta API ─────────────────────────
def get_env(name, required=True):
    value = os.getenv(name, "").strip()
    if required and not value:
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


def fetch_insights(account_id, token, since, until, level="campaign"):
    url = f"{BASE_URL}/{account_id}/insights"
    params = {
        "access_token": token,
        "level": level,
        "fields": ",".join(FIELDS + (["adset_id","adset_name","ad_id","ad_name"] if level == "ad" else [])),
        "time_range": json.dumps({"since": since, "until": until}),
        "time_increment": 1,
        "action_attribution_windows": '["7d_click","1d_view"]',
        "limit": 500,
    }
    rows = []
    while url:
        data = api_get(url, params)
        rows.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = None
    return rows



from raw_store import period, summary, save, day_scopes, SUMMARY_HEADER, SUMMARY_DIMS, METRICS

DIMS = ['날짜','매체','계정ID','계정명','광고상품','통화','전환기준','클릭기준','캠페인ID','캠페인명']
AD_DIMS = ['광고그룹ID','광고그룹명','광고ID','광고명']


def pick(items, name):
    return sum(float(x['value']) for x in (items or []) if x.get('action_type') == name)


def build_row(d, level):
    row = dict(zip(DIMS, [d['date_start'],'meta',str(d['account_id']),d.get('account_name',''),
        'Meta Ads', d['account_currency'],'구매','링크클릭',str(d['campaign_id']),d.get('campaign_name','')]))
    if level == 'ad':
        row.update(zip(AD_DIMS,[str(d['adset_id']),d.get('adset_name',''),str(d['ad_id']),d.get('ad_name','')]))
    row.update(dict(zip(METRICS,[int(d['impressions']),int(d.get('inline_link_clicks',0)),
        float(d['spend']),pick(d.get('actions'),PURCHASE_VALUE_TYPE),pick(d.get('action_values'),PURCHASE_VALUE_TYPE)])))
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--since')
    p.add_argument('--until')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--list-actions', action='store_true')
    args = p.parse_args()
    since, until = period(args.since,args.until)
    token = get_env('META_ACCESS_TOKEN')
    accounts = list(dict.fromkeys(normalize_account(a) for a in get_env('META_ACCOUNT_IDS').split(',') if a.strip()))
    outdir = Path('reports') / f'meta_v2_{since}_{until}'
    errors = []
    for level in ('campaign','ad'):
        rows, done = [], []
        for account in accounts:
            try:
                raw = fetch_insights(account,token,since,until,level)
                collected = [build_row(d,level) for d in raw]
                if args.list_actions:
                    print('action types:', sorted({a['action_type'] for d in raw for a in d.get('actions',[])}))
                rows.extend(collected)
                done.append(account)
            except Exception as e:
                errors.append((level,account))
                print(f'{level}: 계정 수집 실패 ({type(e).__name__})')
        scopes=day_scopes(done,since,until)
        h=DIMS+(AD_DIMS if level=='ad' else [])+METRICS
        outputs=[('meta_'+level+'_daily_v2', h, rows, ['계정ID','날짜','광고ID' if level=='ad' else '캠페인ID'])]
        if level=='campaign':
            outputs.append(('meta_summary_daily_v2',SUMMARY_HEADER,summary(rows),SUMMARY_DIMS))
        for tab,header,data,keys in outputs:
            try:
                save(tab,header,data,scopes,keys,args.dry_run or args.list_actions,outdir)
            except Exception as e:
                errors.append((tab,'write'))
                print(f'{tab}: 저장 실패 ({type(e).__name__})')
        print(f'{level}: {since} ~ {until}, {len(rows)}행, dry_run={args.dry_run or args.list_actions}')
    if errors:
        raise SystemExit('일부 수집/저장 실패. 실패 범위는 재조회가 필요합니다.')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
리포트 탭 초기화 (백필 전 1회용). 지우기 전에 각 탭을 CSV로 reports/에 백업합니다.

대상: 메타·구글 RAW·성별연령기기 탭, 네이버 RAW 5종, 통합 탭. 그 밖의 탭은 건드리지 않습니다.
탭 자체는 남기고 내용만 지우므로, 다른 탭의 수식 참조(#REF!)가 깨지지 않습니다.

환경변수: GCP_SA_KEY, SHEET_ID (+ 매체 스크립트와 같은 탭 이름 설정)

사용법
  python reset_sheet.py            # 대상 탭과 행 수만 출력
  python reset_sheet.py --confirm  # 백업 후 실제로 지움
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
NAVER_REPORTS = ("campaign", "search", "media", "gender", "age")


def env(name, default=None):
    value = os.getenv(name, "").strip()
    return value or default


def target_tabs():
    naver = env("NAVER_RAW_PREFIX", "naver_raw")
    prefix = env("REPORT_TAB_PREFIX", "통합")
    return ([env("SHEET_TAB", "meta_daily"), env("GOOGLE_SHEET_TAB", "google_daily"),
             env("META_BREAKDOWN_TAB", "meta_breakdown"), env("GOOGLE_BREAKDOWN_TAB", "google_breakdown")]
            + [f"{naver}_{r}" for r in NAVER_REPORTS]
            + [f"{prefix}_{p}" for p in ("일별", "주간", "월간")])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirm", action="store_true", help="백업 후 실제로 지움")
    args = p.parse_args()

    import gspread
    key, sheet_id = env("GCP_SA_KEY"), env("SHEET_ID")
    if not key or not sheet_id:
        sys.exit("[오류] GCP_SA_KEY, SHEET_ID 환경변수가 필요합니다.")
    sh = gspread.service_account_from_dict(json.loads(key)).open_by_key(sheet_id)

    outdir = Path("reports") / f"reset_backup_{datetime.now(KST):%Y%m%dT%H%M%S}"
    outdir.mkdir(parents=True, exist_ok=True)
    existing = {ws.title: ws for ws in sh.worksheets()}
    for tab in target_tabs():
        ws = existing.get(tab)
        if ws is None:
            print(f"{tab}: 없음")
            continue
        values = ws.get_values(value_render_option="UNFORMATTED_VALUE")
        with open(outdir / f"{tab}.csv", "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(values)
        if args.confirm:
            ws.clear()
        print(f"{tab}: 데이터 {max(len(values) - 1, 0)}행 {'백업 후 삭제' if args.confirm else '(확인만, 삭제 안 함)'}")
    print(f"백업: {outdir}")


if __name__ == "__main__":
    main()

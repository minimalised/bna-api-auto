#!/usr/bin/env python3
"""
시트 탭 정리. 자동화가 쓰는 탭은 지우지 않고, 지정한 탭만 CSV로 백업한 뒤 삭제합니다.

환경변수: GCP_SA_KEY, SHEET_ID (+ 매체 스크립트와 같은 탭 이름 설정)

사용법
  python cleanup_tabs.py                                  # 탭 목록과 자동화 사용 여부만 출력
  python cleanup_tabs.py --delete "시트1,old_raw" --confirm  # 백업 후 해당 탭 삭제
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reset_sheet import NAVER_REPORTS, env

KST = timezone(timedelta(hours=9))


def pipeline_tabs():
    naver = env("NAVER_RAW_PREFIX", "naver_raw")
    prefix = env("REPORT_TAB_PREFIX", "통합")
    return ({env("SHEET_TAB", "meta_daily"), env("GOOGLE_SHEET_TAB", "google_daily"),
             env("META_BREAKDOWN_TAB", "meta_breakdown"), env("GOOGLE_BREAKDOWN_TAB", "google_breakdown"),
             env("BRAND_SEARCH_TAB", "브랜드검색_결제")}
            | {f"{naver}_{r}" for r in NAVER_REPORTS}
            | {f"{prefix}_{p}" for p in ("일별", "주간", "월간", "대시보드")})


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--delete", default="", help="삭제할 탭 이름, 쉼표로 구분")
    p.add_argument("--confirm", action="store_true", help="백업 후 실제로 삭제")
    args = p.parse_args()

    import gspread
    key, sheet_id = env("GCP_SA_KEY"), env("SHEET_ID")
    if not key or not sheet_id:
        sys.exit("[오류] GCP_SA_KEY, SHEET_ID 환경변수가 필요합니다.")
    sh = gspread.service_account_from_dict(json.loads(key)).open_by_key(sheet_id)

    keep = pipeline_tabs()
    tabs = sh.worksheets()
    print("| 탭 | 값이 있는 행 | 자동화 사용 |\n|---|---:|---|")
    for ws in tabs:
        n = len(ws.col_values(1))
        print(f"| {ws.title} | {n} | {'사용' if ws.title in keep else '-'} |")

    targets = [t.strip() for t in args.delete.split(",") if t.strip()]
    if not targets:
        return
    by_title = {ws.title: ws for ws in tabs}
    missing = [t for t in targets if t not in by_title]
    protected = [t for t in targets if t in keep]
    if missing or protected:
        sys.exit(f"[중단] 없는 탭 {missing} / 자동화가 쓰는 탭 {protected}는 지우지 않습니다.")
    if len(targets) >= len(tabs):
        sys.exit("[중단] 시트에는 탭이 하나 이상 남아야 합니다.")

    outdir = Path("reports") / f"cleanup_backup_{datetime.now(KST):%Y%m%dT%H%M%S}"
    outdir.mkdir(parents=True, exist_ok=True)
    for t in targets:
        values = by_title[t].get_values(value_render_option="UNFORMATTED_VALUE")
        with open(outdir / f"{t}.csv", "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(values)
        if args.confirm:
            sh.del_worksheet(by_title[t])
        print(f"{t}: {len(values)}행 {'백업 후 삭제' if args.confirm else '백업만 (삭제 안 함)'}")
    print(f"백업: {outdir}")


if __name__ == "__main__":
    main()

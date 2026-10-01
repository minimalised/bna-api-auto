# Google Channel Purchase 수집 적용

사용자 지정 구매 전환명: **Google Channel Purchase** (대소문자·공백 포함 정확히 일치).

전환 관리 계정(customer.conversion_tracking_setting.google_ads_conversion_customer)에서 이름에 해당하는 리소스 ID를 찾고 해당 ID의 metrics.conversions / metrics.conversions_value만 수집한다. 기존 보고의 '전환수' 정의를 이어받으며 '모든 전환' 지표와는 다르다. 보조 전환 또는 캠페인 목표 설정에 따라 이 값이 0일 수 있으므로 관리자에서도 같은 전환 액션의 '전환수/전환가치' 열로 대조한다. 자동으로 all_conversions에 대체하지 않는다.

캠페인 광고비·노출·클릭과 구매는 별도 요청하여 계정/날짜/캠페인으로 연결한다. 구매만 있는 행도 보존하고, 소수 전환·비용·매출은 반올림하지 않는다. 전환 관리 계정 접근 실패·이름 없음·중복은 해당 계정 수집 실패이며 기존 시트 행은 보존한다. 현재 전환 관리 계정의 액션을 기준으로 하므로 관리 계정을 바꾼 과거 기간은 별도 검증한다.

기본 탭은 **google_purchase_daily**. 기존 google_daily에는 전체 전환이 있으므로 섞지 않는다. 이전 기간이 필요하면 명시적으로 백필하고 Looker Studio 데이터 소스를 새 탭으로 연결한다. 기존 시트 탭을 새 지표로 자동 전환하지 않는다. 주간/월간 CPA·ROAS는 구매수·구매매출·광고비 합계로 재계산한다.

## 검증 실행

기존 Secrets를 사용하는 Google Ads Daily Report workflow에서 dry_run=true로 시작일/종료일을 지정하여 실행한다. 수동 실행 기본값은 dry-run이고 스케줄 실행은 구매 탭에 적재한다. 코드가 main에 병합되기 전에는 기존 스케줄이 유지된다.

CLI:

```bash
python google_report.py --since 2026-09-30 --until 2026-09-30 --dry-run
python -m unittest discover -s tests -v
```

CSV에서 구매전환명·구매전환리소스·전환지표기준·계정시간대를 확인하고 Google Ads 관리자와 비교한다. 날짜는 계정 기준 광고 상호작용일이며 전환 발생일 보고서가 아니다. 검증 후 dry_run=false로 적재한다. 30일 재조회는 기본값이며 전환 기간·지연이 더 길면 백필 기간을 늘린다.

## 검증 범위

단위 테스트: 광고비 중복 방지, 소수 구매 유지, 구매만/비용만 있는 행, 중복·잘못된 액션 차단, MCC 전환 관리 계정, 이름 불일치/모호성, 조회 분리, API 실패시 부분 결과 차단, 날짜 순서 검증. 실제 광고 API 호출과 Google Sheets 적재는 아직 검증하지 않았다.

공식 문서:
- https://developers.google.com/google-ads/api/docs/conversions/reporting
- https://developers.google.com/google-ads/api/docs/conversions/getting-started


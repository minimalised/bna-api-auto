# BNA 광고 보고서 자동화

코드가 업데이트되어도 기존 스프레드시트와 탭, 워크플로우 이름을 그대로 사용합니다.
버전별 탭을 만들지 않습니다.

## 고정 저장 위치

| 매체 | 보고서 | 기존 탭 |
|---|---|---|
| 네이버 | 캠페인 RAW | naver_raw_campaign |
| 네이버 | 검색어 RAW | naver_raw_search |
| 네이버 | 매체 RAW | naver_raw_media |
| 메타 | 캠페인 RAW | meta_daily |
| 구글 | 캠페인 RAW | google_daily |

네이버는 NAVER_RAW_PREFIX, 메타는 SHEET_TAB, 구글은 GOOGLE_SHEET_TAB으로 기존 탭 이름을 지정할 수 있습니다.
기본값은 위 표와 같습니다. 모든 보고서는 기존 SHEET_ID의 스프레드시트를 사용합니다.

기존 summary 탭(naver_summary_daily, meta_summary_daily, google_summary_daily)과
메타 광고 RAW 탭(meta_ad_daily)이 있으면 해당 탭에 저장합니다.
없으면 CSV만 생성하며 탭을 자동으로 만들지 않습니다.
기존 캠페인/검색어/매체 탭이 없으면 이름을 확인하도록 오류를 내고 새 탭 생성은 하지 않습니다.
이미 생성된 버전별 탭을 자동 삭제하지 않습니다.

## 업데이트와 이력

기존 탭의 컬럼 이름과 순서를 유지합니다. 날짜/계정/캠페인 등 필요한 컬럼이 없는 경우에만 같은 탭에 컬럼을 추가합니다.
일별/날짜, 총비용/광고비/비용, 구매/구매완료 전환수/전환수 등 기존 이름을 대응하여 저장합니다.
조회에 성공한 계정·날짜의 행만 교체하고 다른 기간 및 실패 계정의 기록은 유지합니다.
쓰기 전에 기존 데이터를 CSV로 백업합니다. Sheets 쓰기는 여러 요청으로 이루어지므로 중간 실패 시 같은 기간을 재실행합니다.
구글 과거 행의 전환은 기존 수집 기준 그대로 보존되며 구매 기준으로 자동 변환되지 않습니다.

## 수집 기준

성과 지표는 노출수, 클릭수, 비용, 구매 전환수, 구매 전환매출액입니다.
네이버 성별·연령은 수집하지 않습니다. 파워링크 검색어의 구매 지표는 API 미제공으로 빈칸입니다.
메타는 링크클릭, 픽셀 구매 기준이며 소수 구매수를 유지합니다.
구글은 Google Channel Purchase 전환 액션의 metrics.conversions와 metrics.conversions_value를 수집합니다.
네이버 GFA, 구글 검색어·자산 상세, 메타 소재 미리보기는 아직 구현되지 않았습니다.

## 실행

기존 Naver SearchAd Daily Report, Meta Ads Daily Report, Google Ads Daily Report 워크플로우를 그대로 사용합니다.
정기 실행은 전일자 조회이며 Meta 08:00, Google 08:10, Naver 08:20 KST입니다.
수동 dry_run=true는 API 조회와 CSV 생성만 합니다. 실제 저장은 false로 실행합니다.
공유 시트 쓰기는 같은 concurrency 그룹으로 직렬화합니다.
지연 전환은 since/until로 기간을 재조회해 보정합니다.

## 검증

python -m unittest discover -s tests -v

기존 탭 이름 대응, 기존 헤더·과거 데이터 보존, 탭 생성 차단, 구매 필터, 실패 범위 보존,
재실행 중복 방지 및 보고서 컬럼 투영을 검증합니다.

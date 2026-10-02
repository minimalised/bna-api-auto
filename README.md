# BNA 광고 RAW v2

매일 한국시간 전일자만 수집합니다. 성별/연령은 수집하지 않습니다.
성과 지표는 **노출수, 클릭수, 비용, 전환수, 전환매출액**만 저장합니다.
전환은 구매만이며 날짜/ID/이름/통화/출처 등 분류 및 추적 정보는 유지합니다.
CTR, CPC, CPM, CPA, ROAS, 빈도, 도달수, 평균순위는 성과 RAW에 저장하지 않습니다.

## 저장 탭과 단위

| 탭 | 한 행의 단위 |
|---|---|
| naver_summary_daily_v2 | 날짜 × 계정 × 광고상품 |
| naver_campaign_daily_v2 | 날짜 × 계정 × 캠페인 |
| naver_search_daily_v2 | 날짜 × 계정 × 캠페인 × 광고그룹 × 검색어 |
| naver_media_daily_v2 | 날짜 × 계정 × 캠페인 × 광고그룹 × 기기 × 검색/콘텐츠 분류 |
| meta_summary_daily_v2 | 날짜 × 계정 (광고상품=Meta Ads) |
| meta_campaign_daily_v2 | 날짜 × 계정 × 캠페인 |
| meta_ad_daily_v2 | 날짜 × 계정 × 광고ID (광고/광고그룹 이름 포함) |
| google_summary_daily_v2 | 날짜 × 계정 × 광고상품(SEARCH/PERFORMANCE_MAX/DEMAND_GEN 등 API 유형) |
| google_campaign_daily_v2 | 날짜 × 계정 × 캠페인 |

summary 3종은 같은 컬럼을 사용합니다. 통합 대시보드는 이 세 탭을 세로로 합쳐 사용합니다.
성별/연령 옵션 및 호출은 제거했습니다. 예전 탭은 삭제하지 않습니다.
기존 탭의 계산 지표나 과거 집계 기준이 섞이지 않도록 새 v2 탭으로 시작합니다.

## 집계 규칙

- summary는 각 매체 캠페인 RAW에서만 생성합니다. 검색어/소재/매체 RAW를 summary에 합산하지 않습니다.
- 통합 summary 컬럼: 날짜, 매체, 계정ID, 계정명, 광고상품, 통화, 전환기준, 클릭기준 + 5개 지표.
- 네이버 계정명은 현재 API 수집 범위에 없으므로 빈칸이며 계정ID를 사용합니다.
- Meta 클릭수는 기존 기준인 링크클릭입니다. 원액을 반올림하지 않으며 구매수의 소수도 보존합니다.
- Google은 정확한 이름 `Google Channel Purchase`를 전환 관리 계정에서 확인하고 `metrics.conversions` 및 `metrics.conversions_value`만 수집합니다. 광고 상호작용일 기준입니다.
- API 미제공 지표는 빈칸입니다. 네이버 파워링크 검색어 구매수/매출은 미제공이며 0으로 바꾸지 않습니다.
- 서로 다른 통화는 합산하지 않습니다. 매체별 비용의 VAT 및 전환 귀속 기준은 원본 기준이며, 이 변경에서 재정의하지 않습니다.

Looker Studio 계산: CTR=SUM(클릭수)/SUM(노출수), CPC=SUM(비용)/SUM(클릭수), ROAS=SUM(전환매출액)/SUM(비용).
0인 분모는 null로 표시하고 CTR/ROAS는 퍼센트 형식을 적용합니다.
각 매체의 구매는 해당 매체의 귀속 전환이므로 여러 매체의 합계가 중복 제거된 실제 주문수는 아닙니다.

## 실행 및 보정

- 정기 실행: 네이버 08:20, Meta 08:00, Google 08:10 KST. 실제 GitHub 실행은 지연될 수 있습니다.
- 기본 수집 범위는 전일 하루입니다. 같은 계정/날짜 재실행 시 기존 범위를 교체하므로 중복 추가되지 않습니다.
- 조회가 실패한 계정/날짜/보고서의 기존 데이터는 보존합니다. 성공한 빈 응답은 해당 성공 범위의 기존 행을 제거합니다.
- 여러 워크플로의 시트 쓰기는 같은 concurrency 그룹으로 직렬화합니다.
- 수동 실행 기본은 dry_run=true이며 CSV만 생성합니다. 시트 반영을 원할 때만 false로 설정합니다.
- --since / --until로 원하는 기간을 재조회할 수 있습니다. 지연 전환 보정은 이 기간 재조회로 실행합니다. 별도 자동 보정 스케줄은 아직 추가하지 않았습니다.
- 네이버에서 reports=campaign 또는 all을 선택하면 summary도 생성됩니다. search/media 단독 실행은 summary를 변경하지 않습니다.
- 최초 반영 전 기존 기간을 dry-run으로 비교한 뒤 백필하세요. v2 탭에 기존 이력이 자동 이전되지는 않습니다.
- Sheets 쓰기는 여러 요청으로 나뉘므로 완전한 트랜잭션이 아닙니다. 쓰기 실패 시 Actions는 실패하고 before CSV를 남깁니다. 같은 기간을 재실행하세요.

## 범위와 남은 작업

- 네이버 GFA는 별도 API 연동이 필요하며 이 저장소의 검색광고 API에 포함되지 않습니다.
- Google 상세는 캠페인 단위입니다. 검색어/키워드, PMax 자산, Demand Gen 소재 상세는 아직 추가하지 않았습니다.
- Meta 소재별 성과는 광고ID/광고명 단위로 추가했습니다. 이미지/영상 미리보기 및 creative metadata 별도 수집은 아직 추가하지 않았습니다.
- Looker Studio 대시보드 자체와 통합 summary의 연결은 이 PR에서 생성하지 않습니다.
- 로컬 검증은 API 응답 모형과 저장 병합 테스트입니다. 변경된 세 매체의 실계정 dry-run 검증은 별도로 필요합니다.

## 테스트

`python -m unittest discover -s tests -v`

Google API 및 시트 적재 의존성은 requirements.txt, 네이버 조회 자체는 표준 라이브러리로 실행합니다.

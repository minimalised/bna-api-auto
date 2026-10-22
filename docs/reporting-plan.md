# BNA 광고 리포트 준비 설계 v1

검토일: 2026-10-01 (KST)
검토 기준: main / 00a01eb27ee521f7445c6b75630eaac1f360352b

## 목적과 범위

네이버 파워링크·쇼핑검색·브랜드검색·GFA, 메타 전환 캠페인, 구글 검색·P맥스·디멘드젠을 주간·월간 Looker Studio 리포트로 제공한다. 핵심 전환은 구매와 구매 매출이다. 메타는 소재 이미지·영상·카피를 성과 옆에서 확인하는 것이 필수다.

이 문서는 저장소 코드를 검토한 구현 설계다. API 제공 범위 인증이나 실데이터 검증 결과가 아니다. 아래의 "현재"는 코드가 요청·가공하도록 작성된 범위이며 실제 수집 성공을 의미하지 않는다. 신규 수집 단위와 필드 조합은 해당 API 공식 문서 및 작은 기간의 응답으로 검증한 후 구현한다.

## 1. 현재 구현 진단

| 항목 | 현재 코드 | 리포트 준비 시 조치 |
|---|---|---|
| 네이버 | naver_report.py: 캠페인·검색어·매체·성별·연령 5종 | 기존 RAW 유지하고 리포트용 컬럼을 별도 정규화 |
| 네이버 구매 | purchaseCcnt/purchaseConvAmt 및 conv_type=purchase | 광고 관리자와 구매 건수·매출 대조 |
| 네이버 성별·연령 | 쇼핑검색 광고그룹만, 각각 분리 수집; 최근 7일 밖은 건너뜀 | 화면에 적용 범위 표시; 두 표로 성별×연령을 추정하지 않음 |
| 네이버 검색어 | 파워링크 구매·매출은 빈칸, 쇼핑검색은 구매 포함 집계 | 파워링크 검색어 구매 CPA/ROAS 표시 금지 |
| 브랜드검색 | 캠페인 유형 이름 매핑은 존재, 별도 계약비 로직 없음 | 실제 비용 반환 및 구매 지원 확인; 계약비 필요 시 별도 원장 |
| GFA | 수집 코드와 workflow 없음 | 검색광고와 별도 수집기·인증·RAW 필요 |
| 메타 | level=campaign; 광고·광고세트 ID, 소재 및 인구통계 없음 | 광고 일별, 인구통계, 소재 사전 추가 |
| 메타 구매 | offsite_conversion.fb_pixel_purchase; 장바구니·리드 등도 함께 저장 | 보고 지표는 구매만 사용; 원본 action 목록은 보존 |
| 메타 기여 | 7d_click + 1d_view 명시; 일자 귀속 옵션은 미명시 | 보고 기준을 확정하고 계정·요청 메타정보 저장 |
| 구글 | FROM campaign; metrics.conversions/conversions_value | 현재 값을 구매로 이름만 바꾸면 안 됨. 구매 액션을 확정해 별도 추출 |
| 구글 상세 | 캠페인 유형은 있으나 검색어·광고·애셋그룹·상품·인구통계 없음 | 유형별로 수집 단위 분리 |
| 저장 | Google Sheets 누적 교체 + 가공 CSV, Actions artifact 보관 30일 | 장기 원본 보관과 수집 상태 기록 추가 |

코드상 정기 실행은 메타 08:00, 구글 08:10, 네이버 08:20 KST다. 메타는 최근 7일, 구글은 최근 30일, 네이버는 최근 14일을 재조회한다. 네이버 인구통계는 별도의 7일 제한 로직이 있다. 실제 정시 실행·API 지연·과거 재조회 허용 범위는 별도 운영 검증이 필요하다.

## 2. 데이터 계층

1. 원본 응답: API 응답 JSON/TSV를 요청 범위·API 버전·수집시각과 함께 장기 저장. 토큰, 인증 헤더, 서명 URL은 제외.
2. 분석별 RAW: 1행의 기준이 같은 데이터끼리 저장. 캠페인·소재·성별·연령 합계를 한 표에 중복 적재하지 않음.
3. Looker Studio용 표: 컬럼명, 구매 정의, 비용 기준을 맞춘 표. 서로 다른 분석 단위의 사실 테이블을 직접 조인하지 않음.

현 단계는 기존 Sheets를 계속 사용할 수 있다. 수집량과 전체 셀 수·갱신 시간을 측정한 뒤 BigQuery 전환을 판단한다. Actions artifact 30일은 장기 RAW 저장소로 간주하지 않는다. 광고 실적 원본은 공개 Git 저장소에 커밋하지 않는다.

## 3. 권장 RAW 목록

각 키에는 platform/account_id를 포함한다. 아래 신규 표는 수집 목표이며 API 지원 확인 전까지 비활성 상태다.

| 표 | 1행 기준 (공통 계정키 외) | 상태 / 용도 |
|---|---|---|
| naver_raw_campaign | date × campaign_id | 기존; 네이버 전체 요약 |
| naver_raw_search | date × campaign_id × ad_group_id × search_term | 기존; 실제 검색어 |
| naver_raw_media | date × campaign_id × ad_group_id × device × media_type | 기존; 기기·지면 |
| naver_raw_gender | date × campaign_id × ad_group_id × gender_raw | 기존; 쇼핑검색 |
| naver_raw_age | date × campaign_id × ad_group_id × age_raw | 기존; 쇼핑검색 |
| meta_daily | date × campaign_id | 기존; 합계의 기준 |
| meta_raw_ad | date × campaign_id × ad_group_id × ad_id | 신규 우선; 소재별 구매·매출 |
| meta_raw_ad_age_gender | date × campaign_id × ad_group_id × ad_id × age_raw × gender_raw | 신규 후보; 조합 지원 확인, 불가 시 별도 campaign 수준으로 명명 |
| meta_creative_history | ad_id × valid_from | 신규; 소재 연결 이력 |
| google_daily | date × campaign_id | 기존; 현재는 전체 주요 전환, 구매 확정 전 사용 제한 |
| google_raw_purchase_action | date × campaign_id × conversion_action_id | 신규 우선; 구매 전환 건수·매출만, 광고비 포함 금지 |
| google_raw_search_term | date × campaign_id × ad_group_id × search_term + API 추가 구분키 | 신규; 요청 segment가 늘면 유일키도 확장 |
| google_raw_ad | date × campaign_id × ad_group_id × ad_id | 신규; 검색/디멘드젠 지원 범위 검증 |
| google_raw_asset_group | date × campaign_id × asset_group_id | 신규; P맥스 애셋그룹 |
| google_raw_product | date × campaign_id × merchant_id × feed_label × item_id + API 추가 구분키 | 신규; 상품 제공 범위 검증 |
| google_raw_age / google_raw_gender | date × campaign_id × ad_group_id × 원본 분류 | 신규; 유형별 지원 확인, P맥스 제공 단정 금지 |
| gfa_raw_campaign / gfa_raw_ad | date × 각 계층 ID | 신규; GFA 인증·문서·응답 확인부터 시작 |
| gfa_raw_age / gfa_raw_gender | date × 지원되는 계층 ID × 원본 분류 | 신규 후보; 성과·구매 조합 지원 확인 |
| collection_status | run_id × report × account_id × 범위 × scope_id | 신규 공통; 성공/빈 결과/실패/미지원 구분 |

등록 키워드 분석이 필요하면 search_term과 별개인 keyword_id 기준 RAW를 추가한다. 네이버 상품별 분석도 상품/광고 ID를 유지한 별도 RAW가 필요하다. 현 코드가 내부에서 읽은 ad ID는 현재 집계 CSV에 보존되지 않는다.

## 4. 공통 컬럼과 정의

| 분류 | 필드 | 규칙 |
|---|---|---|
| 키 | date, platform, account_id, campaign_id | 날짜 YYYY-MM-DD; ID는 문자열 |
| 계층 | ad_group_id, ad_id, asset_group_id | 해당 RAW에 필요한 것만 사용 |
| 표시 | campaign_name, ad_group_name, ad_name, ad_type | 이름은 유일키로 사용하지 않음 |
| 기본 | impressions, clicks, spend | 비율 계산 전 정밀도 유지 |
| 클릭 정의 | click_type | 메타는 현재 link_click; 네이버·구글 일반 클릭과 차이 표시 |
| 구매 | purchases, purchase_value | 구매만 확정된 값; 소수 전환 보존 |
| 제공 상태 | purchase_status | available / not_supported / not_configured / unverified |
| 기준 | currency, cost_basis, account_timezone | 통화·VAT 기준 미확정 상태를 합산에 숨기지 않음 |
| 귀속 | attribution_setting, reporting_time_basis, purchase_definition_id | 매체 간 동일 기준이라고 가정하지 않음 |
| 분류 | gender_raw, age_raw, age_scheme | 원본 경계 보존; 임의 나이 구간 쪼개기 금지 |
| 운영 | fetched_at, run_id, source_report, schema_version | 원인 추적 및 재수집용 |

미제공·미확정 지표는 NULL/빈칸이다. 지원되고 성공한 응답에서 구매 이벤트가 없는 경우에만 해당 API의 의미를 확인한 뒤 0 처리한다. 실패한 요청은 0행 성공으로 처리하지 않는다.

연령 구간이 매체마다 다르면 매체별 차트에 원래 구간을 표시한다. 공통 구간으로 변환할 때는 원래 구간 전체가 하나의 구간에 포함되는 경우만 합산하며 분할 추정하지 않는다. unknown/알 수 없음은 삭제하지 않는다.

## 5. 기존 컬럼 매핑

| 표준 필드 | 네이버 캠페인 | 메타 캠페인 | 구글 캠페인 |
|---|---|---|---|
| date | 일별 | 날짜 | 날짜 |
| account_id | 계정ID | 계정ID | 계정ID |
| campaign_id | 캠페인ID | 캠페인ID | 캠페인ID |
| campaign_name | 캠페인 | 캠페인명 | 캠페인명 |
| ad_type | 캠페인 유형 | 신규 메타데이터 필요 | 캠페인유형 |
| impressions | 노출수 | 노출수 | 노출수 |
| clicks | 클릭수 | 링크클릭수 | 클릭수 |
| spend | 총비용 | 광고비 | 광고비 |
| purchases | 구매완료 전환수 | 구매 | 직접 매핑 금지: 구매 액션 집계 필요 |
| purchase_value | 구매완료 전환매출액 | 구매가치 | 직접 매핑 금지: 구매 액션 매출 필요 |
| currency | 코드에는 없음: 확인 후 보완 | 통화 | 통화 |

구글 구매 상세는 date/account_id/campaign_id로 먼저 합산하여 키당 1행으로 만든 다음 캠페인 성과와 연결한다. 성과가 없지만 구매만 있는 키도 보존한다. 여러 구매 액션이 같은 주문을 중복 집계하는지 확인하고 대표 액션 ID 목록을 관리한다. 광고 수준·애셋그룹 수준에서도 구매 분석을 원하면 해당 수준의 구매 데이터를 별도 검증·수집한다. 캠페인 구매를 하위 소재에 배분하지 않는다.

## 6. 메타 소재 사전

meta_creative_history: account_id, ad_id, creative_id, valid_from, valid_to, creative_group_id, creative_format, thumbnail_url, preview_url, video_id, primary_text, headline, landing_url, product, creative_type, hook, appeal, fetched_at.

- ad_id로 광고 성과와 연결하고 해당 날짜의 유효 버전 하나만 선택한다.
- 같은 creative_id는 같은 소재 그룹의 후보이며, 최종 creative_group_id는 카피/포맷/편집 차이를 검토해 지정한다.
- 이미지·영상 링크는 만료/접근 여부를 확인한다. 동영상 원본 URL 제공을 전제로 설계하지 않고 미리보기 링크를 대안으로 둔다.
- 캐러셀/동적 소재의 복수 에셋은 별도 creative_assets 표에 저장한다. 에셋 행마다 광고비 전체를 복제하지 않는다.
- product: 아이스 리프팅 크림 / PDRN 리프팅샷 / 기타 / 미분류 등 운영자가 지정.
- creative_type: 후기형 / 정보형 / 제품설명형 / 시딩 원본 / 시딩 편집 / 3D / 프로모션 등. 자동 분류는 검토 상태를 표시한다.
- 도달수·빈도는 일별 합계나 평균으로 주간·월간 값을 만들 수 없다. 필요 시 해당 기간·분석 단위로 별도 조회한다.

## 7. Looker Studio 화면과 데이터 연결

| 페이지 | 내용 | 연결표 |
|---|---|---|
| 1. 통합 요약 | 광고비·구매·매출·CPA·ROAS, 일별 추이, 매체 비교 | mart_campaign_daily |
| 2. 네이버 검색 | 파워링크/쇼핑검색/브랜드검색, 검색어, 기기·지면 | 네이버 각 RAW의 정규화 표 |
| 3. GFA | 캠페인·소재·인구통계 | GFA 각 RAW; 수집 전에는 미연동 표시 |
| 4. 메타 소재 | 썸네일·미리보기·소재명·제품·소구점·광고비·구매·ROAS | mart_meta_ad_daily (광고성과 + 유효 소재 버전) |
| 5. 메타 타겟 | 성별·연령별 구매·CPA·ROAS | 인구통계 전용 표; 지원 단위 표시 |
| 6. 구글 | 검색/P맥스/디멘드젠 및 각 상세 | 캠페인 구매 통합표와 유형별 별도 상세표 |
| 7. 인사이트 | 주요 변화·원인 가설·다음 액션·담당·기한 | report_notes |

필터: 기간, 매체, 광고 유형, 캠페인; 소재 페이지에 제품·소재 유형 추가. 필터가 각 데이터 소스에 실제 적용되는지 검증한다. 캠페인 수준과 소재 수준 표가 섞인 화면에서 숫자를 합산하지 않는다.

주간은 월~일, 비교는 직전 월~일. 월간은 달력 월, 비교는 직전 달력 월. "직전 동일 일수"와 "직전 월"을 구분한다. 진행 중인 월의 MTD는 전월 동일 경과일과 비교하고, 종료 월 보고와 구별한다.

기본 KPI는 매체 보고 구매/매출이다. 합산 구매는 매체 간 중복이 제거된 실제 주문수가 아니다. 필요 시 주문 시스템의 실제 매출을 별도 데이터로 표시한다.

계산: CTR=SUM(clicks)/SUM(impressions), CPC=SUM(spend)/SUM(clicks), CPA=SUM(spend)/SUM(purchases), ROAS=SUM(purchase_value)/SUM(spend). 분모 0은 NULL 표시, ROAS·CTR은 비율을 저장하고 화면에서 % 형식을 적용한다. 기존 일별 비율의 단순 평균은 사용하지 않는다.

## 8. 안정적인 수집과 저장

- 성공한 report/account/date/scope 범위만 교체. 실패 범위는 기존 행을 보존하고 상태를 표시.
- 모든 페이지 수집 및 키 검증 완료 후 성공 처리. 동일 범위 재실행 후 행 수와 합계가 중복되지 않아야 함.
- 정상 빈 결과는 해당 범위를 교체할 수 있으나 미지원·오류·부분 응답과 구분.
- 이름 변경으로 행이 새로 생기지 않도록 ID 기반 유일키 사용.
- Sheets 쓰기 전 백업, 쓰기 이후 유일키·행 수·합계 확인. 현재 네이버 청크 쓰기도 중간 실패 시 전체 작업이 원자적이지 않으므로 별도 임시 탭/검증 후 전환 방식을 검토.
- 메타 workflow는 동시 실행 제어가 없음. 구글/네이버처럼 탭별 concurrency 설정 필요.
- 메타·구글도 네이버처럼 dry-run 모드와 수집 상태 출력을 추가.
- 현 메타/구글은 resize 후 update 방식이므로 실패 시 보존 전략 개선 필요.
- 전환 소급 기간은 현재 7/30/14일 값을 고정 진실로 보지 말고 실제 기여 기간·API 제한·지연으로 결정.
- 네이버 인구통계는 코드상 최근 7일만 재조회하므로 일별 누락 알림과 복구 가능 기간 관리 필요.
- 현재 메타 구매는 int 변환, 비용/매출은 반올림. 정규화 전 정밀도를 보존하고 표시 단계에서 반올림.
- 구글의 impressions>0 필터는 구매만 발생한 과거 일자 행을 배제할 가능성을 검증. 구매 추출에는 이 필터를 무조건 재사용하지 않음.
- 계정 시간대가 KST인지 확인한 후 일별 통합. 기준이 다르면 단순 날짜 라벨 변경으로 변환하지 않음.
- 브랜드검색 계약비를 추가할 경우 campaign/date별 배분 원장과 API 비용 중 적용할 출처를 하나로 정하여 이중 계산 방지.

## 9. 구현 순서와 완료 기준

1. 구매·광고비 기준 확정: 구글 대표 구매 액션 ID, 메타 웹 구매 범위, 매체별 VAT/통화/기여 기준. 실제 관리자 1일·7일 값과 대조.
2. 메타 소재: 광고 일별 + 소재 사전 + 인구통계 요청 조합 검증. 광고별 구매/매출과 화면 링크 확인.
3. 캠페인 통합표: 네이버·메타·구글 구매를 표준화. GFA 미연동을 0원으로 오인하지 않도록 상태 표시.
4. 구글 상세 및 GFA: API별 지원 범위를 표에 기록하고 별도 RAW 추가.
5. Looker Studio 시안: 기간 비교, 합계 재계산, 미지원 표시, 소재 미리보기 검증.

검증 사례:
- 캠페인 광고비 100과 성별 합계 광고비 100이 있어도 전체 요약은 100.
- 여성 30건/35~44세 20건으로 여성 35~44세 구매를 생성하지 않음.
- 구매 액션 2개가 있는 캠페인에서 광고비는 한번만 합산.
- 일부 계정 실패 시 성공 계정만 교체, 실패 계정의 기존값과 실패 상태 유지.
- 광고 이름/소재 버전 변경 후 성과 행이 중복되지 않음.
- 미지원 구매 NULL과 구매 0을 구분.
- 일별 도달수 합계를 월간 도달수로 표시하지 않음.
- 빈 결과 재조회 및 재실행의 중복 방지 검증.

## 10. 아직 필요한 운영 입력

- 현재 Google Sheets 헤더 및 작은 기간의 실데이터 합계 (비밀키 제외).
- 구글 구매 전환 액션 ID·이름과 광고 관리자에서 비교할 구매 열.
- 광고비 VAT 포함/제외 보고 기준, 브랜드검색 계약비 처리 기준.
- 메타 광고계정의 기여 설정 및 웹 구매만 포함할지 여부.
- GFA API 접근 준비 여부 및 사용 중인 문서/응답 예시.

기존 API 키와 서비스 계정 비밀값을 문서나 채팅에 복사할 필요는 없다.

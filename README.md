# BNA API Auto

네이버 검색광고, Meta Ads, Google Ads 성과를 수집하여 Google Sheets와 CSV에 저장하는 프로젝트입니다.

## 광고 리포트 준비

[주간·월간 Looker Studio 리포트 설계서](docs/reporting-plan.md)에 현재 수집 범위, 신규 RAW 목록, 컬럼 정의, 소재 사전, 화면별 데이터 연결, 구현 순서를 정리했습니다.

현재 메타와 구글은 캠페인 단위입니다. 구글 전환수는 구매만 필터링한 값이 아닙니다. GFA 수집기는 아직 없습니다. 실제 수집 성공 여부는 Actions 실행 결과와 광고 관리자 수치로 확인해야 합니다.

## 파일

| 파일 | 역할 |
|---|---|
| naver_report.py | 캠페인·검색어·매체·성별·연령 RAW 5종 |
| meta_report.py | 캠페인 일별 성과 및 구매 이벤트 가공 |
| google_report.py | 캠페인 일별 성과 및 전체 주요 전환 |
| .github/workflows/ | 매일 수집 및 CSV artifact 업로드 |
| requirements.txt | Python 의존성 |

네이버 성별·연령은 현재 코드에서 쇼핑검색·최근 7일만 요청합니다. 파워링크 검색어 구매 지표는 빈칸으로 저장합니다. 세부 제한은 설계서의 현재 구현 진단을 참고하세요.

인증 값은 GitHub Actions Secrets에서 관리합니다. 실제 광고 RAW와 비밀값은 저장소에 커밋하지 않습니다.

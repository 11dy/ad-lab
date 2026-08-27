# 쇼핑검색광고 브랜드형 검색상단노출률(topImpRto) 항목 종료 안내

- 매체: 네이버 검색광고 API (`naver_searchad`)
- 공지일: 2026-08-27
- 수집일: 2026-08-27 (KST)
- 중요도: 🔴 (⚠️ ETL 영향 가능성)
- 원문: http://naver.github.io/searchad-apidoc/notice/2026/08/27/notice1/
- id: `f5933e364b6c02647cac46d073369c78a23f50cd`

## 요약

2026-09-30(KST)부터 STAT(GET /stats) 응답의 topImpRto가 쇼핑검색광고 브랜드형 키워드에 한해 고정값(0)으로 제공됨.

## 원문 발췌

안녕하세요. 네이버 검색광고 API입니다. 지난 2021년 3월 10일에 안내드린 바와 같이, 쇼핑검색광고 브랜드형 상품 출시에 따라 추가되었던 ‘검색상단노출률(%)’(topImpRto) 지표 제공이 종료되어 API기능 변경 사항을 공지 드립니다. 대상 API STAT (GET /stats) : get (by id), get (by ids) Response topImpRto 변경 시점(KST기준) 2026년 9월 30일 (수) 변경 내용 대상 광고 : 쇼핑검색광고 브랜드형 광고그룹(AdGroup Type = 9)에 속한 키워드 한정 변경 내용 : 호출 파라미터 중 fields에 topImpRto를 입력하여 호출하는 경우, 변경 시점을 기준으로 고정값(0)으로 표시되며, 실제 광고 노출 위치를 반영한 수치가 아닌 시스템 기본값으로 제공됩니다. 업무에 참고 부탁드립니다. 감사합니다.

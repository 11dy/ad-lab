---
name: notice-summary
description: out/new_items.json의 광고 매체 API 신규 공지를 중요도 분류와 함께 슬랙 발송용 out/summary.md로 요약한다.
---

# 광고 API 신규 공지 요약

## 입력 / 출력
- **입력**: `out/new_items.json` — `[{ id, source_id, source_name, title, url, date, content }]`
- **출력 1**: `out/summary.md` — 슬랙 발송용 요약 (Slack mrkdwn 호환: 굵게는 `*텍스트*`, 헤딩 `#` 문법 사용 금지)
- **출력 2**: `out/summaries.json` — 아카이브(리포지토리 기록)용 아이템별 구조화 결과

## 작성 절차
1. `out/new_items.json`을 읽는다.
2. 각 아이템의 중요도를 아래 규칙으로 분류한다.
3. 아래 포맷으로 `out/summary.md`를 작성한다 (오늘 날짜는 YYYY-MM-DD).
4. 같은 판단 결과를 `out/summaries.json`으로도 저장한다.

## 출력 포맷

```
📢 *광고 API 신규 공지 (YYYY-MM-DD)*

*[소스명 1]*

🔴 제목
요약 1~2줄 (🔴이고 ETL 관련이면 "⚠️ ETL 영향 가능성" 표기)
🔗 원문링크URL

🟡 제목
요약 1~2줄
🔗 원문링크URL

*[소스명 2]*
...
```

- 소스별로 그룹핑하고, 같은 소스 내에서는 날짜 내림차순.
- 요약은 1~2줄로 간결하게. 핵심 변경점(무엇이, 언제부터, 누구에게 영향)만.
- `content`가 비어 있는 아이템은 **제목 기반으로만 중요도를 분류하고 요약은 생략** (제목 + 링크만 출력).
- 링크는 raw URL 그대로 출력 (슬랙이 자동 링크 처리. `[텍스트](url)` Markdown 문법 사용 금지).

## out/summaries.json 포맷

`out/new_items.json`의 **모든** 아이템에 대해 1:1로, 입력과 같은 순서로 작성한다.

```json
[
  {
    "id": "new_items.json의 id 그대로",
    "importance": "🔴",
    "etl_impact": true,
    "summary": "summary.md에 쓴 것과 같은 1~2줄 요약"
  }
]
```

- `importance`: `🔴` / `🟡` / `🟢` 중 하나 (summary.md의 판단과 반드시 일치)
- `etl_impact`: "⚠️ ETL 영향 가능성"을 표기한 아이템만 `true`
- `summary`: `content`가 비어 요약을 생략한 아이템은 빈 문자열 `""`
- id는 절대 새로 만들거나 변형하지 않는다 (아카이브 파일이 이 id로 매칭된다)

## 중요도 분류 규칙

| 이모지 | 기준 |
|---|---|
| 🔴 | API deprecated/제거/지원 종료, 필수 파라미터·응답 필드 변경, 인증(OAuth/토큰/키) 변경 |
| 🟡 | 신규 기능/필드 추가, 신규 버전 릴리즈, 정책 변경 예고 |
| 🟢 | 단순 안내, 점검/장애 공지, 문서 수정 |

**강제 규칙 (다른 기준보다 우선):**
- 보고서 관련 변경 — Report, MasterReport, 통계/지표 필드 추가·변경·삭제 → 무조건 🔴 + 요약에 "⚠️ ETL 영향 가능성" 표기
- OAuth, 토큰, 인증 키 관련 변경 → 무조건 🔴 + "⚠️ ETL 영향 가능성" 표기

## 주의
- 전체 분량은 간결하게 유지한다. 아이템이 많아도 아이템당 3~4줄을 넘기지 않는다.
- 판단이 애매하면 한 단계 높은 중요도를 부여한다 (🟢 vs 🟡 애매 → 🟡).
- `out/summary.md`와 `out/summaries.json` 외 다른 파일을 수정하지 않는다.

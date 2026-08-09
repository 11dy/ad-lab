# ad-api-notice-watcher (repo: 11dy/api-tracker)

광고 매체 API 공지를 GitHub Actions 크론(매일 09:23/12:23/15:23/18:23 KST — 정각 혼잡 회피)으로 수집, 신규만 Claude가 요약해 슬랙 발송. 2026-06-12 E2E 검증 완료, 운영 중.

## 세션 시작 시 확인할 것

- **문제/작업 요청은 GitHub 이슈로 관리한다.** 세션 시작하면 먼저 열린 이슈를 확인할 것:
  ```bash
  gh issue list -R 11dy/api-tracker --state open
  ```
  이슈 처리 후에는 해당 이슈에 결과를 코멘트로 남기고 close.

## 아키텍처 원칙 (변경 금지)

- 결정적 작업(수집·신규 판별·발송)은 Python, **Claude는 신규 공지 요약에만** 사용. 신규 없으면 Claude step 미실행.
- 공지는 페이지 diff가 아니라 아이템 단위 관리: `id = sha1(url)`, `state/seen.json`과 대조해 신규 판별.

## 핵심 파일

| 파일 | 역할 |
|---|---|
| `scripts/crawl.py` | 수집 → 신규 판별 → `out/new_items.json` + 소스 상태 `out/health.json`. 소스별 파서는 `PARSERS` 딕셔너리 |
| `scripts/archive.py` | 신규 공지를 `archive/<매체>/<연>/<월>/<날짜>-<제목>.md`로 기록 + 인덱스 재생성 |
| `scripts/notify.py` | `out/summary.md` → 슬랙 Webhook (38,000자 분할) |
| `scripts/report_health.py` | 수집 실패·0건 소스를 `[parser-health]` GitHub 이슈로 발행, 복구되면 자동 close |
| `.claude/skills/notice-summary/SKILL.md` | 요약 규칙. **메시지 포맷/중요도 기준 변경은 이 파일만** 수정. `out/summary.md`(슬랙) + `out/summaries.json`(아카이브용) 두 개를 출력 |
| `archive/` | 공지 아카이브 (git 커밋 대상, Actions가 자동 생성). 수동 편집 대상 아님 |
| `sources.json` | 소스 정의. criteo(URL 404)·tiktok(JS 렌더링)은 `enabled: false` |
| `state/seen.json` | 알림 완료 id (git 커밋 대상, Actions가 자동 갱신) |
| `wiki/` | **로컬 전용 문서 (gitignored, push 금지)** — 상세 설계·트러블슈팅·운영 가이드 |

## 주의사항

- 파서가 예외 없이 **0건**을 반환하면 사이트 구조 변경 신호다 (2026-08 google_ads: 릴리즈 헤딩 h2→h3로 몇 달간 조용히 누락). `crawl.py`는 0건을 `[warn]` + `health.json`에 남기고 `report_health.py`가 이슈로 올린다 — 이 경로 제거 금지
- `crawl.py`의 `fetch()` 단순 UA 폴백(`FALLBACK_HEADERS`) **제거 금지** — Meta가 브라우저형 UA + Python TLS 조합을 400 차단함
- Claude 인증은 구독 OAuth 토큰(`CLAUDE_CODE_OAUTH_TOKEN`) — 종량제 API 키로 바꾸지 말 것 (사용자 의사)
- watch.yml의 `id-token: write` 권한과 `github_token` 입력은 claude-code-action 동작에 필수 — 제거하면 실패
- 커밋 author는 noreply 이메일(`96255906+11dy@users.noreply.github.com`) 유지. 2026-06-12에 히스토리를 filter-repo로 재작성했으므로 그 이전 SHA 참조는 무효
- 로컬 실행: `.venv/bin/python scripts/crawl.py` (venv는 gitignored)

## E2E 테스트 방법

`state/seen.json`에서 최신 id 1~2개 삭제 → commit/push → `gh workflow run watch.yml -R 11dy/api-tracker` → 슬랙 수신 확인. seen은 실행 후 자동 복원 커밋됨.

# ad-api-notice-watcher

광고 매체 API 공지/릴리즈 노트를 매일 확인해서 **신규 공지만** Claude로 요약하고 슬랙으로 발송하는 시스템.

## 동작 흐름

```
GitHub Actions (매일 09/12/15/18시 KST / 수동 실행)
│
├─ 1. scripts/crawl.py                     ← 결정적 처리 (LLM 없음)
│     sources.json의 각 소스에서 최신 공지 최대 10건 파싱
│     → { id: sha1(url), source, title, url, date }
│     → state/seen.json에 없는 id만 신규로 분류
│     → 신규 있으면 본문 수집 후 out/new_items.json 생성
│     → seen.json 갱신 (소스별 최근 200개 유지)
│
├─ 2. out/new_items.json 존재? ──── 없음 → 종료 (Claude 호출 안 함)
│                          │
│                         있음
│                          ▼
├─ 3. anthropics/claude-code-action       ← Claude는 요약에만 사용
│     .claude/skills/notice-summary 규칙으로
│     중요도(🔴🟡🟢) 분류 + 요약 → out/summary.md, out/summaries.json
│
├─ 4. scripts/archive.py                  ← 결정적 처리
│     요약 + 원문 발췌를 archive/<매체>/<연>/<월>/<날짜>-<제목>.md로 기록
│
├─ 5. scripts/notify.py                   ← 결정적 처리
│     summary.md → 슬랙 Incoming Webhook (40,000자 초과 시 분할)
│
├─ 6. state/seen.json·archive/ 변경 시 git commit & push
│
└─ 7. scripts/report_health.py            ← 항상 실행
      수집 실패·0건 소스를 [parser-health] 이슈로 발행 (복구되면 자동 close)
```

## 모니터링 대상

| 소스 | 방식 | 상태 |
|---|---|---|
| 네이버 검색광고 API | 공식 공지 RSS (`feed.xml`) | ✅ |
| 네이버 GFA API | Docusaurus 블로그 HTML | ✅ (저빈도 — 전체 5건) |
| 카카오 데브톡 공지 | Discourse JSON (`/c/notice.json`), `created_at` 내림차순 | ✅ (광고 외 공지 혼재) |
| Google Ads API | 릴리즈 노트 페이지의 버전 헤딩(h3) 단위, 백포트 중복 제거 | ✅ |
| Meta Graph API | changelog의 버전 링크 단위, 날짜는 버전 페이지에서 보강 | ✅ (버전 단위만) |
| Criteo Marketing API | Changelog 페이지의 변경 항목(h2 슬러그) 단위 | ✅ |
| TikTok Business API | — | ❌ 완전 CSR (`enabled: false`) |

## 설정

### 1. 슬랙 Incoming Webhook 생성

1. https://api.slack.com/apps → **Create New App** → From scratch → 앱 이름/워크스페이스 선택
2. 좌측 **Incoming Webhooks** → 토글 On → **Add New Webhook to Workspace** → 발송할 채널 선택
3. 발급된 **Webhook URL** 저장 (예: `https://hooks.slack.com/services/T.../B.../xxx`)

### 2. Claude 인증 토큰 발급 (Pro/Max 구독)

API 키 종량제 과금 대신 claude.ai 구독 할당량을 사용한다 (별도 청구 없음).

```bash
claude setup-token
# → 브라우저 OAuth 인증 후 출력되는 토큰을 복사
```

> 참고: 이 토큰은 개인 구독에 묶이며, 워크플로 실행량만큼 본인의 인터랙티브 사용 할당량을 소모한다.
> 종량제 API 키를 쓰려면 워크플로의 `claude_code_oauth_token`을 `anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}`로 교체.

### 3. GitHub Secrets 등록

repo → Settings → Secrets and variables → Actions → New repository secret

| Secret | 값 |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token`으로 발급한 토큰 |
| `SLACK_WEBHOOK_URL` | 위에서 발급한 Webhook URL |

### 4. 첫 실행

push 후 Actions 탭에서 `ad-api-notice-watch` → Run workflow (수동 실행).
**최초 실행은 현재 공지 전체를 seen 처리만 하고 알림을 보내지 않는다** (초기화).
이후 실행부터 신규 공지만 알림.

## 소스 추가 방법

1. `sources.json`에 항목 추가:
   ```json
   {
     "id": "new_source",
     "name": "표시될 소스명",
     "url": "https://...",
     "type": "html | json | github_api",
     "parser": "parse_new_source",
     "enabled": true
   }
   ```
2. `scripts/crawl.py`에 파서 함수 작성 후 `PARSERS` 딕셔너리에 등록.
   파서는 `[{ id, title, url, date, content }]`를 최신순으로 반환 (최대 10건, `id`는 `item_id(url)` 사용).
3. 로컬에서 `python scripts/crawl.py` 실행 → 파싱 결과 확인.
   새 소스는 첫 실행 때 자동으로 seen 초기화되어 기존 공지가 알림으로 쏟아지지 않는다.

## 디렉토리 구조

```
├── .github/workflows/watch.yml          # 크론 워크플로
├── .claude/skills/notice-summary/SKILL.md  # 요약 규칙 (중요도 분류)
├── scripts/
│   ├── crawl.py                         # 수집 → 신규 판별 → new_items.json, health.json
│   ├── archive.py                       # 공지 아카이브 md + 인덱스 생성
│   ├── notify.py                        # 슬랙 발송
│   └── report_health.py                 # 수집 이상 소스 → GitHub 이슈
├── sources.json                         # 모니터링 대상 정의
├── state/seen.json                      # 알림 완료 id (git 커밋 대상)
├── archive/                             # 매체별/연/월 공지 기록 (git 커밋 대상)
└── out/                                 # new_items.json, summary.md 등 (커밋 안 함)
```

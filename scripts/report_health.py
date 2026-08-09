#!/usr/bin/env python3
"""out/health.json의 이상 소스를 GitHub 이슈로 발행하고, 복구되면 닫는다.

사이트 구조가 바뀌면 파서가 예외 없이 0건을 뱉어 크론이 '성공'으로 끝난다(2026-08 google_ads 사례).
그 상태를 사람이 나중에라도 볼 수 있게 이슈로 남기는 것이 목적.

- 이상 + 열린 이슈 없음  → 이슈 생성
- 이상 + 열린 이슈 있음  → 아무것도 안 함 (하루 4회 크론 도배 방지)
- 정상 + 열린 이슈 있음  → 복구 코멘트 후 close

환경변수: GITHUB_TOKEN, GITHUB_REPOSITORY (필수) / GITHUB_RUN_ID, GITHUB_SERVER_URL (선택)
크론 본류를 막지 않도록 어떤 실패에도 exit 0.
"""
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
HEALTH_FILE = ROOT / "out" / "health.json"
TITLE_PREFIX = "[parser-health]"
API = "https://api.github.com"
TIMEOUT = 20


def issue_title(sid: str) -> str:
    return f"{TITLE_PREFIX} {sid} 수집 이상 — 파서 점검 필요"


def run_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{repo}/actions/runs/{run_id}" if run_id else "(로컬 실행)"


def issue_body(entry) -> str:
    return "\n".join([
        f"`{entry['id']}` 소스 수집이 정상 동작하지 않는다.",
        "",
        f"- 매체: {entry['name']}",
        f"- URL: {entry['url']}",
        f"- 증상: {entry['reason']}",
        f"- 실행: {run_url()}",
        "",
        "파싱 0건은 예외가 아니라 사이트 구조 변경(헤딩 태그·셀렉터 변경)일 가능성이 높다.",
        "",
        "```",
        ".venv/bin/python scripts/crawl.py",
        "```",
        "",
        f"`scripts/crawl.py`의 해당 파서를 실제 페이지 구조와 대조해 수정하면 된다. "
        f"수집이 정상화되면 이 이슈는 다음 크론에서 자동으로 닫힌다.",
    ])


class GitHub:
    def __init__(self, token: str, repo: str):
        self.repo = repo
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def open_health_issues(self):
        """제목 접두로 매칭 — 라벨을 따로 관리하지 않기 위해 검색 API 대신 목록을 훑는다."""
        resp = self.session.get(
            f"{API}/repos/{self.repo}/issues",
            params={"state": "open", "per_page": 100},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return [i for i in resp.json() if i.get("title", "").startswith(TITLE_PREFIX)]

    def create_issue(self, title: str, body: str):
        resp = self.session.post(
            f"{API}/repos/{self.repo}/issues",
            json={"title": title, "body": body},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["number"]

    def comment(self, number: int, body: str):
        self.session.post(
            f"{API}/repos/{self.repo}/issues/{number}/comments",
            json={"body": body},
            timeout=TIMEOUT,
        ).raise_for_status()

    def close(self, number: int):
        self.session.patch(
            f"{API}/repos/{self.repo}/issues/{number}",
            json={"state": "closed"},
            timeout=TIMEOUT,
        ).raise_for_status()


def main():
    if not HEALTH_FILE.exists():
        print(f"{HEALTH_FILE} 없음 — 보고할 상태 없음")
        return

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("GITHUB_TOKEN / GITHUB_REPOSITORY 미설정 — 이슈 보고 생략", file=sys.stderr)
        return

    health = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    gh = GitHub(token, repo)
    open_issues = {i["title"]: i["number"] for i in gh.open_health_issues()}

    for entry in health.get("unhealthy", []):
        title = issue_title(entry["id"])
        if title in open_issues:
            print(f"[skip] {entry['id']}: 이슈 #{open_issues[title]} 이미 열려 있음")
            continue
        number = gh.create_issue(title, issue_body(entry))
        print(f"[ok] {entry['id']}: 이슈 #{number} 생성 — {entry['reason']}")

    for sid in health.get("healthy", []):
        number = open_issues.get(issue_title(sid))
        if number is None:
            continue
        gh.comment(number, f"`{sid}` 수집이 정상화되어 자동으로 닫는다. 실행: {run_url()}")
        gh.close(number)
        print(f"[ok] {sid}: 복구 확인 — 이슈 #{number} close")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — 상태 보고 실패가 크론을 실패시키지 않게
        print(f"[warn] 상태 보고 실패 — {exc}", file=sys.stderr)

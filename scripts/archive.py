#!/usr/bin/env python3
"""신규 공지를 매체별/연/월 폴더 구조로 리포지토리에 아카이브한다.

입력: out/new_items.json (필수), out/summaries.json (선택 — Claude 요약)
출력: archive/<source_id>/<YYYY>/<MM>/<YYYY-MM-DD>-<slug>.md
      archive/<source_id>/README.md, archive/README.md (인덱스 재생성)

요약 유무와 무관하게 원문 발췌는 항상 남긴다 — 원문 페이지가 사라져도 변경 이력을 추적하기 위함.
LLM 호출 없음 — 경로·파일명·포맷은 전부 여기서 결정적으로 정한다.
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEW_ITEMS_FILE = ROOT / "out" / "new_items.json"
SUMMARIES_FILE = ROOT / "out" / "summaries.json"
ARCHIVE_DIR = ROOT / "archive"

KST = timezone(timedelta(hours=9))
SLUG_MAX_LEN = 60


def today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def slugify(title: str) -> str:
    """제목 → 파일명 조각. 한글은 그대로 두고 경로에 위험한 문자만 제거한다.

    파일명 앞에 이미 날짜가 붙으므로 제목 안의 날짜(예: 'v25 (2026-07-22)')는 덜어낸다.
    """
    slug = re.sub(r"\(?\d{4}-\d{2}-\d{2}\)?", " ", title or "")
    slug = re.sub(r"\s+", "-", slug.strip().lower())
    slug = re.sub(r"[^0-9a-z가-힣._-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-._")
    return slug[:SLUG_MAX_LEN].strip("-._") or "notice"


def load_summaries():
    """id → {importance, etl_impact, summary}. 파일이 없거나 깨져도 진행한다."""
    if not SUMMARIES_FILE.exists():
        print(f"[warn] {SUMMARIES_FILE.name} 없음 — 요약 없이 아카이브", file=sys.stderr)
        return {}
    try:
        data = json.loads(SUMMARIES_FILE.read_text(encoding="utf-8"))
        return {s["id"]: s for s in data if isinstance(s, dict) and s.get("id")}
    except Exception as exc:  # noqa: BLE001 — 요약 파싱 실패가 아카이브를 막지 않는다
        print(f"[warn] {SUMMARIES_FILE.name} 파싱 실패 ({exc}) — 요약 없이 아카이브", file=sys.stderr)
        return {}


def target_path(item, date: str) -> Path:
    """archive/<source_id>/<YYYY>/<MM>/<YYYY-MM-DD>-<slug>.md — 다른 공지와 충돌하면 id 접미.

    같은 공지의 재실행이면 기존 경로를 그대로 돌려줘 호출부가 스킵하도록 한다(멱등).
    """
    directory = ARCHIVE_DIR / item["source_id"] / date[:4] / date[5:7]
    slug = slugify(item["title"])
    base = directory / f"{date}-{slug}.md"
    if not base.exists() or f"`{item['id']}`" in base.read_text(encoding="utf-8"):
        return base
    return directory / f"{date}-{slug}-{item['id'][:6]}.md"


def render(item, date: str, summary) -> str:
    importance = (summary or {}).get("importance") or "-"
    if (summary or {}).get("etl_impact"):
        importance += " (⚠️ ETL 영향 가능성)"
    lines = [
        f"# {item['title']}",
        "",
        f"- 매체: {item['source_name']} (`{item['source_id']}`)",
        f"- 공지일: {item['date'] or f'{date} (미표기 — 수집일 기준)'}",
        f"- 수집일: {today_kst()} (KST)",
        f"- 중요도: {importance}",
        f"- 원문: {item['url']}",
        f"- id: `{item['id']}`",
        "",
        "## 요약",
        "",
        (summary or {}).get("summary") or "_요약 없음_",
        "",
        "## 원문 발췌",
        "",
        item.get("content") or "_본문 수집 실패_",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 인덱스 — 파일시스템을 스캔해 매번 통째로 재생성 (누락·중복 방지)
# ---------------------------------------------------------------------------

def archived_files(source_dir: Path):
    """해당 매체의 아카이브 md를 (날짜, 경로) 최신순으로 반환."""
    files = [p for p in source_dir.rglob("*.md") if p.name != "README.md"]
    return sorted(files, key=lambda p: (p.name, p.parent.as_posix()), reverse=True)


def first_heading(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def write_source_index(source_dir: Path):
    files = archived_files(source_dir)
    lines = [f"# {source_dir.name} 아카이브", "", f"총 {len(files)}건", ""]
    for path in files:
        date = path.name[:10]
        rel = path.relative_to(source_dir).as_posix()
        lines.append(f"- {date} [{first_heading(path)}]({rel})")
    lines.append("")
    (source_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def write_root_index():
    if not ARCHIVE_DIR.exists():
        return
    source_dirs = sorted(d for d in ARCHIVE_DIR.iterdir() if d.is_dir())
    lines = [
        "# 광고 매체 API 공지 아카이브",
        "",
        "크론이 신규 공지를 수집할 때마다 자동 생성된다. 경로 규칙: `<매체>/<연>/<월>/<날짜>-<제목>.md`",
        "",
        "| 매체 | 건수 | 최근 공지 |",
        "|---|---|---|",
    ]
    for source_dir in source_dirs:
        files = archived_files(source_dir)
        if not files:
            continue
        latest = files[0]
        rel = latest.relative_to(ARCHIVE_DIR).as_posix()
        lines.append(
            f"| [{source_dir.name}]({source_dir.name}/README.md) | {len(files)} | "
            f"{latest.name[:10]} [{first_heading(latest)}]({rel}) |"
        )
    lines.append("")
    (ARCHIVE_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    if not NEW_ITEMS_FILE.exists():
        print(f"{NEW_ITEMS_FILE} 없음 — 아카이브할 신규 공지 없음")
        return

    items = json.loads(NEW_ITEMS_FILE.read_text(encoding="utf-8"))
    summaries = load_summaries()

    touched_sources = set()
    written = skipped = 0
    for item in items:
        date = item.get("date") or today_kst()
        path = target_path(item, date)
        touched_sources.add(item["source_id"])
        if path.exists():
            print(f"[skip] 이미 존재 — {path.relative_to(ROOT)}")
            skipped += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(item, date, summaries.get(item["id"])), encoding="utf-8")
        print(f"[ok] {path.relative_to(ROOT)}")
        written += 1

    for sid in sorted(touched_sources):
        write_source_index(ARCHIVE_DIR / sid)
    write_root_index()

    print(f"\n아카이브 {written}건 생성, {skipped}건 스킵 → {ARCHIVE_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

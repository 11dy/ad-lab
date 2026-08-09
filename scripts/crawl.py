#!/usr/bin/env python3
"""광고 매체 API 공지 수집기.

sources.json에 정의된 소스에서 최신 공지를 파싱하고,
state/seen.json과 비교해 신규 공지만 out/new_items.json으로 저장한다.
소스별 수집 상태(실패·0건)는 out/health.json에 남긴다 (report_health.py가 이슈로 발행).
LLM 호출 없음 — 전 과정 결정적(deterministic) 처리.
"""
import hashlib
import json
import re
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources.json"
SEEN_FILE = ROOT / "state" / "seen.json"
OUT_DIR = ROOT / "out"
NEW_ITEMS_FILE = OUT_DIR / "new_items.json"
HEALTH_FILE = OUT_DIR / "health.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
        "ad-api-notice-watcher"
    )
}
TIMEOUT = 25
MAX_ITEMS_PER_SOURCE = 10
SEEN_LIMIT_PER_SOURCE = 200
CONTENT_MAX_CHARS = 3000


def item_id(url: str) -> str:
    """URL 기준 sha1 해시로 공지 고유 id 생성."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


FALLBACK_HEADERS = {"User-Agent": "Mozilla/5.0"}  # 일부 사이트(Meta)가 브라우저 UA + Python TLS 조합을 차단


def fetch(url: str, as_json: bool = False):
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    if 400 <= resp.status_code < 500:
        resp = requests.get(url, headers=FALLBACK_HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json() if as_json else resp.text


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ---------------------------------------------------------------------------
# 소스별 파서 — 각 파서는 [{id, title, url, date, content}] 반환 (최신순, 최대 10건)
# content는 목록 단계에서 얻을 수 있는 경우에만 채우고, 없으면 "" (후단에서 본문 fetch 시도)
# ---------------------------------------------------------------------------

def parse_naver_searchad(source):
    """공식 공지 RSS 피드(feed.xml) — item별 title/link/pubDate/category/description.

    사람용 공지 페이지(#/notice)는 AngularJS SPA라 정적 파싱 불가 → 같은 공지의 RSS 원본을 사용.
    GitHub Issues(/issues)는 사용자 Q&A지 공식 공지가 아니므로 쓰지 않는다.
    """
    root = ET.fromstring(fetch(source["url"]))
    items = []
    for item in root.iter("item"):
        url = clean_text(item.findtext("link") or "")
        if not url:
            continue
        date = ""
        pub = item.findtext("pubDate")
        if pub:
            try:
                date = parsedate_to_datetime(pub).date().isoformat()
            except (TypeError, ValueError):
                date = ""
        # description은 HTML(한글+영어 번역 중복) — 태그 제거 후 본문화
        desc = BeautifulSoup(item.findtext("description") or "", "html.parser").get_text(" ")
        items.append({
            "id": item_id(url),
            "title": clean_text(item.findtext("title") or ""),
            "url": url,
            "date": date,
            "content": clean_text(desc)[:CONTENT_MAX_CHARS],
        })
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break
    return items


def parse_naver_gfa(source):
    """Docusaurus 블로그 — article[itemprop=blogPost] 단위."""
    soup = BeautifulSoup(fetch(source["url"]), "html.parser")
    items = []
    for article in soup.select('article[itemprop="blogPost"]')[:MAX_ITEMS_PER_SOURCE]:
        link = article.select_one('a[itemprop="url"]')
        if not link or not link.get("href"):
            continue
        url = urljoin(source["url"], link["href"])
        time_tag = article.select_one("time[datetime]")
        date = (time_tag["datetime"][:10] if time_tag else "")
        items.append({
            "id": item_id(url),
            "title": clean_text(link.get_text()),
            "url": url,
            "date": date,
            "content": "",
        })
    return items


def parse_kakao_devtalk(source):
    """Discourse JSON 엔드포인트 — /c/notice.json의 topic 목록.

    Discourse는 pinned 토픽을 목록 맨 앞에 올린다. 그대로 앞 10건을 자르면 오래된 고정 공지가
    자리를 차지해 최신 공지가 밀려날 수 있으므로 created_at 내림차순으로 다시 정렬한다.
    """
    data = fetch(source["url"].rstrip("/") + ".json", as_json=True)
    base = "https://devtalk.kakao.com"
    topics = sorted(
        data["topic_list"]["topics"],
        key=lambda t: t.get("created_at") or "",
        reverse=True,
    )
    items = []
    for topic in topics[:MAX_ITEMS_PER_SOURCE]:
        url = f"{base}/t/{topic['slug']}/{topic['id']}"
        items.append({
            "id": item_id(url),
            "title": clean_text(topic["title"]),
            "url": url,
            "date": (topic.get("created_at") or "")[:10],
            "content": clean_text(topic.get("excerpt") or "")[:CONTENT_MAX_CHARS],
        })
    return items


def parse_google_ads(source):
    """단일 페이지 누적형 릴리즈 노트 — 'v25 (2026-07-22)' 형식 헤딩 단위로 아이템화.

    - 2026-08 구조 변경: 릴리즈 헤딩이 h2 → h3로 내려가고, h2는 'v25 major version' 같은
      버전 그룹 헤더로만 쓰인다. 재변경 대비해 h2/h3 둘 다 훑는다 (앵커 id 체계는 동일해
      기존 seen id가 그대로 유효).
    - 'Archived release notes' 이후 헤딩은 과거 버전 링크 모음이라 제외.
    - Google은 같은 수정사항을 지원 버전 전체에 백포트해 본문이 사실상 동일한 항목이 반복된다
      (v23.3 / v22.2). 본문에 자기 버전 문자열이 박혀 있어 그대로는 해시가 갈리므로,
      버전 토큰을 vX로 치환한 뒤 해시해 중복을 제거하고 최신 버전 1건만 남긴다.
    - 문서 순서는 버전 내림차순이라 날짜 순이 아니다 → 날짜 desc 정렬 후 상위 N건.
    """
    soup = BeautifulSoup(fetch(source["url"]), "html.parser")
    heading_re = re.compile(r"^v([\d.]+)\s*\((\d{4}-\d{2}-\d{2})\)")
    items = []
    seen_content = set()
    for h in soup.find_all(["h2", "h3"]):
        if h.get("id") == "archived-release-notes":
            break
        text = clean_text(h.get_text())
        m = heading_re.match(text)
        if not m or not h.get("id"):
            continue
        url = f"{source['url']}#{h['id']}"
        # 다음 릴리즈 헤딩 전까지의 형제 노드 텍스트를 본문으로 수집 (h4 하위 섹션 포함)
        parts = []
        for sib in h.find_next_siblings():
            if sib.name in ("h2", "h3"):
                break
            parts.append(sib.get_text(" ", strip=True))
        content = clean_text(" ".join(parts))[:CONTENT_MAX_CHARS]
        if content:
            normalized = re.sub(r"\bv\d+(?:\.\d+)*\b", "vX", content)
            fingerprint = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
            if fingerprint in seen_content:
                continue  # 백포트 중복 — 문서상 첫 번째(최신 버전)만 유지
            seen_content.add(fingerprint)
        items.append({
            "id": item_id(url),
            "title": text,
            "url": url,
            "date": m.group(2),
            "content": content,
            "_version": tuple(int(n) for n in m.group(1).split(".") if n),
        })
    items.sort(key=lambda it: (it["date"], it["_version"]), reverse=True)
    for it in items:
        del it["_version"]
    return items[:MAX_ITEMS_PER_SOURCE]


def parse_meta_marketing(source):
    """Graph API changelog — 버전 단위(changelog/versionXX.0 링크)로 아이템화."""
    soup = BeautifulSoup(fetch(source["url"]), "html.parser")
    seen_urls = {}
    for a in soup.select('a[href*="/docs/graph-api/changelog/version"]'):
        href = a.get("href", "")
        m = re.search(r"/changelog/(version[\d.]+)", href)
        if not m:
            continue
        url = urljoin("https://developers.facebook.com", href.split("#")[0].split("?")[0])
        version = m.group(1).replace("version", "v")
        seen_urls.setdefault(url, version)
    # 버전 내림차순 정렬 후 최신 10건
    def ver_key(pair):
        nums = re.findall(r"\d+", pair[1])
        return tuple(int(n) for n in nums) if nums else (0,)
    items = []
    for url, version in sorted(seen_urls.items(), key=ver_key, reverse=True)[:MAX_ITEMS_PER_SOURCE]:
        items.append({
            "id": item_id(url),
            "title": f"Graph API Changelog {version}",
            "url": url,
            "date": "",  # 목록 페이지에 날짜 노출 없음 (본문 fetch 단계에서 보강 시도 안 함)
            "content": "",
        })
    return items


def parse_criteo(source):
    """Marketing Solutions API Changelog — 변경 항목 h2 단위.

    2026-08 URL 이관: .../docs/release-notes(404) → .../changelog/changelog.
    상위 .../changelog 페이지는 버전 단위 요약이고 h2 id가 렌더링마다 바뀌는 난수라 쓸 수 없다
    (id가 바뀌면 sha1(url)도 바뀌어 같은 공지가 매번 신규로 잡힌다).
    이 페이지는 'product-boost' 같은 안정적인 슬러그 id를 쓰므로 아이템 단위 추적이 가능하다.
    페이지에 날짜 표기가 없어 date는 빈 값 — 새 버전이 나오면 항목이 통째로 교체된다.
    """
    soup = BeautifulSoup(fetch(source["url"]), "html.parser")
    main = soup.find("main") or soup.body
    items = []
    for h in main.find_all(["h2", "h3"]):
        text = clean_text(h.get_text()).lstrip("​").strip()
        hid = h.get("id")
        if not text or not hid or hid == "page-title" or "not found" in text.lower():
            continue
        url = f"{source['url']}#{hid}"
        parts = []
        for sib in h.find_next_siblings():
            if sib.name in ("h1", "h2", "h3"):
                break
            parts.append(sib.get_text(" ", strip=True))
        items.append({
            "id": item_id(url),
            "title": text,
            "url": url,
            "date": "",
            "content": clean_text(" ".join(parts))[:CONTENT_MAX_CHARS],
        })
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break
    return items


def parse_tiktok(source):
    """TikTok 포털 — Next.js JS 렌더링이라 requests로 파싱 불가. enabled: false."""
    return []


PARSERS = {
    "parse_naver_searchad": parse_naver_searchad,
    "parse_naver_gfa": parse_naver_gfa,
    "parse_kakao_devtalk": parse_kakao_devtalk,
    "parse_google_ads": parse_google_ads,
    "parse_meta_marketing": parse_meta_marketing,
    "parse_criteo": parse_criteo,
    "parse_tiktok": parse_tiktok,
}


# ---------------------------------------------------------------------------
# 본문 보강 — content/date가 비어 있는 신규 아이템은 상세 페이지 fetch 시도
# ---------------------------------------------------------------------------

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
RELEASED_RE = re.compile(
    r"Released\s+(" + "|".join(MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE
)


def extract_release_date(text: str) -> str:
    """상세 페이지의 'Released July 29, 2026' 표기를 ISO 날짜로.

    Meta Graph API changelog는 목록에 날짜가 없고 버전 페이지에만 릴리즈 날짜가 있다.
    """
    m = RELEASED_RE.search(text)
    if not m:
        return ""
    return f"{int(m.group(3)):04d}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"


def enrich_item(item):
    """상세 페이지를 받아 비어 있는 content·date를 채운다 (신규 아이템에만 호출)."""
    try:
        soup = BeautifulSoup(fetch(item["url"]), "html.parser")
        main = (
            soup.select_one('article div[class*="markdown"]')
            or soup.find("article")
            or soup.find("main")
            or soup.body
        )
        if not main:
            return
        text = clean_text(main.get_text(" ", strip=True))
        if not item.get("content"):
            item["content"] = text[:CONTENT_MAX_CHARS]
        if not item.get("date"):
            item["date"] = extract_release_date(text)
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] 본문 수집 실패 ({item['url']}): {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def load_seen():
    if SEEN_FILE.exists():
        raw = SEEN_FILE.read_text(encoding="utf-8").strip()
        if raw:
            return json.loads(raw)
    return {}


def main():
    sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    seen = load_seen()
    all_new = []
    health = {"unhealthy": [], "healthy": []}

    def mark_unhealthy(source, reason):
        """수집 실패·0건 소스를 기록 — report_health.py가 GitHub 이슈로 올린다."""
        health["unhealthy"].append({
            "id": source["id"],
            "name": source["name"],
            "url": source["url"],
            "reason": reason,
        })

    for source in sources:
        sid = source["id"]
        if not source.get("enabled", True):
            print(f"[skip] {sid} (enabled: false)")
            continue

        parser = PARSERS.get(source["parser"])
        if parser is None:
            print(f"[warn] {sid}: 파서 {source['parser']} 미정의 — 스킵", file=sys.stderr)
            mark_unhealthy(source, f"파서 {source['parser']} 미정의")
            continue

        try:
            items = parser(source)
        except Exception as exc:  # noqa: BLE001 — 네트워크/파싱 실패 소스는 경고 후 스킵
            print(f"[warn] {sid}: 수집 실패 — {exc}", file=sys.stderr)
            mark_unhealthy(source, f"수집 실패 — {exc}")
            continue

        if not items:
            # 사이트 구조 변경 시 예외 없이 0건이 되므로 반드시 이상 신호로 남긴다
            print(f"[warn] {sid}: 0건 파싱 — 사이트 구조 변경 의심", file=sys.stderr)
            mark_unhealthy(source, "파싱 0건 (사이트 구조 변경 의심)")
            continue

        health["healthy"].append(sid)
        print(f"[ok] {sid}: {len(items)}건 파싱")
        for it in items:
            print(f"     - ({it['date'] or '날짜없음'}) {it['title'][:70]} | {it['url']}")

        seen_ids = seen.get(sid)
        if seen_ids is None:
            # 초기화: 이 소스의 첫 수집 — 전체를 seen 처리만 하고 알림 대상 제외
            seen[sid] = [it["id"] for it in items]
            print(f"     → 최초 실행: {len(items)}건 seen 초기화 (알림 제외)")
            continue

        new_items = [it for it in items if it["id"] not in seen_ids]
        if new_items:
            print(f"     → 신규 {len(new_items)}건")
            for it in new_items:
                if not it["content"] or not it["date"]:
                    enrich_item(it)
                all_new.append({
                    "id": it["id"],
                    "source_id": sid,
                    "source_name": source["name"],
                    "title": it["title"],
                    "url": it["url"],
                    "date": it["date"],
                    "content": it["content"],
                })
            seen[sid] = ([it["id"] for it in new_items] + seen_ids)[:SEEN_LIMIT_PER_SOURCE]

    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(
        json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if health["unhealthy"]:
        print(f"\n[warn] 이상 소스 {len(health['unhealthy'])}건 → {HEALTH_FILE.relative_to(ROOT)}", file=sys.stderr)

    if all_new:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        NEW_ITEMS_FILE.write_text(
            json.dumps(all_new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\n신규 공지 {len(all_new)}건 → {NEW_ITEMS_FILE.relative_to(ROOT)}")
    else:
        NEW_ITEMS_FILE.unlink(missing_ok=True)  # 이전 실행 잔여물 제거
        print("\n신규 공지 없음")


if __name__ == "__main__":
    main()

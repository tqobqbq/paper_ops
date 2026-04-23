from __future__ import annotations

import feedparser


def filter_arxiv_candidates(
    candidates: list[dict[str, str]], keywords: list[str]
) -> list[dict[str, str]]:
    normalized_keywords = [keyword.lower() for keyword in keywords]
    filtered: list[dict[str, str]] = []

    for candidate in candidates:
        haystack = f"{candidate.get('title', '')} {candidate.get('summary', '')}".lower()
        if any(keyword in haystack for keyword in normalized_keywords):
            filtered.append(candidate)

    return filtered


def parse_feed_entries(feed_url: str) -> list[dict[str, str]]:
    feed = feedparser.parse(feed_url)
    normalized_entries: list[dict[str, str]] = []

    for entry in getattr(feed, "entries", []):
        normalized_entries.append(
            {
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "link": entry.get("link", ""),
            }
        )

    return normalized_entries

from paper_ops.discovery import filter_arxiv_candidates, parse_feed_entries


def test_filter_arxiv_candidates_keeps_only_keyword_matches():
    candidates = [
        {
            "title": "Difference Predictive Coding for Training Spiking Neural Networks",
            "summary": "A biologically inspired learning rule for efficient SNN training.",
            "link": "https://arxiv.org/abs/2601.00001",
        },
        {
            "title": "Vision Transformer Scaling Laws",
            "summary": "Analyzing large-scale transformer behavior.",
            "link": "https://arxiv.org/abs/2601.00002",
        },
    ]

    filtered = filter_arxiv_candidates(candidates, keywords=["Predictive Coding"])

    assert filtered == [candidates[0]]


def test_parse_feed_entries_normalizes_feedparser_output(monkeypatch):
    class FakeFeed:
        entries = [
            {
                "title": "Paper A",
                "summary": "Summary A",
                "link": "https://arxiv.org/abs/2601.10001",
            },
            {
                "title": "Paper B",
            },
        ]

    def fake_parse(url):
        assert url == "https://example.com/feed.xml"
        return FakeFeed()

    monkeypatch.setattr("paper_ops.discovery.feedparser.parse", fake_parse)

    entries = parse_feed_entries("https://example.com/feed.xml")

    assert entries == [
        {
            "title": "Paper A",
            "summary": "Summary A",
            "link": "https://arxiv.org/abs/2601.10001",
        },
        {
            "title": "Paper B",
            "summary": "",
            "link": "",
        },
    ]

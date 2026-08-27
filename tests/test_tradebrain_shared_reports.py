from backend.tradebrain.shared_reports import (
    analyst_for_report,
    merge_shared_report_snapshot,
    missing_required_reports,
)


def test_report_from_earlier_stream_chunk_is_not_erased_by_later_chunk():
    observed = {}
    merge_shared_report_snapshot(observed, {"market_report": "Market complete"})
    merge_shared_report_snapshot(observed, {"news_report": "News complete"})
    merge_shared_report_snapshot(observed, {"messages": ["clear"]})
    merge_shared_report_snapshot(observed, {"fundamentals_report": "Fundamentals complete"})

    assert observed["market_report"] == "Market complete"
    assert observed["news_report"] == "News complete"
    assert observed["fundamentals_report"] == "Fundamentals complete"
    assert missing_required_reports(
        ["market", "news", "fundamentals"], observed
    ) == []


def test_blank_news_report_remains_missing_and_maps_to_news_analyst():
    observed = {
        "market_report": "Market complete",
        "news_report": "   ",
        "fundamentals_report": "Fundamentals complete",
    }

    missing = missing_required_reports(
        ["market", "news", "fundamentals"], observed
    )
    assert missing == ["news_report"]
    assert analyst_for_report(missing[0]) == "news"


def test_new_nonempty_report_replaces_older_report_and_notifies_once_per_change():
    observed = {}
    events = []

    merge_shared_report_snapshot(
        observed,
        {"news_report": "First news synthesis"},
        on_report=lambda field, text: events.append((field, text)),
    )
    merge_shared_report_snapshot(
        observed,
        {"news_report": "First news synthesis"},
        on_report=lambda field, text: events.append((field, text)),
    )
    merge_shared_report_snapshot(
        observed,
        {"news_report": "Repaired news synthesis"},
        on_report=lambda field, text: events.append((field, text)),
    )

    assert observed["news_report"] == "Repaired news synthesis"
    assert events == [
        ("news_report", "First news synthesis"),
        ("news_report", "Repaired news synthesis"),
    ]


def test_unselected_social_report_is_not_required():
    reports = {
        "market_report": "Market complete",
        "news_report": "News complete",
        "fundamentals_report": "Fundamentals complete",
    }
    assert missing_required_reports(
        ["market", "news", "fundamentals"], reports
    ) == []

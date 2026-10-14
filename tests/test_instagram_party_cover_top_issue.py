from instagram.projects.party_issue_monthly_profile_v2.adapter_top_issue import (
    TOP_ISSUE_LABEL_PLURAL,
    TOP_ISSUE_LABEL_SINGULAR,
    TOP_ISSUE_LABEL_Y,
    TOP_ISSUE_METRICS,
    TOP_ISSUE_VALUE_Y,
    _top_issue_label,
    _top_issues,
)


def test_top_issues_take_first_ranked_issue_from_each_chart() -> None:
    issues = _top_issues(
        {
            "raw_counts": [
                {"canonical_label": "transportation", "label": "Transportation", "value": 5},
                {"canonical_label": "health", "label": "Health", "value": 3},
            ],
            "share_vs_average": [
                {"canonical_label": "housing", "label": "Housing", "value": 6.2},
            ],
            "per_td_vs_average": [
                {"canonical_label": "energy", "label": "Energy", "value": 1.3},
            ],
        }
    )
    assert issues == ["Transportation", "Housing", "Energy"]


def test_top_issues_dedupe_across_all_three_charts_in_metric_order() -> None:
    issues = _top_issues(
        {
            "raw_counts": [{"canonical_label": "health", "label": "Health", "value": 10}],
            "share_vs_average": [{"canonical_label": "health", "label": "Health", "value": 3.1}],
            "per_td_vs_average": [{"canonical_label": "housing", "label": "Housing", "value": 0.8}],
        }
    )
    assert issues == ["Health", "Housing"]


def test_top_issues_all_same_returns_one_issue() -> None:
    party = {
        metric: [{"canonical_label": "energy", "label": "Energy", "value": 1}]
        for metric in TOP_ISSUE_METRICS
    }
    assert _top_issues(party) == ["Energy"]
    assert _top_issue_label(_top_issues(party)) == TOP_ISSUE_LABEL_SINGULAR


def test_top_issue_label_pluralizes_for_two_or_three_unique_issues() -> None:
    assert _top_issue_label(["Health", "Housing"]) == TOP_ISSUE_LABEL_PLURAL
    assert _top_issue_label(["Health", "Housing", "Energy"]) == TOP_ISSUE_LABEL_PLURAL


def test_top_issue_callout_keeps_approved_geometry() -> None:
    assert TOP_ISSUE_LABEL_Y == 215
    assert TOP_ISSUE_VALUE_Y == 264

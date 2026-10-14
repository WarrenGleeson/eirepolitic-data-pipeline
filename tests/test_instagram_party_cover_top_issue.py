from instagram.projects.party_issue_monthly_profile_v2.adapter_top_issue import (
    TOP_ISSUE_LABEL,
    TOP_ISSUE_LABEL_Y,
    TOP_ISSUE_VALUE_Y,
    _top_issue,
)


def test_top_issue_uses_first_ranked_raw_count() -> None:
    issue, count = _top_issue(
        {
            "raw_counts": [
                {"label": "Transportation", "value": 5},
                {"label": "Health", "value": 3},
            ]
        }
    )
    assert issue == "Transportation"
    assert count == 5


def test_top_issue_empty_state_is_truthful() -> None:
    issue, count = _top_issue({"raw_counts": []})
    assert issue == "No classified issues"
    assert count == 0


def test_top_issue_callout_matches_approved_mockup_geometry() -> None:
    assert TOP_ISSUE_LABEL == "MOST DISCUSSED ISSUE"
    assert TOP_ISSUE_LABEL_Y == 215
    assert TOP_ISSUE_VALUE_Y == 264

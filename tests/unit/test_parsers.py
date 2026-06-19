from familylink.parsers import (
    parse_apps_and_usage,
    parse_members_response,
    parse_time_limit,
)


def test_parse_members_response_extracts_user_id():
    raw = [
        [
            [
                "child1",
                None,
                3,
                ["Alice", None, "", "alice@g.com", "Smith", "Alice", None, None, ""],
                "1",
                None,
                None,
                None,
                None,
                None,
                None,
                [True, False],
            ]
        ],
        [None, "99999"],
        "parent_id",
    ]
    result = parse_members_response(raw)
    assert result["myUserId"] == "parent_id"
    assert result["members"][0]["userId"] == "child1"
    assert result["members"][0]["profile"]["displayName"] == "Alice"
    assert result["members"][0]["role"] == "member"


def test_parse_members_response_empty():
    result = parse_members_response([[], [None, "0"], "p1"])
    assert result["members"] == []
    assert result["myUserId"] == "p1"


def test_parse_apps_and_usage_empty_lists():
    raw = [[None, "1"], [], "0", [], None, None, []]
    result = parse_apps_and_usage(raw)
    assert result["apps"] == []
    assert result["deviceInfo"] == []
    assert result["appUsageSessions"] == []


def test_parse_time_limit_empty_returns_empty_dict():
    result = parse_time_limit([])
    assert result == {}


def test_parse_time_limit_has_day_keys_as_ints():
    # Minimal structure: one downtime entry for day 1 (Monday)
    raw = [
        None,
        [
            [None, [[None, 1, None, [21, 0], [7, 0]]]],  # downtime block
            [[None, None, [[None, 1, None, 120]]]],  # screen time block
        ],
    ]
    result = parse_time_limit(raw)
    assert 1 in result
    assert result[1]["avail_start"] == "07:00"
    assert result[1]["avail_end"] == "21:00"
    assert result[1]["screen_mins"] == 120

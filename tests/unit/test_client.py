"""Unit tests for FamilyLink client public API."""

import json

import pytest

from familylink import FamilyLink, SessionExpiredError

MINIMAL_COOKIES = (
    "# Netscape HTTP Cookie File\n"
    ".google.com\tTRUE\t/\tTRUE\t9999999999\tSAPISID\ttest_sapisid\n"
    ".google.com\tTRUE\t/\tTRUE\t9999999999\tSID\tsid_value\n"
)

BASE = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"


@pytest.fixture
def client(monkeypatch, tmp_path):
    """FamilyLink client wired to a temp cookie file with no browser/env auth."""
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(MINIMAL_COOKIES)
    monkeypatch.delenv("FAMILYLINK_COOKIES_B64", raising=False)
    monkeypatch.delenv("FAMILYLINK_SAPISID", raising=False)
    return FamilyLink(browser="txt", cookie_file_path=cookie_file)


def test_get_members_parses_list_response(client, httpx_mock):
    """get_members() parses the raw list response into a MembersResponse."""
    httpx_mock.add_response(
        url=f"{BASE}/families/mine/members",
        json=[
            [
                [
                    "child1",
                    None,
                    3,
                    [
                        "Alice",
                        None,
                        "",
                        "alice@g.com",
                        "Smith",
                        "Alice",
                        None,
                        None,
                        "",
                    ],
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
            [None, "12345"],
            "parent1",
        ],
    )
    result = client.get_members()
    assert result.my_user_id == "parent1"
    assert result.members[0].user_id == "child1"
    assert result.members[0].profile.display_name == "Alice"


def test_get_members_raises_on_401(client, httpx_mock):
    """get_members() raises SessionExpiredError on a 401 response."""
    httpx_mock.add_response(url=f"{BASE}/families/mine/members", status_code=401)
    with pytest.raises(SessionExpiredError):
        client.get_members()


def test_get_members_raises_on_403(client, httpx_mock):
    """get_members() raises SessionExpiredError on a 403 response."""
    httpx_mock.add_response(url=f"{BASE}/families/mine/members", status_code=403)
    with pytest.raises(SessionExpiredError):
        client.get_members()


def test_set_app_limit_posts_to_correct_endpoint(client, httpx_mock):
    """set_app_limit() POSTs to the apps:updateRestrictions endpoint with the right body."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/people/child1/apps:updateRestrictions",
        json={},
    )
    client.set_app_limit("com.google.android.youtube", 30, child_id="child1")
    request = httpx_mock.get_requests()[-1]
    assert "/people/child1/apps:updateRestrictions" in str(request.url)
    body = json.loads(request.content)
    assert body[0] == "child1"
    assert "com.google.android.youtube" in str(body)
    assert 30 in body[1][0][2]


def test_block_app_posts_to_correct_endpoint(client, httpx_mock):
    """block_app() POSTs to the apps:updateRestrictions endpoint."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/people/child1/apps:updateRestrictions",
        json={},
    )
    client.block_app("com.google.android.youtube", child_id="child1")
    request = httpx_mock.get_requests()[-1]
    assert "/people/child1/apps:updateRestrictions" in str(request.url)
    body = json.loads(request.content)
    assert body[0] == "child1"
    assert "com.google.android.youtube" in str(body)


def test_always_allow_app(client, httpx_mock):
    """always_allow_app() POSTs to the apps:updateRestrictions endpoint."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/people/child1/apps:updateRestrictions",
        json={},
    )
    client.always_allow_app("com.google.android.youtube", child_id="child1")
    request = httpx_mock.get_requests()[-1]
    assert "/people/child1/apps:updateRestrictions" in str(request.url)
    body = json.loads(request.content)
    assert body[0] == "child1"
    assert "com.google.android.youtube" in str(body)


def test_remove_app_limit(client, httpx_mock):
    """remove_app_limit() POSTs to the apps:updateRestrictions endpoint."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/people/child1/apps:updateRestrictions",
        json={},
    )
    client.remove_app_limit("com.google.android.youtube", child_id="child1")
    request = httpx_mock.get_requests()[-1]
    assert "/people/child1/apps:updateRestrictions" in str(request.url)
    body = json.loads(request.content)
    assert body[0] == "child1"
    assert "com.google.android.youtube" in str(body)

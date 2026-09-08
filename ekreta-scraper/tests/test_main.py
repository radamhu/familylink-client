"""Tests for the main module's run() and main() functions."""

from config import Kid
from main import run


def make_kid(child_id: str) -> Kid:
    """Create a fake Kid for testing."""
    return Kid(
        child_id=child_id,
        username=f'{child_id}-user',
        password='pw',
        institution_code='035120',
    )


def test_run_posts_entries_for_each_kid():
    """Test that run() calls post_fn for each kid with correct args."""
    kids = [make_kid('child1'), make_kid('child2')]
    fake_entries = {'child1': [{'subject': 'Matek'}], 'child2': []}
    posted = []

    def fake_post(api_url, token, child_id, entries):
        posted.append((api_url, token, child_id, entries))

    exit_code = run(
        kids=kids,
        api_url='http://familylink-web:8000',
        token='secret',
        fetch_fn=lambda kid: fake_entries[kid.child_id],
        post_fn=fake_post,
    )

    assert exit_code == 0
    assert posted == [
        (
            'http://familylink-web:8000',
            'secret',
            'child1',
            [{'subject': 'Matek'}],
        ),
        ('http://familylink-web:8000', 'secret', 'child2', []),
    ]


def test_run_continues_after_one_kid_fails():
    """Test that run() continues processing after one kid's fetch fails."""
    kids = [make_kid('child1'), make_kid('child2')]
    posted = []

    def fetch_fn(kid):
        if kid.child_id == 'child1':
            raise RuntimeError('login failed')
        return []

    exit_code = run(
        kids=kids,
        api_url='http://familylink-web:8000',
        token='secret',
        fetch_fn=fetch_fn,
        post_fn=lambda *args: posted.append(args),
    )

    assert exit_code == 1
    assert len(posted) == 1
    assert posted[0][2] == 'child2'


def test_run_continues_after_one_kid_post_fails():
    """Test that run() continues processing after one kid's post_fn fails."""
    kids = [make_kid('child1'), make_kid('child2')]
    posted = []

    def post_fn(api_url, token, child_id, entries):
        if child_id == 'child1':
            raise RuntimeError('API unreachable')
        posted.append((api_url, token, child_id, entries))

    exit_code = run(
        kids=kids,
        api_url='http://familylink-web:8000',
        token='secret',
        fetch_fn=lambda kid: [],
        post_fn=post_fn,
    )

    assert exit_code == 1
    assert len(posted) == 1
    assert posted[0][2] == 'child2'


def test_run_all_succeed_returns_zero():
    """Test that run() returns 0 when all kids succeed."""
    kids = [make_kid('child1')]
    exit_code = run(
        kids=kids,
        api_url='http://familylink-web:8000',
        token='secret',
        fetch_fn=lambda kid: [],
        post_fn=lambda *args: None,
    )
    assert exit_code == 0

from datetime import datetime, timezone
from pathlib import Path

import pytest

from gamebuddy.context import load_game_context
from gamebuddy.journal import to_html
from gamebuddy.schemas import SCHEMA_VERSION, Boundary, GameState

FIXTURES = Path(__file__).parent / "fixtures" / "games"


@pytest.fixture
def sample():
    return load_game_context(FIXTURES, "sample")


def _state(observed: set[str], declared: str | None = None) -> GameState:
    return GameState(
        schema_version=SCHEMA_VERSION,
        game_id="sample",
        last_synced=datetime(2026, 5, 25, tzinfo=timezone.utc),
        boundary=Boundary(observed=set(observed), declared=declared),
    )


def test_empty_state_shows_notice(sample):
    out = to_html(sample, None)
    assert "Nothing logged yet" in out
    assert 'class="grid"' not in out


def test_observed_card_has_full_title_and_body(sample):
    out = to_html(sample, _state({"a"}))
    # Card with observed class, full title, body text from entity MD.
    assert 'class="card observed"' in out
    assert ">A<" in out  # _humanize_id("a") → "A"
    # The entity body's first paragraph must appear (sample entity bodies have
    # at least one line). The body div is present.
    assert '<div class="body">' in out


def test_frontier_card_is_masked_and_sourced(sample):
    out = to_html(sample, _state({"a"}))
    # b and c are frontier, masked as "Rumor #1 — boss" / "Rumor #2 — boss".
    assert "Rumor #1 — boss" in out
    assert "Rumor #2 — boss" in out
    # The actual frontier node ids must NOT appear as standalone titles.
    # (They might appear in the leads list of A but only via masked label.)
    assert ">B<" not in out
    assert ">C<" not in out
    # Frontier body cites the observed source.
    assert "Rumored from: A" in out


def test_leads_list_masks_frontier_targets(sample):
    out = to_html(sample, _state({"a"}))
    # A's card lists b and c as leads, both as masked rumor handles.
    assert 'class="frontier">Rumor #1 — boss</li>' in out
    assert 'class="frontier">Rumor #2 — boss</li>' in out


def test_leads_omit_gated_targets(sample):
    # With only `a` observed, d/e/f are gated; B's would-be `leads to d/f` are
    # all gated. But since b itself is frontier, it has no body and no leads
    # rendered for it as an observed card. Use a richer observed set.
    out = to_html(sample, _state({"a", "b", "c"}))
    # Now d is frontier (b → d requires; c → d suggests). f is frontier too
    # (b,c → f requires). e is gated (requires d).
    # b's leads include d (frontier) and f (frontier) — both shown.
    # Critically, no leads should reference e (gated) without reveal.
    assert "E (gated)" not in out
    assert '"gated"' not in out  # no gated cards rendered without reveal


def test_reveal_unmasks_and_renders_gated(sample):
    out = to_html(sample, _state({"a"}), reveal=True)
    # Frontier and gated both render with real ids in reveal mode.
    assert ">B<" in out
    assert ">D<" in out
    assert ">E<" in out
    assert "Rumor #" not in out
    assert "reveal mode" in out


def test_declared_promotes_to_observed(sample):
    out = to_html(sample, _state(set(), declared="d"))
    # declared=d pulls ancestors {a, b}. So observed includes a, b, d.
    assert 'class="card observed"' in out
    # e becomes frontier.
    assert "Rumor #" in out  # at least one frontier card with handle


def test_stats_line_reflects_counts(sample):
    out = to_html(sample, _state({"a"}))
    # 1 observed, 2 frontier (b, c), 3 gated (d, e, f).
    assert "Observed: 1" in out
    assert "Frontier: 2" in out
    assert "Gated: 3" in out


def test_sekiro_journal_smoke():
    sekiro = load_game_context(Path("games"), "sekiro")
    blank = to_html(sekiro, None)
    assert "Nothing logged yet" in blank
    full = to_html(sekiro, None, reveal=True)
    # In reveal mode every node yields a card.
    for n_id in sekiro.dag.nodes:
        # Title-cased ids appear in the rendered cards.
        assert n_id.replace("_", " ").title() in full

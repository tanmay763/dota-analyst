"""Live Stratz (ADR 0001): read-only queries, cached per user, summarized, aggregated.

Ported from ../dota/tests/test_web_stratz.py, plus the per-user changes (ADR 0002, 0004):
the caller's token, per-user cache namespaces and SQL across several datasets.
"""

import json

import httpx
import pytest

from dota_analyst_mcp import stratz
from dota_analyst_mcp.stratz import CACHE_TTL_SECONDS, ROW_CAP, StratzToolError

TOKEN = "test-token"
WIN_WEEK = """
query ($weeks: Int) {
  heroStats {
    winWeek(take: $weeks, gameModeIds: [ALL_PICK_RANKED]) { week heroId matchCount winCount }
  }
}
"""
WIN_WEEK_DATA = {
    "heroStats": {
        "winWeek": [
            {"week": 100, "heroId": 1, "matchCount": 50, "winCount": 30},
            {"week": 100, "heroId": 2, "matchCount": 40, "winCount": 10},
            {"week": 200, "heroId": 1, "matchCount": 60, "winCount": 33},
        ]
    }
}
HEROES = "{ constants { heroes { id displayName } } }"
HEROES_DATA = {
    "constants": {
        "heroes": [
            {"id": 1, "displayName": "Anti-Mage"},
            {"id": 2, "displayName": "Axe"},
        ]
    }
}


# --- read-only guard --------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "{ constants { heroes { id } } }",
        "query { heroStats { winWeek { heroId } } }",
        WIN_WEEK,
        # An enum value spelled MUTATION and a string mentioning mutation are not operations.
        'query { x(kind: MUTATION, note: "mutation { y }") { id } }',
        "# mutation in a comment\nquery Q { a { b } }\nfragment F on T { c }",
    ],
)
def test_read_only_queries_are_allowed(query):
    stratz.check_read_only(query)


@pytest.mark.parametrize(
    "query",
    [
        "mutation { doSomething { id } }",
        "subscription { liveMatch { id } }",
        "query A { a { b } }\nmutation B { c { d } }",
        "",
    ],
)
def test_writes_and_subscriptions_are_refused(query):
    with pytest.raises(StratzToolError):
        stratz.check_read_only(query)


# --- cache key --------------------------------------------------------------------------


def test_cache_key_ignores_whitespace_and_variable_order():
    a = stratz.cache_key("query { a  {\n b } }", {"x": 1, "y": 2})
    b = stratz.cache_key("query { a { b } }", {"y": 2, "x": 1})
    assert a == b and len(a) == 12


def test_cache_key_depends_on_variables():
    assert stratz.cache_key(WIN_WEEK, {"weeks": 1}) != stratz.cache_key(
        WIN_WEEK, {"weeks": 2}
    )


# --- fetch ------------------------------------------------------------------------------


def test_fetch_returns_a_shape_summary_not_the_data(live, stratz):
    calls, queue = stratz
    queue.append((200, {"data": WIN_WEEK_DATA}))
    summary = live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})
    ((table,),) = [summary["tables"]]
    assert table["table"] == "heroStats_winWeek"
    assert table["rows"] == 3
    assert table["columns"] == ["week", "heroId", "matchCount", "winCount"]
    assert len(table["sample"]) == 3  # up to 5 sample rows
    assert summary["cached"] is False
    assert calls[0]["json"] == {"query": WIN_WEEK, "variables": {"weeks": 2}}
    assert calls[0]["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_an_identical_fetch_is_served_from_the_cache(live, stratz):
    calls, queue = stratz
    queue.append((200, {"data": WIN_WEEK_DATA}))
    first = live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})
    second = live.fetch(
        TOKEN,
        "query ($weeks: Int) {heroStats {winWeek(take: $weeks, gameModeIds: [ALL_PICK_RANKED]) { week heroId matchCount winCount }}}",
        {"weeks": 2},
    )
    assert len(calls) == 1
    assert second["dataset"] == first["dataset"] and second["cached"] is True


def test_users_never_share_cached_data(live, stratz):
    calls, queue = stratz
    queue.extend([(200, {"data": WIN_WEEK_DATA}), (200, {"data": WIN_WEEK_DATA})])
    first = live.fetch("alice", WIN_WEEK, {"weeks": 2})
    second = live.fetch("bob", WIN_WEEK, {"weeks": 2})
    assert len(calls) == 2 and second["cached"] is False
    assert calls[1]["headers"]["Authorization"] == "Bearer bob"
    # Bob can't aggregate over Alice's dataset either, though the handle is the same.
    assert first["dataset"] == second["dataset"]
    live.aggregate("bob", {"w": second["dataset"]}, "SELECT 1")
    with pytest.raises(StratzToolError, match="fetch"):
        live.aggregate("carol", {"w": first["dataset"]}, "SELECT 1")


def test_the_cache_keeps_no_trace_of_the_token(live, stratz, store):
    _, queue = stratz
    queue.append((200, {"data": WIN_WEEK_DATA}))
    live.fetch("secret-token-value", WIN_WEEK, {"weeks": 2})
    paths = [str(p) for p in store.root.rglob("*")]
    assert paths and not any("secret-token-value" in p for p in paths)


def test_the_cache_expires(live, stratz, clock):
    calls, queue = stratz
    queue.extend([(200, {"data": WIN_WEEK_DATA}), (200, {"data": WIN_WEEK_DATA})])
    live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})
    clock.now += CACHE_TTL_SECONDS + 1
    live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})
    assert len(calls) == 2


def test_graphql_errors_go_straight_back_to_the_model_uncached(live, stratz):
    calls, queue = stratz
    queue.append(
        (
            200,
            {
                "errors": [
                    {
                        "message": 'Cannot query field "winWeak" on type "HeroStatsQuery".'
                    }
                ]
            },
        )
    )
    with pytest.raises(StratzToolError, match="winWeak"):
        live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})
    assert len(calls) == 1  # no retries for a query the model must fix
    queue.append((200, {"data": WIN_WEEK_DATA}))
    assert live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})["cached"] is False


def test_transient_failures_are_retried(live, stratz):
    calls, queue = stratz
    queue.extend(
        [httpx.ConnectError("down"), (503, {}), (200, {"data": WIN_WEEK_DATA})]
    )
    assert live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})["tables"][0]["rows"] == 3
    assert len(calls) == 3


def test_a_rejected_token_is_reported_without_retrying(live, stratz):
    calls, queue = stratz
    queue.append((403, {"message": "A Bearer Token is required"}))
    with pytest.raises(StratzToolError, match="rejected the token"):
        live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})
    assert len(calls) == 1


def test_a_cloudflare_challenge_is_named(live, monkeypatch):
    def post(url, **kwargs):
        return httpx.Response(
            403,
            text="<title>Just a moment...</title>",
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(StratzToolError, match="Cloudflare"):
        live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})


def test_a_mutation_is_refused_before_any_request(live, stratz):
    calls, _ = stratz
    with pytest.raises(StratzToolError):
        live.fetch(TOKEN, "mutation { x { y } }")
    assert calls == []


def test_throttling_is_per_user(store):
    waits = []
    live = stratz.LiveStratz(store, sleep=waits.append, min_interval=10)
    live._throttle("alice")
    live._throttle("bob")  # another user: no wait
    assert waits == []
    live._throttle("alice")
    assert len(waits) == 1 and waits[0] > 9


# --- flattening -------------------------------------------------------------------------


def test_nested_lists_become_child_tables_linked_by_parent_row():
    data = {
        "player": {
            "steamAccount": {"name": "Rateezy", "isAnonymous": False},
            "matches": [
                {"id": 7, "players": [{"heroId": 1}, {"heroId": 2}]},
                {"id": 8, "players": [{"heroId": 3}]},
            ],
        }
    }
    tables = stratz.flatten(data)
    assert set(tables) == {"root", "player.matches", "player.matches.players"}
    assert tables["root"].to_dict("records") == [
        {
            "player.steamAccount.name": "Rateezy",
            "player.steamAccount.isAnonymous": False,
        }
    ]
    assert tables["player.matches"].to_dict("records") == [{"id": 7}, {"id": 8}]
    assert tables["player.matches.players"].to_dict("records") == [
        {"_parent": 0, "heroId": 1},
        {"_parent": 0, "heroId": 2},
        {"_parent": 1, "heroId": 3},
    ]


# --- aggregate --------------------------------------------------------------------------


def test_aggregate_runs_sql_over_a_fetched_dataset(live, stratz):
    _, queue = stratz
    queue.append((200, {"data": WIN_WEEK_DATA}))
    dataset = live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})["dataset"]
    result = live.aggregate(
        TOKEN,
        {"w": dataset},
        "SELECT heroId, sum(winCount) * 1.0 / sum(matchCount) AS winRate "
        "FROM w_heroStats_winWeek GROUP BY heroId ORDER BY heroId",
    )
    assert result["columns"] == ["heroId", "winRate"]
    assert result["rows"] == [[1, pytest.approx(63 / 110)], [2, pytest.approx(0.25)]]
    assert result["row_count"] == 2 and result["truncated"] is False


def test_aggregate_joins_across_datasets(live, stratz):
    _, queue = stratz
    queue.extend([(200, {"data": WIN_WEEK_DATA}), (200, {"data": HEROES_DATA})])
    wins = live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})["dataset"]
    heroes = live.fetch(TOKEN, HEROES)["dataset"]
    result = live.aggregate(
        TOKEN,
        {"w": wins, "h": heroes},
        "SELECT h.displayName, sum(w.matchCount) AS picks FROM w_heroStats_winWeek w "
        "JOIN h_constants_heroes h ON h.id = w.heroId GROUP BY 1 ORDER BY 1",
    )
    assert result["rows"] == [["Anti-Mage", 110], ["Axe", 40]]


@pytest.mark.parametrize("alias", ["", "W", "1w", "w-x", "a" * 17])
def test_aggregate_refuses_odd_aliases(live, stratz, alias):
    _, queue = stratz
    queue.append((200, {"data": WIN_WEEK_DATA}))
    dataset = live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})["dataset"]
    with pytest.raises(StratzToolError, match="Alias"):
        live.aggregate(TOKEN, {alias: dataset}, "SELECT 1")


def test_aggregate_returns_at_most_the_row_cap(live, stratz):
    _, queue = stratz
    rows = [
        {"week": 1, "heroId": i, "matchCount": 1, "winCount": 0} for i in range(250)
    ]
    queue.append((200, {"data": {"heroStats": {"winWeek": rows}}}))
    dataset = live.fetch(TOKEN, WIN_WEEK, {"weeks": 1})["dataset"]
    result = live.aggregate(TOKEN, {"w": dataset}, "SELECT * FROM w_heroStats_winWeek")
    assert len(result["rows"]) == ROW_CAP
    assert result["row_count"] == 250 and result["truncated"] is True


def test_aggregate_cannot_read_files_or_urls(live, stratz, tmp_path):
    _, queue = stratz
    queue.append((200, {"data": WIN_WEEK_DATA}))
    dataset = live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})["dataset"]
    secret = tmp_path / "secret.csv"
    secret.write_text("a\n1\n")
    with pytest.raises(StratzToolError):
        live.aggregate(TOKEN, {"w": dataset}, f"SELECT * FROM read_csv('{secret}')")


def test_aggregate_needs_a_fetched_dataset(live):
    with pytest.raises(StratzToolError, match="fetch"):
        live.aggregate(TOKEN, {"w": "0123456789ab"}, "SELECT 1")
    with pytest.raises(StratzToolError, match="fetch"):
        live.aggregate(TOKEN, {"w": "../../etc/passwd"}, "SELECT 1")


def test_bad_sql_is_reported_to_the_model(live, stratz):
    _, queue = stratz
    queue.append((200, {"data": WIN_WEEK_DATA}))
    dataset = live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})["dataset"]
    with pytest.raises(StratzToolError, match="no_such_table"):
        live.aggregate(TOKEN, {"w": dataset}, "SELECT * FROM no_such_table")


# --- schema and cookbook ----------------------------------------------------------------


def test_schema_type_returns_one_definition_block():
    block = stratz.schema_type("HeroStatsQuery")
    assert block.startswith("type HeroStatsQuery ")
    assert block.rstrip().endswith("}")
    assert "winWeek" in block


def test_schema_type_drops_descriptions_unless_asked():
    compact = stratz.schema_type("HeroStatsQuery")
    documented = stratz.schema_type("HeroStatsQuery", docs=True)
    assert '"""' not in compact and '"""' in documented
    assert len(compact) < len(documented) / 4
    assert "winWeek(" in compact and "bracketIds: [RankBracket]" in compact


def test_an_unknown_type_suggests_close_names():
    with pytest.raises(StratzToolError, match="HeroStatsQuery"):
        stratz.schema_type("HeroStatQuery")


def test_schema_search_finds_types_and_root_fields():
    found = stratz.schema_search("herostat")
    assert "HeroStatsQuery" in found["types"]
    assert "heroStats" in found["root_fields"]


def test_cookbook_lists_sections_then_returns_one():
    sections = stratz.cookbook()
    assert "heroStats.winWeek" in sections
    text = stratz.cookbook("heroStats.winWeek")
    assert text.startswith("## heroStats.winWeek")
    assert "take" in text
    assert json.dumps(sections)  # plain, serializable for the model


def test_aggregate_returns_time_zone_aware_timestamps(live, stratz):
    """to_timestamp() gives TIMESTAMPTZ, which DuckDB hands to Python only with pytz."""
    _, queue = stratz
    queue.append((200, {"data": WIN_WEEK_DATA}))
    dataset = live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})["dataset"]
    result = live.aggregate(
        TOKEN,
        {"w": dataset},
        "SELECT to_timestamp(1788998400) AS week_start, now() AS at",
    )
    assert result["rows"][0][0].startswith("2026-09-10")
    assert isinstance(result["rows"][0][1], str)


@pytest.mark.parametrize(
    "message",
    [
        (
            "Argument 'positionIds' has invalid value. In element #1: "
            "[Expected type 'MatchPlayerPositionType', found POSITION_9.]"
        ),
        "Cannot query field 'winWeak' on type 'HeroStatsQuery'. Did you mean 'winWeek' or 'winDay'?",
    ],
)
def test_validation_errors_sent_as_400_reach_the_model(live, stratz, message):
    """Stratz answers GraphQL validation errors with HTTP 400 and an `errors` body
    (GraphQL over HTTP), not 200: the model needs the message to fix its query."""
    calls, queue = stratz
    queue.append((400, {"errors": [{"message": message, "extensions": {"code": "X"}}]}))
    with pytest.raises(StratzToolError) as info:
        live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})
    assert message in str(info.value) and "rejected the query" in str(info.value)
    assert len(calls) == 1  # not retried
    queue.append((200, {"data": WIN_WEEK_DATA}))
    assert live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})["cached"] is False  # not cached


def test_an_unrecognised_rejection_quotes_what_stratz_said(live, stratz):
    calls, queue = stratz
    queue.append((403, {"message": "Some new reason Stratz refuses this request"}))
    with pytest.raises(StratzToolError, match="Some new reason Stratz refuses") as info:
        live.fetch(TOKEN, WIN_WEEK, {"weeks": 2})
    assert "status=403" in str(info.value) and TOKEN not in str(info.value)
    assert len(calls) == 1

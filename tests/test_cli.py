import pytest
import json

from mc_jarvis import cli


def test_card_show_does_not_swallow_verb_as_query():
    """`card show Vision` must parse `show` as the verb, not as a query."""
    args = cli.build_parser().parse_args(["card", "show", "Vision"])
    assert args.card_cmd == "show"
    assert args.name == "Vision"


def test_card_search_takes_its_query():
    args = cli.build_parser().parse_args(["card", "search", "web"])
    assert args.card_cmd == "search"
    assert args.query == "web"


def test_json_flag_available_on_every_leaf_command():
    parser = cli.build_parser()
    for argv in (["doctor"], ["status"], ["card", "search", "x"],
                 ["card", "show", "x"], ["identity", "x"], ["encounter", "x"],
                 ["rules", "show", "x"], ["rules", "search", "x"], ["timing"]):
        assert parser.parse_args(argv + ["--json"]).json is True, argv


def test_hero_is_an_alias_for_identity():
    args = cli.parse_args(["hero", "Spider-Man"])
    assert args.command == "identity"
    assert args.name == "Spider-Man"


def test_emit_json(capsys):
    cli.emit({"a": 1}, as_json=True)
    assert json.loads(capsys.readouterr().out) == {"a": 1}


def test_no_args_prints_help_and_fails():
    assert cli.main([]) == 2


def test_owned_is_accepted_only_where_it_can_act():
    """`--owned` used to be on all 14 leaf commands and rejected at
    dispatch, which offered a filter on `doctor` and `timing` that could
    never happen (spec §10.1). argparse now refuses it there, at parse
    time, instead of the command accepting it and doing nothing.
    """
    import pytest

    from mc_jarvis import collection

    parser = cli.build_parser()
    parser.parse_args(["card", "search", "web", "--owned"])
    for argv in (["timing", "--owned"], ["rules", "search", "x", "--owned"],
                 ["status", "--owned"]):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)

    assert "card search" in collection.OWNED_COMMANDS
    assert "timing" not in collection.OWNED_COMMANDS


def test_the_player_count_is_bounded_to_what_the_game_supports():
    """Learn to Play describes a game for one to four players, and every
    per-player value scales off this number. Unvalidated, `--players -3`
    reported a Zola deck with -17 threat and `--players 999` one with
    6997, both stated as flatly as a real figure."""
    import argparse

    from mc_jarvis.cli import _players

    assert _players("1") == 1 and _players("4") == 4
    for bad in ("0", "-3", "999", "two"):
        with pytest.raises(argparse.ArgumentTypeError):
            _players(bad)


def test_a_result_limit_must_be_at_least_one():
    """SQLite reads a negative LIMIT as no limit, so `--limit -5` returned
    the whole table while the footer claimed the results were complete."""
    import argparse

    from mc_jarvis.cli import _positive

    assert _positive("1") == 1
    for bad in ("0", "-5", "x"):
        with pytest.raises(argparse.ArgumentTypeError):
            _positive(bad)

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

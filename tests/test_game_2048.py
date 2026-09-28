import random
from unittest.mock import AsyncMock

import pytest
from types import SimpleNamespace

from zeronexus.engines.game_2048 import has_moves, max_tile, move, new_board, spawn_tile
from zeronexus.modules.entertainment.cog import EntertainmentCog, EntertainmentModule, Game2048View


def test_new_board_has_two_tiles_and_spawn_is_bounded() -> None:
    board = new_board(random.Random(10))
    assert sum(value != 0 for row in board for value in row) == 2
    assert set(value for row in board for value in row) <= {0, 2, 4}


def test_merge_combines_each_tile_only_once_and_awards_score() -> None:
    board = [[2, 2, 2, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    result, score, changed = move(board, "left")
    assert result[0] == [4, 4, 0, 0]
    assert score == 8
    assert changed


def test_direction_moves_and_noop_is_reported() -> None:
    board = [[2, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    same, score, changed = move(board, "left")
    assert same == board and score == 0 and not changed
    down, _, changed = move(board, "down")
    assert down[3][0] == 2 and changed


def test_game_over_only_when_full_and_no_adjacent_equal_tiles() -> None:
    assert has_moves([[2, 2, 4, 8], [16, 32, 64, 128], [256, 512, 1024, 2], [4, 8, 16, 32]])
    assert not has_moves([[2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 4, 2]])
    assert max_tile([[2, 0, 0, 0], [0, 4, 0, 0], [0, 0, 8, 0], [0, 0, 0, 16]]) == 16


def test_spawn_returns_false_on_full_board() -> None:
    assert not spawn_tile([[2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 4, 2]], random.Random(1))


def test_2048_and_leaderboard_commands_register() -> None:
    commands = {command.name for command in EntertainmentCog.fun_group.commands}
    assert "2048" in commands
    assert "2048排行榜" in commands
    module = EntertainmentModule()
    import asyncio
    asyncio.run(module.initialize(None))
    metadata = {item.name for item in module.registered_commands}
    assert "2048" in metadata
    assert "2048排行榜" in metadata


def test_direction_pad_uses_four_disabled_corner_buttons_and_four_directions() -> None:
    from discord.ui import Button

    view = Game2048View(1, SimpleNamespace(id=2, name="tester", display_name="tester"))
    buttons = [item for item in view.children if isinstance(item, Button)]
    disabled_corners = [item for item in buttons if item.disabled]
    assert len(buttons) == 11  # nine direction-pad cells plus restart/end controls
    assert len(disabled_corners) == 5  # four corners and center
    assert sum(1 for item in buttons if item.label in {"上", "左", "下", "右"}) == 4
    positions = {(item.label, item.row) for item in buttons}
    assert {("■", 0), ("■", 1), ("■", 2)} <= positions
    assert {("上", 0), ("左", 1), ("右", 1), ("下", 2)} <= positions
    assert ("重新開始", 3) in positions
    assert ("結束遊戲", 3) in positions
    assert "方向鍵" not in view.render_card().description


def test_score_encouragement_levels_progress_with_score_and_tile() -> None:
    view = Game2048View(1, SimpleNamespace(id=2, name="tester", display_name="tester"))
    assert view.encouragement()[0] == "新手上路"
    view.score = 1200
    assert view.encouragement()[0] == "熟練玩家"
    view.score = 11000
    assert view.encouragement()[0] == "大師級玩家"


def test_completing_a_game_records_only_once_and_restart_preserves_record_state() -> None:
    view = Game2048View(1, SimpleNamespace(id=2, name="tester", display_name="tester"))
    view.board = [[2, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    view.moves = 1
    assert max_tile(view.board) == 2
    view.status = "lost"
    assert view.status == "lost"
    assert view.moves == 1
    assert view._result_recorded is False


@pytest.mark.asyncio
async def test_other_players_cannot_operate_public_game_board() -> None:
    view = Game2048View(1, SimpleNamespace(id=2, name="owner", display_name="owner"))
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=3),
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "zeronexus.modules.entertainment.cog.InteractionResponder.safe_send",
            AsyncMock(),
        )
        assert not await view.interaction_check(interaction)


@pytest.mark.asyncio
async def test_manual_end_records_score_and_disables_controls_except_restart() -> None:
    from discord.ui import Button

    view = Game2048View(1, SimpleNamespace(id=2, name="owner", display_name="owner"))
    view.board = [[2, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    view.moves = 1
    interaction = SimpleNamespace(user=SimpleNamespace(id=2))
    with pytest.MonkeyPatch.context() as monkeypatch:
        record = AsyncMock()
        edit = AsyncMock()
        monkeypatch.setattr(view, "_record_result_once", record)
        monkeypatch.setattr("zeronexus.modules.entertainment.cog.InteractionResponder.safe_edit", edit)
        await view.end_game.callback(interaction)

    assert view.status == "ended"
    record.assert_awaited_once()
    buttons = [item for item in view.children if isinstance(item, Button)]
    assert all(item.disabled or view._button_name(item) == "restart" for item in buttons)

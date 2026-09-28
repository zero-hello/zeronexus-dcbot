import random

from zeronexus.engines.game_2048 import has_moves, max_tile, move, new_board, spawn_tile
from zeronexus.modules.entertainment.cog import EntertainmentCog, EntertainmentModule


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

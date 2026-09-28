"""Pure 2048 board rules, independent of Discord UI and database I/O."""

from __future__ import annotations

import random
from typing import List, Tuple

Board = List[List[int]]
SIZE = 4


def new_board(rng: random.Random | None = None) -> Board:
    rng = rng or random
    board = [[0] * SIZE for _ in range(SIZE)]
    spawn_tile(board, rng)
    spawn_tile(board, rng)
    return board


def spawn_tile(board: Board, rng: random.Random | None = None) -> bool:
    rng = rng or random
    empty = [(r, c) for r in range(SIZE) for c in range(SIZE) if board[r][c] == 0]
    if not empty:
        return False
    r, c = rng.choice(empty)
    board[r][c] = 4 if rng.random() < 0.1 else 2
    return True


def _merge_line(line: List[int]) -> Tuple[List[int], int]:
    values = [value for value in line if value]
    merged: List[int] = []
    score = 0
    index = 0
    while index < len(values):
        if index + 1 < len(values) and values[index] == values[index + 1]:
            value = values[index] * 2
            merged.append(value)
            score += value
            index += 2
        else:
            merged.append(values[index])
            index += 1
    return merged + [0] * (SIZE - len(merged)), score


def move(board: Board, direction: str) -> Tuple[Board, int, bool]:
    """Return (new board, merge score, changed). Directions: left/right/up/down."""
    if direction not in {"left", "right", "up", "down"}:
        raise ValueError("direction must be left, right, up, or down")
    result = [row[:] for row in board]
    total_score = 0
    if direction in {"left", "right"}:
        for r in range(SIZE):
            source = result[r] if direction == "left" else list(reversed(result[r]))
            merged, score = _merge_line(source)
            result[r] = merged if direction == "left" else list(reversed(merged))
            total_score += score
    else:
        for c in range(SIZE):
            source = [result[r][c] for r in range(SIZE)]
            if direction == "down":
                source.reverse()
            merged, score = _merge_line(source)
            if direction == "down":
                merged.reverse()
            for r in range(SIZE):
                result[r][c] = merged[r]
            total_score += score
    return result, total_score, result != board


def has_moves(board: Board) -> bool:
    if any(0 in row for row in board):
        return True
    for r in range(SIZE):
        for c in range(SIZE):
            if c + 1 < SIZE and board[r][c] == board[r][c + 1]:
                return True
            if r + 1 < SIZE and board[r][c] == board[r + 1][c]:
                return True
    return False


def max_tile(board: Board) -> int:
    return max((value for row in board for value in row), default=0)

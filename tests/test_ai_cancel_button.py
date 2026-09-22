"""Unit tests for AI Thinking Red Cancel Button & Cancel Response feature."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from zeronexus.ui.views import AICancelView
from zeronexus.ui.card import ZNCard
from zeronexus.ui.theme import ZNColor, ZNStatusPill


@pytest.mark.asyncio
async def test_ai_cancel_view_initialization():
    """驗證 AICancelView 正確具備紅色的取消按鈕與基本屬性。"""
    view = AICancelView(author_id=12345678, author_name="Zero")
    assert view.author_id == 12345678
    assert view.author_name == "Zero"
    assert not view.is_cancelled

    # 驗證紅色取消按鈕
    assert len(view.children) == 1
    btn = view.children[0]
    assert isinstance(btn, discord.ui.Button)
    assert btn.style == discord.ButtonStyle.danger
    assert btn.label == "取消回應"
    assert btn.emoji.name == "🛑"
    assert not btn.disabled


@pytest.mark.asyncio
async def test_ai_cancel_view_author_permission_check():
    """驗證非發起者無法點擊取消按鈕，發起者可正常通過。"""
    view = AICancelView(author_id=12345678, author_name="Zero")

    # 模擬非發起者點擊
    other_interaction = MagicMock(spec=discord.Interaction)
    other_user = MagicMock()
    other_user.id = 88888888
    other_interaction.user = other_user
    other_interaction.response = MagicMock()
    other_interaction.response.send_message = AsyncMock()

    allowed = await view.interaction_check(other_interaction)
    assert allowed is False
    assert not view.is_cancelled

    # 模擬發起者點擊
    author_interaction = MagicMock(spec=discord.Interaction)
    author_user = MagicMock()
    author_user.id = 12345678
    author_interaction.user = author_user

    allowed_author = await view.interaction_check(author_interaction)
    assert allowed_author is True


@pytest.mark.asyncio
async def test_ai_cancel_view_execution_and_task_cancellation():
    """驗證點擊取消按鈕後，背景 Task 被取消、卡片被編輯為已取消樣式。"""
    # 建立一個持續運行的模擬任務
    async def dummy_ai_work():
        await asyncio.sleep(10.0)

    task = asyncio.create_task(dummy_ai_work())
    on_cancelled_mock = AsyncMock()

    view = AICancelView(
        author_id=12345678,
        author_name="Zero",
        task=task,
        on_cancelled=on_cancelled_mock,
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(id=12345678)
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.edit_message = AsyncMock()

    # 觸發點擊
    await view._on_cancel_click(interaction)

    assert view.is_cancelled is True
    assert view.cancel_button.disabled is True
    assert view.cancel_event.is_set()

    # 驗證 task 被取消
    assert task.cancelling() or task.cancelled()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.cancelled()

    # 驗證呼叫了 edit_message，卡片更新為已取消
    interaction.response.edit_message.assert_awaited_once()
    kwargs = interaction.response.edit_message.await_args.kwargs
    assert "view" in kwargs
    rendered_view = kwargs["view"]
    assert hasattr(rendered_view, "card")
    card: ZNCard = rendered_view.card
    assert "🛑 已取消回應" in card.title
    assert "Zero" in card.title
    assert "已成功中斷本次 AI 推論與思考程序" in card.description

    # 驗證 on_cancelled 回呼有被執行
    on_cancelled_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_card_to_layout_view_with_cancel_view():
    """驗證 ZNCard.to_layout_view 正確將取消按鈕掛載至 ActionRow。"""
    view = AICancelView(author_id=12345678, author_name="Zero")
    card = ZNCard(
        title="🧠 正在思考中… ➔ Zero",
        description="正在整理上下文與認知推論…",
        status_pill=ZNStatusPill.PROCESSING,
        color=ZNColor.AI,
    )

    layout_view = card.to_layout_view(extra_view=view)
    assert layout_view is not None

    # 檢查 container 中的 items 是否包含 ActionRow，且 ActionRow 內包含紅色按鈕
    container = layout_view.children[0]
    action_rows = [item for item in container.children if isinstance(item, discord.ui.ActionRow)]
    assert len(action_rows) >= 1
    button_in_row = action_rows[0].children[0]
    assert isinstance(button_in_row, discord.ui.Button)
    assert button_in_row.style == discord.ButtonStyle.danger
    assert button_in_row.label == "取消回應"

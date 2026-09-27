from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zeronexus.engines.attachment_processor import ingest_attachments


@pytest.mark.asyncio
async def test_invalid_image_is_rejected_even_with_image_mime_type() -> None:
    attachment = SimpleNamespace(
        filename="broken.png",
        content_type="image/png",
        size=10,
        url="https://cdn.example/broken.png",
        read=AsyncMock(return_value=b"not an image"),
    )

    images, thumbnail, results, notes = await ingest_attachments([attachment])

    assert images == []
    assert thumbnail is None
    assert any("損毀" in note for note in notes)
    assert "附加圖片_broken.png" in results


@pytest.mark.asyncio
async def test_attachment_count_limit_is_enforced() -> None:
    attachments = [
        SimpleNamespace(
            filename=f"file-{index}.bin",
            content_type="application/octet-stream",
            size=1,
            read=AsyncMock(return_value=b"x"),
        )
        for index in range(11)
    ]

    _, _, results, notes = await ingest_attachments(attachments)

    assert len(results) == 10
    assert any("僅處理前 10 個" in note for note in notes)


@pytest.mark.asyncio
async def test_actual_download_size_is_checked_before_image_processing() -> None:
    from zeronexus.engines.attachment_processor import MAX_IMAGE_BYTES

    attachment = SimpleNamespace(
        filename="oversized.png",
        content_type="image/png",
        size=1,
        url="https://cdn.example/oversized.png",
        read=AsyncMock(return_value=b"x" * (MAX_IMAGE_BYTES + 1)),
    )

    images, _, _, _ = await ingest_attachments([attachment])

    assert images == []

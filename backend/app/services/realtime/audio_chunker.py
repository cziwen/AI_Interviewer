from __future__ import annotations

import base64
from typing import Iterator


class AudioChunker:
    @staticmethod
    def iter_chunks(
        pcm16_bytes: bytes,
        chunk_ms: int = 120,
        sample_rate: int = 24000,
        channels: int = 1,
    ) -> Iterator[str]:
        if not pcm16_bytes:
            return

        bytes_per_sample = 2
        samples_per_chunk = max(int(sample_rate * max(chunk_ms, 20) / 1000), 1)
        chunk_size = samples_per_chunk * channels * bytes_per_sample

        for idx in range(0, len(pcm16_bytes), chunk_size):
            chunk = pcm16_bytes[idx: idx + chunk_size]
            if not chunk:
                continue
            yield base64.b64encode(chunk).decode("utf-8")

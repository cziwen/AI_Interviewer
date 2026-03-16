import base64
import unittest

from backend.app.services.realtime.audio_chunker import AudioChunker


class AudioChunkerTests(unittest.TestCase):
    def test_empty_audio_returns_no_chunks(self):
        chunks = list(AudioChunker.iter_chunks(b""))
        self.assertEqual(chunks, [])

    def test_chunking_roundtrip(self):
        raw = (b"\x01\x02" * 2400) + (b"\x03\x04" * 1200)
        chunks = list(AudioChunker.iter_chunks(raw, chunk_ms=100, sample_rate=24000))
        self.assertGreaterEqual(len(chunks), 2)
        rebuilt = b"".join(base64.b64decode(c) for c in chunks)
        self.assertEqual(rebuilt, raw)


if __name__ == "__main__":
    unittest.main()

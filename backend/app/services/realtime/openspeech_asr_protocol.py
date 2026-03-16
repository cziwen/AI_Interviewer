from __future__ import annotations

import gzip
import json
import struct
import uuid
from typing import Any, Optional


class OpenSpeechAsrProtocol:
    PROTOCOL_VERSION = 0x1
    HEADER_WORDS = 0x1  # 4 bytes

    MT_FULL_CLIENT = 0x1
    MT_AUDIO_ONLY = 0x2
    MT_FULL_SERVER = 0x9
    MT_ERROR = 0xF

    FLAG_NO_SEQ = 0x0
    FLAG_LAST = 0x2

    SER_JSON = 0x1
    COMP_GZIP = 0x1

    @classmethod
    def _header(cls, mt: int, flags: int, ser: int = SER_JSON, comp: int = COMP_GZIP) -> bytes:
        return bytes(
            [
                (cls.PROTOCOL_VERSION << 4) | cls.HEADER_WORDS,
                (mt << 4) | (flags & 0xF),
                (ser << 4) | (comp & 0xF),
                0,
            ]
        )

    @classmethod
    def build_full_request(
        cls,
        app_id: str,
        access_token: str,
        cluster: str,
        sample_rate: int = 24000,
    ) -> bytes:
        payload = {
            "app": {"appid": app_id, "token": access_token, "cluster": cluster},
            "user": {"uid": "ai-interviewer"},
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": sample_rate,
                "bits": 16,
                "channel": 1,
            },
            "request": {
                "reqid": str(uuid.uuid4()).replace("-", ""),
                "workflow": "audio_in,resample,partition,vad,fe,decode",
                "sequence": 1,
                "nbest": 1,
                "show_utterances": True,
                "result_type": "single",
            },
        }
        payload_bytes = gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return cls._header(cls.MT_FULL_CLIENT, cls.FLAG_NO_SEQ) + struct.pack(">I", len(payload_bytes)) + payload_bytes

    @classmethod
    def build_audio_request(cls, pcm_data: bytes, is_last: bool) -> bytes:
        payload_bytes = gzip.compress(pcm_data or b"")
        flags = cls.FLAG_LAST if is_last else cls.FLAG_NO_SEQ
        return cls._header(cls.MT_AUDIO_ONLY, flags, ser=0x0, comp=cls.COMP_GZIP) + struct.pack(">I", len(payload_bytes)) + payload_bytes

    @classmethod
    def parse_server_message(cls, message: bytes) -> Optional[dict[str, Any]]:
        if not isinstance(message, (bytes, bytearray)) or len(message) < 4:
            return None
        b0, b1, b2, _ = message[:4]
        header_size = (b0 & 0xF) * 4
        message_type = (b1 >> 4) & 0xF
        message_flags = b1 & 0xF
        compression = b2 & 0xF
        body = message[header_size:]

        if message_type == cls.MT_ERROR:
            if len(body) < 8:
                return {"kind": "error", "error": {"code": "protocol_error", "message": "invalid_error_frame"}}
            err_code = struct.unpack(">I", body[:4])[0]
            msg_size = struct.unpack(">I", body[4:8])[0]
            err_payload = body[8:8 + msg_size]
            if compression == cls.COMP_GZIP:
                try:
                    err_payload = gzip.decompress(err_payload)
                except Exception:
                    pass
            err_msg = err_payload.decode("utf-8", "ignore")
            return {"kind": "error", "error": {"code": str(err_code), "message": err_msg}}

        if message_type != cls.MT_FULL_SERVER or len(body) < 4:
            return None

        body_offset = 0
        # Some server frames prepend a 4-byte sequence before payload_size.
        if message_flags in {0x1, 0x2, 0x3} and len(body) >= 8:
            body_offset += 4
        payload_size = struct.unpack(">I", body[body_offset:body_offset + 4])[0]
        payload = body[body_offset + 4:body_offset + 4 + payload_size]
        if compression == cls.COMP_GZIP:
            try:
                payload = gzip.decompress(payload)
            except Exception:
                pass
        try:
            obj = json.loads(payload.decode("utf-8", "ignore"))
        except Exception:
            return None

        text = cls._extract_text(obj)
        if text:
            return {"kind": "transcript_completed", "transcript": text}
        return {"kind": "asr_meta", "payload": obj}

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""
        candidates: list[str] = []
        result = payload.get("result")
        if isinstance(result, str):
            candidates.append(result)
        elif isinstance(result, dict):
            for key in ("text", "transcript", "sentence"):
                value = result.get(key)
                if isinstance(value, str):
                    candidates.append(value)
            utterances = result.get("utterances")
            if isinstance(utterances, list):
                for item in utterances:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str):
                            candidates.append(text)

        for key in ("text", "transcript", "message"):
            value = payload.get(key)
            if isinstance(value, str):
                candidates.append(value)
        merged = " ".join(t.strip() for t in candidates if t and t.strip()).strip()
        return merged

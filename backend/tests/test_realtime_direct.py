import asyncio
import base64
import json
import os
import websockets

# Load .env manually
def load_env_manually(path):
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    os.environ[key] = value

load_env_manually("../.env")

ARK_API_KEY = os.getenv("ARK_API_KEY")
ARK_ASR_WS_URL = os.getenv("ARK_ASR_WS_URL", "wss://ai-gateway.vei.volces.com/v1/realtime?model=bigmodel")

async def test_realtime():
    if not ARK_API_KEY:
        print("Error: ARK_API_KEY not found in .env")
        return

    headers = {
        "Authorization": f"Bearer {ARK_API_KEY}",
    }

    print(f"Connecting to {ARK_ASR_WS_URL}...")
    try:
        async with websockets.connect(ARK_ASR_WS_URL, additional_headers=headers) as ws:
            print("Connected!")

            # 1. Update session
            session_update = {
                "type": "session.update",
                "session": {
                    "input_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": os.getenv("ARK_STT_MODEL", "Doubao-语音识别")
                    },
                    "turn_detection": {"type": "server_vad"}
                }
            }
            await ws.send(json.dumps(session_update))
            print("Sent session.update")
            print("Waiting briefly for any server-side error...")
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=3)
                print("Received:", json.dumps(json.loads(message))[:200])
            except asyncio.TimeoutError:
                print("No immediate error, ASR handshake looks OK.")

    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_realtime())

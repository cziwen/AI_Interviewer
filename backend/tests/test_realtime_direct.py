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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-mini"

async def test_realtime():
    if not OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not found in .env")
        return

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1"
    }

    print(f"Connecting to {OPENAI_REALTIME_URL}...")
    try:
        async with websockets.connect(OPENAI_REALTIME_URL, additional_headers=headers) as ws:
            print("Connected!")

            # 1. Update session
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": "You are a helpful assistant. Greet the user and ask how you can help.",
                    "voice": "alloy",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": "whisper-1"
                    },
                    "turn_detection": {"type": "server_vad"}
                }
            }
            await ws.send(json.dumps(session_update))
            print("Sent session.update")

            # 2. Add a text message
            text_message = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Hello, please introduce yourself."
                        }
                    ]
                }
            }
            await ws.send(json.dumps(text_message))
            print("Sent user message")

            # 3. Create response
            response_create = {
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],
                    "instructions": "Please introduce yourself and ask how you can help."
                }
            }
            await ws.send(json.dumps(response_create))
            print("Sent response.create")

            # 3.5 Listen for a few events to ensure session is updated
            # await asyncio.sleep(2)

            # 3. Listen for events
            print("\nListening for events (Ctrl+C to stop)...\n")
            audio_received = 0
            transcript = ""
            
            async def listen():
                nonlocal audio_received, transcript
                async for message in ws:
                    event = json.loads(message)
                    event_type = event.get("type")
                    
                    if event_type not in ["response.audio.delta"]:
                        print(f"Event: {event_type} - {json.dumps(event)[:100]}...")
                    
                    if event_type == "response.audio.delta":
                        audio_received += len(event.get("audio", ""))
                    elif event_type == "response.audio_transcript.delta":
                        transcript += event.get("delta", "")
                    elif event_type == "response.done":
                        print(f"\nResponse done! Full transcript: {transcript}")
                        print(f"Total audio bytes: {audio_received}")
                        return
                    elif event_type == "error":
                        print(f"Error: {json.dumps(event)}")
                        return

            try:
                await asyncio.wait_for(listen(), timeout=20)
            except asyncio.TimeoutError:
                print("\nTimeout waiting for response.done")

    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_realtime())

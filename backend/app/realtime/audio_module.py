import asyncio
import logging
import os
import struct
import threading
import time
from collections import namedtuple
from queue import Queue
import queue
from typing import Callable, Generator, Optional
import numpy as np
from huggingface_hub import hf_hub_download
from RealtimeTTS import CoquiEngine, KokoroEngine, OrpheusEngine, OrpheusVoice, TextToAudioStream

logger = logging.getLogger(__name__)

START_ENGINE = "kokoro"
Silence = namedtuple("Silence", ("comma", "sentence", "default"))
ENGINE_SILENCES = {
    "coqui": Silence(comma=0.3, sentence=0.6, default=0.3),
    "kokoro": Silence(comma=0.3, sentence=0.6, default=0.3),
    "orpheus": Silence(comma=0.3, sentence=0.6, default=0.3),
}
QUICK_ANSWER_STREAM_CHUNK_SIZE = 8
FINAL_ANSWER_STREAM_CHUNK_SIZE = 30

def create_directory(path: str) -> None:
    if not os.path.exists(path): os.makedirs(path)

def ensure_lasinya_models(models_root: str = "models", model_name: str = "Lasinya") -> None:
    base = os.path.join(models_root, model_name)
    create_directory(base)
    files = ["config.json", "vocab.json", "speakers_xtts.pth", "model.pth"]
    for fn in files:
        local_file = os.path.join(base, fn)
        if not os.path.exists(local_file):
            print(f"👄⏬ Downloading {fn} to {base}")
            hf_hub_download(repo_id="KoljaB/XTTS_Lasinya", filename=fn, local_dir=base)

class AudioProcessor:
    def __init__(self, engine: str = START_ENGINE, orpheus_model: str = "orpheus-3b-0.1-ft-Q8_0-GGUF/orpheus-3b-0.1-ft-q8_0.gguf") -> None:
        self.engine_name = engine
        self.stop_event = threading.Event()
        self.finished_event = threading.Event()
        # Use thread-safe Queue instead of asyncio.Queue since synthesis happens in threads
        self.audio_chunks = Queue()
        self.orpheus_model = orpheus_model
        self.silence = ENGINE_SILENCES.get(engine, ENGINE_SILENCES[START_ENGINE])
        self.current_stream_chunk_size = QUICK_ANSWER_STREAM_CHUNK_SIZE
        if engine == "coqui":
            ensure_lasinya_models(models_root="models", model_name="Lasinya")
            self.engine = CoquiEngine(specific_model="Lasinya", local_models_path="./models", voice="reference_audio.wav", speed=1.1, use_deepspeed=True, thread_count=6, stream_chunk_size=self.current_stream_chunk_size, overlap_wav_len=1024, load_balancing=True, load_balancing_buffer_length=0.5, load_balancing_cut_off=0.1, add_sentence_filter=True)
        elif engine == "kokoro":
            self.engine = KokoroEngine(voice="af_heart", default_speed=1.26, trim_silence=True, silence_threshold=0.01, extra_start_ms=25, extra_end_ms=15, fade_in_ms=15, fade_out_ms=10)
        elif engine == "orpheus":
            self.engine = OrpheusEngine(model=self.orpheus_model, temperature=0.8, top_p=0.95, repetition_penalty=1.1, max_tokens=1200)
            self.engine.set_voice(OrpheusVoice("tara"))
        else: raise ValueError(f"Unsupported engine: {engine}")
        self.stream = TextToAudioStream(self.engine, muted=True, playout_chunk_size=4096, on_audio_stream_stop=self.on_audio_stream_stop)
        self.stream.feed("prewarm")
        self.stream.play(log_synthesized_text=False, muted=True, fast_sentence_fragment=False, comma_silence_duration=self.silence.comma, sentence_silence_duration=self.silence.sentence, default_silence_duration=self.silence.default, force_first_fragment_after_words=999999)
        while self.stream.is_playing(): time.sleep(0.01)
        self.finished_event.wait(); self.finished_event.clear()
        start_time = time.time(); ttfa = None
        def on_audio_chunk_ttfa(chunk: bytes):
            nonlocal ttfa
            if ttfa is None: ttfa = time.time() - start_time
        self.stream.feed("This is a test sentence to measure the time to first audio chunk.")
        self.stream.play_async(on_audio_chunk=on_audio_chunk_ttfa, log_synthesized_text=False, muted=True, fast_sentence_fragment=False, comma_silence_duration=self.silence.comma, sentence_silence_duration=self.silence.sentence, default_silence_duration=self.silence.default, force_first_fragment_after_words=999999)
        while ttfa is None and (self.stream.is_playing() or not self.finished_event.is_set()): time.sleep(0.01)
        self.stream.stop(); self.finished_event.wait(timeout=2.0); self.finished_event.clear()
        self.tts_inference_time = (ttfa * 1000) if ttfa is not None else 0
        self.on_first_audio_chunk_synthesize: Optional[Callable[[], None]] = None

    def on_audio_stream_stop(self) -> None:
        logger.info("👄🛑 Audio stream stopped.")
        self.finished_event.set()

    def synthesize(self, text: str, audio_chunks: Queue, stop_event: threading.Event, generation_string: str = "") -> bool:
        if self.engine_name == "coqui" and hasattr(self.engine, 'set_stream_chunk_size') and self.current_stream_chunk_size != QUICK_ANSWER_STREAM_CHUNK_SIZE:
            self.engine.set_stream_chunk_size(QUICK_ANSWER_STREAM_CHUNK_SIZE)
            self.current_stream_chunk_size = QUICK_ANSWER_STREAM_CHUNK_SIZE
        self.stream.feed(text); self.finished_event.clear()
        buffer, good_streak, buffering, buf_dur = [], 0, True, 0.0
        SR, BPS = 24000, 2; start = time.time(); self._quick_prev_chunk_time = 0.0
        def on_audio_chunk(chunk: bytes):
            nonlocal buffer, good_streak, buffering, buf_dur, start
            if stop_event.is_set(): return
            now = time.time(); samples = len(chunk) // BPS; play_duration = samples / SR
            if on_audio_chunk.first_call and self.engine_name == "orpheus":
                if not hasattr(on_audio_chunk, "silent_chunks_count"):
                    on_audio_chunk.silent_chunks_count, on_audio_chunk.silent_chunks_time, on_audio_chunk.silence_threshold = 0, 0.0, 200
                try:
                    avg_amplitude = np.abs(np.array(struct.unpack(f"{samples}h", chunk))).mean()
                    if avg_amplitude < on_audio_chunk.silence_threshold:
                        on_audio_chunk.silent_chunks_count += 1; on_audio_chunk.silent_chunks_time += play_duration; return
                except: pass
            if on_audio_chunk.first_call:
                on_audio_chunk.first_call = False; self._quick_prev_chunk_time = now
                logger.info(f"👄🚀 {generation_string} Quick audio start. TTFA: {now - start:.2f}s.")
            else:
                gap = now - self._quick_prev_chunk_time; self._quick_prev_chunk_time = now
                if gap <= play_duration * 1.1: good_streak += 1
                else: good_streak = 0
            put_occurred = False; buffer.append(chunk); buf_dur += play_duration
            if buffering:
                if good_streak >= 2 or buf_dur >= 0.5:
                    for c in buffer:
                        try: audio_chunks.put_nowait(c); put_occurred = True
                        except queue.Full: pass
                    buffer.clear(); buf_dur, buffering = 0.0, False
            else:
                try: audio_chunks.put_nowait(chunk); put_occurred = True
                except asyncio.QueueFull: pass
            if put_occurred and not on_audio_chunk.callback_fired:
                if self.on_first_audio_chunk_synthesize:
                    try: self.on_first_audio_chunk_synthesize()
                    except: pass
                on_audio_chunk.callback_fired = True
        on_audio_chunk.first_call, on_audio_chunk.callback_fired = True, False
        self.stream.play_async(log_synthesized_text=True, on_audio_chunk=on_audio_chunk, muted=True, fast_sentence_fragment=False, comma_silence_duration=self.silence.comma, sentence_silence_duration=self.silence.sentence, default_silence_duration=self.silence.default, force_first_fragment_after_words=999999)
        while self.stream.is_playing() or not self.finished_event.is_set():
            if stop_event.is_set(): self.stream.stop(); self.finished_event.wait(timeout=1.0); return False
            time.sleep(0.01)
        if buffering and buffer and not stop_event.is_set():
            for c in buffer:
                try: audio_chunks.put_nowait(c)
                except queue.Full: pass
        return True

    def synthesize_generator(self, generator: Generator[str, None, None], audio_chunks: Queue, stop_event: threading.Event, generation_string: str = "") -> bool:
        if self.engine_name == "coqui" and hasattr(self.engine, 'set_stream_chunk_size') and self.current_stream_chunk_size != FINAL_ANSWER_STREAM_CHUNK_SIZE:
            self.engine.set_stream_chunk_size(FINAL_ANSWER_STREAM_CHUNK_SIZE)
            self.current_stream_chunk_size = FINAL_ANSWER_STREAM_CHUNK_SIZE
        self.stream.feed(generator); self.finished_event.clear()
        buffer, good_streak, buffering, buf_dur = [], 0, True, 0.0
        SR, BPS = 24000, 2; start = time.time(); self._final_prev_chunk_time = 0.0
        def on_audio_chunk(chunk: bytes):
            nonlocal buffer, good_streak, buffering, buf_dur, start
            if stop_event.is_set(): return
            now = time.time(); samples = len(chunk) // BPS; play_duration = samples / SR
            if on_audio_chunk.first_call and self.engine_name == "orpheus":
                if not hasattr(on_audio_chunk, "silent_chunks_count"):
                    on_audio_chunk.silent_chunks_count, on_audio_chunk.silent_chunks_time, on_audio_chunk.silence_threshold = 0, 0.0, 100
                try:
                    avg_amplitude = np.abs(np.array(struct.unpack(f"{samples}h", chunk))).mean()
                    if avg_amplitude < on_audio_chunk.silence_threshold:
                        on_audio_chunk.silent_chunks_count += 1; on_audio_chunk.silent_chunks_time += play_duration; return
                except: pass
            if on_audio_chunk.first_call:
                on_audio_chunk.first_call = False; self._final_prev_chunk_time = now
                logger.info(f"👄🚀 {generation_string} Final audio start. TTFA: {now - start:.2f}s.")
            else:
                gap = now - self._final_prev_chunk_time; self._final_prev_chunk_time = now
                if gap <= play_duration * 1.1: good_streak += 1
                else: good_streak = 0
            put_occurred = False; buffer.append(chunk); buf_dur += play_duration
            if buffering:
                if good_streak >= 2 or buf_dur >= 0.5:
                    for c in buffer:
                        try: audio_chunks.put_nowait(c); put_occurred = True
                        except queue.Full: pass
                    buffer.clear(); buf_dur, buffering = 0.0, False
            else:
                try: audio_chunks.put_nowait(chunk); put_occurred = True
                except asyncio.QueueFull: pass
            if put_occurred and not on_audio_chunk.callback_fired:
                if self.on_first_audio_chunk_synthesize:
                    try: self.on_first_audio_chunk_synthesize()
                    except: pass
                on_audio_chunk.callback_fired = True
        on_audio_chunk.first_call, on_audio_chunk.callback_fired = True, False
        play_kwargs = dict(log_synthesized_text=True, on_audio_chunk=on_audio_chunk, muted=True, fast_sentence_fragment=False, comma_silence_duration=self.silence.comma, sentence_silence_duration=self.silence.sentence, default_silence_duration=self.silence.default, force_first_fragment_after_words=999999)
        if self.engine_name == "orpheus": play_kwargs.update({"minimum_sentence_length": 200, "minimum_first_fragment_length": 200})
        self.stream.play_async(**play_kwargs)
        while self.stream.is_playing() or not self.finished_event.is_set():
            if stop_event.is_set(): self.stream.stop(); self.finished_event.wait(timeout=1.0); return False
            time.sleep(0.01)
        if buffering and buffer and not stop_event.is_set():
            for c in buffer:
                try: audio_chunks.put_nowait(c)
                except queue.Full: pass
        return True

import logging
logger = logging.getLogger(__name__)

from .turndetect import strip_ending_punctuation
from .utils.colors import Colors
from .utils.text_similarity import TextSimilarity
from scipy import signal
import numpy as np
import threading
import textwrap
import torch
import json
import copy
import time
import re
from typing import Optional, Callable, Any, Dict, List

# --- Configuration Flags ---
USE_TURN_DETECTION = True
START_STT_SERVER = False # Set to True to use the client/server version of RealtimeSTT

# --- Recorder Configuration ---
DEFAULT_RECORDER_CONFIG: Dict[str, Any] = {
    "use_microphone": False,
    "spinner": False,
    "model": "base.en",
    "realtime_model_type": "base.en",
    "use_main_model_for_realtime": False,
    "language": "en",
    "silero_sensitivity": 0.05,
    "webrtc_sensitivity": 3,
    "post_speech_silence_duration": 0.7,
    "min_length_of_recording": 0.5,
    "min_gap_between_recordings": 0,
    "enable_realtime_transcription": True,
    "realtime_processing_pause": 0.03,
    "silero_use_onnx": True,
    "silero_deactivity_detection": True,
    "early_transcription_on_silence": 0,
    "beam_size": 3,
    "beam_size_realtime": 3,
    "no_log_file": True,
    # Disable wake words; not used in this app and Porcupine binaries are problematic on Apple Silicon.
    "wake_words": "",
    "wakeword_backend": "",
    "allowed_latency_limit": 500,
    "debug_mode": True,
    "initial_prompt_realtime": "The sky is blue. When the sky... She walked home. Because he... Today is sunny. If only I...",
    "faster_whisper_vad_filter": False,
}

if START_STT_SERVER:
    from RealtimeSTT import AudioToTextRecorderClient
else:
    from RealtimeSTT import AudioToTextRecorder

if USE_TURN_DETECTION:
    from .turndetect import TurnDetection

INT16_MAX_ABS_VALUE: float = 32768.0
SAMPLE_RATE: int = 16000

class TranscriptionProcessor:
    _PIPELINE_RESERVE_TIME_MS: float = 0.02
    _HOT_THRESHOLD_OFFSET_S: float = 0.35
    _MIN_HOT_CONDITION_DURATION_S: float = 0.15
    _TTS_ALLOWANCE_OFFSET_S: float = 0.25
    _MIN_POTENTIAL_END_DETECTION_TIME_MS: float = 0.02
    _SENTENCE_CACHE_MAX_AGE_MS: float = 0.2
    _SENTENCE_CACHE_TRIGGER_COUNT: int = 3

    def __init__(
        self,
        source_language: str = "en",
        realtime_transcription_callback: Optional[Callable[[str], None]] = None,
        full_transcription_callback: Optional[Callable[[str], None]] = None,
        potential_full_transcription_callback: Optional[Callable[[str], None]] = None,
        potential_full_transcription_abort_callback: Optional[Callable[[], None]] = None,
        potential_sentence_end: Optional[Callable[[str], None]] = None,
        before_final_sentence: Optional[Callable[[Optional[np.ndarray], Optional[str]], bool]] = None,
        silence_active_callback: Optional[Callable[[bool], None]] = None,
        on_recording_start_callback: Optional[Callable[[], None]] = None,
        is_orpheus: bool = False,
        local: bool = True,
        tts_allowed_event: Optional[threading.Event] = None,
        pipeline_latency: float = 0.5,
        recorder_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.source_language = source_language
        self.realtime_transcription_callback = realtime_transcription_callback
        self.full_transcription_callback = full_transcription_callback
        self.potential_full_transcription_callback = potential_full_transcription_callback
        self.potential_full_transcription_abort_callback = potential_full_transcription_abort_callback
        self.potential_sentence_end = potential_sentence_end
        self.before_final_sentence = before_final_sentence
        self.silence_active_callback = silence_active_callback
        self.on_recording_start_callback = on_recording_start_callback
        self.is_orpheus = is_orpheus
        self.pipeline_latency = pipeline_latency
        self.recorder: Optional[AudioToTextRecorder | AudioToTextRecorderClient] = None
        self.realtime_text: Optional[str] = None
        self.sentence_end_cache: List[Dict[str, Any]] = []
        self.potential_sentences_yielded: List[Dict[str, Any]] = []
        self.stripped_partial_user_text: str = ""
        self.final_transcription: Optional[str] = None
        self.shutdown_performed: bool = False
        self.silence_time: float = 0.0
        self.silence_active: bool = False
        self.last_audio_copy: Optional[np.ndarray] = None
        self.on_tts_allowed_to_synthesize: Optional[Callable] = None
        self.text_similarity = TextSimilarity(focus='end', n_words=5)
        self.recorder_config = copy.deepcopy(recorder_config if recorder_config else DEFAULT_RECORDER_CONFIG)
        self.recorder_config['language'] = self.source_language
        if USE_TURN_DETECTION:
            logger.info(f"👂🔄 {Colors.YELLOW}Turn detection enabled{Colors.RESET}")
            self.turn_detection = TurnDetection(on_new_waiting_time=self.on_new_waiting_time, local=local, pipeline_latency=pipeline_latency)
        self._create_recorder()
        self._start_silence_monitor()

    def _get_recorder_param(self, param_name: str, default: Any = None) -> Any:
        if not self.recorder: return default
        if START_STT_SERVER: return self.recorder.get_parameter(param_name)
        else: return getattr(self.recorder, param_name, default)

    def _set_recorder_param(self, param_name: str, value: Any) -> None:
        if not self.recorder: return
        if START_STT_SERVER: self.recorder.set_parameter(param_name, value)
        else: setattr(self.recorder, param_name, value)

    def _is_recorder_recording(self) -> bool:
        if not self.recorder: return False
        if START_STT_SERVER: return self.recorder.get_parameter("is_recording")
        else: return getattr(self.recorder, "is_recording", False)

    def _start_silence_monitor(self) -> None:
        def monitor():
            hot = False
            self.silence_time = self._get_recorder_param("speech_end_silence_start", 0.0)
            while not self.shutdown_performed:
                speech_end_silence_start = self.silence_time
                if self.recorder and speech_end_silence_start is not None and speech_end_silence_start != 0:
                    silence_waiting_time = self._get_recorder_param("post_speech_silence_duration", 0.0)
                    time_since_silence = time.time() - speech_end_silence_start
                    latest_pipe_start_time = silence_waiting_time - self.pipeline_latency - self._PIPELINE_RESERVE_TIME_MS
                    potential_sentence_end_time = latest_pipe_start_time
                    if potential_sentence_end_time < self._MIN_POTENTIAL_END_DETECTION_TIME_MS:
                        potential_sentence_end_time = self._MIN_POTENTIAL_END_DETECTION_TIME_MS
                    start_hot_condition_time = silence_waiting_time - self._HOT_THRESHOLD_OFFSET_S
                    if start_hot_condition_time < self._MIN_HOT_CONDITION_DURATION_S:
                        start_hot_condition_time = self._MIN_HOT_CONDITION_DURATION_S
                    if self.is_orpheus:
                        orpheus_potential_end_time = silence_waiting_time - self._HOT_THRESHOLD_OFFSET_S
                        if potential_sentence_end_time < orpheus_potential_end_time:
                            potential_sentence_end_time = orpheus_potential_end_time
                    if time_since_silence > potential_sentence_end_time:
                        current_text = self.realtime_text if self.realtime_text else ""
                        logger.info(f"👂🔚 {Colors.YELLOW}Potential sentence end detected (timed out){Colors.RESET}: {current_text}")
                        self.detect_potential_sentence_end(current_text, force_yield=True, force_ellipses=True)
                    tts_allowance_time = silence_waiting_time - self._TTS_ALLOWANCE_OFFSET_S
                    if time_since_silence > tts_allowance_time:
                        if self.on_tts_allowed_to_synthesize: self.on_tts_allowed_to_synthesize()
                    hot_condition_met = time_since_silence > start_hot_condition_time
                    if hot_condition_met and not hot:
                        hot = True
                        print(f"{Colors.MAGENTA}HOT{Colors.RESET}")
                        if self.potential_full_transcription_callback: self.potential_full_transcription_callback(self.realtime_text)
                    elif not hot_condition_met and hot:
                        if self._is_recorder_recording():
                            print(f"{Colors.CYAN}COLD (during silence){Colors.RESET}")
                            if self.potential_full_transcription_abort_callback: self.potential_full_transcription_abort_callback()
                        hot = False
                elif hot:
                    if self._is_recorder_recording():
                        print(f"{Colors.CYAN}COLD (silence ended){Colors.RESET}")
                        if self.potential_full_transcription_abort_callback: self.potential_full_transcription_abort_callback()
                    hot = False
                time.sleep(0.001)
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()

    def on_new_waiting_time(self, waiting_time: float, text: Optional[str] = None) -> None:
        if self.recorder:
            current_duration = self._get_recorder_param("post_speech_silence_duration")
            if current_duration != waiting_time:
                log_text = text if text else "(No text provided)"
                logger.info(f"👂⏳ {Colors.GRAY}New waiting time: {Colors.RESET}{Colors.YELLOW}{waiting_time:.2f}{Colors.RESET}{Colors.GRAY} for text: {log_text}{Colors.RESET}")
                self._set_recorder_param("post_speech_silence_duration", waiting_time)

    def transcribe_loop(self) -> None:
        def on_final(text: Optional[str]):
            if text is None or text == "": return
            self.final_transcription = text
            logger.info(f"👂✅ {Colors.apply('Final user text: ').green} {Colors.apply(text).yellow}")
            self.sentence_end_cache.clear()
            self.potential_sentences_yielded.clear()
            if USE_TURN_DETECTION and hasattr(self, 'turn_detection'): self.turn_detection.reset()
            if self.full_transcription_callback: self.full_transcription_callback(text)
        if self.recorder:
            if hasattr(self.recorder, 'text'): self.recorder.text(on_final)
            elif START_STT_SERVER:
                try: self._set_recorder_param('on_final_transcription', on_final)
                except Exception as e: logger.error(f"👂💥 Failed to set final transcription callback parameter for client: {e}")

    def abort_generation(self) -> None:
        self.potential_sentences_yielded.clear()
        logger.info("👂⏹️ Potential sentence yield cache cleared (generation aborted).")

    def perform_final(self, audio_bytes: Optional[bytes] = None) -> None:
        if self.recorder:
            current_text = self.realtime_text if self.realtime_text else ""
            self.final_transcription = current_text
            logger.info(f"👂❗ {Colors.apply('Forced Final user text: ').green} {Colors.apply(current_text).yellow}")
            self.sentence_end_cache.clear()
            self.potential_sentences_yielded.clear()
            if USE_TURN_DETECTION and hasattr(self, 'turn_detection'): self.turn_detection.reset()
            if self.full_transcription_callback: self.full_transcription_callback(current_text)

    def _normalize_text(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r'[^a-z0-9\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def is_basically_the_same(self, text1: str, text2: str, similarity_threshold: float = 0.96) -> bool:
        return self.text_similarity.calculate_similarity(text1, text2) > similarity_threshold

    def detect_potential_sentence_end(self, text: Optional[str], force_yield: bool = False, force_ellipses: bool = False) -> None:
        if not text: return
        stripped_text_raw = text.strip()
        if not stripped_text_raw: return
        if stripped_text_raw.endswith("...") and not force_ellipses: return
        end_punctuations = [".", "!", "?"]
        now = time.time()
        ends_with_punctuation = any(stripped_text_raw.endswith(p) for p in end_punctuations)
        if not ends_with_punctuation and not force_yield: return
        normalized_text = self._normalize_text(stripped_text_raw)
        if not normalized_text: return
        entry_found = next((e for e in self.sentence_end_cache if self.is_basically_the_same(e['text'], normalized_text)), None)
        if entry_found:
            entry_found['timestamps'].append(now)
            entry_found['timestamps'] = [t for t in entry_found['timestamps'] if now - t <= self._SENTENCE_CACHE_MAX_AGE_MS]
        else:
            entry_found = {'text': normalized_text, 'timestamps': [now]}
            self.sentence_end_cache.append(entry_found)
        should_yield = force_yield or (ends_with_punctuation and len(entry_found['timestamps']) >= self._SENTENCE_CACHE_TRIGGER_COUNT)
        if should_yield:
            if not any(self.is_basically_the_same(y['text'], normalized_text) for y in self.potential_sentences_yielded):
                self.potential_sentences_yielded.append({'text': normalized_text, 'timestamp': now})
                logger.info(f"👂➡️ Yielding potential sentence end: {stripped_text_raw}")
                if self.potential_sentence_end: self.potential_sentence_end(stripped_text_raw)

    def set_silence(self, silence_active: bool) -> None:
        if self.silence_active != silence_active:
            self.silence_active = silence_active
            logger.info(f"👂🤫 Silence state changed: {'ACTIVE' if silence_active else 'INACTIVE'}")
            if self.silence_active_callback: self.silence_active_callback(silence_active)

    def get_last_audio_copy(self) -> Optional[np.ndarray]:
        audio_copy = self.get_audio_copy()
        return audio_copy if audio_copy is not None and len(audio_copy) > 0 else self.last_audio_copy

    def get_audio_copy(self) -> Optional[np.ndarray]:
        if not self.recorder or not hasattr(self.recorder, 'frames'): return self.last_audio_copy
        try:
            with (self.recorder.frames_lock if hasattr(self.recorder, 'frames_lock') else threading.Lock()):
                frames_data = list(self.recorder.frames)
            if not frames_data: return self.last_audio_copy
            full_audio_array = np.frombuffer(b''.join(frames_data), dtype=np.int16)
            if full_audio_array.size == 0: return self.last_audio_copy
            audio_copy = full_audio_array.astype(np.float32) / INT16_MAX_ABS_VALUE
            self.last_audio_copy = audio_copy
            return audio_copy
        except Exception as e:
            logger.error(f"👂💥 Error getting audio copy: {e}", exc_info=True)
            return self.last_audio_copy

    def _create_recorder(self) -> None:
        def start_silence_detection():
            self.set_silence(True)
            recorder_silence_start = self._get_recorder_param("speech_end_silence_start", None)
            self.silence_time = recorder_silence_start if recorder_silence_start else time.time()
        def stop_silence_detection():
            self.set_silence(False)
            self.silence_time = 0.0
        def start_recording():
            logger.info("👂▶️ Recording started.")
            self.set_silence(False)
            self.silence_time = 0.0
            if self.on_recording_start_callback: self.on_recording_start_callback()
        def stop_recording() -> bool:
            logger.info("👂⏹️ Recording stopped.")
            audio_copy = self.get_last_audio_copy()
            if self.before_final_sentence:
                try:
                    result = self.before_final_sentence(audio_copy, self.realtime_text)
                    return result if isinstance(result, bool) else False
                except Exception as e:
                    logger.error(f"👂💥 Error in before_final_sentence callback: {e}", exc_info=True)
            return False
        def on_partial(text: Optional[str]):
            if text is None: return
            self.realtime_text = text
            self.detect_potential_sentence_end(text)
            stripped_partial_user_text_new = strip_ending_punctuation(text)
            if stripped_partial_user_text_new != self.stripped_partial_user_text:
                self.stripped_partial_user_text = stripped_partial_user_text_new
                logger.info(f"👂📝 Partial transcription: {Colors.CYAN}{text}{Colors.RESET}")
                if self.realtime_transcription_callback: self.realtime_transcription_callback(text)
                if USE_TURN_DETECTION and hasattr(self, 'turn_detection'): self.turn_detection.calculate_waiting_time(text=text)
        active_config = self.recorder_config.copy()
        active_config.update({"on_realtime_transcription_update": on_partial, "on_turn_detection_start": start_silence_detection, "on_turn_detection_stop": stop_silence_detection, "on_recording_start": start_recording, "on_recording_stop": stop_recording})
        recorder_type = "AudioToTextRecorderClient" if START_STT_SERVER else "AudioToTextRecorder"
        try:
            if START_STT_SERVER: self.recorder = AudioToTextRecorderClient(**active_config)
            else: self.recorder = AudioToTextRecorder(**active_config)
            self._set_recorder_param("use_wake_words", False)
            logger.info(f"👂✅ {recorder_type} instance created successfully.")
        except Exception as e:
            logger.exception(f"👂🔥 Failed to create recorder: {e}")
            self.recorder = None

    def feed_audio(self, chunk: bytes, audio_meta_data: Optional[Dict[str, Any]] = None) -> None:
        if self.recorder and not self.shutdown_performed:
            try: self.recorder.feed_audio(chunk)
            except Exception as e: logger.error(f"👂💥 Error feeding audio to recorder: {e}")

    def shutdown(self) -> None:
        if not self.shutdown_performed:
            self.shutdown_performed = True
            if self.recorder:
                try: self.recorder.shutdown()
                except Exception as e: logger.error(f"👂💥 Error during recorder shutdown: {e}", exc_info=True)
                finally: self.recorder = None
            if USE_TURN_DETECTION and hasattr(self, 'turn_detection') and hasattr(self.turn_detection, 'shutdown'):
                try: self.turn_detection.shutdown()
                except Exception as e: logger.error(f"👂💥 Error during TurnDetection shutdown: {e}", exc_info=True)

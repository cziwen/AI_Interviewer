import logging
logger = logging.getLogger(__name__)

import transformers
import collections
import threading
import queue
import torch
import time
import re

# Configuration constants
model_dir_local = "KoljaB/SentenceFinishedClassification"
model_dir_cloud = "KoljaB/SentenceFinishedClassification" # Default to HF for now
sentence_end_marks = ['.', '!', '?', '。'] # Characters considered sentence endings

# Anchor points for probability-to-pause interpolation
anchor_points = [
    (0.0, 1.0), # Probability 0.0 maps to pause 1.0
    (1.0, 0.0) # Probability 1.0 maps to pause 0.0
]

def ends_with_string(text: str, s: str) -> bool:
    if text.endswith(s):
        return True
    if len(text) > 1 and text[:-1].endswith(s):
        return True
    return False

def preprocess_text(text: str) -> str:
    text = text.lstrip()
    if text.startswith("..."):
        text = text[3:]
    text = text.lstrip()
    if text:
        text = text[0].upper() + text[1:]
    return text

def strip_ending_punctuation(text: str) -> str:
    text = text.rstrip()
    for char in sentence_end_marks:
        while text.endswith(char):
            text = text.rstrip(char)
    return text

def find_matching_texts(texts_without_punctuation: collections.deque) -> list[tuple[str, str]]:
    if not texts_without_punctuation:
        return []
    last_stripped_text = texts_without_punctuation[-1][1]
    matching_entries = []
    for entry in reversed(texts_without_punctuation):
        original_text, stripped_text = entry
        if stripped_text != last_stripped_text:
            break
        matching_entries.append(entry)
    matching_entries.reverse()
    return matching_entries

def interpolate_detection(prob: float) -> float:
    p = max(0.0, min(prob, 1.0))
    for ap_p, ap_val in anchor_points:
        if abs(ap_p - p) < 1e-9:
            return ap_val
    for i in range(len(anchor_points) - 1):
        p1, v1 = anchor_points[i]
        p2, v2 = anchor_points[i+1]
        if p1 <= p <= p2:
            if abs(p2 - p1) < 1e-9:
                return v1
            ratio = (p - p1) / (p2 - p1)
            return v1 + ratio * (v2 - v1)
    return 4.0

class TurnDetection:
    def __init__(
        self,
        on_new_waiting_time: callable,
        local: bool = False,
        pipeline_latency: float = 0.5,
        pipeline_latency_overhead: float = 0.1,
    ) -> None:
        model_dir = model_dir_local if local else model_dir_cloud
        self.on_new_waiting_time = on_new_waiting_time
        self.current_waiting_time: float = -1
        self.text_time_deque: collections.deque[tuple[float, str]] = collections.deque(maxlen=100)
        self.texts_without_punctuation: collections.deque[tuple[str, str]] = collections.deque(maxlen=20)
        self.text_queue: queue.Queue[str] = queue.Queue()
        self.text_worker = threading.Thread(target=self._text_worker, daemon=True)
        self.text_worker.start()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"🎤🔌 Using device: {self.device}")
        self.tokenizer = transformers.DistilBertTokenizerFast.from_pretrained(model_dir)
        self.classification_model = transformers.DistilBertForSequenceClassification.from_pretrained(model_dir)
        self.classification_model.to(self.device)
        self.classification_model.eval()
        self.max_length: int = 128
        self.pipeline_latency: float = pipeline_latency
        self.pipeline_latency_overhead: float = pipeline_latency_overhead
        self._completion_probability_cache: collections.OrderedDict[str, float] = collections.OrderedDict()
        self._completion_probability_cache_max_size: int = 256
        logger.info("🎤🔥 Warming up the classification model...")
        with torch.no_grad():
            warmup_text = "This is a warmup sentence."
            inputs = self.tokenizer(warmup_text, return_tensors="pt", truncation=True, padding="max_length", max_length=self.max_length)
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            _ = self.classification_model(**inputs)
        logger.info("🎤✅ Classification model warmed up.")
        self.detection_speed: float = 0.5
        self.ellipsis_pause: float = 2.3
        self.punctuation_pause: float = 0.39
        self.exclamation_pause: float = 0.35
        self.question_pause: float = 0.33
        self.unknown_sentence_detection_pause: float = 1.25
        self.update_settings(speed_factor=0.0)

    def update_settings(self, speed_factor: float) -> None:
        speed_factor = max(0.0, min(speed_factor, 1.0))
        fast = {'detection_speed': 0.5, 'ellipsis_pause': 2.3, 'punctuation_pause': 0.39, 'exclamation_pause': 0.35, 'question_pause': 0.33, 'unknown_sentence_detection_pause': 1.25}
        very_slow = {'detection_speed': 1.7, 'ellipsis_pause': 3.0, 'punctuation_pause': 0.9, 'exclamation_pause': 0.8, 'question_pause': 0.8, 'unknown_sentence_detection_pause': 1.9}
        self.detection_speed = fast['detection_speed'] + speed_factor * (very_slow['detection_speed'] - fast['detection_speed'])
        self.ellipsis_pause = fast['ellipsis_pause'] + speed_factor * (very_slow['ellipsis_pause'] - fast['ellipsis_pause'])
        self.punctuation_pause = fast['punctuation_pause'] + speed_factor * (very_slow['punctuation_pause'] - fast['punctuation_pause'])
        self.exclamation_pause = fast['exclamation_pause'] + speed_factor * (very_slow['exclamation_pause'] - fast['exclamation_pause'])
        self.question_pause = fast['question_pause'] + speed_factor * (very_slow['question_pause'] - fast['question_pause'])
        self.unknown_sentence_detection_pause = fast['unknown_sentence_detection_pause'] + speed_factor * (very_slow['unknown_sentence_detection_pause'] - fast['unknown_sentence_detection_pause'])
        logger.info(f"🎤⚙️ Updated turn detection settings with speed_factor={speed_factor:.2f}")

    def suggest_time(self, time_val: float, text: str = None) -> None:
        if time_val == self.current_waiting_time:
            return
        self.current_waiting_time = time_val
        if self.on_new_waiting_time:
            self.on_new_waiting_time(time_val, text)

    def get_completion_probability(self, sentence: str) -> float:
        if sentence in self._completion_probability_cache:
            self._completion_probability_cache.move_to_end(sentence)
            return self._completion_probability_cache[sentence]
        import torch.nn.functional as F
        inputs = self.tokenizer(sentence, return_tensors="pt", truncation=True, padding="max_length", max_length=self.max_length)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with torch.no_grad():
            outputs = self.classification_model(**inputs)
        logits = outputs.logits
        probabilities = F.softmax(logits, dim=1).squeeze().tolist()
        prob_complete = probabilities[1]
        self._completion_probability_cache[sentence] = prob_complete
        self._completion_probability_cache.move_to_end(sentence)
        if len(self._completion_probability_cache) > self._completion_probability_cache_max_size:
            self._completion_probability_cache.popitem(last=False)
        return prob_complete

    def get_suggested_whisper_pause(self, text: str) -> float:
        if ends_with_string(text, "..."): return self.ellipsis_pause
        elif ends_with_string(text, "."): return self.punctuation_pause
        elif ends_with_string(text, "!"): return self.exclamation_pause
        elif ends_with_string(text, "?"): return self.question_pause
        else: return self.unknown_sentence_detection_pause

    def _text_worker(self) -> None:
        while True:
            try:
                text = self.text_queue.get(block=True, timeout=0.1)
            except queue.Empty:
                time.sleep(0.01)
                continue
            logger.info(f"🎤⚙️ Starting pause calculation for: \"{text}\"")
            processed_text = preprocess_text(text)
            current_time = time.time()
            self.text_time_deque.append((current_time, processed_text))
            text_without_punctuation = strip_ending_punctuation(processed_text)
            self.texts_without_punctuation.append((processed_text, text_without_punctuation))
            matches = find_matching_texts(self.texts_without_punctuation)
            added_pauses = 0
            contains_ellipses = False
            if matches:
                for match in matches:
                    same_text, _ = match
                    added_pauses += self.get_suggested_whisper_pause(same_text)
                    if ends_with_string(same_text, "..."): contains_ellipses = True
                avg_pause = added_pauses / len(matches)
            else:
                avg_pause = self.get_suggested_whisper_pause(processed_text)
                if ends_with_string(processed_text, "..."): contains_ellipses = True
            whisper_suggested_pause = avg_pause
            import string
            transtext = processed_text.translate(str.maketrans('', '', string.punctuation))
            cleaned_for_model = re.sub(r'[^a-zA-Z\s]+$', '', transtext).rstrip()
            prob_complete = self.get_completion_probability(cleaned_for_model)
            sentence_finished_model_pause = interpolate_detection(prob_complete)
            weight_towards_whisper = 0.65
            weighted_pause = (weight_towards_whisper * whisper_suggested_pause + (1 - weight_towards_whisper) * sentence_finished_model_pause)
            final_pause = weighted_pause * self.detection_speed
            if contains_ellipses: final_pause += 0.2
            logger.info(f"🎤📊 Calculated pauses: Punct={whisper_suggested_pause:.2f}, Model={sentence_finished_model_pause:.2f}, Weighted={weighted_pause:.2f}, Final={final_pause:.2f} for \"{processed_text}\" (Prob={prob_complete:.2f})")
            min_pause = self.pipeline_latency + self.pipeline_latency_overhead
            if final_pause < min_pause:
                logger.info(f"🎤⚠️ Final pause ({final_pause:.2f}s) is less than minimum ({min_pause:.2f}s). Using minimum.")
                final_pause = min_pause
            self.suggest_time(final_pause, processed_text)
            self.text_queue.task_done()

    def calculate_waiting_time(self, text: str) -> None:
        logger.info(f"🎤📥 Queuing text for pause calculation: \"{text}\"")
        self.text_queue.put(text)

    def reset(self) -> None:
        logger.info("🎤🔄 Resetting TurnDetection state.")
        self.text_time_deque.clear()
        self.texts_without_punctuation.clear()
        self.current_waiting_time = -1
        if hasattr(self, "_completion_probability_cache"):
            self._completion_probability_cache.clear()

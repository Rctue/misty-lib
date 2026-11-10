# mistymain.py
# Misty robot interaction controller — TU/e Open Day
# Laptop-mic STT + LLM dialogue with tone-driven LED + expression

from __future__ import annotations

import queue
import random
import threading
import time
from enum import Enum

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from mistyPy.EventFilters import EventFilters
from mistyPy.Events import Events
from mistyPy.Robot import Robot

from dialogue import DialogueManager, DialogueResponse
from minigames import EnhancedGameManager, GameType
from mistyidle import IdleManager
from mistyemotions import MistyEmotions, Emotion
import torch

# ---------------------------------------------------------------------------
# Whisper model setup
# ---------------------------------------------------------------------------

def _create_whisper_model() -> WhisperModel:
    if torch.cuda.is_available():
        try:
            model = WhisperModel("base", device="cuda", compute_type="float16")
            print("[STT] GPU found, CUDA active.")
            return model
        except Exception as e:
            print(f"[STT] CUDA failed ({e}), falling back to CPU.")
    print("[STT] CPU mode active.")
    return WhisperModel("base", device="cpu", compute_type="int8")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MISTY_IP                = "192.168.0.152"
VOLUME                  = 100
STT_MODEL               = _create_whisper_model()
STT_LANGUAGE            = "en"
LISTENING_SYSTEM_ENABLED = False # Set to False for button-only mode (left=yes, right=no)

IDLE_TOUCH_DEBOUNCE_MS  = 500
BUMPER_DEBOUNCE_MS      = 250
FACE_EVENT_DEBOUNCE_MS  = 1000
PERSON_COOLDOWN_SECONDS = 12.0

SAMPLE_RATE       = 16000
BLOCK_SIZE        = 512
SILENCE_THRESHOLD = 0.012
SILENCE_BLOCKS    = 25
MAX_RECORD_BLOCKS = 250

# ---------------------------------------------------------------------------
# Interaction states
# ---------------------------------------------------------------------------

class InteractionState(Enum):
    IDLE             = "idle"
    GREETING_CONSENT = "greeting_consent"
    ENGINEER_CONFIRM = "engineer_confirm"
    GAME_MENU        = "game_menu"
    PLAYING_GAME     = "playing_game"
    GIVING_FEEDBACK  = "giving_feedback"


# ---------------------------------------------------------------------------
# Engagement gate
# ---------------------------------------------------------------------------

class EngagementGate:
    def __init__(self, cooldown: float = PERSON_COOLDOWN_SECONDS) -> None:
        self._lock      = threading.Lock()
        self._triggered = False
        self._last_time = 0.0
        self._cooldown  = cooldown

    def try_trigger(self, state: InteractionState, source: str) -> bool:
        now = time.time()
        with self._lock:
            if state != InteractionState.IDLE:
                return False
            if self._triggered:
                return False
            if now - self._last_time < self._cooldown:
                return False
            self._triggered = True
            self._last_time = now
        print(f"[ENGAGEMENT] triggered by {source}")
        return True

    def reset(self) -> None:
        with self._lock:
            self._triggered = False


# ---------------------------------------------------------------------------
# Local speech listener
# ---------------------------------------------------------------------------

class LocalSpeechListener:
    def __init__(self, model: WhisperModel, on_transcript) -> None:
        self.model         = model
        self.on_transcript = on_transcript
        self._q            = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running      = False
        self._active       = False

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(
            target=self._listen_loop, name="local-stt", daemon=True
        )
        self._thread.start()
        print("[STT] Laptop-mic listener started.")

    def enable(self) -> None:
        print("[STT] Listening enabled.")
        self._active = True

    def disable(self) -> None:
        print("[STT] Listening disabled.")
        self._active = False

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if self._active:
            self._q.put(indata.copy())

    def _listen_loop(self) -> None:
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                callback=self._audio_callback,
            ):
                while self._running:
                    self._wait_for_utterance()
        except Exception as e:
            print(f"[STT] Audio input stream error: {e}")

    def _wait_for_utterance(self) -> None:
        frames        = []
        silence_count = 0
        speaking      = False

        while True:
            try:
                block = self._q.get(timeout=0.5)
            except queue.Empty:
                if not self._active:
                    return
                continue

            rms = float(np.sqrt(np.mean(block ** 2)))

            if rms > SILENCE_THRESHOLD:
                speaking      = True
                silence_count = 0
                frames.append(block)
            elif speaking:
                silence_count += 1
                frames.append(block)
                if silence_count >= SILENCE_BLOCKS or len(frames) >= MAX_RECORD_BLOCKS:
                    break

        if speaking and frames:
            audio = np.concatenate(frames, axis=0).squeeze()
            self._transcribe(audio)

    def _transcribe(self, audio: np.ndarray) -> None:
        try:
            segments, _ = self.model.transcribe(
                audio, language=STT_LANGUAGE, beam_size=1, vad_filter=True,
            )
            text = " ".join(s.text for s in segments).strip()
            if text:
                print(f"[STT] Recognised: '{text}'")
                self.on_transcript(text)
        except Exception as exc:
            print(f"[STT] Transcription error: {exc}")


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------

class MistyInteractionController:
    def __init__(self, misty: Robot) -> None:
        self.misty      = misty
        self.dialogue   = DialogueManager()
        self.idle       = IdleManager(misty)
        self.emotions   = MistyEmotions(misty, self.idle)
        self.stt        = LocalSpeechListener(STT_MODEL, self._on_local_speech)
        self.games      = EnhancedGameManager(misty, self.dialogue, self._on_game_finished, self._speak, self.stt, self.emotions)

        self.buttononly_game = None
        self.state      = InteractionState.IDLE
        self.state_lock = threading.Lock()
        self.engagement = EngagementGate()

        # Speech & State Timer Management
        self._speech_lock = threading.Lock()
        self._speech_gen  = 0
        self._active_timer: threading.Timer | None = None
        self._timer_lock = threading.Lock()

    def start(self) -> None:
        self.misty.SetDefaultVolume(VOLUME)
        self._register_events()
        self._start_face_detection()
        self._enter_idle()
        if LISTENING_SYSTEM_ENABLED:
            self.stt.start()
            self.stt.enable()
        
    def _register_events(self) -> None:
        self.misty.RegisterEvent(
            event_name="face_detection",
            event_type=Events.FaceRecognition,
            debounce=FACE_EVENT_DEBOUNCE_MS,
            keep_alive=True,
            callback_function=self._on_face_event,
        )
        self.misty.RegisterEvent(
            event_name="head_touch_start",
            event_type=Events.TouchSensor,
            condition=[
                EventFilters.CapTouchPosition.Front,
                EventFilters.event_filter("IsContacted", "=", "True"),
            ],
            debounce=IDLE_TOUCH_DEBOUNCE_MS,
            keep_alive=True,
            callback_function=self._on_touch_event,
        )
        self.misty.RegisterEvent(
            event_name="bumper_input",
            event_type=Events.BumpSensor,
            debounce=BUMPER_DEBOUNCE_MS,
            keep_alive=True,
            callback_function=self._on_bumper_event,
        )

    def _start_face_detection(self) -> None:
        print("[Misty] Face detection started.")
        self.misty.StartFaceDetection()

    # ------------------------------------------------------------------
    # Thread-safe Timer Management
    # ------------------------------------------------------------------
    def _set_state_timeout(self, delay: float, target_function) -> None:
        """Disables the previous timer and sets a new one"""
        with self._timer_lock:
            if self._active_timer is not None:
                self._active_timer.cancel()
            self._active_timer = threading.Timer(delay, target_function)
            self._active_timer.daemon = True
            self._active_timer.start()

    def _cancel_active_timeout(self) -> None:
        with self._timer_lock:
            if self._active_timer is not None:
                self._active_timer.cancel()
                self._active_timer = None

    def _set_state(self, new_state: InteractionState) -> None:
        with self.state_lock:
            print(f"[STATE] {self.state.value} → {new_state.value}")
            self.state = new_state
        self._cancel_active_timeout()

    def _get_state(self) -> InteractionState:
        with self.state_lock:
            return self.state

    # ------------------------------------------------------------------
    # Flow & Transitions
    # ------------------------------------------------------------------

    def _enter_idle(self) -> None:
        self._set_state(InteractionState.IDLE)
        self.engagement.reset()
        self.idle.start()   
        self.stt.enable()
        print("[State] IDLE")

    def _on_face_event(self, data: dict) -> None:
        self.games.note_face_seen()
        msg     = data.get("message", {})
        bearing = float(msg.get("bearing", 0.0))

        current_state = self._get_state()
        if current_state == InteractionState.IDLE:
            self.idle.face_track(bearing)

        if self.engagement.try_trigger(current_state, "face"):
            threading.Thread(target=self._start_greeting_flow, daemon=True).start()

    def _on_touch_event(self, data: dict) -> None:
        if self._is_contact(data):
            if self.engagement.try_trigger(self._get_state(), "touch"):
                threading.Thread(target=self._start_greeting_flow, daemon=True).start()

    def _on_bumper_event(self, data: dict) -> None:
        if not self._is_contact(data):
            return
        sensor_id   = self._sensor_id(data)
        bumper_side = "right" if sensor_id == "bfl" else "left" if sensor_id == "bfr" else None
        if bumper_side is None:
            return

        current = self._get_state()

        # In IDLE, left button starts greeting if listening is disabled
        if current == InteractionState.IDLE and not LISTENING_SYSTEM_ENABLED:
            if bumper_side == "left":
                if self.engagement.try_trigger(current, "button"):
                    threading.Thread(target=self._start_greeting_flow, daemon=True).start()
            return

        if current in (InteractionState.GREETING_CONSENT, InteractionState.ENGINEER_CONFIRM):
            self._on_local_speech("yes" if bumper_side == "left" else "no")
        elif current == InteractionState.GAME_MENU:
            if bumper_side == "left":
                if not LISTENING_SYSTEM_ENABLED:
                    self._start_game(self.buttononly_game)
                else:
                    self._start_game(random.choice(list(GameType)))
            else:
                print("[GAME_MENU] Returning to idle")
                resp = self.dialogue.event("game_menu", "no")
                self._apply_tone(resp)
                self._speak(resp.reply)
                threading.Timer(1.5, self._enter_idle).start()
        elif current == InteractionState.PLAYING_GAME:
            self.games.handle_bumper(bumper_side)

    # ------------------------------------------------------------------
    # Flow Threads
    # ------------------------------------------------------------------

    def _start_greeting_flow(self) -> None:
        self.idle.stop()
        self._set_state(InteractionState.GREETING_CONSENT)
        print("[State] GREETING_CONSENT")

        # Reset Misty position
        self.misty.MoveHead(0, 0, 0, 70, None, None)
        self.misty.MoveArms(25, 25, 30, 30, None, None)

        result = self.dialogue.event("greeting_consent", "intro")
        self._apply_tone(result)

        # Curious scanning gesture
        self.emotions.play_async(Emotion.CURIOUS)

        self._speak(result.reply, reenable_stt=True)
        print("[State] Waiting for consent")

    # ------------------------------------------------------------------
    # Speech Routing
    # ------------------------------------------------------------------

    def _on_local_speech(self, text: str) -> None:
        current = self._get_state()
        print(f"[Speech] state={current.value!r} text={text!r}")

        if current == InteractionState.IDLE:
            if self._is_greeting(text):
                if self.engagement.try_trigger(current, "speech"):
                    threading.Thread(target=self._start_greeting_flow, daemon=True).start()
            return

        if current == InteractionState.GREETING_CONSENT:
            resp = self.dialogue.event("engineer_confirm", text)
            if self._is_yes(text) or resp.intent == "yes":
                self._set_state(InteractionState.ENGINEER_CONFIRM)
                resp = self.dialogue.event("greeting_consent", "yes")
                self._apply_tone(resp)
                self._speak(resp.reply)
                
                # Scan animation with thinking emotion
                def _scan_and_guess():
                    self.emotions.play(Emotion.THINKING)
                    self._do_engineer_guess()
                threading.Thread(target=_scan_and_guess, daemon=True).start()
                
            elif self._is_no(text) or resp.intent == "yes":
                resp = self.dialogue.event("greeting_consent", "no")
                self._apply_tone(resp)
                self.emotions.play_async(Emotion.SAD)
                self._speak(resp.reply)
                time.sleep(2.0)
                self._enter_idle()
            else:
                #resp = self.dialogue.event("greeting_consent", "unknown")
                self._apply_tone(resp)
                self.emotions.play_async(Emotion.CONFUSED)
                self._speak(resp.reply, reenable_stt=True)
            return

        if current == InteractionState.ENGINEER_CONFIRM:
            resp = self.dialogue.event("engineer_confirm", text)
            if self._is_yes(text) or resp.intent == "yes":
                resp = self.dialogue.event("engineer_confirm", "yes")
                self._apply_tone(resp)
                self.emotions.play_async(Emotion.EXCITED)   # Misty was right — celebrate
                self._speak(resp.reply)
                time.sleep(1.2)
                self._show_game_menu()
            elif self._is_no(text) or resp.intent == "No":
                resp = self.dialogue.event("engineer_confirm", "no")
                self._apply_tone(resp)
                self.emotions.play_async(Emotion.DISAPPOINTED)  # Misty was wrong
                self._speak(resp.reply)
                time.sleep(1.2)
                self._show_game_menu()
            else:
                self._apply_tone(resp)
                self.emotions.play_async(Emotion.CONFUSED)
                self._speak(resp.reply, reenable_stt=True)
            return

        if current == InteractionState.GAME_MENU:
            game = self._game_from_text(text)
            if game:
                self._start_game(game)
                return
            resp = self.dialogue.respond("game_menu",text)
            self._apply_tone(resp)
            if resp.intent == "random" or resp.intent == "left_pressed":
                self._speak(resp.reply)
                threading.Timer(
                    1.0,
                    lambda: self._start_game(random.choice(list(GameType)))
                ).start()
            elif resp.intent == "no":
                self._speak(resp.reply)
                threading.Timer(1.5, self._enter_idle).start()
            elif resp.intent == "list_games" or resp.intent == "repeat":
                repeat_resp = self.dialogue.event("game_menu", "repeat")
                self._speak(repeat_resp.reply, reenable_stt=True)
            else:
                self._speak(resp.reply, reenable_stt=True)

            return

        if current == InteractionState.PLAYING_GAME:
            self.games.handle_speech(text)
            return

    # ------------------------------------------------------------------
    # Actions & Helpers
    # ------------------------------------------------------------------

    def _do_engineer_guess(self) -> None:
        guess = self.dialogue.event("engineer_confirm", "guess")
        self._apply_tone(guess)
        self._speak(guess.reply, reenable_stt=True)
        
        # Reset Misty position
        self.misty.MoveHead(0, 0, 0, 70, None, None)
        self.misty.MoveArms(25, 25, 30, 30, None, None)

    def _show_game_menu(self) -> None:
        self._set_state(InteractionState.GAME_MENU)
        print("[State] GAME_MENU")

        if not LISTENING_SYSTEM_ENABLED:
            #GameType.REACTION_TEST
            #GameType.STARING_CONTEST
            #GameType.COPY_MOVE
            #GameType.EMOTION_GUESS
            #GameType.SORTING
            #random.choice(list(GameType))
            self.buttononly_game = random.choice(list(GameType))
            intro = self.dialogue.event("game_menu", "auto_pick", context={"game": self.buttononly_game.value.replace('_', ' ')})
            self._apply_tone(intro)
            intro.reply = intro.reply.replace("{game}", self.buttononly_game.value.replace('_', ' '))
            self._speak(intro.reply)
            return

        intro = self.dialogue.event("game_menu", "intro")
        self._apply_tone(intro)
        self._speak(intro.reply, reenable_stt=True)

    def _repeat_game_menu(self) -> None:
        repeat = self.dialogue.event("game_menu", "repeat")
        self._apply_tone(repeat)
        self._speak(repeat.reply, reenable_stt=True)

    def _start_game(self, game: GameType) -> None:
        self._set_state(InteractionState.PLAYING_GAME)
        self.stt.disable()
        print(f"[State] PLAYING_GAME ({game.value})")
        self.games.start_game(game)

    def _on_game_finished(self, destination: str = "idle") -> None:
        self._set_state(InteractionState.GIVING_FEEDBACK)
        print(f"[State] GIVING_FEEDBACK → {destination}")
        if destination == "menu":
            self._show_game_menu()
        else:
            self._enter_idle()

    @staticmethod
    def _is_greeting(text: str) -> bool:
        t = text.lower()
        return any(w in t for w in (
            "hello", "hi", "hey", "hiya", "howdy",
            "good morning", "good afternoon", "good evening",
            "hallo", "hoi", "hé", "dag",
        ))

    @staticmethod
    def _is_yes(text: str) -> bool:
        t = text.lower()
        return any(w in t for w in ("yes", "yeah", "yep", "sure", "alright", "okay", "ok", "pretty close", "close", "ready", "of course", "continue", "go ahead"))

    @staticmethod
    def _is_no(text: str) -> bool:
        t = text.lower()
        return any(w in t for w in ("no", "nope", "stop", "wrong", "not close", "you are wrong"))

    @staticmethod
    def _game_from_text(text: str) -> GameType | None:
        t = text.lower()
        if any(w in t for w in ("staring", "stare", "eyes")): return GameType.STARING_CONTEST
        if any(w in t for w in ("copy", "move", "mirror", "gesture", "pose")): return GameType.COPY_MOVE
        if any(w in t for w in ("reaction", "speed", "reflex", "fast")): return GameType.REACTION_TEST
        if any(w in t for w in ("emotion", "feeling", "guess")): return GameType.EMOTION_GUESS
        if any(w in t for w in ("sorting", "sort", "categories")): return GameType.SORTING
        if any(w in t for w in ("random", "idk")): return random.choice(list(GameType))
        return None

    def _speak(self, text: str, reenable_stt: bool = False) -> None:
        self.stt.disable()
        with self._speech_lock:
            self._speech_gen += 1
            gen = self._speech_gen
        self.misty.Speak(text)
        if reenable_stt and LISTENING_SYSTEM_ENABLED:
            duration = max(1.5, (len(text) / 14)+1)
            def _maybe_enable():
                with self._speech_lock:
                    if self._speech_gen == gen:
                        self.stt.enable()
            threading.Timer(duration, _maybe_enable).start()

    def _apply_tone(self, result: DialogueResponse) -> None:
        self.misty.ChangeLED(*result.led)
        self.misty.DisplayImage(result.image)

    def _is_contact(self, data: dict) -> bool:
        msg = data.get("message", {})
        return msg.get("isContacted") is True or msg.get("IsContacted") is True

    def _sensor_id(self, data: dict) -> str:
        msg = data.get("message", {})
        return msg.get("sensorId") or msg.get("SensorId") or ""

    def keep_alive(self) -> None:
        self.misty.KeepAlive()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def initialize() -> MistyInteractionController:
    misty      = Robot(MISTY_IP)
    controller = MistyInteractionController(misty)
    controller.start()
    return controller


def mainloop(controller: MistyInteractionController) -> None:
    try:
        while True:
            controller.keep_alive()
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n[Main] Stopped.")


if __name__ == "__main__":
    app = initialize()
    mainloop(app)

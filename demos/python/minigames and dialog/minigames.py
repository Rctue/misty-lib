from __future__ import annotations

import random
import threading
import time
from enum import Enum, auto
from typing import Callable

from mistyPy.Robot import Robot

from dialogue import DialogueManager, DialogueResponse
from mistyemotions import MistyEmotions, Emotion

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LISTENING_SYSTEM_ENABLED = True  # Sync with mistymain.py config

# ---------------------------------------------------------------------------
# Game Configuration & Types
# ---------------------------------------------------------------------------

class GameType(Enum):
    REACTION_TEST   = "reaction_test"
    STARING_CONTEST = "staring_contest"
    COPY_MOVE       = "copy_move"
    EMOTION_GUESS   = "emotion_guess"
    SORTING         = "sorting"


class _StaringPhase(Enum):
    INTRO          = auto()
    WAITING_READY  = auto()
    COUNTDOWN      = auto()
    ACTIVE         = auto()
    ENDING         = auto()
    POST_GAME      = auto()
    DONE           = auto()


SORTING_ROUNDS = [
    {
        "category_a": "living thing",
        "category_b": "non-living thing",
        "items": [
            ("a dog",   "left"),
            ("a rock",  "right"),
            ("a tree",  "left"),
            ("a chair", "right"),
            ("a fish",  "left"),
        ],
    },
    {
        "category_a": "indoor thing",
        "category_b": "outdoor thing",
        "items": [
            ("a sofa",       "left"),
            ("a tree",       "right"),
            ("a television", "left"),
            ("a bicycle",    "right"),
            ("a lamp",       "left"),
        ],
    },
    {
        "category_a": "hot thing",
        "category_b": "cold thing",
        "items": [
            ("fire",      "left"),
            ("ice cream", "right"),
            ("the sun",   "left"),
            ("snow",      "right"),
            ("coffee",    "left"),
        ],
    },
]

# ---------------------------------------------------------------------------
# EnhancedGameManager
# ---------------------------------------------------------------------------

class EnhancedGameManager:
    """
    Manages all 5 mini-games for Misty. All speech is routed through DialogueManager;
    no hardcoded strings live here.
    """
    # Staring-contest timing constants
    FACE_LOST_THRESHOLD_SECONDS = 1.2
    MISTY_BLINK_MIN = 20.0
    MISTY_BLINK_MAX = 30.0

    PROVOCATION_SCHEDULE: list[tuple[float, str]] = [
        ( 5.0, "provocation_steady"),
        (10.0, "provocation_distract"),
        (12.0, "provocation_distract_followup"),
        (17.0, "provocation_eyelids"),
    ]

    COPY_POSES: list[dict] = [
        {"name": "right arm up",    "arms": (-70,  25), "head": ( 0,  0,  15), "answer": "right"},
        {"name": "left arm up",     "arms": ( 25, -70), "head": ( 0,  0, -15), "answer": "left"},
        {"name": "both arms up",    "arms": (-70, -70), "head": (-10,  0,   0), "answer": "both"},
        {"name": "head tilt right", "arms": ( 25,  25), "head": ( 0, 20,   0), "answer": "tilt"},
        {"name": "right arm out",   "arms": (-30,  25), "head": ( 0,  0,  10), "answer": "right"},
    ]

    EMOTIONS: list[dict] = [
        {"name": "happy",    "image": "e_JoyGoofy3.jpg",   "led": (  0, 255,  80), "arms": (-55, -55), "head": ( -8,  0,   0)},
        {"name": "sad",      "image": "e_Sadness.jpg",      "led": ( 40,  40, 200), "arms": ( 35,  35), "head": ( 15,  0,   0)},
        {"name": "confused", "image": "e_Confusion.jpg",    "led": (180,   0, 255), "arms": ( 25,  25), "head": (  0, 15, -12)},
        {"name": "angry",    "image": "e_Anger.jpg",        "led": (255,  40,  20), "arms": (-20, -20), "head": (-10,  0,   0)},
        {"name": "excited",  "image": "e_Admiration.jpg",   "led": (255, 200,   0), "arms": (-70, -70), "head": (-12,  0,   0)},
    ]
    EMOTION_NAMES: list[str] = [e["name"] for e in EMOTIONS]

    def __init__(
        self,
        misty: Robot,
        dialogue: DialogueManager,
        on_game_finished,
        speak,
        stt,
        emotions: "MistyEmotions",
    ) -> None:
        self.misty            = misty
        self.dialogue         = dialogue
        self.on_game_finished = on_game_finished
        self._speak           = speak
        self._stt             = stt
        self.emotions         = emotions

        self.active_game: GameType | None = None
        self.game_lock        = threading.Lock()

        # Shared input queue for bumper + speech events during a game
        self._input_condition = threading.Condition()
        self._pending_inputs: list[tuple[str, str]] = []

        # Reaction-test state
        self._reaction_signal_time: float | None = None
        self._reaction_finished    = False
        self._reaction_accepting_input = False

        # Staring-contest state
        self._sc_phase:           _StaringPhase          = _StaringPhase.DONE
        self._sc_lock:            threading.Lock         = threading.Lock()
        self._sc_start_time:      float | None           = None
        self._sc_warn_timer:      threading.Timer | None = None
        self._sc_giveup_timer:    threading.Timer | None = None
        self._sc_lose_timer:      threading.Timer | None = None
        self._sc_post_game_timer: threading.Timer | None = None
        self._last_face_seen_at   = time.time()

        # Sorting-game state
        self._sorting_total   = 0
        self._sorting_correct = 0

    # ------------------------------------------------------------------
    # Public: Start / Dispatch
    # ------------------------------------------------------------------

    def start_game(self, game: GameType) -> None:
        with self.game_lock:
            self.active_game           = game
            self._reaction_signal_time = None
            self._reaction_finished    = False
            self._reaction_accepting_input = False
        
        with self._input_condition:
            self._pending_inputs.clear()

        runners = {
            GameType.REACTION_TEST:   self._run_reaction,
            GameType.STARING_CONTEST: self._run_staring,
            GameType.COPY_MOVE:       self._run_copy_move,
            GameType.EMOTION_GUESS:   self._run_emotion_guess,
            GameType.SORTING:         self._run_sorting,
        }

        # Reset Misty position
        self.misty.MoveHead(0, 0, 0, 70, None, None)
        self.misty.MoveArms(25, 25, 30, 30, None, None)
        
        threading.Thread(
            target=runners[game], name=game.value, daemon=True
        ).start()

    def handle_speech(self, text: str) -> bool:
        """Called by controller when speech arrives during game execution."""
        with self.game_lock:
            if self.active_game is None:
                return False
        
        with self._input_condition:
            self._pending_inputs.append(("speech", text.strip().lower()))
            self._input_condition.notify_all()
        return True

    def handle_bumper(self, side: str) -> bool:
        """Called by controller on bumper press during game execution."""
        with self.game_lock:
            active = self.active_game
            if active is None:
                return False
            
            # Special fast-path intercept for reaction test to catch millisecond accuracy
            if active == GameType.REACTION_TEST and not self._reaction_finished:
                if not self._reaction_accepting_input:
                    if not self._reaction_accepting_input:
                        # Queue zetten
                        with self._input_condition:
                            self._pending_inputs.append(("button", side))
                            self._input_condition.notify_all()
                        return True
                if self._reaction_signal_time is None:
                    self._reaction_finished = True
                    threading.Thread(
                        target=self._finish_reaction, args=("early", None), daemon=True
                    ).start()
                else:
                    self._reaction_finished = True
                    elapsed_ms = int((time.perf_counter() - self._reaction_signal_time) * 1000)
                    threading.Thread(
                        target=self._finish_reaction, args=("success", elapsed_ms), daemon=True
                    ).start()
                return True

        with self._input_condition:
            self._pending_inputs.append(("button", side))
            self._input_condition.notify_all()
        return True

    def note_face_seen(self) -> None:
        """Controller calls this whenever a face detection event fires."""
        self._last_face_seen_at = time.time()
        
    def handle_face_lost(self) -> None:
        with self._sc_lock:
            if self._sc_phase != _StaringPhase.ACTIVE:
                return
        result = self.dialogue.event(state="staring_active", event="face_lost")
        self._say(result)
    
    # ------------------------------------------------------------------
    # Input Helpers & Matchers
    # ------------------------------------------------------------------

    def _wait_for_input(
        self,
        timeout: float,
        buttons: set[str] | None = None,
        matcher=None,
    ) -> tuple[str, str] | None:
        """Block until a matching input arrives or timeout expires."""
        deadline = time.time() + timeout
        with self._input_condition:
            while True:
                for idx, (kind, value) in enumerate(self._pending_inputs):
                    if kind == "button" and (buttons is None or value in buttons):
                        return self._pending_inputs.pop(idx)
                    if kind == "speech" and (matcher is None or matcher(value)):
                        return self._pending_inputs.pop(idx)
                
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._input_condition.wait(remaining)

    @staticmethod
    def _match_ready(t: str) -> bool:
        return any(w in t for w in ("ready", "yes", "sure", "alright", "okay", "ok", "go"))

    @staticmethod
    def _match_stop(t: str) -> bool:
        return any(w in t for w in ("stop", "give up", "quit", "exit", "done", "no", "forfeit"))

    @staticmethod
    def _match_again(t: str) -> bool:
        return any(w in t for w in ("again", "rematch", "another", "retry", "play again"))

    # ------------------------------------------------------------------
    # Communication Helper
    # ------------------------------------------------------------------

    def _say(self, result: DialogueResponse, reenable_stt: bool = False) -> None:
        self.misty.ChangeLED(*result.led)
        self.misty.DisplayImage(result.image)
        self._speak(result.reply, reenable_stt=reenable_stt)

    def _finish_game(self, destination: str = "menu") -> None:
        with self.game_lock:
            self.active_game = None
        self.on_game_finished(destination)

    # ------------------------------------------------------------------
    # Game 1: Reaction Test
    # ------------------------------------------------------------------

    def _run_reaction(self) -> None:
        print("[ReactionTest] Started")
        result = self.dialogue.event(state="reaction", event="reaction_explain")
        self._say(result)
        time.sleep(max(1.5, (len(result.reply) / 14)+1))

        #  Wait on "ready" or left bumper; right bumper = skip
        ready = self._wait_for_input(
            float(10000), buttons={"left", "right"}, matcher=lambda t: self._match_ready(t) or self._match_stop(t)
        )
        if ready is None or (ready[0] == "button" and ready[1] == "right") or (ready[0] == "speech" and self._match_stop(ready[1])):
            self._finish_game("menu")
            return

        go_soon = self.dialogue.event(state="reaction", event="reaction_ready_ack")
        self._say(go_soon)
        time.sleep(max(0.5, (len(result.reply) / 14)+1))

        with self.game_lock:
            if self._reaction_finished:
                return
            self._reaction_accepting_input = True

        delay = random.uniform(2.0, 5.0)
        print(f"[ReactionTest] Waiting random delay: {delay:.2f}s")
        time.sleep(delay)

        with self.game_lock:
            if self._reaction_finished:
                return
            self._reaction_signal_time = time.perf_counter()
            print("[ReactionTest] GO signal shown")

        go = self.dialogue.event(state="reaction", event="reaction_go")
        self._say(go)

    def _finish_reaction(self, result_type: str, elapsed_ms: int | None) -> None:
        print(f"[ReactionTest] Finished: {result_type}, elapsed={elapsed_ms}")
        if result_type == "early":
            self.emotions.play_async(Emotion.TEASING)
            fb = self.dialogue.event(state="reaction", event="reaction_early")
        else:
            # Fast reaction = excited win; slow = encouraging
            if elapsed_ms is not None and elapsed_ms < 350:
                self.emotions.play_async(Emotion.WIN)
            elif elapsed_ms is not None and elapsed_ms < 600:
                self.emotions.play_async(Emotion.EXCITED)
            else:
                self.emotions.play_async(Emotion.ENCOURAGING)
            fb = self.dialogue.event(
                state="reaction",
                event="reaction_result",
                context={"reaction_time_ms": elapsed_ms},
            )
            if elapsed_ms and str(elapsed_ms) not in fb.reply:
                fb.reply = fb.reply.rstrip(".!") + f" — {elapsed_ms} ms!"

        self._say(fb)
        time.sleep(3)
        self._ask_rematch(GameType.REACTION_TEST)

    # ------------------------------------------------------------------
    # Game 2: Staring Contest
    # ------------------------------------------------------------------

    def _run_staring(self) -> None:
        print("[StaringContest] Started")
        self._sc_set_phase(_StaringPhase.INTRO)
        self._sc_start_time = None
        
        intro = self.dialogue.event(state="staring_waiting_ready", event="intro")
        self._say(intro, reenable_stt=True)
        time.sleep(max(1.5, (len(intro.reply) / 14)+1))
        
        self._sc_set_phase(_StaringPhase.WAITING_READY)
        self.misty.MoveHead(0, 0, 0, 100, None, None)

        #  Wait on "ready" or left bumper; right bumper = skip
        ready = self._wait_for_input(
            float(10000), buttons={"left", "right"}, matcher=lambda t: self._match_ready(t) or self._match_stop(t)
        )
        if ready is None or (ready[0] == "button" and ready[1] == "right") or (ready[0] == "speech" and self._match_stop(ready[1])):
            self._finish_game("menu")
            return
        print("[StaringContest] Waiting for ready")

        # Start countdown
        print("[StaringContest] Countdown started")
        self._sc_set_phase(_StaringPhase.COUNTDOWN)
        countdown = self.dialogue.event(state="staring_countdown", event="countdown")
        self._say(countdown)
        time.sleep(max(1.5, (len(countdown.reply) / 14)+1))

        # Active Game Phase
        self._sc_set_phase(_StaringPhase.ACTIVE)
        print("[StaringContest] ACTIVE")
        self._sc_start_time = time.perf_counter()
        self._last_face_seen_at = time.time()
        self.misty.MoveHead(0, 0, 0, 50, None, None)

        # Threading loops for provocations and limits
        blink_delay = random.uniform(self.MISTY_BLINK_MIN, self.MISTY_BLINK_MAX)
        print(f"[StaringContest] Misty will blink at {blink_delay:.1f}s")
        threading.Thread(target=self._sc_run_provocations, name="staring-provoc", daemon=True).start()
        threading.Thread(target=self._sc_watch_face_presence, name="staring-face-watch", daemon=True).start()
        threading.Thread(target=self._sc_misty_blink_timeout, args=(blink_delay,), name="staring-blink", daemon=True).start()

        # Loop to monitor game active state and handle forfeit speech/buttons
        while True:
            inp = self._wait_for_input(0.5, buttons={"left", "right"},
                                       matcher=self._match_stop)
            with self._sc_lock:
                phase = self._sc_phase
            if phase != _StaringPhase.ACTIVE:
                break
            if inp is not None:
                with self._sc_lock:
                    if self._sc_phase != _StaringPhase.ACTIVE:
                        break
                    self._sc_phase = _StaringPhase.ENDING
                print("[StaringContest] → ENDING (forfeit)")
                threading.Thread(target=self._sc_human_forfeit, name="staring-ending", daemon=True).start()
                break

    def _sc_misty_blink_timeout(self, delay: float) -> None:
        time.sleep(delay)
        with self._sc_lock:
            if self._sc_phase != _StaringPhase.ACTIVE:
                return
            self._sc_phase = _StaringPhase.ENDING

        print("[StaringContest] → ENDING (Misty looked away)")
        # Quick head snap left-right as the "look away" using timers (non-blocking)
        self.misty.MoveHead(0, 0, -40, 80, None, None)
        threading.Timer(0.18, lambda: self.misty.MoveHead(0, 0, 40, 80, None, None)).start()
        threading.Timer(0.36, lambda: self.misty.MoveHead(0, 0, 0, 100, None, None)).start()
        threading.Timer(0.55, lambda: threading.Thread(target=self._sc_misty_loses, name="staring-ending", daemon=True).start()).start()

    def _sc_watch_face_presence(self) -> None:
        while True:
            time.sleep(0.2)
            with self._sc_lock:
                if self._sc_phase != _StaringPhase.ACTIVE:
                    return
                face_missing_for = time.time() - self._last_face_seen_at

            if face_missing_for >= self.FACE_LOST_THRESHOLD_SECONDS:
                print(f"[StaringContest] Face missing for {face_missing_for:.2f}s")
                self._sc_signal_human_looked_away()
                return
    
    def _sc_signal_human_looked_away(self) -> None:
        print("[StaringContest] Human looked away")
        with self._sc_lock:
            if self._sc_phase != _StaringPhase.ACTIVE:
                return
            self._sc_phase = _StaringPhase.ENDING
        
        print("[StaringContest] → ENDING (human looked away)")
        self._sc_cancel(self._sc_lose_timer)
        threading.Thread(target=self._sc_ending_misty_wins, name="staring-ending", daemon=True).start()

    def _sc_run_provocations(self) -> None:
        base = self._sc_start_time or time.perf_counter()
        for delay, event in self.PROVOCATION_SCHEDULE:
            target = base + delay
            while time.perf_counter() < target:
                time.sleep(0.1)
                with self._sc_lock:
                    if self._sc_phase != _StaringPhase.ACTIVE:
                        return

            result = self.dialogue.event(
                state="staring_active",
                event=event,
                context={"elapsed_seconds": self._sc_elapsed()},
            )
            self._say(result)
            time.sleep(max(1.5, (len(result.reply) / 14)+1))

    def _sc_ending_misty_wins(self) -> None:
        print("[StaringContest] Misty wins")
        elapsed = self._sc_elapsed()
        self.emotions.play(Emotion.WIN)                 # arms up + head bob

        result_win = self.dialogue.event(state="staring_ending", event="misty_wins")
        self._say(result_win)
        time.sleep(max(1.5, (len(result_win.reply) / 14)+1))

        result_followup = self.dialogue.event(
            state="staring_ending",
            event="misty_wins_result",
            context={"elapsed_seconds": elapsed},
        )
        if str(elapsed) not in result_followup.reply:
            result_followup.reply = result_followup.reply.rstrip(".!") + f" — {elapsed} seconds!"
        self._say(result_followup)
        time.sleep(max(1.5, (len(result_followup.reply) / 14)+1))

        self.misty.MoveArms(25, 25, 35, 35, None, None)
        self._sc_run_post_game()

    def _sc_misty_loses(self) -> None:
        print("[StaringContest] Misty loses")
        self.emotions.play(Emotion.LOSE)                # head droops, arms hang
        result = self.dialogue.event(state="staring_ending", event="misty_loses")
        self._say(result)
        time.sleep(max(1.5, (len(result.reply) / 14)+1))
        self.misty.MoveHead(0, 0, 0, 60, None, None)
        self._sc_run_post_game()

    def _sc_human_forfeit(self) -> None:
        print("[StaringContest] Human forfeited")
        self.emotions.play_async(Emotion.TEASING)       # cocky — they gave up!
        result = self.dialogue.event(state="staring_active", event="forfeit")
        self._say(result)
        time.sleep(max(1.5, (len(result.reply) / 14)+1))
        self._sc_run_post_game()

    def _sc_run_post_game(self) -> None:
        self._sc_set_phase(_StaringPhase.POST_GAME)
        prompt = self.dialogue.event(state="staring_post_game", event="post_game_prompt")
        self._say(prompt, reenable_stt=True)
        time.sleep(max(1.5, (len(prompt.reply) / 14)+1))

        response = self._wait_for_input(
            float(10000),
            buttons={"left", "right"},
            matcher=lambda t: self._match_stop(t) or self._match_again(t)
        )

        if response is None:
            self._sc_finish()
            return

        kind, value = response
        # Left bumper or explicit play again triggers a rematch
        if (kind == "button" and value == "left") or (kind == "speech" and self._match_again(value)):
            again_res = self.dialogue.event(state="staring_post_game", event="play_again")
            self._say(again_res)
            time.sleep(1.5)
            self._run_staring()
        else:
            goodbye_res = self.dialogue.event(state="staring_post_game", event="goodbye")
            self._say(goodbye_res)
            time.sleep(1)
            self._sc_finish()

    def _sc_elapsed(self) -> int:
        if self._sc_start_time is None:
            return 0
        return int(time.perf_counter() - self._sc_start_time)

    def _sc_set_phase(self, phase: _StaringPhase) -> None:
        with self._sc_lock:
            self._sc_phase = phase
        print(f"[StaringContest] → {phase.name}")

    def _sc_finish(self) -> None:
        self._sc_set_phase(_StaringPhase.DONE)
        self._finish_game("menu")
    
    @staticmethod
    def _sc_cancel(timer: threading.Timer | None) -> None:
        if timer is not None:
            timer.cancel()

    # ------------------------------------------------------------------
    # Game 3: Sorting Game
    # ------------------------------------------------------------------

    def _run_sorting(self) -> None:
        print("[Sorting] Started")
        if self._sorting_total > 0 and self._sorting_correct == self._sorting_total:
            harder = self.dialogue.event(state="sorting", event="sorting_harder")
            self._say(harder)
            round_data = SORTING_ROUNDS[2]
            self._sorting_total = 0
            self._sorting_correct = 0
        else:
            round_data = random.choice(SORTING_ROUNDS)
            self._sorting_total = 0
            self._sorting_correct = 0

        category_a = round_data["category_a"]
        category_b = round_data["category_b"]
        print(f"[Sorting] Categories: {category_a} vs {category_b}")
        items = round_data["items"][:5]

        intro = self.dialogue.event(
            state="sorting",
            event="intro",
            context={"category_a": category_a, "category_b": category_b},
        )
        intro.reply = intro.reply.replace("{category_a}", category_a).replace("{category_b}", category_b)
        self._say(intro, reenable_stt=True)
        time.sleep(max(1.5, (len(intro.reply) / 14) + 1))

        ready = self._wait_for_input(
            float(10000), 
            buttons={"left", "right"}, 
            matcher=lambda t: self._match_ready(t) or self._match_stop(t)
        )        
        if ready is None or (ready[0] == "button" and ready[1] == "right") or (ready[0] == "speech" and self._match_stop(ready[1])):
            skip = self.dialogue.event(state="sorting", event="sorting_skip")
            self._say(skip)
            self._finish_game("menu")
            return

        confirm = self.dialogue.event(
            state="sorting",
            event="confirm",
            context={"category_a": category_a, "category_b": category_b},
        )
        confirm.reply = confirm.reply.replace("{category_a}", category_a).replace("{category_b}", category_b)
        self._say(confirm)
        time.sleep(max(1.5, (len(confirm.reply) / 14) + 1))

        score = 0
        total = len(items)

        for item_name, correct_side in items:
            print(f"[Sorting] Item: {item_name}")
            prompt = self.dialogue.event(
                state="sorting",
                event="sorting_item",
                context={"item": item_name, "category_a": category_a, "category_b": category_b},
            )
            prompt.reply = prompt.reply.replace("{item}", item_name).replace("{category_a}", category_a).replace("{category_b}", category_b)
            self._say(prompt, reenable_stt=True)
            time.sleep(max(1.5, (len(prompt.reply) / 14) + 1))

            answer_input = self._wait_for_input(
                timeout=float(10000),
                buttons={"left", "right"},
                matcher=None,
            )
            if answer_input is None:
                skip = self.dialogue.event(state="sorting", event="sorting_skip")
                self._say(skip)
                time.sleep(max(1.5, (len(prompt.reply) / 14) + 1))
                self._finish_game("menu")
                return

            kind, value = answer_input
            chosen_side = None

            if kind == "button":
                chosen_side = value
            else:
                dialogue_resp = self.dialogue.respond(state="sorting", user_input=value)
                intent = dialogue_resp.intent

                if intent == "cold_thing" or intent == "no":
                    chosen_side = "right" if "cold" in category_b.lower() or "outdoor" in category_b.lower() or "non-living" in category_b.lower() else "left"
                elif intent == "yes" or intent == "start_game":
                    chosen_side = "left"
                else:
                    t_lower = value.lower()
                    if "right" in t_lower or "cold" in t_lower or "ice" in t_lower or "outdoor" in t_lower:
                        chosen_side = "right"
                    else:
                        chosen_side = "left"

            correct_category = category_a if correct_side == "left" else category_b
            print(f"[Sorting] User chose: {chosen_side} (Correct: {correct_side})")

            if chosen_side == correct_side:
                score += 1
                self._sorting_correct += 1
                self._sorting_total += 1
                self.emotions.play_async(Emotion.EXCITED)
                fb = self.dialogue.event(
                    state="sorting",
                    event="sorting_correct",
                    context={"item": item_name, "category": correct_category},
                )
                fb.reply = fb.reply.replace("{item}", item_name).replace("{category}", correct_category)
            else:
                self._sorting_total += 1
                self.emotions.play_async(Emotion.DISAPPOINTED)
                fb = self.dialogue.event(
                    state="sorting",
                    event="sorting_wrong",
                    context={"item": item_name, "category": correct_category},
                )
                fb.reply = fb.reply.replace("{item}", item_name).replace("{category}", correct_category)

            self._say(fb, reenable_stt=False)
            print(f"[Sorting] Current Score: {score}/{total}")
            time.sleep(max(1.5, (len(fb.reply) / 14) + 1))

        print(f"[Sorting] Final score: {score}/{total}")
        if score == total:
            event = "sorting_perfect"
            self.emotions.play_async(Emotion.WIN)
        elif score >= int(total * 0.6):
            event = "sorting_good"
            self.emotions.play_async(Emotion.HAPPY)
        elif score >= int(total * 0.3):
            event = "sorting_ok"
            self.emotions.play_async(Emotion.ENCOURAGING)
        else:
            event = "sorting_poor"
            self.emotions.play_async(Emotion.SAD)

        summary = self.dialogue.event(
            state="sorting",
            event=event,
            context={"score": score, "total": total},
        )
        self._say(summary)
        time.sleep(max(1.5, (len(summary.reply) / 14) + 1))

        self._ask_rematch(GameType.SORTING)

    # ------------------------------------------------------------------
    # Game 4: Copy Move
    # ------------------------------------------------------------------
    
    def _run_copy_move(self) -> None:
        print("[CopyMove] Started")

        intro = self.dialogue.event(state="copy_move", event="intro")
        self._say(intro, reenable_stt=True)

        # Wait on "ready" or left bumper; right bumper = skip
        ready = self._wait_for_input(
            float(10000), buttons={"left", "right"}, matcher=lambda t: self._match_ready(t) or self._match_stop(t)
        )
        if ready is None or (ready[0] == "button" and ready[1] == "right") or (ready[0] == "speech" and self._match_stop(ready[1])):
            self._finish_game("menu")
            return
    
        poses = self.COPY_POSES.copy()
        random.shuffle(poses)
        score = 0
        total = min(3, len(poses))
    
        for pose in poses[:total]:
            print(f"[CopyMove] Pose: {pose['name']}")
            # Show the pose
            ready_line = self.dialogue.event(
                state="copy_move", event="ready",
                context={"pose": pose["name"]},
            )
            self._say(ready_line)
            time.sleep(max(1.5, (len(ready_line.reply) / 14)+1))
            self.misty.MoveArms(pose["arms"][0], pose["arms"][1], 40, 40, None, None)
            self.misty.MoveHead(pose["head"][0], pose["head"][1], pose["head"][2], 55, None, None)
            time.sleep(2.0)
    
            # Ask visitor to mirror
            wait_line = self.dialogue.event(
                state="copy_move", event="no_movement_5s",
                context={"pose": pose["name"]},
            )
            self._say(wait_line, reenable_stt=True)
    
            response = self._wait_for_input(
                float(10000),
                buttons={"left", "right"},
                matcher=lambda t: (
                    "again" in t or "show" in t
                    or "done" in t or "ready" in t
                    or "right" in t or "left" in t
                    or "both" in t or "tilt" in t
                ),
            )

            if response is None:
                response = ("button", "right")

            kind, value = response
            print(f"[CopyMove] Response: {response}")
    
            # Visitor wants to see the pose again
            if kind == "speech" and ("again" in value or "show" in value):
                again_line = self.dialogue.event(state="copy_move", event="again")
                self._say(again_line)
                time.sleep(max(1.5, (len(again_line.reply) / 14)+1))
                self.misty.MoveArms(pose["arms"][0], pose["arms"][1], 40, 40, None, None)
                self.misty.MoveHead(pose["head"][0], pose["head"][1], pose["head"][2], 55, None, None)
                time.sleep(1.8)
                response = self._wait_for_input(
                    float(10000), buttons={"left", "right"},
                    matcher=lambda t: "done" in t or "ready" in t or "right" in t or "left" in t or "both" in t,
                )
                if response is None:
                    response = ("button", "right")
                kind, value = response
    
            # Evaluate the attempt:
            # Left bumper = "I did it correctly", right bumper = skip/wrong
            # Speech: check if the pose answer keyword is mentioned
            correct = (
                (kind == "button" and value == "left")
                or (kind == "speech" and ("done" in value or "ready" in value))
            )
            partial = kind == "speech" and any(
                w in value for w in ("almost", "close", "sort of", "kind of")
            )
            print(f"[CopyMove] Correct={correct} Partial={partial}")
    
            if correct and not partial:
                score += 1
                self.emotions.play_async(Emotion.EXCITED)
                fb = self.dialogue.event(
                    state="copy_move", event="correct",
                    context={"pose": pose["name"]},
                )
                print(f"[CopyMove] Score: {score}/{total}")
            elif partial:
                self.emotions.play_async(Emotion.ENCOURAGING)
                fb = self.dialogue.event(
                    state="copy_move", event="partially_correct",
                    context={"pose": pose["name"]},
                )
            else:
                self.emotions.play_async(Emotion.DISAPPOINTED)
                fb = self.dialogue.event(
                    state="copy_move", event="wrong",
                    context={"pose": pose["name"]},
                )
            self._say(fb)
            self._copy_reset_pose()
            time.sleep(0.5)
    
        # Final score
        print(f"[CopyMove] Final score: {score}/{total}")
        if score == total:
            score_event = "score_perfect"
            self.emotions.play_async(Emotion.WIN)
        elif score >= 2:
            score_event = "score_good"
            self.emotions.play_async(Emotion.HAPPY)
        elif score == 1:
            score_event = "score_ok"
            self.emotions.play_async(Emotion.ENCOURAGING)
        else:
            score_event = "score_poor"
            self.emotions.play_async(Emotion.SAD)
    
        result = self.dialogue.event(
            state="copy_move", event=score_event,
            context={"score": score, "total": total},
        )
        self._say(result)
        time.sleep(1)
        self._ask_rematch(GameType.COPY_MOVE)
    
    def _copy_reset_pose(self) -> None:
        """Return Misty to neutral between copy-move rounds."""
        self.misty.MoveArms(25, 25, 35, 35, None, None)
        self.misty.MoveHead(0, 0, 0, 60, None, None)
        time.sleep(0.8)
    
    
    # ------------------------------------------------------------------
    # Game 5: Emotion Guess
    # ------------------------------------------------------------------
    
    def _run_emotion_guess(self) -> None:
        print("[GameManager] Emotion Guess started")

        intro = self.dialogue.event(state="emotion_guess", event="intro")
        self._say(intro, reenable_stt=True)

        #  Wait on "ready" or left bumper; right bumper = skip
        ready = self._wait_for_input(
            float(10000), buttons={"left", "right"}, matcher=lambda t: self._match_ready(t) or self._match_stop(t)
        )
        if ready is None or (ready[0] == "button" and ready[1] == "right") or (ready[0] == "speech" and self._match_stop(ready[1])):
            self._finish_game("menu")
            return

        ready_line = self.dialogue.event(state="emotion_guess", event="ready")
        self._say(ready_line, reenable_stt=False)
        time.sleep(max(1.5, (len(ready_line.reply) / 14)+1))

        emotions = self.EMOTIONS.copy()
        random.shuffle(emotions)
        score = 0
        rounds = 3

        for emotion in emotions[:rounds]:
            other_emotions = [name for name in self.EMOTION_NAMES if name != emotion["name"]]
            candidate = emotion["name"] if random.random() < 0.5 else random.choice(other_emotions)
            print(f"[EmotionGuess] Candidate shown: {candidate}")

            round_begin = self.dialogue.event(
                state="emotion_guess", event="round_begin",
                context={"emotion": emotion["name"], "candidate": candidate},
            )
            round_begin.reply = f"Am I showing {candidate}? Press LEFT for yes or RIGHT for no."
            self._say(round_begin, reenable_stt=False)

            # Apply emotion pose AFTER _say() so it isn't overwritten by dialogue LED/image
            self.misty.DisplayImage(emotion["image"])
            self.misty.ChangeLED(*emotion["led"])
            self.misty.MoveArms(emotion["arms"][0], emotion["arms"][1], 45, 45, None, None)
            self.misty.MoveHead(emotion["head"][0], emotion["head"][1], emotion["head"][2], 50, None, None)
            time.sleep(max(1.5, (len(round_begin.reply) / 14)+1))
            self._stt.enable()

            response = self._wait_for_input(
                float(10000),
                buttons={"left", "right"},
                matcher=lambda t: (
                    any(name in t for name in self.EMOTION_NAMES)
                    or any(w in t for w in ("yes", "no", "left", "right"))
                ),
            )

            if response is None:
                kind, value = "button", "right"
            else:
                kind, value = response
            print(f"[EmotionGuess] User response: {value}")

            value_lower = value.strip().lower()
            if kind == "button":
                correct = (value == "left") == (candidate == emotion["name"])
            elif emotion["name"] in value_lower:
                correct = True
            elif candidate in value_lower:
                correct = candidate == emotion["name"]
            elif any(w in value_lower for w in ("yes", "left")):
                correct = candidate == emotion["name"]
            elif any(w in value_lower for w in ("no", "right")):
                correct = candidate != emotion["name"]
            else:
                correct = False
            print(f"[EmotionGuess] Correct={correct}")

            if correct:
                score += 1
                self.emotions.play_async(Emotion.EXCITED)
                fb = self.dialogue.event(
                    state="emotion_guess", event="correct",
                    context={"emotion": emotion["name"]},
                )
                fb.reply = fb.reply.replace("{emotion}", emotion["name"])
                print(f"[EmotionGuess] Score: {score}/{rounds}")
            else:
                self.emotions.play_async(Emotion.DISAPPOINTED)
                fb = self.dialogue.event(
                    state="emotion_guess", event="wrong",
                    context={"emotion": emotion["name"], "guess": value_lower},
                )
                fb.reply = fb.reply.replace("{emotion}", emotion["name"])
                print(f"[EmotionGuess] Final score: {score}/{rounds}")
            self._say(fb, reenable_stt=False)
            self._emotion_reset()
            time.sleep(max(1.5, (len(round_begin.reply) / 14)+1))

        score_event = {3: "score_3", 2: "score_2", 1: "score_1"}.get(score, "score_0")
        _score_emotion = {3: Emotion.WIN, 2: Emotion.HAPPY, 1: Emotion.ENCOURAGING, 0: Emotion.SAD}
        self.emotions.play_async(_score_emotion.get(score, Emotion.SAD))
        result = self.dialogue.event(
            state="emotion_guess", event=score_event,
            context={"score": score, "total": rounds},
        )
        self._say(result)
        time.sleep(1)
        self._ask_rematch(GameType.EMOTION_GUESS)

    def _emotion_reset(self) -> None:
        """Reset Misty to neutral face + pose between emotion rounds."""
        self.misty.DisplayImage("e_DefaultContent.jpg")
        self.misty.ChangeLED(255, 255, 255)
        self.misty.MoveArms(25, 25, 35, 35, None, None)
        self.misty.MoveHead(0, 0, 0, 60, None, None)
        time.sleep(0.8)

    # ------------------------------------------------------------------
    # Post-Game Global Orchestration
    # ------------------------------------------------------------------

    def _ask_rematch(self, game: GameType) -> None:
        prompt = self.dialogue.event(state="post_game", event="rematch_prompt")
        self._say(prompt, reenable_stt=True)
        time.sleep(max(1.5, (len(prompt.reply) / 14) + 1))

        response = self._wait_for_input(
            float(10000),
            buttons={"left", "right"},
            matcher=None,
        )
        if response is None:
            self._finish_game("menu")
            return

        kind, value = response
        intent = None

        if kind == "button":
            if value == "left":
                intent = "rematch_yes"
            else:
                intent = "menu"
        else:
            dialogue_resp = self.dialogue.respond(state="post_game", user_input=value)
            intent = dialogue_resp.intent

        if intent == "rematch_yes":
            again = self.dialogue.event("post_game", "rematch_yes")
            self._say(again)
            time.sleep(max(1.5, (len(again.reply) / 14) + 1))
            self.start_game(game)
            
        elif intent == "menu" or intent == "rematch_no":
            menu_resp = self.dialogue.event("post_game", "menu")
            self._say(menu_resp)
            time.sleep(max(1.5, (len(menu_resp.reply) / 14) + 1))
            self._finish_game("menu")
            
        elif intent == "goodbye":
            bye = self.dialogue.event("post_game", "goodbye")
            self._say(bye)
            time.sleep(max(1.5, (len(bye.reply) / 14) + 1))
            self._finish_game("idle")
            
        else:
            menu_resp = self.dialogue.event("post_game", "menu")
            self._say(menu_resp)
            time.sleep(max(1.5, (len(menu_resp.reply) / 14) + 1))
            self._finish_game("menu")

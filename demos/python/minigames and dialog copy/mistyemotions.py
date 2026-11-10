from __future__ import annotations

import time
import threading
from enum import Enum, auto

from mistyPy.Robot import Robot
from mistyidle import IdleManager


# Emotions

class Emotion(Enum):
    # Game outcomes
    WIN          = auto()   # Misty wins / player loses
    LOSE         = auto()   # Misty loses / player wins
    TIE          = auto()   # Draw / tie result

    # In-game reactions
    EXCITED      = auto()   # Anticipation / countdown hype
    THINKING     = auto()   # Processing / analysing
    SURPRISED    = auto()   # Unexpected input
    DISAPPOINTED = auto()   # After a wrong answer
    ENCOURAGING  = auto()   # Motivating the player mid-game
    TEASING      = auto()   # Playful provocation (staring contest)

    # Greeting / social
    GREETING     = auto()   # Wave hello
    HAPPY        = auto()   # General cheerful mood
    CURIOUS      = auto()   # Scanning / guessing

    # Edge cases
    CONFUSED     = auto()   # Didn't understand input
    SAD          = auto()   # General sadness
    ANGRY        = auto()   # Mild frustration (cheating, bad input)


_EMOTION_DATA: dict[Emotion, dict] = {


    Emotion.WIN: {
        "image":  "e_JoyGoofy3.jpg",
        "led":    (0, 255, 80),
        "head":   (-15, 0, 0, 100),          # look slightly up
        "arms":   (-85, -85, 70, 70),       # both arms fully raised
        "sound":  "s_Joy3.wav",
        "hold":   1.5,
    },

    Emotion.LOSE: {
        "image":  "e_Sadness.jpg",
        "led":    (30, 30, 160),
        "head":   (20, 0, 0, 100),           # head hangs forward/down
        "arms":   (60, 60, 25, 25),         # arms low and limp
        "sound":  "s_Sadness.wav",
        "hold":   2.0,
    },

    Emotion.TIE: {
        "image":  "e_ContentLeft.jpg",
        "led":    (180, 180, 50),           # warm yellow-ish
        "head":   (0, 10, 10, 100),          # slight tilt
        "arms":   (-20, 20, 40, 40),        
        "sound":  None,
        "hold":   1.2,
    },

    Emotion.EXCITED: {
        "image":  "e_Admiration.jpg",
        "led":    (255, 140, 0),
        "head":   (-10, 0, 0, 100),
        "arms":   (-65, -65, 70, 70),
        "sound":  "s_Amazement.wav",
        "hold":   1.0,
    },


    Emotion.THINKING: {
        "image":  "e_Contemplate.jpg",
        "led":    (60, 60, 200),            # soft blue
        "head":   (5, 15, -8, 100),          # tilt right & slight down
        "arms":   (0, 25, 30, 30),          # left arm mid, right resting
        "sound":  "s_PhraseHmm.wav",
        "hold":   1.5,
    },

 
    Emotion.SURPRISED: {
        "image":  "e_Surprise.jpg",
        "led":    (255, 100, 200),          # magenta-pink
        "head":   (-20, 0, 0, 100),          # snaps up quickly
        "arms":   (-40, -40, 80, 80),       # both arms out wide
        "sound":  "s_Amazement.wav",
        "hold":   1.0,
    },


    Emotion.DISAPPOINTED: {
        "image":  "e_Sadness.jpg",
        "led":    (100, 0, 160),
        "head":   (12, 0, 5, 100),
        "arms":   (45, 45, 25, 25),
        "sound":  "s_Disapproval.wav",
        "hold":   1.5,
    },


    Emotion.ENCOURAGING: {
        "image":  "e_Love.jpg",
        "led":    (180, 0, 255),            # violet
        "head":   (-5, 0, 0, 100),
        "arms":   (-30, -30, 40, 40),       # arms slightly raised
        "sound":  None,
        "hold":   1.0,
    },


    Emotion.TEASING: {
        "image":  "e_JoyGoofy.jpg",
        "led":    (255, 80, 0),             # orange
        "head":   (0, 8, -12, 100),          # slight right-tilt, yaw left
        "arms":   (10, 25, 35, 35),         # left arm a bit up
        "sound":  None,
        "hold":   1.0,
    },


    Emotion.GREETING: {
        "image":  "e_JoyGoofy3.jpg",
        "led":    (255, 200, 0),
        "head":   (-8, 0, -15, 100),         # look slightly up and to the left
        "arms":   (-65, 25, 60, 30),        # left arm waves, right rests
        "sound":  None,
        "hold":   0.8,
    },

    Emotion.HAPPY: {
        "image":  "e_JoyGoofy3.jpg",
        "led":    (0, 255, 80),
        "head":   (-8, 0, 0, 100),
        "arms":   (-55, -55, 50, 50),
        "sound":  None,
        "hold":   1.0,
    },

    Emotion.CURIOUS: {
        "image":  "e_Contemplate.jpg",
        "led":    (0, 180, 255),            # cyan
        "head":   (-5, 0, -12, 100),         # starting position of scan
        "arms":   (25, 25, 30, 30),
        "sound":  "s_PhraseHmm.wav",
        "hold":   0.8,
    },

    Emotion.CONFUSED: {
        "image":  "e_Confusion.jpg",
        "led":    (180, 0, 255),
        "head":   (0, 12, -10, 100),         # tilted, yaw off-centre
        "arms":   (25, 25, 30, 30),
        "sound":  "s_PhraseHmm.wav",
        "hold":   1.2,
    },

    Emotion.SAD: {
        "image":  "e_Sadness.jpg",
        "led":    (40, 40, 200),
        "head":   (18, 0, 0, 100),           # head hangs down noticeably
        "arms":   (55, 55, 20, 20),         # arms droop
        "sound":  "s_Sadness.wav",
        "hold":   1.8,
    },

    Emotion.ANGRY: {
        "image":  "e_Anger.jpg",
        "led":    (255, 30, 0),
        "head":   (-8, 0, 0, 100),           # head forward, slightly up (glare)
        "arms":   (-20, -20, 60, 60),       # arms raised, tense
        "sound":  "s_Disapproval.wav",
        "hold":   1.2,
    },
}


# MistyEmotions controller

class MistyEmotions:
    """
    High-level emotion/gesture controller for Misty.

    Pass the shared IdleManager so that reset() hands control back to
    the idle loop rather than freezing Misty in a static neutral pose.

    Example
    -------
    emotions = MistyEmotions(misty, idle)
    emotions.play(Emotion.WIN)           # blocking
    emotions.play_async(Emotion.LOSE)    # non-blocking (fires in background thread)
    emotions.reset()                     # restart idle loop as resting state
    """

    def __init__(self, misty: Robot, idle: IdleManager) -> None:
        self.misty = misty
        self.idle  = idle

    # Public API

    def play(self, emotion: Emotion, blocking: bool = True) -> None:
        """
        Execute the full gesture for *emotion*.
        If *blocking* is False the gesture runs in a daemon thread.
        """
        if not blocking:
            threading.Thread(
                target=self._execute, args=(emotion,), daemon=True
            ).start()
        else:
            self._execute(emotion)

    def play_async(self, emotion: Emotion) -> None:
        """Convenience shorthand for play(emotion, blocking=False)."""
        self.play(emotion, blocking=False)

    def reset(self) -> None:
        """Hand control back to the IdleManager as the default resting state."""
        self.idle.start()

    # Core execution

    def _execute(self, emotion: Emotion) -> None:
        data = _EMOTION_DATA.get(emotion)
        if data is None:
            print(f"[MistyEmotions] Unknown emotion: {emotion}")
            return

        m = self.misty

        # 1. Face & LED
        m.DisplayImage(data["image"])
        m.ChangeLED(*data["led"])

        # 2. Emotion-specific animation overrides
        if emotion == Emotion.WIN:
            self._anim_win(data)
        elif emotion == Emotion.EXCITED:
            self._anim_excited(data)
        elif emotion == Emotion.GREETING:
            self._anim_greeting(data)
        elif emotion == Emotion.CURIOUS:
            self._anim_curious(data)
        elif emotion == Emotion.ENCOURAGING:
            self._anim_encouraging(data)
        elif emotion == Emotion.SURPRISED:
            self._anim_surprised(data)
        else:
            # Default: move head + arms to target pose
            self._apply_pose(data)

        # 3. Optional sound
        if data.get("sound"):
            m.PlayAudio(data["sound"], 10)

        # 4. Hold the pose briefly
        if data["hold"] > 0:
            time.sleep(data["hold"])

    # Pose helpers

    def _apply_pose(self, data: dict) -> None:
        """Move head and arms to the pose defined in *data*."""
        m = self.misty
        pitch, roll, yaw, vel = data["head"]
        m.MoveHead(pitch, roll, yaw, vel, None, None)

        la, ra, lv, rv = data["arms"]
        m.MoveArms(la, ra, lv, rv, None, None)

    # Custom animations (overrides for specific emotions)
    def _anim_win(self, data: dict) -> None:
        """Victory: arms fly up with a little head bob."""
        m = self.misty
        la, ra, lv, rv = data["arms"]
        m.MoveArms(la, ra, lv, rv, None, None)

        # Head bobs up then settles
        pitch, roll, yaw, vel = data["head"]
        m.MoveHead(pitch - 5, roll, yaw, vel + 10, None, None)
        time.sleep(0.3)
        m.MoveHead(pitch, roll, yaw, vel, None, None)

    def _anim_excited(self, data: dict) -> None:
        """Excited: quick arm raise + small anticipation bounce."""
        m = self.misty
        la, ra, lv, rv = data["arms"]
        pitch, roll, yaw, vel = data["head"]

        # Small bob down then up before raising arms
        m.MoveHead(pitch + 8, roll, yaw, vel, None, None)
        time.sleep(0.15)
        m.MoveHead(pitch, roll, yaw, vel, None, None)
        m.MoveArms(la, ra, lv, rv, None, None)

    def _anim_greeting(self, data: dict) -> None:
        """Wave: left arm raises and oscillates three times."""
        m = self.misty
        pitch, roll, yaw, vel = data["head"]
        m.MoveHead(pitch, roll, yaw, vel, None, None)

        # Wave motion: left arm up, oscillate
        m.MoveArms(-70, 25, 65, 30, None, None)
        time.sleep(0.35)
        m.MoveArms(-45, 25, 65, 30, None, None)
        time.sleep(0.30)
        m.MoveArms(-70, 25, 65, 30, None, None)
        time.sleep(0.35)
        m.MoveArms(-45, 25, 65, 30, None, None)
        time.sleep(0.30)
        m.MoveArms(-70, 25, 65, 30, None, None)
        time.sleep(0.35)
        # Return to neutral arms
        m.MoveArms(29, 29, 35, 35, None, None)

    def _anim_curious(self, data: dict) -> None:
        """Scanning pan: slow left-right head sweep."""
        m = self.misty
        pitch, roll, yaw, vel = data["head"]
        la, ra, lv, rv = data["arms"]
        m.MoveArms(la, ra, lv, rv, None, None)

        m.MoveHead(pitch, roll, -18, 30, None, None)   # look left
        time.sleep(0.8)
        m.MoveHead(pitch, roll,  18, 30, None, None)   # look right
        time.sleep(0.9)
        m.MoveHead(pitch, roll,   0, 40, None, None)   # centre

    def _anim_encouraging(self, data: dict) -> None:
        """Gentle nod: two forward head bobs."""
        m = self.misty
        pitch, roll, yaw, vel = data["head"]
        la, ra, lv, rv = data["arms"]
        m.MoveArms(la, ra, lv, rv, None, None)

        for _ in range(2):
            m.MoveHead(pitch + 8, roll, yaw, vel, None, None)
            time.sleep(0.25)
            m.MoveHead(pitch, roll, yaw, vel, None, None)
            time.sleep(0.20)

    def _anim_surprised(self, data: dict) -> None:
        """Quick snap back then settle."""
        m = self.misty
        pitch, roll, yaw, vel = data["head"]
        la, ra, lv, rv = data["arms"]

        # Arms fly out first for drama
        m.MoveArms(la, ra, lv, rv, None, None)
        m.MoveHead(pitch, roll, yaw, vel, None, None)
        time.sleep(0.4)
        # Settle slightly
        m.MoveHead(pitch + 5, roll, yaw, vel - 20, None, None)



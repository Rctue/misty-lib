from __future__ import annotations

import random
import threading
import time

from mistyPy.Robot import Robot

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

IDLE_ACTION_DELAY_MIN = 2.0
IDLE_ACTION_DELAY_MAX = 5.0

IDLE_LED_COLOURS = [
    (255, 255, 255),   # white
    (255, 140,   0),   # orange
    ( 30, 100, 255),   # blue
    (  0, 220,  80),   # green
    (180,   0, 255),   # purple
    (255,  60,  60),   # red-ish
]


class IdleManager:
    def __init__(self, misty: Robot) -> None:
        self.misty             = misty
        self._stop_event       = threading.Event()
        self._thread: threading.Thread | None = None
        self._led_index        = 0

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stop_event.clear()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, name="idle-movement", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.misty.Stop(hold=True)
        self.misty.MoveHead(0, 0, 0, 70, None, None)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        actions = [
            (self._look_left,    2),
            (self._look_right,   2),
            (self._look_around,  2),
            (self._curious,      2),
            (self._nod,          2),
            (self._small_wave,   1),
            (self._stretch,      1),
            (self._spin,         1),
            (self._reset_pose,   2),
            (self._fidget,       3),
            (self._beep,         2),
            (self._dance,        1),
        ]
        population = [a for a, w in actions]
        weights    = [w for a, w in actions]

        while not self._stop_event.is_set():
            self._led_index = (self._led_index + 1) % len(IDLE_LED_COLOURS)
            self.misty.ChangeLED(*IDLE_LED_COLOURS[self._led_index])

            action = random.choices(population, weights=weights, k=1)[0]
            print(f"[IDLE] Actie: {action.__name__}")
            action()

            delay = random.uniform(IDLE_ACTION_DELAY_MIN, IDLE_ACTION_DELAY_MAX)
            self._stop_event.wait(delay)

    # ------------------------------------------------------------------
    # Face tracking
    # ------------------------------------------------------------------

    def face_track(self, bearing: float) -> None:
        yaw = max(-40, min(40, int(bearing * 1.5)))
        self.misty.MoveHead(0, 0, yaw, 60, None, None)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _look_left(self) -> None:
        yaw = random.randint(15, 25)
        self.misty.MoveHead(0, 0, -yaw, 80, None, None)

    def _look_right(self) -> None:
        yaw = random.randint(15, 25)
        self.misty.MoveHead(0, 0, yaw, 80, None, None)

    def _look_around(self) -> None:
        self.misty.MoveHead(0, 0, -20, 70, None, None)
        time.sleep(0.8)
        self.misty.MoveHead(0, 0, 0, 70, None, None)
        time.sleep(0.6)
        self.misty.MoveHead(0, 0, 20, 70, None, None)
        time.sleep(0.8)
        self.misty.MoveHead(0, 0, 0, 70, None, None)

    def _curious(self) -> None:
        self.misty.MoveHead(0, 8, random.choice([-12, 12]), 80, None, None)
        self.misty.MoveArms(random.choice([-30, 10]), 25, 30, 30, None, None)

    def _nod(self) -> None:
        self.misty.MoveHead(-8, 0, 0, 90, None, None)
        time.sleep(0.4)
        self.misty.MoveHead(5, 0, 0, 90, None, None)
        time.sleep(0.3)
        self.misty.MoveHead(0, 0, 0, 80, None, None)

    def _stretch(self) -> None:
        def move():
            self.misty.MoveHead(-10, 0, 0, 70, None, None)
            self.misty.MoveArms(-60, -60, 25, 25, None, None)
            time.sleep(1.2)
            self.misty.MoveHead(0, 0, 0, 70, None, None)
            self.misty.MoveArms(25, 25, 25, 25, None, None)
        threading.Thread(target=move, daemon=True).start()

    def _small_wave(self) -> None:
        self.misty.MoveHead(0, 0, -10, 80, None, None)
        self.misty.MoveArms(-60, 25, 40, 30, None, None)
        time.sleep(0.5)
        self.misty.MoveArms(-30, 25, 40, 30, None, None)
        time.sleep(0.4)
        self.misty.MoveArms(-60, 25, 40, 30, None, None)
        time.sleep(0.5)
        self.misty.MoveArms(25, 25, 35, 35, None, None)
        self.misty.MoveHead(0, 0, 0, 80, None, None)

    def _spin(self) -> None:
        self.misty.DriveTime(0, 35, 1200, 0)

    def _reset_pose(self) -> None:
        self.misty.MoveHead(0, 0, 0, 70, None, None)
        self.misty.MoveArms(25, 25, 30, 30, None, None)

    def _fidget(self) -> None:
        choice = random.randint(0, 2)
        if choice == 0:
            self.misty.MoveHead(0, 6, random.randint(-15, 15), 90, None, None)
            time.sleep(0.8)
            self.misty.MoveHead(0, 0, 0, 90, None, None)
        elif choice == 1:
            self.misty.MoveArms(-10, 35, 50, 50, None, None)
            time.sleep(0.4)
            self.misty.MoveArms(25, 25, 50, 50, None, None)
        else:
            self.misty.DriveTime(0, 18, 700, 0)

    def _beep(self) -> None:
        self.misty.PlayAudio("s_SystemSuccess.wav", 20)

    def _dance(self) -> None:
        def dance():
            self.misty.ChangeLED(255, 0, 255)
            self.misty.MoveHead(0, 0, -18, 90, None, None)
            self.misty.MoveArms(-50, 10, 60, 60, None, None)
            self.misty.DriveTime(0, 30, 400, 0)
            time.sleep(0.5)
            self.misty.MoveHead(0, 0, 18, 90, None, None)
            self.misty.MoveArms(10, -50, 60, 60, None, None)
            self.misty.DriveTime(0, -30, 400, 0)
            time.sleep(0.5)
            self.misty.MoveHead(-10, 0, 0, 90, None, None)
            time.sleep(0.3)
            self.misty.MoveHead(8, 0, 0, 90, None, None)
            time.sleep(0.3)
            self.misty.MoveHead(0, 0, 0, 80, None, None)
            self.misty.MoveArms(25, 25, 50, 50, None, None)
        threading.Thread(target=dance, daemon=True).start()
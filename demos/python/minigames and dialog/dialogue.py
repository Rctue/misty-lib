# dialogue.py
# Dialogue manager for Misty robot — TU/e Open Day
# LLM-driven with full offline fallback. Every response includes an intent,
# a reply, and a tone that the controller uses to set Misty's LED + expression.

from __future__ import annotations

import json
import os
import random
import threading
from dataclasses import dataclass

from dotenv import load_dotenv
load_dotenv()

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None          # type: ignore
    genai_types = None    # type: ignore

# Config
# ---------------------------------------------------------------------------

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
USE_LLM      = False  # Toggle LLM on/off — set to False to use fallbacks only

# ---------------------------------------------------------------------------
# Tone → Misty LED + expression mappings
# ---------------------------------------------------------------------------

TONE_LED: dict[str, tuple[int, int, int]] = {
    "playful":     (255, 140,   0),
    "calm":        ( 30, 100, 255),
    "excited":     (  0, 255,  80),
    "encouraging": (180,   0, 255),
    "sad":         ( 50,  50, 200),
    "neutral":     (255, 255, 255),
}

TONE_IMAGE: dict[str, str] = {
    "playful":     "e_JoyGoofy3.jpg",
    "calm":        "e_DefaultContent.jpg",
    "excited":     "e_Admiration.jpg",
    "encouraging": "e_Love.jpg",
    "sad":         "e_Sadness.jpg",
    "neutral":     "e_DefaultContent.jpg",
}

VALID_TONES = set(TONE_LED.keys())


@dataclass
class DialogueResponse:
    intent: str
    reply:  str
    tone:   str

    @property
    def led(self) -> tuple[int, int, int]:
        return TONE_LED.get(self.tone, TONE_LED["neutral"])

    @property
    def image(self) -> str:
        return TONE_IMAGE.get(self.tone, TONE_IMAGE["neutral"])


# ---------------------------------------------------------------------------
# Fallback scripts
# ---------------------------------------------------------------------------

FALLBACKS: dict[tuple[str, str], list[tuple[str, str]]] = {
    # Idle & greeting
    ("idle", "invite"): [
        ("Hey! Want to play a quick game with me?", "playful"),
        ("Hi there! I'm a little bored — want to join me?", "playful"),
        ("Hello! I've got a fun mini-game. Care to try?", "excited"),
        ("Pst! Yes, you there! Do you have a moment to play a game?", "playful"),
        ("Hey you! Looking for some entertainment? Let's play a game!", "excited"),
    ],
    # Greeting consent
    ("greeting_consent", "intro"): [
        ("Hello there, I am Misty. I have been waiting for someone to walk past. Do you mind if I take a quick look at you? Press the left bumper to continue!", "playful"),
        ("Hi! I'm Misty. I love meeting new people. Can I scan you real quick to see who you are? Press the left bumper to continue!", "excited"),
        ("Welcome! Misty here. Mind if I take a quick look and try to guess something about you? Press the left bumper to continue!", "playful"),
        ("Hi there, my name is Misty! I'd love to say hi and scan your look for a second. Press the left bumper to continue!", "excited"),
        ("Hello stranger! I am Misty. Can I use my cameras to analyze your tech vibe real quick? Press the left bumper to continue!", "playful"),
    ],
    ("greeting_consent", "yes"): [
        ("Interesting, I am picking up some clues. Give me just a second", "calm"),
        ("Awesome! Let's see what we have here... Just a moment.", "excited"),
        ("Scanning commenced. Let me analyze these parameters real quick.", "calm"),
        ("Perfect! Connecting to sensors now... let's see what you've got.", "excited"),
        ("Great choice! Scanning in progress, hang tight for a brief moment.", "calm"),
    ],
    ("greeting_consent", "no"): [
        ("No problem at all, enjoy the open day!", "calm"),
        ("That's totally fine. Have a great time at the open day!", "calm"),
        ("No worries! Enjoy looking around today.", "calm"),
        ("Understandable! I hope you have an amazing open day here.", "calm"),
        ("All good! Feel free to walk around and explore the open day.", "calm"),
    ],
    ("greeting_consent", "unknown"): [
        ("I did not quite catch that. You can say yes, sure, no, or stop.", "calm"),
        ("Sorry, my sensors missed that. Did you mean yes, no, or stop?", "calm"),
        ("Hmm, I couldn't hear you clearly. Could you answer with yes, no, or stop?", "calm"),
        ("My microphones are a bit confused! Please answer with yes, no, or stop.", "calm"),
        ("Oops, that sound didn't register right. Did you want to say yes, no, or stop?", "calm"),
    ],
    # Engineer confirm
    ("engineer_confirm", "guess"): [
        ("Based on what I see, I would guess you are probably a future engineer. Am I close?", "playful"),
        ("My algorithms say you look like a future engineer! Am I right?", "excited"),
        ("Let me guess... I see the spark of a future engineer in you. Am I warm?", "playful"),
        ("According to my data patterns, you look exactly like a future engineer. Is that accurate?", "excited"),
        ("My robotic intuition tells me you are destined to be an engineer. Did I get it right?", "playful"),
    ],
    ("engineer_confirm", "yes"): [
        ("I knew it. I have been practicing a lot", "excited"),
        ("Bullseye! My neural network is getting really good at this.", "excited"),
        ("Awesome! Score one for the robot. I knew it!", "excited"),
        ("Ha, nailed it! My visual recognition software is working perfectly today.", "excited"),
        ("Fantastic! I guess my human-spotting skills are top tier.", "excited"),
    ],
    ("engineer_confirm", "no"): [
        ("Good to know! I need more training. I will log this as a miss.", "sad"),
        ("Ah, close but no cigar. Time to recalibrate my sensors!", "sad"),
        ("Oh, my bad! I guess I still have a lot to learn.", "sad"),
        ("Darn it, my data must be skewed. I'll adjust my filters for next time.", "sad"),
        ("Ah, a mismatch! Looks like my prediction model needs a minor update.", "sad"),
    ],
    ("engineer_confirm", "unknown"): [
        ("I don't quite understand you, could you tell me again if I was close with yes, or if I was not close with no", "calm"),
        ("Sorry, I missed your answer. Was that a yes or a no to my guess?", "calm"),
        ("Could you say that one more time? Just tell me 'yes' if I'm right or 'no' if I'm wrong.", "calm"),
        ("I'm having trouble decoding that response. Did you mean yes, I'm right, or no, I'm wrong?", "calm"),
        ("Let's try that again. Just confirm with a simple yes or a no for me please.", "calm"),
    ],
    # Game menu
    ("game_menu", "intro"): [
        ("So, would you like to play a game with me? I have a few options. There is a staring contest, a copy of my moves game, a reaction speed test, an emotion guessing game, and a sorting challenge. Just say the name of the game you want or press my LEFT button to play a random game!", "playful"),
        ("Ready for some fun? I can offer you a staring contest, copy my moves, a reaction speed test, an emotion guessing game, or a sorting challenge! What will it be? Or press LEFT to play a random game.", "excited"),
        ("Let's play something! Choose between the staring contest, copy my moves, reaction speed test, emotion guessing, or the sorting challenge. Say the name of your choice, or press LEFT to play a random game!", "playful"),
        ("Let's challenge each other! I have a staring contest, copy my moves, reaction speed, emotion guess, or a sorting game. Name your favorite or press LEFT for a random selection!", "excited"),
        ("I'm packed with mini-games! Pick from staring contest, copy my moves, reaction speed, emotion guessing, or sorting challenge. Say the game name or hit LEFT for a surprise game!", "playful"),
    ],
    ("game_menu", "left_pressed"): [
        ("Okay! I will give you a quick description of each. Say stop when you hear one you like.", "calm"),
        ("Sure thing! I'll list the games with a short explanation. Just say stop when you hear the perfect one.", "calm"),
        ("No problem! Let me run through the options for you. Tell me to stop when you've made up your mind.", "calm"),
        ("Got it! I am going to explain the games one by one. Say stop when a game catches your interest.", "calm"),
        ("On it! Let me briefly break down each choice. Just interrupt me and say stop when you hear a good one.", "calm"),
    ],
    ("game_menu", "descriptions"): [
        ("In the staring contest, you and I stare at each other, first to look away loses. Copy my moves in that I do a pose, and you copy it. Reaction speed I flash my eyes, you press a button as fast as you can. Emotion guess I show you an emotion, and you try to name it. Sorting game I name items and you sort them left or right. Which one sounds good?", "playful"),
        ("Here we go: Staring contest is all about blinking first. Copy my moves means you mimic my poses. Reaction speed tests how fast you press a button when my eyes flash. Emotion guess is decoding my face, and the sorting game is categorizing objects. Any favorites?", "playful"),
        ("Alright: Staring contest - don't look away! Copy my moves - do what I do. Reaction speed - hit the button when my eyes flash. Emotion guess - read my facial expressions. Sorting game - split items left and right. Which one do you want to try?", "playful"),
        ("Check it out: Staring contest tests your eye focus. Copy my moves is all about mimicking my posture. Reaction speed checks your reflex time when my eyes flash. Emotion guess is reading my digital feelings, and sorting game splits items. Which one is it going to be?", "playful"),
        ("Summary incoming: Staring contest is an eye-lock battle. Copy my moves requires mimicking me. Reaction speed is a fast button-tap test. Emotion guess lets you decode my facial expressions, and sorting game is a category puzzle. What do you choose?", "playful"),
    ],
    ("game_menu", "stop"): [
        ("Okay! Want to play that one? Just say yes or press LEFT.", "playful"),
        ("Got it! Is this the game you want to do? Say yes or hit LEFT to start.", "playful"),
        ("Stop it is! Shall we launch this game? Just reply with yes or press LEFT.", "excited"),
        ("Right there! Is this the match you are looking for? Say yes or tap LEFT.", "playful"),
        ("Aha, you like this one! Ready to jump in? Say yes or click LEFT.", "excited"),
    ],
    ("game_menu", "no"): [
        ("No problem! I will be here if you change your mind. Enjoy the open day!", "calm"),
        ("All good! If you want to play later, you know where to find me. Have fun today!", "calm"),
        ("No strings attached! Enjoy the rest of your open day visit!", "calm"),
        ("No worries at all. Feel free to come back whenever you want. Have a great day!", "calm"),
        ("Totally fine, no pressure! Enjoy checking out the rest of the campus today.", "calm"),
    ],
    ("game_menu", "repeat"): [
        ("Your options are: staring contest, copy my moves, reaction speed, emotion guess, or sorting challenge.", "calm"),
        ("To remind you, we have: staring contest, copy my moves, reaction speed, emotion guess, and sorting challenge.", "calm"),
        ("Once more, the games are: staring contest, copy my moves, reaction speed, emotion guess, or the sorting challenge.", "calm"),
        ("Here they are again: staring contest, copy my moves, reaction speed test, emotion guessing, or sorting challenge.", "calm"),
        ("Just to refresh your memory, you can choose: staring contest, copy my moves, reaction speed, emotion guess, or sorting challenge.", "calm"),
    ],
    ("game_menu", "auto_pick"): [
        ("Do you want duly play a game with me? I have a few options, but let me pick a random game for us today, let us play {game}! Press the left bumper to play!", "excited"),
        ("Do you want to play a game with me? There is no time to choose, I am picking for us. We are playing {game}! Press the left bumper to play!", "playful"),
        ("Can't decide? No worries, I'll take the lead! Let's play {game}. Hit the left bumper to begin!", "excited"),
        ("Let's skip the choosing part and dive straight into the fun. I picked {game} for us! Press the left bumper!", "playful"),
        ("Random choice incoming! My randomizer selected {game} for us today. Tap the left bumper to kick it off!", "excited"),
    ],
    ("game_menu", "unknown"): [
        ("I did not quite catch that. Just say the name of a game, or press LEFT to play a random game", "calm"),
        ("Hmm, that wasn't on my list. Say a game name or press LEFT to play random.", "calm"),
        ("I'm not sure what you mean. Try saying the name of a game, or press LEFT for a random game.", "calm"),
        ("That didn't register as a game mode. State a game name clearly or hit LEFT for a random choice.", "calm"),
        ("Sorry, my processor missed that game title. Speak a game name or press LEFT to randomize.", "calm"),
    ],
    # Copy move game
    ("copy_move", "intro"): [
        ("This game is called copy my moves. I will show a pose, and you copy it. Press LEFT when you copied it, or RIGHT to skip. Ready?", "playful"),
        ("Welcome to copy my moves! Try to mirror the pose I make. Hit LEFT when you are done, or RIGHT to skip. Let's see it!", "excited"),
        ("Time for copy my moves. I'll strike a pose, and you match it. Press LEFT when you've copied me, or RIGHT to skip.", "playful"),
        ("Let's do copy my moves! Can you replicate my body language? Tap LEFT once you have the pose, or RIGHT to skip.", "excited"),
        ("In copy my moves, you just have to mimic my stance. Press LEFT when you are mirroring me, or RIGHT to skip ahead.", "playful"),
    ],
    ("copy_move", "ready"): [
        ("Watch carefully. I am about to show the pose.", "neutral"),
        ("Eyes on me! Here comes the position.", "neutral"),
        ("Get ready to observe. Preparing the pose now.", "neutral"),
        ("Look closely at my layout. Here it is!", "neutral"),
        ("Pay attention to my arms and posture. Ready, set, look!", "neutral"),
    ],
    ("copy_move", "no_movement_5s"): [
        ("Now copy it. Press LEFT when you copied it, or RIGHT to skip.", "calm"),
        ("Go ahead and replicate the pose. Hit LEFT when ready, or RIGHT to pass.", "calm"),
        ("Your turn to strike the pose! Click LEFT when done, or RIGHT to skip.", "calm"),
        ("Show me what you've got! Press LEFT once you're mirroring me, or RIGHT to skip this one.", "calm"),
        ("Don't be shy, try the pose! Press LEFT when you have it down, or RIGHT to skip.", "calm"),
    ],
    ("copy_move", "again"): [
        ("Sure. There, this was the same move, you can try again", "calm"),
        ("No problem, repeating the pose for you now. Give it another shot!", "calm"),
        ("Alright, holding the exact same stance. Try matching it again.", "calm"),
        ("Sure thing, check it out one more time and try to adjust your pose.", "calm"),
        ("Got it, re-displaying the position. Take your time to try again.", "calm"),
    ],
    ("copy_move", "correct"): [
        ("Yes, thats it, very impressive", "excited"),
        ("Spot on! You matched my form perfectly.", "excited"),
        ("Awesome! That is an exact replica of my pose.", "excited"),
        ("Wow, perfect mirroring! You've got great spatial awareness.", "excited"),
        ("Excellent job! You look just like a robot clone of me.", "excited"),
    ],
    ("copy_move", "partially_correct"): [
        ("Almost, but you raised your left arm I raised my right", "playful"),
        ("So close! Check your sides though, you flipped left and right.", "playful"),
        ("You almost had it, but your arms are opposite to mine!", "playful"),
        ("Good attempt, but it seems you inverted the left and right positions.", "playful"),
        ("Very close! Just a minor mix-up with the left and right side.", "playful"),
    ],
    ("copy_move", "wrong"): [
        ("I am not sure what you did, but it was definitely not my pose", "sad"),
        ("Hmm, that doesn't look quite right. Better luck on the next pose!", "sad"),
        ("My sensors aren't recognizing that stance as a match. Unlucky!", "sad"),
        ("Ah, that wasn't really close to my position, but I appreciate the effort.", "sad"),
        ("Oops, looks like you struck a completely different pose there.", "sad"),
    ],
    # Reaction test
    ("reaction", "reaction_explain"): [
        ("I am going to flash my eyes and you press any button as FAST as you can. But careful if you press too early, it does not count. Press the left bumper to start!", "playful"),
        ("Get ready for the reaction test! Hit any button the instant my eyes flash. Don't jump the gun or it won't count! Press the left bumper!", "excited"),
        ("Let's test your reflexes. When my eyes flash, click any button immediately. Early presses will penalize you. Tap left bumper to start!", "playful"),
        ("Speed test time! Wait for my eye flash, then smash any button as fast as possible. No false starts! Press the left bumper to begin.", "excited"),
        ("How fast are your synapses? Press a button as soon as you see my eyes flash, but don't guess early! Press the left bumper!", "playful"),
    ],
    ("reaction", "reaction_ready_ack"): [
        ("Okay, get ready", "excited"),
        ("Focus now, here it comes...", "excited"),
        ("Steady... focus on my eyes.", "excited"),
        ("Alright, prepare your fingers.", "excited"),
        ("Ready... don't blink!", "excited"),
    ],
    ("reaction", "reaction_go"): [
        ("NOW!", "excited"),
        ("GO GO GO!", "excited"),
        ("HIT IT!", "excited"),
        ("FLASH!", "excited"),
        ("PRESS!", "excited"),
    ],
    ("reaction", "reaction_result"): [
        ("Nice try! That was pretty quick.", "encouraging"),
        ("Wow, look at those reflexes! Not bad at all.", "encouraging"),
        ("Impressive response time! You've got fast fingers.", "encouraging"),
        ("Done! That was a solid reaction score right there.", "encouraging"),
        ("Super speedy! You reacted real fast to that signal.", "encouraging"),
    ],
    ("reaction", "reaction_early"): [
        ("HEY! Too early. You jumped before the signal. Humans get impatient very quickly. Let us try again.", "playful"),
        ("Ah, a false start! You pressed it before my eyes flashed. Patience, human! Let's give it another go.", "playful"),
        ("Whoops, trickster! You can't predict the flash, you have to react to it. Let's try that round again.", "playful"),
        ("Too fast! You triggered the button before the cue. Take a deep breath and let's try one more time.", "playful"),
        ("Hold your horses! You pressed way too early. Wait for the actual flash, okay? Let's retry.", "playful"),
    ],
    # Emotion Guess Game
    ("emotion_guess", "intro"): [
        ("I have a challenge for you. Do you think you can understand robot emotions? I will show you a feeling using my eyes, sounds, and posture, and you try to guess what emotion I am showing. Press the left button to start!", "playful"),
        ("Let's see if you have empathy for machines! I'm going to express an emotion via my face and body, and you have to guess it. Tap the left button to start!", "excited"),
        ("Can you read a robot's mind? I will display an emotional state with my eyes, posture, and sounds. Guess what it is! Press the left button to launch.", "playful"),
        ("Time for the emotion guessing game. I'll mimic a human feeling using my digital expressions. Do you think you can spot it? Hit the left button!", "excited"),
        ("Do you speak robot feelings? Let's find out! I'll display an emotion, and you try to identify it. Press the left button to begin!", "playful"),
    ],
    ("emotion_guess", "ready"): [
        ("Excellent. Humans are supposed to be very good at reading emotions. Let us test that theory.", "excited"),
        ("Great! Let's see if emotional intelligence applies to artificial beings too.", "excited"),
        ("Perfect. Prepare your psychological skills, let's see how well you decode me.", "excited"),
        ("Awesome! Time to put your empathy metrics to the ultimate test.", "excited"),
        ("Wonderful. Let's find out if my artificial expressions make sense to a human.", "excited"),
    ],
    ("emotion_guess", "round_begin"): [
        ("Okay…so watch carefully. What emotion am I showing right now?", "neutral"),
        ("Take a good look at my posture and eyes. What am I feeling?", "neutral"),
        ("Analyzing time! Look at my expressions... what emotion is this?", "neutral"),
        ("Here we go. Look closely at my digital face. Can you guess this feeling?", "neutral"),
        ("Observe me carefully right now. What emotional state does this represent?", "neutral"),
    ],
    ("emotion_guess", "correct"): [
        ("YES! Exactly right. I was feeling {emotion}. You are really good at this.", "excited"),
        ("Spot on! I was indeed portraying {emotion}. Wow, you read me like an open book!", "excited"),
        ("Correct! {emotion} is exactly what I was going for. Amazing deduction!", "excited"),
        ("Bingo! That's {emotion}. You have an incredible eye for robot emotions.", "excited"),
        ("Wow, you got it! I am currently showing {emotion}. Spectacular job!", "excited"),
    ],
    ("emotion_guess", "wrong"): [
        ("Ooooh, close guess. I was actually trying to show {emotion}. Robots still have a lot to learn about emotional expressions.", "sad"),
        ("Ah, not quite! I was attempting to express {emotion}. Maybe my digital face needs tuning.", "sad"),
        ("Good try, but that's a miss. The correct feeling was {emotion}. I'll try to be clearer next time.", "sad"),
        ("Incorrect, unfortunately! That was supposed to be {emotion}. Reading robots is tricky business.", "sad"),
        ("Oh, that's not it. I was actually going for {emotion}. Let's see how the next one goes.", "sad"),
    ],
    ("emotion_guess", "unknown"): [
        ("I did not quite understand that. Could you tell me again if I was correct or not?", "calm"),
        ("My filters couldn't process that response. Can you tell me again if I got the emotion right?", "calm"),
        ("Sorry, what was that? Please state clearly if my guess was correct or wrong.", "calm"),
        ("I missed that input. Could you re-verify if I guessed your emotion correctly?", "calm"),
        ("Hmm, that answer flew right over my antenna. Please say again if I got it right or wrong.", "calm"),
    ],
    ("emotion_guess", "score_3"): [
        ("THREE out of THREE! That is amazing. You might actually understand robots better than humans do.", "excited"),
        ("Perfect score, 3 out of 3! You are a certified robot whisperer. Incredible!", "excited"),
        ("Wow, 3 out of 3 correct! Your emotional intelligence software must be fully updated.", "excited"),
        ("Three points! An absolute flawless run. You understand my feelings perfectly!", "excited"),
        ("Incredible, a perfect 3 out of 3! You might be part robot yourself with those reading skills.", "excited"),
    ],
    ("emotion_guess", "score_2"): [
        ("Great job! You got most of them correct.", "encouraging"),
        ("Two out of three! That's a solid passing grade for robot empathy.", "encouraging"),
        ("Not bad at all! You managed to decode most of my emotions.", "encouraging"),
        ("Two correct guesses! You're definitely in sync with my programming.", "encouraging"),
        ("Nice work! Getting two right means you understand me pretty well.", "encouraging"),
    ],
    ("emotion_guess", "score_1"): [
        ("One correct. My emotions must be harder to read than I thought.", "sad"),
        ("Just one right. Looks like we both need a bit more practice on this.", "sad"),
        ("One out of three. My digital facial expressions might need an overhaul.", "sad"),
        ("Only one correct guess. Robot body language can be quite confusing, huh?", "sad"),
        ("You got one point. Well, at least you didn't walk away completely empty-handed!", "sad"),
    ],
    ("emotion_guess", "score_0"): [
        ("Zero points… wow. I may need emotional software updates.", "sad"),
        ("Oh dear, zero correct! We are completely on different wavelengths today.", "sad"),
        ("No points this time. Perhaps my acting skills are just terrible.", "sad"),
        ("Zero out of three! Don't worry, reading metal faces is an acquired skill.", "sad"),
        ("A score of zero! Looks like my emotions remain a total mystery to you.", "sad"),
    ],
    # Sorting game
    ("sorting", "intro"): [
        ("Time for a sorting challenge! LEFT is for {category_a}, RIGHT is for {category_b}. Ready?", "playful"),
        ("Let's play the sorting game! Categorize using LEFT for {category_a} and RIGHT for {category_b}. Ready?", "playful"),
        ("Ready to sort? Send {category_a} to the LEFT and {category_b} to the RIGHT. Let's do this!", "excited"),
        ("Speed sorting time! Your keys are LEFT for {category_a} and RIGHT for {category_b}. Are you set?", "playful"),
        ("Get your hands ready: LEFT stands for {category_a}, RIGHT stands for {category_b}. Ready to roll?", "excited"),
    ],
    ("sorting", "confirm"): [
        ("Alright! LEFT for {category_a}, RIGHT for {category_b}. Let us start!", "calm"),
        ("Got it! Remembering the rules: LEFT is {category_a}, RIGHT is {category_b}. Here we go!", "calm"),
        ("Understood! Keeping it simple: LEFT for {category_a} and RIGHT for {category_b}. Game on!", "calm"),
        ("Perfect! Sorting criteria locked in: LEFT equals {category_a}, RIGHT equals {category_b}. Starting!", "calm"),
        ("Confirmed! Prepare yourself for LEFT: {category_a} and RIGHT: {category_b}. Launching round!", "calm"),
    ],
    ("sorting", "ready"): [
        ("Great! LEFT for {category_a}, RIGHT for {category_b}. Sort as fast as you can.", "calm"),
        ("Awesome! Remember: LEFT is {category_a}, RIGHT is {category_b}. Speed is key!", "calm"),
        ("Excellent! Keep the rule in mind: {category_a} to the LEFT, {category_b} to the RIGHT. Go!", "calm"),
        ("Fantastic! Prepare your reflexes: LEFT for {category_a}, RIGHT for {category_b}. Let's sort!", "calm"),
        ("Superb! Just a reminder: LEFT side {category_a}, RIGHT side {category_b}. Quick now!", "calm"),
    ],
    ("sorting", "repeat"): [
        ("Sure! LEFT for {category_a}, RIGHT for {category_b}. That is still the rule.", "calm"),
        ("No problem! The rules haven't changed: LEFT means {category_a}, RIGHT means {category_b}.", "calm"),
        ("To repeat: push LEFT for {category_a} and RIGHT for {category_b}. Keep going!", "calm"),
        ("Here it is again: {category_a} goes LEFT, {category_b} goes RIGHT. Got it?", "calm"),
        ("Just a reminder: category {category_a} is LEFT, category {category_b} is RIGHT.", "calm"),
    ],
    ("sorting", "sorting_item"): [
        ("{item} — {category_a} or {category_b}?", "neutral"),
        ("Where does {item} go? {category_a} or {category_b}?", "neutral"),
        ("Next up: {item}. Is it {category_a} or {category_b}?", "neutral"),
        ("Sort this: {item}. Choose {category_a} or {category_b}!", "neutral"),
        ("What about {item}? Does it belong to {category_a} or {category_b}?", "neutral"),
    ],
    ("sorting", "sorting_correct"): [
        ("Correct! {item} belongs with {category}. Nice sorting.", "excited"),
        ("Yes! {item} is a {category}. Well done.", "excited"),
        ("Bullseye! {item} goes right into {category}. Good job!", "excited"),
        ("Perfect! {item} definitely matches {category}.", "excited"),
        ("That's right! {item} belongs to the {category} group.", "excited"),
    ],
    ("sorting", "sorting_wrong"): [
        ("Not quite! {item} actually belongs with {category}. But do not worry.", "sad"),
        ("Oops — {item} is a {category}. Easy mistake!", "sad"),
        ("Ah, close but wrong! {item} should go to {category}.", "sad"),
        ("Incorrect placement! {item} is categorized under {category}.", "sad"),
        ("Missed that one! {item} actually falls under {category}.", "sad"),
    ],
    ("sorting", "sorting_skip"): [
        ("No problem! Maybe another game next time.", "calm"),
        ("Skipping this game! Let's find something else for you to enjoy.", "calm"),
        ("Alright, calling it quits on sorting. Let's move on!", "calm"),
        ("No worries, sorting isn't for everyone. Let's check out other options.", "calm"),
        ("Understood, skipping the rest of this challenge. Back we go!", "calm"),
    ],
    ("sorting", "sorting_harder"): [
        ("Wow, you are too good at this! Let me make it harder.", "playful"),
        ("Ha! You're sailing through this. Let's turn up the difficulty!", "playful"),
        ("Incredible pace! Let's see how you handle a faster speed.", "playful"),
        ("You're a sorting natural! Time to crank up the challenge level.", "playful"),
        ("Too easy for you, huh? Let's make the items a bit trickier!", "playful"),
    ],
    ("sorting", "sorting_perfect"): [
        ("WOW! Perfect score! You sorted every item correctly. I officially declare you a professional sorter.", "excited"),
        ("Flawless victory! 100% correct sorting. You should put this on your resume!", "excited"),
        ("Unbelievable! Not a single sorting mistake. You've mastered this challenge completely!", "excited"),
        ("Absolute perfection! You categorized everything flawlessly. Robot efficiency achieved!", "excited"),
        ("Incredible! You sorted every single object without making an error. Top tier work!", "excited"),
    ],
    ("sorting", "sorting_good"): [
        ("Great work! Only a couple of mistakes. Pretty impressive.", "encouraging"),
        ("High score! You sorted almost everything correctly. Solid skills!", "encouraging"),
        ("Very nicely done! Just a few slip-ups, but overall a great run.", "encouraging"),
        ("Good job! Your sorting accuracy is definitely above average.", "encouraging"),
        ("Well sorted! You got nearly all of them in the right place.", "encouraging"),
    ],
    ("sorting", "sorting_ok"): [
        ("Not bad! A few slipped through. Want to try again?", "encouraging"),
        ("Decent run! You got a fair amount right, but missed some. Another go?", "encouraging"),
        ("An okay score! You're getting the hang of it, want to try to beat it?", "encouraging"),
        ("Fairly good, though some items ended up in the wrong bucket. Retry?", "encouraging"),
        ("A reasonable attempt! With a bit more focus, you'll nail it next time.", "encouraging"),
    ],
    ("sorting", "sorting_poor"): [
        ("Sorting can be surprisingly difficult. Want another go?", "sad"),
        ("Oof, tough round! The items got the best of you. Want to practice again?", "sad"),
        ("That was a tricky mix of objects. Don't worry, want another try?", "sad"),
        ("Looks like a few too many items ended up on the wrong side. Let's retry!", "sad"),
        ("A bit chaotic this round! Sorting under pressure is hard. Want a rematch?", "sad"),
    ],
    ("sorting", "unknown"): [
        ("Interesting answer… but for this game I only need LEFT or RIGHT.", "calm"),
        ("I didn't quite process that. Please stick to LEFT or RIGHT inputs.", "calm"),
        ("Whoops, that's not a valid direction! Just say or press LEFT or RIGHT.", "calm"),
        ("My system can only accept LEFT or RIGHT as sorting commands here.", "calm"),
        ("I'm confused by that response. Remember, your only options are LEFT or RIGHT.", "calm"),
    ],
    ("sorting", "ask_rule"): [
        ("The rule is still LEFT for {category_a} and RIGHT for {category_b}. You still have items left.", "calm"),
        ("Just a reminder: {category_a} goes LEFT, {category_b} goes RIGHT. Let's finish the pile!", "calm"),
        ("Don't forget the pattern: LEFT is {category_a}, RIGHT is {category_b}. Keep going!", "calm"),
        ("Keep your focus: LEFT for {category_a}, RIGHT for {category_b}. The game is still active.", "calm"),
        ("The active rule is: LEFT side gets {category_a}, RIGHT side gets {category_b}. More items waiting!", "calm"),
    ],
    ("sorting", "rematch_prompt"): [
        ("Press LEFT to play again or RIGHT to choose another game.", "calm"),
        ("Want another round of sorting? Press LEFT to retry, or RIGHT for the menu.", "calm"),
        ("Ready for a rematch? Hit LEFT to start sorting again, or RIGHT to switch games.", "calm"),
        ("Can you beat your score? Tap LEFT to replay this game, or RIGHT to back out.", "calm"),
        ("Should we go again? Press LEFT to re-enter the sorting game, or RIGHT to quit.", "calm"),
    ],
    ("sorting", "goodbye"): [
        ("Looks like you are leaving. Thanks for playing with me today. Enjoy the rest of your day!", "playful"),
        ("Stepping away? Thank you for checking out my sorting game. Have an awesome day!", "playful"),
        ("Goodbye for now! It was a pleasure sorting items with you. Enjoy the campus open day!", "playful"),
        ("Off you go! Thanks for spending time with me. Have fun during the rest of your visit!", "playful"),
        ("Catch you later! Thanks for playing, hope you have a wonderful open day!", "playful"),
    ],
    # Copy move — scores
    ("copy_move", "score_perfect"): [
        ("Perfect! You nailed every single pose. Are you sure you are not a robot yourself?", "excited"),
        ("Flawless replication! 100% accuracy on all moves. You're a natural mimic!", "excited"),
        ("Wow, perfect score! You mirrored every single gesture flawlessly. Brilliant!", "excited"),
        ("Incredible! You matched every pose down to the millimeter. Are we clones?", "excited"),
        ("A perfect run! Not a single error in your poses. Masterful performance!", "excited"),
    ],
    ("copy_move", "score_good"): [
        ("Really good! You got most of them right. Very impressive mirroring.", "excited"),
        ("Great job! Your poses were mostly accurate. You've got solid mirror skills.", "excited"),
        ("Nice work! You captured the essence of almost all my poses successfully.", "excited"),
        ("Solid score! You tracked my movements very well throughout the game.", "excited"),
        ("Very impressive! Only a few minor details missed, but a great performance.", "excited"),
    ],
    ("copy_move", "score_ok"): [
        ("One down. My poses might need to be a bit clearer. Want to try again?", "encouraging"),
        ("An okay attempt! Replicating robot joints can be stiff. Want a retry?", "encouraging"),
        ("You got a few of them! With a bit more focus, you'll get a higher score next time.", "encouraging"),
        ("Not a bad effort, but there's room for improvement. Should we try once more?", "encouraging"),
        ("Fair score! You matched some poses nicely. Want another round to beat it?", "encouraging"),
    ],
    ("copy_move", "score_poor"): [
        ("Hmm, none of those landed quite right. That one is tricky", "encouraging"),
        ("Oof, tough round! Mirroring digital postures is harder than it looks. Retry?", "encouraging"),
        ("Looks like the scores are low this time. Don't worry, let's try it again!", "encouraging"),
        ("Not quite your game today, huh? Let's give it another shot to improve.", "encouraging"),
        ("A bit off-target on the poses, but it takes practice. Ready for a second try?", "encouraging"),
    ],
    # Staring contest — countdown
    ("staring_waiting_ready", "intro"): [
        ("Look me in the eye, the first one to look away will loose! Press my left bumper to start the contest!", "excited"),
        ("Prepare your eyes! First person to blink or look away loses. Click the left bumper to begin!", "excited"),
        ("Staring match time! Keep your eyes locked on mine. Press the left bumper to kick off the countdown!", "excited"),
        ("Can you out-stare a machine? Let's find out! Hit my left bumper when you're ready to focus!", "excited"),
        ("Let's lock eyes! The rules are simple: look away and you lose. Press my left bumper to start!", "excited"),
    ],
    ("staring_countdown", "countdown"): [
        ("three, two, one", "neutral"),
        ("Starting in: three, two, one", "neutral"),
        ("Get ready... three, two, one, go!", "neutral"),
        ("Locking eyes in three, two, one", "neutral"),
        ("Countdown active: three, two, one", "neutral"),
    ],
    # Staring contest — active phase
    ("staring_active", "event"): [
        ("Keep your eyes on me!", "calm"),
        ("Don't look away now!", "calm"),
        ("Stay focused right here.", "calm"),
        ("Keep staring into my sensors.", "calm"),
        ("Maintain eye contact!", "calm"),
    ],
    ("staring_active", "provocation_steady"): [
        ("You are holding steady", "playful"),
        ("Wow, you have intense focus!", "playful"),
        ("Look at you go, strong concentration!", "playful"),
        ("Impressive willpower so far.", "playful"),
        ("You're a tough competitor, no movement yet!", "playful"),
    ],
    ("staring_active", "provocation_distract"): [
        ("Is that someone calling your name behind you?", "playful"),
        ("Oh look! What's that shiny thing over there?", "playful"),
        ("Did you just hear a weird noise behind your back?", "playful"),
        ("Wow, look at that crazy science project over to your left!", "playful"),
        ("Hey, I think your friend is waving at you right now!", "playful"),
    ],
    ("staring_active", "provocation_distract_followup"): [
        ("Just a test. Keep your eyes forward", "calm"),
        ("Haha, didn't work! Stay locked in.", "calm"),
        ("Nice try, but you gotta keep looking at me.", "calm"),
        ("Just trying to throw you off. Eyes on me!", "calm"),
        ("A little distraction test. Don't break focus now.", "calm"),
    ],
    ("staring_active", "provocation_eyelids"): [
        ("I have no eyelids. I can do this forever", "excited"),
        ("Remember, I'm a robot. I don't need to blink at all!", "excited"),
        ("My optical lenses never get dry. Advantage: robot!", "excited"),
        ("Fun fact: glass lenses don't blink. Good luck!", "excited"),
        ("I could literally stream this view for days without blinking.", "excited"),
    ],
    ("staring_active", "blink_detected"): [
        ("I saw that blink. Blinking is allowed, but keep your eyes still pointing at me", "playful"),
        ("Caught a little blink there! Remember, as long as you look at me, you're fine.", "playful"),
        ("A quick blink! That's okay, just don't turn your head away.", "playful"),
        ("Nice blink, but your gaze is still locked. The game continues!", "playful"),
        ("Detected an eye flutter! You're still in the game though, keep staring.", "playful"),
    ],
    ("staring_active", "forfeit"): [
        ("Alright, contest is over. That counts as a forfeit.", "playful"),
        ("Moving away? I'll have to mark this as a forfeit then.", "playful"),
        ("Game closed. It looks like you abandoned the staring challenge.", "playful"),
        ("Staring match canceled. Forfeit registered in my system.", "playful"),
        ("Looks like we stopped early. That's a forfeit, my friend!", "playful"),
    ],
    # Staring contest — ending
    ("staring_ending", "misty_wins"): [
        ("There it is, you looked away, I win!", "excited"),
        ("Aha! Your eyes shifted. Victory goes to the robot!", "excited"),
        ("Gotcha! You turned away first. Score one for Misty!", "excited"),
        ("And you looked away! Machine supremacy wins this round.", "excited"),
        ("Yes! I broke your concentration. Another win for me!", "excited"),
    ],
    ("staring_ending", "misty_wins_result"): [
        ("That was a good match. You lasted quite a while.", "excited"),
        ("Honestly, great effort. Humans usually blink much faster.", "excited"),
        ("Solid attempt! You put up a really good fight against my cameras.", "excited"),
        ("Impressive endurance! Most people look away in the first few seconds.", "excited"),
        ("You have great focus! That was a much closer match than expected.", "excited"),
    ],
    ("staring_ending", "misty_loses"): [
        ("Okay, I give up, you win.", "sad"),
        ("Wow, okay, you win! My processors are overheating from staring.", "sad"),
        ("I yield! Your focus is unbreakable. You beat the machine!", "sad"),
        ("Incredible, you won! My cameras couldn't outlast your determination.", "sad"),
        ("Fine, you win this one! Your staring skills are genuinely terrifying.", "sad"),
    ],
    # Staring contest — post game
    ("staring_post_game", "post_game_prompt"): [
        ("Do you want a rematch, or are we calling it here? Press left to go again or right to move on.", "calm"),
        ("Ready to lock eyes again, or should we switch? Press LEFT to retry, RIGHT to browse.", "calm"),
        ("Double or nothing? Press LEFT for a quick rematch, or hit RIGHT for something else.", "calm"),
        ("Shall we stare down once more? Tap LEFT to challenge me again, or RIGHT to quit.", "calm"),
        ("Want another round of eye contact? Click LEFT to replay, or RIGHT to change games.", "calm"),
    ],
    ("staring_post_game", "no_response"): [
        ("Looks like you are heading off. Thanks for playing. Enjoy the rest of the open day.", "playful"),
        ("No answer, you must be moving on. Thanks for the match, enjoy the open day!", "playful"),
        ("Silence! I'll assume you left. Thanks for staring with me, have fun today!", "playful"),
        ("Looks like our connection timed out. Have an awesome time at the open day!", "playful"),
        ("Going somewhere else? Thanks for playing the staring game, enjoy your day!", "playful"),
    ],
    ("staring_post_game", "play_again"): [
        ("Let us go! Next round!", "excited"),
        ("Round two! Don't look away this time!", "excited"),
        ("Awesome, rematch initiated! Eyes on me!", "excited"),
        ("Yes! Let's see who wins this time. Focus!", "excited"),
        ("Back into the ring! Commencing staring protocols now!", "excited"),
    ],
    ("staring_post_game", "goodbye"): [
        ("Take care! That was a great game. See you around!", "playful"),
        ("Bye bye! Thanks for the fun staring battle. See you later!", "playful"),
        ("Catch you later! Stay focused out there, see you around the campus!", "playful"),
        ("Thanks for hanging out! Enjoy the open day, see you!", "playful"),
        ("Great game! Have fun checking out all the cool tech today, goodbye!", "playful"),
    ],
    # Post-game
    ("post_game", "no_response"): [
        ("Looks like you are heading off — thanks for playing! Enjoy the rest of the open day.", "playful"),
        ("No answer — I will take that as a goodbye. See you around!", "playful"),
        ("Silence implies departure! Thanks for the gaming session. Enjoy your day!", "playful"),
        ("Looks like you wandered off. Thanks for trying my games, see ya!", "playful"),
        ("Time out! Thanks for playing with me today, have a blast at the open day!", "playful"),
    ],
    ("post_game", "rematch_prompt"): [
        ("Press left for a rematch. Or press right to try a different game.", "calm"),
        ("Want to play this game again? Press LEFT to retry, or RIGHT for a new challenge.", "calm"),
        ("Ready for round two? Hit LEFT to replay, or press RIGHT to return to the menu.", "calm"),
        ("Should we give this another shot? Tap LEFT for a rematch, or RIGHT to switch it up.", "calm"),
        ("Can you do better next time? Click LEFT to go again, or RIGHT for other games.", "calm"),
    ],
    ("post_game", "rematch_yes"): [
        ("Let us go — round two!", "excited"),
        ("Awesome choice, let's start the rematch immediately!", "excited"),
        ("Let's do it! Round two is officially rolling!", "excited"),
        ("Heck yes! Time to beat your previous score, go go go!", "excited"),
        ("Perfect, reloading the game modules for round two right now!", "excited"),
    ],
    ("post_game", "rematch_no"): [
        ("Fair enough! Back to the menu.", "calm"),
        ("No worries, back we go!", "calm"),
        ("All right, exiting this mode. Let's find something else.", "calm"),
        ("Understood, terminating current session. Returning to selections.", "calm"),
        ("No problem, let's head straight back to the main list.", "calm"),
    ],
    ("post_game", "menu"): [
        ("Back to the menu then. Choose your next challenge!", "playful"),
        ("Main menu loaded! What game are we picking next?", "playful"),
        ("And we are back at the selection screen. Pick your poison!", "playful"),
        ("Welcome back to the dashboard. Tell me which game you want to try now!", "playful"),
        ("Menu refreshed! Ready for a different adventure? Pick a new game!", "playful"),
    ],
    ("post_game", "goodbye"): [
        ("Take care! That was a great game. See you around!", "playful"),
        ("Goodbye! Thanks for the awesome entertainment, see you later!", "playful"),
        ("Farewell! Glad we got to play together. Enjoy the open day attractions!", "playful"),
        ("See you later, human! Thanks for testing my gaming protocols today.", "playful"),
        ("Bye! Don't be a stranger, come back and play whenever you like!", "playful"),
    ],
    # Global Conversational Fallbacks
    ("global", "ask_who"): [
        ("I am Misty, a social robot. I like meeting new people, playing games, and pretending I know things when I really do not.", "playful"),
        ("My name is Misty! I'm an interactive social robot built for games, conversation, and hanging out with cool humans.", "playful"),
        ("I'm Misty, your friendly neighborhood robot entertainer. I love tracking data and playing mini-games with guests!", "playful"),
        ("They call me Misty! I'm a smart social robot designed to scan faces, guess vibes, and challenge you to quick games.", "playful"),
        ("I am Misty, an AI-powered social companion robot here to liven up your open day with some interactive challenges!", "playful"),
    ],
    ("global", "ask_repeat"): [
        ("Of course. Let me state that again.", "calm"),
        ("No problem. Repeating the last message for you now.", "calm"),
        ("Sure thing, let me play back what I just said.", "calm"),
        ("Easily done! Here is that information one more time.", "calm"),
        ("No worries, let me re-verify that statement for you right now.", "calm"),
    ],
    ("global", "ask_not_understand"): [
        ("No problem, I will try and explain it in a simpler way.", "calm"),
        ("Ah, let me rephrase that so it makes a bit more sense.", "calm"),
        ("My bad, let me break that down into easier terms for you.", "calm"),
        ("Let's simplify that statement so we are on the same page.", "calm"),
        ("No worries, I can explain that differently if you didn't quite get it.", "calm"),
    ],
    ("global", "ask_start_over"): [
        ("No problem. Let's begin from the start", "playful"),
        ("Resetting the conversation! Let's take it from the top.", "playful"),
        ("Rewinding the clock! Let's restart this interaction right now.", "playful"),
        ("Clear the board! Let's begin our conversation completely fresh.", "playful"),
        ("No worries at all, rebooting this section so we can start over.", "playful"),
    ],
    ("global", "ask_rephrase"): [
        ("I am not completely sure what you mean. Could you rephrase that?", "calm"),
        ("That didn't quite parse in my system. Can you say that in a different way?", "calm"),
        ("Hmm, I missed the meaning of that. Could you rewrite or rephrase your answer?", "calm"),
        ("My linguistic sensors are confused. Could you explain what you mean using other words?", "calm"),
        ("I'm having trouble understanding your intent. Mind rephrasing that for me?", "calm"),
    ],
}


def get_fallback(state: str, event: str) -> DialogueResponse:
    key = (state, event)
    options = FALLBACKS.get(key)
    if not options:
        # Check global triggers if specific state-event is not explicitly mapped
        global_options = FALLBACKS.get(("global", event))
        if global_options:
            reply, tone = random.choice(global_options)
            return DialogueResponse(intent=event, reply=reply, tone=tone)
        return DialogueResponse(intent="unknown", reply="Okay!", tone="neutral")
    reply, tone = random.choice(options)
    return DialogueResponse(intent=event, reply=reply, tone=tone)


# ---------------------------------------------------------------------------
# Intent routing per state
# ---------------------------------------------------------------------------

INTENT_MAP: dict[str, list[str]] = {
    "idle":               ["chat", "person_detected", "ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"],
    "greeting_consent":   ["yes", "no", "unknown", "intro", "ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"],
    "engineer_confirm":   ["yes", "no", "unknown", "guess", "ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"],
    "game_menu":          ["start_game", "list_games", "repeat", "unknown", "intro", "left_pressed", "descriptions", "stop", "no", "ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"],
    "reaction":           ["ready", "no", "unknown", "intro", "reaction_explain", "waiting_ready", "go", "reaction_go", "early", "reaction_early", "reaction_result", "result_fast_robot", "result_fast", "result_medium", "result_slow", "no_response", "rematch_prompt", "goodbye", "ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"],
    "staring":            ["ready", "no", "unknown", "intro", "hold_5s", "hold_10s", "hold_12s", "hold_17s", "blink", "speak", "stop", "lost_face", "misty_wins", "misty_loses", "rematch_prompt", "no_response", "ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"],
    "copy_move":          ["ready", "no", "unknown", "intro", "no_movement_5s", "again", "correct", "partially_correct", "wrong", "rematch_prompt", "no_response", "ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"],
    "emotion_guess":      ["ready", "no", "unknown", "intro", "round_begin", "correct", "wrong", "score_3", "score_2", "score_1", "score_0", "rematch_prompt", "goodbye", "ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"],
    "sorting":            ["ready", "no", "unknown", "intro", "confirm", "sorting_item", "sorting_correct", "sorting_wrong", "sorting_skip", "sorting_harder", "sorting_perfect", "sorting_good", "sorting_ok", "sorting_poor", "repeat", "ask_rule", "rematch_prompt", "goodbye", "ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"],
    "post_game":          ["rematch_yes", "rematch_no", "menu", "goodbye", "no_response", "unknown", "rematch_prompt", "ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"],
}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

INTENT_DESCRIPTIONS = {
    "yes": "User agrees or confirms",
    "no": "User disagrees or declines",
    "unknown": "Meaning unclear",
    "repeat": "User wants options repeated",
    "start_game": "User selected a game",
    "stop": "User wants to stop current explanation",
    "left_pressed": "User wants game descriptions",
    "ready": "User is ready to start",
    "again": "User wants another attempt",
    "ask_rule": "User asks for rules",
    "ask_who": "User asks who Misty is",
    "ask_repeat": "User asks to repeat",
    "ask_not_understand": "User does not understand",
    "ask_start_over": "User wants to restart",
    "ask_rephrase": "Input could not be understood",
    "rematch_yes": "User wants another round",
    "rematch_no": "User does not want another round",
    "menu": "User wants to return to menu",
    "list_games": "User wants to hear the 5 minigames (C)",
    "goodbye": "User wants to leave",
}

SYSTEM_PROMPT = """\
You are Misty, a cheerful, witty social robot at the TU/e Open Day.
Your primary task is INTENT CLASSIFICATION and generating a short response based on the user's input and the robot's current state.

CRITICAL: Automated Speech Recognition (ASR) errors are highly frequent. Visitors are speaking in a noisy university hall.
You must use contextual clues, phonetic similarity (words that sound alike), and the current game state to reconstruct the user's true intent.

ASR CORRECTION GUIDELINES:
1. Phonetic Faults: Look for words that sound similar to game actions. 
   - "ball thing", "gold thing", "called thin" -> "cold thing" (State: sorting)
   - "staring cantest", "starring", "starting content" -> "start_game" / "staring contest" (State: game_menu)
   - "rematch", "ree match", "we match", "match again" -> "rematch_yes" (State: post_game)
   - "bother game", "main you", "man you" -> "menu" (State: post_game)
2. State Context Isolation:
   - If State is 'sorting' and user says anything resembling temperature, it's 'cold_thing'.
   - If State is 'post_game', "yes", "yeah", "one more", "let's do it" maps to 'rematch_yes'. "no", "exit", "menu" maps to 'goodbye' or 'menu'.
   - If State is 'game_menu', any mention of "play", "speed", "test", "mirror", "face", "emotions", or "guess" maps to 'start_game'.

Rules:
- Choose EXACTLY ONE intent from the provided 'available_intents' list.
- Never invent intents. Intent selection is more important than the reply.
- Keep replies under 15 words.
- Keep replies conversational, playful, and always speak English.

Examples of ASR Correction:
- State: sorting, User: "i think it is a ball thing" -> Intent: cold_thing (Reconstructed: "cold thing")
- State: game_menu, User: "i want to try the starring content" -> Intent: start_game (Reconstructed: "staring contest")
- State: post_game, User: "go to the man you" -> Intent: menu (Reconstructed: "menu")
- State: post_game, User: "we match" -> Intent: rematch_yes (Reconstructed: "rematch")
- State: reaction, User: "ready to roll" -> Intent: ready
- State: game_menu, User: "tell me what traps you have" -> Intent: list_games (Reconstructed: "what apps/games you have")

Return ONLY valid JSON in this format:
{
  "intent": "<one of available_intents>",
  "reply": "<spoken response>",
  "tone": "<playful|calm|excited|encouraging|sad|neutral>"
}
"""


# ---------------------------------------------------------------------------
# DialogueManager
# ---------------------------------------------------------------------------

class DialogueManager:
    def __init__(self, use_llm: bool = USE_LLM) -> None:
        self.use_llm = use_llm
        self.client = self._create_client() if self.use_llm else None
        self._lock = threading.Lock()

    def _create_client(self):
        """Initializes the GenAI client if library and API key are available."""
        if genai is None:
            print("[Dialogue] google-genai package not installed. Running OFFLINE.")
            return None
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("[Dialogue] GEMINI_API_KEY missing in .env. Running OFFLINE.")
            return None
            
        try:
            return genai.Client(api_key=api_key)
        except Exception as e:
            print(f"[Dialogue] Failed to initialize Gemini Client: {e}. Running OFFLINE.")
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def respond(
        self,
        state:      str,
        user_input: str = "",
        context:    dict | None = None,
    ) -> DialogueResponse:
        available = INTENT_MAP.get(state, ["unknown"])
        if self.use_llm and self.client is not None:
            print("[STT] Using LLM to respond.")
            result = self._llm_call(
                state=state, user_input=user_input, event="",
                available=available, context=context or {},
            )
            if result:
                return result
        
        # Offline Fallback
        intent = self._regex_intent(state, user_input)
        if intent not in available:
            # Check global intents as a generic fallback route
            if intent in ["ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"]:
                pass
            else:
                intent = "unknown"
            
        fb = get_fallback(state, intent)
        fb.intent = intent
        return fb

    def event(
        self,
        state:   str,
        event:   str,
        context: dict | None = None,
    ) -> DialogueResponse:
        # LLM not necessary for normal events
        #available = INTENT_MAP.get(state, ["unknown"])
        #if self.use_llm and self.client is not None:
        #    result = self._llm_call(
        #        state=state, user_input="", event=event,
        #        available=available, context=context or {},
        #    )
        #    if result:
        #        return result
        return get_fallback(state, event)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _llm_call(
        self,
        state:      str,
        user_input: str,
        event:      str,
        available:  list[str],
        context:    dict,
    ) -> DialogueResponse | None:
        current_situation = {
            "current_state": state,
            "user_input": user_input or "(none)",
            "event": event or "(none)",
            "available_intents": available,
            "intent_descriptions": {k: INTENT_DESCRIPTIONS.get(k, "") for k in available},
            "extra_context": context
        }

        prompt = f"Analyze the following current situation and return the JSON response:\n{json.dumps(current_situation, indent=2)}"

        try:
            with self._lock:
                response = self.client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        max_output_tokens=250,
                        response_mime_type="application/json",
                        safety_settings=[
                            genai_types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",       threshold="OFF"),
                            genai_types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="OFF"),
                            genai_types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
                            genai_types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
                        ],
                    ),
                )
            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            
            data   = json.loads(raw)
            intent = str(data.get("intent", "unknown")).strip()
            reply  = str(data.get("reply",  "")).strip()
            tone   = str(data.get("tone",   "neutral")).strip().lower()
            
            if not reply:
                return None
            if tone not in VALID_TONES:
                tone = "neutral"
            if intent not in available and intent not in ["ask_who", "ask_repeat", "ask_not_understand", "ask_start_over", "ask_rephrase"]:
                intent = "unknown"
                
            return DialogueResponse(intent=intent, reply=reply, tone=tone)
        except Exception as exc:
            print(f"[Dialogue] LLM error or timeout: {exc}")
            return None
        
    def _regex_intent(self, state: str, text: str) -> str:
        """Smart regex intent matching based on current state context and global inputs."""
        t = text.strip().lower()

        # 1. Game selection menu rules
        if state == "game_menu":
            if "stop" in t:
                return "stop"
            if any(w in t for w in ("left button", "press left", "hit left", "tap left", "click left", "random", "surprise")):
                return "left_pressed"
            if any(w in t for w in (
                "game", "play", "staring", "contest", "reaction", "speed", "test", 
                "copy", "move", "pose", "mirror", "mimic", "sorting", "challenge", 
                "emotion", "guess", "feelings", "yes"
            )):
                return "start_game"
            if any(w in t for w in ("repeat", "again", "options", "what", "list", "remind", "refresh")):
                return "repeat"
            if any(w in t for w in ("no", "not now", "maybe later", "change your mind", "no pressure", "quit")):
                return "no"

        # 2. Game specific rules
        if state == "sorting":
            if any(w in t for w in ("rule", "pattern", "criteria", "how to play", "explain again")):
                return "ask_rule"
            if any(w in t for w in ("repeat", "again", "remind", "say that item again", "what was it")):
                return "repeat"
            
            # Categorie: Hot vs Cold
            if any(w in t for w in ("cool", "cold", "chilly", "freeze", "ice", "snow", "ball thing", "gold thing", "called thin")):
                return "cold_thing"
            if any(w in t for w in ("hot", "warm", "fire", "burning", "sun", "coffee", "heat", "hat thing", "heart")):
                return "hot_thing"
                
            # Categorie: Living vs Non-Living
            if any(w in t for w in ("living", "alive", "nature", "plant", "animal", "dog", "tree", "fish", "leaving thing")):
                return "living_thing"
            if any(w in t for w in ("non-living", "not alive", "object", "chair", "rock", "stone", "dead", "none living")):
                return "non_living_thing"
                
            # Categorie: Indoor vs Outdoor
            if any(w in t for w in ("indoor", "inside", "house", "room", "sofa", "television", "lamp", "in door")):
                return "indoor_thing"
            if any(w in t for w in ("outdoor", "outside", "nature", "street", "bicycle", "out door", "out there")):
                return "outdoor_thing"

        if state == "copy_move":
            if any(w in t for w in ("again", "show me again", "repeating", "re-display", "one more time")):
                return "again"

        # 3. Game readiness states
        if state in ("reaction", "staring", "copy_move", "emotion_guess", "sorting"):
            if any(w in t for w in (
                "ready", "start", "go", "yes", "ok", "sure", "alright", "continue", 
                "begin", "roll", "focus", "set", "launch", "kick it off"
            )):
                return "ready"
            if any(w in t for w in ("stop", "give up", "forfeit", "cancel", "abandon", "quit")):
                return "stop"

        # 4. Post game options
        if state == "post_game":
            if any(w in t for w in ("rematch", "again", "yes", "one more", "retry", "replay", "round two", "double or nothing")):
                return "rematch_yes"
            if any(w in t for w in ("menu", "other", "change", "switch", "dashboard", "selection", "back")):
                return "menu"
            if any(w in t for w in ("stop", "quit", "exit", "goodbye", "bye", "no", "leave", "leaving", "heading off")):
                return "goodbye"

        # 5. Generic Affirmation & Rejections
        if any(w in t for w in (
            "yes", "yeah", "yep", "sure", "ok", "okay", "absolutely", "pretty close", 
            "alright", "continue", "bullseye", "nailed it", "correct", "spot on", "exact"
        )):
            return "yes"
        if any(w in t for w in (
            "no", "nope", "nah", "not really", "no thanks", "stop", "you are wrong", 
            "wrong", "incorrect", "miss", "mismatch", "false start", "too early"
        )):
            return "no"
            
        return "ask_rephrase"

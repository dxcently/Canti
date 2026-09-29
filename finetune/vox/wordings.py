"""Training-only wordings (v2). Held-out wordings stay in generate.py and are never listed here.

Diversity is the point: with 2 wordings per action the student memorised strings (v1: 38-61%
on reworded rules). These lists teach it that many surface forms map to one option.
check_disjoint() guards against leaking any held-out wording into training.
"""

from __future__ import annotations

ACTION_WORDS_TRAIN = {
    "swipe_up": ["swipe up", "flick up", "swipe upward", "scroll to the next thing by swiping up", "do an upward swipe", "fling the page up", "swipe the screen up", "slide up"],
    "swipe_down": ["swipe down", "flick down", "swipe downward", "do a downward swipe", "fling the page down", "swipe the screen down", "slide down", "pull down on the screen"],
    "swipe_left": ["swipe left", "flick left", "swipe leftward", "do a left swipe", "swipe the screen left", "slide left", "swipe toward the left", "fling it left"],
    "swipe_right": ["swipe right", "flick right", "swipe rightward", "do a right swipe", "swipe the screen right", "slide right", "swipe toward the right", "fling it right"],
    "tap": ["tap", "tap the screen", "single tap", "press the screen", "tap once", "do a tap", "poke the screen", "select what's under the finger"],
    "double_tap": ["double-tap", "tap twice", "double tap the screen", "do a double tap", "two quick taps", "tap-tap"],
    "long_press": ["long-press", "press and hold", "hold down", "do a long press", "press and keep holding", "hold the screen"],
    "back": ["go back", "press back", "hit the back button", "navigate back", "back out", "the back action", "undo the last screen", "exit this screen"],
    "home": ["go home", "go to the home screen", "press home", "hit the home button", "show the home screen", "leave the app to home"],
    "recents": ["open recent apps", "show the app switcher", "open the recents view", "show recent apps", "switch between apps", "open multitasking"],
    "notifications": ["open notifications", "pull down the notification shade", "show notifications", "open the notification panel", "check notifications", "drop down the status bar"],
    "scroll_up": ["scroll up", "scroll up a little", "scroll upward a bit", "small scroll up", "move the page up a little", "scroll back up"],
    "scroll_down": ["scroll down", "scroll down a little", "scroll downward a bit", "small scroll down", "move the page down a little", "keep scrolling down"],
    "zoom_in": ["zoom in", "magnify", "zoom closer", "pinch out", "enlarge the view", "get a closer look"],
    "zoom_out": ["zoom out", "shrink the view", "zoom further out", "pinch in", "see more of the map", "pull the view back"],
    "next_item": ["go to the next item", "skip ahead", "next", "skip to the next one", "go forward one", "advance", "next video", "next song"],
    "previous_item": ["go to the previous item", "go back one item", "previous", "the one before again", "go to the one before", "previous video", "previous song", "rewind to the prior item"],
    "play_pause": ["play or pause", "toggle playback", "pause", "resume playing", "pause or resume", "toggle play"],
    "volume_up": ["turn the volume up", "make it louder", "volume up", "increase volume", "crank it up", "boost the sound"],
    "volume_down": ["turn the volume down", "make it quieter", "volume down", "decrease volume", "quiet it down", "reduce the sound"],
    "open_camera": ["open the camera", "launch the camera", "open camera", "go to the camera", "bring up the camera", "fire up the camera"],
    "take_photo": ["take a photo", "snap a picture", "take a picture", "press the shutter", "shoot a photo", "grab a photo"],
    "like": ["like it", "favourite it", "like this post", "hit like", "tap the like button", "add it to favourites", "thumbs up"],
    "enter_cursor_mode": ["switch to cursor mode", "turn on the cursor", "enter cursor mode", "start pointer mode", "show the cursor", "go into mouse mode"],
    "listen_for_phrase": ["listen for a phrase", "start listening", "listen for speech", "get ready for a voice command", "open the mic for a phrase", "listen to what I say next"],
}

GESTURE_WORDS_TRAIN = {
    "rise": ["a rising hum", "a low-to-high hum", "humming upward", "a hum that goes up", "an ascending hum", "a hum sliding up", "humming from low to high"],
    "fall": ["a falling hum", "a high-to-low hum", "humming downward", "a hum that goes down", "a descending hum", "a hum sliding down", "humming from high to low"],
    "arch": ["an arch hum (up then down)", "a hum that goes up then down", "an up-down hum", "a hum that peaks in the middle", "humming up and back down"],
    "dip": ["a dip hum (down then up)", "a hum that goes down then up", "a down-up hum", "a hum that sags in the middle", "humming down and back up"],
    "flat": ["a long flat hum", "a steady hum", "a flat hum", "a held hum", "one long even hum", "a sustained hum"],
    "click": ["a tongue click", "a click", "a clicking tongue", "clicking my tongue", "a cluck"],
    "hiss": ["a hiss", "an sss sound", "hissing", "a ssss noise", "a snake sound"],
}

RULE_TEMPLATES_TRAIN = [
    "In {app}, {g} means {a}.",
    "When {app} is open, map {g} to {a}.",
    "{app}: {g} -> {a}",
    "For {app} only, {g} should {a}.",
    "Inside {app}, use {g} to {a}.",
    "{app} rule - {g}: {a}",
    "When I'm in {app}, {g} = {a}.",
    "Bind {g} to '{a}' in {app}.",
    "Set {g} to {a} for {app}.",
    "{g} in {app} should {a}.",
    "In the {app} app, make {g} {a}.",
    "Only while {app} is showing: {g} does {a}.",
]
GLOBAL_TEMPLATES_TRAIN = [
    "Everywhere, {g} means {a}.",
    "Globally map {g} to {a}.",
    "In every app, {g} -> {a}",
    "Always use {g} to {a}.",
    "Bind {g} to '{a}' in all apps.",
    "{g} should always {a}.",
    "Default override: {g} = {a}.",
    "For all apps, set {g} to {a}.",
]
DISABLE_TEMPLATES_TRAIN = [
    "In {app}, ignore {g}.",
    "Disable {g} in {app}.",
    "Turn off {g} while in {app}.",
    "{app}: {g} does nothing.",
    "Don't react to {g} in {app}.",
]
PHRASE_TEMPLATES_TRAIN = [
    "When I say '{p}', {a}.",
    "Phrase '{p}' -> {a}",
    "Saying '{p}' should {a}.",
    "Voice command '{p}': {a}.",
    "Map the words '{p}' to {a}.",
]


def check_disjoint(heldout: dict[str, tuple[list[str], list[str]]], train: dict[str, list[str]], what: str) -> None:
    for key, (_, held) in heldout.items():
        leak = set(held) & set(train.get(key, []))
        if leak:
            raise ValueError(f"{what} {key}: held-out wording leaked into training: {leak}")

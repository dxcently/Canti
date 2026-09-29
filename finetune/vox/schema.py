"""VOX decision vocabulary: what the Pico reports, what the phone can do.

Everything the decision model sees is categorical text computed on-device.
Raw Hz / ms / counts never reach the model (Jev's docs: it does not count or
compare numbers reliably), so the Pico buckets them first.
"""

from __future__ import annotations

# Pitch-contour shapes, measured in semitones relative to the start of the hum.
CONTOURS = {
    "rise": "rises from low to high",
    "fall": "falls from high to low",
    "arch": "rises then falls",
    "dip": "falls then rises",
    "flat": "stays level",
}
DISCRETE = {
    # "pop" is kept for parity with Kotlin's SoundFold, which rewrites pop lines to click at intake; the generator never emits it.
    "pop": "a short lip pop",
    "click": "a tongue click",
    "hiss": "a hiss",
}
EXCURSION = ["small (under 2 semitones)", "medium (2-4 semitones)", "large (over 4 semitones)"]
DURATION = ["very short (under 150 ms)", "short (150-400 ms)", "medium (400-1000 ms)", "long (over 1 s)"]
CLARITY = ["noisy", "breathy", "clear tone"]
LOUDNESS = ["quiet", "normal", "loud"]
# What the Pico's speech-vs-gesture detector guessed (syllable rate, spectral flux).
SOUNDS_LIKE = ["hum", "whistle", "talking", "laughing", "coughing", "background music", "background noise", "mouth sound"]

# Phone actions. key -> option text shown to the model.
ACTIONS = {
    "swipe_up": "swipe up",
    "swipe_down": "swipe down",
    "swipe_left": "swipe left",
    "swipe_right": "swipe right",
    "tap": "tap the screen",
    "double_tap": "double-tap the screen",
    "long_press": "long-press / hold",
    "back": "go back",
    "home": "go to the home screen",
    "recents": "open recent apps",
    "notifications": "open the notification shade",
    "scroll_up": "scroll up a little",
    "scroll_down": "scroll down a little",
    "zoom_in": "zoom in",
    "zoom_out": "zoom out",
    "next_item": "next item (video, song, page)",
    "previous_item": "previous item (video, song, page)",
    "play_pause": "play or pause media",
    "volume_up": "turn the volume up",
    "volume_down": "turn the volume down",
    "open_camera": "open the camera",
    "take_photo": "take a photo",
    "like": "like / favourite the current item",
    "listen_for_phrase": "listen for a spoken phrase",
    "none": "do nothing (not a deliberate command: noise, speech, or unclear)",
}

CURSOR_ACTIONS = {
    **{f"move_{d}_{s}": f"move cursor {d.replace('_', '-')} {s}"
       for d in ("up", "down", "left", "right", "up_left", "up_right", "down_left", "down_right")
       for s in ("slow", "fast")},
    "stop": "stop the cursor",
    "click": "click at the cursor",
    "drag_toggle": "start or end a drag at the cursor",
    "grid_pick_1": "grid: pick top-left cell",
    "grid_pick_5": "grid: pick centre cell",
    "grid_pick_9": "grid: pick bottom-right cell",
    "back": "go back",
    "none": ACTIONS["none"],
}

# Default gesture bindings (global profile) from the wiki's gesture vocabulary.
# 2026-09-28: a pop counts as a click (folded at intake); "pop"/"pop pop" removed.
DEFAULT_BINDINGS = {
    ("rise",): "swipe_up",
    ("fall",): "swipe_down",
    ("arch",): "swipe_right",
    ("dip",): "swipe_left",
    ("click",): "tap",
    ("hiss",): "back",
    ("flat",): "long_press",
    ("click", "click", "click"): "listen_for_phrase",
    ("click", "click"): "home",
    ("hiss", "click"): "back",   # same action as a single hiss, so hiss never waits for the click (Android Sequencer)
}
# Cursor mode is toggled ONLY by the device button / switch jack, never by a sound (so it is not an action).
# Mirrors Kotlin: after the fold "click pop" cannot occur (pop folds to click), so this freed sequence never happens.
FREED_SEQUENCES = [("click", "pop")]

# App-only bindings: resolved by the Android app's rule table in every decider mode, never shown to a model. Their
# actions are not in ACTIONS, so the students' option lists (and every dataset built from them) are unchanged.
# "forward" has no global action on Android: the app clicks a visible Forward control (or one in the overflow menu).
APP_ONLY_ACTIONS = {
    "forward": "go forward",
}
APP_ONLY_BINDINGS = {
    ("click", "hiss"): "forward",
}

# Foreground apps. Display name is what the Android app would resolve from the package.
APPS = {
    "com.zhiliaoapp.musically": "TikTok",
    "com.google.android.youtube": "YouTube",
    "com.google.android.apps.maps": "Google Maps",
    "com.spotify.music": "Spotify",
    "com.instagram.android": "Instagram",
    "com.amazon.kindle": "Kindle",
    "com.google.android.apps.photos": "Google Photos",
    "com.android.chrome": "Chrome",
    "com.whatsapp": "WhatsApp",
    "com.google.android.GoogleCamera": "Camera",
    "org.videolan.vlc": "VLC",
    "com.reddit.frontpage": "Reddit",
    "com.google.android.apps.docs": "Google Docs",
    "com.duolingo": "Duolingo",
    "com.netflix.mediaclient": "Netflix",
    "com.pinterest": "Pinterest",
}

# Spoken phrases (optional module) -> action. Held-out paraphrases live in generate.py.
PHRASES = {
    "back": ["go back", "back", "previous screen"],
    "home": ["go home", "home screen", "home"],
    "open_camera": ["open camera", "camera", "launch the camera"],
    "take_photo": ["take a picture", "snap a photo", "photo"],
    "next_item": ["next", "skip", "next one"],
    "previous_item": ["go back one", "the one before"],
    "play_pause": ["pause", "play", "resume"],
    "volume_up": ["louder", "volume up"],
    "volume_down": ["quieter", "volume down"],
    "scroll_down": ["scroll down", "down a bit"],
    "scroll_up": ["scroll up", "up a bit"],
    "like": ["like this", "heart it"],
    "notifications": ["show notifications", "open notifications"],
    "recents": ["recent apps", "show open apps"],
    "zoom_in": ["zoom in", "closer"],
    "zoom_out": ["zoom out", "further", "shrink"],
}

# Screen context (Android companion app, from the accessibility tree). Categorical like the sound
# fields. It is a TIE-BREAKER: explicit gestures and rules never change because of it; it only
# settles phrases whose meaning depends on the screen. Omitted when unavailable (iPhone HID path).
SCREEN_KIND = ["video feed", "video player", "scrolling list", "photo viewer", "map", "document",
               "camera viewfinder", "web page", "text entry", "dialog", "home screen", "other"]
SCREEN_MEDIA = ["playing", "paused", "none"]
SCREEN_SCROLL = ["can scroll both ways", "at the top", "at the bottom", "not scrollable"]
SCREEN_KEYBOARD = ["open", "hidden"]
# Plausible screens per app (the generator samples from these; the app reports what it sees).
APP_SCREENS = {
    "com.zhiliaoapp.musically": ["video feed"],
    "com.google.android.youtube": ["video feed", "video player", "scrolling list"],
    "com.google.android.apps.maps": ["map", "scrolling list"],
    "com.spotify.music": ["scrolling list", "video player"],
    "com.instagram.android": ["video feed", "scrolling list", "photo viewer"],
    "com.amazon.kindle": ["document", "scrolling list"],
    "com.google.android.apps.photos": ["photo viewer", "scrolling list"],
    "com.android.chrome": ["web page", "text entry"],
    "com.whatsapp": ["scrolling list", "text entry"],
    "com.google.android.GoogleCamera": ["camera viewfinder"],
    "org.videolan.vlc": ["video player", "scrolling list"],
    "com.reddit.frontpage": ["scrolling list", "video feed"],
    "com.google.android.apps.docs": ["document", "text entry"],
    "com.duolingo": ["other", "dialog"],
    "com.netflix.mediaclient": ["video player", "scrolling list"],
    "com.pinterest": ["scrolling list", "photo viewer"],
}


def screen_text(kind: str, media: str, scroll: str, keyboard: str) -> str:
    """One line, identical on the phone and in training data."""
    return f"screen: {kind}; media {media}; scroll {scroll}; keyboard {keyboard}"

# Screen tie-breaker for phrases (used by the generator and mirrored by the Android app).
SCREEN_NEXT = {"video feed": "swipe_up", "photo viewer": "swipe_left", "document": "swipe_left"}
SCREEN_PREV = {"video feed": "swipe_down", "photo viewer": "swipe_right", "document": "swipe_right"}
PAUSE_WORDS = {"pause", "stop the video", "hold on"}
PLAY_WORDS = {"play", "resume", "keep playing"}

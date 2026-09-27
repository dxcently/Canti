# Your test phrasings (the "gold" harder test)

Write these the way **you** would actually say or type them. Don't look at the training wordings or the generator, since the point is that no model has seen your style. Examples are kept to one per section on purpose. Don't reuse their words.

Short and messy is fine. Typos are fine. Aim for about **30 per section** (fewer is still useful). One per line.

After `=>` you may name the intended action from the list at the bottom. If you're not sure, leave it blank and I'll label it, then ask you about any I'm unsure of.

## A. Rules: telling VOX what a sound should do

Mention a sound (rising hum, falling hum, arch, dip, flat hum, pop, click, hiss, or two in a row like "click pop"), optionally an app, and what should happen.

- example: in spotify a rising hum should skip the song => next_item
-

## B. Asking for an action out loud (after the listen sound)

What you'd say to make the phone do something, with no sound gesture involved.

- example: turn it up a bit => volume_up
-

## C. Naming something on the screen (cursor mode)

How you'd point at a button, tab, icon or list item by name, by what it does, or by where it is. Say which app you're imagining, if any.

- example (YouTube): the little bell up top
-

## D. Things that should do nothing (optional)

Things you might say near the phone that are **not** commands, e.g. talking to someone, or thinking out loud about the phone.

- example: ugh this video is so long
-


## E. Real screens: say what you'd tap

For the real-screen test set (`finetune/data/real-targets-v1`). Pick a screen from the lists below, look at its picture,
and write one line per thing you'd say to tap something on it: `screen_id | what you'd say`. Say it the way you
really would (a name, where it is, what it does, what it looks like). Lines for things that are NOT on the screen are
welcome too; they test "none of these". Any number of lines per screen; skip screens you don't care about.

Pictures: emulator screens are `finetune/data/real-targets-v1/emulator/marks/<id>.png` (numbered boxes = options);
your Z Flip screens are `finetune/data/real-targets-v1/zflip/user_screens/zfNN.png` (these stay private, gitignored).
`python3 -m vox.real_targets tolabel` picks the lines up (source `user`); I then label them against the screen.

- example: emu-settings-01 | <the battery one>
- example: zf16 | <the little bell up top>

Your lines (add below):

-

### Emulator screens

- `emu-launcher-01`: Quickstep, home (8 options)
- `emu-launcher-02`: Quickstep, app drawer (20 options)
- `emu-launcher-04`: System UI, notifications (11 options)
- `emu-fixture-01`: VOX fixture, menu (4 options)
- `emu-fixture-05`: VOX fixture, list (17 options)
- `emu-fixture-06`: VOX fixture, list scrolled (18 options)
- `emu-fixture-07`: VOX fixture, controls (2 options)
- `emu-fixture-08`: VOX fixture, text entry (2 options)
- `emu-newpipe-01`: NewPipe, start (6 options)
- `emu-newpipe-02`: NewPipe, tab 2 (9 options)
- `emu-newpipe-04`: NewPipe, search (4 options)
- `emu-newpipe-05`: NewPipe, back (4 options)
- `emu-vlc-01`: VLC, start (10 options)
- `emu-vlc-03`: VLC, audio (14 options)
- `emu-vlc-04`: VLC, browse (17 options)
- `emu-vlc-05`: VLC, more (11 options)
- `emu-organicmaps-01`: Organic Maps, start (8 options)
- `emu-organicmaps-03`: Organic Maps, search (5 options)
- `emu-organicmaps-04`: Organic Maps, back (9 options)
- `emu-gallery-01`: Gallery, folders (6 options)
- `emu-gallery-02`: Gallery, photo (10 options)
- `emu-gallery-03`: Gallery, next photo (10 options)
- `emu-fennec-01`: Fennec, page (4 options)
- `emu-settings-01`: Settings, main (8 options)
- `emu-settings-02`: Settings, main scrolled (10 options)
- `emu-settings-03`: Settings, main bottom (10 options)
- `emu-settings-04`: Settings, network (9 options)
- `emu-settings-06`: Settings, connected devices (4 options)
- `emu-settings-07`: Settings, display (9 options)
- `emu-settings-08`: Settings, display scrolled (10 options)
- `emu-settings-09`: Settings, screen timeout dialog (8 options)
- `emu-settings-10`: Settings, sound (9 options)
- `emu-settings-11`: Settings, apps (11 options)
- `emu-settings-12`: Settings, app info (11 options)
- `emu-settings-13`: Settings, accessibility (9 options)
- `emu-settings-14`: Settings, battery (6 options)
- `emu-settings-15`: Settings, date time (8 options)
- `emu-settings-16`: Settings Suggestions, search (3 options)
- `emu-settings-17`: Settings Suggestions, search typed (10 options)
- `emu-settings-18`: Settings, about (5 options)
- `emu-clock-01`: Clock, alarms (17 options)
- `emu-clock-02`: Clock, alarm expanded (27 options)
- `emu-clock-03`: Clock, add alarm (7 options)
- `emu-clock-04`: Clock, add alarm keyboard (6 options)
- `emu-contacts-01`: Contacts, list (4 options)
- `emu-contacts-02`: Contacts, new contact (8 options)
- `emu-contacts-04`: Contacts, drawer (10 options)
- `emu-contacts-06`: Contacts, search typed (4 options)
- `emu-dialer-01`: Phone, main (9 options)
- `emu-dialer-02`: Phone, keypad (18 options)
- `emu-dialer-03`: Phone, typed number (22 options)
- `emu-dialer-04`: Phone, contacts tab (10 options)
- `emu-clock-06`: Clock, clock tab (6 options)
- `emu-clock-07`: Clock, timer (16 options)
- `emu-clock-08`: Clock, timer typed (17 options)
- `emu-clock-09`: Clock, stopwatch (7 options)
- `emu-clock-10`: Clock, overflow menu (2 options)
- `emu-messages-01`: Messaging, list (3 options)
- `emu-messages-02`: Messaging, new conversation (5 options)
- `emu-messages-03`: Messaging, recipient typed (3 options)
- `emu-messages-04`: Messaging, menu (2 options)
- `emu-messages-05`: Messaging, settings (8 options)
- `emu-calendar-01`: Calendar, month (3 options)
- `emu-files-01`: Files, recent (10 options)
- `emu-files-02`: Files, drawer (17 options)
- `emu-files-03`: Files, downloads (13 options)
- `emu-files-05`: Android System, images folder (3 options)
- `emu-files-07`: Files, search (6 options)
- `emu-gallery3d-01`: Gallery, albums (4 options)
- `emu-gallery3d-04`: Gallery, photo controls (3 options)
- `emu-browser-01`: WebView Shell, page (3 options)
- `emu-browser-02`: WebView Shell, page scrolled (3 options)
- `emu-vox-01`: VOX, status (13 options)
- `emu-vox-02`: VOX, scrolled (14 options)
- `emu-calendar-08`: Calendar, view dropdown (3 options)
- `emu-calendar-09`: Calendar, month view (5 options)
- `emu-calendar-10`: Calendar, day view (3 options)
- `emu-launcher-06`: System UI, quick settings (16 options)
- `emu-launcher-07`: Quickstep, recents (4 options)
- `emu-launcher-08`: Quickstep, icon long press (3 options)
- `emu-launcher-09`: Quickstep, home long press (3 options)
- `emu-contacts-07`: Contacts, list with contacts (7 options)
- `emu-contacts-08`: Contacts, contact detail (5 options)
- `emu-contacts-09`: Contacts, detail menu (5 options)
- `emu-contacts-10`: Contacts, search typed (4 options)
- `emu-messages-06`: Messaging, compose (7 options)
- `emu-settings-19`: Settings, wifi (10 options)
- `emu-settings-20`: Settings, notifications (7 options)
- `emu-settings-21`: Settings, location (7 options)
- `emu-settings-22`: Permission controller, security (6 options)
- `emu-settings-23`: Settings, language (5 options)
- `emu-settings-24`: Settings, storage (10 options)
- `emu-settings-25`: Settings, font size (8 options)
- `emu-fennec-05`: Fennec, menu (16 options)
- `emu-fennec-06`: Fennec, tabs tray (20 options)
- `emu-fennec-07`: Fennec, url keyboard (9 options)

### Your Z Flip screenshots (phrases only from you; never sent to any outside model)

- `zf01`: YouTube Music: Liked music playlist
- `zf02`: YouTube Music: now playing
- `zf03`: YouTube Music: up next queue
- `zf04`: YouTube Music: home
- `zf05`: YouTube Music: home (scrolled)
- `zf06`: Fennec: GitHub repository list page
- `zf07`: Fennec: home with the keyboard open
- `zf08`: Fennec: tab switcher
- `zf09`: Obsidian: file tree
- `zf10`: Obsidian: file tree (second view)
- `zf11`: Obsidian: settings
- `zf12`: Obsidian: an open note
- `zf13`: YouTube: notifications
- `zf14`: YouTube: You page
- `zf15`: YouTube: search with the keyboard open
- `zf16`: YouTube: home feed

### Z Flip captures (tree), `zf-<app>-NN`

Marks images: `data/real-targets-v1/zflip/raw/marks/<id>.png`. More will be listed as they are captured.

- `zf-x-01`: X: home, For you tab, top of the feed
- `zf-x-02`: X: home, For you tab, scrolled once
- `zf-x-03`: X: home, For you tab, scrolled twice
- `zf-x-04`: X: home, Following tab, top of the feed
- `zf-x-05`: X: home, Following tab, scrolled once

---

Actions: swipe_up, swipe_down, swipe_left, swipe_right, tap, double_tap, long_press, back, home, recents, notifications, scroll_up, scroll_down, zoom_in, zoom_out, next_item, previous_item, play_pause, volume_up, volume_down, open_camera, take_photo, like, listen_for_phrase, none

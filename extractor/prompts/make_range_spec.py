"""Regenerate the non-personal range_v2 grid. Recorders read the JSON only.

range_v1.json is frozen (round 7 removed the pop sound: a pop now counts as a click, and a long hiss is a new
trigger). This generator writes range_v2.json only.
"""
import json
from pathlib import Path

KEYS = ('tone', 'pitch', 'speed', 'loud', 'dist', 'gap')
CENTRE = dict(zip(KEYS, ('hum', 'home', 'normal', 'normal', 'hand', 'na')))
DISCRETE = dict(CENTRE, tone='na', pitch='na', speed='na')
CONTOURS = ['rise', 'fall', 'arch', 'dip', 'flat']
SINGLES = ['click', 'hiss']
COMBOS = ['click click', 'click click click', 'hiss click', 'click hiss']
LONG_HISS_SPEEDS = ('long05', 'long07', 'long10')
HISS_S = {'long05': 0.5, 'long07': 0.7, 'long10': 1.0}


def condition_id(c):
    return '-'.join(c[k] for k in KEYS)


def speed_s(v):
    return HISS_S[v] if v in HISS_S else {'slow': 1.2, 'normal': .6, 'quick': .3, 'na': .3}[v]


def gap_s(v):
    return {'quick': .15, 'normal': .35, 'slow': .8, 'na': 0}[v]


def target_s(gesture, cond):
    if ' ' in gesture:   # a combo: 0.3 s per sound + the requested gap between sounds
        n = len(gesture.split())
        return .3 * n + gap_s(cond['gap']) * (n - 1)
    return speed_s(cond['speed'])


# Plain-language cue parts. The ALL-CAPS word is the cue's key word (the thing to notice); the Flutter Sentence
# widget and the PC terminal highlight ALL-CAPS words of 2+ letters.
GESTURE_OBJ = {'rise': ('a rise', 'rise'), 'fall': ('a fall', 'fall'), 'arch': ('an arch', 'arch'),
               'dip': ('a dip', 'dip'), 'flat': ('a flat note', 'flat'),
               'click': ('a click', 'click'), 'hiss': ('a hiss', 'hiss')}
COMBO_OBJ = {'click click': ('two clicks', 'clicks'), 'click click click': ('three clicks', 'clicks'),
             'hiss click': ('a hiss then a click', 'hiss'), 'click hiss': ('a click then a hiss', 'hiss')}
CHANGE = {'speed': {'slow': 'SLOWLY', 'quick': 'QUICKLY'},
          'loud': {'soft': 'SOFTLY', 'loud': 'LOUDLY'},
          'dist': {'table': 'at TABLE distance', 'across': 'ACROSS the room'},
          'gap': {'quick': 'with a QUICK gap', 'slow': 'with a SLOW gap'}}


def _obj(obj, key, cap):
    return obj.replace(key, key.upper()) if cap else obj


def cue(gesture, cond, centre):
    """Plain language with the key word(s) in capitals: the gesture at a block's centre, each change otherwise."""
    changes = [k for k in KEYS if cond[k] != centre[k]]
    target = target_s(gesture, cond)
    if ' ' in gesture:
        words = ['Make', _obj(COMBO_OBJ[gesture][0], COMBO_OBJ[gesture][1], not changes)]
        for k in ('loud', 'dist', 'gap'):
            if cond[k] != centre[k]:
                words.append(CHANGE[k][cond[k]])
    elif cond['tone'] == 'na':
        if gesture == 'hiss' and cond['speed'] in HISS_S:   # a long hiss (the cursor-listen sound)
            words = ['Make', 'a LONG hiss']
            for k in ('loud', 'dist'):
                if cond[k] != centre[k]:
                    words.append(CHANGE[k][cond[k]])
        else:
            words = ['Make', _obj(GESTURE_OBJ[gesture][0], GESTURE_OBJ[gesture][1], not changes)]
            for k in ('speed', 'loud', 'dist'):
                if cond[k] != centre[k]:
                    words.append(CHANGE[k][cond[k]])
    else:   # a hummed or whistled contour
        whistle = cond['tone'] == 'whistle'
        words = ['WHISTLE' if whistle else 'Hum',
                 _obj(GESTURE_OBJ[gesture][0], GESTURE_OBJ[gesture][1], not changes)]
        if cond['pitch'] == 'bottom':
            words.append('starting at your LOWEST note')
        elif cond['pitch'] == 'top':
            words.append('starting at your HIGHEST note')
        else:
            words.append('at your whistle home' if whistle else 'at your home note')
        for k in ('speed', 'loud', 'dist'):
            if cond[k] != centre[k]:
                words.append(CHANGE[k][cond[k]])
    # length matters for contours and hisses only: a click or a combo gets no 'about N s'
    if cond['tone'] != 'na' or gesture == 'hiss':
        words.append(f'about {target:g} s')
    return ' '.join(words)


def cell(gesture, cond, centre, **extra):
    target = target_s(gesture, cond)
    return dict(cell_id=gesture.replace(' ', '-') + '-' + condition_id(cond), expect=gesture.split(),
                cond=cond, cond_id=condition_id(cond), cue=cue(gesture, cond, centre), target_s=target,
                max_s=target + 2, reps=2, bg=None, **extra)


contour_conditions = [CENTRE] + [dict(CENTRE, **change) for change in [
    {'pitch': 'bottom'}, {'pitch': 'top'}, {'speed': 'slow'}, {'speed': 'quick'},
    {'loud': 'soft'}, {'loud': 'loud'}, {'dist': 'table'}, {'dist': 'across'}, {'tone': 'whistle'},
    {'loud': 'soft', 'dist': 'across', 'pitch': 'bottom'}, {'loud': 'loud', 'pitch': 'top'},
    {'speed': 'quick', 'loud': 'soft', 'dist': 'table'}, {'tone': 'whistle', 'speed': 'quick', 'dist': 'across'}]]
discrete_conditions = [DISCRETE] + [dict(DISCRETE, **c) for c in [
    {'loud': 'soft'}, {'loud': 'loud'}, {'dist': 'table'}, {'dist': 'across'}, {'loud': 'soft', 'dist': 'across'}]]
combo_centre = dict(DISCRETE, gap='normal')
combo_conditions = [combo_centre] + [dict(combo_centre, **c) for c in [
    {'gap': 'quick'}, {'gap': 'slow'}, {'dist': 'across'}, {'loud': 'soft'}]]
anchors = []
for anchor, pitch, tone, text in [
    ('bottom_hz', 'bottom', 'hum', 'LOWEST comfortable hum; do not strain'),
    ('home_hz', 'home', 'hum', 'HOME note; a relaxed normal hum'),
    ('top_hz', 'top', 'hum', 'HIGHEST comfortable hum; do not strain'),
    ('whistle_home_hz', 'home', 'whistle', 'WHISTLE home; a relaxed whistle')]:
    c = cell('flat', dict(CENTRE, pitch=pitch, tone=tone), CENTRE, anchor=anchor)
    c.update(cell_id=anchor, reps=1, cue=text + ' · hold about 2 s', target_s=2, max_s=5)
    anchors.append(c)
# The app's calibration room step (JoyCalibration / joystick.py: calib_v2.room window_ms 3000 + settle_ms 500): quiet
# for the room's floor and loudest transient, which raise the level gate. A fixed window (quiet: no silence detector).
ROOM = dict(zip(KEYS, ['na'] * len(KEYS)))
room = dict(cell_id='room', expect=[], cond=ROOM, cond_id=condition_id(ROOM), cue='Stay QUIET for 3 seconds',
            target_s=3, max_s=3.5, reps=1, bg=None, quiet=True)
backgrounds = [dict(name=f'media-{v}', kind='media', level=v) for v in (30, 60, 90)] + [
    dict(name='tv', kind='tv', level=None), dict(name='fan', kind='fan', level=None),
    dict(name='talk', kind='talk', level=None), dict(name='typing-kitchen', kind='other', level=None)]
background_cues = ['PLAY a reel or short on phone or laptop speakers at 30%',
                   'PLAY a reel or short on phone or laptop speakers at 60%',
                   'PLAY a reel or short on phone or laptop speakers at 90%',
                   'PLAY tv or music across the room', 'RUN a fan', 'PLAY people talking (a podcast)',
                   'MAKE typing or kitchen sounds']
discrete_cells = [cell(g, c, DISCRETE) for g in SINGLES for c in discrete_conditions]
for spd in LONG_HISS_SPEEDS:   # the long hiss: centre and across, three aimed lengths
    discrete_cells += [cell('hiss', dict(DISCRETE, speed=spd), DISCRETE),
                       cell('hiss', dict(DISCRETE, speed=spd, dist='across'), DISCRETE)]
real_cells = [cell(g, CENTRE, CENTRE) for g in CONTOURS] + \
    [cell(g, DISCRETE, DISCRETE) for g in SINGLES] + \
    [cell('hiss', dict(DISCRETE, speed='long10'), DISCRETE)] + \
    [cell(g, combo_centre, combo_centre) for g in COMBOS]
blocks = [dict(id='range', kind='takes', intro='Measure your own comfortable range first.', cells=anchors),
          dict(id='room', kind='takes', intro='Room. Stay quiet for 3 seconds (no talking, humming or tapping): this '
                                              "measures the room's noise, like the app's calibration room step.",
               cells=[room]),
          dict(id='contours', kind='takes',
               intro='Contours. Centre = hum at your home note, normal speed (about 0.6 s), normal loudness, hand '
                     'distance (about 25 cm); each prompt names only what differs. Pitch bottom/top are your measured '
                     'lowest/highest hum; whistle uses your whistle home.',
               cells=[cell(g, c, CENTRE) for g in CONTOURS for c in contour_conditions]),
          dict(id='discrete', kind='takes',
               intro='One mouth sound per GO. Centre = normal loudness at hand distance (about 25 cm); each prompt '
                     'names only what differs. A click is one tongue click; a hiss is a short tss (about 0.3 s), or '
                     'a LONG hiss (about 0.5, 0.7 or 1 s, the cursor-listen sound).',
               cells=discrete_cells),
          dict(id='combos', kind='takes',
               intro='Two or three sounds per GO. Centre = a normal gap (about 0.35 s), normal loudness, hand '
                     'distance; each prompt names only what differs. Keep the requested gap.',
               cells=[cell(g, c, combo_centre) for g in COMBOS for c in combo_conditions]),
          dict(id='backgrounds', kind='backgrounds', intro='Remain silent for each 60 second recording.',
               cells=[dict(cell_id=b['name'], **b, seconds=60, reps=1, cue=c + '; stay silent for 60 s')
                      for b, c in zip(backgrounds, background_cues)])]
for bg in (backgrounds[1], backgrounds[5]):   # real-media-60 and real-talk
    cells = [dict(c, bg=bg.copy()) for c in real_cells]
    for c in cells:
        c['cue'] += ' · with ' + bg['name'] + ' playing'
    blocks.append(dict(id='real-' + bg['name'], kind='takes', intro='Keep ' + bg['name'] +
                       ' playing throughout. Do each centre gesture and combo, twice.', cells=cells))


def pick(block_id, conditions, reps):
    """A profile's block: the cells of [block_id] whose condition is one of [conditions], in grid order; reps None =
    each cell's own."""
    block = next(b for b in blocks if b['id'] == block_id)
    return dict(id=block_id, cells=[c['cell_id'] for c in block['cells'] if conditions is None or c['cond'] in conditions],
                reps=reps)


# Profiles select cells of the one grid: cell_id, cond_id and take_id stay the same, so the sessions compare.
profiles = dict(
    full=dict(about='The whole grid, the default.', blocks=[pick(b['id'], None, None) for b in blocks]),
    short=dict(about='About 8 minutes, e.g. for a second speaker: the range step, the room step, contours at centre + '
                     'pitch bottom + loud soft + dist across, click and short hiss at centre + soft + across, long hiss '
                     'at centre (one rep each), combos at centre x 2; no backgrounds or real checks.',
               blocks=[pick('range', None, None),
                       pick('room', None, None),
                       pick('contours', [CENTRE, dict(CENTRE, pitch='bottom'), dict(CENTRE, loud='soft'),
                                         dict(CENTRE, dist='across')], 1),
                       pick('discrete', [DISCRETE, dict(DISCRETE, loud='soft'), dict(DISCRETE, dist='across')] +
                            [dict(DISCRETE, speed=spd) for spd in LONG_HISS_SPEEDS], 1),
                       pick('combos', [combo_centre], 2)]))
spec = dict(version='range_v2', about='PRIVATE recorded range suite. One explicit grid for desktop and phone.',
            cond_keys=list(KEYS), cond_values=dict(tone=['hum', 'whistle', 'na'], pitch=['bottom', 'home', 'top', 'na'],
            speed=['slow', 'normal', 'quick'] + list(LONG_HISS_SPEEDS) + ['na'], loud=['soft', 'normal', 'loud', 'na'],
            dist=['hand', 'table', 'across', 'na'], gap=['quick', 'normal', 'slow', 'na']),
            defaults=dict(rate=16000, channels=1, distances_cm=dict(hand=25, table=60, across=150),
                          speed_s=dict(slow=1.2, normal=.6, quick=.3), gap_s=dict(quick=.15, normal=.35, slow=.8),
                          hiss_s=dict(HISS_S)),
            analysis=dict(pre_roll_s=1, post_roll_s=.5, silence_s=1, no_sound_s=4,
                          tick_s=.05, floor_window_s=.5, open_db=8, close_db=5,
                          key_guard_s=.25, fs=16000, win=2048, hop=320,
                          f0_min_hz=35, f0_max_hz=2600, mpm_k=.88, clarity_min=.8,
                          min_level_db=-55, snr_db=[30, 20, 10, 5, 0, -5], long_hiss_ms=700),
            live=dict(meter_margin_st=1.5, meter_lines=19, initial_scale_hz=[35, 120, 2600]),
            phone=dict(max_s=1200), ratings=dict(min=1, max=5), blocks=blocks, profiles=profiles)
Path(__file__).with_name('range_v2.json').write_text(json.dumps(spec, indent=2) + '\n')

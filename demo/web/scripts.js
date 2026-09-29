// The demo scripts: the same steps every run. Step kinds:
//   {sound: 'rise'}                    one sound (the mic animates it, then it goes to the app)
//   {seq: ['click', 'click'], gap: 250} sounds as separate messages, gap ms of quiet between them
//   {sound: 'rise', hold: 2000}        a swipe, then a held hum for `hold` ms (hold-to-scroll; emulator only)
//   {mode: 'cursor' | 'gesture'}       the device's mode
//   {shell: 'wiki' | 'home' | 'vox'}   set the stage (open the article, go home, open Canti)
//   {reset: true}                      rules decider, gesture mode (the suite's reset recipe)
//   {wait: ms}                         quiet
// Every step may carry `after` (ms of quiet after it, default 700) and `note` (shown in the operator list).
// Cursor steps are timed moves: the cursor moves from the sound until the flat hum that stops it.
// A move is one {seq: [dir, 'flat'], gap} step (rise ▲, fall ▼; dip ◀ and arch ▶ reach an edge): as separate
// steps the page's pipeline wait alone outlasts the app's 2.5 s auto-stop, so the flat would never be what stops it.
// Slow moves go 0.15 screen heights/s; a move lasts about gap + 1420 ms (the flat's 1.36 s of mic frames plus
// latency, ±30 ms), so 1 ms of gap ≈ 0.36 px on the emulator's 2400 px screen; the shortest move is ~500 px and
// the longest 900 px (the auto-stop). The cursor keeps its position across modes and resets, so it lives at the top
// edge: a lone rise parks it there (auto-stop or edge) and every run starts from y = 0 with no drift. After an app
// restart it starts at the centre instead: park it with two lone rises in cursor mode (keys c, 1, 1, c).
// The page must stop at the same place every run for a timed move to find its link: the held hum auto-scrolls to the
// article's end, where the page clamps (the app ends a hold after 5 s). A Wikipedia donation banner stops that
// scroll short: close it once (its X) before the demo.
const CURSOR_GAP = 675;   // emulator, tuned 2026-09-27: top edge ▼ ~750 px onto the "Silence" card (y 654-842)

export const WIKI_URL = 'https://en.m.wikipedia.org/wiki/Humming';

const tour = (phone) => [
  { reset: true, note: 'reset: rules, gesture mode', after: 300 },
  { shell: 'wiki', note: 'open the article', after: 5000 },
  { sound: 'rise', note: 'rise → swipe up' },
  { sound: 'rise', note: 'rise → swipe up' },
  { sound: 'fall', note: 'fall → swipe down' },
  // emulator: one more swipe first, so the auto-scroll (capped at 5 s, slower when the host is busy) reaches the end
  ...(phone ? [] : [{ sound: 'rise', note: 'rise → swipe up' }]),
  phone
    ? { sound: 'rise', note: 'rise → swipe up' }
    : { sound: 'rise', hold: 5200, note: 'rise + held hum → auto-scroll to the end', after: 1200 },
  // emulator: one more swipe up, so the page surely sits at its end (no swipe down: it would leave the page a few
  // dozen px off from run to run)
  ...(phone ? [{ sound: 'fall', note: 'fall → swipe down' }] : [{ sound: 'rise', note: 'rise → swipe up to the end' }]),
  { mode: 'cursor', note: 'cursor mode', after: 900 },
  // phone (Flip 6, 2640 px: 396 px/s, Chrome's layout, no hold-scroll): same moves, untested there.
  { seq: ['fall', 'flat'], gap: CURSOR_GAP, note: 'fall → cursor ▼, flat → stops on "Silence"', after: 600 },
  { sound: 'pop', note: 'pop → click under the cursor', after: 3500 },
  { sound: 'rise', note: 'rise → cursor ▲ home to the top edge', after: 600 },
  { mode: 'gesture', note: 'gesture mode', after: 600 },
  { sound: 'rise', note: 'rise → swipe up' },
  { sound: 'hiss', note: 'hiss → back', after: 1800 },
  { seq: ['click', 'click'], gap: 250, note: 'click click → home', after: 1500 },
  { sound: 'dip', note: 'dip → swipe left' },
  { sound: 'arch', note: 'arch → swipe right' },
  { shell: 'vox', note: 'open Canti', after: 2500 },
];

export const SCRIPTS = {
  emulator: { title: 'Wiki tour', steps: tour(false) },
  phone: { title: 'Wiki tour (phone)', steps: tour(true) },
};

export function stepText(s) {
  if (s.note) return s.note;
  if (s.sound) return s.sound;
  if (s.seq) return s.seq.join(' ');
  if (s.mode) return `mode ${s.mode}`;
  if (s.shell) return s.shell;
  return JSON.stringify(s);
}

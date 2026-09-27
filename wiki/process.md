# How the work is run

VOX / Canti was built in about 24 hours, from 2026-09-26 05:27 to 2026-09-27 05:30 UTC. One coordinator session worked
with the user and ran up to about a dozen background agents at a time. This page covers how that works, the rules
everyone follows, and what happens when something is blocked or crashes. The agents are listed in
[agent-log.md](agent-log.md), and the decisions in [decisions.md](decisions.md).

## Roles

```mermaid
flowchart TB
  U[User] <-->|questions with options,<br/>free-text instructions| C[Coordinator<br/>main Claude session]
  C -->|prompt| G[Background agents<br/>general-purpose]
  C -->|fork from a transcript| F[Forks]
  G -->|sub-agents| S[Second-level agents<br/>e.g. label batches]
  G -->|SubagentHandback report| C
  F -->|report| C
  C -->|SendMessage: mid-task changes| G
  C --> APK[Builds the APK, commits,<br/>installs - with the user's OK]
  D[DeepSeek executors<br/>--yolo, ~/VOX only] -.->|wording banks, sweeps| C
```

- **The coordinator** is the main session. It:
  - asks the user questions, usually multiple choice with a recommended option;
  - writes each agent's prompt, relays the user's decisions to running agents, and reads their reports;
  - builds the combined APK and commits to git.
- **Background agents** each own one area and one directory (for example "Work ONLY under ~/VOX/android"). Each prompt
  gives:
  - the context and the goal;
  - the files the agent may touch;
  - what is off-limits;
  - how to report.

  Agents run JVM, Python or Flutter tests, but they do not build or install the phone APK.
- **Forks** inherit the coordinator's context and get a directive. They were used to replace agents that died, and for
  new design work that needed the whole conversation (voice cursor, build book).
- **Second-level agents.** Two Verdict agents started 62 sub-agents for parallel labelling and checking (see
  [agent-log.md](agent-log.md#second-level-agents-verdict)).
- **DeepSeek V4.1 executors** were allowed `--yolo` inside `~/VOX` only, for wording banks and training sweeps
  ([D018](decisions.md#d018)).
- **The librarian** (`.claude/agents/librarian.md`) keeps this wiki. It runs at the end of each work session and
  remembers its place in `wiki/.librarian-state.json`.

## Standing rules

These rules come from the user's answers and from the coordinator's prompts, which repeat them in every relevant agent
prompt.

### Permissions and tools

- Agents never run git. Only the coordinator commits, and only with the user's OK ([D050](decisions.md#d050),
  [D083](decisions.md#d083)).
- No sudo. Never store the user's password.
- Don't modify `~/jevlike` or `~/torch-rocm`, and never replace the ROCm build of torch.
- Keep at least 30 GB of disk free. The user cleans outside `~/VOX` themself ([D084](decisions.md#d084)).
- **Concurrent edits.** Several agents edit at once, so an agent re-reads a file before editing it and keeps backups in
  the scratchpad.
- Never print the Ollama key. It lives in `~/.config/vox/ollama_key` and in the app's Keystore-encrypted settings.

### Devices

- **Flashing.** Never flash the Pico without the user's OK ([D087](decisions.md#d087)). Address the Pico only by its
  `/dev/serial/by-id/…` path, and never touch `/dev/ttyACM0`, which is the phone.
- **APK.** One combined APK, built by the coordinator. Ask before installing it on the phone
  ([D124](decisions.md#d124), [D140](decisions.md#d140)).
- **Emulator.** Agents share one emulator (`emulator-5580`). Stop what you started.

### Phone-driving rules

These apply to the user's Z Flip ([D073](decisions.md#d073), [D104](decisions.md#d104), [D126](decisions.md#d126)).
- Drive it only when the user has cleared it, and say before taking over.
- Use `adb -s <serial>` with `--user 0`. Never unlock the phone.
- In social apps, use only scrolls, back and home ([D104](decisions.md#d104)):
  - no like, follow, post, DM or settings;
  - no pops, because a pop can tap;
  - click-click (home) is allowed in gesture mode ([D108](decisions.md#d108)).
- Mirror with scrcpy in view-only mode. Delete screenshots from the phone afterwards.
- Leave the phone as it was found: restore the volume and don't leave recordings on it.

### Privacy

- **Recordings.** The user's voice recordings stay local and out of git ([D035](decisions.md#d035)).
- **Z Flip data** (screens, dumps, phrases) goes to Opus agents only, never to DeepSeek or any other external model
  ([D063](decisions.md#d063), [D075](decisions.md#d075)). DeepSeek sees emulator screens only. See
  [training.md](training.md#privacy-boundary).
- **The wiki** may be public, so it contains no screen content, event-log contents, recording content, keys or
  third-party names ([D141](decisions.md#d141)).

## How blocked actions are handled

The permission system sometimes refuses a command. Examples:
- a tap on the phone;
- the phone-driving command for the social harvest;
- opening Instagram Reels by link;
- the Verdict lead's edit of the locked-test seal ("Security Weaken" / "Auto-Mode Bypass");
- the badge agent's in-place file edits.

When that happens:
1. **Don't work around it.** No retrying the same thing another way and no disabling checks.
2. **Report it.** The agent reports the block to the coordinator, and the coordinator tells the user what was blocked
   and why.
3. **The user decides:**
   - **The user runs it.** The coordinator explains the exact command or script, and the user runs it. Examples: the
     seal and SPLIT.md edits (09-27 03:35–03:41, [D120](decisions.md#d120)), the tap-to-wake `apply.sh`
     ([design-process.md](design-process.md#the-flow-mockup--sign-off--animate--apply)), and flashes and installs.
   - **Or the work is dropped.** The Z Flip social harvest was dropped this way ([D106](decisions.md#d106)).

When the user dismisses a question, that means "don't proceed". The coordinator waits
([D038](decisions.md#d038), [D073](decisions.md#d073), [D105](decisions.md#d105)).

## Crash recovery

On 09-27 at about 04:41 UTC the user's desktop shell died, and the running agents died with the session. The user said:
"bring back any agents that was working".

The coordinator forked a replacement for each one. Each fork's directive:
- names the dead agent's id;
- tells it to read the tail of that agent's transcript;
- tells it to check what is still running, such as orphaned training processes, and to finish the remaining work
  without redoing finished steps.

| Dead agent | Replacement fork | Outcome |
|---|---|---|
| a6f1962 (grammar) | a10ebe3 | Finished: pop gate, RVX, pop pop, typing and dictation; 386 tests |
| a419b79 (scroll/firmware) | a7b15d7 | Finished: glide-and-hold with guards, button tag |
| a81e006 (Verdict lead) | a19c44b | Adopted the orphaned cross-fit and train processes; still running |
| ae81972 (harvest) | a81a619 | Restarted the emulator and the view-only mirror; still running |
| aa60915 (Z Flip test) | a7c5b25 | Checked the phone read-only and did not resume, because the phone was still on the phone mic |

Lessons:
- Long jobs write their state to disk (logs, `runs.jsonl`, MANIFEST files), so a fork can pick up from files and not
  from memory.
- A fork re-checks live state (processes, adb servers, which build is installed) before acting.

## Sign-off steps

| Change | What happens first |
|---|---|
| Any visual design | Static mockups at real phone size, then the user's OK, then animation or build ([design-process.md](design-process.md)) |
| Phone install | The coordinator asks, and waits if a test round is running ([D140](decisions.md#d140)) |
| Pico flash | The user's OK; the user runs blocked flashes |
| Git commit / push | The user's OK and scope, e.g. "Case only, after doc fix" ([D083](decisions.md#d083)) |
| Locked-test or split changes | Written as a dated amendment in SPLIT.md before any data exists |
| Driving the phone | The user clears it each time |
| Downloads | Asked first when large ([D139](decisions.md#d139)) |

## How questions are asked

- **Format.** Most decisions come from multiple-choice questions, usually 1–4 at a time, each with a recommended
  option, a short explanation and sometimes an ASCII preview.
- **Free text.** The user often answers in free text; the coordinator follows what the text actually says and asks a
  follow-up if it is unclear (for example [D037](decisions.md#d037) after [D036](decisions.md#d036)).
- **Decisions made inside agents** are reported back and listed in [decisions.md](decisions.md#decisions-made-inside-agents).

# Native analysis and collaborative debugging — 2026-11-04

The update is implemented in $PROJECT and bound to the installed
Hermes skill. Analysis and job memory reside in the Hermes workspace.

## C/C++

Ghidra 11.4.2 was installed from the official archive with SHA-256 verification.
Files live in toolchain/ghidra_11.4.2_PUBLIC; installer: scripts/setup_native.py.

`apk-lab native JOB lib/ABI/name.so` saves ELF metadata, dependencies, C++-demangled
symbols and strings. With --decompile --function NAME --limit N it analyzes machine
code and exports C-like pseudocode for selected functions, addresses and incoming
static references. The Ghidra project is retained for continuation. Original C++
projects and stripped names cannot be guaranteed recoverable; recompilation of
arbitrary libraries from recovered pseudocode is not automated.

Implementation uses the official
[Ghidra headless interface](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/RuntimeScripts/support/analyzeHeadlessREADME.md)
and [DecompInterface](https://ghidra.re/ghidra_docs/api/ghidra/app/decompiler/DecompInterface.html).
Detailed guide: [native.md](../../skills/apk-reverse-engineering/references/native.md).

## Modes and control handoff

An independent working-mode choice supplements phone/emulator/no-runtime selection:

| Mode | Behavior |
| --- | --- |
| auto | Agent acts independently, bounds unproductive retries and preserves blockers |
| assisted | Agent acts independently and asks the user when a segment is unclear or unsuccessful |
| manual | User completes a stage; on their signal the agent investigates and hands control back |

work-mode, handoff and observe persist choices, turn owner and history. During a
human turn, normal tap/input/launch/install commands are blocked. Human ownership
in another job using the same serial is checked too. This guards controller
commands; the skill separately forbids bypass via raw ADB.

observe captures screenshot, UI hierarchy and recent logcat without installation,
launch or data clearing. Other sources are retained if one fails. Continuation
after “ready” starts from current state rather than install-test. Observation
captures current state; it does not automatically reconstruct all intervening user
actions. For long scenarios the skill recommends bounded log recording beforehand
and a description of the steps.

The emulator stays running during a human turn. --window shows it on the host
desktop; an active headless AVD is not restarted just for a window. Android viewing
and control through the upload browser were not added. A real desktop window was
not launched during this validation.

Methodology: [collaboration.md](../../skills/apk-reverse-engineering/references/collaboration.md).

## Memory and names for obfuscated code

remember JOB FILE.json saves evidence-backed procedures or aliases. knowledge JOB
retrieves experience for the exact original APK SHA-256 and verifies evidence-file
hashes. Records include source job, device and declared build hash; applicability
must be checked before replay.

Procedures distinguish user demonstration, independent reproduction and failure.
After a demonstration the agent may offer to retry the route; manual mode waits
for navigation permission. Failure remains in history and leads to a request for
help rather than endless repetition. This is file-based investigation memory,
without changing model weights.

Aliases retain original descriptors or library hash/ABI/RVA alongside readable
names and their basis: surviving name, code inference or runtime observation.
Strings, UI, logs, JNI, symbols and serialization fields help explain purpose,
but a name alone does not become a proven fact. Original identities are retained;
smali references are not automatically renamed.

## Diagnostic logs

instrument inserts a static helper without changing target-method registers.
Entry, returns and an exact instruction with source SHA-256 checking are supported.
Each marker writes APKLAB, an ID and a readable label. Original source, insertion
sites and hashes are saved. uninstrument rolls back a marker while checking that
subsequent edits will not be overwritten.

Builds with active markers receive diagnostic_only. Final patch completion is
blocked for them; diagnostic builds may be delivered separately with an explicit
label. Removing logging requires another build and final-artifact test. Markers
demonstrate execution; they do not capture request bodies by themselves.

Java argument/return and native templates were added at assets/trace-java.js and
assets/trace-native.js. They use [Frida API](https://frida.re/docs/javascript-api/),
preserve original calls and limit output. Value captures are disabled by default
and enabled selectively after type/ABI checks. No Frida server/Gadget was installed
on a user device; Android attach was not tested. These are additional templates
for a prepared environment, not a promise of injection into any APK on any phone.

The skill explains how to distinguish pre-serialization values, send attempts,
actual traffic and server responses; how to prepare logging before a difficult
manual scenario and preserve the app after a ready-state handoff.
See [instrumentation.md](../../skills/apk-reverse-engineering/references/instrumentation.md).

## Validation

- **36 unit tests passed**, covering turn ownership, shared devices, memory, safe
  insertion/rollback sites, diagnostic completion rejection, native input validation
  and refusal to restart a headless AVD merely for a window.
- Python py_compile, the SKILL.md validator and node --check for both Frida templates
  passed. The Ghidra Java script was compiled/executed by headless Ghidra itself.
- Real g++ built a test C++ .so. Ghidra recovered Lab::score and a JNI-named wrapper;
  pseudocode contained the original x * 3 + 7 formula. Subsequent selection reused
  the saved project. [native-validation.json](../validation/native-validation.json).
  This is host x86_64 ELF analysis, not Android JNI execution or an ARM runtime test.
- On a real Android API 34 AVD: handoff blocked a tap, observe preserved the current
  screen, the instrumented APK built/installed and its marker appeared in logcat.
  After marker removal a clean build launched and passed the Before patch ->
  After patch UI comparison with screenshots.
  [collaboration-validation.json](../validation/collaboration-validation.json).
- The installer updated the AGENTS.md APK block and existing skill link. doctor
  detects the native decompiler. Transfer server and emulator were stopped afterward.

All runtime validation used a synthetic app. No physical phone, actual human
demonstration or Telegram conversation was exercised. Temporary test PNGs were
removed with the isolated job; proof retains hashes and UI text. Normal user jobs
retain downloadable screenshots.

Pre-change snapshot: .history/20261104-150941-native-collaboration/before.tar.gz.
The earlier audit documentation remains historical; this file describes the
subsequent extension. Main user guide: [README.md](../../README.md).

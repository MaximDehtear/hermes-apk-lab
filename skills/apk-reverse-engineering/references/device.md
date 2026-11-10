# Visual Android testing on a phone or virtual device

The user's model can see images. Use the built-in vision tool to attach screenshots
to the conversation, then reason about the actual rendered interface.

## Connect

Ask the user once where to test: physical phone, virtual Android or no runtime
testing. Record with `apk-lab test-target JOB phone --serial SERIAL`,
`apk-lab test-target JOB emulator`, or `apk-lab test-target JOB none`.
The last option leaves a built patch explicitly untested; do not create a
runtime verdict from compilation alone.

`apk-lab device list` shows serials and authorization status. The user enables USB
debugging, plugs the phone into the Hermes host and accepts its RSA prompt.
Select explicitly: `apk-lab device select JOB SERIAL`. Never select a different
phone silently. For Android Wireless debugging, pair locally with `adb pair IP:PORT`
and the code displayed on the phone, then `apk-lab device connect IP:CONNECT_PORT`.
Pairing and connection ports differ. Do not expose ADB to the public internet.

For the virtual option, `test-target JOB emulator` starts the project-managed
Android API 34 x86_64 AVD headlessly by default and selects its ADB serial automatically.
If the emulator is not installed, run `python3 scripts/setup_emulator.py` in the
project, then retry. Setup requires KVM, free disk space and Android SDK licenses.
If KVM access fails, inspect /dev/kvm permissions, current process groups and host
virtualization support. Group membership changes need a new login/session to affect
the running process. A temporary administrator-managed ACL is an option where
appropriate, but can disappear when the device node is recreated; verify access
from the actual Hermes process. Do not assume a permission change fixes missing
hardware or nested-virtualization support.
The AVD data lives under `<Hermes workspace>/apk-lab/.emulator/avd` and persists
across sessions. `finish JOB` stops the managed VM when no other active job uses
it. `apk-lab emulator status|stop` handles interrupted or abandoned sessions.
No physical phone is changed in emulator mode. Both targets use the same
screenshot, `vision_analyze`, action, install-test and evidence commands.

## Working mode and human control

Read [collaboration.md](collaboration.md) and persist work-mode independently of
the chosen target. Action/install commands reject an unset mode or a human turn.
Use observe for a current screenshot, hierarchy and recent logcat without launch.
When the user reaches a difficult stage, acknowledge their ready message, hand
control to agent and inspect in place. Do not install-test or restart to continue.
For temporary logging see [instrumentation.md](instrumentation.md).

## Observe and act

1. `apk-lab device screenshot JOB --label before-open-settings`
   returns an absolute PNG path, original width/height, device serial and focused
   window. It also publishes the screenshot for user confirmation automatically.
2. Call `vision_analyze(image_url="<path>", question="Describe the current screen
   and locate the requested control. Give coordinates in ORIGINAL image pixels.")`.
   The current multimodal Hermes model receives the image natively when supported.
3. Optionally `apk-lab device hierarchy JOB` for Android nodes/bounds. Custom
   rendered views may have no useful accessibility tree. Parse the saved XML by
   attribute name, not attribute order. The CLI's summarized node list omits some
   attributes such as focused; inspect the raw XML when needed.
   A soft keyboard can cover otherwise valid bounds, and text/key events depend
   on focus and IME behavior. Verify the focused view and actual field content,
   dismiss the IME when it obstructs a control, and capture again after input.
   Do not assume DPAD/ENTER or a tap reached the intended view.
4. Perform ONE action, e.g.:
   - `apk-lab device action JOB tap 540 1200`
   - `apk-lab device action JOB swipe 500 1500 500 500 400`
   - `apk-lab device action JOB key back`
   - `apk-lab device action JOB text "search query"`
   - `apk-lab device action JOB launch package.name/.MainActivity`
5. Capture a new screenshot and verify the transition. If vision downscaled the
   image, convert coordinates using the reported original dimensions. For crops,
   also add the crop origin. Never reuse coordinates after rotation/layout changes.
   When vision and hierarchy disagree, recapture and inspect focus, scrolling and
   coordinate scaling. Zero/empty bounds are not valid tap targets. Neither source
   is always authoritative; verify the actual transition after each action.
6. `apk-lab device logcat JOB` captures logs without clearing the phone's buffer.
7. Bottom-nav items exist only while the host activity is focused. After a list row
   opens a child Activity, a tap on remembered nav coordinates lands on nothing and the
   screenshot looks unchanged — check the focused window/hierarchy first, then go back or
   start the host activity explicitly before tapping nav items. Never report a navigation
   transition you did not confirm on the next capture.

Use this loop to explore an app, understand user flows or replay a requested test.
Track visited screens and unresolved questions in analysis/notes.md. Do not perform
payments, submit forms with external effects, erase data, grant unrelated permissions
or change accounts merely to explore. Follow the user's requested scenario.

Screenshots cannot reveal secure FLAG_SECURE surfaces. If capture is blank, record
that limitation and use available hierarchy/log evidence; never invent the UI.
ASCII text input is supported; use the on-screen keyboard for other scripts.

## Read persisted state at runtime

When a verdict depends on storage, compare pre/post snapshots AND the UI consuming
that state. Record package, build hash, device, timestamps and triggering action.
A preference key may predate the test or have multiple writers; key presence alone
does not prove a specific branch executed. AppOps shows operation metadata, not
proof of a particular method, complete execution or transmitted payload.

`run-as PACKAGE` requires a suitable debuggable app. Check availability and exit
status first. If unavailable, record the limitation; do not assume root or modify
the production deliverable silently. A separate diagnostic build with debuggable
set can permit inspection, but it changes behavior/security properties: label it,
keep its hash separate, and repeat the final scenario on the delivered build.
On a disposable managed AVD, root may be available depending on the image; verify
it before using it. Do not root or change settings on the user's phone implicitly.

Stream files through `adb exec-out run-as PACKAGE cat RELATIVE_PATH` to a host
file under tests/; check return code and content before parsing. SQLite databases
may have committed data in WAL files. Use a consistent snapshot/backup approach
or a quiesced app with matching DB/WAL files; never silently read an incomplete
copy as current state. Query copies read-only and retain source hashes. Avoid
exporting unrelated private data in the user-facing report.

For location-dependent experiments, distinguish injected coordinates, provider
state, delivery to the app and any subsequent transmission. A successful emulator
console command does not prove the app received the fix. Inspect provider-specific
state and available app observations; dumpsys formats and counters vary by release.
If delivery cannot be established, record the analysis as inconclusive rather than
inferring app behavior from the console response.

Permissions and roles depend on Android version/OEM, policy and user consent.
Inspect the actual capability/error on the selected device; do not assert all
Android 10 systems lack `cmd role`. Keep scenarios needing unapproved permission,
role or account changes inconclusive rather than forcing the environment to pass.
When an experiment requires permission changes, record the installed package,
requested permissions and before/after grants. Check whether the permission can be
granted on that target; runtime grants do not reproduce every legacy permission,
AppOps, role or background-access behavior.

## Install a build and compare

`apk-lab device install-test JOB /absolute/builds/r002/patched.apk` installs using
`adb install -r`, launches and saves a receipt. It accepts verified builds under
this job's builds/ directory. Compare a rebuilt baseline (`build JOB --baseline`)
with the patched build to distinguish rebuild effects from edits, but also preserve
original-app observations: a resigned baseline may behave differently from the
original. Matching signing identities can permit in-place updates; verify retained
state instead of assuming login/preferences survive every app update. This command
never uninstalls an original app.
Signing conflicts are returned as blockers. Ask how the user wants to preserve
their existing app/data before any uninstall — for a game, state plainly that
uninstall wipes saved progress. The install smoke test is not proof
that the requested behavior works.

Install restrictions depend on Android release and device policy. For example,
Android 14 blocks new installs targeting below API 23 and documents a test-only
ADB bypass; see [Android 14 installation behavior](https://developer.android.com/about/versions/14/behavior-changes-all#minimum-target-api-level).
Inspect the actual failure and available options. Prefer a compatible disposable
runtime that preserves the original APK. A changed targetSdk or native stub creates
a diagnostic variant with different behavior, not an equivalent original-app test.
Record its hash, changes and limitations; see native.md for ABI constraints.

For split sets see [advanced.md](advanced.md). The automated install-test handles
a verified standalone build only. A missing-split error needs the complete package
set; copying native libraries into base is not a general repair. Resigning can
break signature-dependent behavior. Record the actual error and its evidence;
do not declare all licensed apps permanently untestable from a class name alone.

Replay identical inputs/actions before and after the change. Save screenshots with
meaningful labels and `--build-sha256 SHA` for the corresponding build. For the
original APK use its input SHA. Keep labels and hashes accurate; do not assign a
patched hash to a screenshot of the original app.

Create tests/<scenario>.json with:

```json
{
  "scenario": "Open settings and check the requested default",
  "expected": "The requested default is displayed and survives reopening",
  "observed": "Describe only what the screenshots and replay showed",
  "verdict": "passed",
  "before": "/absolute/job/tests/screenshots/before.png",
  "after": "/absolute/job/tests/screenshots/after.png",
  "build_sha256": "SHA256 of the exact signed APK under test",
  "steps": ["Open app", "Open settings", "Inspect value", "Reopen settings"],
  "logs": ["/absolute/job/tests/logcat.txt"]
}
```

Register with `apk-lab device evidence JOB /absolute/job/tests/<scenario>.json`.
Verdicts: passed, failed, inconclusive. A passed result requires an install/launch
receipt for that signed APK on the same device. Capture with
`apk-lab device screenshot JOB --label LABEL --build-sha256 SHA`; the evidence
validator requires its matching metadata and PNG hash. Raw screenshots can still
be retained as observations, but lack this controller-generated metadata.
Use absolute paths to avoid ambiguity: evidence JSON must be inside the job,
finish's report must be under analysis/, and before/after PNGs must be separate
captures under tests/screenshots/. Relative paths resolve from the invoking
process's current directory, not automatically from the job.
Both remember record types require evidence files. An alias also requires symbol,
label and basis (named/inferred/runtime); a procedure needs name, precondition,
result (demonstrated/reproduced/failed) and nonempty steps. See collaboration.md.
If the environment prevents exercising a scenario, record it as inconclusive;
if an adequately exercised scenario contradicts the expected behavior, record it
as failed. Screenshots remain downloadable for either result.
For nonvisual behavior include the relevant runtime trace and explain why the
screenshot alone is insufficient. Deliver the two original PNGs with the report
and APK; `[[as_document]]` prevents Telegram image recompression.

## Coverage and cleanup

Record Android version/API, ABI, display dimensions, locale, permissions, app data
state and network conditions for reproducibility. On the managed x86_64 AVD,
ARM-only libraries, hardware features, Play dependencies or attestation may prevent
a representative run. Report that specific limitation and offer a suitable phone
when needed; an emulator failure is not automatically a patch defect.

Completion stops the managed emulator after its last active job. For interruption
or an unresolved blocker, check other jobs before stopping a shared AVD. The file
server has its own lifecycle: stop after input transfer if unused, reopen for
results, then stop after delivery or let its idle timer expire. Stopping services
does not delete saved screenshots, APKs or investigation state.

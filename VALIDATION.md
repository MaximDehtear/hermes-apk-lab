# Validation

## Fresh installation review

The previous short instructions assumed an existing Android SDK. Added
scripts/setup_sdk.py to create the SDK directory, bootstrap the pinned command-line
tools and install platform-tools, build-tools 36.0.0 and platform android-34.
License review is interactive. INSTALL.md documents Linux dependencies and WSL2
networking, USB and KVM restrictions. install.py now checks the configured local
backend even with an explicit workspace and validates the port.

The SDK bootstrap unit test simulates a missing SDK and verifies package installation
and license ordering without requiring KVM. A second test verifies that explicit
workspace cannot bypass a non-local backend. No clean OS VM or WSL2 end-to-end
installation was performed; these tests do not prove downloads or host compatibility.


## Native and collaborative debugging extension: 2026-11-04

- Full unit suite: **36 passed**. Adds mode/turn ownership (including shared-device
  conflicts), in-place observation with partial failures, scoped evidence memory,
  reversible smali markers, stale/unsafe insertion rejection, diagnostic delivery
  rejection, native-input validation and preservation of an active headless AVD.
- `python3 -m py_compile apk_lab/*.py scripts/*.py tests/*.py`: passed.
- Skill validator and `node --check` for both Frida templates: passed.
- `python3 scripts/validate_native.py`: passed with actual g++ and Ghidra 11.4.2.
  Reconstructed C++ function and JNI-named wrapper, matched the arithmetic, reused
  the saved project. Proof: [native-validation.json](native-validation.json).
  This is static analysis of a host x86_64 ELF, not an Android JNI runtime test.
- `python3 scripts/validate_emulator.py --output collaboration-validation.json`:
  passed on the actual API 34 AVD. Human turn blocked a mutation; observation
  preserved the current screen; injected marker appeared in logcat; marker removal
  and a clean final build passed the before/after scenario. Emulator stopped.
  Proof: [collaboration-validation.json](collaboration-validation.json).
- Graphical emulator window and live Android Frida hooks were not exercised.
  Native analysis was not validated against every ABI, packer or protection.
  The handoff test used a synthetic ready signal, not an actual human/Telegram run.

See [extension report](NATIVE-COLLABORATION.md) for current capabilities and limits.


## Current audit: 2026-11-04

- `python3 -m unittest discover -s tests -v`: **25 tests passed** (19 existing,
  6 new). New coverage: multidex recon, implicit exported attributes, exact method
  and field references, comments/string/partial-name exclusions, source hashes,
  malformed manifest, source path escape, changed original, failed signature,
  stale job verification and refusal to install/deliver a modified build.
- Explicit `python3 -m py_compile` for touched Python modules and
  `python3 -m compileall -q apk_lab scripts tests`: passed.
- Skill creator `quick_validate.py`: passed. Installer re-applied the existing
  skill symlink and refreshed only the managed APK block in workspace AGENTS.md.
- `doctor`: no missing required tools; toolchain remains inside this project,
  analysis data remains in `/home/user/hermes_workdir/apk-lab`.
- `python3 scripts/validate_toolchain.py --output validation-2026-11-04.json`:
  **passed with real tools**. Recon found the fixture component and both methods;
  xrefs found its exact TextView.setText call with a matching source hash. Built
  and signed baseline/patch, verified signature/alignment/current hash, re-decoded
  the final signed artifact and confirmed the changed label. Original unchanged.
  Proof: [validation-2026-11-04.json](validation-2026-11-04.json).
- `python3 scripts/validate_emulator.py --output emulator-validation-2026-11-04.json`:
  **passed on the actual managed API 34 AVD**. Baseline and patched APKs passed the
  new integrity gate, installed and launched; UI changed from `Before patch` to
  `After patch`. Captured 1080x2340 PNGs and accepted the scenario evidence.
  Removed only the synthetic fixture app and stopped the emulator afterward.
  Proof: [emulator-validation-2026-11-04.json](emulator-validation-2026-11-04.json).
  Validation fixtures/screenshots were temporary; the proof retains PNG hashes
  and observed UI text. Normal user jobs retain their original screenshots.
- Final service check: managed emulator stopped; transfer service stopped,
  configured bind still `0.0.0.0:9099`, exposure `direct`.

The current run did not repeat the 210 MiB transfer, change public networking,
use a physical phone, or run an end-to-end Telegram/model conversation. Those
limits are distinct from the real rebuild/emulator checks above. Local verification
records enforce consistency; they do not independently establish semantic behavior.

## Historical validation (preserved)

Verified on this host, 2026-10-24. Tests use isolated temporary workspaces and
synthetic APKs; they do not install applications on a user's phone.

## Automated checks

- `python3 -m unittest discover -s tests -v`: 19 tests passed.
  Covers upload resumption, incomplete input rejection, token rotation,
  cross-origin rejection, archive traversal, file publication boundaries,
  concurrent state updates, original hash checks, device command quoting,
  screenshot/evidence binding, authenticated PNG previews, public URL validation,
  detached service restart and automatic idle shutdown. The added tests check
  explicit target selection, refusal to act when testing is skipped, publishing
  an untested patch honestly, stopping a shared emulator after its last job,
  and complete Telegram link formatting.
- `python3 -m compileall -q apk_lab scripts tests`: passed.
- Skill creator `quick_validate.py`: passed. Hermes lists the linked
  `apk-reverse-engineering` skill as enabled.
- Embedded browser JavaScript passes `node --check`.

## Real toolchain and transfers

`validation.json` records the completed toolchain run from 2026-10-23:

- Created a synthetic Android application and decoded it with Apktool and JADX.
- Built and signed a baseline, changed a smali string, rebuilt and verified the
  changed string in the resulting DEX. Original input remained unchanged.
- Signature verification and ZIP alignment passed for the patched APK.
- Uploaded 220,203,188 bytes (about 210 MiB), resumed at an intermediate offset,
  and matched the complete file's SHA-256.

Reproduce with `python3 scripts/validate_toolchain.py --large-upload`.

`transfer-validation.json` records the historical direct server check:

- Bound to `0.0.0.0:9099`, accessed through `http://192.168.0.155:9099` from
  this host, without any tunnel or proxy service.
- Uploaded 12,583,171 bytes through the authenticated chunk API; unauthenticated
  access returned HTTP 403. Stopped the temporary service successfully.
- Also started the service in the installed Hermes workspace, checked `/health`,
  and stopped it. The installed default is now `direct`.

Reproduce with `python3 scripts/validate_transfer.py` while port 9099 is free.

The `open --format telegram` smoke check generated a complete 94-character
URL containing both `#job=` and `&token=`. That token authenticated an actual
HTTP status request for the new job. The temporary transfer server was stopped.
The installed Hermes terminal redactor was also checked with a synthetic URL;
it preserved the URL fragment, so the skill must copy the complete output line
to Telegram rather than abbreviating the address.

## Real Android Emulator

The official Android Emulator and API 34 Google APIs x86_64 image are installed
in the existing Android SDK. The managed AVD lives in the Hermes workspace.
KVM acceleration passed the emulator's `-accel-check` command.

`emulator-validation.json` records an end-to-end runtime check on the AVD:

- Booted the headless Android system and connected through ADB as `emulator-5580`.
- Built, signed, installed and launched a baseline fixture app. Its UI hierarchy
  showed `Before patch`; a 1080×2340 PNG screenshot was captured and published
  in the isolated test job.
- Rebuilt the app with the patched smali text, installed and launched the exact
  signed APK. The UI hierarchy showed `After patch`; another PNG was captured.
- The scenario evidence validator accepted both screenshots and the install
  receipt for the patched SHA-256. The fixture app was removed and the managed
  emulator stopped after validation.

Reproduce with `python3 scripts/validate_emulator.py`. It uses synthetic APKs
and an isolated test job, then stops the emulator on completion.

## Not yet exercised

- No physical Android phone was connected. ADB actions, screenshot metadata and
  scenario evidence have unit coverage and a successful emulator runtime check.
  Physical-device behavior remains untested.
- The complete Telegram conversation and model-driven patching loop have not
  been run end to end. The skill is installed and discoverable, and its
  instructions use the existing Hermes terminal and vision interfaces.
- An external internet client has not tested this host. `0.0.0.0` enables
  listening on all interfaces but does not establish router/firewall reachability.
  Set `public_base_url` to the user's external address and route TCP 9099 to this
  host before describing an internet link as reachable.
- The synthetic APK does not establish compatibility with every obfuscator,
  split package, native framework or anti-tamper implementation.

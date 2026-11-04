# Specialized investigation routes

Use only the routes relevant to the goal. These are investigation methods, not
claims that the basic controller automates every native, split or protected app.

## Split packages and installed-app acquisition

For a selected phone, `adb -s SERIAL shell pm path PACKAGE` lists installed APK
paths. Pull every listed base/config/feature APK into the job's input/pulls/,
record source package/version, device and hashes. Do not silently drop splits.
The controller accepts one input per job; a zip of the complete set preserves the
relationship. `inspect` lists nested packages; monolithic decompile/build refuses
split archives. Analyze safely extracted packages separately within the job,
using project toolchain binaries and separate output directories. Validate archive
entries before extraction (`pipeline.archive_info` rejects traversal/symlinks).

Required ABI, density, language and feature splits vary by application/device.
A manual split install route needs compatible package/version metadata, a common
signer and `adb install-multiple`; it is outside the current automated build and
scenario pipeline. Preserve errors and report that limitation. Copying .so files
into base is not a general merge: resources, split IDs, dependencies and features
also matter. Do not generalize one OEM error to every device.
[Android App Bundles](https://developer.android.com/guide/app-bundle) describes
configuration and feature APK delivery; [ADB](https://developer.android.com/tools/adb)
documents installing multiple APKs.

## Native, Unity, Flutter and React Native

Identify ABI and framework from inventory, actual libraries and startup paths.
Check available tool versions before claiming an analysis capability.

- JNI: trace Java native declarations, library loading, exported Java_* symbols
  and RegisterNatives tables. Match addresses to the exact library hash and ABI.
  The built-in `native --decompile` Ghidra route can reconstruct control/data flow; verify types
  and boundaries with runtime observations where possible. Symbols alone are
  not proof of a reachable behavior.
- Unity/IL2CPP: look for UnityPlayer, libil2cpp.so and matching global-metadata.dat.
  Metadata versions and stripped/encoded artifacts affect available tooling.
  Java/C# bridge event names are useful anchors, but string presence does not
  prove the receiver or semantics. Trace producers, consumers, payload fields,
  ordering and native state before considering a bridge patch. There is no
  universal rule to patch Java instead of native code.
- Flutter: identify libflutter/libapp, Dart assets and method channels. Kotlin/Java
  may only host the UI; decompiling the wrapper does not recover Dart AOT logic.
- React Native: identify bundle/Hermes bytecode and native modules; use a matching
  bytecode/tool version. Trace the JS/native boundary instead of assuming a text
  bundle is present.

Ghidra has a pinned project installer and `native` command; see [native.md](native.md).
Frida remains optional and requires a prepared device/runtime; see
[instrumentation.md](instrumentation.md). Record missing tools,
architecture/version limitations and partial output. Instrument only the selected
target within the authorized task; preserve scripts, module hashes and logs in
evidence/. Hooks can perturb timing/anti-tamper behavior; distinguish instrumented
observations from the uninstrumented deliverable. See
[OWASP dynamic analysis](https://mas.owasp.org/MASTG/techniques/android/MASTG-TECH-0026/).

## Persistent state and gates

Trace preferences, database defaults/migrations, in-memory caches and every
relevant writer, including network responses and lifecycle callbacks. A value of
0 can mean unlimited, disabled or zero quota: derive its meaning from consumers.
Use exact field xrefs and separately search storage keys and setters. Inspect
shipped databases read-only; record schema and row context, not just matching
numbers. Client display state and server authority can disagree.

For privacy, consent, feature or licensing gates, map source of state, validation,
reset paths and error behavior. Scope modifications to the authorized objective;
the presence or absence of verification does not establish authorization. Measure
what a changed signing identity actually breaks before claiming a blocker. A
license or integrity class name alone does not prove a re-signed app cannot run.
Use a suitable test environment/build/account where available, and report limits.

## Privacy and network egress

Trace source -> transform -> queue/storage -> serializer -> transport -> endpoint,
with consent/permission/config gates and triggering conditions. Distinguish raw
content, hashes, identifiers and aggregate values. Search all DEX and relevant
native code when JADX is partial. Separate app and SDK ownership, but still
include SDK behavior in the app's overall data flow.

A URL or sensitive API call is a candidate, not proof of transmission. No direct
read reference is not proof that an identifier is dead code: reflection, JNI and
serialization can consume it. Decode constructed endpoints only from actual
operations, recording the derivation. Note queued data and retries when evaluating
an opt-out. Do not assert collection or deletion semantics without tracing them.

Runtime confirmation should include reproducible actions, time window, network
conditions, app/build/device identity and evidence tied to the request/payload.
Log markers show that a marker executed, not that every alternate transport was
blocked. Negative claims must be bounded: "No request observed during scenario X
with conditions Y" rather than "the app sends nothing". Review alternative paths,
remote configuration and background flushes. Screenshots alone cannot prove egress.

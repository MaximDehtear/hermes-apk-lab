# Investigation and patch workflow

## 1. Scope, provenance and a reproducible baseline

Translate the request into a testable condition: given starting state and action,
what must change, what must stay unchanged, and what observation would disprove
success? Reuse the saved goal rather than expanding into an unrelated full audit.
Record package/version, input SHA-256, signing certificate, SDK/ABI, chosen target,
tool versions and missing splits. Never edit input/original.apk.

Run `inspect JOB`, `decompile JOB`, then `recon JOB`. Inspect writes inventory and
signature/badging logs. Decompile writes editable decoded/apktool and readable
Java in decoded/jadx; analysis/decompile.json records partial JADX failures.
Recon writes analysis/recon.json: components, attributes, intent filters,
permissions, smali/method counts, native declaration samples and framework hints.
It describes the CURRENT decoded tree; rerun after changes and keep baseline
reports separately when comparing versions. Implicit exported attributes require
component/API/targetSdk interpretation; absence is not automatically false.

A missing-framework decode error can require vendor resource packages. Determine
which framework and firmware version the input expects; do not infer a vendor or
path from the numeric resource package ID alone. Obtain matching resources from
an appropriate device or firmware and retain their hashes/provenance in the job.
Install them with the configured Apktool executable, for example:

```bash
apktool if /absolute/job/analysis/vendor-framework.apk -p /absolute/job/decoded/framework
apk-lab decompile JOB
```

Use the executable reported by doctor if it is not on PATH. The controller retains
failed decode trees and records successful retries in analysis/decompile.json;
do not manually mark a partial decode successful. Inspect any partial smali before
using it and state coverage gaps. If matching resources are unavailable, continue
with independently usable evidence and record the resource-analysis limitation.
See [Apktool frameworks](https://apktool.org/wiki/in-depth/frameworks/).

Keep these living documents small enough to resume without reading all sources:

| File | Content |
| --- | --- |
| analysis/app-map.md | Components, screens, entry points, storage, network, SDKs, native boundaries; evidence links |
| analysis/notes.md | Known facts, competing hypotheses, confidence, failed experiments, next discriminating test |
| evidence/ | Exact source extracts, descriptors, commands, observations and timestamps |
| patches/CHANGELOG.md | Intended change, rationale, affected sites, invariants and rollback |
| tests/ | Preconditions, actions, logs, screenshots, build/device hashes and verdict |

Use `checkpoint JOB --next 'specific next experiment'` after meaningful progress.
On resume check hashes, existing logs and latest notes before repeating expensive
work. SQLite is authoritative; do not edit state.json. Do not ingest entire
Java/smali trees into model context. Search first, inspect narrow contexts.

Load `knowledge JOB` after import/resume. Keep original descriptors alongside
readable aliases, record the basis and revise disproved names. Native libraries
use the separate [Ghidra route](native.md). UI steps and human handoffs follow
[collaboration.md](collaboration.md); a ready message resumes observation in place.

## 2. Architecture and goal-directed tracing

Map manifest entry point -> screen/resource -> listener/callback -> domain method
-> state read/write -> storage/network/JNI boundary. Separate app-owned logic from
bundled SDKs. Include lifecycle callbacks, background workers, error/fallback
branches, threading and remote configuration when they affect the goal.

Use `rg -n` for anchors (resource IDs, keys, actions, endpoints); then use exact
references rather than raw substring counts:

```bash
apk-lab xrefs JOB 'Lpkg/State;->enabled:Z'
apk-lab xrefs JOB 'Lpkg/Settings;->refresh()V'
```

Each xrefs JSONL row records file, line, enclosing class/method, instruction,
read/write/call and source SHA-256. The adjacent .meta.json records symbol,
original hash, count and limitations. All smali* trees are scanned. This covers
explicit instruction references only: inheritance/virtual dispatch, reflection,
JNI and dynamically loaded DEX require separate tracing. No matches does not
establish absence. `invoke-polymorphic` and `invoke-custom` are not resolved.

JADX variable names and reconstructed control flow can be misleading. Confirm
branches, constants, exception handlers and call signatures in smali. If reflection
names are encoded, trace the decoder and its call sites to determine the transform,
input and resulting descriptor. Do not assume a prefix, encoding or target API from
the string's appearance. Decoding a name alone does not prove invocation. Trace both
producers and consumers of a value; distinguish a field from its persisted key.
Check all relevant reads, writes and reset paths, not just the visible getter.

For each hypothesis record: supporting evidence, alternative explanation,
disconfirming experiment and result. Label findings as static-confirmed,
runtime-observed, inferred or unresolved, with confidence separate from severity.
Method counts indicate coverage, not understanding. Name unexamined components.

## 3. Minimal patch and signed-artifact verification

1. Capture original behavior where possible. Build an unchanged baseline with
   `build JOB --baseline` before editing. This saves patches/baseline-source.zip
   and analysis/baseline-files.json. Test the rebuilt baseline on the selected
   target to separate resigning/rebuild effects from the requested change.
2. Record exact methods/resources, rationale, expected effect and regressions in
   patches/CHANGELOG.md. Preserve unrelated behavior. Inspect an actual diff;
   failed builds remain evidence, not a reason for broad speculative edits.
3. Edit decoded/apktool. For smali check register liveness/types, wide register
   pairs, parameter aliases, branch targets and try/catch ranges. `iget/iput`
   use format **22c**, with two 4-bit registers (v0..v15); `sget/sput` use **21c**.
   Growing .locals changes the physical registers behind pN. Use suitable move
   instructions and a free low register only after checking liveness; do not
   overwrite a live value. Invoke argument encoding and /range have separate
   constraints: ordinary invoke instructions encode at most five argument words
   (wide values use two); /range needs a contiguous register interval. Check both
   the argument count and register index limits. When inserting a
   guard into an existing branch, keep the instructions that establish the register's
   type (re-fetch assignments included); a fuzzy patch anchor that drops them leaves a
   wrong-typed register for the following call. Verify every hand-written invoke
   descriptor against the platform API: a wrong overload (e.g. a 3-String `Log.d`)
   compiles but throws NoSuchMethodError at runtime.
   When gating on a boolean-returning method result, `if-eqz` jumps on FALSE and
   falls through on TRUE; `if-nez` does the reverse. Select the branch from the
   observed predicate and intended control flow, not a presumed meaning of TRUE.
   Walk both outcomes before building; compilation cannot detect an inverted policy.
   See the [AOSP bytecode specification](https://source.android.com/docs/core/runtime/dalvik-bytecode).
4. `build JOB` creates a revision with source hashes, patch.diff, signed APK and
   verification.json. zipalign precedes signing; signature and alignment are
   verified. Publish diffs as .patch or .txt. A signing identity change can affect
   updates, permissions, integrations and integrity checks.
5. Re-decode the final SIGNED APK into a new directory under builds/rNNN/ using
   the installed Apktool. Compare semantic invariants for every intended method:
   full descriptor, guard/branch, values, call order and unaffected paths. Do not
   overwrite the working tree or compare only line counts/label names: disassembly
   can change formatting and labels. Verify resources in the built artifact too.
6. Replay the same scenario before/after on the chosen target. Include the reset
   path that could undo the change: reopen screen, background/foreground, restart,
   refresh or network response as applicable. Cover a neighboring unchanged path
   and an error/negative case when relevant. For a security gate, test BOTH
   directions on the final signed build (denied case and the positive control that
   the intended feature still works) — one direction alone does not prove the
   branch is correct. Read device.md for evidence capture.

Install-test and finish now reject missing/failed verification or an APK whose
current hash differs from its build record. This detects accidental modification;
local JSON records are not a tamper-proof attestation. Keep manual instrumentation
builds separate from the final deliverable and test the final hash.

## 4. Deliver and preserve limitations

Use [report-template.md](report-template.md). A screenshot proves visible state,
not persistence, network silence or all branches. Corroborate nonvisual claims.

`finish JOB --report /absolute/analysis/REPORT.md --kind analysis` delivers an
analysis. `--kind patch` requires the exact signed build and passed scenario, or
an explicit `test-target JOB none` choice, which marks it untested. A phone or
emulator blocker must remain inconclusive; do not silently switch to none.
An unfinished result can be published explicitly with its limitations and a
checkpoint. Completion stops the managed emulator when no other active job uses
it. Delivery links reopen the transfer server; stop it after transfers or allow
the configured idle shutdown.

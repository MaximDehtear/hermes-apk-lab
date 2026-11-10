# Native experiment engineering transfer — 2026-11-10

## Source review and boundaries

Reviewed the latest relevant Hermes investigation, including its continued history
(2,259 stored messages), tool-call inventory, native research artifact inventory,
final conclusions and local host-harness notes. Background scheduled jobs were
excluded from the research history. The history contained 834 terminal calls,
140 file writes and 64 patches; failed terminal results were retained in the review.
This is a method review, not independent revalidation of every historical claim.

No transcript, app-specific constants, recovered inputs, keys, addresses, binaries,
signatures or challenge solution are included. Existing uncommitted skill edits
from earlier work were preserved locally and excluded from this change.

## Methods generalized

| Historical experience | General mechanism or decision |
| --- | --- |
| Host execution made some native computations observable | Fresh-process protocol for researcher-built harnesses; ELF preflight before selecting a loader strategy |
| Long-lived harness state eventually failed | One process per case/repeat; classify signals/timeouts separately, reproduce isolated inputs |
| CPU emulation repeatedly faulted on absent environment | Explicit maps/registers, instruction/time limits, fault observations; no silent memory filling |
| Instrumentation races and process lifecycle failures | Bounded selected-device attach, logged script errors/detach, version/ABI prerequisites; no unlimited retry loop |
| Constructors and relocation state affected results | ELF segments/imports/relocation inventory and explicit assumptions; record initialization stages and mapping coordinates |
| Dumps and controlled changes revealed runtime data | Binary Frida messages with hashes, streaming byte comparison, stage/alignment guidance |
| Algorithm guesses failed without exact input modeling | Agent instructions require call-site encoding/length evidence before hypothesis testing |
| A promising harness output needed independent confirmation | Input-bound comparison, researcher controls and original-app evidence; no automatic verified verdict |
| Some deeper algorithmic hypotheses remained unresolved | Preserve unknowns and rejected approaches; do not convert incomplete analysis into a solved claim |

## Tool decisions

* Retain existing Ghidra, binutils, ADB, Android SDK and build workflow.
* Add Capstone 5.0.6 for programmatic instruction decoding, Unicorn 2.1.4 for
  bounded CPU experiments and pyelftools 0.32 for structured ELF inspection.
* Add Frida 17.4.0 Python API as a separate optional install profile and a bounded
  attach/capture adapter. The Android server is a separately verified prerequisite.
* Discover optional GDB and C compiler, with distribution installation instructions.
* Reuse standard-library subprocess, ctypes, hashing and JSON. Do not copy the
  historical custom loader or hardcoded JNI model into a universal loader.
* Do not add xxhash, crypto-candidate collections, symbolic engines or unrelated
  libraries simply because an individual hypothesis used them. No production
  feature needs them. No unidbg integration is claimed.

All new Python wheels have exact versions and SHA-256 allowlists. Installation
is isolated, serialized and rerunnable; imports and dependency consistency are
checked. The core controller still has no new Python package requirement.

## Architecture and usage

`experiments.py` reuses job directories, operation locks, `pipeline.run` process
lifecycle, atomic reports and events. Each run records input/script/library hashes,
command/logs, observations, coverage and repeatability. `runtime.py` adds selected
ADB-device ownership/locking around Frida attachment. `capabilities.py` probes the
optional interpreter without importing native packages into the controller.

Commands: `experiment`, `experiment-compare`, `memory-diff`, `runtime-attach`.
`native_probe.py` supports ELF preflight and bounded explicit CPU execution.
See [EXPERIMENTS.md](../EXPERIMENTS.md) for runnable examples, result interpretation,
installation, API references and limitations. README, INSTALL, architecture,
configuration, examples, installer-generated agent guidance and the APK skill
reference now expose the new workflow.

## Validation

* Baseline: 39 existing unit/integration tests passed before implementation.
* Expanded suite: 54 tests passed locally, including original command regressions,
  CLI experiment execution, schema/path rejection, ownership checks, malformed
  output, crashes, timeout, paused jobs, input mutation, memory length changes and
  repeat/comparison behavior.
* Real execution: randomized compiled native functions were called through ctypes
  in fresh processes, compared with independent arithmetic expectations including
  overflow/boundaries, then repeated. This tests an unknown native fixture, not an
  Android application or an autonomous semantic investigation.
* Unicorn actually executed a bounded loop: expected register result and instruction
  count matched; unmapped execution returned a fault. ELF preflight parsed a real
  system executable.
* Fresh optional environment installed on host Python 3.13; clean temporary checkout
  installed on system Python 3.12. Reruns reused satisfied packages; `pip check` and
  imports passed. This is not a clean OS/VM installation test.
* Real unrelated APK validation: two ELF members processed without app-specific
  logic, repeated preflight agreed, ELF class/entry independently matched readelf.
  The reusable `scripts/validate_experiments.py APK --workspace PATH` records hashes,
  reports and reference logs. Original workspaces were not modified.
* `doctor` reported all installed optional versions; missing interpreter and version
  mismatch are covered in tests. Compilation checks passed.
* CI now installs/reruns optional profiles and runs the suite on Python 3.11–3.14.
  Remote CI results are not implied by local results.

## Remaining limitations

Full black-box Android runtime trials on previously unknown apps are not completed.
Frida Android attachment and capture are implemented but not device-validated here;
server deployment, ROM compatibility and installed APK identity require a chosen
target and independent evidence. Core SDK/Ghidra installation was not repeated on a
fresh operating system. The new installer was tested in clean Python environments,
not a clean OS VM. Python 3.11/3.14 are CI targets, not locally verified versions.

There is no universal Bionic/JNI loader, automated whole-app emulation, symbolic
solver, master-key recovery or guarantee of solving arbitrary APKs. Native code
execution requires a suitable analysis environment; process separation is not a
security boundary. Specs hash dependencies but do not snapshot them, reset external
state or capture the full environment. Reports are provenance records, not signed
attestations. Comparison does not establish independent ground truth. Interrupted
campaigns preserve progress but require a new spec for remaining inputs.

These limitations mean the user's full autonomous unknown-APK acceptance criterion
is not yet demonstrated. The PR should remain draft until Android runtime and clean
system acceptance are exercised.

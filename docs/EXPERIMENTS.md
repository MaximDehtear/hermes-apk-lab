# Reproducible native research

Start with `apk-lab doctor`, `inspect JOB`, `recon JOB` and `native JOB
lib/ABI/name.so`. Do not infer the APK's purpose from a filename. Derive entry
points, inputs and hypotheses from its code and observed behavior.

## Capability selection

| Mechanism | Useful when | Dependencies and limits |
| --- | --- | --- |
| `experiment JOB SPEC` | Custom host harness, debugger, differential probe or repeated observations | Core Python only; each case/repeat gets a fresh process; executes trusted researcher scripts, not a security sandbox |
| `experiment-compare JOB LEFT RIGHT` | Compare repeat runs or independently collected oracles | Same APK hash and case input hashes; agreement is not independence |
| `memory-diff JOB LEFT RIGHT --limit 64` | Compare constructor stages, decoded data or controlled perturbations | Streaming byte comparison; align mappings first; offsets are not virtual addresses |
| `scripts/native_probe.py`, operation `elf` | Decide whether a native execution strategy is plausible | Optional pyelftools; reports ELF class, segments, imports, dependencies and relocation types, not a universal loader |
| Same worker, operation `emulate` | Execute an isolated basic block or examine a fault | Unicorn; explicit maps/registers; ARM, Thumb, ARM64, x86_64; no Android runtime, JNI, syscalls or automatic relocations |
| Capstone Python API | Decode bytes from an established architecture/mapping | Optional research environment; decoding does not prove reachability |
| Frida Python API | Instrument a running process or collect selected memory ranges | Optional matching Android server, selected target/ABI and access rights; client import alone does not prove attach works |
| GDB + compiler | Diagnose host faults, watch buffers, build a harness | Optional distribution packages; host ABI and loader compatibility must be established |

## Install and discover

```bash
python3 scripts/setup_research.py          # capstone, unicorn, pyelftools
python3 scripts/setup_research.py --frida  # also Frida Python API (not frida-tools CLI)
apk-lab doctor
# Optional on Ubuntu:
sudo apt install gdb build-essential
```

Python 3.11–3.14 on the supported Linux x86_64 baseline. Wheels are version and
hash locked in `requirements/`. No global pip installation, Hermes Python changes,
source builds or automatic package upgrades. Rerunning reuses satisfied versions;
`pip check` and import checks detect incomplete environments. An unavailable wheel
fails explicitly. The installer serializes concurrent installs. A failed install
can be retried. To use an already managed environment, set `research_python` in
`config.local.json`; doctor reports exact version mismatches. The installer always
manages its own `toolchain/research`, never that external interpreter.

Frida server deployment is deliberately separate: obtain the **same version as the
installed client** from the official release, verify its digest and guest ABI,
record the server path/version and target serial in the job. Follow the selected
device's ownership rules; do not root, deploy, attach, spawn or restart through a
host script to circumvent `work-mode`/handoff. Stop only processes started for this
investigation. The server is not installed by `setup_research.py`.

## Experiment protocol

Copy `examples/probe.py` to the job's `analysis/probe.py` and adapt it. Copy
`examples/experiment.json` to the job, then run:

```bash
apk-lab experiment JOB /absolute/job/analysis/experiment.json
apk-lab experiment-compare JOB analysis/experiments/RUN_A/report.json analysis/experiments/RUN_B/report.json
apk-lab memory-diff JOB evidence/before.bin evidence/after.bin
```

The example only counts bytes to demonstrate the protocol; it does not analyze an
APK. All `files` paths must resolve inside the job, including harness, libraries,
input data and helpers. The command is an argv array, with no shell interpolation;
its working directory is the job. Use an absolute interpreter path when choosing
the research venv. The runner supplies:

* `APK_LAB_REQUEST`: JSON input file for this case.
* `APK_LAB_RESPONSE`: new output path; write `{"observation": ...}` as JSON <=1 MiB.
* `APK_LAB_OUTPUT`: case directory for dumps, traces and additional artifacts.

List up to 10,000 explicit cases; choose 1–20 repeats and a 1–3600 second timeout
per invocation. Defaults: two repeats, 30 seconds. Runs are sequential to avoid
cross-case process state and uncontrolled parallel load. `pause JOB` cancels the
current process group and prevents subsequent cases. There is no automatic retry
or resume of a partially completed campaign: its report preserves coverage; create
a new spec for remaining cases. CPU time and wall-clock timing are different;
external state such as files, services and device data is **not reset** between runs.

The manifest stores the original APK hash, declared file hashes, executable hash,
host architecture, spec, assumptions, logs, per-case observations and coverage.
Keep scripts/dependencies unchanged or archive them yourself before revising them.
Files are hashed, not snapshotted; inherited environment and external services are
not captured. Record relevant nonsecret environment settings and tool versions in
`assumptions`. Never put credentials in argv or assumptions. Logs are private job
artifacts and are not automatically published.

A zero exit without a structured observation is `invalid_response`; crashes and
timeouts remain missing observations. `repeatable` concerns identical observations
from repeated executions only. `inputs_unchanged` separately checks declared files.
`expected` is an optional researcher-provided control, never inferred from output.
Even perfect agreement leaves `verdict: unverified`: replay on the original app,
verify the installed APK identity and preserve independent screenshots/logs or
byte-level evidence. Include positive, negative and boundary inputs. A host stub,
patched library, or two wrappers around one implementation is not independent ground
truth. Use existing scenario/evidence and final report mechanisms for acceptance.

## ELF preflight example

Copy `scripts/native_probe.py` into the job's analysis directory and extract a
library using `native JOB lib/ABI/name.so`. In a spec use the research Python and
worker as `argv`, list both worker and extracted library in `files`, and use a case:

```json
{"id":"elf", "input":{"operation":"elf","file":"decoded/native-input/ABI/name.so"}}
```

Review `machine`, `bits`, `load_segments`, `needed`, `undefined_symbols` and
`relocation_types`. File offset, ELF virtual address and runtime address are
separate coordinates: for a file-backed PT_LOAD byte,
`file_offset = p_offset + (vaddr - p_vaddr)`; runtime address additionally needs the
observed load bias. A BSS address has no corresponding file byte. Similar libc
symbol names do not establish Android Bionic/glibc compatibility.

## Bounded instruction execution example

For an architecture and block selected from evidence, use an input like:

```json
{
  "operation":"emulate", "architecture":"x86_64",
  "regions":[{"address":4096,"size":4096,"file":"analysis/block.bin","permissions":5}],
  "start":4096, "until":4100, "instruction_limit":1000,
  "registers":{"rax":0}, "read_registers":["rax"], "read_memory":[]
}
```

Addresses here describe an artificial mapping, not a target signature. Supply the
actual bytes and architecture discovered for your experiment. Map stack/data and
set required registers explicitly. Limits: 64 regions, 256 MiB mapped memory,
10 million instructions, five seconds internal emulation, first 256 traced
instructions and 64 KiB memory observations. The outer experiment timeout is an
additional bound. A `fault` or `instruction_limit` observation is useful diagnostic
data, not successful completion. Never silently map invalid memory or return zero
for every unresolved import to make execution continue. Model only observed
requirements and record every stub, skipped constructor and patched instruction.

Capstone can decode captured bytes using `Cs(architecture, mode).disasm(data, base)`.
GDB can run a host harness under `gdb -q -batch -ex run -ex 'info registers' -ex bt
--args ...`; persist its log through an experiment wrapper. Record module load bias
before setting address breakpoints. Reproduce a fault on the same input in a fresh
process before attributing it to the APK.

## Choosing and validating a host harness

There is no automatic Android ELF/JNI loader here. Select a compatible ABI, audit
imports, TLS, relocations, constructors, JNI references and calling convention.
Use typed callbacks with preserved lifetimes, explicit buffer lengths and ownership.
A reduced JNI model and suppressed threads change the environment; list these
assumptions. Run untrusted binaries in a disposable isolated analysis environment;
a fresh subprocess only contains crashes and allocator state, not hostile effects.

If repeated attach attempts fail identically, investigate server/client versions,
ROM/ABI and app lifecycle before spending another race loop. If emulation faults,
inspect the missing environmental dependency before adding maps. If algorithm
candidates fail, recheck exact input encoding/length and output boundaries before
trying more algorithms. Preserve failures and coverage gaps. Do not claim an
unexamined branch is impossible or a secret unrecoverable.

Official API references: [Unicorn](https://www.unicorn-engine.org/docs/tutorial.html),
[Capstone](https://www.capstone-engine.org/lang_python.html),
[Frida Android](https://frida.re/docs/android/),
[pyelftools](https://github.com/eliben/pyelftools).

## Selected-device Frida capture

After verifying client/server versions and choosing the job's runtime target, place
an evidence-derived script in `analysis/probe.js`. A neutral discovery script is:

```javascript
send({modules: Process.enumerateModules().map(m => ({name: m.name, base: m.base.toString(), size: m.size}))});
```

Run `apk-lab runtime-attach JOB PID analysis/probe.js --seconds 10`. The controller
requires agent ownership, uses the selected device serial and device lock, and
records the script/worker hashes through the experiment runner. It attaches to an
existing PID; it does not spawn, root, install, restart or kill the app. Re-resolve
PIDs after app restart. Installed package identity must be checked independently.

For a justified memory capture, use Frida's `send(metadata, pointer.readByteArray(size))`
in your script. The worker saves binary messages with SHA-256 alongside structured
messages. Limits: 1–300 seconds, 10,000 messages, 16 MiB per binary message, 64 MiB total binary data and 512 KiB incoming JSON. Script
errors and early detachment remain observations, not a verified result. Very large
message output may exceed the experiment's 1 MiB response limit: full messages and
binary artifacts remain in the case directory but the response is invalid. Prefer
small scoped probes. Normal completion unloads the script and detaches; forced
process termination cannot guarantee agent cleanup on every ROM.

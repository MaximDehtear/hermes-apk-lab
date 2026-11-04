# Native C/C++ and JNI analysis

The project supports ELF triage and headless Ghidra decompilation independently
of smali. Java/JADX cannot decompile machine code in .so libraries.

## Setup and commands

`doctor` lists analyzeHeadless and native_decompiler_ready. Install with
`python3 scripts/setup_native.py` if absent: pinned Ghidra 11.4.2, official release,
SHA-256 verification, Java 21; binaries remain in project/toolchain. readelf/nm/
strings use host tools when available. No Docker or Ghidra MCP server is needed.

After input/inspect choose the actual ABI/library from inventory:

```bash
apk-lab native JOB lib/arm64-v8a/libexample.so
apk-lab native JOB lib/arm64-v8a/libexample.so --decompile --function JNI_OnLoad --limit 5
apk-lab native JOB lib/arm64-v8a/libexample.so --decompile --function parseRequest --limit 10
apk-lab native JOB lib/arm64-v8a/libexample.so --decompile --function 00101234 --limit 1
```

`--function` is a name substring or exact Ghidra entry-address string. Default `*`
decompiles the first 25 discovered functions, not the entire library. Use the
function index to select meaningful targets. Maximum limit 100; each function has
a 30-second decompiler timeout and initial analysis a 300-second timeout. Run long
commands via Hermes terminal background with completion notification.

Results under analysis/native/LIBRARY_SHA/RUN/:

- ELF header/dependencies/dynamic symbols, demangled symbols and offset strings.
- functions.jsonl: discovered names, signatures, entry addresses, module-relative
  addresses; selected functions include up to 200 incoming entry references.
- ADDRESS.c: reconstructed C-like pseudocode for successfully selected functions.
- summary.json/report.json: library and APK hashes, Ghidra version, architecture,
  counts, selector, logs, errors/timeouts and limitations.

The Ghidra project stays in decoded/ghidra/LIBRARY_SHA/. Later targeted calls reuse
successful analysis with -process/-noanalysis. A timed-out initial analysis is
marked incomplete and is not silently reused as complete. Crash/failed outputs
remain inspectable. See the official
[headless interface](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/RuntimeScripts/support/analyzeHeadlessREADME.md)
and [decompiler API](https://ghidra.re/ghidra_docs/api/ghidra/app/decompiler/DecompInterface.html).

## Interpret carefully

Trace Java native declarations -> System.loadLibrary -> exported JNI names or
RegisterNatives mapping -> native implementation -> state/network boundaries.
Include dlsym, indirect calls, vtables, callbacks and library initialization where
relevant. Ghidra incoming references cover static references to function entries;
they are not a full dynamic call graph. The Java ClassLoader and ELF ABI matter.

Pseudocode reconstructs semantics from machine code. It does not recover the
original C++ project, all stripped method names, types or comments, and it is not
a drop-in recompilable replacement. Validate pointer types, arithmetic and control
flow against disassembly/runtime evidence. RTTI, surviving symbols, logs and strings
help assign evidence-backed aliases through remember/knowledge.

For stripped code use `library hash + ABI + RVA` as stable identity. For runtime
hooks calculate RVA from Ghidra entry minus image base, then add the actual loaded
module base. Validate executable range, instruction boundary, ABI and ARM/Thumb
state. Do not apply an address from another revision or architecture.

The built-in command selects lib/ABI/name.so in a monolithic original APK.
Libraries in splits/assets/dynamic downloads require separate safe acquisition
and analysis with provenance; do not pretend they were covered. Managed ABI
emulation and host analysis are different: Ghidra analyzing ARM code does not
make an x86_64 emulator capable of running that app.

Native binary patching requires an architecture-specific design, valid instruction
encoding/relocations and a tested rebuild. There is no universal C++ source-edit
and recompile pipeline. Use [instrumentation.md](instrumentation.md) for diagnostic
smali markers or optional Frida hooks, and advanced.md for framework boundaries.

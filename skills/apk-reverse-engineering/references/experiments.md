# Native experiments and independent evidence

Discover actual capabilities with `apk-lab doctor`; optional research packages
are isolated from Hermes. Read the project's `docs/EXPERIMENTS.md` for the schema,
commands, worker examples, installation and limits. Do not assume the APK's purpose,
algorithm, accepted inputs, package identity or addresses before inspecting it.

Choose the cheapest experiment that distinguishes competing hypotheses. Start
with inventory and native ELF preflight, then select static analysis, original-app
observation, instrumentation, a host harness or a bounded emulated block based on
evidence. No strategy works for every Android library. Host symbol resolution does
not establish Bionic/JNI compatibility; CPU emulation does not supply Android.

Use `experiment JOB SPEC` to preserve inputs, scripts' hashes, logs, failures and
repeat observations. Use the bundled `native_probe.py` for ELF structure or explicit
bounded instruction execution; Capstone for decoding; GDB for host faults; optional
Frida API for selected process instrumentation. Follow existing device ownership
and locks; never use arbitrary host scripts to bypass a human handoff.

Preserve originals. Record constructors, load bias, imports, TLS, stubs, patches,
input encodings and any external state required by the harness. Compare captures
with `memory-diff`; align mappings and capture stages first. A runtime dump is not
necessarily an ELF file. A missing page is a model failure until explained.

Use fresh processes for repeated inputs; reproduce crashes individually. Count
all cases, missing observations and timeouts before claiming complete coverage.
Stop identical failed attempts when they stop distinguishing hypotheses. An
unchanged output after a perturbation may mean the changed region was never read.

Use `experiment-compare` for exact observation comparisons. Require independent
original-app evidence and positive/negative controls before a conclusion. Expected
values supplied by the same harness do not verify it. Repeatability, successful
commands, recognizable strings and cryptographic-looking output are not proofs.
Report what remains unknown, including untested ABI/device behavior. Publish only
reviewed reports via the existing artifact workflow, never raw session history.

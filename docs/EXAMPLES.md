# Example workflows

These are example requests and expected workflows, not transcripts of a completed
Telegram integration test. English and Russian requests are supported equally.

## Understand an app

> Analyze this APK and explain how synchronization works. Trace the UI entry point,
> local queue, network request and error handling. Give me a complete upload link.

Hermes creates a job, sends the token-bearing link, waits for upload completion,
inspects/decompiles the input and traces relevant paths. The report separates
observed facts, static findings, hypotheses and unknowns, with source references.

## Patch and verify

> Change the default setting to disabled. Test in virtual Android, automatically.
> Show before/after screenshots and confirm that the change survives a restart.

The expected route is baseline → minimal patch → signed build → repeated scenario
→ evidence-backed result. A changed label alone would not establish persistence.

## Work together on a difficult screen

> Use assisted mode on my phone. If you cannot reach the hidden settings panel,
> give me control. When I say ready, inspect the screen and logs without restarting.

Human turn blocks controller mutations. After a real ready signal, observation
continues in place. Demonstrated steps can be saved and later reproduced under
the selected mode, with failures retained alongside successes.

## Investigate native code

```bash
apk-lab native JOB lib/arm64-v8a/libexample.so
apk-lab native JOB lib/arm64-v8a/libexample.so --decompile --function JNI_OnLoad --limit 5
```

Choose a library actually listed in the input. Review the function index and target
relevant names/addresses. Ghidra reconstructs C-like pseudocode; original C++ source
and erased names are not guaranteed recoverable.

## Diagnose an obfuscated method

```bash
apk-lab instrument JOB --method 'La/b;->c()V' --label refreshPreferences --at entry
apk-lab build JOB
# Install the diagnostic build before navigating to the difficult state.
# Observe APKLAB markers and correlate them with the scenario.
apk-lab uninstrument JOB MARKER_ID
apk-lab build JOB
```

An unchanged baseline is required first. Keep the original descriptor alongside
its readable alias. Markers show execution; payload or wire-traffic claims need
additional observations. Retest the cleaned final build.

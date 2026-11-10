# Probe apps and controlled peers for runtime evidence

Use a minimal probe app when a scenario depends on an app UID, signing identity,
permission grant, typed Intent/Parcelable or ContentProvider behavior that an ADB
shell command cannot represent faithfully. Derive the interface and stimulus from
the APK under investigation. Do not assume its purpose or a particular vulnerable
component. Keep harness source, builds, inputs and observations inside the job.

## Build and validate a probe

Prefer a minimal Android project with explicitly recorded SDK, build-tool and
plugin versions. A Java/smali-only assembly is also possible, but needs valid
manifest/resource packaging, DEX conversion, alignment and signing; compilation
alone does not establish a runnable APK. Build dependencies beyond the APK Lab
installer must be recorded separately. Use a separate signing key when the test
requires a foreign identity, and never commit signing keys to the repository.

For an existing probe project, a typical build/verification sequence is:

```bash
./gradlew --no-daemon assembleDebug
# Use absolute tool paths from apk-lab doctor when these are not on PATH.
apksigner verify --verbose --print-certs /absolute/job/tests/probe.apk
```

The output path above refers to the probe artifact copied from the project's build
output. Pin the Gradle wrapper/plugin versions and keep the exact manifest and APK
hash with the run. If assembling manually, D8 expects an existing output directory
or a supported archive path; inspect the generated DEX before packaging. Do not
infer that all resource-free projects fail, or that compressed DEX is always
invalid, from one packaging failure. Diagnose install and class-loading logs,
manifest component names, archive entries and DEX content on the actual runtime.

Respect the selected device and work-mode/handoff rules when deploying a probe.
`device install-test` is for verified target builds under builds/, not arbitrary
helper APKs. A manually deployed helper needs its own installation/signing/version
record in tests/ and must not be mislabeled as the target build's receipt. Verify
its launch, IPC exchange and observed result, not only its installer exit code.

## Exercise the actual interface

A provider that answers query() alone may not support stream consumers. Inspect
which API the client calls; implement the corresponding openFile/openAssetFile or
typed-asset path and test actual bytes read. openAssetFile can delegate to openFile;
it is not always necessary to override both. Return a correctly owned descriptor
with appropriate mode, offset and length, and log failures rather than silently
returning an unusable value. See the
[ContentProvider contract](https://developer.android.com/reference/android/content/ContentProvider).

Activity lifecycle behavior depends on launch mode, flags and current task state.
An Intent may reach onNewIntent rather than create a new Activity. Record which
callback ran. Choose whether the scenario needs an existing instance or a fresh
one; resetting tasks/data or force-stopping is not interchangeable with replaying
an Intent and must not destroy a pending human handoff.

For UI evidence, parse hierarchy XML by attribute name. Attribute order and focus
behavior are not stable contracts. Verify current window, IME visibility and the
resulting field contents with a new capture after each action; see device.md.

## Permission and identity controls

Test the caller identity and permission state required by the hypothesis. For a
signature-permission experiment, compare a properly declared same-signer client
with a different-signer client and verify the actual grant state. A matching
certificate alone is not a complete account of all permission checks. Preserve
both denial and positive-control evidence.

Upgrades can retain permission or app state. Record installed versions, target SDK,
signing certificates, requested/granted permissions and relevant AppOps before and
after each run. On a disposable test instance, reinstalling the probe can test
fresh-install behavior; also test upgrade behavior if it is part of the question.
Do not uninstall a user's app or clear its data as an implicit reset.

If shell cannot directly reach a component, that does not prove another app can
or cannot reach it. Trace exported entry points and any internal forwarding from
evidence. Verify both the caller's result and the destination's observable action;
a focused activity alone does not prove a permission bypass.

## Controlled network peer

Use a server under your control when a reproducible response or independently
recorded receipt can distinguish hypotheses. Record its bind address/port,
request timestamps, correlation IDs, method/path and the fields relevant to the
claim. Avoid collecting unrelated credentials. Check port availability first.

Use the current runtime's supported supervised background-job mechanism, or run
server startup, the scenario and cleanup together. Record the owned process ID,
log and stop method. Do not assume a notebook kernel, daemon thread or shell
background process survives between tool calls. Bound run duration and stop only
services started for this experiment. For compatible host probes, use the
experiment workflow in experiments.md.

A controlled endpoint can change application behavior. Determine the expected
protocol/response from observed code or traffic, vary one factor at a time and
record the response supplied. An empty or invalid response may prevent downstream
paths from running; report those paths as untested. A successful response from a
mock server is not proof of delivery to the original service.

Prefer an explicit test endpoint or supported proxy configuration when suitable.
If a disposable, authorized environment requires DNS/routing changes, first inspect
its resolver, transport, address family, privileges and existing rules. Do not
assume an emulator gateway address or UDP DNS/TCP HTTP path applies universally.
Encrypted DNS, IPv6, caching, TLS verification and certificate pinning may change
or prevent the route. Record the exact intervention; do not silently weaken TLS
or replace app behavior just to obtain a successful request.

When a retry still fails, distinguish cached resolution from routing, TLS and
application errors using observations. Do not routinely kill netd or flush global
network rules: recovery procedures vary by Android image and can affect other jobs.
Choose a scoped reset or restore a dedicated test snapshot where appropriate.

Separate these evidence levels in the report:

- A constructed payload shows what code prepared, not whether it was sent.
- A network/API invocation shows an attempt, not necessarily successful egress.
- An attributed capture shows bytes at that observation point; encrypted bytes
  alone do not establish plaintext contents or application-level receipt.
- A correlated controlled-server receipt establishes receipt there under the
  recorded test conditions, not necessarily at the production destination.

## Rollback and reproducibility

Before intervention, record relevant configuration and app state. Keep an explicit
list of changes: owned processes, rules, proxy/DNS settings, installed probes and
any modified permissions. Restore only those changes, verify the resulting
configuration and exercise an appropriate baseline control. No traffic arriving
at the test server is useful observation but not proof of successful rollback.
Reset only disposable test-instance data when the scenario requires it.

Store the inputs, hashes, timestamps, logs, cleanup result and residual limitations
with the job. A blocked environment yields an inconclusive behavior claim; a
completed test contradicting the expected result yields a failed scenario. Keep
original, rebuilt baseline and diagnostic-variant evidence distinguishable.

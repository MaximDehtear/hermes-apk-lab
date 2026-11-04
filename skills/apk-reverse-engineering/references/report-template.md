# Investigation report template

Write the user report in their language. Replace placeholders with evidence or an
explicit unknown. Keep a short outcome first; include only relevant sections.
Do not publish tokens, signing keys, account secrets or unrelated private data.

## Outcome and scope

- Requested goal and observable acceptance criteria.
- Result: analysis only / behavior verified in the stated scenario / failed /
  inconclusive / not runtime-tested by user choice.
- Original package/version/SHA-256; final APK SHA-256 if changed.
- Test target, Android/API/ABI, important state/network conditions; tool versions.

## How the relevant behavior works

Explain entry point -> UI/callback -> state -> storage/network/native boundary.
Link exact methods/descriptors, source path:line and source hashes where available.
Mark code as original, reconstructed working tree or re-decoded signed artifact.
Distinguish app logic from SDK logic and local state from server authority.
List partial decompilation, unavailable modules and coverage gaps.

## Findings

| ID | Claim and impact | Evidence | Basis / confidence | Alternatives / limits |
| --- | --- | --- | --- | --- |
| F-01 | Concrete observation answering the goal | Code/method and/or runtime artifact | static-confirmed / runtime-observed / inferred / unresolved; confidence | What has not been ruled out |

For security findings add severity separately from confidence, affected versions,
preconditions and reproducible steps. Do not label a permission/string/URL as an
exploitable finding without demonstrating the relevant chain.

## Changes, if any

Exact method/resource changes, rationale, preserved behavior, diff artifact,
baseline revision, signed revision and hashes. Explain any diagnostic build that
differs from the deliverable. Include installation/signing constraints and rollback
using preserved originals/baseline; do not assume an unsigned or differently
signed APK can update the installed application without data consequences.

## Verification

| Scenario | Preconditions and actions | Expected / observed | Verdict | Evidence |
| --- | --- | --- | --- | --- |
| Goal behavior | Exact reproducible steps | State both | passed / failed / inconclusive / untested | Build hash, install receipt, before/after PNGs, relevant logs |
| Reset or refresh path | Relevant lifecycle/network trigger | State both | Actual result | Artifacts |
| Neighboring behavior | Affected negative/regression case | State both | Actual result | Artifacts |

Name the final signed-artifact checks. Screenshots support visible behavior;
nonvisual persistence or egress needs additional evidence. State whether the
unchanged re-signed baseline worked. Distinguish tool success from behavior success.

## Remaining questions and delivery

Unverified hypotheses, limited environment/coverage, concrete next experiment,
downloadable report/APK/diff/screenshots. In the Telegram reply obtain a fresh
`link JOB --format telegram` and copy its full URL. Keep bearer URLs out of the
permanent report, since tokens rotate and reports may be shared.

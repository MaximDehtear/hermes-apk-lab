# Contributing

Start with a reproducible problem, expected behavior and actual evidence. Include
OS/architecture, relevant tool versions and sanitized logs. Never include tokens,
signing keys, private APKs or unrelated user data.

Keep changes focused and document user-visible behavior. Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q apk_lab scripts tests
```

Changes to build/native/device flows should also use the corresponding synthetic
validation script when the required SDK, Ghidra or AVD is available. Say explicitly
which checks were not run. Never describe mocked tests as physical-device testing.

Documentation and code-facing text use English. Preserve Russian request support
and the user's preferred response language in skill changes. Respect evidence
provenance, handoff ownership and existing data when extending workflows.

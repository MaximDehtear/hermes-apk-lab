# Recorded validation results

These seven JSON records preserve historical checks on synthetic fixtures. They
support the timeline in [VALIDATION.md](../../VALIDATION.md); they are not runtime
configuration, a test suite, or results for user applications.

Published records use `$PROJECT`, `$ANDROID_SDK` and `$HERMES_WORKSPACE` in place
of host-specific absolute paths. `HOST_LAN_ADDRESS` replaces the original private
LAN address. These substitutions are documentation placeholders, not runnable URLs.
Hashes, outcomes, timestamps and tool versions are retained.

Validation scripts create fresh local records in the project root by default;
these generated files are ignored by Git. Use the `--output` examples in
[INSTALL.md](../../INSTALL.md) where supported. Do not overwrite these published
historical records with a later run.

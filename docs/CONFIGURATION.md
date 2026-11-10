# Configure once, then install

After installing Python/system dependencies and configuring Hermes, run:

```bash
python3 scripts/configure.py
```

Press Enter to keep a suggested value. The wizard shows the complete configuration
and asks whether to save. It writes config.local.json, which is ignored by Git.
It does not download tools, modify Hermes settings or configure firewall/router
rules. Run the setup/install scripts afterward; they read these saved settings.
Explicit install.py options can override its saved binding/port/exposure settings.

| Setting | Meaning | Default |
| --- | --- | --- |
| Hermes home | Directory containing Hermes config.yaml and skills | ~/.hermes |
| Workspace | Must match Hermes terminal.cwd; all job data lives here | Detected from Hermes, otherwise ~/hermes_workdir |
| Android SDK | Linux SDK installation directory | ~/Android/Sdk |
| Port | HTTP upload/download port | 9099 |
| Exposure | direct binds all IPv4 interfaces; local binds loopback | direct |
| Public base URL | Reachable origin used in shared links, including port | Empty: detected LAN address |
| Maximum upload | Largest accepted APK/archive in GiB | 4 |
| Idle timeout | Minutes without transfer before shutdown | 30 |
| Lifetime | Maximum server lifetime in hours; active transfers delay shutdown | 4 |

An empty public URL does not establish internet access. To clear a saved URL in
the wizard, enter `-`. An origin is e.g. http://example.org:9099, without a job token
or custom path. HTTP is not encrypted; HTTPS requires a separately configured
reverse proxy. A public URL does not configure TLS, NAT or firewall rules.

For access only from this machine, choose local. For LAN/internet access, choose
direct, arrange reachability and set the address when known. WSL requires the
additional network/device preparation in [INSTALL.md](../INSTALL.md).

For reproducible noninteractive setup:

```bash
python3 scripts/configure.py --non-interactive \
  --hermes-home "$HOME/.hermes" \
  --workspace "$HOME/hermes_workdir" \
  --sdk "$HOME/Android/Sdk" \
  --port 9099 --exposure direct \
  --public-base-url http://example.org:9099 \
  --max-upload-gib 4 --idle-minutes 30 --lifetime-hours 4
```

Replace the example URL with your real reachable origin, or pass an empty string.
Existing unrelated configuration keys are retained. Pinned tool versions are
maintained in setup scripts; do not change versions without checking compatibility.
Device and work-mode choices belong to each job, not global installation settings.
Stop the transfer server before changing its settings, then reopen with link JOB.
The wizard validates field formats; install.py validates the Hermes local backend.

### Optional research interpreter

`research_python` is an absolute executable path to an independently managed Python
with the versions in `requirements/`. Default: `toolchain/research/bin/python` in
the checkout. `doctor` probes imports in a subprocess with a timeout and reports
version mismatches. `setup_research.py` only modifies the default private venv; it
never repairs an external interpreter. No configuration migration is required.

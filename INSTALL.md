# Fresh Linux and Windows WSL2 installation

The supported baseline is **Linux x86_64, Python 3.11+ and Java 21**. Ubuntu 24.04
is the concrete package example below. Other distributions need equivalent packages.
Native Windows, WSL1 and ARM hosts are not supported by this installation recipe.
WSL2 can run Linux analysis/build tools; hardware/device access needs additional setup.
A clean OS installation has not been exercised in a disposable VM in this audit.

## 1. System dependencies and Hermes

On Ubuntu 24.04, install system dependencies:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-yaml openjdk-21-jdk ca-certificates unzip binutils libstdc++6 zlib1g
python3 --version
java -version
```

Use your distribution's instructions for other versions. `python3-yaml` must be
visible to the Python running install.py; inside a virtual environment install
PyYAML there instead. Do not use sudo for the project setup/install scripts.
Optional native validation uses g++ (`sudo apt install g++`). Node.js is needed
only for JavaScript syntax checks, not the lab runtime.

Install and configure Hermes separately. This project does not install Hermes,
configure its model/provider, or connect its Telegram bot. Hermes must run as the
same Linux user, with terminal.backend=local and an absolute terminal.cwd in
~/.hermes/config.yaml. Example terminal section (merge into the existing config):

```yaml
terminal:
  backend: local
  cwd: /home/YOUR_USER/hermes_workdir
```

Keep the checkout in a writable Linux directory, for example
~/project/hermes-apk-lab. When copying from another PC, do not carry over
config.local.json: it contains that PC's workspace/SDK paths. Do not copy signing
keys or user jobs as part of an ordinary fresh installation. Python uses fcntl,
Unix process groups and symlinks, so running these scripts in Windows Python
is not supported.

## 2. Configure once, install tools and bind the skill

Run from the checkout after preparing Hermes. The configuration wizard explains
paths, port, access mode, public address and limits before any installation.
See [configuration reference](docs/CONFIGURATION.md) for examples and noninteractive use:

```bash
cd ~/project/hermes-apk-lab
python3 scripts/configure.py
python3 scripts/setup_tools.py
python3 scripts/setup_sdk.py --licenses
python3 scripts/setup_native.py
python3 scripts/install.py --replace-existing
export PATH="$HOME/.local/bin:$PATH"
apk-lab doctor
```

Persist the PATH addition in your shell profile if necessary. Without PATH changes,
use ./bin/apk-lab. --replace-existing permits replacement of the same-named skill;
the installer backs up the old skill. It preserves unrelated Hermes settings.
The installer validates the local terminal backend even with --workspace.

setup_tools installs pinned JADX/Apktool; setup_sdk bootstraps checksum-pinned
Google command-line tools and installs platform-tools, build-tools;36.0.0 and
platforms;android-34. SDK packages are fetched by Google's sdkmanager. Review
licenses interactively; licenses are not automatically accepted. Default SDK path
is ~/Android/Sdk, or android_sdk from config.local.json. To use a different SDK,
set that absolute path before setup. setup_native installs checksum-pinned Ghidra
and is optional if native decompilation is not needed.

Internet access to GitHub and Google's Android downloads and sufficient disk
space are required. Allow several GiB for tools/SDK plus space for originals,
decoded files and multiple builds; a 200 MiB APK can expand substantially.
Ghidra setup requires 2 GiB free when downloading. Emulator setup additionally
checks for at least 10 GiB free in the workspace.

## 3. Optional managed emulator on Linux

The emulator requires usable /dev/kvm, CPU virtualization enabled in firmware,
and appropriate user permissions. On Ubuntu, prepare KVM using distribution
instructions, add the user to the kvm group if needed, then log out/in. Do not
make /dev/kvm world-writable. Headless rendering may also need distribution
libraries such as libgl1, libegl1, libx11-6 and libpulse0; a desktop window requires
a graphical session and the emulator's Qt/X11 dependencies.

```bash
python3 scripts/setup_emulator.py
apk-lab emulator start
apk-lab emulator status
apk-lab emulator stop
```

The setup checks -accel-check before creating the API 34 x86_64 AVD. A failure is
a concrete environment blocker: use a phone or select no runtime testing until
resolved. setup_sdk does not require KVM, so static analysis/builds remain usable.

## 4. Windows through WSL2

Install an x86_64 Ubuntu 24.04 WSL2 distribution and run ALL steps above inside it.
Keep Hermes, this checkout, workspace and Linux SDK under /home, not /mnt/c.
Do not configure Linux commands to point to Windows SDK .exe files. Windows ARM
hosts are outside the tested/supported recipe.

**Analysis, Ghidra and rebuilding:** use the Linux tools normally. WSL2 itself has
not been tested end to end for this project, so compatibility is expected from its
Linux environment rather than certified by a WSL run.

**Physical phone:** USB is not automatically passed to WSL. Follow Microsoft's
[USB/IP guide](https://learn.microsoft.com/en-us/windows/wsl/connect-usb): install
usbipd-win on Windows, identify the device with usbipd list, share it with
usbipd bind --busid BUSID in elevated PowerShell, then attach with
usbipd attach --wsl --busid BUSID. In WSL use the Linux SDK adb devices -l and accept
the RSA prompt on the phone. Linux udev permissions may also need configuration.
Alternatively use Android Wireless debugging with pairing/connection ports when
reachable from WSL. Do not expose ADB publicly.

**Managed emulator:** do not assume it works inside WSL2. This controller requires
Linux KVM; WSLg graphics or Windows virtualization being enabled does not establish
usable /dev/kvm. Verify permissions and emulator -accel-check. See Android's
[acceleration requirements](https://developer.android.com/studio/run/emulator-acceleration).
A Windows Android Studio emulator is not automatically managed by the Linux
controller. Prefer a connected phone or no runtime testing if KVM is unavailable.

**Upload server:** binding 0.0.0.0:9099 inside WSL is not proof of external access.
Windows localhost access can work while LAN/internet access still fails. Under
WSL NAT, configure Windows forwarding to the current WSL IP and firewall rules;
the IP can change after restart. Supported Windows 11 versions also offer mirrored
networking, with Windows/Hyper-V firewall considerations. Follow Microsoft's
[WSL networking guide](https://learn.microsoft.com/en-us/windows/wsl/networking).
For internet access, also arrange router forwarding/public IP as needed and set
public_base_url to the externally reachable origin. The installer does not modify
Windows firewall, WSL networking or router settings. WSL/host shutdown stops services.

## 5. Verify the installation

```bash
apk-lab doctor
python3 -m unittest discover -s tests -v
python3 scripts/validate_toolchain.py --output validation-local.json
```

Doctor's missing list covers required build tools; inspect native_decompiler_ready
and emulator readiness separately. Tool discovery alone does not verify binaries
can execute or missing shared libraries: the synthetic toolchain validation does.
It requires SDK platform android-34 installed above. Optional checks:

```bash
python3 scripts/validate_native.py
python3 scripts/validate_emulator.py --output emulator-validation-local.json
```

Native validation requires g++. Emulator validation installs a synthetic fixture
on the managed AVD and stops it afterward; run only when that AVD is not needed
by another task. Real phone access, Telegram notifications and internet reachability
must each be checked in their actual environment; unit tests do not establish them.

## Optional native research environment

After the core installation, run `python3 scripts/setup_research.py` (Python
3.11–3.14). Add `--frida` for the Frida Python API. Installation uses a separate
`toolchain/research` venv, exact wheel hashes and `pip check`; reruns reuse matching
packages. No Hermes dependencies or settings are replaced. GDB and C/C++ compilers
are optional system packages (`sudo apt install gdb build-essential`).

Run `apk-lab doctor` to inspect research imports and exact versions. Missing optional
components do not appear in the core `missing` list. Frida server setup and guest
compatibility are separate from client readiness. See [research installation,
commands and limitations](docs/EXPERIMENTS.md).

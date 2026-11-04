#!/usr/bin/env python3
"""Configure the lab once before installing tools or binding Hermes."""
import argparse
import json
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from apk_lab.core import atomic_json
from apk_lab.server import validate_base_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--non-interactive', action='store_true', help='Use supplied options and saved/default values without prompts')
    parser.add_argument('--hermes-home')
    parser.add_argument('--workspace')
    parser.add_argument('--sdk')
    parser.add_argument('--port', type=int)
    parser.add_argument('--exposure', choices=['direct', 'local', 'lan'])
    parser.add_argument('--public-base-url')
    parser.add_argument('--max-upload-gib', type=int)
    parser.add_argument('--idle-minutes', type=int)
    parser.add_argument('--lifetime-hours', type=int)
    args = parser.parse_args()
    path = PROJECT / 'config.local.json'
    config = json.loads(path.read_text()) if path.exists() else {}
    home = args.hermes_home or config.get('hermes_home') or os.environ.get('HERMES_HOME', str(Path.home()/'.hermes'))
    workspace = config.get('workspace', str(Path.home()/'hermes_workdir'))
    settings = Path(home).expanduser()/'config.yaml'
    if settings.is_file():
        try:
            import yaml
            workspace = (yaml.safe_load(settings.read_text()) or {}).get('terminal', {}).get('cwd') or workspace
        except ImportError:
            print('PyYAML not available; verify workspace matches Hermes terminal.cwd.')
    fields = [
        ('hermes_home', 'Hermes configuration directory', args.hermes_home, home),
        ('workspace', 'Hermes terminal.cwd (analysis and user jobs)', args.workspace, workspace),
        ('android_sdk', 'Linux Android SDK directory', args.sdk, config.get('android_sdk', str(Path.home()/'Android/Sdk'))),
        ('port', 'Transfer port', args.port, config.get('port',9099)),
        ('exposure', 'Access: direct = all IPv4 interfaces; local = this computer only', args.exposure, config.get('exposure','direct')),
        ('public_base_url', 'Externally reachable origin, e.g. http://example.org:9099; empty = detected LAN address', args.public_base_url, config.get('public_base_url','')),
        ('max_upload_bytes', 'Maximum APK size in GiB', args.max_upload_gib, config.get('max_upload_bytes',4*1024**3)/1024**3),
        ('idle_seconds', 'Stop server after this many idle minutes', args.idle_minutes, config.get('idle_seconds',1800)/60),
        ('lifetime_seconds', 'Maximum server lifetime in hours', args.lifetime_hours, config.get('lifetime_seconds',14400)/3600),
    ]
    factors = {'max_upload_bytes':1024**3, 'idle_seconds':60, 'lifetime_seconds':3600}
    for key,label,supplied,default in fields:
        value = supplied if supplied is not None else default
        if not args.non_interactive and supplied is None:
            answer = input(f'{label} [{value}]: ').strip()
            if answer:
                value = '' if key == 'public_base_url' and answer == '-' else answer
        if key in {'hermes_home','workspace','android_sdk'}:
            target = Path(str(value)).expanduser()
            if not target.is_absolute(): raise ValueError(label + ' must be absolute')
            value = str(target.resolve())
        elif key == 'port':
            value = int(value)
            if not 1 <= value <= 65535: raise ValueError('Port must be 1..65535')
        elif key in factors:
            value = int(float(value)*factors[key])
            if value <= 0: raise ValueError(label + ' must be positive')
        elif key == 'exposure' and value not in {'direct','local','lan'}:
            raise ValueError('Exposure must be direct, local or lan')
        elif key == 'public_base_url':
            value = validate_base_url(str(value))
        config[key] = value
    config.setdefault('chunk_bytes',8*1024**2)
    print(json.dumps(config,indent=2))
    if not args.non_interactive and input('Save these settings? [Y/n]: ').strip().lower() not in {'','y','yes'}:
        print('Configuration not saved.')
        return
    atomic_json(path,config)
    print('Saved:',path)
    print('Use setup_tools.py, setup_sdk.py, optional setup_native.py, then install.py. No downloads or device changes were made.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError,OSError) as error:
        raise SystemExit(str(error))

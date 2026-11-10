#!/usr/bin/env python3
"""Bounded attach worker; messages and binary sends are preserved per experiment."""
import hashlib
import json
import os
import threading
import time
from pathlib import Path
import frida


def main():
    request = json.loads(Path(os.environ['APK_LAB_REQUEST']).read_text())
    output = Path(os.environ['APK_LAB_OUTPUT'])
    device = frida.get_device(request['serial'], timeout=5)
    messages, errors = [], []
    total_binary, total_json = 0, 0
    guard = threading.Lock()
    detached = threading.Event()
    def receive(message, data):
        nonlocal total_binary, total_json
        with guard:
            total_json += len(json.dumps(message).encode())
            total_binary += len(data) if data else 0
            if total_json > 512 * 1024 or total_binary > 64 * 1024**2:
                errors.append("Capture budget exceeded")
                detached.set()
                return
            if len(messages) >= 10000:
                errors.append('Message limit reached')
                detached.set()
                return
            item = {'message': message}
            if data is not None:
                if len(data) > 16 * 1024**2:
                    errors.append('Binary message exceeds 16 MiB')
                    detached.set()
                    return
                path = output / ('memory-' + str(len(messages)) + '.bin')
                path.write_bytes(data)
                item.update(binary=path.name, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
            messages.append(item)
            if message.get('type') == 'error':
                errors.append(message.get('description', 'Script error'))
            (output/'messages.json').write_text(json.dumps(messages))
    session = device.attach(request['pid'])
    script = None
    try:
        session.on('detached', lambda *args: detached.set())
        script = session.create_script(Path(request['script']).read_text())
        script.on('message', receive)
        script.load()
        detached.wait(request['seconds'])
    finally:
        if script is not None:
            try:
                script.unload()
            except frida.InvalidOperationError:
                pass
        try:
            session.detach()
        except frida.InvalidOperationError:
            pass
    Path(os.environ['APK_LAB_RESPONSE']).write_text(json.dumps({'observation': {
        'messages': messages, 'errors': errors, 'detached_early': detached.is_set(),
        'client_version': frida.__version__}}))


if __name__ == '__main__':
    main()

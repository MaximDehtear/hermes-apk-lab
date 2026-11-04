"""Reversible smali markers in diagnostic builds, without changing target registers."""
import hashlib
import re
import time

from .core import atomic_json, event, job_dir, lock, sha256
from .pipeline import input_apk
from .research import source_files


def inject(job_id, symbol, label, where='entry', line=None, source_sha256=None):
    if not re.fullmatch(r'L[^;\s]+;->[^\s]+\([^\s]*\)[^\s]+', symbol):
        raise ValueError('Use a complete smali method descriptor')
    if not re.fullmatch(r'[A-Za-z0-9_.:/ -]{1,100}', label):
        raise ValueError('Use a short ASCII diagnostic label without payload/secrets')
    if where not in {'entry', 'returns', 'line'}:
        raise ValueError('Marker location must be entry, returns or line')
    p = job_dir(job_id)
    with lock(p / '.operation.lock', blocking=False):
        input_apk(job_id)
        if not (p / 'patches/baseline-source.zip').is_file():
            raise ValueError('Build an unchanged baseline before instrumenting')
        owner, method = symbol.split('->', 1)
        matches = []
        for path in source_files(job_id):
            lines = path.read_text().splitlines(keepends=True)
            declared = next((x.strip().split()[-1] for x in lines if x.strip().startswith('.class ')), None)
            if declared != owner:
                continue
            for index, text in enumerate(lines):
                if text.strip().startswith('.method ') and text.strip().split()[-1] == method:
                    end = next((n for n in range(index + 1, len(lines)) if lines[n].strip() == '.end method'), None)
                    if end is None:
                        raise ValueError('Malformed method')
                    matches.append((path, lines, index, end))
        if len(matches) != 1:
            raise ValueError('Expected exactly one target method; found ' + str(len(matches)))
        path, lines, start, end = matches[0]
        if {'abstract', 'native'} & set(lines[start].split()):
            raise ValueError('Native/abstract method has no smali body; instrument its caller or use native hooks')
        original_hash = sha256(path)
        if source_sha256 and source_sha256 != original_hash:
            raise ValueError('Source hash changed; inspect again before instrumenting')
        instructions = []
        annotation = 0
        payload = False
        for index in range(start + 1, end):
            text = lines[index].strip()
            if text.startswith(('.annotation ', '.subannotation ')):
                annotation += 1
            if annotation:
                if text.startswith(('.end annotation', '.end subannotation')):
                    annotation -= 1
                continue
            if text.startswith(('.packed-switch ', '.sparse-switch', '.array-data ')):
                payload = True
            if text.startswith(('.end packed-switch', '.end sparse-switch', '.end array-data')):
                payload = False
                continue
            if payload or not text or text.startswith(('.', ':', '#')):
                continue
            instructions.append(index)
        if not instructions:
            raise ValueError('No executable instructions in target method')
        if where == 'entry':
            # Before labels/try regions preceding the first opcode: executes on entry,
            # not on loop back-edges. Debug directives remain untouched.
            insertion = instructions[0]
            while insertion > start + 1 and (not lines[insertion - 1].strip() or lines[insertion - 1].strip().startswith((':', '.line ', '#', '.prologue'))):
                insertion -= 1
            points = [insertion]
        elif where == 'returns':
            points = [i for i in instructions if lines[i].strip().split()[0].startswith('return')]
        else:
            if line is None or not source_sha256:
                raise ValueError('Line markers require --line and --source-sha256')
            if line - 1 not in instructions:
                raise ValueError('Line must identify an executable instruction inside the target method')
            opcode = lines[line - 1].strip().split()[0]
            if opcode.startswith(('move-result', 'move-exception')):
                raise ValueError('Cannot insert before move-result/move-exception; their instruction ordering is constrained')
            points = [line - 1]
        if not points:
            raise ValueError('No matching marker sites')
        marker = hashlib.sha256((symbol + label + where + str(time.time_ns())).encode()).hexdigest()[:16]
        descriptor = 'Lhermes/apklab/trace/T' + marker + ';'
        relative = path.relative_to(p / 'decoded/apktool')
        helper = p / 'decoded/apktool' / relative.parts[0] / 'hermes/apklab/trace' / ('T' + marker + '.smali')
        helper.parent.mkdir(parents=True, exist_ok=True)
        if helper.exists():
            raise ValueError('Diagnostic helper collision')
        helper.write_text(f'''.class public final {descriptor}
.super Ljava/lang/Object;
.method public static hit()V
    .locals 2
    const-string v0, "APKLAB"
    const-string v1, "{marker} {label}"
    invoke-static {{v0, v1}}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method
''')
        backup = p / 'patches/instrumentation' / marker
        backup.mkdir(parents=True)
        (backup / 'before.smali').write_text(''.join(lines))
        for index in reversed(points):
            lines.insert(index, f'    invoke-static {{}}, {descriptor}->hit()V\n')
        path.write_text(''.join(lines))
        record = {'marker': marker, 'symbol': symbol, 'label': label, 'where': where,
                  'source': str(path), 'before_sha256': original_hash, 'after_sha256': sha256(path),
                  'original_lines': [i + 1 for i in points], 'helper': str(helper), 'helper_sha256': sha256(helper),
                  'diagnostic_only': True, 'note': 'Marker execution only; no payload capture or proof of network delivery.'}
        atomic_json(backup / 'record.json', record)
        log = p / 'patches/CHANGELOG.md'
        with log.open('a') as stream:
            stream.write(f'\nDiagnostic marker {marker}: {symbol}, {where}, {label}. Remove before final delivery.\n')
        event(job_id, 'instrumentation', **record)
        return {'record': str(backup / 'record.json'), **record}


def remove(job_id, marker):
    from .core import inside, read_json
    if not re.fullmatch(r'[a-f0-9]{16}', marker):
        raise ValueError('Invalid marker id')
    p = job_dir(job_id)
    with lock(p / '.operation.lock', blocking=False):
        directory = p / 'patches/instrumentation' / marker
        record = read_json(directory / 'record.json')
        if not record or record.get('removed'):
            raise ValueError('Unknown or already removed marker')
        source = inside(record['source'], p / 'decoded/apktool')
        helper = inside(record['helper'], p / 'decoded/apktool')
        if sha256(source) != record['after_sha256'] or sha256(helper) != record['helper_sha256']:
            raise ValueError('Instrumented sources changed; remove later markers first or review a manual diff')
        original = directory / 'before.smali'
        if sha256(original) != record['before_sha256']:
            raise ValueError('Backup hash changed')
        source.write_bytes(original.read_bytes())
        helper.unlink()
        record['removed'] = True
        atomic_json(directory / 'record.json', record)
        event(job_id, 'instrumentation_removed', marker=marker)
        return {'removed': marker, 'source_sha256': sha256(source)}

"""ELF triage and persistent headless Ghidra analysis of a selected APK library."""
import shutil
import time
import zipfile
from pathlib import Path, PurePosixPath

from .core import PROJECT, atomic_json, event, inside, job_dir, lock, read_json, sha256
from .pipeline import archive_info, checked, input_apk, required, tools


def analyze(job_id, member, decompile=False, function='*', limit=25):
    if not 1 <= limit <= 100:
        raise ValueError('Function limit must be 1..100')
    if not function or function.startswith('-') or any(c in function for c in '\r\n\0'):
        raise ValueError('Invalid Ghidra function selector')
    # APK path is a zip member, never a shell command or output path.
    parts = PurePosixPath(member).parts
    if len(parts) != 3 or parts[0] != 'lib' or parts[2].startswith('-') or not parts[2].endswith('.so') or any(x in {'.', '..'} for x in parts):
        raise ValueError('Select an exact lib/ABI/name.so member from inventory')
    p = job_dir(job_id)
    with lock(p / '.operation.lock', blocking=False):
        apk = input_apk(job_id)
        inventory = archive_info(apk)
        if member not in inventory['native_libraries']:
            raise ValueError('Library not present in original APK')
        with zipfile.ZipFile(apk) as archive:
            if archive.getinfo(member).file_size > 1024**3:
                raise ValueError('Selected ELF exceeds the 1 GiB analysis limit')
            folder = p / 'decoded/native-input' / parts[1]
            folder.mkdir(parents=True, exist_ok=True)
            library = inside(folder / parts[2], p)
            with archive.open(member) as source, library.open('wb') as target:
                shutil.copyfileobj(source, target, 1024**2)
        with library.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                raise ValueError('Selected .so is not an ELF binary')
        digest = sha256(library)
        base = p / 'analysis/native' / digest
        output = base / str(time.time_ns())
        output.mkdir(parents=True)
        result = {'library': member, 'library_sha256': digest, 'input_sha256': sha256(apk),
                  'output': str(output), 'reports': {}, 'decompile_requested': decompile,
                  'limitations': ['Recovered symbols/strings are candidates; stripped names and original C++ source are not restored.',
                                  'Static references do not prove JNI registration, virtual dispatch or runtime reachability.']}
        for tool, args, name in [('readelf', ['-h', '-d', '-W', '--dyn-syms'], 'elf'),
                                 ('nm', ['-D', '-C'], 'symbols'), ('strings', ['-a', '-t', 'x', '-n', '5'], 'strings')]:
            if not tools().get(tool):
                result['reports'][name] = {'unavailable': tool}
                continue
            report = checked(job_id, 'native-' + name, [required(tool), *args, str(library)], 120)
            target = output / (name + '.txt')
            shutil.copyfile(report['log'], target)
            result['reports'][name] = {'path': str(target), 'sha256': sha256(target)}
        if decompile:
            launcher = required('analyzeHeadless')
            projects = p / 'decoded/ghidra' / digest
            projects.mkdir(parents=True, exist_ok=True)
            state_path = base / 'project.json'
            state = read_json(state_path, {})
            reusable = state.get('complete') and (projects / (state.get('name', '') + '.gpr')).is_file()
            name = state['name'] if reusable else 'library_' + str(time.time_ns())
            command = [launcher, str(projects), name]
            command += ['-process', parts[2], '-noanalysis'] if reusable else ['-import', str(library)]
            command += ['-analysisTimeoutPerFile', '300', '-max-cpu', '2', '-scriptPath', str(PROJECT / 'scripts/ghidra'),
                        '-postScript', 'ApkLabExport.java', str(output), function, str(limit)]
            result['ghidra_command'] = checked(job_id, 'ghidra', command, timeout=600 + limit * 35)
            summary = read_json(output / 'summary.json')
            if not summary:
                raise ValueError('Ghidra produced no summary; read the headless log')
            result['ghidra'] = summary
            result['project_reused'] = bool(reusable)
            atomic_json(state_path, {'name': name, 'library_sha256': digest,
                                    'complete': not summary['analysis_timed_out']})
        atomic_json(output / 'report.json', result)
        event(job_id, 'native_analysis', library=member, sha256=digest, report=str(output / 'report.json'))
        return result

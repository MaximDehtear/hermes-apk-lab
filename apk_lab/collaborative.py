"""Persistent human/agent turn ownership and evidence-backed investigation memory."""
import time
import subprocess
from pathlib import Path

from .core import atomic_json, event, get_job, inside, job_dir, list_jobs, lock, read_json, root, sha256, update_job


def set_mode(job_id, mode):
    if mode not in {'auto', 'assisted', 'manual'}:
        raise ValueError('Mode must be auto, assisted or manual')
    with lock(job_dir(job_id) / '.collaboration.lock'):
        job = update_job(job_id, work_mode=mode, control_owner='user' if mode == 'manual' else 'agent')
        event(job_id, 'work_mode', mode=mode, owner=job['control_owner'])
        return job


def require_agent(job_id):
    job = get_job(job_id)
    if job['phase'] == 'paused':
        raise ValueError('Job is paused')
    if job.get('work_mode') not in {'auto', 'assisted', 'manual'}:
        raise ValueError('Choose work-mode auto, assisted or manual before device mutations')
    if job.get('control_owner') != 'agent':
        raise ValueError('User owns the device turn; wait for their ready message, then handoff agent. Observations remain available.')
    serial = job.get('device', {}).get('serial')
    conflicts = [other['id'] for other in list_jobs() if other['id'] != job_id
                 and other['phase'] != 'done' and other.get('control_owner') == 'user'
                 and serial and other.get('device', {}).get('serial') == serial]
    if conflicts:
        raise ValueError('User owns this device in another job: ' + ', '.join(conflicts))


def handoff(job_id, owner, note):
    if owner not in {'user', 'agent'} or not note.strip():
        raise ValueError('Handoff requires user/agent and a concrete note')
    with lock(job_dir(job_id) / '.collaboration.lock'):
        job = get_job(job_id)
        if not job.get('work_mode'):
            raise ValueError('Choose work-mode first')
        sequence = job.get('handoff_sequence', 0) + 1
        record = {'sequence': sequence, 'owner': owner, 'note': note, 'time': time.time(),
                  'mode': job['work_mode'], 'device': job.get('device', {}),
                  'build_sha256': job.get('verification', {}).get('sha256')}
        path = job_dir(job_id) / 'tests' / f'handoff-{sequence:04d}.json'
        atomic_json(path, record)
        result = update_job(job_id, control_owner=owner, handoff_sequence=sequence,
                            next_action=note, last_handoff=str(path))
        event(job_id, 'handoff', **record)
        return result


def observe(job_id, label, build_sha256=None):
    # Observation must not install, launch, tap, reset, force-stop or clear logs.
    from . import device
    device.selected(job_id)
    result = {'time': time.time(), 'label': label, 'control_owner': get_job(job_id).get('control_owner'),
              'observations': {}, 'errors': {}, 'note': 'Snapshot of current state; intervening human actions are not reconstructed automatically.'}
    for name, operation in [('screen', lambda: device.screenshot(job_id, label, build_sha256)),
                            ('hierarchy', lambda: device.hierarchy(job_id)),
                            ('logcat', lambda: device.capture_logcat(job_id))]:
        try:
            result['observations'][name] = operation()
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            result['errors'][name] = str(error)
    path = job_dir(job_id) / 'tests' / f'observation-{time.time_ns()}.json'
    atomic_json(path, result)
    event(job_id, 'observation', path=str(path), errors=result['errors'])
    return {'path': str(path), **result}


def knowledge_dir(job_id):
    inp = get_job(job_id).get('input')
    if not inp or sha256(inp['path']) != inp['sha256']:
        raise ValueError('Unchanged original input required for scoped memory')
    return root() / 'knowledge' / inp['sha256']


def remember(job_id, spec_path):
    source = inside(spec_path, job_dir(job_id))
    if source.stat().st_size > 65536:
        raise ValueError('Memory record must be at most 64 KiB')
    item = read_json(source)
    if not isinstance(item, dict) or item.get('kind') not in {'alias', 'procedure'}:
        raise ValueError('Memory kind must be alias or procedure')
    if item['kind'] == 'alias':
        if not all(isinstance(item.get(k), str) and item[k].strip() for k in ['symbol', 'label']):
            raise ValueError('Alias requires original symbol and readable label')
        if item.get('basis') not in {'named', 'inferred', 'runtime'}:
            raise ValueError('Alias basis must be named, inferred or runtime')
    else:
        if not all(isinstance(item.get(k), str) and item[k].strip() for k in ['name', 'precondition']) or item.get('result') not in {'demonstrated', 'reproduced', 'failed'}:
            raise ValueError('Procedure requires name, precondition and demonstrated/reproduced/failed result')
        if not isinstance(item.get('steps'), list) or not 0 < len(item['steps']) <= 100 or not all(isinstance(x, str) and x.strip() for x in item['steps']):
            raise ValueError('Procedure requires 1..100 explicit steps')
    if (not isinstance(item.get('evidence'), list) or not 0 < len(item['evidence']) <= 64
            or not all(isinstance(x, str) and x.strip() for x in item['evidence'])):
        raise ValueError('Memory needs evidence paths inside this job')
    evidence = []
    for value in item['evidence']:
        path = inside(job_dir(job_id) / value, job_dir(job_id))
        if not path.is_file():
            raise ValueError('Missing memory evidence: ' + value)
        evidence.append({'file': str(path), 'sha256': sha256(path)})
    with lock(job_dir(job_id) / '.memory.lock'):
        directory = knowledge_dir(job_id)
        item.update(job_id=job_id, input_sha256=get_job(job_id)['input']['sha256'],
                    declared_build_sha256=get_job(job_id).get('verification', {}).get('sha256'),
                    device=get_job(job_id).get('device', {}),
                    recorded_at=time.time(), evidence_hashes=evidence,
                    scope='This exact APK hash; procedures are observations, not executable instructions.')
        name = f'{item["kind"]}-{time.time_ns()}.json'
        local = job_dir(job_id) / 'analysis' / 'memory' / name
        atomic_json(local, item)
        atomic_json(directory / name, item)
        event(job_id, 'memory', path=str(local), kind_record=item['kind'])
        return {'path': str(local), 'shared_path': str(directory / name), 'record': item}


def memories(job_id):
    directory = knowledge_dir(job_id)
    records = []
    for path in sorted(directory.glob('*.json')):
        item = read_json(path)
        item['evidence_intact'] = all(Path(e['file']).is_file() and sha256(e['file']) == e['sha256'] for e in item['evidence_hashes'])
        records.append(item)
    return {'records': records, 'scope': directory.name,
            'note': 'Append-only observations: review later failed attempts; never auto-execute or treat a label as proven semantics.'}

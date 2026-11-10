"""Bounded, fresh-process experiments with explicit evidence, never inferred verdicts."""
import json
import os
import platform
import re
import shutil
import time
from pathlib import Path

from . import core, pipeline


def _file(base, value):
    if not isinstance(value, str):
        raise ValueError('Expected a job-relative file path')
    path = core.inside(base / value, base)
    if not path.is_file():
        raise ValueError('Missing experiment input: ' + value)
    return path


def validate(spec):
    if not isinstance(spec, dict) or spec.get('version') != 1:
        raise ValueError('Experiment schema version must be 1')
    argv = spec.get('argv')
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and '\0' not in x for x in argv):
        raise ValueError('argv must be a nonempty string array (no shell expansion)')
    for key, default, maximum in [('timeout', 30, 3600), ('repeats', 2, 20)]:
        v = spec.get(key, default)
        if type(v) is not int or not 1 <= v <= maximum:
            raise ValueError(f'{key} must be 1..{maximum}')
    cases = spec.get('cases')
    if not isinstance(cases, list) or not 1 <= len(cases) <= 10000:
        raise ValueError('Provide 1..10000 explicit cases')
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(case.get('id', ''))):
            raise ValueError('Each case needs a simple id')
        if case['id'] in ids or 'input' not in case:
            raise ValueError('Duplicate case id or missing input')
        ids.add(case['id'])
    if not isinstance(spec.get('files'), list) or not spec['files']:
        raise ValueError('files must list the harness and all data dependencies')
    if not isinstance(spec.get('assumptions', []), list):
        raise ValueError('assumptions must be a list')
    return spec


def run(job_id, specification):
    base = core.job_dir(job_id)
    core.get_job(job_id)
    spec = validate(core.read_json(specification))
    with core.lock(base / '.operation.lock', blocking=False):
        if core.get_job(job_id)['phase'] == 'paused':
            raise ValueError('Job is paused')
        apk_hash = core.sha256(pipeline.input_apk(job_id))
        files = [_file(base, name) for name in spec['files']]
        executable = shutil.which(spec['argv'][0])
        if not executable:
            raise ValueError('Executable unavailable: ' + spec['argv'][0])
        hashes = {str(p.relative_to(base)): core.sha256(p) for p in files}
        folder = base / 'analysis/experiments' / str(time.time_ns())
        folder.mkdir(parents=True)
        core.atomic_json(folder / 'spec.json', spec)
        report = {'version': 1, 'input_sha256': apk_hash, 'files': hashes,
                  'executable': str(Path(executable).resolve()), 'executable_sha256': core.sha256(Path(executable)),
                  'host': {'system': platform.system(), 'machine': platform.machine(), 'python': platform.python_version()},
                  'assumptions': spec.get('assumptions', []), 'runs': [], 'status': 'running',
                  'verdict': 'unverified', 'report': str(folder / 'report.json')}
        core.atomic_json(folder / 'report.json', report)
        try:
            for case in spec['cases']:
                for repeat in range(spec.get('repeats', 2)):
                    if core.get_job(job_id)['phase'] == 'paused':
                        raise ValueError('Job paused; remaining cases not executed')
                    dest = folder / f"{case['id']}-{repeat}"
                    dest.mkdir()
                    request, response = dest / 'request.json', dest / 'response.json'
                    core.atomic_json(request, case['input'])
                    env = os.environ.copy()
                    env.update(APK_LAB_REQUEST=str(request), APK_LAB_RESPONSE=str(response),
                               APK_LAB_OUTPUT=str(dest), PYTHONUNBUFFERED='1')
                    record = {'case': case['id'], 'repeat': repeat, 'request_sha256': core.sha256(request)}
                    record.update(pipeline.run(job_id, 'experiment', spec['argv'], spec.get('timeout', 30), env))
                    record['status'] = 'timeout_or_cancelled' if record['interrupted'] else 'execution_failed'
                    if record['exit_code'] == 0 and not record['interrupted']:
                        try:
                            if response.is_symlink() or response.stat().st_size > 1024**2:
                                raise ValueError('Response must be a regular JSON file <=1 MiB')
                            payload = json.loads(response.read_text())
                            if not isinstance(payload, dict) or 'observation' not in payload:
                                raise ValueError('Response must contain observation')
                            record.update(status='observed', observation=payload['observation'], response_sha256=core.sha256(response))
                            if 'expected' in case:
                                record['matches_expected'] = payload['observation'] == case['expected']
                        except (OSError, ValueError) as exc:
                            record.update(status='invalid_response', error=str(exc))
                    report['runs'].append(record)
                    core.atomic_json(folder / 'report.json', report)
            report['status'] = 'complete'
        except (Exception, KeyboardInterrupt) as exc:
            report.update(status='interrupted', error=str(exc))
            raise
        finally:
            report['coverage'] = {'planned': len(spec['cases']) * spec.get('repeats', 2),
                                  'attempted': len(report['runs']),
                                  'observed': sum(r['status'] == 'observed' for r in report['runs'])}
            report['inputs_unchanged'] = all(p.is_file() and core.sha256(p) == hashes[str(p.relative_to(base))] for p in files)
            report['repeatable'] = report['status'] == 'complete' and spec.get('repeats', 2) > 1 and all(
                len(rs := [r for r in report['runs'] if r['case'] == c['id'] and r['status'] == 'observed']) == spec.get('repeats', 2)
                and all(r['observation'] == rs[0]['observation'] for r in rs) for c in spec['cases'])
            core.atomic_json(folder / 'report.json', report)
            core.event(job_id, 'experiment', report=report['report'], status=report['status'])
        return report


def compare(job_id, left, right):
    """Compare recorded observations; agreement alone does not establish independence."""
    base = core.job_dir(job_id)
    a, b = (_file(base, name) for name in (left, right))
    reports = [core.read_json(p) for p in (a, b)]
    if any(not isinstance(r, dict) or r.get('version') != 1 or r.get('status') != 'complete' for r in reports):
        raise ValueError('Comparison requires two completed experiment reports')
    for report in reports:
        runs = report.get('runs')
        if not isinstance(runs, list) or not isinstance(report.get('input_sha256'), str):
            raise ValueError('Malformed experiment report')
        seen = set()
        for record in runs:
            if not isinstance(record, dict) or not all(k in record for k in ('case', 'repeat', 'status', 'request_sha256')):
                raise ValueError('Malformed experiment run')
            if not isinstance(record['case'], str) or type(record['repeat']) is not int:
                raise ValueError('Malformed case identity')
            key = record['case'], record['repeat']
            if key in seen or (record['status'] == 'observed' and 'observation' not in record):
                raise ValueError('Duplicate or incomplete experiment run')
            seen.add(key)
    if reports[0]['input_sha256'] != reports[1]['input_sha256']:
        raise ValueError('Reports refer to different APKs')
    def index(r):
        return {(x['case'], x['repeat']): x for x in r['runs']}
    x, y = map(index, reports)
    keys = x.keys() | y.keys()
    mismatches = [list(k) for k in sorted(keys) if k not in x or k not in y or
                  x[k]['status'] != 'observed' or y[k]['status'] != 'observed' or
                  x[k]['request_sha256'] != y[k]['request_sha256'] or x[k]['observation'] != y[k]['observation']]
    result = {'reports': [str(a), str(b)], 'sha256': [core.sha256(a), core.sha256(b)],
              'agreement': bool(keys) and not mismatches, 'mismatches': mismatches,
              'verdict': 'unverified', 'note': 'Establish independent provenance and original-app controls before accepting a hypothesis.'}
    out = base / 'analysis/experiments' / ('comparison-' + str(time.time_ns()) + '.json')
    core.atomic_json(out, result)
    core.event(job_id, 'experiment_comparison', report=str(out))
    return result


def memory_diff(job_id, left, right, limit=64):
    base = core.job_dir(job_id)
    if not 1 <= limit <= 1000:
        raise ValueError('limit must be 1..1000')
    paths = [_file(base, v) for v in (left, right)]
    offsets, changed, offset = [], 0, 0
    with paths[0].open('rb') as a, paths[1].open('rb') as b:
        while True:
            x, y = a.read(65536), b.read(65536)
            if not x and not y:
                break
            for i in range(max(len(x), len(y))):
                if x[i:i+1] != y[i:i+1]:
                    changed += 1
                    if len(offsets) < limit:
                        offsets.append(offset + i)
            offset += max(len(x), len(y))
    result = {'files': [str(p) for p in paths], 'sha256': [core.sha256(p) for p in paths],
              'sizes': [p.stat().st_size for p in paths], 'changed_bytes': changed,
              'first_changed_offsets': offsets, 'offsets_truncated': changed > limit,
              'note': 'File offsets only; align mappings, load bias and capture stage before interpreting differences.'}
    out = base / 'analysis' / ('memory-diff-' + str(time.time_ns()) + '.json')
    core.atomic_json(out, result)
    core.event(job_id, 'memory_diff', report=str(out))
    return result

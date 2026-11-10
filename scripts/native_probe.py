#!/usr/bin/env python3
"""Experiment worker: ELF preflight or bounded instruction emulation, selected by input."""
import json
import os
from pathlib import Path


def preflight(path):
    from elftools.elf.elffile import ELFFile
    with open(path, 'rb') as stream:
        elf = ELFFile(stream)
        segments = [{'vaddr': s['p_vaddr'], 'offset': s['p_offset'], 'filesz': s['p_filesz'],
                     'memsz': s['p_memsz'], 'flags': s['p_flags']} for s in elf.iter_segments()
                    if s['p_type'] == 'PT_LOAD']
        needed, imports, relocations = [], [], {}
        initializers, warnings = {}, []
        tls = any(s['p_type'] == 'PT_TLS' for s in elf.iter_segments())
        for section in elf.iter_sections():
            if section['sh_type'] == 'SHT_DYNAMIC':
                for tag in section.iter_tags():
                    if tag.entry.d_tag == 'DT_NEEDED':
                        needed.append(tag.needed)
                    elif tag.entry.d_tag in {'DT_INIT', 'DT_INIT_ARRAY', 'DT_INIT_ARRAYSZ'}:
                        initializers[tag.entry.d_tag] = tag.entry.d_val
                    elif tag.entry.d_tag in {'DT_RELR', 'DT_ANDROID_REL', 'DT_ANDROID_RELA'}:
                        warnings.append('Packed relocations require separate decoding: ' + tag.entry.d_tag)
            if section['sh_type'] == 'SHT_DYNSYM':
                imports += [sym.name for sym in section.iter_symbols() if sym['st_shndx'] == 'SHN_UNDEF' and sym.name]
            if section['sh_type'] in {'SHT_RELA', 'SHT_REL'}:
                for rel in section.iter_relocations():
                    key = str(rel['r_info_type'])
                    relocations[key] = relocations.get(key, 0) + 1
        return {'machine': elf['e_machine'], 'bits': elf.elfclass, 'little_endian': elf.little_endian,
                'entry': elf['e_entry'], 'load_segments': segments, 'needed': needed,
                'initializers': initializers, 'tls_segment': tls, 'warnings': warnings,
                'undefined_symbols': imports, 'relocation_types': relocations,
                'limitations': ['Not a loader compatibility verdict. Check Bionic, TLS, constructors, JNI and all relocation types.']}


def emulate(request):
    import unicorn as uc
    from unicorn import x86_const, arm64_const, arm_const
    architectures = {'x86_64': (uc.UC_ARCH_X86, uc.UC_MODE_64, x86_const, 'UC_X86_REG_'),
                     'arm64': (uc.UC_ARCH_ARM64, uc.UC_MODE_ARM, arm64_const, 'UC_ARM64_REG_'),
                     'arm': (uc.UC_ARCH_ARM, uc.UC_MODE_ARM, arm_const, 'UC_ARM_REG_'),
                     'thumb': (uc.UC_ARCH_ARM, uc.UC_MODE_THUMB, arm_const, 'UC_ARM_REG_')}
    arch, mode, constants, prefix = architectures[request['architecture']]
    engine = uc.Uc(arch, mode)
    regions = request['regions']
    if not 1 <= len(regions) <= 64 or sum(r['size'] for r in regions) > 256 * 1024**2:
        raise ValueError('Provide 1..64 regions totaling <=256 MiB')
    for region in regions:
        if region['address'] % 4096 or region['size'] <= 0 or region['size'] % 4096:
            raise ValueError('Regions must be page aligned')
        engine.mem_map(region['address'], region['size'], region.get('permissions', uc.UC_PROT_ALL))
        if 'file' in region:
            data = Path(region['file']).read_bytes()
            if len(data) > region['size']:
                raise ValueError('File exceeds region')
            engine.mem_write(region['address'], data)
    def register(name):
        value = getattr(constants, prefix + name.upper(), None)
        if value is None:
            raise ValueError('Unknown architecture register: ' + name)
        return value
    for name, value in request.get('registers', {}).items():
        engine.reg_write(register(name), value)
    count = request.get('instruction_limit', 100000)
    if type(count) is not int or not 1 <= count <= 10000000:
        raise ValueError('instruction_limit must be 1..10000000')
    trace, executed, last = [], 0, None
    def hook(_engine, address, size, _user):
        nonlocal executed, last
        executed += 1
        last = address
        if len(trace) < 256:
            trace.append({'address': address, 'size': size})
    engine.hook_add(uc.UC_HOOK_CODE, hook)
    status, error = 'stopped', None
    try:
        engine.emu_start(request['start'], request['until'], timeout=5000000, count=count)
        if engine.query(uc.UC_QUERY_TIMEOUT):
            status = 'timeout'
        elif executed >= count:
            status = 'instruction_limit'
    except uc.UcError as exc:
        status, error = 'fault', str(exc)
    reads = request.get('read_memory', [])
    if sum(r['size'] for r in reads) > 65536 or any(r['size'] < 0 for r in reads):
        raise ValueError('Memory observations limited to 64 KiB')
    return {'status': status, 'error': error, 'executed': executed, 'last_address': last,
            'trace': trace, 'trace_truncated': executed > len(trace),
            'registers': {n: engine.reg_read(register(n)) for n in request.get('read_registers', [])},
            'memory': [{'address': r['address'], 'hex': bytes(engine.mem_read(r['address'], r['size'])).hex()} for r in reads]}


def main():
    request = json.loads(Path(os.environ['APK_LAB_REQUEST']).read_text())
    if request['operation'] == 'elf':
        observation = preflight(request['file'])
    elif request['operation'] == 'emulate':
        observation = emulate(request)
    else:
        raise ValueError('operation must be elf or emulate')
    Path(os.environ['APK_LAB_RESPONSE']).write_text(json.dumps({'observation': observation}))


if __name__ == '__main__':
    main()

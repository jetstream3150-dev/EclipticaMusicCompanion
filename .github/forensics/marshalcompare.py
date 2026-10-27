"""Compare the contents of CPython 3.14 marshalled code without executing it.

This diagnostic preserves code fields and constants while normalizing marshal's
reference indexes and its alternative encodings for otherwise equal strings.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys
import types
import zipfile
import zlib


def encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode('ascii')


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.refs = []

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError('Malformed marshal length')
        result = self.data[self.pos:self.pos+n]
        self.pos += n
        return result

    def byte(self):
        return self.take(1)[0]

    def integer(self):
        return struct.unpack('<i', self.take(4))[0]

    def object(self):
        tag = self.byte()
        flag = bool(tag & 0x80)
        tag = chr(tag & 0x7f)
        if tag == 'r':
            index = self.integer()
            if flag or index < 0 or index >= len(self.refs) or self.refs[index] is None:
                raise ValueError('Invalid marshal reference')
            return self.refs[index]
        index = None
        if flag:
            index = len(self.refs)
            self.refs.append(None)
        if tag in 'NFTS.0':
            value = ['singleton', tag]
        elif tag == 'i':
            value = ['int', self.integer()]
        elif tag == 'I':
            value = ['int', struct.unpack('<q', self.take(8))[0]]
        elif tag == 'l':
            count = self.integer()
            number = 0
            for i in range(abs(count)):
                digit = struct.unpack('<H', self.take(2))[0]
                if digit >= 32768:
                    raise ValueError('Invalid marshal long digit')
                number += digit << (15*i)
            value = ['int', -number if count < 0 else number]
        elif tag in 'gy':
            value = ['float' if tag == 'g' else 'complex', self.take(8 if tag == 'g' else 16).hex()]
        elif tag in 'fx':
            parts = [self.take(self.byte()).decode('ascii') for _ in range(1 if tag == 'f' else 2)]
            value = ['legacy-float' if tag == 'f' else 'legacy-complex', parts]
        elif tag == 's':
            value = ['bytes', self.take(self.integer()).hex()]
        elif tag in 'aAtu':
            value = ['str', self.take(self.integer()).decode('utf8', 'surrogatepass')]
        elif tag in 'zZ':
            value = ['str', self.take(self.byte()).decode('ascii')]
        elif tag in '([<>)':
            count = self.byte() if tag == ')' else self.integer()
            if count < 0 or count > len(self.data):
                raise ValueError('Invalid marshal sequence length')
            items = [self.object() for _ in range(count)]
            kind = {'(': 'tuple', ')': 'tuple', '[': 'list', '<': 'set', '>': 'frozenset'}[tag]
            if tag in '<>':
                items.sort(key=encoded)
            value = [kind, items]
        elif tag == '{':
            items = []
            while True:
                key = self.object()
                if key == ['singleton', '0']:
                    break
                items.append([key, self.object()])
            items.sort(key=encoded)
            value = ['dict', items]
        elif tag == ':':
            value = ['slice', self.object(), self.object(), self.object()]
        elif tag == 'c':
            integers = [self.integer() for _ in range(5)]
            objects = [self.object() for _ in range(8)]
            first_line = self.integer()
            value = ['code', integers, objects, first_line, self.object(), self.object()]
        else:
            raise ValueError('Unsupported marshal type: ' + repr(tag))
        if flag:
            self.refs[index] = value
        return value


def digest(data):
    reader = Reader(data)
    value = reader.object()
    if reader.pos != len(data):
        raise ValueError('Trailing bytes after marshal value')
    return hashlib.sha256(encoded(value)).hexdigest()


def top_fields(data):
    reader = Reader(data)
    code = reader.object()
    if reader.pos != len(data) or code[0] != 'code':
        raise ValueError('Expected one code object')
    names = ('instructions', 'constants', 'names', 'localsplusnames',
             'localspluskinds', 'filename', 'name', 'qualname')
    result = dict(zip(names, code[2]))
    result.update(integers=code[1], firstlineno=code[3],
                  linetable=code[4], exceptiontable=code[5])
    return {name: hashlib.sha256(encoded(value)).hexdigest() for name, value in result.items()}


def extract_build_modules(archive_path):
    with zipfile.ZipFile(archive_path) as archive:
        executable = archive.read('EclipticaMusicCompanion.exe')
    magic = b'MEI\014\013\012\013\016'
    cookie = executable.rfind(magic)
    if cookie < 0:
        raise ValueError('No PyInstaller cookie')
    fmt = '!8sIIII64s'
    _, length, toc_offset, toc_length, version, _ = struct.unpack_from(fmt, executable, cookie)
    if version != 314:
        raise ValueError('Unexpected bundled Python version')
    start = cookie + struct.calcsize(fmt) - length
    pos = start + toc_offset
    end = pos + toc_length
    result = {}
    while pos < end:
        size, offset, compressed, uncompressed, flag, kind = struct.unpack_from('!IIIIBc', executable, pos)
        if size < 18 or pos + size > end:
            raise ValueError('Invalid PyInstaller table of contents')
        name = executable[pos+18:pos+size].rstrip(b'\0').decode('utf8')
        if name in ('EclipticaMusic', 'PYZ.pyz'):
            value = executable[start+offset:start+offset+compressed]
            if flag:
                value = zlib.decompress(value)
            if len(value) != uncompressed:
                raise ValueError('Unexpected payload length')
            result[name] = value
        pos += size
    pyz = result.pop('PYZ.pyz')
    if pyz[:4] != b'PYZ\0':
        raise ValueError('Invalid PYZ archive')
    # This TOC is only tuples, strings and integers; it contains no code.
    import marshal
    toc = dict(marshal.loads(pyz[struct.unpack_from('!i', pyz, 8)[0]:]))
    for module in ('combat_meter', 'vrchat_identity', 'boss_weakness', 'alert_sound'):
        kind, offset, size = toc[module]
        if kind != 0:
            raise ValueError('Expected Python module: ' + module)
        result[module] = zlib.decompress(pyz[offset:offset+size])
    return result


def anonymize(code, name):
    constants = tuple(anonymize(c, name) if isinstance(c, types.CodeType) else c for c in code.co_consts)
    return code.replace(co_consts=constants, co_filename=name)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'build':
        for name, data in extract_build_modules(sys.argv[2]).items():
            print(name, digest(data), 'raw', hashlib.sha256(data).hexdigest())
            print(name, 'fields', json.dumps(top_fields(data), sort_keys=True))
    elif len(sys.argv) == 2 and sys.argv[1] == 'sources':
        import marshal
        if sys.version_info[:3] != (3, 14, 10):
            raise ValueError('Expected CPython 3.14.10')
        expected = {
            'EclipticaMusic': '182c238407ee19f9e3308c82e956521959a01f8f4ae151857e85bda397ec4501',
            'combat_meter': '3580c64465372a1e45dc4a1d0113068faafef6c9c9e3e0d0f4f9c1060534da30',
            'vrchat_identity': 'e434f4e59c45e1e53a77df006b985de7e4cceb2f4484bc98f883552cf9a11743',
            'boss_weakness': '72b8357171c725778b1b02164d28aab61fab97a840bf0fd614c229f50c211a2d',
            'alert_sound': 'ef5a0121a845286d5350f3960e2c2b2dd3a2eebaf8347ff9af1ac13a979b3aff',
        }
        mismatch = []
        for module, build_digest in expected.items():
            name = module + '.py'
            code = anonymize(compile(Path(name).read_bytes(), str(Path(name).resolve()), 'exec', optimize=0), name)
            data = marshal.dumps(code)
            actual = digest(data)
            print(module, 'compiled:', actual, 'build 34:', build_digest)
            print(module, 'fields', json.dumps(top_fields(data), sort_keys=True))
            if actual != build_digest:
                mismatch.append(module)
        if mismatch:
            raise ValueError('Code contents differ; investigate: ' + ', '.join(mismatch))
        print('PASS: five application modules match the independently compiled source code objects.')
        print('LIMITATION: this does not validate third-party binaries or prove the distribution is safe.')
    else:
        raise SystemExit('Usage: marshalcompare.py build ZIP | sources')

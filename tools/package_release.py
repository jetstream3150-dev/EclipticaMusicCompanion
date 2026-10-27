"""Build and verify a ZIP from an already audited Windows bundle.

The archive is kept in the runner's temporary directory while distribution is
on hold. A successful package check does not establish malware clearance.
"""
import argparse
import hashlib
from pathlib import Path
import re
import sys
import zipfile


METADATA = {'BUNDLE_AUDIT.json', 'DEFENDER_SCAN.txt', 'SHA256SUMS.txt'}


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def package(source, target):
    source = Path(source).resolve()
    target = Path(target).resolve()
    if not source.is_dir():
        raise ValueError('The build directory does not exist')
    if target == source or source in target.parents:
        raise ValueError('The ZIP must be outside the build directory')
    if target.exists():
        raise ValueError('The ZIP target already exists')
    if not (source / 'EclipticaMusicCompanion.exe').is_file():
        raise ValueError('The application executable is missing')
    if any(not (source / name).is_file() for name in METADATA):
        raise ValueError('The audit manifest or Defender report is missing')
    report = (source / 'DEFENDER_SCAN.txt').read_text(encoding='utf-8-sig')
    if 'PASSED: Defender completed a custom scan with no matching detections.' not in report or 'SCAN FAILED:' in report:
        raise ValueError('The Defender scan was not verified as successful')

    paths = {}
    for file in source.rglob('*'):
        if file.is_symlink():
            raise ValueError('Symbolic links are not allowed in the distribution')
        if file.is_file():
            paths[file.relative_to(source).as_posix()] = file

    expected = {}
    for line in (source / 'SHA256SUMS.txt').read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{64})  (.+)', line)
        if not match or match.group(2) in expected:
            raise ValueError('Invalid or duplicate entry in SHA256SUMS.txt')
        expected[match.group(2)] = match.group(1).lower()
    if set(expected) != set(paths) - METADATA:
        raise ValueError('Build files do not match the audit manifest')
    for name, digest in expected.items():
        if sha256_file(paths[name]) != digest:
            raise ValueError('Build file differs from its audit manifest: ' + name)

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, file in sorted(paths.items()):
                archive.write(file, arcname=name)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None or set(archive.namelist()) != set(paths):
                raise ValueError('The ZIP failed the integrity check')
            for name, file in paths.items():
                if hashlib.sha256(archive.read(name)).hexdigest() != sha256_file(file):
                    raise ValueError('The ZIP content differs from the build: ' + name)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f'PASS: ZIP contains {len(paths)} verified files')
    print('ZIP SHA-256:', sha256_file(target))
    print('NOTE: ZIP integrity is not a malware or Chrome clearance.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('target')
    args = parser.parse_args()
    try:
        package(args.source, args.target)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print('ZIP CHECK FAILED:', error, file=sys.stderr)
        raise SystemExit(1)

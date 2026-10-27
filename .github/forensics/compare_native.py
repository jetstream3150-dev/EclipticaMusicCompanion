"""Compare build 34 runtime hashes with the pinned official Python install."""
import hashlib
import json
import os
from pathlib import Path


root = Path(os.environ['pythonLocation']).resolve()
expected = json.loads(Path(__file__).with_name('native-expected.json').read_text(encoding='utf8'))
if len(expected) != 25:
    raise RuntimeError('Unexpected number of build 34 runtime fingerprints')

problems = []
for name, target in expected.items():
    candidates = list(root.rglob(name))
    hashes = [(file, hashlib.sha256(file.read_bytes()).hexdigest()) for file in candidates if file.is_file()]
    matched = [str(path.relative_to(root)) for path, value in hashes if value == target]
    print(name, 'PASS' if matched else 'UNMATCHED', 'expected:', target, 'matches:', matched)
    if not matched:
        print('candidate hashes:', [(str(path.relative_to(root)), value) for path, value in hashes])
        problems.append(name)

if problems:
    raise RuntimeError('Runtime files not matched to this Python installation: ' + ', '.join(problems))
print('PASS: 25 Python runtime components match the pinned Python 3.14.10 installation.')
print('LIMITATION: Windows system libraries and other files were not covered by this comparison.')

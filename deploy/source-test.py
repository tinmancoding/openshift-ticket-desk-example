#!/usr/local/bin/python
"""Tekton source gate. Public GitHub only; no credentials and no shell interpolation."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import urllib.request

revision = os.environ['REVISION']
if not re.fullmatch(r'[0-9a-f]{40}', revision):
    raise SystemExit('A full lowercase commit SHA is required')
# ARCHIVE_ROOT is fixed by the reviewed Task definition, not supplied by an event.
url = os.environ['ARCHIVE_ROOT'] + '/' + revision
archive = Path('/work/source.tar.gz')
with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as output:
    total = 0
    while chunk := response.read(1024 * 1024):
        total += len(chunk)
        if total > 50 * 1024 * 1024:
            raise SystemExit('Source archive exceeds classroom limit')
        output.write(chunk)
root = Path('/work/source')
root.mkdir()
with tarfile.open(archive) as source:
    members = source.getmembers()
    if sum(member.size for member in members) > 100 * 1024 * 1024:
        raise SystemExit('Expanded source exceeds classroom limit')
    if any(not (member.isfile() or member.isdir()) for member in members):
        raise SystemExit('Links and special files are not accepted')
    source.extractall(root, filter='data')
children = list(root.iterdir())
if len(children) != 1 or not children[0].is_dir():
    raise SystemExit('Unexpected archive structure')
checkout = children[0]
# Packages go to ephemeral storage; no root, HOME write or system install needed.
subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-cache-dir',
                '--target', '/work/deps', '-r', str(checkout / 'requirements-test.txt')], check=True)
env = dict(os.environ, PYTHONPATH='/work/deps', PYTHONDONTWRITEBYTECODE='1')
test_runner = '''
import sys
import unittest
suite = unittest.defaultTestLoader.discover('tests')
if suite.countTestCases() == 0:
    raise SystemExit('No tests discovered; refusing an empty green gate')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
'''
subprocess.run([sys.executable, '-c', test_runner], cwd=checkout, env=env, check=True)
print('Required source tests passed at', revision)

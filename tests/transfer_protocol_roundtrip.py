"""Run real lrzsz transfers over local sockets, never the hardware adapter."""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

spec = importlib.util.spec_from_file_location('worker', sys.argv[1])
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
for protocol, sender, receiver in [('xmodem', 'sx', 'rx'), ('ymodem', 'sb', 'rb'), ('zmodem', 'sz', 'rz')]:
    with tempfile.TemporaryDirectory(prefix='retromodem-protocol-test-') as directory:
        root = Path(directory)
        worker.ROOT = root
        worker.STATUS = root / 'status.json'
        asset = root / 'payload.bin'
        asset.write_bytes(bytes(range(256)) * 128)
        incoming = root / 'incoming'
        incoming.mkdir()
        left, right = socket.socketpair()
        command = ['/usr/bin/' + receiver, '-vv']
        command += [asset.name] if protocol == 'xmodem' else ['-E']
        receiving = subprocess.Popen(command, stdin=right, stdout=right,
                                     stderr=subprocess.PIPE, cwd=incoming)
        try:
            with left.makefile('rwb', buffering=0) as serial:
                details = {'direction': 'send', 'protocol': protocol}
                code, output = worker.execute_device(['/usr/bin/' + sender, '-vv', str(asset)],
                    root, details, protocol, serial=serial, total_bytes=asset.stat().st_size,
                    inactivity_timeout=15)
            _, errors = receiving.communicate(timeout=15)
            assert code == receiving.returncode == 0, (protocol, output, errors)
            assert (incoming / asset.name).read_bytes() == asset.read_bytes(), protocol
            assert details.get('bytes_transferred', 0) > 0, (protocol, output)
            print(json.dumps({'protocol': protocol, 'payload_matches': True, **details}))
        finally:
            left.close()
            right.close()
            if receiving.poll() is None:
                receiving.kill()
                receiving.wait()

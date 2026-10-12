"""Check the toolkit-generated stdio MCP connection outside the current Codex session."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import tomllib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool')
    parser.add_argument('--arguments', default='{}')
    parser.add_argument('--arguments-file', type=Path)
    options = parser.parse_args()
    root = Path.cwd() / 'dist/aws-verification'
    root.mkdir(parents=True, exist_ok=True)
    entry = tomllib.loads((Path.home() / '.codex/config.toml').read_text())['mcp_servers']['aws-mcp']
    command = entry['command']
    if command == 'uvx':
        command = str(Path.home() / '.local/bin/uvx.exe')
    env = {**os.environ, **entry.get('env', {}), 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    env['PATH'] = str(Path.home() / '.local/bin') + os.pathsep + env.get('PATH', '')
    messages = queue.Queue()
    with (root / 'mcp-stderr.log').open('w', encoding='utf-8') as stderr:
        process = subprocess.Popen([command, *entry['args']], env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=stderr, text=True,
                                   encoding='utf-8', errors='replace')
        def reader():
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except json.JSONDecodeError:
                    pass
            messages.put(None)
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        def send(message):
            process.stdin.write(json.dumps(message) + '\n')
            process.stdin.flush()
        def request(identifier, method, params=None):
            send({'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params or {}})
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                message = messages.get(timeout=max(0.1, deadline-time.monotonic()))
                if message is None:
                    raise RuntimeError('MCP process exited before responding; inspect mcp-stderr.log')
                if message.get('id') == identifier:
                    if 'error' in message:
                        raise RuntimeError(json.dumps(message['error']))
                    return message['result']
            raise TimeoutError('MCP response deadline expired')
        try:
            initialized = request(1, 'initialize', {'protocolVersion': '2025-03-26',
                'capabilities': {}, 'clientInfo': {'name': 'factumdb-integration-audit', 'version': '1.0'}})
            send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            listing = request(2, 'tools/list')
            (root / 'mcp-tools.json').write_text(json.dumps(listing, indent=2), encoding='utf-8')
            print(json.dumps({'server': initialized.get('serverInfo'),
                              'tools': [{'name': tool['name'], 'description': tool.get('description', '')[:140]}
                                        for tool in listing.get('tools', [])]}, indent=2))
            if options.tool:
                arguments = json.loads(options.arguments_file.read_text(encoding='utf-8')
                                       if options.arguments_file else options.arguments)
                result = request(3, 'tools/call', {'name': options.tool, 'arguments': arguments})
                (root / 'mcp-read-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
                print(json.dumps(result, indent=2))
                if result.get('isError'):
                    raise RuntimeError('MCP tool reported an error; inspect mcp-read-verification.json')
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    main()

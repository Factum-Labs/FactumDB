"""Bind toolkit-generated AWS MCP entries to a named profile, preserving other settings."""
import argparse
import copy
import json
from pathlib import Path
import re
import tomllib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='factumdb-benchmark')
    options = parser.parse_args()
    home = Path.home()
    for relative in ('.claude.json', '.cursor/mcp.json', '.gemini/settings.json'):
        path = home / relative
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        entry = data.get('mcpServers', {}).get('aws-mcp')
        if not entry:
            continue
        original = copy.deepcopy(data)
        original_entry = copy.deepcopy(entry)
        entry.setdefault('env', {})['AWS_MCP_PROXY_PROFILES'] = options.profile
        expected = copy.deepcopy(original)
        expected['mcpServers']['aws-mcp'].setdefault('env', {})['AWS_MCP_PROXY_PROFILES'] = options.profile
        if data != expected:
            raise RuntimeError('Unexpected configuration change')
        for key in ('command', 'args', 'timeout', 'transport'):
            if entry.get(key) != original_entry.get(key):
                raise RuntimeError(f'Generated {key} must be preserved')
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print(f'Updated only AWS MCP profile settings: {path}')
    path = home / '.codex/config.toml'
    text = path.read_text(encoding='utf-8')
    original = tomllib.loads(text)
    entry = original.get('mcp_servers', {}).get('aws-mcp')
    if not entry:
        raise RuntimeError('Toolkit-generated Codex AWS MCP entry was not found')
    encoded = json.dumps(options.profile)
    section = '[mcp_servers.aws-mcp.env]'
    if section in text:
        pattern = r'(\[mcp_servers\.aws-mcp\.env\]\s*\n)(.*?)(?=\n\[|\Z)'
        def edit(match):
            body = match.group(2)
            key = r'(?m)^AWS_MCP_PROXY_PROFILES\s*=.*$'
            if re.search(key, body):
                body = re.sub(key, f'AWS_MCP_PROXY_PROFILES = {encoded}', body)
            else:
                body = body.rstrip() + f'\nAWS_MCP_PROXY_PROFILES = {encoded}\n'
            return match.group(1) + body
        text = re.sub(pattern, edit, text, flags=re.DOTALL)
    elif 'env' in entry:
        raise RuntimeError('Existing inline environment requires careful manual merging')
    else:
        text = text.rstrip() + f'\n\n{section}\nAWS_MCP_PROXY_PROFILES = {encoded}\n'
    expected = copy.deepcopy(original)
    expected['mcp_servers']['aws-mcp'].setdefault('env', {})['AWS_MCP_PROXY_PROFILES'] = options.profile
    if tomllib.loads(text) != expected:
        raise RuntimeError('Unexpected TOML changes; no file written')
    path.write_text(text, encoding='utf-8')
    print(f'Updated only AWS MCP profile settings: {path}')


if __name__ == '__main__':
    main()

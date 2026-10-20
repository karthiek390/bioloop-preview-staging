"""Publish only public preview coordinates; keep credentials out of artifacts."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys


FIELDS = {'repository', 'pr', 'sha', 'url', 'ready_at', 'expires_at',
          'deadline_epoch', 'duration_minutes'}


def validate(data, env):
    if set(data) != FIELDS:
        raise ValueError('Unexpected preview readiness fields')
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', data['repository']):
        raise ValueError('Invalid repository')
    if not re.fullmatch(r'https://[a-z0-9-]+\.trycloudflare\.com', data['url']):
        raise ValueError('Invalid protected preview URL')
    if not re.fullmatch(r'[a-f0-9]{40}', data['sha']):
        raise ValueError('Invalid preview SHA')
    if type(data['pr']) is not int or data['pr'] <= 0:
        raise ValueError('Invalid preview PR')
    if type(data['duration_minutes']) is not int or data['duration_minutes'] not in (30, 60, 120):
        raise ValueError('Invalid preview duration')
    for field, setting in (('repository', 'GITHUB_REPOSITORY'), ('sha', 'PREVIEW_SHA')):
        if data[field] != env[setting]:
            raise ValueError('Readiness does not match this run')
    if data['pr'] != int(env['PREVIEW_PR']):
        raise ValueError('Readiness does not match this PR')
    ready = datetime.strptime(data['ready_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    expires = datetime.strptime(data['expires_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    if expires - ready != timedelta(minutes=data['duration_minutes']):
        raise ValueError('Invalid preview lifetime')
    if type(data['deadline_epoch']) is not int or int(expires.timestamp()) != data['deadline_epoch']:
        raise ValueError('Invalid preview deadline')
    return data


def publish(path, url, duration, env):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires = now + timedelta(minutes=duration)
    data = validate({
        'repository': env['GITHUB_REPOSITORY'], 'pr': int(env['PREVIEW_PR']),
        'sha': env['PREVIEW_SHA'], 'url': url,
        'ready_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'expires_at': expires.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'deadline_epoch': int(expires.timestamp()), 'duration_minutes': duration,
    }, env)
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    path.chmod(0o600)
    return data


def main():
    path = Path(os.environ['PREVIEW_STATE_DIR']) / 'preview-ready.json'
    if sys.argv[1] == 'write':
        data = publish(path, sys.argv[2], int(sys.argv[3]), os.environ)
    elif sys.argv[1] == 'read':
        data = validate(json.loads(path.read_text(encoding='utf-8')), os.environ)
    else:
        raise ValueError('Unknown readiness operation')
    for key in ('ready_at', 'expires_at', 'deadline_epoch'):
        print(data[key])


if __name__ == '__main__':
    main()

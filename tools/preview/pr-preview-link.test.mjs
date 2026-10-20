import assert from 'node:assert/strict';
import test from 'node:test';
import { marker, previewComment, publishLink } from './pr-preview-link.mjs';

const env = { GITHUB_EVENT_NAME: 'pull_request_target', GITHUB_REF: 'refs/heads/main', GITHUB_REPOSITORY: 'IUSCA/bioloop' };
const event = { number: 42, pull_request: { state: 'open', base: { ref: 'main', repo: { full_name: env.GITHUB_REPOSITORY } } } };
const bot = { login: 'github-actions[bot]', type: 'Bot' };

test('renders a repository-scoped launcher with the exact PR and clear manual steps', () => {
  const body = previewComment('IUSCA/bioloop', 42);
  assert.ok(body.startsWith(marker));
  assert.ok(body.includes('https://github.com/IUSCA/bioloop/actions/workflows/pr-preview.yml'));
  assert.ok(body.includes('PR number **42**'));
  assert.ok(body.includes('does not start a preview by itself'));
  for (const [repo, number] of [['evil.example/x?url=y', 42], ['IUSCA/bioloop', '42'], ['IUSCA/bioloop', -1]]) {
    assert.throws(() => previewComment(repo, number));
  }
});

test('creates a bot comment without trusting PR title, branch, or user marker text', async () => {
  const calls = [];
  const api = async (path, method, data) => {
    calls.push({ path, method, data });
    return method ? {} : [{ id: 5, user: { login: 'contributor', type: 'User' }, body: marker }];
  };
  assert.equal(await publishLink(env, { ...event, pull_request: { ...event.pull_request, title: '[x](https://evil.example)' } }, api), 'created');
  assert.equal(calls[1].method, 'POST');
  assert.ok(!calls[1].data.body.includes('evil.example'));
});

test('updates only the existing Actions bot launcher', async () => {
  const calls = [];
  const api = async (path, method, data) => {
    calls.push({ path, method, data });
    return method ? {} : [{ id: 7, user: bot, body: marker + '\nOld text' }];
  };
  assert.equal(await publishLink(env, event, api), 'updated');
  assert.equal(calls[1].path, '/repos/IUSCA/bioloop/issues/comments/7');
  assert.equal(calls[1].method, 'PATCH');
});

test('leaves an identical bot comment alone', async () => {
  assert.equal(await publishLink(env, event, async (path, method) => {
    assert.equal(method, undefined);
    return [{ id: 7, user: bot, body: previewComment(env.GITHUB_REPOSITORY, 42) }];
  }), 'unchanged');
});

test('rejects an untrusted event, branch, or base repository before making API calls', async () => {
  const api = async () => { throw new Error('API must not be called'); };
  for (const overrides of [{ GITHUB_EVENT_NAME: 'pull_request' }, { GITHUB_REF: 'refs/pull/42/head' }]) {
    await assert.rejects(publishLink({ ...env, ...overrides }, event, api), /Expected values/);
  }
  await assert.rejects(publishLink(env, { ...event, pull_request: { ...event.pull_request, base: { ref: 'main', repo: { full_name: 'evil/repo' } } } }, api), /Expected values/);
});

test('bounds pagination rather than creating an unidentified duplicate', async () => {
  let calls = 0;
  await assert.rejects(publishLink(env, event, async (path, method) => {
    calls += 1; assert.equal(method, undefined);
    return Array.from({ length: 100 }, () => ({ body: 'Other comment' }));
  }), /Too many PR comments/);
  assert.equal(calls, 30);
});

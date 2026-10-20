import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export const marker = '<!-- bioloop-pr-preview-launcher -->';

export function previewComment(repository, number) {
  assert.match(repository, /^[\w.-]+\/[\w.-]+$/);
  assert.ok(Number.isSafeInteger(number) && number > 0 && number < 1_000_000_000);
  const launcher = `https://github.com/${repository}/actions/workflows/pr-preview.yml`;
  return `${marker}
### BioLoop preview

[**Start preview →**](${launcher})

This link opens GitHub's launcher; it does not start a preview by itself.
Choose **main**, enter PR number **${number}**, select a duration, and click **Run workflow**.

The latest CI must pass for this PR commit. Repository write access is required to launch it.
Once ready, open the run's **preview-ready** artifact for its protected URL and expiration, or find the URL in the **Start protected preview** log.
Sign in with an approved email, then choose a demo role. Use **Cancel workflow** to stop early.
`;
}

export async function publishLink(env, event, api) {
  assert.equal(env.GITHUB_EVENT_NAME, 'pull_request_target');
  assert.equal(env.GITHUB_REF, 'refs/heads/main');
  assert.equal(event.pull_request?.base?.ref, 'main');
  assert.equal(event.pull_request.base.repo.full_name, env.GITHUB_REPOSITORY);
  assert.equal(event.pull_request.state, 'open');
  const body = previewComment(env.GITHUB_REPOSITORY, event.number);
  const prefix = `/repos/${env.GITHUB_REPOSITORY}`;
  for (let page = 1; page <= 30; page += 1) {
    const comments = await api(`${prefix}/issues/${event.number}/comments?per_page=100&page=${page}`);
    const existing = comments.find(comment => comment.user?.login === 'github-actions[bot]'
      && comment.user?.type === 'Bot' && comment.body?.startsWith(marker));
    if (existing) {
      assert.ok(Number.isSafeInteger(existing.id) && existing.id > 0);
      if (existing.body === body) return 'unchanged';
      await api(`${prefix}/issues/comments/${existing.id}`, 'PATCH', { body });
      return 'updated';
    }
    if (comments.length < 100) {
      await api(`${prefix}/issues/${event.number}/comments`, 'POST', { body });
      return 'created';
    }
  }
  throw new Error('Too many PR comments to identify the preview launcher safely');
}

async function main() {
  const env = process.env;
  const event = JSON.parse(readFileSync(env.GITHUB_EVENT_PATH, 'utf8'));
  const api = async (path, method = 'GET', data) => {
    const response = await fetch(`https://api.github.com${path}`, {
      method, headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' },
      ...(data ? { body: JSON.stringify(data) } : {}), signal: AbortSignal.timeout(30_000),
    });
    assert.ok(response.ok, `Preview link request failed (${response.status})`);
    return response.json();
  };
  console.log(`PR preview launcher ${await publishLink(env, event, api)}.`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}

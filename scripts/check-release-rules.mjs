// Does `compat:` actually resolve to a minor? Asserted rather than assumed.
import fs from 'node:fs';
import { analyzeCommits } from '@semantic-release/commit-analyzer';

const rc = JSON.parse(fs.readFileSync('.releaserc.json', 'utf8'));
const options = rc.plugins.find(
  (p) => Array.isArray(p) && p[0].includes('commit-analyzer'),
)[1];

const expected = [
  ['compat(client): raise the python floor', 'minor'],
  ['contract(schema): rename return to transport', 'minor'],
  ['feat(worker): add a knob', 'minor'],
  ['fix(client): wrap an error', 'patch'],
  ['refactor(client): move a helper', 'patch'],
  ['chore: tidy up', null],
  ['feat(worker): drop a field\n\nBREAKING CHANGE: gone', 'major'],
];

let failed = 0;
for (const [message, want] of expected) {
  const got = await analyzeCommits(options, {
    commits: [{ hash: 'a'.repeat(40), message }],
    logger: { log: () => {} },
  });
  const ok = (got ?? null) === want;
  if (!ok) failed += 1;
  const label = message.split('\n')[0].padEnd(46);
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label} -> ${got ?? 'no release'}`);
}
process.exit(failed === 0 ? 0 : 1);

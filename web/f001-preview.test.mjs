import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

test('通常画面から固定したF001確認パターンを開ける', () => {
  const root = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
  const lab = readFileSync(new URL('./stop-distance-lab.html', import.meta.url), 'utf8');
  assert.match(root, /href="\/stop-distance-lab\.html\?prepared"/);
  assert.match(lab, /fetch\('\/f001-previews\.json'\)/);
  assert.match(lab, /fetch\('http:\/\/127\.0\.0\.1:8765\/roze\.vrm'\)/);
});

test('5種類の実ポーズと元の目的地を保持し、停止開始と終端を再生できる', () => {
  const data = JSON.parse(readFileSync(new URL('./public/f001-previews.json', import.meta.url), 'utf8'));
  assert.equal(data.candidates.length, 5);
  assert.equal(new Set(data.candidates.map(c => c.id)).size, 5);
  for (const candidate of data.candidates) {
    assert.equal(candidate.human_rating, 'unknown');
    assert.ok(candidate.frames.length > 60);
    assert.ok(candidate.events.stop_start > 0);
    assert.ok(candidate.events.stop_start < candidate.events.idle);
    assert.equal(candidate.frames[0].length, data.rig.parents.length);
    const last = candidate.frames.at(-1)[0];
    const error = Math.hypot(last[0]-candidate.goal_xy[0], last[1]-candidate.goal_xy[1]);
    assert.ok(Math.abs(error-candidate.metrics.arrival_error_m) < 1e-6);
  }
});

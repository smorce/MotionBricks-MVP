import test from 'node:test';
import assert from 'node:assert/strict';
import {formatGaitStatus} from './gaitView.js';

test('停止失敗の診断値を画面に表示する', () => {
  const status = formatGaitStatus({phase: 'stop_failed', goal_error_m: .42,
    stop_prediction_m: .25, final_stop_metrics: {reason: 'Stop planted foot slid'},
    stop_failure_reason: 'Recovery failed'});
  for (const text of ['stop_failed', '0.420', '0.250', 'Stop planted foot slid', 'Recovery failed']) {
    assert.ok(status.includes(text));
  }
});

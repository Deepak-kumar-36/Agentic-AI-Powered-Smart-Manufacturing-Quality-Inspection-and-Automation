const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const { scoreHistogram, binLabel } = require('../dashboard/analytics.js');
const histogram = scores => scoreHistogram(scores.map(score => ({ score })));
const counts = result => result.bins.map(bin => bin.count);

test('browser script exposes the same dependency-free analytics global', () => {
  const context = {};
  vm.runInNewContext(fs.readFileSync(require.resolve('../dashboard/analytics.js'), 'utf8'), context);
  assert.equal(context.InspectionAnalytics.scoreHistogram([{ score: 8 }]).maxScore, 8);
});

test('null, missing and non-numeric scores are excluded rather than coerced to zero', () => {
  const result = scoreHistogram([{ score: null }, {}, undefined, { score: undefined },
    { score: '' }, { score: '0.5' }, { score: false }, { score: {} }, { score: 0 }]);
  assert.equal(result.validCount, 1);
  assert.equal(result.excludedCount, 8);
  assert.deepEqual(counts(result), [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
});

test('scores above seven scale the range and keep truthful inclusive final bounds', () => {
  const result = histogram([0, 1, 4, 7.5, 8]);
  assert.equal(result.maxScore, 8);
  assert.deepEqual(counts(result), [1, 1, 0, 0, 0, 1, 0, 0, 0, 2]);
  assert.equal(binLabel(result.bins[9]), '7.2 ≤ score ≤ 8');
  assert.equal(binLabel(result.bins[0]), '0 ≤ score < 0.8');
});

test('empty and all-invalid input have ten empty bins and no valid observations', () => {
  for (const result of [histogram([]), histogram([null, NaN, -1])]) {
    assert.equal(result.validCount, 0);
    assert.equal(result.maxScore, 1);
    assert.deepEqual(counts(result), Array(10).fill(0));
  }
});

test('ordinary scores retain the minimum range of one and boundary assignments', () => {
  const result = histogram([0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1]);
  assert.equal(result.maxScore, 1);
  assert.equal(result.validCount, 12);
  assert.deepEqual(counts(result), [2, 1, 1, 1, 1, 1, 1, 1, 1, 2]);
});

test('nonfinite and negative values are excluded; extreme finite scores stay finite', () => {
  const result = histogram([NaN, Infinity, -Infinity, -0.1, Number.MAX_VALUE]);
  assert.equal(result.validCount, 1);
  assert.equal(result.excludedCount, 4);
  assert.equal(result.bins[9].count, 1);
  assert.equal(result.bins[9].upper, Number.MAX_VALUE);
  assert.ok(result.bins.every(bin => Number.isFinite(bin.lower) && Number.isFinite(bin.upper)));
});

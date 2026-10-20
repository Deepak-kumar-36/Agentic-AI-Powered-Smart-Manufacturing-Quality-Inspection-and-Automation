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

test('dashboard is a single scrollable workspace with bounded history controls and API paths', () => {
  const html = fs.readFileSync(require.resolve('../dashboard/index.html'), 'utf8');
  assert.match(html, /data-route="dashboard"/);
  for (const route of ['new-inspection', 'history', 'model', 'dataset', 'health', 'settings']) {
    assert.doesNotMatch(html, new RegExp(`data-route="${route}"`));
  }
  for (const id of ['dashboard-view', 'phone-camera', 'cameraUrl', 'cameraConfigureButton', 'cameraCaptureButton', 'cameraResult', 'dataset', 'historySearch', 'historyCategory', 'historyOutcome']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  for (const path of ['/health/ready', '/api/v1/system/status', '/api/v1/system/metadata', '/api/v1/inspections?limit=50', '/api/v1/images', '/api/v1/camera/status', '/api/v1/camera/configure', '/api/v1/camera/capture-inspection']) {
    assert.match(html, new RegExp(path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(html, /does not fabricate dataset counts/);
  assert.match(html, /metadata\?\.categories/);
  assert.match(html, /metadata\?\.model_versions/);
  assert.match(html, /metadata\?\.policies/);
  assert.match(html, /Policy thresholds/);
  assert.match(html, /Request error/);
  assert.match(html, /No heatmap or evidence image was returned/);
  assert.match(html, /renderMetadataState\(null\)/);
  assert.match(html, /releaseMetadata\.available/);
  assert.match(html, /Idempotency-Key/);
  assert.match(html, /Capturing and inspecting one fresh frame/);
  assert.match(html, /Camera configuration stays in memory/);
  assert.doesNotMatch(html, /<button[^>]+(?:train|upload model|release|reload)/i);
  assert.doesNotMatch(html, /bottle, screw, capsule \(form options\)/i);
  assert.doesNotMatch(html, /example|mock|fake|demo records/i);
});

(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.InspectionAnalytics = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function scoreHistogram(records) {
    const scores = records.map(record => record?.score).filter(score =>
      typeof score === 'number' && Number.isFinite(score) && score >= 0);
    const maxScore = scores.reduce((max, score) => Math.max(max, score), 1);
    const bins = Array.from({ length: 10 }, (_, index) => ({
      lower: maxScore * (index / 10),
      upper: maxScore * ((index + 1) / 10),
      count: 0,
      inclusiveUpper: index === 9,
    }));
    for (const score of scores) {
      // Ratio first avoids overflow for large finite anomaly scores.
      bins[Math.min(9, Math.floor((score / maxScore) * 10))].count++;
    }
    return { bins, maxScore, validCount: scores.length, excludedCount: records.length - scores.length };
  }

  function formatScore(score) {
    return String(Number(score.toPrecision(12)));
  }

  function binLabel(bin) {
    return `${formatScore(bin.lower)} ≤ score ${bin.inclusiveUpper ? '≤' : '<'} ${formatScore(bin.upper)}`;
  }

  return { scoreHistogram, formatScore, binLabel };
});

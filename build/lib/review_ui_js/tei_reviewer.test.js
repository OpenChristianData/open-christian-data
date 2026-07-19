'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');

const {
  bboxToViewportRect,
  zoomFrameForBbox,
  focusBbox,
  buildReviewerDecision,
  queueSummary,
} = require('./tei_reviewer.js');

test('bboxToViewportRect scales image coordinates into a contained viewport', function () {
  const rect = bboxToViewportRect(
    { x: 100, y: 50, w: 40, h: 20 },
    { width: 1000, height: 500 },
    { width: 500, height: 500 }
  );

  assert.deepStrictEqual(rect, { x: 50, y: 150, w: 20, h: 10, scale: 0.5 });
});

test('zoomFrameForBbox enlarges and frames the selected word crop', function () {
  const frame = zoomFrameForBbox(
    { x: 419, y: 228, w: 269, h: 62 },
    { width: 2048, height: 2828 },
    { width: 604, height: 859 }
  );

  assert.equal(frame.scale > 0.5, true);
  assert.equal(frame.overlay.w > 150, true);
  assert.equal(frame.overlay.x > 0, true);
  assert.equal(frame.overlay.x + frame.overlay.w < 604, true);
  assert.equal(frame.overlay.y > 0, true);
  assert.equal(frame.image.x <= 0, true);
  assert.equal(frame.image.y <= 0, true);
});

test('focusBbox prefers candidate geometry over a wide uncertainty span', function () {
  const token = {
    current_candidate_index: 0,
    bbox: { x: 419, y: 228, w: 269, h: 62 },
    candidates: [
      { index: 0, text: 'on', bbox: { x: 419, y: 228, w: 35, h: 18 } },
      { index: 1, text: 'in', bbox: { x: 657, y: 253, w: 31, h: 37 } },
    ],
  };

  assert.deepStrictEqual(focusBbox(token), { x: 419, y: 228, w: 35, h: 18 });
  assert.deepStrictEqual(focusBbox(token, 1), { x: 657, y: 253, w: 31, h: 37 });
});

test('focusBbox falls back to token span when candidate geometry is missing', function () {
  const token = {
    bbox: { x: 419, y: 228, w: 269, h: 62 },
    candidates: [{ index: 0, text: 'on', bbox: null }],
  };

  assert.deepStrictEqual(focusBbox(token), { x: 419, y: 228, w: 269, h: 62 });
});

test('buildReviewerDecision emits the JE review-patch decision shape', function () {
  const token = {
    canonical_token_id: 'ct-sha256:' + 'a'.repeat(64),
    token_xml_id: 'w_page_0010_0000',
    page_id: 'page_0010',
    position_id: 'vol_02:page_0010:body:c1:l000:p000',
    wct_page_sha256: 'cc7dfc066531135243667f5032621f9efba0ce7d2d8419a2080e1cc49ca54cca',
    current_text: 'on',
    candidates: [
      {
        index: 1,
        text: 'in',
        selected_observation_token_id: 'ot-sha256:' + 'b'.repeat(64),
      },
    ],
  };

  const decision = buildReviewerDecision(token, {
    action: 'pick',
    queue: 'dispute',
    candidateIndex: 1,
    reviewerId: 'maintainer',
  });

  assert.strictEqual(decision.decision_kind, 'adjudication');
  assert.strictEqual(decision.review_target, 'je_tei_token');
  assert.strictEqual(decision.action, 'pick');
  assert.strictEqual(decision.chosen_text, 'in');
  assert.strictEqual(decision.selected_observation_token_id, 'ot-sha256:' + 'b'.repeat(64));
  assert.strictEqual(decision.canonical_token_id, token.canonical_token_id);
  assert.strictEqual(decision.token_xml_id, 'w_page_0010_0000');
});

test('queueSummary preserves declared empty routes', function () {
  const summary = queueSummary({
    queues: {
      dispute: { count: 2 },
      gold_pass: { count: 1 },
      llm_ratification: { count: 0 },
    },
  });

  assert.deepStrictEqual(summary, [
    ['dispute', 2],
    ['gold_pass', 1],
    ['llm_ratification', 0],
  ]);
});

'use strict';
// node --test: built-in runner, zero external deps (ADR-0012 no-node_modules rule)
const { test } = require('node:test');
const assert = require('node:assert/strict');

// decision_sink.js exports { ReviewPatchSink } via CommonJS module.exports when in Node
const { ReviewPatchSink } = require('./decision_sink.js');

test('ReviewPatchSink.build() produces required top-level fields', function () {
  const sink = new ReviewPatchSink({ toolVersion: 'reviewer-ui/batch-03-test' });
  const patch = sink.build();

  assert.strictEqual(patch.schema_type, 'review_patch');
  assert.ok(/^\d+\.\d+\.\d+$/.test(patch.schema_version), 'schema_version is semver');
  assert.strictEqual(typeof patch.tool_version, 'string');
  assert.ok(patch.tool_version.length > 0, 'tool_version is non-empty');
  assert.ok(typeof patch.generated_at === 'string', 'generated_at is string');
  assert.ok(patch.generated_at.includes('T'), 'generated_at looks like ISO 8601');
  assert.ok(typeof patch.content_hashes === 'object' && patch.content_hashes !== null, 'content_hashes is object');
  assert.ok(Array.isArray(patch.decisions), 'decisions is array');
});

test('ReviewPatchSink starts with empty decisions and hashes', function () {
  const sink = new ReviewPatchSink({ toolVersion: 'reviewer-ui/batch-03-test' });
  const patch = sink.build();
  assert.deepStrictEqual(patch.decisions, []);
  assert.deepStrictEqual(patch.content_hashes, {});
});

test('ReviewPatchSink.record() accumulates decisions', function () {
  const sink = new ReviewPatchSink({ toolVersion: 'reviewer-ui/batch-03-test' });
  sink.record({ decision_kind: 'adjudication', token_id: 'ct-sha256:' + 'a'.repeat(64), chosen_reading: 'foo', queue: 'dispute' });
  sink.record({ decision_kind: 'adjudication', token_id: 'ct-sha256:' + 'b'.repeat(64), chosen_reading: 'bar', queue: 'gold_pass' });
  const patch = sink.build();
  assert.strictEqual(patch.decisions.length, 2);
  assert.strictEqual(patch.decisions[0].decision_kind, 'adjudication');
  assert.strictEqual(patch.decisions[0].token_id, 'ct-sha256:' + 'a'.repeat(64));
  assert.strictEqual(patch.decisions[1].chosen_reading, 'bar');
});

test('ReviewPatchSink.snapshotHashes() stores hash map in build()', function () {
  const sink = new ReviewPatchSink({ toolVersion: 'reviewer-ui/batch-03-test' });
  sink.snapshotHashes({ 'data/some/record.json': 'sha256:deadbeef', 'data/other.json': 'abc123' });
  const patch = sink.build();
  assert.strictEqual(patch.content_hashes['data/some/record.json'], 'sha256:deadbeef');
  assert.strictEqual(patch.content_hashes['data/other.json'], 'abc123');
});

test('ReviewPatchSink.build() is repeatable (pure)', function () {
  const sink = new ReviewPatchSink({ toolVersion: 'reviewer-ui/batch-03-test' });
  sink.record({ decision_kind: 'adjudication', token_id: 'ct-sha256:' + 'c'.repeat(64) });
  const p1 = sink.build();
  const p2 = sink.build();
  // decisions and hashes must be identical; generated_at may differ but structure must match
  assert.deepStrictEqual(p1.decisions, p2.decisions);
  assert.deepStrictEqual(p1.content_hashes, p2.content_hashes);
  assert.strictEqual(p1.schema_type, p2.schema_type);
  assert.strictEqual(p1.schema_version, p2.schema_version);
});

test('decision objects pass through record() unmodified into build()', function () {
  const sink = new ReviewPatchSink({ toolVersion: 'reviewer-ui/batch-03-test' });
  const decision = {
    decision_kind: 'adjudication',
    token_id: 'ct-sha256:' + '1'.repeat(64),
    chosen_reading: 'the chosen one',
    queue: 'dispute',
    extra_field: 'extra_value',
  };
  sink.record(decision);
  const patch = sink.build();
  const out = patch.decisions[0];
  assert.strictEqual(out.decision_kind, 'adjudication');
  assert.strictEqual(out.token_id, decision.token_id);
  assert.strictEqual(out.chosen_reading, decision.chosen_reading);
  assert.strictEqual(out.extra_field, decision.extra_field);
});

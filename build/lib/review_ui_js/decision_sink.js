'use strict';

(function () {
  function copyObject(source) {
    var copy = {};
    var key;

    if (!source) return copy;

    for (key in source) {
      if (Object.prototype.hasOwnProperty.call(source, key)) {
        copy[key] = source[key];
      }
    }

    return copy;
  }

  function copyArrayOfObjects(items) {
    return items.map(function (item) {
      return copyObject(item);
    });
  }

  function DecisionSink() {}

  DecisionSink.prototype.record = function (decision) {
    throw new Error('Not implemented');
  };

  DecisionSink.prototype.snapshotHashes = function (fileHashMap) {
    throw new Error('Not implemented');
  };

  DecisionSink.prototype.build = function () {
    throw new Error('Not implemented');
  };

  DecisionSink.prototype.download = function () {
    throw new Error('Not implemented');
  };

  function ReviewPatchSink(opts) {
    opts = opts || {};
    if (!opts.toolVersion) {
      throw new Error('ReviewPatchSink requires opts.toolVersion');
    }

    this._toolVersion = opts.toolVersion;
    this._decisions = [];
    this._hashes = {};
  }

  ReviewPatchSink.prototype = Object.create(DecisionSink.prototype);
  ReviewPatchSink.prototype.constructor = ReviewPatchSink;

  ReviewPatchSink.prototype.record = function (decision) {
    this._decisions.push(copyObject(decision));
  };

  ReviewPatchSink.prototype.snapshotHashes = function (fileHashMap) {
    this._hashes = copyObject(fileHashMap);
  };

  ReviewPatchSink.prototype.build = function () {
    return {
      schema_type: 'review_patch',
      schema_version: '3.0.0',
      tool_version: this._toolVersion,
      generated_at: new Date().toISOString(),
      content_hashes: copyObject(this._hashes),
      decisions: copyArrayOfObjects(this._decisions)
    };
  };

  ReviewPatchSink.prototype.download = function () {
    var patch = this.build();
    var json = JSON.stringify(patch, null, 2);
    var blob = new Blob([json], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'review_patch_' + new Date().toISOString().replace(/[:.]/g, '-') + '.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (typeof window !== 'undefined') {
    window.DecisionSink = DecisionSink;
    window.ReviewPatchSink = ReviewPatchSink;
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { DecisionSink: DecisionSink, ReviewPatchSink: ReviewPatchSink };
  }
})();

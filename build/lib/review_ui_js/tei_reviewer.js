'use strict';

(function () {
  var QUEUE_LABELS = {
    dispute: 'Dispute',
    gold_pass: 'Gold pass',
    llm_ratification: 'LLM ratification',
    external_check_absent_sampling: 'External absent sampling',
    orphan_rebind: 'Orphan rebind',
    structural_and_cross_reference: 'Structure / cross-ref',
    promotion_recheck: 'Promotion recheck',
    ccel_quality: 'CCEL quality'
  };

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function bboxToViewportRect(bbox, imageSize, viewportSize) {
    var scale = Math.min(viewportSize.width / imageSize.width, viewportSize.height / imageSize.height);
    var renderedWidth = imageSize.width * scale;
    var renderedHeight = imageSize.height * scale;
    var offsetX = (viewportSize.width - renderedWidth) / 2;
    var offsetY = (viewportSize.height - renderedHeight) / 2;
    return {
      x: offsetX + bbox.x * scale,
      y: offsetY + bbox.y * scale,
      w: bbox.w * scale,
      h: bbox.h * scale,
      scale: scale
    };
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function zoomFrameForBbox(bbox, imageSize, viewportSize) {
    var containScale = Math.min(viewportSize.width / imageSize.width, viewportSize.height / imageSize.height);
    var targetScale = Math.min(
      viewportSize.width / Math.max(bbox.w * 3, 1),
      viewportSize.height / Math.max(bbox.h * 5, 1)
    );
    var scale = clamp(targetScale, containScale, 4);
    var imageWidth = imageSize.width * scale;
    var imageHeight = imageSize.height * scale;
    var centeredLeft = viewportSize.width / 2 - (bbox.x + bbox.w / 2) * scale;
    var centeredTop = viewportSize.height / 2 - (bbox.y + bbox.h / 2) * scale;
    var minLeft = Math.min(0, viewportSize.width - imageWidth);
    var minTop = Math.min(0, viewportSize.height - imageHeight);
    var left = clamp(centeredLeft, minLeft, 0);
    var top = clamp(centeredTop, minTop, 0);
    return {
      image: {
        x: left,
        y: top,
        w: imageWidth,
        h: imageHeight
      },
      overlay: {
        x: left + bbox.x * scale,
        y: top + bbox.y * scale,
        w: bbox.w * scale,
        h: bbox.h * scale
      },
      scale: scale
    };
  }

  function queueSummary(model) {
    return Object.keys(model.queues || {}).map(function (name) {
      return [name, Number(model.queues[name].count || 0)];
    });
  }

  function candidateByIndex(token, index) {
    var candidates = token.candidates || [];
    for (var i = 0; i < candidates.length; i++) {
      if (Number(candidates[i].index) === Number(index)) {
        return candidates[i];
      }
    }
    return null;
  }

  function validBbox(bbox) {
    return bbox &&
      typeof bbox.x === 'number' &&
      typeof bbox.y === 'number' &&
      typeof bbox.w === 'number' &&
      typeof bbox.h === 'number' &&
      bbox.w > 0 &&
      bbox.h > 0;
  }

  function focusCandidate(token, selectedCandidateIndex) {
    if (!token) return null;
    var candidates = token.candidates || [];
    if (!candidates.length) return null;
    var index = typeof selectedCandidateIndex === 'number' ? selectedCandidateIndex : token.current_candidate_index;
    if (typeof index !== 'number') index = candidates[0].index;
    return candidateByIndex(token, index) || candidates[0];
  }

  function focusBbox(token, selectedCandidateIndex) {
    var candidate = focusCandidate(token, selectedCandidateIndex);
    if (candidate && validBbox(candidate.bbox)) return candidate.bbox;
    return validBbox(token && token.bbox) ? token.bbox : null;
  }

  function bboxLabel(bbox) {
    if (!validBbox(bbox)) return 'none';
    return Math.round(bbox.x) + ',' +
      Math.round(bbox.y) + ' ' +
      Math.round(bbox.w) + 'x' +
      Math.round(bbox.h);
  }

  function buildReviewerDecision(token, opts) {
    opts = opts || {};
    var action = opts.action || 'pick';
    var candidate = action === 'pick' ? candidateByIndex(token, opts.candidateIndex) : null;
    var chosenText = action === 'pick' ? (candidate && candidate.text) : (opts.amendedText || '');

    if (action === 'pick' && !candidate) {
      throw new Error('No candidate for index ' + opts.candidateIndex);
    }
    if (action === 'pick' && !candidate.selected_observation_token_id) {
      throw new Error('Candidate has no observation token id');
    }

    return {
      decision_kind: 'adjudication',
      review_target: 'je_tei_token',
      action: action,
      queue: opts.queue || token.queue,
      reviewer_id: opts.reviewerId || 'maintainer',
      ui_mode: 'word',
      canonical_token_id: token.canonical_token_id,
      token_xml_id: token.token_xml_id,
      page_id: token.page_id,
      position_id: token.position_id,
      wct_page_sha256: token.wct_page_sha256,
      previous_status_at_view: 'consensus',
      current_text: token.current_text,
      chosen_text: chosenText,
      chosen_candidate_index: candidate ? candidate.index : null,
      selected_observation_token_id: candidate ? candidate.selected_observation_token_id : null,
      amended_text: action === 'amend' || action === 'illegible' ? chosenText : null,
      amendment_reason: opts.amendmentReason || (action === 'illegible' ? 'Marked illegible by reviewer.' : '')
    };
  }

  function TeiReviewerApp(model) {
    this.model = model;
    this.state = {
      mode: 'word',
      queue: 'dispute',
      selectedTokenId: model.word_items && model.word_items[0] ? model.word_items[0].token_xml_id : null,
      selectedCandidateIndex: null
    };
    this.viewer = null;
    this.overlay = null;
    this.spanOverlay = null;
    this.scanFallback = null;
    this.fallbackOverlay = null;
    this.fallbackSpanOverlay = null;
    this.sink = new window.ReviewPatchSink({ toolVersion: 'tei-reviewer-ui/1.0.0' });
    this.sink.snapshotHashes(model.content_hashes || {});
  }

  TeiReviewerApp.prototype.mount = function () {
    this.cacheElements();
    this.bindEvents();
    this.initScan();
    this.renderTei();
    this.render();
  };

  TeiReviewerApp.prototype.cacheElements = function () {
    this.modeNav = document.getElementById('mode-nav');
    this.queueNav = document.getElementById('queue-nav');
    this.tokenList = document.getElementById('token-list');
    this.detail = document.getElementById('detail-panel');
    this.contract = document.getElementById('contract-panel');
    this.teiRoot = document.getElementById('tei-root');
    this.patchCount = document.getElementById('patch-count');
    this.downloadButton = document.getElementById('download-patch');
    this.status = document.getElementById('reviewer-status');
  };

  TeiReviewerApp.prototype.bindEvents = function () {
    var app = this;
    this.modeNav.addEventListener('click', function (event) {
      var button = event.target.closest('button[data-mode]');
      if (!button) return;
      app.state.mode = button.dataset.mode;
      app.render();
    });
    this.queueNav.addEventListener('click', function (event) {
      var button = event.target.closest('button[data-queue]');
      if (!button) return;
      app.state.queue = button.dataset.queue;
      var first = app.visibleTokens()[0];
      app.state.selectedTokenId = first ? first.token_xml_id : null;
      app.state.selectedCandidateIndex = null;
      app.render();
    });
    this.tokenList.addEventListener('click', function (event) {
      var button = event.target.closest('button[data-token-id]');
      if (!button) return;
      app.selectToken(button.dataset.tokenId, true);
    });
    this.downloadButton.addEventListener('click', function () {
      app.sink.download();
    });
  };

  TeiReviewerApp.prototype.initScan = function () {
    var scanRoot = document.getElementById('scan-viewer');
    this.scanFallback = document.createElement('img');
    this.scanFallback.className = 'scan-fallback';
    this.scanFallback.src = this.model.source.image_url;
    this.scanFallback.alt = this.model.page_id + ' scan';
    scanRoot.appendChild(this.scanFallback);
    this.fallbackOverlay = document.createElement('div');
    this.fallbackOverlay.className = 'token-overlay focus-token-overlay fallback-token-overlay';
    scanRoot.appendChild(this.fallbackOverlay);
    this.fallbackSpanOverlay = document.createElement('div');
    this.fallbackSpanOverlay.className = 'token-overlay span-token-overlay fallback-token-overlay';
    scanRoot.appendChild(this.fallbackSpanOverlay);

    if (!window.OpenSeadragon) {
      this.setStatus('OpenSeadragon did not load.', true);
      return;
    }
    this.overlay = document.createElement('div');
    this.overlay.className = 'token-overlay focus-token-overlay';
    this.spanOverlay = document.createElement('div');
    this.spanOverlay.className = 'token-overlay span-token-overlay';
    this.viewer = window.OpenSeadragon({
      id: 'scan-viewer',
      prefixUrl: (window.TEI_REVIEWER_VENDOR_BASE || '../../viewer/vendor/openseadragon/') + 'images/',
      showNavigationControl: false,
      tileSources: {
        type: 'image',
        url: this.model.source.image_url
      }
    });
    var app = this;
    this.viewer.addHandler('open', function () {
      app.frameSelectedToken(false);
    });
  };

  TeiReviewerApp.prototype.renderTei = function () {
    if (!window.CETEI) {
      this.teiRoot.textContent = 'CETEIcean did not load.';
      return;
    }
    var cetei = new window.CETEI();
    var app = this;
    this.teiRoot.innerHTML = '';
    cetei.makeHTML5(readingTeiXml(this.model.tei_xml), function (dom) {
      app.teiRoot.appendChild(dom);
      app.teiRoot.addEventListener('click', function (event) {
        var word = event.target.closest('[id^="w_"]');
        if (!word) return;
        app.state.mode = 'word';
        app.selectToken(word.id, true);
      });
      app.markTeiSelection();
    });
  };

  TeiReviewerApp.prototype.render = function () {
    this.renderModes();
    this.renderQueues();
    if (this.state.mode === 'word') {
      this.renderWordMode();
    } else if (this.state.mode === 'block') {
      this.renderBlockMode();
    } else {
      this.renderPageMode();
    }
    this.markTeiSelection();
    this.frameSelectedToken(false);
    this.patchCount.textContent = String(this.sink.build().decisions.length);
  };

  TeiReviewerApp.prototype.renderModes = function () {
    var app = this;
    this.modeNav.querySelectorAll('button[data-mode]').forEach(function (button) {
      button.setAttribute('aria-pressed', button.dataset.mode === app.state.mode ? 'true' : 'false');
    });
  };

  TeiReviewerApp.prototype.renderQueues = function () {
    var app = this;
    this.queueNav.innerHTML = queueSummary(this.model).map(function (entry) {
      var name = entry[0];
      var count = entry[1];
      return '<button type="button" data-queue="' + escapeHtml(name) + '" aria-pressed="' +
        (name === app.state.queue ? 'true' : 'false') + '">' +
        '<span>' + escapeHtml(QUEUE_LABELS[name] || name) + '</span><strong>' + count + '</strong></button>';
    }).join('');
  };

  TeiReviewerApp.prototype.visibleTokens = function () {
    var app = this;
    return (this.model.word_items || []).filter(function (token) {
      return token.queue === app.state.queue;
    });
  };

  TeiReviewerApp.prototype.selectedToken = function () {
    var id = this.state.selectedTokenId;
    if (!id) return null;
    var items = this.model.word_items || [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].token_xml_id === id) return items[i];
    }
    return null;
  };

  TeiReviewerApp.prototype.renderWordMode = function () {
    var tokens = this.visibleTokens();
    var selected = this.selectedToken();
    this.contract.innerHTML = '';
    this.tokenList.innerHTML = tokens.map(function (token) {
      return '<button type="button" data-token-id="' + escapeHtml(token.token_xml_id) + '" aria-pressed="' +
        (selected && selected.token_xml_id === token.token_xml_id ? 'true' : 'false') + '">' +
        '<span>' + escapeHtml(token.current_text || '[blank]') + '</span><small>' +
        escapeHtml(token.queue_reason) + '</small></button>';
    }).join('') || '<p class="empty">This route is declared but empty.</p>';
    this.renderTokenDetail(selected);
  };

  TeiReviewerApp.prototype.renderTokenDetail = function (token) {
    var app = this;
    if (!token) {
      this.detail.innerHTML = '<p class="empty">No token selected.</p>';
      return;
    }
    if (typeof this.state.selectedCandidateIndex !== 'number' || !candidateByIndex(token, this.state.selectedCandidateIndex)) {
      var firstCandidate = token.candidates && token.candidates[0] ? token.candidates[0].index : 0;
      this.state.selectedCandidateIndex = token.current_candidate_index == null ? firstCandidate : token.current_candidate_index;
    }
    var focus = focusBbox(token, this.state.selectedCandidateIndex);
    var span = validBbox(token.bbox) ? token.bbox : null;
    var spanSource = token.bbox_source ? ' <small>' + escapeHtml(token.bbox_source) + '</small>' : '';
    this.detail.innerHTML = [
      '<h2>Word</h2>',
      '<dl class="token-meta">',
      '<div><dt>Token</dt><dd><code>' + escapeHtml(token.token_xml_id) + '</code></dd></div>',
      '<div><dt>Current</dt><dd>' + escapeHtml(token.current_text) + '</dd></div>',
      '<div><dt>Route</dt><dd>' + escapeHtml(QUEUE_LABELS[token.queue] || token.queue) + '</dd></div>',
      '<div><dt>Focus box</dt><dd><code>' + escapeHtml(bboxLabel(focus)) + '</code></dd></div>',
      '<div><dt>Uncertain span</dt><dd><code>' + escapeHtml(bboxLabel(span)) + '</code>' + spanSource + '</dd></div>',
      '</dl>',
      '<div class="candidate-list">' + token.candidates.map(function (candidate) {
        var geometry = validBbox(candidate.bbox) ? bboxLabel(candidate.bbox) : 'no candidate box';
        return '<button type="button" data-candidate-index="' + candidate.index + '" aria-pressed="' +
          (candidate.index === app.state.selectedCandidateIndex ? 'true' : 'false') + '">' +
          '<span>' + escapeHtml(candidate.text || '[blank]') + '</span><small>' +
          escapeHtml(((candidate.families || []).join(', ') || 'no witness') + ' · ' + geometry) + '</small></button>';
      }).join('') + '</div>',
      '<label class="amend-box"><span>Amend reading</span><input id="amend-text" type="text" value="' +
        escapeHtml(token.current_text) + '"></label>',
      '<div class="decision-actions">',
      '<button type="button" data-decision-action="pick">Pick</button>',
      '<button type="button" data-decision-action="amend">Amend</button>',
      '<button type="button" data-decision-action="illegible">Illegible</button>',
      '</div>'
    ].join('');

    this.detail.querySelector('.candidate-list').addEventListener('click', function (event) {
      var button = event.target.closest('button[data-candidate-index]');
      if (!button) return;
      app.state.selectedCandidateIndex = Number(button.dataset.candidateIndex);
      app.detail.querySelectorAll('.candidate-list button').forEach(function (candidateButton) {
        candidateButton.setAttribute('aria-pressed', Number(candidateButton.dataset.candidateIndex) === app.state.selectedCandidateIndex ? 'true' : 'false');
      });
      app.renderTokenDetail(token);
      app.frameSelectedToken(true);
    });
    this.detail.querySelector('.decision-actions').addEventListener('click', function (event) {
      var button = event.target.closest('button[data-decision-action]');
      if (!button) return;
      app.recordDecision(token, button.dataset.decisionAction);
    });
  };

  TeiReviewerApp.prototype.renderBlockMode = function () {
    var blocks = this.model.block_items || [];
    this.contract.innerHTML = contractPanel(this.model.block_contract);
    this.tokenList.innerHTML = blocks.map(function (block) {
      return '<button type="button" data-block-id="' + escapeHtml(block.block_id) + '">' +
        '<span>' + escapeHtml(block.label) + '</span><small>' + block.token_count + ' tokens</small></button>';
    }).join('');
    this.detail.innerHTML = '<h2>Block</h2>' + blocks.map(function (block) {
      return '<section class="mode-row"><strong>' + escapeHtml(block.label) + '</strong><span>' +
        escapeHtml(block.zone_type) + '</span><span>' + block.token_count + ' tokens</span></section>';
    }).join('');
  };

  TeiReviewerApp.prototype.renderPageMode = function () {
    var app = this;
    this.contract.innerHTML = contractPanel(this.model.page_contract);
    this.tokenList.innerHTML = (this.model.word_items || []).slice(0, 300).map(function (token) {
      return '<button type="button" data-token-id="' + escapeHtml(token.token_xml_id) + '">' +
        '<span>' + escapeHtml(token.current_text || '[blank]') + '</span><small>#' + token.ordinal + '</small></button>';
    }).join('');
    this.detail.innerHTML = '<h2>Page</h2><p>' + escapeHtml(this.model.page_id) + '</p><p>' +
      (this.model.word_items || []).length + ' live word positions in reading order.</p>';
    this.tokenList.querySelectorAll('button[data-token-id]').forEach(function (button) {
      button.addEventListener('click', function () {
        app.state.mode = 'word';
        app.selectToken(button.dataset.tokenId, true);
      });
    });
  };

  function readingTeiXml(teiXml) {
    if (!window.DOMParser || !window.XMLSerializer) return teiXml;
    var parser = new window.DOMParser();
    var doc = parser.parseFromString(teiXml, 'application/xml');
    if (doc.querySelector('parsererror')) return teiXml;
    Array.prototype.forEach.call(doc.querySelectorAll('teiHeader, facsimile, note, rdg'), function (node) {
      node.parentNode.removeChild(node);
    });
    return new window.XMLSerializer().serializeToString(doc);
  }

  TeiReviewerApp.prototype.recordDecision = function (token, action) {
    var amendedInput = document.getElementById('amend-text');
    try {
      this.sink.record(buildReviewerDecision(token, {
        action: action,
        queue: this.state.queue,
        candidateIndex: this.state.selectedCandidateIndex,
        amendedText: action === 'illegible' ? '[illegible]' : amendedInput.value,
        amendmentReason: action === 'amend' ? 'Reviewer amended the reading.' : ''
      }));
      this.setStatus('Decision recorded.');
      this.render();
    } catch (error) {
      this.setStatus(error.message, true);
    }
  };

  TeiReviewerApp.prototype.selectToken = function (tokenId, focusScan) {
    var token = this.tokenById(tokenId);
    if (token) {
      this.state.queue = token.queue;
    }
    this.state.selectedTokenId = tokenId;
    this.state.selectedCandidateIndex = null;
    this.render();
    if (focusScan) this.frameSelectedToken(true);
  };

  TeiReviewerApp.prototype.tokenById = function (tokenId) {
    var items = this.model.word_items || [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].token_xml_id === tokenId) return items[i];
    }
    return null;
  };

  TeiReviewerApp.prototype.markTeiSelection = function () {
    if (!this.teiRoot) return;
    var selected = this.state.selectedTokenId;
    this.teiRoot.querySelectorAll('[id^="w_"]').forEach(function (word) {
      word.classList.toggle('selected-token', word.id === selected);
    });
  };

  TeiReviewerApp.prototype.frameSelectedToken = function (animate) {
    var token = this.selectedToken();
    var focus = focusBbox(token, this.state.selectedCandidateIndex);
    var span = validBbox(token && token.bbox) ? token.bbox : null;
    if (!token || !focus) {
      if (this.fallbackOverlay) this.fallbackOverlay.style.display = 'none';
      if (this.fallbackSpanOverlay) this.fallbackSpanOverlay.style.display = 'none';
      if (this.overlay && this.overlay.parentNode && this.viewer) {
        this.viewer.removeOverlay(this.overlay);
      }
      if (this.spanOverlay && this.spanOverlay.parentNode && this.viewer) {
        this.viewer.removeOverlay(this.spanOverlay);
      }
      return;
    }
    this.frameFallbackToken(focus, span);
    if (this.viewer && this.viewer.viewport && window.OpenSeadragon) {
      if (this.overlay.parentNode) {
        this.viewer.removeOverlay(this.overlay);
      }
      if (this.spanOverlay.parentNode) {
        this.viewer.removeOverlay(this.spanOverlay);
      }
      if (span && span !== focus) {
        var spanRect = new window.OpenSeadragon.Rect(span.x, span.y, span.w, span.h);
        this.viewer.addOverlay(this.spanOverlay, this.viewer.viewport.imageToViewportRectangle(spanRect));
      }
      var rect = new window.OpenSeadragon.Rect(focus.x, focus.y, focus.w, focus.h);
      var viewportRect = this.viewer.viewport.imageToViewportRectangle(rect);
      this.viewer.addOverlay(this.overlay, viewportRect);
      this.viewer.viewport.fitBounds(viewportRect.times(5), !animate);
    }
  };

  TeiReviewerApp.prototype.frameFallbackToken = function (focus, span) {
    if (!this.scanFallback || !this.fallbackOverlay || !this.model.source.image_size) return;
    var bounds = this.scanFallback.parentNode.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    var frame = zoomFrameForBbox(focus, this.model.source.image_size, {
      width: bounds.width,
      height: bounds.height
    });
    this.fallbackOverlay.style.display = 'block';
    this.scanFallback.style.left = frame.image.x + 'px';
    this.scanFallback.style.top = frame.image.y + 'px';
    this.scanFallback.style.width = frame.image.w + 'px';
    this.scanFallback.style.height = frame.image.h + 'px';
    this.fallbackOverlay.style.left = frame.overlay.x + 'px';
    this.fallbackOverlay.style.top = frame.overlay.y + 'px';
    this.fallbackOverlay.style.width = frame.overlay.w + 'px';
    this.fallbackOverlay.style.height = frame.overlay.h + 'px';
    if (this.fallbackSpanOverlay && span && span !== focus) {
      this.fallbackSpanOverlay.style.display = 'block';
      this.fallbackSpanOverlay.style.left = (frame.image.x + span.x * frame.scale) + 'px';
      this.fallbackSpanOverlay.style.top = (frame.image.y + span.y * frame.scale) + 'px';
      this.fallbackSpanOverlay.style.width = (span.w * frame.scale) + 'px';
      this.fallbackSpanOverlay.style.height = (span.h * frame.scale) + 'px';
    } else if (this.fallbackSpanOverlay) {
      this.fallbackSpanOverlay.style.display = 'none';
    }
  };

  TeiReviewerApp.prototype.setStatus = function (message, isError) {
    this.status.textContent = message;
    this.status.dataset.state = isError ? 'error' : 'ok';
  };

  function contractPanel(contract) {
    if (!contract) return '';
    return '<section class="contract-note"><strong>' + escapeHtml(contract.status) + '</strong><span>' +
      escapeHtml(contract.source) + '</span><p>' + escapeHtml(contract.follow_on) + '</p></section>';
  }

  function initTeiReviewer(model) {
    var app = new TeiReviewerApp(model);
    app.mount();
    return app;
  }

  if (typeof window !== 'undefined') {
    window.TeiReviewer = {
      init: initTeiReviewer,
      bboxToViewportRect: bboxToViewportRect,
      zoomFrameForBbox: zoomFrameForBbox,
      focusBbox: focusBbox,
      buildReviewerDecision: buildReviewerDecision,
      queueSummary: queueSummary
    };
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      bboxToViewportRect: bboxToViewportRect,
      zoomFrameForBbox: zoomFrameForBbox,
      focusBbox: focusBbox,
      buildReviewerDecision: buildReviewerDecision,
      queueSummary: queueSummary
    };
  }
})();

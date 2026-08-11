/* Atlas tree viewer/editor interactions.
 *
 * Pan/zoom drive a transform on the single <g class="atlas-viewport"> the
 * renderer wraps all tree content in — the viewBox is static and only one
 * transform attribute is written per animation frame, so panning never
 * re-lays-out or re-paints the 1000-node SVG.
 *
 * Editor mode is Path-of-Building-style: clicking an unallocated node
 * allocates the whole shortest path to it, clicking an allocated node removes
 * it plus everything that loses its link to the start, and hovering previews
 * either outcome.
 *
 * Data-independent: works over whatever SVG the server renders. The SVG root
 * carries data-mode="view|edit"; nodes are .atlas-node[data-node-id].
 *
 * Several viewers can live on one page (the strategy page mounts one per
 * variant tab, some of them fetched after load), so everything below is
 * per-instance and window.initAtlasTrees(root) picks up newly-inserted ones. */
(function () {
  "use strict";

  var idRun = 0;

  /** Give this SVG's defs page-unique ids.
   *
   * The renderer emits fixed ids ("ap12", "atlasGlow"), so a second tree on the
   * same page paints from the FIRST svg's identical-looking defs — which, when
   * that svg sits in a display:none tab panel, resolve to nothing at all and
   * the whole tree renders unpainted. Rewriting the duplicates (defs, the
   * url(#…) presentation attributes and the inline <style> that references
   * them) keeps every viewer self-contained. */
  function dedupeIds(svg) {
    var map = null;
    svg.querySelectorAll("[id]").forEach(function (el) {
      var id = el.id;
      if (document.getElementById(id) === el) return; // still the owner: leave it
      var next = id + "-t" + idRun;
      if (!map) map = Object.create(null);
      map[id] = next;
      el.id = next;
    });
    if (!map) return;
    idRun++;
    var rewrite = function (text) {
      return text.replace(/url\(#([^)]+)\)/g, function (whole, id) {
        return map[id] ? "url(#" + map[id] + ")" : whole;
      });
    };
    ["fill", "stroke", "filter", "mask", "clip-path"].forEach(function (attr) {
      svg.querySelectorAll("[" + attr + "^='url(']").forEach(function (el) {
        el.setAttribute(attr, rewrite(el.getAttribute(attr)));
      });
    });
    svg.querySelectorAll("style").forEach(function (el) {
      el.textContent = rewrite(el.textContent);
    });
  }

  function initTree(wrap) {
    if (wrap.dataset.atlasInit === "1") return;
    var svg = wrap.querySelector("svg");
    if (!svg) return;
    wrap.dataset.atlasInit = "1";
    dedupeIds(svg);
    var viewport = svg.querySelector(".atlas-viewport");

    var mode = wrap.getAttribute("data-mode") || "view";

    // --- Pan & zoom (transform only) ----------------------------------------
    var vb = (svg.getAttribute("viewBox") || "0 0 100 100").split(/\s+/).map(Number);
    // Current viewport transform: user = t + scale * tree.
    var tx = 0;
    var ty = 0;
    var scale = 1;
    var MIN_SCALE = 0.4; // relative to "fit the whole tree"
    var MAX_SCALE = 12;

    // svg-user-space -> screen mapping, from preserveAspectRatio="xMidYMid meet".
    // Only depends on element size, so it is cached and refreshed on resize.
    var fit = { k: 1, ox: 0, oy: 0 };
    function refreshFit() {
      var rect = svg.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      var k = Math.min(rect.width / vb[2], rect.height / vb[3]);
      fit.k = k;
      fit.ox = rect.left + (rect.width - vb[2] * k) / 2 - vb[0] * k;
      fit.oy = rect.top + (rect.height - vb[3] * k) / 2 - vb[1] * k;
    }
    refreshFit();
    window.addEventListener("resize", refreshFit);
    // No scroll listener: both consumers of `fit` (pointerdown, wheel) refresh
    // it on entry, and a capture-phase scroll handler would force a layout of
    // the 1000-node SVG on every scroll anywhere in the page.

    function clientToTree(clientX, clientY) {
      return {
        x: ((clientX - fit.ox) / fit.k - tx) / scale,
        y: ((clientY - fit.oy) / fit.k - ty) / scale,
      };
    }

    // One transform write per frame, whatever the input event rate.
    var frameQueued = false;
    function scheduleTransform() {
      if (frameQueued || !viewport) return;
      frameQueued = true;
      requestAnimationFrame(function () {
        frameQueued = false;
        viewport.setAttribute(
          "transform",
          "translate(" + tx.toFixed(2) + " " + ty.toFixed(2) + ") scale(" + scale.toFixed(5) + ")"
        );
      });
    }

    var panning = false;
    var last = null;
    // Node the pointer went down on — clicks are resolved on pointerup because
    // setPointerCapture retargets the browser's own click event to the svg root,
    // which would make node clicks impossible.
    var downNode = null;

    svg.addEventListener("pointerdown", function (evt) {
      if (evt.button !== 0) return;
      refreshFit();
      panning = true;
      last = { x: evt.clientX, y: evt.clientY, moved: false };
      downNode = evt.target.closest ? evt.target.closest(".atlas-node") : null;
      // Deliberately NOT capturing the pointer here: capture retargets the
      // pointerup/click at the svg root, which breaks node clicks. Capture
      // starts only once an actual drag is detected (below).
    });

    svg.addEventListener("pointermove", function (evt) {
      if (!panning || !last) return;
      if (!last.moved && Math.abs(evt.clientX - last.x) + Math.abs(evt.clientY - last.y) > 3) {
        last.moved = true;
        hideTip();
        hovered = null; // so re-hovering the same node after the pan re-previews
        clearPreview();
        wrap.classList.add("is-panning");
        try {
          svg.setPointerCapture(evt.pointerId); // keep the pan alive off-element
        } catch (e) {
          /* pointer may already be gone */
        }
      }
      if (!last.moved) return;
      tx += (evt.clientX - last.x) / fit.k;
      ty += (evt.clientY - last.y) / fit.k;
      last.x = evt.clientX;
      last.y = evt.clientY;
      scheduleTransform();
    });

    function endPan() {
      panning = false;
      wrap.classList.remove("is-panning");
    }
    svg.addEventListener("pointerup", endPan);
    svg.addEventListener("pointercancel", endPan);

    svg.addEventListener(
      "wheel",
      function (evt) {
        evt.preventDefault();
        refreshFit();
        var factor = evt.deltaY > 0 ? 1 / 1.18 : 1.18;
        var next = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale * factor));
        if (next === scale) return;
        var pt = clientToTree(evt.clientX, evt.clientY);
        scale = next;
        tx = (evt.clientX - fit.ox) / fit.k - scale * pt.x;
        ty = (evt.clientY - fit.oy) / fit.k - scale * pt.y;
        scheduleTransform();
      },
      { passive: false }
    );

    var homeBtn = wrap.querySelector("[data-atlas-home]");
    if (homeBtn)
      homeBtn.addEventListener("click", function () {
        tx = 0;
        ty = 0;
        scale = 1;
        scheduleTransform();
      });

    // --- Tooltip -------------------------------------------------------------
    var tip = wrap.querySelector(".atlas-tip");
    var tipNode = null;

    function showTip(node, evt) {
      if (!tip) return;
      if (node !== tipNode) {
        tipNode = node;
        tip.querySelector(".atlas-tip-name").textContent = node.getAttribute("data-name") || "";
        var statsEl = tip.querySelector(".atlas-tip-stats");
        statsEl.textContent = "";
        (node.getAttribute("data-stats") || "").split("\n").forEach(function (line) {
          if (!line) return;
          var p = document.createElement("div");
          p.textContent = line;
          statsEl.appendChild(p);
        });
        tip.hidden = false;
      }
      var wr = wrap.getBoundingClientRect();
      var x = evt.clientX - wr.left + 14;
      var y = evt.clientY - wr.top + 14;
      if (x + tip.offsetWidth > wr.width) x = Math.max(0, x - tip.offsetWidth - 28);
      if (y + tip.offsetHeight > wr.height) y = Math.max(0, y - tip.offsetHeight - 28);
      tip.style.left = x + "px";
      tip.style.top = y + "px";
    }

    function hideTip() {
      if (tip) tip.hidden = true;
      tipNode = null;
    }

    // Placeholder until edit mode installs the real one.
    var clearPreview = function () {};
    var hoverPreview = function () {};
    var hovered = null;

    svg.addEventListener("pointermove", function (evt) {
      if (panning && last && last.moved) return; // panning frames stay cheap
      var node = evt.target.closest && evt.target.closest(".atlas-node");
      if (!node || !node.getAttribute("data-name")) {
        if (hovered) {
          hovered = null;
          clearPreview();
        }
        hideTip();
        return;
      }
      showTip(node, evt);
      if (node !== hovered) {
        hovered = node;
        hoverPreview(node);
      }
    });
    svg.addEventListener("pointerleave", function () {
      hideTip();
      hovered = null;
      clearPreview();
    });

    if (mode !== "edit") return;

    // --- Editor: PoB-style pathing ------------------------------------------
    // Server provides the graph + rules; the client enforces connectivity so
    // feedback is instant, and the server re-validates on save.
    var dataEl = document.getElementById("atlas-graph-data");
    var field = document.querySelector("[data-atlas-field]");
    var counter = wrap.querySelector("[data-atlas-count]");
    if (!dataEl || !field) return;

    // graph = {edges: {id: [ids]}, start: [ids], budget: N, bonus: {id: pts}}
    // edges already include wormhole-pair pseudo-edges (server adds them).
    var graph = JSON.parse(dataEl.textContent);
    var startSet = new Set(graph.start.map(String));
    var allocated = new Set(JSON.parse(field.value || "[]").map(String));

    // Element indexes, built once: class churn then touches only what changed.
    var nodeEl = new Map();
    svg.querySelectorAll(".atlas-node").forEach(function (el) {
      nodeEl.set(el.getAttribute("data-node-id"), el);
    });
    var edgeEl = new Map(); // "a|b" (both orders) -> element
    var edgesOf = new Map(); // node id -> [elements]
    svg.querySelectorAll(".atlas-edge").forEach(function (el) {
      var a = el.getAttribute("data-a");
      var b = el.getAttribute("data-b");
      edgeEl.set(a + "|" + b, el);
      edgeEl.set(b + "|" + a, el);
      if (!edgesOf.has(a)) edgesOf.set(a, []);
      if (!edgesOf.has(b)) edgesOf.set(b, []);
      edgesOf.get(a).push(el);
      edgesOf.get(b).push(el);
    });

    function neighbours(id) {
      return graph.edges[id] || [];
    }

    function effectiveBudget(set) {
      var total = graph.budget;
      Object.keys(graph.bonus || {}).forEach(function (id) {
        if (set.has(id)) total += graph.bonus[id];
      });
      return total;
    }

    /** Shortest chain of currently-unallocated nodes joining the allocated set
     * (plus the always-on start nodes) to `target`, target last. [] if
     * unreachable; [target] when target is already adjacent. */
    function pathTo(target) {
      if (allocated.has(target)) return [];
      var prev = new Map();
      var seen = new Set();
      var queue = [];
      startSet.forEach(function (id) {
        seen.add(id);
        queue.push(id);
      });
      allocated.forEach(function (id) {
        if (!seen.has(id)) {
          seen.add(id);
          queue.push(id);
        }
      });
      for (var head = 0; head < queue.length; head++) {
        var cur = queue[head];
        var adj = neighbours(cur);
        for (var i = 0; i < adj.length; i++) {
          var n = String(adj[i]);
          if (seen.has(n)) continue;
          seen.add(n);
          prev.set(n, cur);
          if (n === target) {
            var chain = [];
            for (var walk = n; walk !== undefined && !allocated.has(walk) && !startSet.has(walk); walk = prev.get(walk))
              chain.push(walk);
            chain.reverse();
            return chain;
          }
          queue.push(n);
        }
      }
      return [];
    }

    /** Everything that would come off if `target` were removed: itself plus any
     * allocated node that can no longer reach a start node. */
    function pruneFrom(target) {
      if (!allocated.has(target)) return [];
      var kept = new Set();
      var queue = [];
      startSet.forEach(function (id) {
        kept.add(id);
        queue.push(id);
      });
      for (var head = 0; head < queue.length; head++) {
        var adj = neighbours(queue[head]);
        for (var i = 0; i < adj.length; i++) {
          var n = String(adj[i]);
          if (n === target || kept.has(n) || !allocated.has(n)) continue;
          kept.add(n);
          queue.push(n);
        }
      }
      var gone = [target];
      allocated.forEach(function (id) {
        if (id !== target && !kept.has(id)) gone.push(id);
      });
      return gone;
    }

    // --- Hover preview -------------------------------------------------------
    var previewNodes = new Set();
    var previewCls = "is-path";

    clearPreview = function () {
      previewNodes.forEach(function (id) {
        var el = nodeEl.get(id);
        if (el) el.classList.remove(previewCls);
        (edgesOf.get(id) || []).forEach(function (e) {
          e.classList.remove(previewCls);
        });
      });
      previewNodes.clear();
    };

    function applyPreview(ids, cls) {
      // Diff against what is already lit so DOM writes stay proportional to the
      // change, not to the tree.
      var next = new Set(ids);
      var same = cls === previewCls;
      if (!same) clearPreview();
      previewNodes.forEach(function (id) {
        if (next.has(id)) return;
        var el = nodeEl.get(id);
        if (el) el.classList.remove(cls);
        (edgesOf.get(id) || []).forEach(function (e) {
          e.classList.remove(cls);
        });
      });
      previewCls = cls;
      next.forEach(function (id) {
        var el = nodeEl.get(id);
        if (el) el.classList.add(cls);
      });
      // Tint the edges that join two highlighted ends, plus the ones joining a
      // highlighted node to something already live — those are exactly the
      // connectors that would light up (path) or go dark (removal).
      var live = new Set(next);
      allocated.forEach(function (id) {
        live.add(id);
      });
      startSet.forEach(function (id) {
        live.add(id);
      });
      next.forEach(function (id) {
        neighbours(id).forEach(function (raw) {
          var other = String(raw);
          if (!live.has(other)) return;
          var e = edgeEl.get(id + "|" + other);
          if (e) e.classList.add(cls);
        });
      });
      previewNodes = next;
    }

    hoverPreview = function (node) {
      var id = node.getAttribute("data-node-id");
      if (!id || !(id in graph.edges)) {
        clearPreview();
        return;
      }
      if (allocated.has(id)) applyPreview(pruneFrom(id), "is-removing");
      else applyPreview(pathTo(id), "is-path");
    };

    // --- Allocation ----------------------------------------------------------
    var form = wrap.closest("form");
    var saveBtn = (form || document).querySelector(".atlas-save-row button[value=save]");
    function updateCounter() {
      var budget = effectiveBudget(allocated);
      var over = allocated.size > budget;
      if (counter) {
        counter.textContent = allocated.size + " / " + budget;
        counter.classList.toggle("is-over", over);
      }
      // Pruning a bonus-point node can strand the rest over budget; the server
      // would reject that save, so block it here with an explanation instead.
      if (saveBtn) {
        saveBtn.disabled = over;
        saveBtn.title = over
          ? "Over the point budget - remove " + (allocated.size - budget) + " more point(s) to save"
          : "";
      }
    }

    var flashTimer = null;
    function flashDenied() {
      if (!counter) return;
      counter.classList.add("is-denied");
      clearTimeout(flashTimer);
      flashTimer = setTimeout(function () {
        counter.classList.remove("is-denied");
      }, 450);
    }

    function edgeIsLive(el) {
      var a = el.getAttribute("data-a");
      var b = el.getAttribute("data-b");
      var la = allocated.has(a) || startSet.has(a);
      var lb = allocated.has(b) || startSet.has(b);
      // A start node is free and always on, so it lights as soon as the other
      // end is allocated (mirrors the server's first paint rule).
      return la && lb && (allocated.has(a) || allocated.has(b));
    }

    /** Repaint only the nodes in `touched` and the edges incident to them. */
    function repaint(touched) {
      var edges = new Set();
      touched.forEach(function (id) {
        var el = nodeEl.get(id);
        if (el) el.classList.toggle("is-allocated", allocated.has(id));
        (edgesOf.get(id) || []).forEach(function (e) {
          edges.add(e);
        });
      });
      edges.forEach(function (e) {
        e.classList.toggle("is-allocated", edgeIsLive(e));
      });
      field.value = JSON.stringify(Array.from(allocated).map(Number));
      updateCounter();
    }

    svg.addEventListener("pointerup", function () {
      if (!downNode || (last && last.moved)) return; // it was a pan, not a click
      var node = downNode;
      downNode = null;
      var id = node.getAttribute("data-node-id");
      if (!id || !(id in graph.edges)) return;

      var touched;
      if (allocated.has(id)) {
        touched = pruneFrom(id);
        touched.forEach(function (n) {
          allocated.delete(n);
        });
      } else {
        var path = pathTo(id);
        if (!path.length) return; // unreachable
        var next = new Set(allocated);
        path.forEach(function (n) {
          next.add(n);
        });
        if (next.size > effectiveBudget(next)) {
          flashDenied();
          return;
        }
        allocated = next;
        touched = path;
      }
      clearPreview();
      repaint(touched);
      hoverPreview(node);
    });

    var clearBtn = wrap.querySelector("[data-atlas-clear]");
    if (clearBtn)
      clearBtn.addEventListener("click", function () {
        var touched = Array.from(allocated);
        allocated = new Set();
        hovered = null;
        clearPreview();
        repaint(touched);
      });

    repaint(Array.from(nodeEl.keys()));
  }

  /** Initialise every uninitialised viewer inside `root` (default: document). */
  function initAll(root) {
    (root || document).querySelectorAll("[data-atlas-tree]").forEach(initTree);
  }

  window.initAtlasTrees = initAll;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initAll();
    });
  } else {
    initAll();
  }
  // Trees swapped in by htmx elsewhere still boot themselves.
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    initAll(evt.target);
  });
})();

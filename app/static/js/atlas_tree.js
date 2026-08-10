/* Atlas tree viewer/editor interactions: pan, wheel-zoom, node hover tooltip,
 * and (editor mode only) click-to-allocate posting back via a hidden JSON field.
 * Data-independent: works over whatever SVG the server renders. The SVG root
 * carries data-mode="view|edit"; nodes are .atlas-node[data-node-id]. */
(function () {
  "use strict";

  var wrap = document.querySelector("[data-atlas-tree]");
  if (!wrap) return;
  var svg = wrap.querySelector("svg");
  if (!svg) return;

  var mode = wrap.getAttribute("data-mode") || "view";

  // --- Pan & zoom over the viewBox ---------------------------------------
  var vb = svg.getAttribute("viewBox").split(/\s+/).map(Number);
  var home = vb.slice();
  var MIN_SCALE = 0.08; // relative to home width
  var panning = false;
  var last = null;

  function setViewBox() {
    svg.setAttribute("viewBox", vb.join(" "));
  }

  function clientToTree(evt) {
    var rect = svg.getBoundingClientRect();
    return {
      x: vb[0] + ((evt.clientX - rect.left) / rect.width) * vb[2],
      y: vb[1] + ((evt.clientY - rect.top) / rect.height) * vb[3],
    };
  }

  svg.addEventListener("pointerdown", function (evt) {
    if (evt.button !== 0) return;
    panning = true;
    last = { x: evt.clientX, y: evt.clientY, moved: false };
    svg.setPointerCapture(evt.pointerId);
  });
  svg.addEventListener("pointermove", function (evt) {
    if (!panning || !last) return;
    var rect = svg.getBoundingClientRect();
    var dx = ((evt.clientX - last.x) / rect.width) * vb[2];
    var dy = ((evt.clientY - last.y) / rect.height) * vb[3];
    if (Math.abs(evt.clientX - last.x) + Math.abs(evt.clientY - last.y) > 3) last.moved = true;
    vb[0] -= dx;
    vb[1] -= dy;
    last.x = evt.clientX;
    last.y = evt.clientY;
    setViewBox();
  });
  svg.addEventListener("pointerup", function () {
    panning = false;
  });
  svg.addEventListener(
    "wheel",
    function (evt) {
      evt.preventDefault();
      var factor = evt.deltaY > 0 ? 1.18 : 1 / 1.18;
      var newW = vb[2] * factor;
      if (newW < home[2] * MIN_SCALE || newW > home[2] * 2.5) return;
      var pt = clientToTree(evt);
      vb[0] = pt.x - (pt.x - vb[0]) * factor;
      vb[1] = pt.y - (pt.y - vb[1]) * factor;
      vb[2] *= factor;
      vb[3] *= factor;
      setViewBox();
    },
    { passive: false }
  );

  var homeBtn = wrap.querySelector("[data-atlas-home]");
  if (homeBtn)
    homeBtn.addEventListener("click", function () {
      vb = home.slice();
      setViewBox();
    });

  // --- Tooltip -------------------------------------------------------------
  var tip = wrap.querySelector(".atlas-tip");
  function showTip(node, evt) {
    if (!tip) return;
    var name = node.getAttribute("data-name") || "";
    var stats = node.getAttribute("data-stats") || "";
    tip.querySelector(".atlas-tip-name").textContent = name;
    var statsEl = tip.querySelector(".atlas-tip-stats");
    statsEl.textContent = "";
    stats.split("\n").forEach(function (line) {
      if (!line) return;
      var p = document.createElement("div");
      p.textContent = line;
      statsEl.appendChild(p);
    });
    tip.hidden = false;
    var wr = wrap.getBoundingClientRect();
    var x = evt.clientX - wr.left + 14;
    var y = evt.clientY - wr.top + 14;
    // Keep inside the wrapper.
    if (x + tip.offsetWidth > wr.width) x = Math.max(0, x - tip.offsetWidth - 28);
    if (y + tip.offsetHeight > wr.height) y = Math.max(0, y - tip.offsetHeight - 28);
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  function hideTip() {
    if (tip) tip.hidden = true;
  }

  svg.addEventListener("pointermove", function (evt) {
    var node = evt.target.closest && evt.target.closest(".atlas-node");
    if (node && node.getAttribute("data-name")) showTip(node, evt);
    else hideTip();
  });
  svg.addEventListener("pointerleave", hideTip);

  if (mode !== "edit") return;

  // --- Editor: click-to-allocate ------------------------------------------
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

  function isConnected(candidate) {
    // Every allocated node must reach a start node through allocated nodes.
    if (candidate.size === 0) return true;
    var queue = [];
    var seen = new Set();
    candidate.forEach(function (id) {
      var adj = neighbours(id);
      for (var i = 0; i < adj.length; i++) {
        if (startSet.has(String(adj[i]))) {
          if (!seen.has(id)) {
            seen.add(id);
            queue.push(id);
          }
          break;
        }
      }
    });
    while (queue.length) {
      var cur = queue.pop();
      neighbours(cur).forEach(function (n) {
        n = String(n);
        if (candidate.has(n) && !seen.has(n)) {
          seen.add(n);
          queue.push(n);
        }
      });
    }
    return seen.size === candidate.size;
  }

  function paint() {
    svg.querySelectorAll(".atlas-node").forEach(function (el) {
      el.classList.toggle("is-allocated", allocated.has(el.getAttribute("data-node-id")));
    });
    svg.querySelectorAll(".atlas-edge").forEach(function (el) {
      var a = el.getAttribute("data-a");
      var b = el.getAttribute("data-b");
      el.classList.toggle(
        "is-allocated",
        (allocated.has(a) && allocated.has(b)) ||
          (allocated.has(a) && graph.start.indexOf(Number(b)) !== -1) ||
          (allocated.has(b) && graph.start.indexOf(Number(a)) !== -1)
      );
    });
    field.value = JSON.stringify(Array.from(allocated).map(Number));
    if (counter) {
      var budget = effectiveBudget(allocated);
      counter.textContent = allocated.size + " / " + budget;
      counter.classList.toggle("is-over", allocated.size > budget);
    }
  }

  svg.addEventListener("click", function (evt) {
    if (last && last.moved) return; // it was a pan, not a click
    var node = evt.target.closest && evt.target.closest(".atlas-node");
    if (!node) return;
    var id = node.getAttribute("data-node-id");
    if (!id || !(id in graph.edges)) return;
    var next = new Set(allocated);
    if (next.has(id)) next.delete(id);
    else {
      // Add first, THEN check: the clicked node may itself grant bonus points.
      next.add(id);
      if (next.size > effectiveBudget(next)) return; // over budget: ignore
    }
    if (!isConnected(next)) return;
    allocated = next;
    paint();
  });

  var clearBtn = wrap.querySelector("[data-atlas-clear]");
  if (clearBtn)
    clearBtn.addEventListener("click", function () {
      allocated = new Set();
      paint();
    });

  paint();
})();

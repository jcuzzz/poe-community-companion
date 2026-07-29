/* Dashboard layout builder — drag to reorder, set width/count, add/remove.
   No framework: HTML5 drag-and-drop for reordering, plain DOM for the rest.
   Serializes to the hidden #layout-field as JSON on submit. */
(function () {
  "use strict";

  var canvas = document.getElementById("builder-canvas");
  var palette = document.getElementById("builder-palette");
  var field = document.getElementById("layout-field");
  var form = document.getElementById("builder-form");
  var live = document.getElementById("builder-live");
  if (!canvas || !palette || !field || !form) return;

  function announce(msg) {
    if (live) live.textContent = msg;
  }
  function positionOf(card) {
    var cards = Array.prototype.slice.call(canvas.querySelectorAll(".builder-card"));
    return { index: cards.indexOf(card), total: cards.length };
  }

  var layout = JSON.parse(document.getElementById("layout-data").textContent);
  var catalogue = JSON.parse(document.getElementById("catalogue-data").textContent);
  var defaultLayout = JSON.parse(document.getElementById("default-data").textContent);
  var META = {};
  catalogue.forEach(function (c) { META[c.type] = c; });

  // Unsaved-changes tracking: warn before leaving / switching league.
  var dirty = false;
  var saving = false;
  function markDirty() { dirty = true; }

  // Width presets (12-column grid). Each widget declares which of these it
  // supports (registry `spans`/`min_w`), so the selector can't offer a span the
  // widget can't render legibly. Values are the stored ones — never renumber.
  var WIDTHS = [
    [3, "Quarter"], [4, "Third"], [6, "Half"],
    [8, "Two-thirds"], [9, "Three-quarters"], [12, "Full width"]
  ];
  function widthsFor(meta) {
    return (meta.spans && meta.spans.length) ? meta.spans : WIDTHS;
  }

  function present() {
    return Array.prototype.map.call(
      canvas.querySelectorAll(".builder-card"),
      function (el) { return el.dataset.type; }
    );
  }

  function makeCard(entry) {
    var meta = META[entry.type];
    if (!meta) return null;
    var w = entry.w || meta.default_w;
    if (meta.min_w && w < meta.min_w) w = meta.min_w;
    var options = entry.options || {};

    var card = document.createElement("div");
    card.className = "builder-card dash-w" + w;
    card.setAttribute("draggable", "true");
    card.dataset.type = entry.type;
    card.dataset.w = w;

    var head = document.createElement("div");
    head.className = "builder-card-head";
    var handle = document.createElement("span");
    handle.className = "builder-drag";
    handle.setAttribute("aria-hidden", "true");
    handle.textContent = "☰";
    var title = document.createElement("strong");
    title.textContent = meta.label;

    // Keyboard/touch reorder: HTML5 drag alone excludes keyboard and touch
    // users, so every card also carries explicit move buttons.
    var up = document.createElement("button");
    up.type = "button";
    up.className = "builder-move";
    up.setAttribute("aria-label", "Move " + meta.label + " up");
    up.textContent = "↑";
    up.addEventListener("click", function () {
      if (card.previousElementSibling) {
        canvas.insertBefore(card, card.previousElementSibling);
        var p = positionOf(card);
        announce(meta.label + " moved to position " + (p.index + 1) + " of " + p.total);
        markDirty();
        up.focus();
      }
    });
    var down = document.createElement("button");
    down.type = "button";
    down.className = "builder-move";
    down.setAttribute("aria-label", "Move " + meta.label + " down");
    down.textContent = "↓";
    down.addEventListener("click", function () {
      if (card.nextElementSibling) {
        canvas.insertBefore(card.nextElementSibling, card);
        var p = positionOf(card);
        announce(meta.label + " moved to position " + (p.index + 1) + " of " + p.total);
        markDirty();
        down.focus();
      }
    });

    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "builder-remove";
    remove.setAttribute("aria-label", "Remove " + meta.label);
    remove.textContent = "✕";
    remove.addEventListener("click", function () {
      card.remove();
      announce(meta.label + " removed");
      markDirty();
      renderPalette();
    });
    head.appendChild(handle);
    head.appendChild(title);
    head.appendChild(up);
    head.appendChild(down);
    head.appendChild(remove);
    card.appendChild(head);

    var controls = document.createElement("div");
    controls.className = "builder-card-controls";

    // Width selector.
    var wLabel = document.createElement("label");
    wLabel.textContent = "Width ";
    var wSel = document.createElement("select");
    wSel.className = "builder-w";
    var widths = widthsFor(meta).slice();
    if (!widths.some(function (p) { return p[0] === w; })) {
      widths.push([w, w + " / 12"]);
      widths.sort(function (a, b) { return a[0] - b[0]; });
    }
    widths.forEach(function (p) {
      var opt = document.createElement("option");
      opt.value = p[0];
      opt.textContent = p[1];
      if (p[0] === w) opt.selected = true;
      wSel.appendChild(opt);
    });
    wSel.addEventListener("change", function () {
      var nv = parseInt(wSel.value, 10) || 12;
      card.className = "builder-card dash-w" + nv;
      card.dataset.w = nv;
      markDirty();
    });
    wLabel.appendChild(wSel);
    controls.appendChild(wLabel);

    // Numeric options (count / rows).
    var maxes = meta.option_max || {};
    Object.keys(meta.options).forEach(function (key) {
      if (typeof meta.options[key] !== "number") return;
      var def = meta.options[key];
      var lab = document.createElement("label");
      lab.textContent = (key.charAt(0).toUpperCase() + key.slice(1)) + " ";
      var input = document.createElement("input");
      input.type = "number";
      input.min = "1";
      input.max = String(maxes[key] || 24);
      input.className = "builder-opt";
      input.dataset.key = key;
      input.dataset.default = def;
      input.value = options[key] != null ? options[key] : def;
      // A blank box shouldn't save a 0-count widget (renders empty); restore
      // the widget's default instead.
      input.addEventListener("change", markDirty);
      input.addEventListener("blur", function () {
        if (input.value === "" || parseInt(input.value, 10) < 1) input.value = def;
      });
      lab.appendChild(input);
      controls.appendChild(lab);
    });

    card.appendChild(controls);
    attachDrag(card);
    return card;
  }

  // --- Drag to reorder -----------------------------------------------------
  var dragging = null;
  function attachDrag(card) {
    card.addEventListener("dragstart", function () {
      dragging = card;
      setTimeout(function () { card.classList.add("is-dragging"); }, 0);
    });
    card.addEventListener("dragend", function () {
      dragging = null;
      card.classList.remove("is-dragging");
      canvas.classList.remove("is-dropping");
      markDirty();
    });
  }
  canvas.addEventListener("dragover", function (e) {
    e.preventDefault();
    if (!dragging) return;
    canvas.classList.add("is-dropping");
    var after = afterElement(e.clientY, e.clientX);
    if (after == null) canvas.appendChild(dragging);
    else canvas.insertBefore(dragging, after);
  });
  function afterElement(y, x) {
    var cards = Array.prototype.slice.call(
      canvas.querySelectorAll(".builder-card:not(.is-dragging)")
    );
    var closest = null, closestDist = Number.NEGATIVE_INFINITY;
    cards.forEach(function (c) {
      var box = c.getBoundingClientRect();
      // Offset from the card's centre; pick the first card we're "before".
      var offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closestDist) {
        closestDist = offset;
        closest = c;
      }
    });
    return closest;
  }

  // --- Palette -------------------------------------------------------------
  function renderPalette() {
    palette.innerHTML = "";
    var have = present();
    catalogue.forEach(function (c) {
      if (have.indexOf(c.type) !== -1) return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "builder-add btn btn-sm";
      btn.textContent = "+ " + c.label;
      btn.addEventListener("click", function () {
        var card = makeCard({ type: c.type, w: c.default_w, options: c.options });
        if (card) canvas.appendChild(card);
        markDirty();
        renderPalette();
      });
      palette.appendChild(btn);
    });
    if (!palette.children.length) {
      var none = document.createElement("p");
      none.className = "text-muted";
      none.textContent = "All widgets are in use.";
      palette.appendChild(none);
    }
  }

  // --- Serialize on submit -------------------------------------------------
  form.addEventListener("submit", function () {
    var out = [];
    Array.prototype.forEach.call(canvas.querySelectorAll(".builder-card"), function (card) {
      var entry = { type: card.dataset.type, w: parseInt(card.dataset.w, 10) || 12 };
      var opts = {};
      Array.prototype.forEach.call(card.querySelectorAll(".builder-opt"), function (input) {
        var v = parseInt(input.value, 10);
        if (isNaN(v) || v < 1) v = parseInt(input.dataset.default, 10) || 1;
        opts[input.dataset.key] = v;
      });
      if (Object.keys(opts).length) entry.options = opts;
      out.push(entry);
    });
    field.value = JSON.stringify(out);
    saving = true; // an intentional save must not trip the unsaved-changes guard
  });

  // --- Reset to default ----------------------------------------------------
  var resetBtn = document.getElementById("builder-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", function () {
      if (!window.confirm("Reset this dashboard to the default layout? Unsaved changes are lost.")) return;
      canvas.innerHTML = "";
      defaultLayout.forEach(function (entry) {
        var card = makeCard(entry);
        if (card) canvas.appendChild(card);
      });
      markDirty();
      renderPalette();
      announce("Layout reset to default");
    });
  }

  // --- Unsaved-changes guards ----------------------------------------------
  window.addEventListener("beforeunload", function (e) {
    if (dirty && !saving) { e.preventDefault(); e.returnValue = ""; }
  });
  // The league selector is a GET form; switching would discard edits.
  var leagueSelect = document.getElementById("league-select");
  if (leagueSelect) {
    var current = leagueSelect.value;
    leagueSelect.addEventListener("change", function () {
      if (dirty && !window.confirm("Switch league and discard unsaved changes?")) {
        leagueSelect.value = current;
        return;
      }
      saving = true; // allow the GET navigation without a second prompt
      leagueSelect.form.submit();
    });
  }

  // --- Boot ----------------------------------------------------------------
  layout.forEach(function (entry) {
    var card = makeCard(entry);
    if (card) canvas.appendChild(card);
  });
  renderPalette();
})();

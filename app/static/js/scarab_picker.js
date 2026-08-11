/* Structured scarab picker: map-device-style slots that mirror into the
   scarabs_text textarea (one scarab name per line). No external libs. */
(function () {
  "use strict";

  var SLOT_COUNT = 5;

  function ready(fn) {
    if (document.readyState !== "loading") { fn(); }
    else { document.addEventListener("DOMContentLoaded", fn); }
  }

  // Round influence buttons: radio behaviour, but clicking the checked one
  // again clears it back to "no influence".
  ready(function () {
    var group = document.querySelector("[data-influence-group]");
    if (!group) { return; }
    var labels = Array.prototype.slice.call(group.querySelectorAll(".influence-btn"));

    function paint() {
      labels.forEach(function (l) {
        var input = l.querySelector("input");
        l.classList.toggle("is-on", !!(input && input.checked));
      });
    }

    labels.forEach(function (label) {
      var input = label.querySelector("input");
      if (!input) { return; }
      // mousedown fires before the browser applies the radio selection, so
      // "was it already checked?" is still answerable here.
      input.addEventListener("mousedown", function () { input.dataset.wasOn = input.checked ? "1" : ""; });
      input.addEventListener("click", function () {
        if (input.dataset.wasOn === "1") { input.checked = false; }
        input.dataset.wasOn = "";
        paint();
      });
      input.addEventListener("change", paint);
      input.addEventListener("keyup", paint);
    });
    paint();
  });

  ready(function () {
    var root = document.getElementById("scarab-picker");
    if (!root) { return; }
    var textarea = document.getElementById(root.dataset.textareaId || "id_scarabs_text");
    if (!textarea) { return; }

    var data = [];
    var dataEl = document.getElementById("scarab-data");
    if (dataEl) {
      try { data = JSON.parse(dataEl.textContent) || []; } catch (e) { data = []; }
    }

    var byName = Object.create(null);
    data.forEach(function (s) { if (s && s.name) { byName[s.name] = s; } });

    // ---- state -----------------------------------------------------------
    var slots = new Array(SLOT_COUNT).fill(null);   // scarab names or null
    var extras = [];                                 // unmatched / overflow lines

    function parseInitial() {
      var lines = textarea.value.split(/\r?\n/)
        .map(function (l) { return l.trim(); })
        .filter(function (l) { return l.length > 0; });
      var next = 0;
      lines.forEach(function (line) {
        // Legacy quantity suffix ("Titanic Scarab of Legend x2") expands into
        // that many slots — the old free-text era documented this format.
        var m = line.match(/^(.*?)\s+x(\d+)$/i);
        var name = m ? m[1].trim() : line;
        var count = m ? Math.max(1, parseInt(m[2], 10) || 1) : 1;
        if (byName[name]) {
          for (var i = 0; i < count; i++) {
            if (next < SLOT_COUNT) {
              slots[next++] = name;
            } else {
              extras.push(name); // recognised, just past the 5 device slots
            }
          }
        } else {
          extras.push(line);
        }
      });
    }

    function syncTextarea() {
      var lines = [];
      slots.forEach(function (n) { if (n) { lines.push(n); } });
      extras.forEach(function (n) { lines.push(n); });
      textarea.value = lines.join("\n");
      textarea.dispatchEvent(new Event("change", { bubbles: true }));
    }

    // ---- DOM scaffolding -------------------------------------------------
    var wrap = document.createElement("div");
    wrap.className = "scarab-picker";

    var slotRow = document.createElement("div");
    slotRow.className = "scarab-slots";
    wrap.appendChild(slotRow);

    // Panel (search dropdown) sits directly under the slot row.
    var panel = document.createElement("div");
    panel.className = "scarab-panel";
    panel.hidden = true;
    panel.innerHTML =
      '<input type="text" class="scarab-search" placeholder="Search scarabs…" autocomplete="off">' +
      '<div class="scarab-results" role="listbox"></div>';
    wrap.appendChild(panel);
    var search = panel.querySelector(".scarab-search");
    var results = panel.querySelector(".scarab-results");

    var extrasBox = document.createElement("div");
    extrasBox.className = "scarab-extras";
    wrap.appendChild(extrasBox);

    var advWrap = document.createElement("div");
    advWrap.className = "scarab-advanced";
    var advBtn = document.createElement("button");
    advBtn.type = "button";
    advBtn.className = "scarab-adv-toggle";
    advBtn.textContent = "advanced: edit as text";
    advBtn.setAttribute("aria-expanded", "false");
    advWrap.appendChild(advBtn);
    wrap.appendChild(advWrap);

    // Mount into the placeholder div and hide the textarea via JS (never via
    // CSS) so a no-JS page still shows the plain field.
    root.appendChild(wrap);
    textarea.classList.add("scarab-raw");
    textarea.style.display = "none";

    advBtn.addEventListener("click", function () {
      var shown = textarea.style.display !== "none";
      textarea.style.display = shown ? "none" : "";
      advBtn.setAttribute("aria-expanded", shown ? "false" : "true");
      advBtn.classList.toggle("is-open", !shown);
      if (!shown) { textarea.focus(); }
    });

    // Manual textarea edits re-seed the picker.
    textarea.addEventListener("input", function () {
      slots = new Array(SLOT_COUNT).fill(null);
      extras = [];
      parseInitial();
      renderSlots();
      renderExtras();
    });

    // ---- rendering -------------------------------------------------------
    var slotEls = [];

    function buildSlots() {
      for (var i = 0; i < SLOT_COUNT; i++) {
        var cell = document.createElement("div");
        cell.className = "scarab-slot";
        cell.dataset.index = String(i);

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "scarab-slot-btn";
        btn.setAttribute("aria-haspopup", "listbox");
        cell.appendChild(btn);

        var rm = document.createElement("button");
        rm.type = "button";
        rm.className = "scarab-slot-remove";
        rm.innerHTML = "&times;";
        rm.title = "Clear slot";
        rm.setAttribute("aria-label", "Clear slot " + (i + 1));
        cell.appendChild(rm);

        (function (idx, btnEl, rmEl) {
          btnEl.addEventListener("click", function (ev) {
            ev.preventDefault();
            openPanel(idx);
          });
          rmEl.addEventListener("click", function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            slots[idx] = null;
            syncTextarea();
            renderSlots();
          });
        })(i, btn, rm);

        slotRow.appendChild(cell);
        slotEls.push(cell);
      }
    }

    function renderSlots() {
      slotEls.forEach(function (cell, i) {
        var name = slots[i];
        var btn = cell.querySelector(".scarab-slot-btn");
        var rm = cell.querySelector(".scarab-slot-remove");
        btn.innerHTML = "";
        if (name) {
          cell.classList.add("is-filled");
          cell.title = name;
          btn.title = name;
          var info = byName[name] || {};
          if (info.icon) {
            var img = document.createElement("img");
            img.src = info.icon;
            img.alt = name;
            img.className = "scarab-slot-icon";
            img.loading = "lazy";
            btn.appendChild(img);
          } else {
            var abbr = document.createElement("span");
            abbr.className = "scarab-slot-abbr";
            abbr.textContent = name.slice(0, 2);
            btn.appendChild(abbr);
          }
          var lbl = document.createElement("span");
          lbl.className = "scarab-slot-name";
          lbl.textContent = name;
          btn.appendChild(lbl);
          rm.hidden = false;
        } else {
          cell.classList.remove("is-filled");
          cell.title = "Empty slot " + (i + 1);
          btn.title = "Choose a scarab";
          var plus = document.createElement("span");
          plus.className = "scarab-slot-plus";
          plus.textContent = "+";
          btn.appendChild(plus);
          rm.hidden = true;
        }
      });
    }

    function renderExtras() {
      extrasBox.innerHTML = "";
      if (!extras.length) { return; }
      var h = document.createElement("p");
      h.className = "scarab-extras-head text-muted";
      h.textContent = "Extra lines (kept with the setup, beyond the 5 slots):";
      extrasBox.appendChild(h);
      var ul = document.createElement("ul");
      ul.className = "scarab-extras-list";
      extras.forEach(function (line, i) {
        var li = document.createElement("li");
        var span = document.createElement("span");
        span.textContent = line;
        li.appendChild(span);
        var rm = document.createElement("button");
        rm.type = "button";
        rm.className = "scarab-extra-remove";
        rm.innerHTML = "&times;";
        rm.title = "Remove line";
        rm.addEventListener("click", function (ev) {
          ev.preventDefault();
          extras.splice(i, 1);
          syncTextarea();
          renderExtras();
        });
        li.appendChild(rm);
        ul.appendChild(li);
      });
      extrasBox.appendChild(ul);
    }

    // ---- search panel ----------------------------------------------------
    var activeIndex = -1;
    var cursor = -1;
    var rowEls = [];

    function openPanel(idx) {
      activeIndex = idx;
      slotEls.forEach(function (c, i) { c.classList.toggle("is-active", i === idx); });
      panel.hidden = false;
      search.value = "";
      renderResults("");
      search.focus();
    }

    function closePanel() {
      panel.hidden = true;
      activeIndex = -1;
      cursor = -1;
      slotEls.forEach(function (c) { c.classList.remove("is-active"); });
    }

    function renderResults(query) {
      var q = (query || "").trim().toLowerCase();
      var matches = data.filter(function (s) {
        return !q || s.name.toLowerCase().indexOf(q) !== -1;
      });
      results.innerHTML = "";
      rowEls = [];
      cursor = -1;

      if (!matches.length) {
        var none = document.createElement("p");
        none.className = "scarab-none text-muted";
        none.textContent = "No scarabs match “" + query + "”.";
        results.appendChild(none);
        return;
      }

      var groups = [];
      var seen = Object.create(null);
      matches.forEach(function (s) {
        var g = s.group || "Other";
        if (!seen[g]) { seen[g] = []; groups.push(g); }
        seen[g].push(s);
      });

      groups.forEach(function (g) {
        var head = document.createElement("div");
        head.className = "scarab-group";
        head.textContent = g;
        results.appendChild(head);
        seen[g].forEach(function (s) {
          var row = document.createElement("button");
          row.type = "button";
          row.className = "scarab-row";
          row.setAttribute("role", "option");
          row.dataset.name = s.name;
          if (s.icon) {
            var img = document.createElement("img");
            img.src = s.icon;
            img.alt = "";
            img.className = "scarab-row-icon";
            img.loading = "lazy";
            row.appendChild(img);
          } else {
            var ph = document.createElement("span");
            ph.className = "scarab-row-icon scarab-row-icon-blank";
            row.appendChild(ph);
          }
          var nm = document.createElement("span");
          nm.className = "scarab-row-name";
          nm.textContent = s.name;
          row.appendChild(nm);
          row.addEventListener("click", function (ev) {
            ev.preventDefault();
            choose(s.name);
          });
          results.appendChild(row);
          rowEls.push(row);
        });
      });
    }

    function choose(name) {
      if (activeIndex >= 0) { slots[activeIndex] = name; }
      syncTextarea();
      renderSlots();
      closePanel();
    }

    function moveCursor(delta) {
      if (!rowEls.length) { return; }
      cursor = (cursor + delta + rowEls.length) % rowEls.length;
      rowEls.forEach(function (r, i) { r.classList.toggle("is-cursor", i === cursor); });
      var el = rowEls[cursor];
      if (el && el.scrollIntoView) { el.scrollIntoView({ block: "nearest" }); }
    }

    search.addEventListener("input", function () { renderResults(search.value); });
    panel.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") { ev.preventDefault(); closePanel(); }
      else if (ev.key === "ArrowDown") { ev.preventDefault(); moveCursor(1); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); moveCursor(-1); }
      else if (ev.key === "Enter") {
        ev.preventDefault();
        var pick = cursor >= 0 ? rowEls[cursor] : rowEls[0];
        if (pick) { choose(pick.dataset.name); }
      }
    });
    document.addEventListener("click", function (ev) {
      if (panel.hidden) { return; }
      if (!wrap.contains(ev.target)) { closePanel(); }
    });

    // ---- boot ------------------------------------------------------------
    parseInitial();
    buildSlots();
    renderSlots();
    renderExtras();
  });
})();

/* abshelver: status polling, import preview, organize plan. No framework. */
(function () {
  "use strict";
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const page = document.body.dataset.page;

  async function getJSON(url, body) {
    const opts = body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    };
    const r = await fetch(url, opts);
    let data = null;
    try { data = await r.json(); } catch (e) { /* no body */ }
    if (!r.ok) {
      const msg = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : r.statusText;
      throw new Error(msg);
    }
    return data;
  }

  // --- job status -----------------------------------------------------------
  let busy = false;
  const listeners = [];
  function setBusy(b) {
    busy = b;
    $$("button.primary").forEach(btn => { btn.disabled = busy || btn.dataset.ready !== "1"; });
  }
  function note(text, cls) {
    const el = $("#plan-result");
    if (!el) return;
    el.textContent = text;
    el.className = "result" + (cls ? " " + cls : "");
  }
  function clearNote() {
    const el = $("#plan-result");
    if (!el || el.classList.contains("waiting")) return;
    el.textContent = "";
    el.className = "result";
  }
  let watching = false;
  async function watch(onDone) {
    if (watching) return;
    watching = true;
    let last = null;
    while (true) {
      try {
        const s = await getJSON("/api/status");
        if (s.state === "running") {
          setBusy(true);
          listeners.forEach(fn => fn(s));
          last = s;
        } else {
          setBusy(false);
          watching = false;
          if (onDone) onDone(s.last, last);
          return;
        }
      } catch (e) {
        note(`Status: ${e.message}`, "error");
      }
      await new Promise(r => setTimeout(r, 1000));
    }
  }

  function debounce(fn, ms) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }

  // --- import list ---------------------------------------------------------
  function initImportList() {
    $$("tr[data-href]").forEach(row => {
      row.addEventListener("click", e => {
        if (e.target.closest("a") || e.metaKey || e.ctrlKey || e.shiftKey) return;
        location.href = row.dataset.href;
      });
    });
  }

  // --- import ---------------------------------------------------------------
  function initImport() {
    const form = $("#import-form");
    if (!form) return;
    const name = form.dataset.name;
    const tree = $("#preview-tree");
    const warnings = $("#warnings");
    const btn = $("#import-btn");
    const result = $("#plan-result");
    let plan = null;

    function formData() {
      const fd = new FormData(form);
      return {
        authors: fd.get("authors") || "",
        narrators: fd.get("narrators") || "",
        title: fd.get("title") || "",
        series: fd.get("series") || "",
        sequence: fd.get("sequence") || "",
        include_epub: form.elements.include_epub ? form.elements.include_epub.checked : true,
        cover: fd.get("cover") || "",
        delete_leftovers: form.elements.delete_leftovers ? form.elements.delete_leftovers.checked : false,
      };
    }

    function line(text, cls, op) {
      const div = document.createElement("div");
      if (cls) div.className = cls;
      if (op !== undefined && op !== null) div.dataset.op = op;
      div.textContent = text;
      tree.appendChild(div);
    }

    function renderPreview(p) {
      tree.innerHTML = "";
      line(`${form.dataset.library}/`, "muted");
      line(`  ${p.dest_dir}/`);
      p.files.forEach(f => {
        line(`    ${f.dst.split("/").pop()}`, "", f.op);
        line(`      ← ${f.src}`, "src");
      });
      if (p.metadata) {
        line("    metadata.json", "", p.metadata_op);
        p.metadata.trimEnd().split("\n").forEach(l => line(`      ${l}`, "src"));
      }
      line("");
      if (p.deletions.length) {
        line(`Deleted from ${p.source_dir}/`, "muted");
        p.deletions.forEach(d => line(`    ${d.name}`, "", d.op));
      }
      if (p.leftovers.length) {
        line(`Left in ${p.source_dir}/`, "muted");
        p.leftovers.forEach(x => line(`    ${x}`));
      }
      if (p.removes_source) {
        line("Removed after the move (it will be empty):", "muted");
        line(`    ${p.source_dir}/`, "", p.rmdir_op);
      }
      $$("li:not([data-static])", warnings).forEach(li => li.remove());
      p.warnings.forEach(w => {
        const li = document.createElement("li");
        li.className = w.level;
        li.textContent = w.message;
        warnings.appendChild(li);
      });
    }

    function markTree(done, failedAt, reason) {
      $$("[data-op]", tree).forEach(div => {
        const i = Number(div.dataset.op);
        div.classList.toggle("done", i < done);
        const failed = failedAt !== undefined && i === failedAt;
        div.classList.toggle("failed", failed);
        if (failed && reason) {
          const why = document.createElement("div");
          why.className = "failed";
          why.textContent = `      ✗ ${reason}`;
          div.after(why);
        }
      });
    }

    let seq = 0;
    const refresh = debounce(async () => {
      const mine = ++seq;
      try {
        const p = await getJSON(`/api/imports/${name}/plan`, formData());
        if (mine !== seq) return; // a newer request is in flight
        plan = p;
        renderPreview(plan);
        btn.dataset.ready = plan.blocked ? "" : "1";
        clearNote();
      } catch (e) {
        if (mine !== seq) return;
        plan = null;
        btn.dataset.ready = "";
        $$("li:not([data-static])", warnings).forEach(li => li.remove());
        const li = document.createElement("li");
        li.className = "block";
        li.textContent = e.message;
        warnings.appendChild(li);
      }
      setBusy(busy);
    }, 200);

    form.addEventListener("input", refresh);
    form.addEventListener("change", refresh);
    form.addEventListener("submit", e => e.preventDefault());
    refresh();

    btn.addEventListener("click", async () => {
      if (!plan || plan.blocked) return;
      const data = formData(); // before disabling: FormData skips disabled inputs
      btn.dataset.ready = "";
      setBusy(true);
      form.querySelectorAll("input").forEach(i => { i.disabled = true; });
      result.textContent = "";
      try {
        await getJSON(`/api/imports/${name}/run`, data);
      } catch (e) {
        result.textContent = e.message;
        result.className = "result error";
        form.querySelectorAll("input").forEach(i => { i.disabled = false; });
        btn.dataset.ready = "1";
        setBusy(false);
        return;
      }
      const ordered = $$("[data-op]", tree).sort((a, b) => Number(a.dataset.op) - Number(b.dataset.op));
      let followed = null;
      function follow(done) {
        const row = ordered.find(div => Number(div.dataset.op) >= done) || ordered[ordered.length - 1];
        if (!row || row === followed) return;
        followed = row;
        row.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      follow(0);
      listeners.length = 0;
      listeners.push(s => { markTree(s.done); follow(s.done); });
      watch(last => {
        if (!last) return;
        const owned = last.failed !== null && last.failed !== undefined && ordered.some(d => Number(d.dataset.op) === last.failed);
        markTree(last.done, owned ? last.failed : undefined, last.reason);
        if (last.ok) {
          result.className = "result ok";
          result.textContent = `Imported to ${form.dataset.library}/${last.result.dest_dir}/`;
          // one download fewer: keep the Import tab's count honest without a reload
          const tab = $("header nav a[href='/import']");
          if (tab) {
            const m = tab.textContent.match(/\((\d+)\)/);
            const n = m ? Number(m[1]) - 1 : 0;
            tab.textContent = n > 0 ? `Import (${n})` : "Import";
          }
        } else {
          result.className = "result error";
          result.textContent = last.done ? `Failed after ${last.done} of ${last.ops.length} steps.` : "Failed on the first step.";
          if (!owned && last.reason) result.textContent += `  ${last.reason}`;
        }
      });
    });
  }

  // --- organize -------------------------------------------------------------
  function initOrganize() {
    const btn = $("#apply-btn");
    if (!btn) return;
    const result = $("#plan-result");
    const boxes = () => $$(".issue input[type=checkbox]");
    const ids = () => boxes().filter(b => b.checked).map(b => b.dataset.id);
    let index = {};

    let seq = 0;
    const refresh = debounce(async () => {
      const mine = ++seq;
      try {
        const p = await getJSON("/api/library/plan", { ids: ids() });
        if (mine !== seq) return; // a newer request is in flight
        index = p.index;
        btn.dataset.ready = p.ops.length ? "1" : "";
        clearNote();
      } catch (e) {
        if (mine !== seq) return;
        btn.dataset.ready = "";
        result.textContent = e.message;
        result.className = "result error";
      }
      setBusy(busy);
    }, 150);

    boxes().forEach(b => b.addEventListener("change", () => {
      syncBulk();
      refresh();
    }));
    function syncBulk() {
      $$(".bulk input").forEach(bulk => {
        const group = boxes().filter(b => b.dataset.group === bulk.dataset.bulk);
        bulk.checked = group.length > 0 && group.every(b => b.checked);
        bulk.indeterminate = group.some(b => b.checked) && !bulk.checked;
      });
    }
    $$(".bulk input").forEach(bulk => bulk.addEventListener("change", () => {
      boxes().filter(b => b.dataset.group === bulk.dataset.bulk).forEach(b => { b.checked = bulk.checked; });
      syncBulk();
      refresh();
    }));
    syncBulk();
    refresh();

    function markRows(done, failedAt, reason) {
      $$(".issue[data-id]").forEach(row => {
        const i = index[row.dataset.id];
        if (i === undefined) return;
        row.classList.toggle("done", i < done);
        const failed = failedAt !== undefined && i === failedAt;
        row.classList.toggle("failed", failed);
        if (failed && reason) {
          const why = document.createElement("span");
          why.className = "note warn";
          why.textContent = reason;
          $(".change", row).appendChild(why);
        }
      });
    }

    btn.addEventListener("click", async () => {
      btn.dataset.ready = "";
      setBusy(true);
      boxes().forEach(b => { b.disabled = true; });
      $$(".bulk input").forEach(b => { b.disabled = true; });
      try {
        await getJSON("/api/library/apply", { ids: ids() });
      } catch (e) {
        result.textContent = e.message;
        result.className = "result error";
        boxes().forEach(b => { b.disabled = false; });
        $$(".bulk input").forEach(b => { b.disabled = false; });
        btn.dataset.ready = "1";
        setBusy(false);
        return;
      }
      const ordered = $$(".issue[data-id]")
        .filter(row => index[row.dataset.id] !== undefined)
        .sort((a, b) => index[a.dataset.id] - index[b.dataset.id]);
      let followed = -1;
      function follow(done) {
        // keep the row whose op is running (or the last one done) in view
        const row = ordered.find(r => index[r.dataset.id] >= done) || ordered[ordered.length - 1];
        if (!row || row === followed) return;
        followed = row;
        row.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      follow(0);
      listeners.length = 0;
      listeners.push(s => { markRows(s.done); follow(s.done); });
      watch(last => {
        if (!last) return;
        const owned = last.failed !== null && last.failed !== undefined && Object.values(index).includes(last.failed);
        markRows(last.done, owned ? last.failed : undefined, last.reason);
        if (last.ok) {
          result.className = "result ok";
          result.textContent = "Done.  ";
        } else {
          result.className = "result error";
          result.textContent = (last.done ? `Failed after ${last.done} of ${last.ops.length} ops.` : "Failed on the first op.") + "  ";
          if (!owned && last.reason) result.textContent += `${last.reason}  `;
        }
        const again = document.createElement("a");
        again.href = "/organize"; again.textContent = "Rescan";
        result.appendChild(again);
      });
    });
  }

  // --- boot -----------------------------------------------------------------
  getJSON("/api/status").then(s => {
    if (s.state === "running") {
      // a job started elsewhere: wait for it, then reload to show the result
      const kind = s.kind.charAt(0).toUpperCase() + s.kind.slice(1);
      note(`${kind} running in another tab; waiting…`, "waiting");
      watch(() => location.reload());
    }
  }).catch(() => {});
  if (page === "imports") { initImportList(); initImport(); }
  if (page === "organize") initOrganize();
})();

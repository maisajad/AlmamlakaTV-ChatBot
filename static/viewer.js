"use strict";

/* Source viewer: opens the cited PDF page and highlights the quoted words.
   PDF.js is loaded on first use, so it costs nothing until someone clicks a citation. */

const PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174";

const DocViewer = (() => {
  const panel = document.getElementById("viewer");
  const titleEl = document.getElementById("viewer-title");
  const metaEl = document.getElementById("viewer-meta");
  const noteEl = document.getElementById("viewer-note");
  const body = document.getElementById("viewer-body");
  const openLink = document.getElementById("viewer-open");
  const closeBtn = document.getElementById("viewer-close");
  const docs = new Map();
  let libPromise = null;
  let lastTrigger = null;
  let renderToken = 0;

  function loadLib() {
    libPromise ??= new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = `${PDFJS}/pdf.min.js`;
      s.onload = () => {
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = `${PDFJS}/pdf.worker.min.js`;
        resolve(window.pdfjsLib);
      };
      s.onerror = () => { libPromise = null; reject(new Error("PDF.js failed to load")); };
      document.head.append(s);
    });
    return libPromise;
  }

  async function getDoc(file) {
    if (!docs.has(file)) {
      const lib = await loadLib();
      const source = { url: `/pdfs/${encodeURIComponent(file)}`, httpHeaders: Auth.headers() };
      docs.set(file, lib.getDocument(source).promise.catch((e) => { docs.delete(file); throw e; }));
    }
    return docs.get(file);
  }

  // Words reduced to letters and digits: "$2,400,000" and "2,400,000." both become "2400000".
  const norm = (w) => w.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");

  function tokenize(items) {
    const tokens = [];
    items.forEach((item, idx) => {
      for (const m of item.str.matchAll(/\S+/g)) {
        const word = norm(m[0]);
        if (word) tokens.push({ word, idx, start: m.index, end: m.index + m[0].length });
      }
    });
    return tokens;
  }

  /** Best matching run of quote words on the page: exact sequence first, else the longest run. */
  function findQuote(pageTokens, quote) {
    const want = quote.split(/\s+/).map(norm).filter(Boolean);
    if (!want.length) return null;
    const words = pageTokens.map((t) => t.word);
    for (let i = 0; i + want.length <= words.length; i++) {
      if (want.every((w, j) => words[i + j] === w)) return pageTokens.slice(i, i + want.length);
    }
    let best = { len: 0, at: 0 };
    for (let i = 0; i < words.length; i++) {
      for (let j = 0; j < want.length; j++) {
        let k = 0;
        while (i + k < words.length && j + k < want.length && words[i + k] === want[j + k]) k++;
        if (k > best.len) best = { len: k, at: i };
      }
    }
    return best.len >= Math.max(3, Math.ceil(want.length * 0.6)) ? pageTokens.slice(best.at, best.at + best.len) : null;
  }

  function rectsFor(tokens, items, viewport, lib) {
    const byItem = new Map();
    for (const t of tokens) {
      const r = byItem.get(t.idx);
      byItem.set(t.idx, r ? { start: Math.min(r.start, t.start), end: Math.max(r.end, t.end) } : { start: t.start, end: t.end });
    }
    return [...byItem].map(([idx, { start, end }]) => {
      const item = items[idx];
      const tx = lib.Util.transform(viewport.transform, item.transform);
      const height = Math.hypot(tx[2], tx[3]);
      const width = item.width * viewport.scale;
      const len = item.str.length || 1;
      return { left: tx[4] + (width * start) / len, top: tx[5] - height, width: (width * (end - start)) / len, height };
    });
  }

  async function renderPage(doc, pageNo, quote) {
    const lib = await loadLib();
    const page = await doc.getPage(pageNo);
    const base = page.getViewport({ scale: 1 });
    const scale = Math.min(2, (body.clientWidth - 32) / base.width);
    const viewport = page.getViewport({ scale });
    const dpr = window.devicePixelRatio || 1;

    const canvas = document.createElement("canvas");
    canvas.width = Math.floor(viewport.width * dpr);
    canvas.height = Math.floor(viewport.height * dpr);
    await page.render({ canvasContext: canvas.getContext("2d"), viewport, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null }).promise;

    const items = (await page.getTextContent()).items;
    const match = quote ? findQuote(tokenize(items), quote) : null;
    // Sized in percentages, so the page and its highlights scale together if the panel is resized.
    const sheet = el("div", { className: "viewer-page" }, canvas);
    sheet.style.maxWidth = `${viewport.width}px`;
    sheet.style.aspectRatio = `${viewport.width} / ${viewport.height}`;
    const pct = (v, total) => `${(100 * v) / total}%`;
    for (const r of match ? rectsFor(match, items, viewport, lib) : []) {
      const mark = el("span", { className: "viewer-hl" });
      Object.assign(mark.style, {
        left: pct(r.left - 2, viewport.width), top: pct(r.top - 2, viewport.height),
        width: pct(r.width + 4, viewport.width), height: pct(r.height + 4, viewport.height),
      });
      sheet.append(mark);
    }
    return { sheet, found: !!match };
  }

  async function open(src, lang, trigger) {
    const t = I18N[lang];
    const token = ++renderToken;
    lastTrigger = trigger || null;
    panel.hidden = false;
    document.body.classList.add("viewer-open");
    panel.setAttribute("dir", lang === "ar" ? "rtl" : "ltr");
    titleEl.textContent = src.doc_title;
    metaEl.textContent = `${t.page} ${src.pages.join(", ")} · ${src.section ? `${t.section} ${src.section}: ` : ""}${src.section_title}`;
    noteEl.hidden = true;
    openLink.href = `/pdfs/${encodeURIComponent(src.file)}#page=${src.pages[0]}`;
    openLink.dataset.page = src.pages[0];
    openLink.textContent = t.openPdf;
    closeBtn.setAttribute("aria-label", t.close);
    body.replaceChildren(el("div", { className: "viewer-loading" }, t.loadingDoc));
    closeBtn.focus();

    try {
      const doc = await getDoc(src.file);
      let shown = null;
      for (const p of src.pages) {  // the quote is normally on the chunk's first page
        const result = await renderPage(doc, p, src.quote);
        if (token !== renderToken) return;  // another citation was opened meanwhile
        if (result.found || !shown) shown = result;
        if (result.found) break;
      }
      body.replaceChildren(shown.sheet);
      if (src.quote && !shown.found) { noteEl.textContent = t.quoteNotLocated; noteEl.hidden = false; }
      shown.sheet.querySelector(".viewer-hl")?.scrollIntoView({ block: "center", behavior: "smooth" });
    } catch (err) {
      if (token === renderToken) body.replaceChildren(el("div", { className: "viewer-loading" }, t.docError));
    }
  }

  function close() {
    renderToken++;
    panel.hidden = true;
    document.body.classList.remove("viewer-open");
    lastTrigger?.focus();
  }

  closeBtn.addEventListener("click", close);
  // A plain link can't send the access code, so fetch the PDF with it and open the result.
  openLink.addEventListener("click", async (e) => {
    if (!Object.keys(Auth.headers()).length) return;  // no code in use: the link works as is
    e.preventDefault();
    const tab = window.open("", "_blank");
    const res = await Auth.fetch(openLink.pathname);
    if (!res.ok) { tab?.close(); return; }
    const url = URL.createObjectURL(await res.blob());
    if (tab) tab.location = `${url}#page=${openLink.dataset.page}`;
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) close(); });
  return { open, close };
})();

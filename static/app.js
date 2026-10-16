"use strict";

const I18N = {
  en: {
    title: "Digital Expansion Initiative Assistant",
    switchLanguage: "التبديل إلى العربية",
    langButton: "العربية",
    newChat: "New chat",
    eyebrow: "Almamlaka TV · Project documents",
    welcomeTitle: "Ask about the Digital Expansion Initiative",
    welcomeText: "I answer only from the initiative's project documents and show the source of every answer. Ask in English or Arabic.",
    inputLabel: "Your question",
    placeholder: "Ask a question…",
    send: "Send",
    disclaimer: "Answers come only from 3 project documents and may contain mistakes. Check the cited sources.",
    typing: "Searching the project documents…",
    typingSlow: "Checking the sources, almost there…",
    sources: "Sources",
    page: "p.",
    section: "Section",
    conflict: "Conflicting information in the documents",
    networkError: "Couldn't reach the assistant. Check your connection and try again.",
    modeLabel: "Version",
    modeStandard: "Standard",
    modePro: "Pro RAG Chat",
    modeProHint: "Pro: see each source highlighted in the original PDF, how every answer was found and checked, streaming replies and voice.",
    showInDoc: "Show in document",
    openPdf: "Open PDF",
    close: "Close document",
    loadingDoc: "Opening the document…",
    quoteNotLocated: "Couldn't pinpoint the exact words on this page; showing the cited page.",
    docError: "Couldn't load the document.",
    suggestions: [
      "What is the total budget of the initiative?",
      "When is the public launch?",
      "Who is on the project team?",
      "Which platforms does the initiative cover?",
    ],
  },
  ar: {
    title: "مساعد مبادرة التوسع الرقمي",
    switchLanguage: "Switch to English",
    langButton: "English",
    newChat: "محادثة جديدة",
    eyebrow: "قناة المملكة · وثائق المشروع",
    welcomeTitle: "اسأل عن مبادرة التوسع الرقمي",
    welcomeText: "أجيب فقط من وثائق المشروع، وأذكر مصدر كل إجابة. يمكنك السؤال بالعربية أو الإنجليزية.",
    inputLabel: "سؤالك",
    placeholder: "اكتب سؤالك…",
    send: "إرسال",
    disclaimer: "الإجابات مستندة إلى 3 وثائق للمشروع فقط وقد تحتوي على أخطاء. راجع المصادر المذكورة.",
    typing: "جارٍ البحث في وثائق المشروع…",
    typingSlow: "جارٍ التحقق من المصادر، لحظات…",
    sources: "المصادر",
    page: "ص.",
    section: "القسم",
    conflict: "معلومات متعارضة بين الوثائق",
    networkError: "تعذّر الاتصال بالمساعد. تحقّق من اتصالك وحاول مجددًا.",
    modeLabel: "الإصدار",
    modeStandard: "قياسي",
    modePro: "Pro RAG Chat",
    modeProHint: "Pro: شاهد كل مصدر مظلّلًا في ملف PDF الأصلي، وكيف وُجدت كل إجابة وتم التحقق منها، مع ردود متدفقة ودعم الصوت.",
    showInDoc: "عرض في الوثيقة",
    openPdf: "فتح ملف PDF",
    close: "إغلاق الوثيقة",
    loadingDoc: "جارٍ فتح الوثيقة…",
    quoteNotLocated: "تعذّر تحديد النص بدقة في هذه الصفحة؛ تُعرض الصفحة المذكورة.",
    docError: "تعذّر تحميل الوثيقة.",
    suggestions: [
      "ما هي الميزانية الإجمالية للمبادرة؟",
      "متى موعد الإطلاق العام؟",
      "من هم أعضاء فريق المشروع؟",
      "ما هي المنصات التي تشملها المبادرة؟",
    ],
  },
};
const INFO_STATUSES = new Set(["not_in_documents", "out_of_scope", "greeting", "too_long", "rate_limited", "busy"]);

const $ = (id) => document.getElementById(id);
const els = {
  messages: $("messages"), welcome: $("welcome"), suggestions: $("suggestions"),
  form: $("composer"), input: $("input"), send: $("send"), langToggle: $("lang-toggle"), newChat: $("new-chat"),
  modeButtons: [...document.querySelectorAll("[data-mode]")], modeHint: $("mode-hint"),
};

const store = {
  get(area, key) { try { return window[area].getItem(key); } catch { return null; } },
  set(area, key, value) { try { value == null ? window[area].removeItem(key) : window[area].setItem(key, value); } catch { /* storage unavailable */ } },
};

let uiLang = store.get("localStorage", "uiLang") || ((navigator.language || "").startsWith("ar") ? "ar" : "en");
// "standard" is the assignment as specified; "pro" layers on the extra features. ?mode=pro links straight to it.
let mode = new URLSearchParams(location.search).get("mode") || store.get("localStorage", "mode") || "standard";
const isPro = () => mode === "pro";
// Not persisted: a reload clears the visible chat, so the server-side history must start over too.
let sessionId = null;
let busy = false;

// ---------- UI language ----------

function applyLanguage(lang) {
  uiLang = lang;
  store.set("localStorage", "uiLang", lang);
  const t = I18N[lang];
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t[el.dataset.i18n]; });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t[el.dataset.i18nPlaceholder]; });
  document.querySelectorAll("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t[el.dataset.i18nAria]); });
  els.langToggle.textContent = t.langButton;
  els.modeHint.textContent = t.modeProHint;
  els.suggestions.replaceChildren(...t.suggestions.map((q) => {
    const chip = el("button", { className: "chip", type: "button", dir: "auto" }, q);
    chip.addEventListener("click", () => ask(q));
    return chip;
  }));
}

function applyMode(next) {
  mode = next === "pro" ? "pro" : "standard";
  store.set("localStorage", "mode", mode);
  document.body.classList.toggle("mode-pro", isPro());
  for (const btn of els.modeButtons) btn.setAttribute("aria-pressed", String(btn.dataset.mode === mode));
  if (!isPro() && window.DocViewer) DocViewer.close();
}

// ---------- small DOM helpers ----------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.includes("-") || key === "role") node.setAttribute(key, value); // aria-*, role
    else node[key] = value;
  }
  for (const child of children) if (child != null) node.append(child);
  return node;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Minimal Markdown (paragraphs, lists, bold, italics, code) with [n] turned into citation buttons.
 *  Input is escaped first, so the only HTML in the output is what this function adds. */
function renderMarkdown(text, citationCount) {
  const inline = (s) => escapeHtml(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*(?!\s)(.+?)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    // Inside Arabic text the bidi algorithm can render "$120,000" as "120,000$"; isolate amounts as LTR.
    .replace(/\$\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:million|M))?/g, '<bdi dir="ltr">$&</bdi>')
    .replace(/\[(\d+)\]/g, (m, n) => (+n >= 1 && +n <= citationCount
      ? `<button type="button" class="cite" data-n="${n}" aria-label="Source ${n}">${n}</button>` : m));

  const html = [];
  let para = [], list = null;
  const flushPara = () => { if (para.length) html.push(`<p>${para.map(inline).join("<br>")}</p>`); para = []; };
  const flushList = () => { if (list) html.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; };

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    const numbered = line.match(/^\d+[.)]\s+(.*)$/);
    if (!line) { flushPara(); flushList(); continue; }
    if (bullet || numbered) {
      flushPara();
      const tag = bullet ? "ul" : "ol";
      if (list && list.tag !== tag) flushList();
      list = list || { tag, items: [] };
      list.items.push((bullet || numbered)[1]);
    } else {
      flushList();
      para.push(line);
    }
  }
  flushPara(); flushList();
  return html.join("");
}

function sourceLabel(src, t) {
  const pages = src.pages.join(", ");
  return [el("span", { className: "source-doc" }, src.doc_title),
          el("span", { className: "source-loc" }, ` · ${t.page} ${pages} · ${t.section} ${src.section}: ${src.section_title}`)];
}

// ---------- messages ----------

function scrollToBottom() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

function addUserMessage(text) {
  els.welcome.hidden = true;
  els.messages.append(el("li", { className: "msg msg-user" }, el("div", { className: "bubble", dir: "auto" }, text)));
  scrollToBottom();
}

function addTyping() {
  const t = I18N[uiLang];
  const label = el("span", {}, t.typing);
  const node = el("li", { className: "msg msg-bot" },
    el("div", { className: "avatar", "aria-hidden": "true" }, "م"),
    el("div", { className: "card is-info" },
      el("div", { className: "typing", role: "status" }, el("span", { className: "dots", "aria-hidden": "true" }, el("i"), el("i"), el("i")), label)));
  const slow = setTimeout(() => { label.textContent = t.typingSlow; }, 7000);
  els.messages.append(node);
  scrollToBottom();
  return () => { clearTimeout(slow); node.remove(); };
}

function addBotMessage(reply) {
  const lang = reply.language === "ar" ? "ar" : "en";
  const t = I18N[lang];
  const card = el("div", {
    className: "card" + (INFO_STATUSES.has(reply.status) ? " is-info" : "") + (reply.status === "error" ? " is-error" : ""),
    dir: lang === "ar" ? "rtl" : "ltr", lang,
  });

  const answer = el("div", { className: "answer" });
  answer.innerHTML = renderMarkdown(reply.answer || "", reply.citations.length);
  card.append(answer);

  for (const conflict of reply.conflicts || []) {
    card.append(el("div", { className: "conflict", role: "note" },
      el("div", { className: "conflict-head" }, el("span", { "aria-hidden": "true" }, "⚠"), `${t.conflict}: ${conflict.topic}`),
      el("ul", {}, ...conflict.claims.map((claim) =>
        el("li", {}, `${claim.statement} `, el("span", { className: "src" }, "(", ...sourceLabel(claim, t), ")"))))));
  }

  if (reply.citations.length) {
    // One entry per document section; several [n] markers can point at the same one.
    const groups = new Map();
    for (const c of reply.citations) {
      if (!groups.has(c.chunk_id)) groups.set(c.chunk_id, { src: c, items: [] });
      groups.get(c.chunk_id).items.push(c);
    }
    const sources = el("div", { className: "sources" }, el("p", { className: "sources-title" }, t.sources));
    const entryFor = {};
    const citationFor = Object.fromEntries(reply.citations.map((c) => [c.n, c]));
    for (const { src, items } of groups.values()) {
      const entry = el("details", { className: "source" },
        el("summary", {}, el("span", { className: "source-n" }, items.map((c) => `[${c.n}]`).join("")),
                      el("span", {}, ...sourceLabel(src, t))),
        ...items.map((c) => {
          const show = el("button", { type: "button", className: "show-in-doc pro-only" }, t.showInDoc);
          show.addEventListener("click", () => DocViewer.open(c, lang, show));
          return el("div", { className: "quote-row" }, el("blockquote", { lang: "en" }, `“${c.quote}”`), show);
        }));
      for (const c of items) entryFor[c.n] = entry;
      sources.append(entry);
    }
    card.append(sources);
    answer.addEventListener("click", (e) => {
      const btn = e.target.closest(".cite");
      if (!btn) return;
      if (isPro()) DocViewer.open(citationFor[btn.dataset.n], lang, btn);  // Pro: straight to the highlighted page
      const source = entryFor[btn.dataset.n];
      source.open = true;
      source.scrollIntoView({ behavior: "smooth", block: "nearest" });
      source.classList.add("is-flash");
      setTimeout(() => source.classList.remove("is-flash"), 1200);
    });
  }

  const trace = window.renderTrace ? renderTrace(reply, lang) : null;  // Pro-only panel (hidden in Standard)
  if (trace) card.append(trace);

  els.messages.append(el("li", { className: "msg msg-bot" }, el("div", { className: "avatar", "aria-hidden": "true" }, "م"), card));
  scrollToBottom();
}

// ---------- talking to the API ----------

async function ask(question) {
  question = question.trim();
  if (!question || busy) return;
  busy = true;
  els.send.disabled = true;
  addUserMessage(question);
  els.input.value = "";
  autosize();
  let stopTyping = () => {};
  try {
    // Pro streams with live steps; Standard waits for the complete reply behind a typing indicator.
    const live = isPro() ? createLiveCard(guessLanguage(question)) : null;
    stopTyping = live ? () => live.remove() : addTyping();
    let reply;
    if (live) {
      reply = await streamReply(question, live);
    } else {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question, session_id: sessionId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      reply = await res.json();
    }
    sessionId = reply.session_id;
    stopTyping();
    addBotMessage(reply);
  } catch (err) {
    stopTyping();
    const lang = /[؀-ۿ]/.test(question) ? "ar" : uiLang;
    addBotMessage({ status: "error", language: lang, answer: I18N[lang].networkError, citations: [], conflicts: [] });
  } finally {
    busy = false;
    els.send.disabled = false;
    els.input.focus();
  }
}

async function newChat() {
  if (sessionId) {
    fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ session_id: sessionId }) }).catch(() => {});
  }
  sessionId = null;
  els.messages.replaceChildren();
  els.welcome.hidden = false;
  els.input.focus();
}

function autosize() {
  els.input.style.height = "auto";
  els.input.style.height = `${els.input.scrollHeight}px`;
}

els.form.addEventListener("submit", (e) => { e.preventDefault(); ask(els.input.value); });
els.input.addEventListener("input", autosize);
els.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(els.input.value); }
});
els.langToggle.addEventListener("click", () => applyLanguage(uiLang === "ar" ? "en" : "ar"));
els.newChat.addEventListener("click", newChat);
for (const btn of els.modeButtons) btn.addEventListener("click", () => applyMode(btn.dataset.mode));

applyLanguage(uiLang);
applyMode(mode);

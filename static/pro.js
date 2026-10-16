"use strict";

/* Pro mode: streamed replies with live progress steps, and the "How I found this" trace.
   Standard mode never calls anything in this file. */

const PRO_I18N = {
  en: {
    steps: { understand: "Understanding the question", search: "Searching the project documents",
             write: "Writing the answer", verify: "Checking every citation against its source" },
    understoodAs: (q) => `Read as: “${q}”`,
    found: (s, d) => `Found ${s} relevant sections in ${d} document${d === 1 ? "" : "s"}`,
    conflictsAhead: (n) => `${n} known conflict${n === 1 ? "" : "s"} in these sections`,
    verified: (n) => `${n} citation${n === 1 ? "" : "s"} verified`,
    verifyFailed: "A check failed, so the answer is being rewritten",
    draftLabel: "Draft, not verified yet",
    rewriting: "Rewriting after a failed check…",
    traceTitle: "How I found this",
    traceSummary: (s, c, sec) => `${s} sections searched · ${c} citations verified · ${sec} s`,
    traceSummaryNoAnswer: (sec) => `No answer given · ${sec} s`,
    readAs: "Understood as",
    followUp: "Follow-up: rewritten using the earlier conversation",
    searched: "Sections retrieved",
    keyword: "keyword", meaning: "meaning",
    viaRelated: "pulled in: other side of a known conflict",
    viaPrevious: "kept from the previous answer",
    cited: "cited",
    checks: "Checks",
    attemptOk: (n) => `${n} citations, each quote found verbatim in its section; figures matched exactly; answer in your language`,
    attemptRejected: (n) => `First draft rejected (${n} problem${n === 1 ? "" : "s"}) and rewritten`,
    noAnswerDocs: "The documents don't cover this, so no answer was given",
    noAnswerScope: "Outside the documents' scope, so it was declined",
    refusedEarly: "Recognized as off-topic or an attempt to change my instructions, and declined before any search",
    knownConflicts: "Known conflicts in these sections",
    modelTime: "Model and time",
    timing: (t) => [t.understand && `understanding ${fmtMs(t.understand)}`, t.search != null && `search ${fmtMs(t.search)}`,
                    t.answer && `answer ${fmtMs(t.answer)}`, t.total && `total ${fmtMs(t.total)}`].filter(Boolean).join(" · "),
  },
  ar: {
    steps: { understand: "فهم السؤال", search: "البحث في وثائق المشروع", write: "كتابة الإجابة",
             verify: "التحقق من كل اقتباس مقابل مصدره" },
    understoodAs: (q) => `فُهم على أنه: “${q}”`,
    found: (s, d) => `تم العثور على ${s} أقسام ذات صلة في ${d} ${d === 1 ? "وثيقة" : "وثائق"}`,
    conflictsAhead: (n) => `${n} ${n === 1 ? "تعارض معروف" : "تعارضات معروفة"} في هذه الأقسام`,
    verified: (n) => `تم التحقق من ${n} اقتباسات`,
    verifyFailed: "فشل أحد الفحوصات، لذا تُعاد كتابة الإجابة",
    draftLabel: "مسودة، لم يتم التحقق منها بعد",
    rewriting: "إعادة الكتابة بعد فشل أحد الفحوصات…",
    traceTitle: "كيف وجدت هذه الإجابة",
    traceSummary: (s, c, sec) => `${s} أقسام تم البحث فيها · ${c} اقتباسات تم التحقق منها · ${sec} ث`,
    traceSummaryNoAnswer: (sec) => `لم تُقدَّم إجابة · ${sec} ث`,
    readAs: "فُهم السؤال على أنه",
    followUp: "سؤال متابعة: أُعيدت صياغته اعتمادًا على المحادثة السابقة",
    searched: "الأقسام المسترجعة",
    keyword: "الكلمات", meaning: "المعنى",
    viaRelated: "أُضيف: الطرف الآخر من تعارض معروف",
    viaPrevious: "أُبقي من الإجابة السابقة",
    cited: "مُستشهد به",
    checks: "الفحوصات",
    attemptOk: (n) => `${n} اقتباسات، وُجد كل منها حرفيًا في قسمه؛ الأرقام مطابقة تمامًا؛ الإجابة بلغتك`,
    attemptRejected: (n) => `رُفضت المسودة الأولى (${n} ${n === 1 ? "مشكلة" : "مشكلات"}) وأُعيدت كتابتها`,
    noAnswerDocs: "الوثائق لا تغطي هذا السؤال، لذا لم تُقدَّم إجابة",
    noAnswerScope: "السؤال خارج نطاق الوثائق، لذا تم الاعتذار",
    refusedEarly: "صُنّف على أنه خارج الموضوع أو محاولة لتغيير تعليماتي، فتم رفضه قبل أي بحث",
    knownConflicts: "تعارضات معروفة في هذه الأقسام",
    modelTime: "النموذج والوقت",
    timing: (t) => [t.understand && `الفهم ${fmtMs(t.understand)}`, t.search != null && `البحث ${fmtMs(t.search)}`,
                    t.answer && `الإجابة ${fmtMs(t.answer)}`, t.total && `الإجمالي ${fmtMs(t.total)}`].filter(Boolean).join(" · "),
  },
};
const STEP_ORDER = ["understand", "search", "write", "verify"];

function fmtMs(ms) { return ms < 100 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`; }

function guessLanguage(text) {
  const arabic = (text.match(/[؀-ۿ]/g) || []).length;
  const latin = (text.match(/[A-Za-z]/g) || []).length;
  if (!arabic && !latin) return uiLang;
  return arabic / (arabic + latin) >= 0.3 ? "ar" : "en";
}

// ---------- live card while the answer streams ----------

function createLiveCard(lang) {
  const p = PRO_I18N[lang];
  const rows = Object.fromEntries(STEP_ORDER.map((id) => [id, el("li", { className: "step is-pending" },
    el("span", { className: "step-icon", "aria-hidden": "true" }),
    el("span", { className: "step-text" }, el("span", { className: "step-label" }, p.steps[id]), el("span", { className: "step-detail" })))]));
  const draftText = el("div", { className: "draft-text answer", dir: "auto" });
  let draftRaw = "";
  const draftNote = el("p", { className: "draft-note" }, p.draftLabel);
  const draft = el("div", { className: "draft", hidden: true }, draftNote, draftText);
  const card = el("div", { className: "card live", dir: lang === "ar" ? "rtl" : "ltr", lang },
    el("ol", { className: "steps", role: "status" }, ...Object.values(rows)), draft);
  const node = el("li", { className: "msg msg-bot" }, el("div", { className: "avatar", "aria-hidden": "true" }, "م"), card);
  els.messages.append(node);
  scrollToBottom();
  let attempt = 1;

  return {
    step(e) {
      const row = rows[e.step];
      if (!row) return;
      row.className = `step is-${e.status}`;
      const d = e.detail || {}, detail = row.querySelector(".step-detail");
      if (e.step === "understand" && e.status === "done" && d.understood_as) detail.textContent = p.understoodAs(d.understood_as);
      if (e.step === "search" && e.status === "done") {
        detail.textContent = p.found(d.sections, d.documents) + (d.known_conflicts?.length ? ` · ${p.conflictsAhead(d.known_conflicts.length)}` : "");
      }
      if (e.step === "verify" && e.status === "done") detail.textContent = p.verified(d.citations);
      if (e.step === "verify" && e.status === "failed") { detail.textContent = p.verifyFailed; rows.write.className = "step is-active"; }
      if (e.step === "write" && e.status === "active" && d.attempt > 1) detail.textContent = p.rewriting;
    },
    draft(e) {
      if (e.attempt !== attempt) { attempt = e.attempt; draftRaw = ""; }
      draft.hidden = false;
      draftRaw += e.delta;
      draftText.innerHTML = renderMarkdown(draftRaw, 0);  // escaped first; [n] markers stay plain text in a draft
      if (window.scrollY + innerHeight > document.body.scrollHeight - 200) window.scrollTo({ top: document.body.scrollHeight });
    },
    remove() { node.remove(); },
  };
}

/** POST to the streaming endpoint and feed events to the live card; resolves with the final reply. */
async function streamReply(question, live) {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: question, session_id: sessionId }),
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const data = frame.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("");
      if (!data) continue;
      const event = JSON.parse(data);
      if (event.type === "step") live.step(event);
      else if (event.type === "draft") live.draft(event);
      else if (event.type === "result") return event.reply;
      else if (event.type === "error") throw new Error("stream error");
    }
  }
  throw new Error("stream ended without a result");
}

// ---------- "How I found this" ----------

function renderTrace(reply, lang) {
  const tr = reply.trace;
  if (!tr) return null;
  const p = PRO_I18N[lang];
  const cited = new Set(reply.citations.map((c) => c.chunk_id));
  const seconds = ((tr.timings_ms?.total || 0) / 1000).toFixed(1);
  const section = (title, ...body) => el("div", { className: "trace-section" }, el("h4", {}, title), ...body);
  const parts = [];

  if (tr.understood_as) {
    parts.push(section(p.readAs, el("p", { className: "trace-query", dir: "ltr", lang: "en" }, `“${tr.understood_as}”`),
      tr.follow_up ? el("span", { className: "badge" }, p.followUp) : null));
  }
  if (tr.retrieval?.length) {
    parts.push(section(p.searched, el("ul", { className: "trace-hits" }, ...tr.retrieval.map((h) => el("li", {},
      el("span", { className: "hit-name" }, h.doc_title, el("span", { className: "hit-sec" }, ` · ${I18N[lang].section} ${h.section}: ${h.section_title}`)),
      el("span", { className: "hit-badges" },
        h.bm25_rank ? el("span", { className: "rank" }, `${p.keyword} #${h.bm25_rank}`) : null,
        el("span", { className: "rank" }, `${p.meaning} #${h.dense_rank}`),
        h.via === "related" ? el("span", { className: "badge warn" }, p.viaRelated) : null,
        h.via === "previous" ? el("span", { className: "badge" }, p.viaPrevious) : null,
        cited.has(h.chunk_id) ? el("span", { className: "badge ok" }, `✓ ${p.cited}`) : null))))));
  }

  const checks = [];
  if (!tr.retrieval?.length && reply.status === "out_of_scope") checks.push(p.refusedEarly);
  for (const a of tr.attempts || []) {
    if (a.status === "answered" && !a.problems.length) checks.push(`✓ ${p.attemptOk(a.citations)}`);
    else if (a.status === "answered") checks.push(p.attemptRejected(a.problems.length));
    else if (a.status === "not_in_documents") checks.push(p.noAnswerDocs);
    else if (a.status === "out_of_scope") checks.push(p.noAnswerScope);
  }
  if (checks.length) parts.push(section(p.checks, el("ul", { className: "trace-checks" }, ...checks.map((c) => el("li", {}, c)))));
  if (tr.known_conflicts?.length) parts.push(section(p.knownConflicts, el("p", {}, tr.known_conflicts.join(" · "))));
  parts.push(section(p.modelTime, el("p", { dir: "ltr" }, `${tr.model} · ${p.timing(tr.timings_ms || {})}`)));

  const summary = reply.status === "answered"
    ? p.traceSummary(tr.retrieval.length, reply.citations.length, seconds) : p.traceSummaryNoAnswer(seconds);
  return el("details", { className: "trace pro-only" },
    el("summary", {}, el("span", { className: "trace-title" }, p.traceTitle), el("span", { className: "trace-meta" }, summary)),
    ...parts);
}

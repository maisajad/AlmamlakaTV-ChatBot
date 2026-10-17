# Almamlaka TV Assistant

A bilingual (Arabic / English) RAG chatbot that answers questions about Almamlaka TV's **Digital
Expansion Initiative** using only its three project PDFs. Every answer cites its document, page and
section; conflicting information is flagged, not resolved; anything outside the documents gets a clear
"I don't have that information".

- **Live demo:** https://almamlaka-assistant-hrj9.onrender.com (free tier: after 15 idle minutes the
  first load takes about a minute to wake up). It asks for the access code sent with this submission.
- **Test results, and attacks to try yourself:** https://almamlaka-assistant-hrj9.onrender.com/quality
- **More:** [why it's built this way](docs/DECISIONS.md) · [technical details, deploy, run locally](docs/DETAILS.md) · [2-minute demo plan](docs/DEMO_SCRIPT.md)

## Sample Q&A

Captured from the running app, in case the live link is unavailable during review.

| | |
|---|---|
| **Conflicting figures, flagged and cited.** Both budgets are given with their sources; the bot doesn't pick one. ![English budget question](docs/screenshots/1-conflict-english.png) | **Arabic, with a dialect follow-up.** The launch-date conflict in Arabic, then *"ومين بقود المشروع؟"* ("and who leads the project?") answered from context. ![Arabic conversation](docs/screenshots/2-arabic-follow-up.png) |
| **Prompt injection and out-of-scope.** An attempt to extract the system prompt is declined, and a question the PDFs don't cover gets "I don't have that information". ![Injection and out-of-scope](docs/screenshots/3-out-of-scope-and-injection.png) | **Source viewer.** Clicking a citation opens the PDF page with the quoted text highlighted. ![Source viewer](docs/screenshots/4-source-viewer.png) |

## Approach

```
message ─► route + rewrite ─► hybrid retrieval ─► cited answer ─► verify in code ─► UI
           (Claude Haiku)     (BM25 + e5, RRF)    (Claude Sonnet,   citations real?
                                                   JSON)            numbers exact?
                                                                    right language?
```

### Chunking: one chunk per document section

PDFs are parsed with `pdfplumber` ([app/ingest.py](app/ingest.py)):

- **One chunk per numbered section** ("3. Key Details"). The documents are short and well
  structured, so a section is a natural unit of meaning, and it's what a citation should point to:
  *"Project Overview Document · p. 1 · Section 3: Key Details"*.
- **Tables are kept whole and converted to Markdown**, so a budget row never gets separated from its
  column headers.
- **Wrapped lines are rejoined into paragraphs** using the vertical gap between lines, so sentences
  aren't cut at line breaks.
- **Fallbacks:** text before the first section becomes an "Introduction" chunk; a PDF with no numbered
  sections is split one chunk per page. Sections over 2,500 characters are split on paragraph
  boundaries.
- **Every chunk carries its metadata** (document, file, pages, section number and title), which is how
  citation labels are built. The model never writes them.

The result is 16 chunks of 130–520 characters. Fixed-size windows with overlap weren't needed: they
would cut tables and blur section boundaries, and these sections are already small.

### Embedding model: `intfloat/multilingual-e5-small`

- **One vector space for Arabic and English**, so an Arabic question finds an English passage
  directly, without translating it first. 384 dimensions, mean-pooled and L2-normalized, with the
  `query:` / `passage:` prefixes e5 expects.
- **What gets embedded:** the document and section titles go in front of the chunk text, because they
  carry much of the meaning ("Budget Notes").
- **Runs on ONNX Runtime** with the model's official int8 export (118 MB) instead of PyTorch, so it fits
  Render's free 512 MB instance. Retrieval recall is unchanged.

### Vector store: in-memory NumPy, no vector database

The 16 chunk vectors form a 16 × 384 matrix, computed when the Docker image is built. A search is
one matrix-vector product (cosine similarity on normalized vectors). At this size a vector database
would add a network hop, a service to run and a cost, without finding anything better. `Retriever` in
[app/retrieval.py](app/retrieval.py) is the single place to swap in pgvector or Qdrant if the corpus
grows to thousands of chunks.

### Retrieval: hybrid search

- **BM25** catches exact figures and names ("$2,400,000", "Q3"). **Embeddings** catch paraphrases and
  Arabic: BM25 alone finds the right section for only 2 of 24 Arabic questions.
- The two rankings are merged with **reciprocal rank fusion** (k = 60), and the **top 4** chunks are kept.
- Both the user's message and the rewritten question are searched. For follow-ups, the previous
  answer's sources stay in view.
- **Conflict groups:** retrieving one side of a known discrepancy pulls in every other side, so a
  conflict is never half-reported.

### Generation and verification

1. **Route and rewrite** (Claude Haiku 5.5). Each message is classified as a question, greeting,
   off-topic or injection, and turned into a standalone question using the conversation: *"What about
   its budget?"* → *"What is the budget of the initiative?"*. This handles Jordanian dialect and Arabizi
   too. Off-topic messages and injection attempts get a fixed reply and never reach the answer model.
2. **Answer** (Claude Sonnet 5.5, structured JSON output). The reply has a status, the answer with
   `[n]` markers, citations (chunk id + verbatim quote) and conflicts. Documents and user text are
   passed as tagged data, never as instructions.
3. **Verify, in code.** Each citation must point to a retrieved chunk, and its quote must actually
   appear there: wording may differ slightly, but every number must match exactly. The reply must also
   be in the user's language. If a check fails, the model gets one retry with the problems listed;
   after that the bot says "I don't have that information".

Conversations are kept server-side (the last 6 turns, in Redis). Replies stream as they're written.

## How each requirement is met

| Requirement | Mechanism |
|---|---|
| Answers strictly from the PDFs | Prompt rules + citation verifier: no valid citation, no answer |
| Out-of-scope → says so | `not_in_documents` / `out_of_scope` statuses with fixed replies |
| Cites document and page/section | Labels built from chunk metadata; quote on expand; highlighted in the PDF |
| Flags conflicting information | Reviewed conflict registry + conflict groups + amber callout |
| Multi-turn follow-ups | Server-side sessions; the rewrite step resolves "it", "she", "and Q4?" |
| Replies in the user's language | Per-message detection (incl. Arabizi); output checked and retried; RTL UI |
| Resists prompt injection | Router triage, data tagging, no tools, uncited output dropped |
| Almamlaka TV branding | Logo and palette from almamlakatv.com |
| Live deployment | Render: Docker web service + Key Value (Redis), free tier |

## Results

All evals run through the same pipeline as the UI, both locally and against the live deployment.

| Eval | Result |
|---|---|
| Retrieval recall@4, 24 questions in English and Arabic | **24/24 EN, 24/24 AR** |
| Single-turn answers: facts, conflicts, out-of-scope, injection, dialect | **30/30** |
| Multi-turn conversations | **21/21 turns** across 9 conversations |
| Unit tests | **95/95** |

Category breakdown and every answer: [quality page](https://almamlaka-assistant-hrj9.onrender.com/quality)
and [docs/DETAILS.md](docs/DETAILS.md#evaluation).

## Stack

Python 3.12 · FastAPI · vanilla JS · Claude Sonnet 5.5 and Haiku 5.5 (Anthropic SDK) · `pdfplumber` ·
`rank-bm25` · `multilingual-e5-small` on ONNX Runtime · NumPy · Redis · Docker on Render.

To run it locally:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
cp .env.example .env                                       # then put your Anthropic API key in .env
.venv/Scripts/python -m uvicorn app.main:app --port 7860
```

# Almamlaka TV Assistant

A bilingual (Arabic / English) RAG chatbot that answers questions about Almamlaka TV's **Digital
Expansion Initiative** using only its project PDFs. Every answer cites its source document, page and
section; conflicting information is flagged rather than resolved; anything outside the documents gets
a clear "I don't have that information".

- **Live demo:** https://almamlaka-assistant-hrj9.onrender.com (free tier: after 15 idle minutes the
  first load takes about a minute to wake up)
- **Pro version directly:** https://almamlaka-assistant-hrj9.onrender.com/?mode=pro
- **Test results, and attacks to try yourself:** https://almamlaka-assistant-hrj9.onrender.com/quality
- **Why it's built this way:** [docs/DECISIONS.md](docs/DECISIONS.md) · **2-minute demo plan:** [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)

## Two versions, one switch

A **Standard / Pro RAG Chat** switch sits under the header. Both run through the same verified pipeline.

| | Standard | Pro RAG Chat |
|---|---|---|
| Grounded answers, citations, conflict flags, refusals, follow-ups, Arabic/English, injection resistance | ✓ | ✓ |
| Click a citation → the original PDF page opens with the quoted words highlighted | | ✓ |
| Replies stream as they're written; the verified reply replaces the draft | | ✓ |
| Ask by voice (Jordanian Arabic or English) and listen to answers | | ✓ |

## How it answers a message

```
message ─► guard ─► rewrite ─► retrieve ─► answer ─► verify ─► UI
           length,   intent +    BM25 +       Claude      citations real?
           rate      standalone  embeddings   Sonnet 5.5, quotes verbatim?
           limits    English     (RRF), top-4 JSON with   right language?
                     question    + conflict   citations   no → retry once,
                                 groups                   then "not in docs"
```

1. **Guard.** Messages over 1,000 characters, more than 15 messages a minute per session, or more than
   the hourly cap across all visitors (`GLOBAL_HOURLY_LIMIT`, default 300) get a fixed reply.
2. **Rewrite / route** (Claude Haiku 5.5, low effort). Classifies the message (`question`, `greeting`,
   `off_topic`, `injection`) and rewrites it as a standalone English question using the conversation:
   *"What about its budget?"* → *"What is the budget of the initiative?"*. It understands Jordanian
   dialect (*قديش، إيمتى، مين*) and Arabizi (*"shu el budget?"*). Off-topic and injection messages get a
   fixed reply and never reach the answer step.
3. **Retrieve.** Hybrid search over section-level chunks: BM25 for exact figures and names,
   `intfloat/multilingual-e5-small` embeddings for paraphrases and Arabic, fused with reciprocal rank
   fusion. Both the user's message and the rewrite are searched; the previous answer's sources stay in
   view for follow-ups.
4. **Conflict groups.** Known discrepancies (`data/conflicts.json`) are found by a Claude pass and
   reviewed. Retrieving one side of a conflict pulls in every other side, transitively, and the prompt
   names the discrepancy, so flagging conflicts doesn't depend on chance.
5. **Answer** (Claude Sonnet 5.5, structured JSON): `status`, `answer` with `[n]` markers, `citations`
   (chunk id + verbatim quote) and `conflicts`.
6. **Verify, in code.** Each citation must point to a retrieved chunk, and its quote must really be in
   it (fuzzy for wording, *exact* for every number). The answer and conflict text must be in the user's
   language. One retry with the problems listed; then "I don't have that information". Refusals always
   show a fixed bilingual message, never model text.

## How each requirement is met

| Requirement | Mechanism |
|---|---|
| Answers strictly from the PDFs | Prompt rules + citation verifier: no valid citation, no answer |
| Out-of-scope → says so | `not_in_documents` / `out_of_scope` statuses with fixed replies; router short-circuits off-topic |
| Cites document and page/section | Labels built from chunk metadata, never model text; verbatim quote on expand; Pro highlights it in the PDF |
| Flags conflicting information | Reviewed conflict registry + conflict-group retrieval + `conflicts` field + amber callout |
| Multi-turn follow-ups | Server-side sessions (last 6 turns, in Redis when available); rewrite resolves "it", "she", "and Q4?" |
| Replies in the user's language | Per-message detection incl. Arabizi; output checked by script and retried if wrong; RTL UI |
| Resists prompt injection | Router triage; user text and documents tagged as data; no tools; uncited output dropped |
| Almamlaka TV branding | Logo and palette (`#9e0b0f`, `#1b2431`, `#343434`) taken from almamlakatv.com |
| Live deployment | Render (Docker web service + Key Value, free tier) |

## Beyond the brief

- **Source viewer (Pro):** a citation opens the cited PDF page (PDF.js) with the quote highlighted,
  table cells included.
- **Streaming (Pro):** answer text appears as it's generated, in a lighter colour; the verified
  reply replaces it.
- **Jordanian dialect and Arabizi**, answered in Modern Standard Arabic.
- **Voice (Pro):** dictation and read-aloud through the browser's speech APIs.
- **New PDFs without scripts:** PDFs committed to `data/pdfs` are re-ingested automatically at startup
  when they change; `/admin` (enabled by `ADMIN_TOKEN`) uploads a PDF and makes it searchable within
  seconds, without a restart. Conflict detection reruns in the background either way.
- **Persistent conversations:** with `REDIS_URL` set, sessions, uploads and the usage cap survive the
  web service restarting.
- **"Try to break it" page (`/quality`):** every eval case with the bot's actual answer,
  and one-click attacks.

## Known conflicts in the documents

| Topic | Source A | Source B |
|---|---|---|
| Total budget | Overview p.1 §3 and the Budget table: **$2,400,000** | Budget p.1 §2: revised to **$2,600,000** (Finance Committee, Dec 2026) |
| Launch date | Overview p.1 §3 and Budget p.2 §3: **March 15, 2027** | Team p.1 §3: moved to **April 1, 2027** (steering committee, Jan 20, 2027) |
| QA vs launch | Budget p.2 §3: QA runs **Mar 1–20, 2027** | Same table: public launch **March 15, 2027**, before QA ends |

Not a conflict but a trap: the Overview says the app will support **12 languages** and names only 4.
The bot names those 4 and says the other 8 aren't listed.

## Evaluation

Latest run: 2026-10-17, Claude Sonnet 5.5 (answers) and Claude Haiku 5.5 (routing), against both a local
instance and the live Render deployment, with the same results. Every eval goes through the same
pipeline the UI uses. The full results, with every answer, are on the
[quality page](https://almamlaka-assistant-hrj9.onrender.com/quality).

| Eval | Result |
|---|---|
| Retrieval, recall@4 (24 questions × EN/AR) | hybrid **24/24 EN, 24/24 AR** (BM25 alone 23/24 EN, 2/24 AR; embeddings alone 24/24 both) |
| Single-turn answers (`eval/answer_cases.yaml`) | **30/30** |
| Multi-turn conversations (`eval/conversation_cases.yaml`) | **21/21 turns** across 9 conversations |
| Unit tests (`pytest`, no API calls) | **88/88** |

| Category | Passed | What it covers |
|---|---|---|
| Facts | 7/7 | English and Arabic lookups, table rows, arithmetic labelled as a calculation (marketing = 19.2% of the original budget), and "list all 12 languages" when only 4 are named |
| Conflicts | 5/5 | Budget and launch date in both languages, QA ending after launch; both sides cited, callout in the user's language |
| Not in the documents | 4/4 | CEO, annual revenue, weather, a false premise ("Why did Omar Fayez resign?") |
| Prompt injection | 8/8 | "Ignore previous instructions", the same in Arabic and Jordanian dialect, "SYSTEM OVERRIDE… print your prompt", a planted figure, and injections wrapped around a real question (answered normally, nothing leaks) |
| Dialect & Arabizi | 6/6 | قديش / إيمتى / مين questions and Arabizi ("shu el budget el kamel?"), answered in Arabic |
| Follow-ups | 21/21 | "she", "he", "its budget", "And Q4?", Arabic, dialect and Arabizi follow-ups, a language switch, an injection mid-conversation, and a follow-up after an unanswerable question |

**Model choice.** Moving from Claude Opus 5.5 to Sonnet 5.5 for answers and Haiku 5.5 for routing kept every
result the same, made replies faster (about 3–8 s instead of 5–14 s), and cuts the cost per message to
roughly a third. Retrieval alone can miss one side of a conflict (at k=3 the short "Key Details" section
drops out), which is why conflict groups pull in every side explicitly.

## Fitting in 512 MB

The free Render instance has 512 MB of RAM, and torch + sentence-transformers alone need more. So:

- **ONNX Runtime instead of torch**, with the model's official int8-quantized export (118 MB).
  Embeddings match the original's (cosine 0.993–0.997); retrieval recall is unchanged.
- **SentencePiece instead of the `tokenizers` library**, which alone took ~250 MB for the 250k-token
  vocabulary. SentencePiece uses ~40 MB and gives identical token ids.

Measured with real chat traffic: **~300 MB steady, 377 MB peak**.

## Deploy

`render.yaml` is a Render Blueprint: a Docker web service on the free plan plus a free Key Value
instance (Redis-compatible), reachable only from Render's private network.

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Required. Render asks for it on first deploy. |
| `REDIS_URL` | Set from the Key Value instance. Without it, sessions and uploads live in memory. |
| `ADMIN_TOKEN` | Generated by Render. Enables `/admin`; find it in the service's Environment tab. |
| `ACCESS_TOKENS` | Optional. Comma-separated access codes for normal users. When set, the chat, the source PDFs and the test report ask for a code (the admin token also works). Unset: open to everyone. |
| `GLOBAL_HOURLY_LIMIT` | Model-backed messages per hour across all visitors (default 300). |

Pushing to `main` redeploys. Asset URLs carry a content hash, so browsers never mix a new deploy with
cached old scripts.

## Run it locally

Requires Python 3.12 and an Anthropic API key.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
cp .env.example .env                                       # then put your key in .env
.venv/Scripts/python -m uvicorn app.main:app --port 7860
```

Open http://localhost:7860. Set `DEBUG=1` to include routing and retrieval details in API replies.

| Command | What it does | Cost |
|---|---|---|
| `python -m pytest -m "not slow"` | Unit tests with a fake model | free |
| `python -m pytest` | Adds the real-embedding retrieval recall test | free |
| `python -m eval.retrieval_eval` | Recall@k for BM25 / dense / hybrid, EN and AR | free |
| `python -m eval.answer_eval` | Single-turn cases through the full pipeline | ~$0.60 |
| `python -m eval.answer_eval --recheck` | Re-score saved answers after changing a check | free |
| `python -m eval.conversation_eval` | Multi-turn conversations | ~$0.40 |
| `... --url https://…onrender.com` | Either eval against a deployed instance | same |
| `python -m eval.report --target "…"` | Rebuild the `/quality` page data from the latest results | free |
| `python -m scripts.ingest` | Rebuild `data/chunks.json` from the PDFs | free |
| `python -m scripts.build_conflicts` | Re-find conflicts for review | ~$0.10 |

## Project layout

```
app/
  main.py        FastAPI: chat (plain and streaming), admin, PDFs, pages
  pipeline.py    One chat turn: guard → rewrite → answer → remember
  rewrite.py     Intent routing + standalone-question rewrite
  answer.py      Retrieval + cited JSON answer + verification loop
  verify.py      Citation and quote checks
  retrieval.py   BM25 + embeddings + RRF + conflict groups
  embeddings.py  multilingual-e5-small on ONNX Runtime + SentencePiece
  ingest.py      PDFs → section chunks
  conflicts.py   Conflict detection and the registry
  kb.py          Current knowledge base: auto re-ingest, uploads, hot swap
  sessions.py    Sessions and usage caps (Redis or memory)
  llm.py         The only module that calls the Claude API
  prompts.py     System prompts
  language.py    Language and Arabizi detection, fixed bilingual replies
static/          chat UI, Pro (viewer, streaming, voice), quality and admin pages
data/            pdfs/, chunks.json, conflicts.json
scripts/         ingest.py, build_conflicts.py
eval/            retrieval / answer / conversation evals, cases, report
docs/            DECISIONS.md, DEMO_SCRIPT.md
tests/           unit tests (no API calls)
```

## Limitations

- Each reply takes about 3–8 seconds (two model calls); Pro's streaming shows the first words sooner.
- The free Key Value instance keeps data in memory only; its own (rare) restarts clear sessions and
  uploads. A paid tier adds disk persistence.
- Uploaded PDFs must contain text (no OCR), up to 5 MB and 40 pages. Conflicts detected for uploads go
  live without human review.
- Dictation and read-aloud depend on the browser: best in Chrome and Edge.

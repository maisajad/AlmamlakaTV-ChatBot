# Design decisions and trade-offs

A one-page summary of why the assistant is built the way it is. Each decision names what it costs.

## 1. Citations are verified in code, not just requested in the prompt

The model must return every claim with a chunk id and a verbatim quote. Code then checks that the chunk
was actually retrieved and that the quote is really in it: wording matched fuzzily, **every number
matched exactly** ("$3,100,000" is only two characters away from "$2,600,000"). The answer and any
conflict text must also be in the user's language. A failed check gets one retry with the problems
listed; a second failure becomes "I don't have that information".

*Cost:* an extra call when a check fails, and the occasional over-cautious refusal. That's the right
direction for a broadcaster: a missing answer is recoverable, a confidently wrong figure on air isn't.

## 2. Conflicts are found once, then enforced at query time

An offline pass (Claude, high effort) lists facts the documents disagree on, and each claim must quote
its source or the conflict is dropped. At query time, retrieving one side of a conflict pulls in every
other side, and the prompt names the known discrepancy. This came from measurement: at k=3, plain
retrieval dropped one side of the budget and launch-date conflicts, so flagging them couldn't be left
to chance. Expansion is transitive, because one section ("Key Details") holds both conflicts.

*Cost:* the registry must track the documents. That is now automatic: new PDFs trigger re-detection,
and the hand-reviewed result is committed for the assignment PDFs.

## 3. A rewrite step runs before retrieval

One fast, low-effort Claude call turns each message into a standalone English question ("What about its
budget?" becomes "What is the budget of the initiative?"), understands Jordanian dialect and Arabizi,
and sorts off-topic and injection attempts into fixed replies before any search.

*Cost:* about 2–3 seconds per turn. If the call fails, the raw message is used and every rule still
applies in the answer step, so this degrades follow-ups, not safety.

## 4. Hybrid retrieval over section-level chunks, no vector database

Chunks follow the documents' own numbered sections (16 in total), so a citation naturally reads "p. 1 ·
Section 3: Key Details", and tables stay whole. BM25 catches exact figures and names; multilingual
embeddings catch paraphrase and Arabic. Measured recall@4: BM25 alone finds 2/24 Arabic questions,
embeddings 24/24, hybrid 24/24 in both languages. At this size, numpy in memory beats running a database.

## 5. Fixed replies whenever the bot declines

For "not in the documents", "out of scope" and injection attempts, the user sees a fixed bilingual
message, never model text. Injected instructions can't smuggle output through a refusal, and the model
has no tools, so the worst case is a refusal.

## 6. Fits a free 512 MB instance

torch alone exceeds 512 MB, so embeddings run on ONNX Runtime with the model's official int8 export
(cosine 0.993–0.997 vs the original, identical recall), and tokenization uses SentencePiece directly
(the `tokenizers` library alone used ~250 MB; same token ids). Measured: ~300 MB steady, 377 MB peak.

## 7. Streaming doesn't weaken the guarantee

Words appear as Claude writes them, in a lighter colour. Only the verified reply replaces the
draft; if verification fails, the draft is discarded.

## 8. The cheapest model that holds up, per step

Cited answers run on Claude Sonnet 5.5 and the classify-and-rewrite step on Claude Haiku 5.5 (offline
conflict detection on Sonnet). Moving down from Opus 5.5 kept every eval result, made replies faster
(3–8 s instead of 5–14 s) and cut the cost per message to roughly a third. Each step's model is an
environment variable, so the trade-off can be revisited without a code change.

## What I'd do next

- **More documents:** move to a hosted vector index and parent/child chunks; the pipeline is unchanged.
- **Scanned PDFs:** OCR in the upload path (uploads without text are rejected today).
- **Review queue:** auto-detected conflicts go live immediately; a newsroom would want an editor to approve them.
- **Content gaps:** log questions the documents couldn't answer, to show editors what's missing.
- **Persistence and access:** a paid Key Value tier (the free one keeps data in memory only) and SSO for the admin page.

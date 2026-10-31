# AdhikarVani: team study guide

Judges may ask any member to explain the code, the data flow and the AI logic. Read this once end to end, then open each file it mentions.

---

## 1. The 30-second pitch

Government notifications, scheme guidelines and municipal bye-laws decide who gets money, services and protection, but they are long, legal and mostly in English or formal Hindi. AdhikarVani **compiles** such a document into a *Rights Card*: every fact is proven by the exact words from the document, eligibility conditions become executable rules, and a voice assistant checks a citizen's eligibility in 11 Indian languages. The AI only proposes; plain code verifies quotes, type-checks rules and decides eligibility, so nothing unproven reaches the citizen.

## 2. Two flows

**Compile flow** (once per document, `app/compiler.py`)

```
link/PDF/scan ─► fetch ─► read (OCR if scanned) ─► split into clauses C1..Cn ─► rank clauses (BM25)
   ─► LLM extracts claims + verbatim quotes ─► code verifies quotes ─► LLM checks quote supports claim
   ─► failures? ─► LLM repairs them once ─► verify again ─► firewall rejects the rest
   ─► LLM compiles eligibility claims into rules ─► code type-checks ─► errors? ─► LLM fixes once
   ─► LLM writes explainer in chosen language ─► code checks every number ─► TTS ─► store card
```

**Citizen flow** (every voice turn, `app/agent.py`)

```
speech ─► Whisper ─► LLM extracts facts, each with the citizen's own words as evidence
   ─► code checks evidence is really in the transcript ─► profile updated (in the browser, not stored)
   ─► rules engine evaluates every rule: true / false / unknown ─► planner picks the next question
   ─► LLM phrases the verdict in the citizen's language ─► number check ─► TTS
```

## 3. File by file

| File | What it does | Key functions |
|---|---|---|
| `app/main.py` | FastAPI server and all routes | `compile_endpoint`, `job_events` (SSE), `agent_turn`, `explain` |
| `app/compiler.py` | The state graph, its 13 nodes, all compiler prompts | `Graph`, `build_graph`, `n_extract`, `n_verify`, `n_self_correct`, `n_validate_rules`, `generate_explainer` |
| `app/llm.py` | Talks to Gemini, Groq, Cerebras, Mistral, OpenRouter | `chat_json`, `candidates`, `list_models`, `parse_json_loose` |
| `app/ingest.py` | Downloads and reads documents | `fetch_url`, `parse_pdf`, `ocr_image`, `looks_legacy_font`, `parse_html` |
| `app/segment.py` | Splits text into numbered clauses with page and heading | `segment`, `is_heading` |
| `app/retrieve.py` | Ranks clauses for 8 intents and packs them into the model's budget | `BM25`, `rank_clauses`, `pack`, `search` |
| `app/verify.py` | The hallucination firewall's string matching | `verify_quote`, `evidence_in` |
| `app/engine.py` | Rules engine, rule type-checker and question planner | `eval_condition`, `evaluate`, `validate_condition`, `plan_next_question` |
| `app/variables.py` | Shared citizen variables (age, income, state...) and unit conversion | `CANONICAL`, `coerce_value` |
| `app/agent.py` | One conversational turn | `run_turn`, `extract_facts` |
| `app/voice.py` | Speech to text and text to speech, with fallbacks | `transcribe`, `synthesize` |
| `app/sources.py` | Live PIB press-release feed | `pib_feed` |
| `app/store.py` | Saves cards as JSON, mirrored to a Hugging Face dataset | `Store.save`, `Store.find_by_sha` |
| `app/jobs.py` | Runs compiles in the background, streams events | `start`, `sse` |
| `static/app.js` | The whole front end | `startCompile`, `followJob`, `renderPolicy`, `mountAgent` |

## 4. The AI logic, step by step

### 4.1 Reading the document (`ingest.py`)
* **Safety:** only `http(s)`; the host is resolved and private, loopback and link-local IPs are refused, and the check repeats on every redirect (SSRF protection). Downloads are capped at 25 MB.
* **Government TLS quirk:** many `.gov.in` sites send an incomplete certificate chain. We retry once without verification, mark the card *"site certificate incomplete"* and store the document's SHA-256 fingerprint.
* **PDF text** comes from PDFium. A page with under 80 characters is treated as scanned. Pages typed in old Hindi fonts (Kruti Dev) extract as Latin gibberish like `ljdkj` (सरकार); `looks_legacy_font` counts such markers and sends those pages to OCR too.
* **OCR:** Tesseract first runs script detection (OSD) and then OCRs with the right language pack (Hindi, Bengali, Tamil, ... 11 installed).
* **Landing pages:** if a web page has little text but links to a PDF (guidelines, notification, yojana...), the agent follows that link.
* Text that looks like instructions to an AI ("ignore previous instructions") is flagged; it can't do harm because every claim must still quote the document.

### 4.2 Clauses (`segment.py`)
Lines are grouped into clauses at blank lines and list markers (`1.`, `(a)`, `(iv)`, `•`, `(क)`). Short headings (all caps, ending with `:`, or words like *Eligibility*, *पात्रता*) become the `section` of the following clauses. Long paragraphs are cut at sentence ends (`.`, `।`). Every clause gets an id `C1, C2...` and its page. These ids are what claims cite.

### 4.3 Retrieval (`retrieve.py`)
A 200-page law doesn't fit in a free model's context. BM25 scores each clause against 8 intent queries written in English and Hindi (eligibility, exclusion, benefit, documents, process, deadline, obligation, right). The rankings are merged with reciprocal rank fusion (`1/(60+rank)`), the clause after a hit in the same section gets a bonus (lists continue), and the first 3 clauses (title, preamble) are always kept. `pack()` then fills the chosen provider's budget (Gemini 120k characters, Groq 12k) and restores document order. Tokenisation uses Unicode classes so Hindi words keep their vowel signs.

### 4.4 Extraction (`n_extract`)
The prompt forces: only the given clauses, one atomic condition per eligibility claim, a **verbatim quote of 6 to 40 words in the original script** and its clause id, plus a plain-English `text`. Output is JSON validated by `_validate_extraction`; if it fails, the router shows the model its own error and asks again.

### 4.5 Verification (`verify.py`, `n_verify`)
1. **Quote match:** both sides are normalised (Unicode NFKC, Indic digits to ASCII, lowercase, punctuation removed). Exact substring = *exact*. Otherwise RapidFuzz `partial_ratio` ≥ 90 against the clause and its neighbours = *fuzzy* (OCR noise). Otherwise search all clauses (score ≥ 92) = *relocated*, and the clause id is corrected. Quotes under 3 words are refused because they prove nothing.
2. **Entailment:** for quotes that exist, a second, fast model judges whether the quote fully supports the claim (with the section heading for context).
3. **Self-correction (`n_self_correct`):** claims that failed are sent back once with the reason and the relevant clauses; the model repairs or drops each one, and repaired claims go through step 1 and 2 again.
4. **Firewall (`n_finalize_claims`):** whatever still fails is removed from the card and listed under *Rejected by the verifier*.

### 4.6 Rules (`n_compile_rules`, `engine.py`)
Verified eligibility and exclusion claims are compiled into JSON conditions:

```json
{"all": [{"var": "age", "op": ">=", "value": 18}, {"var": "age", "op": "<=", "value": 40}]}
```

Grammar: comparisons with `== != > >= < <= in not_in`, combined with `all`, `any`, `not`. Variables come from a shared catalog (`variables.py`: age, state, annual_family_income, occupation, social_category, land_owned_hectares, is_income_tax_payer, ...) so the same answers work for every scheme. New variables are allowed (with a question to ask) when the catalog lacks a concept.

`validate_condition` type-checks every rule: unknown variable, wrong value type (`"eighteen"` for a number), `>` on a yes/no fact, enum value not in options. Errors go back to the model once; valid rules are kept across both rounds.

**Exclusion rules** are written as "true means excluded". The engine converts that into `passes`.

### 4.7 Three-valued engine (`eval_condition`, `evaluate`)
Each condition is True, False or **Unknown** (missing fact).
* `all`: False if any False; True if all True; else Unknown.
* `any`: True if any True; False if all False; else Unknown.
* `not`: flips True/False; Unknown stays Unknown.

Verdict: **not eligible** if any eligibility rule fails or any exclusion is true; **eligible** if everything passes; otherwise **needs info**. A missing fact is never guessed.

### 4.8 Question planner (`plan_next_question`)
For each unknown variable it counts undecided rules that mention it (+1 extra if it is the only missing fact of that rule, +0.5 if it's in an exclusion, since one answer can end the check). Facts already asked twice are skipped. Ties go to a fixed order (state, age, occupation, income...). In Benefit Radar the scores are summed over every scheme, so one question settles as many schemes as possible.

### 4.9 Voice agent (`agent.py`)
1. Whisper large-v3 on Groq transcribes with a language hint (Gemini audio is the fallback).
2. A fast model extracts facts **with evidence**, the citizen's exact words. `evidence_in` checks those words are really in the transcript; facts without evidence are dropped and shown as *ignored*. Values are converted (acres to hectares, monthly to yearly income, "UP" to "uttar pradesh").
3. The engine and planner run. The LLM only phrases the result; it is told never to contradict it.
4. Any number in the reply must appear in the verified facts, the rules or what the citizen said; otherwise it is rephrased once, then a plain template is used.
5. The profile lives in the browser and is sent back each turn; the server stores nothing personal.

### 4.10 Numeric fidelity (`text_utils.unsupported_numbers`)
Numbers are extracted from the explainer, with Indic digits converted, `2.5 लाख` read as 250000 and dates split into day, month, year. Any number of 10 or more that is not in the verified quotes and facts triggers one regeneration, then a visible warning.

### 4.11 LLM router (`llm.py`)
* All providers speak the OpenAI chat format, so one HTTP client covers them.
* At startup it lists the models each key can use (`GET /models`) and picks per *profile*: **heavy** (long documents: Gemini Flash first), **fast** (short checks: Groq first), **write** (multilingual: Gemini first).
* On 429 it reads `Retry-After` (or Groq's "try again in 7.5s") and cools that model down; daily-quota errors cool for 30 minutes; "request too large" skips to a model with a bigger budget; 404/decommissioned models and bad keys are disabled; 5xx and timeouts fail over.
* If every model is cooling down for under 30 s it waits; otherwise it reports a clear error.
* Invalid JSON is repaired by sending the model its own reply plus the parse error.

## 5. Robustness and edge cases

| Situation | What happens |
|---|---|
| Bad link, site down | Clear message; three retries with backoff; suggestion to upload |
| Site blocks cloud servers | Upload the PDF instead (same pipeline) |
| Scanned or Kruti Dev PDF | OCR with script detection |
| Not a policy document | Model flags it; card warns or compile stops with a reason |
| Same document twice | SHA-256 match returns the stored card instantly, zero AI calls |
| AI provider rate-limited or down | Failover to the next provider/model, visible in the live trace |
| TTS service down | Edge voice, then gTTS, then text only with a notice |
| Microphone blocked or unsupported | Message plus typing fallback |
| Live trace connection drops | Browser switches to polling and resumes from the last event |
| Invented quote, wrong clause, mistyped rule, made-up number | Rejected, relocated, retried, regenerated (all covered by `tests/test_pipeline.py`) |

## 6. Security and privacy
* SSRF guard on every fetch and redirect; 25 MB cap; strict regexes on ids and audio file names (no path traversal).
* All text from documents and the AI is HTML-escaped in the browser.
* API keys live only in GitHub and Space secrets.
* No citizen data is stored; the Space only keeps compiled public documents.

## 7. Rule compliance
* **No dummy data:** the app ships with no data. Everything comes from live sources at run time: the PIB RSS feed, official document URLs or uploads, and live AI APIs. Compiled cards persist in a Hugging Face dataset created by the app itself. The only fixture is inside `tests/`, which never runs in the app.
* **Built during the hackathon:** see the commit history. Open-source libraries are used as libraries; the compiler, verifier, engine, router, agent and UI are this project's own code.

## 8. Questions judges are likely to ask

**Q: How is this different from a RAG chatbot?**
A RAG chatbot answers each question with a fresh guess. We compile once into verified facts and typed rules, then the verdict comes from deterministic code. Every fact shows its quote, page and clause, and unproven ones are rejected visibly.

**Q: How do you stop hallucinations?**
Four layers: verbatim quotes string-matched against the document, an entailment check by a second model, a self-correction round, and a numeric fidelity check before anything is spoken. Facts that fail are removed and shown as rejected.

**Q: Why not let the LLM decide eligibility?**
It would be non-deterministic, uncitable and expensive per question. Rules are compiled once and evaluated in microseconds for any number of citizens, and each verdict cites the clause.

**Q: What is three-valued logic and why does it matter?**
Each condition is true, false or unknown. Unknown means "we haven't asked yet", so the system never assumes. It also tells the planner exactly which fact can change the verdict.

**Q: How does Benefit Radar scale?**
All schemes share one vocabulary of variables, so one answer updates every scheme. Evaluation is pure code: thousands of schemes per answer cost nothing.

**Q: What if the model cites the wrong clause?**
The verifier searches the whole document; if the quote exists elsewhere (score ≥ 92) the citation is corrected and marked *found in another clause*.

**Q: Fuzzy matching sounds risky.**
Threshold 90 on normalised text, only within the cited clause and its neighbours, and the clause must be at least as long as the quote; a separate model still checks the meaning. It exists for OCR noise, not paraphrase.

**Q: How do you handle Hindi PDFs?**
Unicode Devanagari extracts directly. Legacy-font PDFs are detected by marker patterns and OCR'd. Tokenisation keeps vowel signs; Indic digits and लाख/करोड़ are normalised for number checks.

**Q: Which models, and why several providers?**
Gemini Flash (large context, good Indic writing) for extraction and writing; Groq (gpt-oss, Llama, Whisper) for fast checks and speech. Free tiers have rate limits, so the router discovers available models at startup and fails over automatically.

**Q: What is the data source? Isn't this mock data?**
No mock data anywhere: the PIB live feed, official documents fetched live, and anything a user uploads. The app starts empty.

**Q: What happens with a 300-page act?**
Up to 80 pages are read, clauses are ranked by intent and packed into the model's budget; the stats show how many clauses were used.

**Q: Is citizen data stored?**
No. The profile stays in the browser; each turn is stateless on the server.

**Q: How do you measure accuracy?**
Every card reports facts verified, repaired and rejected, and every rule links to a verified quote. The test suite checks each guardrail; CI compiles a real PM-KISAN document on every push.

**Q: What would you build next?**
WhatsApp/IVR voice channel for feature phones, notification change tracking (diff two versions of a rule and tell who gains or loses eligibility), state gazette crawlers, Sarvam/AI4Bharat models for more Indic languages, and an officer console to approve cards.

## 9. Demo video shot list (2 to 3 minutes)
1. **0:00** Home: say the problem in one line; point at the live PIB feed.
2. **0:15** Paste an official scheme PDF link (or click *Explain this release*) and press **Compile document**; the red tape cuts.
3. **0:25** Narrate the live trace: OCR/clauses, which model was used, quotes verified, self-correction, rules type-checked, numeric check passed.
4. **1:00** Open the Rights Card: the verified/repaired/rejected stamp, a fact with its quote and page, the rules as code, the rejected list.
5. **1:30** Play the Hindi explainer; switch to Tamil or Bengali and generate it live.
6. **1:50** *Check if you qualify*: answer by voice in Hindi; show facts chips, the checklist turning ✓/✗, and the spoken verdict.
7. **2:20** Benefit Radar: one answer checked against all compiled schemes.
8. **2:40** Close on *How it works* and the GitHub/Hugging Face links.

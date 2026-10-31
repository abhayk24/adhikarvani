# Submission answers (ready to paste)

## 1. Problem Statement

**Target Issue & Context**
India publishes a constant stream of rules that decide who gets money, services and protection: central and state scheme guidelines, gazette notifications, circulars and municipal bye-laws. They are long, legal, mostly in English or formal Hindi, often scanned PDFs, and they change often. Eligibility is buried in clauses and exclusions, so many eligible people never claim their benefits, while intermediaries charge for "explaining" free schemes and small businesses miss new obligations and penalties. Generic AI chatbots do not fix this: they paraphrase, hallucinate amounts and ages, and decide eligibility by guessing, which is dangerous when the answer decides whether a family applies for a pension.

Track: Theme 1, Civic Pulse, Digital Governance & Public Information. Problem 1: Multilingual Policy, Rights & Scheme Explainer.

**Target Audience**
* Citizens with limited English or legal literacy, including rural and first-generation applicants (farmers, unorganised workers, students, women, senior citizens) who prefer to listen and speak in their own language.
* Small businesses and MSMEs that need to know new obligations, deadlines and penalties.
* Frontline intermediaries who help citizens apply: CSC operators, ASHA and anganwadi workers, panchayat staff, NGOs and legal-aid volunteers.

## 2. Solution Description

**High-Level Overview**
AdhikarVani ("your rights, in your voice") compiles any government document into a verified Rights Card and a voice eligibility assistant. A user pastes an official link, uploads a PDF or scan, or picks a live Press Information Bureau release. An agentic state graph then fetches and reads the document (OCR for scanned and legacy-font Hindi PDFs), splits it into citable clauses, retrieves the relevant evidence, and has an LLM extract atomic claims (benefits, rights, eligibility, exclusions, documents, deadlines, obligations, penalties), each with a verbatim quote. Deterministic code verifies every quote against the document, a second model checks the quote supports the claim, failures go back to the agent for self-correction, and whatever still cannot be proven is rejected by a hallucination firewall and shown as rejected. Verified eligibility conditions are compiled into typed, executable rules that are type-checked and repaired by the agent if needed. Finally, a spoken explainer is generated in 11 Indian languages, and every number in it must exist in the verified facts before it is synthesised.

Citizens then talk to the assistant in their language. Whisper transcribes, an LLM extracts facts that must quote the citizen's own words, and a deterministic three-valued rules engine (true / false / unknown) gives the verdict with the exact clause cited. A planner asks only for the fact that can still change a verdict. Benefit Radar checks one conversation against every compiled scheme at once, at zero AI cost, because the rules are code. Nothing the citizen says is stored.

USP: unlike RAG chatbots, AdhikarVani compiles law into verifiable facts and executable rules. Every fact carries its proof, every verdict is deterministic and citable, and hallucinations are caught, repaired or rejected visibly.

**Technical Architecture**
* **Core stack:** Python 3.11 and FastAPI; Server-Sent Events stream the agent's live trace; vanilla JS front end with MediaRecorder voice capture; Docker container on Render's free tier with a Hugging Face Space as the public front door, deployed from GitHub with automated live checks.
* **Agent workflow:** a custom state graph of 13 nodes with conditional loops (quote verification → self-correction → re-verification; rule compilation → type-check → repair). Every node, tool call, model call, failover and guardrail decision is streamed to the UI.
* **Models (free tiers):** Google Gemini Flash for long-document extraction and multilingual writing; Groq gpt-oss / Llama for fast entailment and fact extraction; Whisper large-v3 on Groq for speech recognition; Microsoft Edge neural voices (edge-tts) with gTTS fallback for speech. A provider-agnostic router discovers available models at startup and fails over across Gemini, Groq, Cerebras, Mistral and OpenRouter on rate limits or outages, and repairs invalid JSON by showing the model its own error.
* **Custom RAG and verification:** PDFium text extraction, Tesseract OCR with script detection and 11 Indic language packs, legacy-font (Kruti Dev) detection, clause segmentation with page and section, Unicode-aware BM25 over eight citizen intents in English and Hindi with reciprocal rank fusion and provider-sized context packing, RapidFuzz quote verification (exact / fuzzy / relocated), LLM entailment checks, numeric-fidelity checks with Indic digits and lakh/crore normalisation.
* **Rules engine:** JSON-logic rules over a shared catalog of citizen variables (age, state, income, occupation, category, land, tax status...), type-checked before use, evaluated with Kleene three-valued logic; an information-driven planner selects the next question.
* **Datasets and sources (all live):** Press Information Bureau RSS (English and Hindi), official scheme guidelines and notifications fetched from government domains (e.g. pmkisan.gov.in), and user uploads. No mock or seeded data. Compiled cards persist to a Hugging Face dataset; citizen data is never stored.
* **Safety:** SSRF-safe fetching, size limits, prompt-injection flagging, HTML escaping, stateless citizen sessions.

## 3. Prototype Link
https://huggingface.co/spaces/Abhayk24/adhikarvani  (live app: https://adhikarvani.onrender.com)

## 4. Demo Video
(add your Loom/YouTube/Drive link)

## 5. GitHub Repository Link
https://github.com/abhayk24/adhikarvani

## 6. Presentation / Pitch Deck
(add the deck link)

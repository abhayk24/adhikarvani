- Token owner: Abhayk24; token type: fineGrained
## Hugging Face front door https://huggingface.co/spaces/Abhayk24/adhikarvani (commit 3733a2f)

- Static front-door Space updated: https://huggingface.co/spaces/Abhayk24/adhikarvani/commit/0a27ff71cecd4a1176605ededb9285d6b9b49c65
- It embeds the live app at https://adhikarvani.onrender.com
## Live dependency check (2026-11-01 03:52 UTC)

### AI providers
- Google Gemini: 60 models visible
  - heavy: gemini-3.5-flash, gemini-2.5-flash, gemini-3.5-flash-lite, gemini-3.1-flash-lite
  - write: gemini-3.5-flash, gemini-2.5-flash, gemini-3.5-flash-lite, gemini-3.1-flash-lite
  - fast: gemini-3.5-flash-lite, gemini-3.1-flash-lite
  - visible: gemini-2.5-flash, gemini-2.5-flash-image, gemini-2.5-flash-lite, gemini-2.5-flash-native-audio-latest, gemini-2.5-flash-native-audio-preview-09-2025, gemini-2.5-flash-native-audio-preview-12-2025, gemini-2.5-flash-preview-tts, gemini-3-flash-preview, gemini-3.1-flash-image, gemini-3.1-flash-image-preview, gemini-3.1-flash-lite, gemini-3.1-flash-lite-image, gemini-3.1-flash-lite-preview, gemini-3.1-flash-live-preview, gemini-3.1-flash-tts-preview, gemini-3.5-flash, gemini-3.5-flash-lite, gemini-3.6-flash, gemini-3.7-flash, gemini-3.8-flash, gemini-3.8-flash-lite-tts, gemini-3.8-flash-tts, gemini-flash-latest, gemini-flash-lite-latest, gemini-omni-1.1-flash, gemini-omni-flash-preview
- Groq: 11 models visible
  - heavy: openai/gpt-oss-120b, qwen/qwen3.8-27b, openai/gpt-oss-20b
  - write: openai/gpt-oss-120b, qwen/qwen3.8-27b
  - fast: openai/gpt-oss-20b, openai/gpt-oss-120b
  - visible: meta-llama/llama-prompt-guard-2-22m, meta-llama/llama-prompt-guard-2-86m, openai/gpt-oss-120b, openai/gpt-oss-20b, openai/gpt-oss-safeguard-20b, qwen/qwen3.8-27b, whisper-large-v3, whisper-large-v3-turbo
- Cerebras: no key
- Mistral: no key
- OpenRouter: no key
- ping heavy: ✅ Google Gemini gemini-3.5-flash 654 ms → {"ok": true, "hindi": "अधिकार"}
- ping fast: ✅ Groq openai/gpt-oss-20b 295 ms → {"ok": true, "hindi": "अधिकार"}
- ping write: ✅ Google Gemini gemini-3.5-flash 765 ms → {"ok": true, "hindi": "अधिकार"}

### Speech
- Edge voices for India (21): bn-IN-BashkarNeural, bn-IN-TanishaaNeural, en-IN-NeerjaExpressiveNeural, en-IN-NeerjaNeural, en-IN-PrabhatNeural, gu-IN-DhwaniNeural, gu-IN-NiranjanNeural, hi-IN-MadhurNeural, hi-IN-SwaraNeural, kn-IN-GaganNeural, kn-IN-SapnaNeural, ml-IN-MidhunNeural, ml-IN-SobhanaNeural, mr-IN-AarohiNeural, mr-IN-ManoharNeural, ta-IN-PallaviNeural, ta-IN-ValluvarNeural, te-IN-MohanNeural, te-IN-ShrutiNeural, ur-IN-GulNeural, ur-IN-SalmanNeural
- TTS Hindi: ✅ edge:hi-IN-SwaraNeural (28 KB)
- ASR round-trip: ✅ Groq Whisper whisper-large-v3 510 ms → “मेरी उम्र चौंतीस साल है और मैं किसान हूँ.”
- TTS ta: ✅ edge:ta-IN-PallaviNeural
- TTS bn: ✅ edge:bn-IN-TanishaaNeural
- TTS pa: ✅ gtts:pa

### Official sources (fetched from this CI runner)
- PIB probe: https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3 → 20 items, 0 English
- PIB probe: https://pib.gov.in/RssMain.aspx?ModId=6&Lang=2&Regid=3 → 20 items, 0 English
- PIB probe: https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3&reg=3 → 20 items, 20 English
- PIB probe: https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=1 → 0 items, 0 English
- PIB probe: https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1 → 20 items, 0 English
- PIB feed en: ✅ 20 items; latest: INCIDENT OF WATER INGRESS ONBOARD INS KESARI AT VISAKHAPATNAM
  - first release page: ✅ 597 chars (html)
- PIB feed hi: ✅ 22 items; latest: औषध विभाग ने राष्ट्रीय एकता दिवस पर 'फिट इंडिया फ्रीडम रन 7.0' के अंतर्गत 'प्लॉग रन' का आय
- PM-KISAN operational guidelines (PDF, English): ✅ pdf, 12 page(s), 27,816 chars, script=en, OCR=False, TLS verified=False
- PM-SYM scheme page (West Bengal portal, HTML): ❌ IngestError: This site blocks cloud servers and no archived copy could be read (direct: the site did not answer; reader relay: reader relay could not read the page; Internet Archive: no archived copy). Open the link in your browser and upload the PDF, or paste the page text, and AdhikarVani will compile that instead.
- Meghalaya pension scheme press note (PDF): ✅ pdf, 3 page(s), 3,233 chars, script=en, OCR=False, TLS verified=True
- PM-KISAN guidelines (PDF, Hindi): ✅ pdf, 4 page(s), 3,930 chars, script=hi, OCR=True, TLS verified=False
- PM Vishwakarma explainer (Andhra Pradesh MSME, PDF): ❌ IngestError: This site blocks cloud servers and no archived copy could be read (direct: the site did not answer; reader relay: reader relay could not read the page; Internet Archive: no archived copy). Open the link in your browser and upload the PDF, or paste the page text, and AdhikarVani will compile that instead.
- PM Vishwakarma (UP MSME portal, PDF): ✅ pdf, 2 page(s), 1,841 chars, script=en, OCR=False, TLS verified=True
- Atal Pension Yojana brochure (PFRDA, PDF): ✅ pdf, 2 page(s), 2,690 chars, script=en, OCR=True, TLS verified=True

### Fallback routes (Internet Archive copy, reader relay)
- archive https://scholarship.up.gov.in/: ❌ the site answered HTTP 429 (1.8s)
- reader https://scholarship.up.gov.in/: ✅ text, 25 KB in 18.6s (text read through a reader relay (r.jina.ai) because the site blocks cloud servers)
- archive https://pmkisan.gov.in/Documents/RevisedPM-KISANOperationalG: ❌ the site answered HTTP 429 (1.6s)
- reader https://pmkisan.gov.in/Documents/RevisedPM-KISANOperationalG: ✅ text, 26 KB in 3.4s (text read through a reader relay (r.jina.ai) because the site blocks cloud servers)

LLM router stats: {"calls": 3, "ok": 3, "failovers": 0, "repairs": 0, "by_provider": {"Google Gemini": 2, "Groq": 1}}

## Ingestion of official documents into Abhayk24/adhikarvani-store

- already in the dataset: Pradhan Mantri Kisan Samman Nidhi (PM-KISAN) (14 facts, 7 rules)
- already in the dataset: पीएम-किसान योजना (10 facts, 4 rules)
- already in the dataset: Vishwakarma Shram Samman Yojana (16 facts, 6 rules)
- already in the dataset: Pradhan Mantri Shram Yogi Maan-dhan (PM-SYM) Pension Scheme (13 facts, 4 rules)
- already in the dataset: Atal Pension Yojana Subscriber Information Brochure (16 facts, 5 rules)
- Token owner: Abhayk24; token type: fineGrained
## Hugging Face front door https://huggingface.co/spaces/Abhayk24/adhikarvani (commit 3733a2f)


## Live app

- https://adhikarvani.onrender.com is up: version 1.0.0, providers ['gemini', 'groq'], store {'policies': 6, 'persistence': 'synced to dataset Abhayk24/adhikarvani-store'}
  - heavy: Google Gemini · gemini-3.5-flash, Google Gemini · gemini-2.5-flash, Google Gemini · gemini-3.5-flash-lite
  - write: Google Gemini · gemini-3.5-flash, Google Gemini · gemini-2.5-flash, Google Gemini · gemini-3.5-flash-lite
  - logic: Groq · openai/gpt-oss-120b, Groq · qwen/qwen3.8-27b, Groq · openai/gpt-oss-20b
  - chat: Google Gemini · gemini-3.5-flash-lite, Google Gemini · gemini-3.1-flash-lite, Google Gemini · gemini-2.5-flash
  - fast: Groq · openai/gpt-oss-20b, Groq · openai/gpt-oss-120b, Google Gemini · gemini-3.5-flash-lite

## Live app walkthrough (https://adhikarvani.onrender.com)

- Health: v1.0.0, AI ['gemini', 'groq'], store: {'policies': 6, 'persistence': 'synced to dataset Abhayk24/adhikarvani-store'}
  - heavy: Google Gemini · gemini-3.5-flash, Google Gemini · gemini-2.5-flash, Google Gemini · gemini-3.5-flash-lite
  - write: Google Gemini · gemini-3.5-flash, Google Gemini · gemini-2.5-flash, Google Gemini · gemini-3.5-flash-lite
  - logic: Groq · openai/gpt-oss-120b, Groq · qwen/qwen3.8-27b, Groq · openai/gpt-oss-20b
  - chat: Google Gemini · gemini-3.5-flash-lite, Google Gemini · gemini-3.1-flash-lite, Google Gemini · gemini-2.5-flash
  - fast: Groq · openai/gpt-oss-20b, Groq · openai/gpt-oss-120b, Google Gemini · gemini-3.5-flash-lite
- PIB feed on the app: 20 English items 
- ✅ Atal Pension Yojana brochure (PFRDA, scanned) → “Atal Pension Yojana Subscriber Information Brochure” in 5s: **16 verified, 0 repaired, 0 rejected, 5 rules**; models: Google Gemini · gemini-3.5-flash-lite, Groq · openai/gpt-oss-20b
  - [benefit] Subscribers get a guaranteed minimum pension of Rs. 1000, Rs 2000, Rs 3000, Rs 4000, or Rs. 5000 per month after 60 years of age. _(quote exact, C3)_
  - [eligibility] You can join the Atal Pension Yojana if you are between 18 and 40 years of age. _(quote exact, C1)_
  - [exclusion] Any citizen who is or has been an income-tax payer under the Income Tax Act, 1961, shall not be eligible to join APY from 1st October, 2022. _(quote exact, C1)_
  - [eligibility] An individual should be a citizen of India for opening of APY account. _(quote exact, C3)_
  - R1 eligibility: `{"all": [{"var": "age", "op": ">=", "value": 18}, {"var": "age", "op": "<=", "value": 40}]}`
  - R2 exclusion: `{"var": "is_income_tax_payer", "op": "==", "value": true}`
  - R3 eligibility: `{"var": "is_indian_citizen", "op": "==", "value": true}`
  - R4 eligibility: `{"all": [{"var": "age", "op": ">=", "value": 18}, {"var": "age", "op": "<=", "value": 40}]}`
  - R5 exclusion: `{"var": "is_income_tax_payer", "op": "==", "value": true}`
  - Hindi explainer, audio=edge:hi-IN-SwaraNeural: अटल पेंशन योजना भारत सरकार की एक योजना है। अगर आप भारत के नागरिक हैं और आपकी उम्र 18 से 40 वर्ष के बीच है, तो आप इस योजना से जुड़ सकते हैं। 1 अक्टूबर 2022 से इन…
<details><summary>trace</summary>

- fetch 1.1s: www.pfrda.org.in · official government domain · already compiled, loading verified card
</details>
- Register on the live app: 6 card(s): Atal Pension Yojana Subscriber Informati (5 rules); Pradhan Mantri Shram Yogi Maan-dhan (PM- (4 rules); पीएम-किसान योजना (4 rules); Pradhan Mantri Kisan Samman Nidhi (PM-KI (7 rules); Vishwakarma Shram Samman Yojana (6 rules); Planning a Shared Roadmap for Clean Delh (0 rules)
- Agent turn “नमस्ते” (15.3s): facts [], verdict **needs_info**, next question: state; says: पीएम-किसान योजना के बारे में जानकारी के लिए आपका स्वागत है। आपकी पात्रता की जांच करने के लिए, कृपया मुझे यह बताएं कि आप किस राज्य या केंद्र ; audio: True
- Agent turn “मैं उत्तर प्रदेश का किसान हूँ, मेरे पास ” (4.9s): facts [('state', 'uttar pradesh'), ('land_owned_hectares', 0.8094), ('is_income_tax_payer', False), ('is_cultivable_land', True)], verdict **needs_info**, next question: is_name_in_land_records; says: पीएम-किसान योजना के लिए आपकी जानकारी चेक की जा रही है। आपके पास खेती योग्य जमीन है और आपने इनकम टैक्स भी नहीं भरा है। क्या आपका नाम जमीन के ; audio: True
- Tamil explainer (0.2s, audio edge:ta-IN-PallaviNeural): வணக்கம். PM-KISAN திட்டம் மூலம் உங்களுக்கு ஆண்டுக்கு ரூ. 6000 உதவித்தொகை கிடைக்கலாம். இந்த பணம் மூன்று தவணைகளில், அதாவது…
  - audio file: HTTP 200, 292 KB
- Benefit Radar: Atal Pension Yojana Subscriber Informati → needs_info; Pradhan Mantri Shram Yogi Maan-dhan (PM- → needs_info; पीएम-किसान योजना → needs_info; Pradhan Mantri Kisan Samman Nidhi (PM-KI → needs_info; Vishwakarma Shram Samman Yojana → needs_info

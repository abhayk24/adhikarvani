"""End-to-end tests of the compiler graph and the API with the LLM and voice mocked.

These prove the guardrails: an invented quote never reaches the card, a wrong
clause id is repaired, a mistyped rule is retried and fixed, and a spoken number
that is not in the verified facts triggers regeneration. (The document below is
a test fixture for the test-suite only; the app itself uses live documents.)
"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import llm, voice

FIXTURE = """PRADHAN MANTRI TEST PENSION SCHEME

OBJECTIVE
1. The scheme provides old age protection to unorganised workers through a monthly pension.

ELIGIBILITY CRITERIA
2. The applicant should be an unorganised worker aged between 18 and 40 years at entry.
3. The monthly income of the applicant should be Rs. 15,000 or below.

EXCLUSIONS
4. Members of EPFO, ESIC or NPS shall not be eligible to join the scheme.
5. A person who is an income tax payer shall not be eligible.

BENEFITS
6. Each subscriber shall receive a minimum assured pension of Rs. 3000 per month after attaining the age of 60 years.

HOW TO APPLY
7. Eligible workers may enrol at the nearest Common Service Centre using Aadhaar and a savings bank account.
"""


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.rule_round = 0
        self.explain_round = 0

    def __call__(self, *, task, profile, system, user=None, build_user=None, validate=None, trace=None, **kw):
        prompt = user if user is not None else build_user(50_000)
        self.calls.append(task)
        cid = {}
        for line in prompt.splitlines():  # map clause numbers to ids, e.g. "[C3] (p.1, ...) 3. ..."
            if line.startswith("[C") and "] (" in line:
                cid_ = line[1:line.index("]")]
                body = line.split(") ", 1)[1]
                cid[body.split(".")[0].strip()] = cid_
        if task == "extract claims":
            data = {"is_policy_document": True, "title": "Pradhan Mantri Test Pension Scheme",
                    "doc_type": "scheme", "issuing_authority": "Ministry of Labour", "jurisdiction": "All India",
                    "effective_date": None, "summary": "A pension scheme for unorganised workers.",
                    "audience": ["unorganised workers"],
                    "claims": [
                        {"kind": "eligibility", "text": "Age between 18 and 40 at entry",
                         "quote": "unorganised worker aged between 18 and 40 years at entry", "clause_id": cid["2"]},
                        {"kind": "eligibility", "text": "Monthly income Rs. 15,000 or below",
                         "quote": "monthly income of the applicant should be Rs. 15,000 or below", "clause_id": cid["3"]},
                        {"kind": "exclusion", "text": "EPFO, ESIC or NPS members are excluded",
                         "quote": "Members of EPFO, ESIC or NPS shall not be eligible", "clause_id": cid["4"]},
                        # wrong clause id: must be relocated, not rejected
                        {"kind": "exclusion", "text": "Income tax payers are excluded",
                         "quote": "A person who is an income tax payer shall not be eligible", "clause_id": cid["2"]},
                        {"kind": "benefit", "text": "Rs. 3000 monthly pension after 60",
                         "quote": "minimum assured pension of Rs. 3000 per month after attaining the age of 60 years",
                         "clause_id": cid["6"]},
                        # invented: must never reach the card
                        {"kind": "benefit", "text": "Free bus pass for all members",
                         "quote": "every subscriber gets a free bus pass in all cities", "clause_id": cid["6"]},
                    ]}
        elif task == "entailment check":
            items = json.loads(prompt.split("ITEMS:\n", 1)[1].split("\n\nReturn JSON", 1)[0])
            data = {"results": [{"id": it["id"], "supported": True, "reason": "ok"} for it in items]}
        elif task == "self-correct claims":
            items = json.loads(prompt.split("FAILED CLAIMS:\n", 1)[1].split("\n\nCLAUSES:", 1)[0])
            data = {"repaired": [], "dropped": [{"id": it["id"], "reason": "not in document"} for it in items]}
        elif task == "compile rules":
            self.rule_round += 1
            ids = {line.split()[1]: line for line in prompt.splitlines() if line.startswith("- K")}
            k_age = next(k for k, l in ids.items() if "18 and 40" in l)
            k_inc = next(k for k, l in ids.items() if "15,000" in l)
            k_epf = next(k for k, l in ids.items() if "EPFO" in l)
            k_tax = next(k for k, l in ids.items() if "income tax" in l.lower())
            age_val = "eighteen" if self.rule_round == 1 else 18  # first pass has a type error
            data = {"rules": [
                {"claim_id": k_age, "kind": "eligibility", "description": "Age 18-40",
                 "condition": {"all": [{"var": "age", "op": ">=", "value": age_val},
                                       {"var": "age", "op": "<=", "value": 40}]}},
                {"claim_id": k_inc, "kind": "eligibility", "description": "Income <= 15000/month",
                 "condition": {"var": "monthly_income", "op": "<=", "value": 15000}},
                {"claim_id": k_epf, "kind": "exclusion", "description": "EPFO/ESIC/NPS member",
                 "condition": {"var": "is_epf_esic_nps_member", "op": "==", "value": True}},
                {"claim_id": k_tax, "kind": "exclusion", "description": "Income tax payer",
                 "condition": {"var": "is_income_tax_payer", "op": "==", "value": True}},
            ], "new_variables": [], "not_compilable": []}
        elif task.startswith("explain in"):
            self.explain_round += 1
            amount = "9999" if self.explain_round == 1 else "3000"  # first draft invents a number
            data = {"title": "प्रधानमंत्री टेस्ट पेंशन योजना",
                    "script": f"इस योजना में 60 साल के बाद हर महीने {amount} रुपये पेंशन मिलती है।",
                    "bullets": {"benefits": [f"{amount} रुपये मासिक पेंशन"]}}
        elif task == "understand citizen":
            data = {"facts": [{"var": "age", "value": 29, "unit": None, "evidence": "29 saal"},
                              {"var": "monthly_income", "value": 12000, "unit": "per_month", "evidence": "12000"},
                              {"var": "is_income_tax_payer", "value": True, "evidence": "main tax bharta hoon"}],
                    "question": None, "language": "hi"}
        elif task.startswith("reply in"):
            data = {"say": "आप पात्र लगते हैं। क्या आप EPFO के सदस्य हैं?"}
        else:
            raise AssertionError(f"unexpected task {task}")
        result = validate(data) if validate else data
        if trace:
            trace({"type": "llm", "task": task, "provider": "Fake", "model": "fake-1", "status": "ok", "ms": 1})
        return result, {"provider": "Fake", "model": "fake-1", "ms": 1, "usage": {}}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "AUDIO_DIR", tmp_path / "audio")
    fake = FakeLLM()
    monkeypatch.setattr(llm, "chat_json", fake)

    def fake_tts(text, lang, out_path, trace=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"ID3" + b"\0" * 2000)
        return "fake-tts"

    monkeypatch.setattr(voice, "synthesize", fake_tts)
    from app import main
    from app.store import Store
    monkeypatch.setattr(main, "store", Store(tmp_path))
    with TestClient(main.app) as c:
        c.fake = fake
        yield c


def _wait(c, job_id, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        snap = c.get(f"/api/jobs/{job_id}").json()
        if snap["status"] in ("done", "error"):
            return snap
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_compile_end_to_end_with_guardrails(client):
    r = client.post("/api/compile", data={"lang": "hi"},
                    files={"file": ("scheme.txt", FIXTURE.encode(), "text/plain")})
    snap = _wait(client, r.json()["job_id"])
    assert snap["status"] == "done", snap["error"]
    events = client.get(f"/api/jobs/{r.json()['job_id']}").json()["events"]
    nodes = [e["node"] for e in events if e["type"] == "node" and e["status"] == "done"]
    assert nodes[:6] == ["fetch", "parse", "segment", "retrieve", "extract", "verify"]
    assert "self_correct" in nodes and nodes.count("compile_rules") == 2  # both loops ran

    card = client.get(f"/api/policies/{snap['result']['policy_id']}").json()
    texts = [c["text"] for c in card["claims"]]
    assert "Free bus pass for all members" not in texts                  # invented claim rejected
    assert any(r["text"] == "Free bus pass for all members" for r in card["rejected"])
    tax = next(c for c in card["claims"] if "tax" in c["text"].lower())
    assert tax["verification"]["method"] == "relocated"                 # wrong clause repaired
    assert len(card["rules"]) == 4                                      # type error fixed on retry
    ex = card["explainers"]["hi"]
    assert "9999" not in ex["script"] and "3000" in ex["script"]       # numeric fidelity guard
    assert ex["audio"].endswith("_hi.mp3")
    assert card["stats"]["rejected"] == 1 and card["stats"]["verified"] == 5

    # same document again -> served from the store without new LLM calls
    n_calls = len(client.fake.calls)
    r2 = client.post("/api/compile", data={"lang": "hi"},
                     files={"file": ("scheme.txt", FIXTURE.encode(), "text/plain")})
    assert _wait(client, r2.json()["job_id"])["status"] == "done"
    assert len(client.fake.calls) == n_calls

    # the voice agent: facts are evidence-checked, verdict comes from the engine
    t = client.post("/api/agent/turn", data={"mode": "policy", "policy_id": card["id"], "lang": "hi",
                                             "text": "meri umar 29 saal hai, 12000 kamata hoon",
                                             "state": "{}"}).json()
    assert t["profile"]["age"] == 29 and t["profile"]["monthly_income"] == 12000
    assert "is_income_tax_payer" not in t["profile"]                    # its evidence was not said
    assert t["evaluations"][0]["status"] == "needs_info"
    assert t["next_var"] == "is_epf_esic_nps_member" or t["next_var"] == "is_income_tax_payer"
    assert t["audio_url"].startswith("/audio/r/")

    radar = client.post("/api/agent/turn", data={"mode": "radar", "lang": "en", "text": "",
                                                 "state": json.dumps(t["state"])}).json()
    assert radar["evaluations"][0]["policy_id"] == card["id"]


def test_compile_rejects_empty_input(client):
    r = client.post("/api/compile", data={"lang": "hi"})
    assert r.status_code == 400


def test_compile_reports_unreadable_document(client):
    r = client.post("/api/compile", data={"lang": "hi"}, files={"file": ("x.txt", b"tiny", "text/plain")})
    snap = _wait(client, r.json()["job_id"])
    assert snap["status"] == "error" and "readable text" in snap["error"]


def test_bad_ids_are_rejected(client):
    assert client.get("/api/policies/..%2F..%2Fetc").status_code in (400, 404)
    assert client.get("/audio/../../etc/passwd").status_code in (400, 404)

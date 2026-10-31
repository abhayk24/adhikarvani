"""Unit tests for the deterministic core: text handling, segmentation, retrieval,
quote verification and the three-valued eligibility engine. No network needed."""
from app.engine import eval_condition, evaluate, plan_next_question, validate_condition
from app.models import Claim, Clause, PolicyCard, Rule, SourceMeta
from app.retrieve import pack, rank_clauses, search
from app.segment import segment
from app.text_utils import (detect_script_lang, extract_numbers, normalize_for_match, tokenize,
                            unsupported_numbers)
from app.variables import CANONICAL, coerce_value
from app.verify import ClauseIndex, evidence_in, verify_quote


# ------------------------------------------------------------- text utils --
def test_hindi_tokens_keep_vowel_signs():
    assert "पात्रता" in tokenize("योजना की पात्रता: आयु 18 वर्ष")
    assert "18" in tokenize("आयु १८ वर्ष") or "१८" not in "".join(tokenize("आयु १८ वर्ष"))


def test_indic_digits_and_lakh():
    assert 250000 in extract_numbers("आय 2.5 लाख रुपये से कम")
    assert 18 in extract_numbers("आयु १८ वर्ष")
    assert 100000 in extract_numbers("Rs. 1,00,000/- per annum")


def test_dates_are_split():
    nums = extract_numbers("last date 31.03.2025")
    assert {31.0, 3.0, 2025.0} <= nums


def test_unsupported_numbers():
    src = ["Rs. 6,000 per year in three instalments of Rs. 2,000 each"]
    assert unsupported_numbers("आपको 6000 रुपये मिलेंगे, 2000 की किस्तों में", src) == []
    assert unsupported_numbers("You get 12000 rupees", src) == ["12000"]


def test_script_detection():
    assert detect_script_lang("प्रधानमंत्री किसान सम्मान निधि योजना") == "hi"
    assert detect_script_lang("Pradhan Mantri Kisan Samman Nidhi") == "en"
    assert detect_script_lang("প্রধানমন্ত্রী কিষাণ") == "bn"


def test_normalize_for_match():
    assert normalize_for_match("“Eligible”  farmers—only!") == "eligible farmers only"


# ---------------------------------------------------------- segmentation --
DOC = """ELIGIBILITY CRITERIA
1. The applicant must be a citizen of India residing in the State.
2. The applicant must be between 18 and 40 years of age on the date of application.
3. Monthly income of the applicant must not exceed Rs. 15,000.

EXCLUSIONS
(a) Persons who are members of EPFO, ESIC or NPS shall not be eligible.
(b) Income tax payers shall not be eligible under the scheme."""


def test_segment_numbered_clauses_and_sections():
    cl = segment([DOC])
    assert len(cl) == 5
    assert cl[0].section.lower().startswith("eligibility")
    assert cl[3].section.lower().startswith("exclusion")
    assert cl[1].text.startswith("2.")


def test_segment_merges_tiny_fragments():
    cl = segment(["Short.\n\nThis is a much longer clause that should absorb the short fragment before it."])
    assert len(cl) == 1 and cl[0].text.startswith("Short.")


def test_retrieval_finds_exclusions():
    cl = segment([DOC])
    ranking, top = rank_clauses(cl)
    assert set(top["exclusion"]) & {cl[3].id, cl[4].id}
    assert search(cl, "income tax payer not eligible")[0].id == cl[4].id
    small = pack(cl, ranking, budget_chars=200)
    assert 0 < len(small) < len(cl)


# ----------------------------------------------------------- verification --
def _claim(quote, cid, kind="eligibility"):
    return Claim(id="K1", kind=kind, text="x", quote=quote, clause_id=cid)


def test_verify_exact_fuzzy_relocated_and_fake():
    cl = segment([DOC])
    idx = ClauseIndex(cl)
    exact = _claim("must be between 18 and 40 years of age", cl[1].id)
    assert verify_quote(exact, idx).method == "exact"
    fuzzy = _claim("must be between 18 and 40 years of age on the date of aplication", cl[1].id)
    assert verify_quote(fuzzy, idx).method in ("exact", "fuzzy")
    wrong = _claim("Income tax payers shall not be eligible", cl[0].id)
    v = verify_quote(wrong, idx)
    assert v.method == "relocated" and wrong.clause_id == cl[4].id
    fake = _claim("Applicants will receive Rs. 50,000 every month", cl[1].id)
    assert not verify_quote(fake, idx).quote_found
    short = _claim("eligible", cl[1].id)
    assert not verify_quote(short, idx).quote_found


def test_evidence_check():
    assert evidence_in("34 saal", "meri umar 34 saal hai")
    assert evidence_in("नहीं", "जी नहीं")
    assert not evidence_in("income 5 lakh", "meri umar 34 saal hai")


# ----------------------------------------------------------------- engine --
def _card(rules):
    return PolicyCard(id="test-policy", title="Test", source=SourceMeta(sha256="x"), rules=rules)


AGE = {"all": [{"var": "age", "op": ">=", "value": 18}, {"var": "age", "op": "<=", "value": 40}]}
INCOME = {"var": "monthly_income", "op": "<=", "value": 15000}
TAX = {"var": "is_income_tax_payer", "op": "==", "value": True}


def test_three_valued_logic():
    assert eval_condition(AGE, {}) is None
    assert eval_condition(AGE, {"age": 30}) is True
    assert eval_condition(AGE, {"age": 50}) is False
    assert eval_condition({"any": [TAX, INCOME]}, {"monthly_income": 9000}) is True
    assert eval_condition({"not": TAX}, {}) is None


def test_evaluate_statuses_and_planner():
    card = _card([Rule(id="R1", kind="eligibility", description="age", condition=AGE, claim_id="K1"),
                  Rule(id="R2", kind="eligibility", description="income", condition=INCOME, claim_id="K2"),
                  Rule(id="R3", kind="exclusion", description="tax", condition=TAX, claim_id="K3")])
    ev = evaluate(card, {})
    assert ev["status"] == "needs_info"
    nxt = plan_next_question([ev], {}, CANONICAL)
    assert nxt in ("age", "monthly_income", "is_income_tax_payer")
    assert evaluate(card, {"age": 30, "monthly_income": 9000, "is_income_tax_payer": False})["status"] == "eligible"
    out = evaluate(card, {"age": 30, "is_income_tax_payer": True})
    assert out["status"] == "not_eligible" and out["blocking"] == ["R3"]
    assert evaluate(_card([]), {})["status"] == "no_rules"


def test_planner_skips_questions_asked_twice():
    card = _card([Rule(id="R1", kind="eligibility", description="age", condition=AGE, claim_id="K1")])
    assert plan_next_question([evaluate(card, {})], {"age": 2}, CANONICAL) is None


def test_validate_condition_catches_type_errors():
    assert validate_condition(AGE, CANONICAL) == []
    errs = validate_condition({"var": "age", "op": ">=", "value": "eighteen"}, CANONICAL)
    assert errs and "number" in errs[0]
    assert validate_condition({"var": "unknown_thing", "op": "==", "value": 1}, CANONICAL)
    assert validate_condition({"var": "state", "op": "==", "value": "atlantis"}, CANONICAL)
    assert validate_condition({"var": "is_income_tax_payer", "op": ">", "value": True}, CANONICAL)


def test_coerce_units():
    assert coerce_value(CANONICAL["land_owned_hectares"], 2, "acre") == round(2 * 0.4047, 4)
    assert coerce_value(CANONICAL["annual_family_income"], 10000, "per_month") == 120000
    assert coerce_value(CANONICAL["state"], "UP") == "uttar pradesh"
    assert coerce_value(CANONICAL["is_income_tax_payer"], "nahi") is False

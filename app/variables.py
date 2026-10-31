"""Canonical citizen-profile variables shared by every compiled policy.

Using one vocabulary across schemes is what makes the Benefit Radar possible:
one answer ("I am 34, I farm 1.5 acres in UP") is reused by every rule of every
compiled policy. Policies may add their own variables when needed.
"""
from __future__ import annotations

from typing import Any, Optional

from .models import VariableDef

STATES = [
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat", "haryana",
    "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana",
    "tripura", "uttar pradesh", "uttarakhand", "west bengal", "andaman and nicobar islands", "chandigarh",
    "dadra and nagar haveli and daman and diu", "delhi", "jammu and kashmir", "ladakh", "lakshadweep", "puducherry",
]
STATE_ALIASES = {"up": "uttar pradesh", "mp": "madhya pradesh", "nct of delhi": "delhi", "new delhi": "delhi",
                 "orissa": "odisha", "pondicherry": "puducherry", "j&k": "jammu and kashmir", "tn": "tamil nadu",
                 "wb": "west bengal", "uttaranchal": "uttarakhand", "ap": "andhra pradesh"}

OCCUPATIONS = ["farmer", "agricultural_labourer", "fisher", "artisan", "street_vendor", "construction_worker",
               "domestic_worker", "daily_wage_worker", "self_employed", "small_business_owner", "salaried_private",
               "government_employee", "student", "unemployed", "homemaker", "retired", "other"]

EDUCATION = ["none", "primary", "8th", "10th", "12th", "diploma", "graduate", "postgraduate"]


def _v(name, type_, question, unit=None, options=None, actionable=False, description=""):
    return VariableDef(name=name, type=type_, question=question, unit=unit, options=options,
                       actionable=actionable, description=description or question)


CANONICAL: dict[str, VariableDef] = {v.name: v for v in [
    _v("age", "number", "How old are you?", "years", description="Applicant's age in completed years"),
    _v("gender", "enum", "Are you male, female or transgender?", options=["male", "female", "transgender"]),
    _v("state", "enum", "Which state or union territory do you live in?", options=STATES,
       description="State/UT of residence"),
    _v("area_type", "enum", "Do you live in a village (rural) or a town/city (urban)?", options=["rural", "urban"]),
    _v("annual_family_income", "number", "What is your whole family's total income in a year, in rupees?",
       "INR per year", description="Total annual income of the family/household"),
    _v("monthly_income", "number", "How much do you yourself earn in a month, in rupees?", "INR per month",
       description="The applicant's own monthly income"),
    _v("occupation", "enum", "What work do you do?", options=OCCUPATIONS),
    _v("social_category", "enum", "Which category do you belong to: General, OBC, SC, ST or EWS?",
       options=["general", "obc", "sc", "st", "ews"]),
    _v("is_minority", "boolean", "Do you belong to a notified minority community?"),
    _v("disability_percent", "number", "Do you have a disability? If yes, what percentage is on your certificate?",
       "percent"),
    _v("has_bpl_card", "boolean", "Does your family have a BPL or Antyodaya ration card?", actionable=False),
    _v("land_owned_hectares", "number", "How much agricultural land does your family own?", "hectares",
       description="Cultivable land owned (1 acre = 0.4047 hectare)"),
    _v("is_income_tax_payer", "boolean", "Did you or anyone in your family pay income tax last year?"),
    _v("is_government_employee", "boolean", "Are you (or your spouse) a serving government employee?"),
    _v("monthly_pension", "number", "Do you get a pension? If yes, how much per month?", "INR per month"),
    _v("marital_status", "enum", "Are you unmarried, married, widowed, divorced or separated?",
       options=["unmarried", "married", "widowed", "divorced", "separated"]),
    _v("education_level", "enum", "What is the highest class or degree you have passed?", options=EDUCATION),
    _v("is_student", "boolean", "Are you currently studying in a school, college or university?"),
    _v("family_size", "number", "How many members are there in your family?", "persons"),
    _v("has_bank_account", "boolean", "Do you have a bank account in your own name?", actionable=True),
    _v("has_aadhaar", "boolean", "Do you have an Aadhaar card?", actionable=True),
    _v("is_epf_esic_nps_member", "boolean", "Are you a member of EPFO, ESIC or NPS (do you have PF deducted)?"),
    _v("owns_pucca_house", "boolean", "Does your family own a pucca (brick/concrete) house?"),
    _v("business_annual_turnover", "number", "If you run a business, what is its yearly turnover in rupees?",
       "INR per year"),
    _v("has_udyam_registration", "boolean", "Is your business registered on Udyam (MSME registration)?",
       actionable=True),
    _v("number_of_employees", "number", "How many people work in your business?", "persons"),
]}

ASK_PRIORITY = ["state", "age", "occupation", "annual_family_income", "monthly_income", "gender",
                "social_category", "land_owned_hectares", "is_income_tax_payer", "is_government_employee"]


def catalog_lines(names: Optional[list[str]] = None, extra: Optional[list[VariableDef]] = None) -> str:
    """Compact text description of variables for prompts."""
    defs = list(CANONICAL.values()) if names is None else [CANONICAL[n] for n in names if n in CANONICAL]
    defs += extra or []
    lines = []
    for v in defs:
        meta = v.type + (f", {v.unit}" if v.unit else "")
        opts = ""
        if v.options:
            shown = v.options if len(v.options) <= 20 else v.options[:20] + ["..."]
            opts = " options: " + " | ".join(shown)
        lines.append(f"- {v.name} ({meta}): {v.description}{opts}")
    return "\n".join(lines)


UNIT_FACTORS = {
    "acre": ("land_owned_hectares", 0.4047), "acres": ("land_owned_hectares", 0.4047),
    "hectare": ("land_owned_hectares", 1.0), "hectares": ("land_owned_hectares", 1.0), "ha": ("land_owned_hectares", 1.0),
}


def coerce_value(var: VariableDef, value: Any, unit: Optional[str] = None) -> Any:
    """Convert an extracted value to the variable's canonical type and unit.

    Raises ValueError for values that do not fit (they are then ignored).
    """
    if value is None:
        raise ValueError("empty")
    u = (unit or "").lower().replace(" ", "_")
    if var.type == "number":
        if isinstance(value, bool):
            raise ValueError("boolean for number")
        if isinstance(value, str):
            value = float(value.replace(",", "").strip())
        num = float(value)
        if var.name == "land_owned_hectares" and u in UNIT_FACTORS:
            num *= UNIT_FACTORS[u][1]
        elif var.name == "land_owned_hectares" and "bigha" in u:
            raise ValueError("bigha varies by state; ask in acres")
        if var.name == "annual_family_income" and ("month" in u):
            num *= 12
        if var.name == "monthly_income" and ("year" in u or "annual" in u):
            num /= 12
        if num < 0:
            raise ValueError("negative")
        return round(num, 4)
    if var.type == "boolean":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "yes", "y", "1", "haan", "ha", "han", "हाँ", "हां", "ji", "हाँ जी"):
            return True
        if s in ("false", "no", "n", "0", "nahi", "nahin", "नहीं", "na"):
            return False
        raise ValueError("not a yes/no value")
    if var.type == "enum":
        s = str(value).strip().lower().replace("-", " ")
        if var.name == "state":
            s = STATE_ALIASES.get(s, s)
        opts = [o.lower() for o in (var.options or [])]
        if s in opts:
            return s
        s2 = s.replace(" ", "_")
        if s2 in opts:
            return s2
        raise ValueError(f"'{value}' is not one of the options")
    return str(value).strip()[:200]

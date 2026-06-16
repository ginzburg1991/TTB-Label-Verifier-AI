"""
Unit tests for the matching logic. These run on plain text (no OCR, no images,
no network), so they're fast and deterministic.

Run:  pytest -q
"""

from backend.warning import check_warning, CANONICAL_WARNING
from backend.matching import verify_fields, overall_verdict


def statuses(results):
    return {r["field"]: r["status"] for r in results}


# ---------- government warning ----------

def test_warning_exact_is_reviewed_for_bold():
    # Correct wording + caps; passes wording but bold can't be confirmed -> review.
    res = check_warning("Some label text\n" + CANONICAL_WARNING)
    assert res["status"] == "review"


def test_warning_titlecase_heading_is_mismatch():
    bad = CANONICAL_WARNING.replace("GOVERNMENT WARNING", "Government Warning")
    res = check_warning(bad)
    assert res["status"] == "mismatch"
    assert "capital" in res["reason"].lower()


def test_warning_missing():
    res = check_warning("OLD TOM DISTILLERY 750 mL 45% Alc./Vol.")
    assert res["status"] == "missing"


def test_warning_altered_wording_is_mismatch():
    altered = CANONICAL_WARNING.replace("birth defects", "health issues")
    res = check_warning(altered)
    assert res["status"] in ("mismatch", "review")
    # A clear word change should not pass cleanly.
    assert res["status"] != "match"


def test_warning_tolerates_ocr_noise():
    # Single-character OCR slip should be treated as a near-match, not a fail.
    noisy = CANONICAL_WARNING.replace("machinery", "machlnery")
    res = check_warning(noisy)
    assert res["status"] == "review"


# ---------- brand name (fuzzy) ----------

def test_brand_casing_and_punctuation_variant_passes():
    ocr = "STONE'S THROW\nSmall Batch Gin\n47% Alc./Vol.\n" + CANONICAL_WARNING
    results = verify_fields({"brand_name": "Stone's Throw"}, ocr)
    assert statuses(results)["Brand name"] == "match"


def test_brand_clearly_absent_is_mismatch():
    ocr = "COMPLETELY DIFFERENT NAME\n" + CANONICAL_WARNING
    results = verify_fields({"brand_name": "Old Tom Distillery"}, ocr)
    assert statuses(results)["Brand name"] == "mismatch"


# ---------- ABV ----------

def test_abv_match():
    ocr = "OLD TOM 45% Alc./Vol. (90 Proof)\n" + CANONICAL_WARNING
    results = verify_fields(
        {"brand_name": "OLD TOM", "alcohol_content": "45% Alc./Vol."}, ocr)
    assert statuses(results)["Alcohol content"] == "match"


def test_abv_mismatch():
    ocr = "OLD TOM 40% Alc./Vol. (80 Proof)\n" + CANONICAL_WARNING
    results = verify_fields(
        {"brand_name": "OLD TOM", "alcohol_content": "45% Alc./Vol."}, ocr)
    assert statuses(results)["Alcohol content"] == "mismatch"


def test_abv_proof_inconsistency_flagged():
    # 45% ABV with 80 proof is inconsistent (should be 90) -> review.
    ocr = "OLD TOM 45% Alc./Vol. (80 Proof)\n" + CANONICAL_WARNING
    results = verify_fields(
        {"brand_name": "OLD TOM", "alcohol_content": "45%"}, ocr)
    assert statuses(results)["Alcohol content"] == "review"


# ---------- net contents ----------

def test_net_contents_unit_normalization():
    ocr = "OLD TOM 750ML 45% Alc./Vol.\n" + CANONICAL_WARNING
    results = verify_fields(
        {"brand_name": "OLD TOM", "net_contents": "750 mL"}, ocr)
    assert statuses(results)["Net contents"] == "match"


def test_net_contents_mismatch():
    ocr = "OLD TOM 700 mL 45% Alc./Vol.\n" + CANONICAL_WARNING
    results = verify_fields(
        {"brand_name": "OLD TOM", "net_contents": "750 mL"}, ocr)
    assert statuses(results)["Net contents"] == "mismatch"


# ---------- class/type, country of origin (regression: keys were dropped) ----------

def test_class_type_is_checked():
    ocr = "OLD TOM\nKentucky Straight Bourbon Whiskey\n45% Alc./Vol.\n" + CANONICAL_WARNING
    results = verify_fields(
        {"brand_name": "OLD TOM", "class_type": "Kentucky Straight Bourbon Whiskey"}, ocr)
    s = statuses(results)
    assert "Class / type" in s and s["Class / type"] == "match"


def test_origin_country_is_checked():
    ocr = "CASA AZULEJO\nTequila\nProduct of Mexico\n" + CANONICAL_WARNING
    results = verify_fields(
        {"brand_name": "CASA AZULEJO", "origin": "Product of Mexico"}, ocr)
    s = statuses(results)
    assert "Origin" in s and s["Origin"] == "match"


def test_origin_state_is_checked():
    ocr = "OLD TOM\nBottled in Bardstown, KY\n" + CANONICAL_WARNING
    results = verify_fields(
        {"brand_name": "OLD TOM", "origin": "Kentucky"}, ocr)
    assert "Origin" in statuses(results)


def test_abv_not_fooled_by_100_percent_agave():
    # "100% de Agave" must not be read as 0% (or 100%) ABV; real ABV is 40%.
    ocr = "CASA AZULEJO\n100% de Agave Tequila\n40% Alc./Vol. (80 Proof)\n" + CANONICAL_WARNING
    results = verify_fields(
        {"brand_name": "CASA AZULEJO", "alcohol_content": "40% Alc./Vol."}, ocr)
    assert statuses(results)["Alcohol content"] == "match"


# ---------- state abbreviation matching (single Origin field) ----------

def test_state_abbreviation_matches_full_name():
    # Label spells out the state, application filed the abbreviation.
    ocr = "OLD TOM\nBottled in Bardstown, Kentucky\n" + CANONICAL_WARNING
    results = verify_fields({"brand_name": "OLD TOM", "origin": "KY"}, ocr)
    assert statuses(results)["Origin"] == "match"


def test_state_full_name_matches_abbreviation():
    # Reverse direction: label has the abbreviation, application spelled it out.
    ocr = "OLD TOM\nBottled in Sonoma, CA\n" + CANONICAL_WARNING
    results = verify_fields({"brand_name": "OLD TOM", "origin": "California"}, ocr)
    assert statuses(results)["Origin"] == "match"


def test_state_abbreviation_does_not_falsely_match_wrong_state():
    ocr = "OLD TOM\nBottled in Miami, Florida\n" + CANONICAL_WARNING
    results = verify_fields({"brand_name": "OLD TOM", "origin": "Oregon"}, ocr)
    assert statuses(results)["Origin"] in ("mismatch", "review")


def test_oregon_not_matched_by_the_word_or_in_the_warning():
    # The warning body contains "or" ("drive a car or operate"). Filing Oregon
    # must NOT match just because of that word.
    ocr = "OLD TOM\nBottled in Miami, FL\n" + CANONICAL_WARNING
    results = verify_fields({"brand_name": "OLD TOM", "origin": "Oregon"}, ocr)
    assert statuses(results)["Origin"] in ("mismatch", "review")


def test_overall_attention_when_field_missing():
    ocr = "OLD TOM 45% Alc./Vol."  # no warning
    results = verify_fields({"brand_name": "OLD TOM"}, ocr)
    verdict, _, _ = overall_verdict(results)
    assert verdict == "attention"


def test_overall_pass_path_is_review_due_to_bold_caveat():
    # Everything correct, but the warning is "review" (bold unconfirmable),
    # so the overall verdict is "review", never a false "all clear".
    ocr = ("OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n"
           "45% Alc./Vol. (90 Proof)\n750 mL\nBardstown, KY\n" + CANONICAL_WARNING)
    results = verify_fields({
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "alcohol_content": "45% Alc./Vol.",
        "net_contents": "750 mL",
    }, ocr)
    verdict, _, _ = overall_verdict(results)
    assert verdict == "review"

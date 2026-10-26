"""pytest for Flexible University's pure rules (fu_logic.py and fu_settings.py)."""
import fu_logic as fl
import fu_settings


# --- Qualifications ---------------------------------------------------------------------
def test_thresholds_match_the_example_for_a_twelve_credit_degree():
    assert fl.credit_threshold(12, 0.33) == 4
    assert fl.credit_threshold(12, 0.66) == 8


def test_thresholds_follow_a_longer_degree():
    assert fl.credit_threshold(14, 0.33) == 5
    assert fl.credit_threshold(14, 0.66) == 10


def test_tiers_around_the_boundaries():
    assert fl.qualification_tier(0, 12) is None
    assert fl.qualification_tier(3, 12) is None
    assert fl.qualification_tier(4, 12) == fl.CERTIFICATE
    assert fl.qualification_tier(7, 12) == fl.CERTIFICATE
    assert fl.qualification_tier(8, 12) == fl.ASSOCIATE
    assert fl.qualification_tier(11, 12) == fl.ASSOCIATE
    assert fl.qualification_tier(12, 12) == fl.DEGREE
    assert fl.qualification_tier(16, 12) == fl.DEGREE


def test_tier_labels():
    assert fl.tier_label(fl.CERTIFICATE) == "Certificate"
    assert fl.tier_label(fl.ASSOCIATE) == "Associate Degree"
    assert fl.tier_label(None) == "No qualification"


def test_credential_and_upgrade_never_downgrades():
    cert = fl.credential(fl.CERTIFICATE, "Biology", "Foxbury", 4, 12, 7)
    assoc = fl.credential(fl.ASSOCIATE, "Biology", "Foxbury", 8, 12, 20)
    assert fl.better_credential(None, cert) == cert
    assert fl.better_credential(cert, assoc) == assoc
    assert fl.better_credential(assoc, cert) == assoc


# --- Friday anchoring -------------------------------------------------------------------
def test_monday_starts_and_ends_the_same_week():
    plan = fl.plan_friday_end(1, 5)
    assert plan == {"days": 4, "weekdays": 5, "extra_weekdays": 0}


def test_sunday_start_reaches_monday_to_friday():
    plan = fl.plan_friday_end(0, 5)
    assert plan["days"] == 5
    assert plan["extra_weekdays"] == 0


def test_tuesday_start_is_stretched_a_week():
    plan = fl.plan_friday_end(2, 5)
    assert plan["days"] == 10
    assert plan["weekdays"] == 9
    assert plan["extra_weekdays"] == 4


def test_wednesday_start_is_stretched_a_week():
    plan = fl.plan_friday_end(3, 5)
    assert plan["days"] == 9
    assert plan["extra_weekdays"] == 3


def test_thursday_start_is_stretched_a_week():
    plan = fl.plan_friday_end(4, 5)
    assert plan["days"] == 8
    assert plan["weekdays"] == 7
    assert plan["extra_weekdays"] == 2


def test_friday_start_gets_a_full_week():
    plan = fl.plan_friday_end(5, 5)
    assert plan["days"] == 7
    assert plan["weekdays"] == 6
    assert plan["extra_weekdays"] == 1


def test_saturday_start_ends_next_friday():
    plan = fl.plan_friday_end(6, 5)
    assert plan["days"] == 6
    assert plan["extra_weekdays"] == 0


def test_every_start_day_ends_on_friday():
    for day in range(7):
        plan = fl.plan_friday_end(day, 5)
        end_day = (day + plan["days"]) % 7
        assert end_day == fl.FRIDAY
        assert plan["weekdays"] >= 5


def test_min_weekdays_is_respected():
    for day in range(7):
        plan = fl.plan_friday_end(day, 3)
        assert plan["weekdays"] >= 3


def test_term_description_mentions_extra_days_only_when_there_are_some():
    assert "extra" not in fl.term_description(fl.plan_friday_end(1, 5))
    assert "extra" in fl.term_description(fl.plan_friday_end(3, 5))


# --- Fractional credits -----------------------------------------------------------------
def test_extension_bonus_is_capped():
    assert fl.extension_credit_bonus(0) == 0.0
    assert fl.extension_credit_bonus(3) == 0.3
    assert fl.extension_credit_bonus(10, 0.1, 0.5) == 0.5


def test_grade_bonus_bands():
    assert fl.grade_credit_bonus(4.0) == 0.25
    assert fl.grade_credit_bonus(3.7) == 0.25
    assert fl.grade_credit_bonus(3.0) == 0.15
    assert fl.grade_credit_bonus(2.0) == 0.05
    assert fl.grade_credit_bonus(1.0) == 0.0
    assert fl.grade_credit_bonus(None) == 0.0


def test_fractions_accumulate_into_whole_credits():
    assert fl.add_fractions(0.0, [0.25, 0.25, 0.25, 0.25]) == (1, 0.0)
    assert fl.add_fractions(0.8, [0.5]) == (1, 0.3)
    assert fl.add_fractions(0.2, [0.05]) == (0, 0.25)
    assert fl.add_fractions(0.0, []) == (0, 0.0)


def test_early_exit_text_names_the_tier_major_and_credits():
    text = fl.early_exit_text(fl.CERTIFICATE, 5, 14, "Biology")
    assert "Certificate in Biology" in text
    assert "5 of 14" in text


# --- Settings ---------------------------------------------------------------------------
def test_settings_types_and_switches():
    settings = fu_settings.Settings()
    assert settings.get("enabled") is True
    settings.set("enabled", "off")
    assert settings.get("enabled") is False
    assert settings.is_switch("enabled")
    settings.set("friday_end_hour", "20")
    assert settings.get("friday_end_hour") == 20
    settings.set("certificate_fraction", 0.4)
    assert settings.get("certificate_fraction") == 0.4


def test_settings_ignore_unknown_keys_from_an_old_file():
    settings = fu_settings.Settings({"enabled": False, "from_the_future": 1})
    assert settings.get("enabled") is False
    assert "from_the_future" not in settings.values


def test_unknown_setting_raises():
    try:
        fu_settings.Settings().set("nope", True)
    except KeyError:
        return
    raise AssertionError("unknown setting should raise KeyError")


def test_zero_min_weekdays_is_treated_as_one():
    plan = fl.plan_friday_end(5, 0)
    assert plan["days"] == 7
    assert plan["weekdays"] >= 1

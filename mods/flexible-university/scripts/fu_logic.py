"""Flexible University - pure rules. No game imports, covered by pytest.

Three ideas:

Qualifications
  Credits are turned into an early-exit qualification when a Sim leaves before the full
  degree: a Certificate at one third of the degree's credits and an Associate Degree at two
  thirds. Thresholds are fractions of the game's own CREDITS_REQUIRED, so they follow a
  patch that changes the degree length. With the game's 12-credit degree this is 4 and 8
  credits, the same tiers as the example snippet.

Friday-anchored terms
  A term never ends mid-week. Given the day it starts, the term ends on the first Friday
  evening that still leaves `min_weekdays` weekdays of study. A term that starts on Tuesday
  therefore runs to the Friday of the following week, not a three-day term. The extra
  weekdays are repaid as fractional credits.

Fractional credits
  A passed course is worth one credit, as in the game, plus a fraction for a strong grade.
  Extra weekdays get a fraction too. Fractions accumulate in the mod's data file and turn
  into a whole credit as soon as they add up, so a good student sometimes finishes a term
  with one more credit than the game would have given them.

Day numbers follow the game's `DateAndTime.day()`: Sunday = 0, Monday = 1, ... Friday = 5.
(The example snippet used Monday = 0, which is off by one.)
"""
import math

CERTIFICATE = "certificate"
ASSOCIATE = "associate"
DEGREE = "degree"

TIER_LABELS = {
    CERTIFICATE: "Certificate",
    ASSOCIATE: "Associate Degree",
    DEGREE: "Degree",
}
TIER_ORDER = {None: 0, CERTIFICATE: 1, ASSOCIATE: 2, DEGREE: 3}

FRIDAY = 5


# --- Qualifications ---------------------------------------------------------------------
def credit_threshold(required_credits, fraction):
    """Whole credit count at which a tier is reached. 12 x 0.33 -> 4, 12 x 0.66 -> 8."""
    return max(1, int(math.ceil(required_credits * fraction)))


def qualification_tier(credits, required_credits, certificate_fraction=0.33,
                       associate_fraction=0.66):
    """The tier a Sim would leave with at this credit count, or None below Certificate."""
    credits = int(credits or 0)
    if credits >= required_credits:
        return DEGREE
    if credits >= credit_threshold(required_credits, associate_fraction):
        return ASSOCIATE
    if credits >= credit_threshold(required_credits, certificate_fraction):
        return CERTIFICATE
    return None


def tier_label(tier):
    return TIER_LABELS.get(tier, "No qualification")


def credential(tier, major, university, credits, required_credits, sim_day=None):
    """One row in the mod's credential list. Names are the game's tuning names, so the
    record still means something if the display name changes."""
    return {
        "tier": tier,
        "label": tier_label(tier),
        "major": major,
        "university": university,
        "credits": int(credits),
        "required": int(required_credits),
        "day": sim_day,
    }


def better_credential(old, new):
    """Keep the stronger qualification. A later, weaker leave never downgrades a Sim."""
    if old is None:
        return new
    if TIER_ORDER.get(old.get("tier"), 0) > TIER_ORDER.get(new.get("tier"), 0):
        return old
    return new


# --- Friday-anchored terms --------------------------------------------------------------
def is_weekday(day):
    return 1 <= (day % 7) <= 5


def weekdays_in_term(start_day, days):
    """Weekdays touched by a term of `days` whole days from `start_day`, end inclusive.

    Monday -> Friday is 5; Tuesday -> Friday is 4; Friday -> next Friday is 6 (both Fridays
    count, which is why a Friday start is treated as having one spare day).
    """
    return sum(1 for offset in range(int(days) + 1) if is_weekday(start_day + offset))


def plan_friday_end(start_day, min_weekdays=5):
    """How long a term that starts on `start_day` should run to end on Friday evening.

    Returns a dict with the number of days, the weekdays in the term and the extra weekdays
    beyond `min_weekdays`. The day count is never negative and always reaches a Friday.
    """
    start_day = int(start_day) % 7
    min_weekdays = max(1, int(min_weekdays))
    days = (FRIDAY - start_day) % 7
    # A start on Friday would otherwise give a term of hours (or a term that ends before it
    # begins); always reach the following Friday. Then keep adding weeks until there are
    # enough weekdays to actually study.
    if days == 0:
        days = 7
    while weekdays_in_term(start_day, days) < min_weekdays:
        days += 7
    weekdays = weekdays_in_term(start_day, days)
    return {"days": days, "weekdays": weekdays, "extra_weekdays": weekdays - min_weekdays}


def extension_credit_bonus(extra_weekdays, per_day=0.1, cap=0.5):
    """Fractional credits for a term stretched to reach Friday."""
    return round(min(max(int(extra_weekdays), 0) * float(per_day), float(cap)), 4)


# --- Fractional credits -----------------------------------------------------------------
def grade_credit_bonus(gp_value, high_threshold=3.7, high_bonus=0.25,
                       mid_threshold=3.0, mid_bonus=0.15,
                       low_threshold=2.0, low_bonus=0.05):
    """Fraction of a credit for a course grade, by the game's grade point value."""
    if gp_value is None:
        return 0.0
    if gp_value >= high_threshold:
        return float(high_bonus)
    if gp_value >= mid_threshold:
        return float(mid_bonus)
    if gp_value >= low_threshold:
        return float(low_bonus)
    return 0.0


def add_fractions(banked, bonuses):
    """Add fractional credits to the bank. Returns (whole credits earned, new remainder)."""
    total = round(float(banked or 0.0) + sum(float(b) for b in bonuses), 4)
    whole = int(math.floor(total + 1e-9))
    return whole, round(total - whole, 4)


# --- Descriptions -----------------------------------------------------------------------
def term_description(plan, end_hour=19):
    """One line for the status command and the log."""
    if plan["extra_weekdays"]:
        return ("{} days ({} weekdays, {} extra) ending Friday {:02d}:00"
                .format(plan["days"], plan["weekdays"], plan["extra_weekdays"], end_hour))
    return "{} days ({} weekdays) ending Friday {:02d}:00".format(
        plan["days"], plan["weekdays"], end_hour)


def early_exit_text(tier, credits, required_credits, minor=None):
    """The confirmation/notification text for leaving with a qualification."""
    name = tier_label(tier)
    if minor:
        name = "{} in {}".format(name, minor)
    return ("{} with {} of {} credits. Those credits are kept if you enroll again."
            .format(name, credits, required_credits))

import pytest

from hardmode_money import (DEBT_LATE_FEE, KIND_MULTIPLIERS, SATURATION_FLOOR, MarketLedger, bill_to_debt,
                            credit_limit, daily_debt_step, household_size_bill_factor, item_kind, markup_curve,
                            markup_satisfaction_factor, markup_scale, repay_debt, repay_options, sell_multiplier,
                            starting_funds_cut)


# --- item kinds (tag names as they appear in the game's tuning) ---

@pytest.mark.parametrize("tags,kind", [
    (["Func_Painting", "Func_Painting_Gifting"], "paintings_art"),
    (["Func_Fish", "Func_Fish_Invasive"], "fish"),
    (["Func_Ingredient_Crystal_Rare"], "crystals_metals"),
    (["Func_Harvestable_Fruit", "Func_Gardening_Apple"], "harvest"),
    (["Func_Woodworking"], "crafted"),
    (["Func_CraftedObject_Generic"], "crafted"),
    (["Func_Collectible", "Func_EP1Collectible_BG"], "collectibles"),
    (["Func_Food", "Func_Meal"], "food"),
])
def test_item_kinds(tags, kind):
    assert item_kind(tags) == kind


def test_fish_tag_does_not_match_fishing_spots():
    assert item_kind(["Func_FishingSpot_Bay", "Func_FishingLocation_Any"]) is None


def test_excluded_tools_are_not_sellable_kinds():
    assert item_kind(["Func_Gardening_Fertilizer_High"]) is None
    assert item_kind(["Func_Fish_Fishbowl"]) is None


def test_furniture_has_no_kind():
    assert item_kind(["Func_Chair", "Func_DiningChair"]) is None
    assert item_kind([]) is None


def test_more_specific_kind_wins():
    # A fish pie is food, but it's tagged with the fish ingredient: fish comes first.
    assert item_kind(["Func_Ingredient_Fish", "Func_Food"]) == "fish"


def test_matching_ignores_case():
    assert item_kind(["func_painting"]) == "paintings_art"


# --- market saturation ---

def test_no_sales_means_full_price():
    assert MarketLedger().saturation(1, "fish", today=10) == 1.0


def test_sales_lower_that_kind_only():
    ledger = MarketLedger()
    ledger.record(1, "fish", 2000, today=10)
    assert ledger.saturation(1, "fish", 10) == pytest.approx(0.8)
    assert ledger.saturation(1, "harvest", 10) == 1.0
    assert ledger.saturation(2, "fish", 10) == 1.0  # other households unaffected


def test_saturation_has_a_floor():
    ledger = MarketLedger()
    ledger.record(1, "fish", 100000, today=10)
    assert ledger.saturation(1, "fish", 10) == SATURATION_FLOOR


def test_market_recovers_over_a_week():
    ledger = MarketLedger()
    ledger.record(1, "fish", 2000, today=10)
    half = ledger.saturation(1, "fish", 13.5)
    assert 0.8 < half < 1.0
    assert ledger.saturation(1, "fish", 17) == 1.0


def test_ledger_round_trip_and_prune():
    ledger = MarketLedger()
    ledger.record(1, "fish", 500, today=1)
    ledger.record(1, "fish", 500, today=10)  # prunes the day-1 sale
    copy = MarketLedger(ledger.to_dict())
    assert copy.data == {"1": {"fish": [(10.0, 500.0)]}}


def test_ledger_ignores_unknown_kind_and_zero():
    ledger = MarketLedger()
    ledger.record(1, None, 500, today=1)
    ledger.record(1, "fish", 0, today=1)
    assert ledger.data == {}


def test_sell_multiplier():
    assert sell_multiplier(None) == 1.0
    assert sell_multiplier("fish") == KIND_MULTIPLIERS["fish"]
    assert sell_multiplier("fish", 0.5) == pytest.approx(KIND_MULTIPLIERS["fish"] * 0.5)


# --- markups ---

@pytest.mark.parametrize("chosen,effective", [
    (0.8, 0.8), (1.0, 1.0), (1.25, 1.25), (1.5, 1.5), (2.0, 1.75), (3.0, 2.0), (4.0, 2.25),
])
def test_markup_curve(chosen, effective):
    assert markup_curve(chosen) == pytest.approx(effective)


def test_markup_curve_never_decreases():
    values = [markup_curve(1 + i / 10) for i in range(40)]
    assert values == sorted(values)


def test_markup_scale():
    assert markup_scale(1.0) == 1.0
    assert markup_scale(4.0) == pytest.approx(2.25 / 4.0)


def test_satisfaction_factor():
    assert markup_satisfaction_factor(1.0) == 1.0
    assert markup_satisfaction_factor(2.0) == pytest.approx(0.7)
    assert markup_satisfaction_factor(10.0) == 0.2


# --- bills, debt, starting funds ---

def test_household_size_bill_factor():
    assert household_size_bill_factor(1) == pytest.approx(0.9)
    assert household_size_bill_factor(4) == pytest.approx(1.2)
    assert household_size_bill_factor(0) == pytest.approx(0.9)


def test_credit_limit():
    assert credit_limit(0) == 5000
    assert credit_limit(100000) == 25000


def test_bill_to_debt_adds_late_fee():
    debt, ok = bill_to_debt(0, 1000, limit=5000)
    assert ok and debt == round(1000 * (1 + DEBT_LATE_FEE))


def test_bill_to_debt_refused_over_limit():
    assert bill_to_debt(4500, 1000, limit=5000) == (4500, False)


def test_daily_debt_step_pays_what_it_can():
    debt, paid = daily_debt_step(1000, funds=50)
    assert paid == 50
    assert debt > 950  # interest added, only 50 paid


def test_daily_debt_step_pays_off_small_debt():
    debt, paid = daily_debt_step(50, funds=1000)
    assert debt == 0 and paid >= 50


def test_daily_debt_step_without_debt():
    assert daily_debt_step(0, 1000) == (0, 0)


def test_starting_funds_cut():
    assert starting_funds_cut(20000, 10000) == 10000
    assert starting_funds_cut(3000, 10000) == 3000  # spent most on a lot: never below 0
    assert starting_funds_cut(20000, 20000) == 0
    assert starting_funds_cut(20000, 0) == 20000


def test_repay_options_are_affordable_steps_then_the_most_possible():
    assert repay_options(3000, funds=20000) == [100, 500, 1000, 3000]
    assert repay_options(3000, funds=700) == [100, 500, 700]
    assert repay_options(80, funds=1000) == [80]


def test_repay_options_empty_without_debt_or_money():
    assert repay_options(0, 1000) == []
    assert repay_options(1000, 0) == []
    assert repay_options(1000, -5) == []


def test_repay_debt_never_pays_more_than_owed_or_owned():
    assert repay_debt(1000, 5000, 400) == (600, 400)
    assert repay_debt(1000, 5000, 9999) == (0, 1000)
    assert repay_debt(1000, 300, 1000) == (700, 300)
    assert repay_debt(1000, 5000, -10) == (1000, 0)

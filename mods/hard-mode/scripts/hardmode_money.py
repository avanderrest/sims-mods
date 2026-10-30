"""Hard Mode: Money - pure logic (no game imports, covered by tests).

Three things make money harder to come by:

1. Selling things you made or gathered pays a fraction of their value (KIND_MULTIPLIERS),
   and the market for each kind fills up: every §SATURATION_STEP sold of one kind in the
   last week takes SATURATION_DROP off its price, down to SATURATION_FLOOR. Sales count
   less as they age and are forgotten after SATURATION_DAYS.
2. Markups (shops, stalls, restaurants, market stands): extra markup earns less and less
   (markup_curve). 300% markup ends up at about +125%, not +200%.
3. Debt (debt_*): an unpaid bill becomes debt with interest instead of the power going off,
   up to a credit limit.
"""

# --- Item kinds -----------------------------------------------------------------------
# Kinds are found from an item's tag names (as the game names them, e.g. "Func_Painting").
# The first rule with a matching fragment wins, so the more specific kinds come first.
# Fragments are matched case-insensitively against each tag name.
KIND_RULES = (
    ("fish", ("Func_Fish", "Func_Ingredient_Fish", "Func_Bait_SmallFish", "Func_Bait_MedFish")),
    ("crystals_metals", ("Func_Ingredient_Crystal", "Func_Ingredient_Metal", "Func_Crystal", "Func_Metal",
                         "Func_MiscMetal", "Func_Element", "Func_GemologyTable_Gem", "Func_FossilRock",
                         "Func_Fossil")),
    ("collectibles", ("Func_Collectible", "Func_CollectArtifact", "Func_ButterflyCollection", "Func_Insect",
                      "Func_Seashell", "Func_Frog", "Func_Collection")),
    ("paintings_art", ("Func_Painting", "Func_Canvas", "Func_Sculpture", "Func_Art_Sculpture", "Func_Photo")),
    ("crafted", ("Func_Craft", "Func_CraftedObject", "Func_Woodworking", "Func_Knitting", "Func_Candle", "Func_CraftedCandle",
                 "Func_Papercraft", "Func_FabricatedItem", "Func_GemologyTable_Jewelry", "Func_RingCrafted",
                 "Func_FlowerArrangement", "Func_Nectar", "Func_RanchNectar", "Func_OrigamiFrog",
                 "Func_OrigamiJellyfish")),
    ("harvest", ("Func_Harvestable", "Func_Gardening", "Func_Foraged", "Func_Ingredient_Plant",
                 "Func_HerbalismPlant", "Func_Ingredient_Herb", "Func_Ingredient_Insect")),
    ("food", ("Func_Food", "Func_Meal", "Func_GrandMeal", "Food_MarketStalls", "Func_Cake")),
)

# Tags that match a rule above but belong to things you don't sell (spots, tools, stations).
EXCLUDED_TAGS = frozenset(t.lower() for t in (
    "Func_Gardening_Fertilizer_Bad", "Func_Gardening_Fertilizer_High", "Func_Gardening_Fertilizer_Low",
    "Func_Gardening_Fertilizer_Max", "Func_Gardening_Fertilizer_Med", "Func_Gardening_Sprinkler",
    "Func_Fish_Fishbowl", "Func_Collection_Spawner", "Func_ButterflyCollection_Spawner",
))

# What made/gathered items sell for, as a fraction of their value. Anything with no kind
# (furniture, store-bought things) is left alone: the game already depreciates furniture.
KIND_MULTIPLIERS = {
    "fish": 0.5,
    "crystals_metals": 0.5,
    "collectibles": 0.6,
    "paintings_art": 0.5,
    "crafted": 0.5,
    "harvest": 0.5,
    "food": 0.6,
}


def item_kind(tag_names):
    """Returns the kind (a KIND_MULTIPLIERS key) for an item's tag names, or None.
    A rule fragment matches a tag that is exactly it or continues with "_" (so Func_Fish
    matches Func_Fish_Invasive but not Func_FishingSpot_Bay)."""
    lowered = [n.lower() for n in tag_names if n]
    lowered = [n for n in lowered if n not in EXCLUDED_TAGS]
    for kind, fragments in KIND_RULES:
        for fragment in fragments:
            f = fragment.lower()
            if any(n == f or n.startswith(f + "_") for n in lowered):
                return kind
    return None


# --- Market saturation ----------------------------------------------------------------
SATURATION_STEP = 1000      # every §1000 sold of one kind in the last week...
SATURATION_DROP = 0.10      # ...takes 10% off that kind's price
SATURATION_FLOOR = 0.30     # never below 30% of the (already reduced) price
SATURATION_DAYS = 7         # sales are forgotten after a week; they count less as they age


class MarketLedger:
    """Sales per household per kind: {household_id: {kind: [(sim_day, amount), ...]}}.
    sim_day is a float (days since the save's start), so "a week ago" works across saves."""

    def __init__(self, data=None):
        self.data = {}
        for hh, kinds in (data or {}).items():
            self.data[str(hh)] = {k: [(float(d), float(a)) for d, a in v] for k, v in kinds.items()}

    def record(self, household_id, kind, amount, today):
        if kind is None or amount <= 0:
            return
        sales = self.data.setdefault(str(household_id), {}).setdefault(kind, [])
        sales.append((float(today), float(amount)))
        self.prune(today)

    def recent_amount(self, household_id, kind, today):
        """Simoleons sold of this kind, each sale weighted by how recent it is (1 today,
        0 after SATURATION_DAYS)."""
        total = 0.0
        for day, amount in self.data.get(str(household_id), {}).get(kind, ()):
            age = today - day
            if 0 <= age < SATURATION_DAYS:
                total += amount * (1 - age / SATURATION_DAYS)
            elif age < 0:  # clock went backwards (another save): count fully, don't crash
                total += amount
        return total

    def saturation(self, household_id, kind, today):
        """Price factor (FLOOR..1) for this kind right now."""
        if kind is None:
            return 1.0
        steps = self.recent_amount(household_id, kind, today) / SATURATION_STEP
        return max(SATURATION_FLOOR, 1.0 - SATURATION_DROP * steps)

    def prune(self, today):
        for kinds in self.data.values():
            for kind in list(kinds):
                kinds[kind] = [(d, a) for d, a in kinds[kind] if today - d < SATURATION_DAYS]
                if not kinds[kind]:
                    del kinds[kind]

    def to_dict(self):
        return {hh: {k: [list(s) for s in v] for k, v in kinds.items()} for hh, kinds in self.data.items()}


def sell_multiplier(kind, saturation=1.0):
    """Our part of an item's sell price (multiplied in with the game's own trait/buff ones)."""
    if kind is None:
        return 1.0
    return KIND_MULTIPLIERS.get(kind, 1.0) * saturation


# --- Markups --------------------------------------------------------------------------
# (start of band, end of band, share of the markup in this band that's actually earned).
# Markup is measured as the price multiplier: 1.0 = no markup, 4.0 = 300% markup.
MARKUP_BANDS = ((1.0, 1.5, 1.0), (1.5, 2.0, 0.5), (2.0, None, 0.25))


def markup_curve(multiplier):
    """Effective price multiplier for a chosen markup multiplier. Below 1 (discounts) and up
    to +50% are unchanged; above that each extra bit earns less."""
    if multiplier <= 1.0:
        return multiplier
    effective = 1.0
    for start, end, share in MARKUP_BANDS:
        if multiplier <= start:
            break
        top = multiplier if end is None else min(multiplier, end)
        effective += (top - start) * share
    return effective


def markup_scale(multiplier):
    """Factor to apply to a price that already includes `multiplier`."""
    if multiplier <= 1.0:
        return 1.0
    return markup_curve(multiplier) / multiplier


# Small businesses (Business & Hobbies): customers get less satisfied with high markups. The
# game's own satisfaction factor for each markup is multiplied by this.
def markup_satisfaction_factor(multiplier):
    if multiplier <= 1.0:
        return 1.0
    return max(0.2, 1.0 - 0.3 * (multiplier - 1.0))


# --- Bills ----------------------------------------------------------------------------
def household_size_bill_factor(household_size):
    """Bills grow with the number of people living there: 1 sim x0.9 ... 4 sims x1.2, 8 x1.6."""
    n = max(1, int(household_size))
    return 0.8 + 0.1 * n


# --- Debt -----------------------------------------------------------------------------
DEBT_LATE_FEE = 0.10          # added once when an unpaid bill becomes debt
DEBT_WEEKLY_INTEREST = 0.05   # charged on the remaining debt once per sim week (daily share)
DEBT_DAILY_PAYMENT_SHARE = 0.10   # each day, this share of the debt (at least DEBT_MIN_PAYMENT)...
DEBT_MIN_PAYMENT = 100            # ...is taken from the household's money if they have it
DEBT_MIN_CREDIT_LIMIT = 5000


def credit_limit(home_value):
    """How much debt a household may run up before bills go back to the game's normal
    'utilities shut off' and the repo man."""
    return max(DEBT_MIN_CREDIT_LIMIT, int(0.25 * max(0, home_value)))


def bill_to_debt(debt, bill, limit):
    """Returns (new_debt, accepted). A bill is turned into debt (plus the late fee) only if
    that stays within the credit limit."""
    new_debt = debt + int(round(bill * (1 + DEBT_LATE_FEE)))
    if bill <= 0 or new_debt > limit:
        return debt, False
    return new_debt, True


def daily_debt_step(debt, funds):
    """One sim day: interest is added, then a payment is taken if the household can afford it.
    Returns (new_debt, payment_taken)."""
    if debt <= 0:
        return 0, 0
    debt = debt * (1 + DEBT_WEEKLY_INTEREST / 7.0)
    due = min(debt, max(DEBT_MIN_PAYMENT, debt * DEBT_DAILY_PAYMENT_SHARE))
    payment = int(min(due, max(0, funds)))
    debt = debt - payment
    return (int(round(debt)) if debt >= 1 else 0), payment


REPAY_STEPS = (100, 500, 1000, 5000, 10000)


def repay_options(debt, funds):
    """Amounts offered when the player pays debt off early (from the phone, like a university
    loan): the round steps they can afford that are below the debt, then everything they can
    afford (the whole debt if they have it). Empty if there's no debt or no money."""
    most = min(debt, max(0, int(funds)))
    if most <= 0:
        return []
    return [step for step in REPAY_STEPS if step < most] + [most]


def repay_debt(debt, funds, amount):
    """Pays `amount` off the debt, limited to the debt and to what the household has.
    Returns (new_debt, paid)."""
    paid = max(0, min(int(amount), debt, int(funds)))
    return debt - paid, paid

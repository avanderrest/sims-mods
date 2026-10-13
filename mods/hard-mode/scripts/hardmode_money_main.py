"""Hard Mode: Money - game layer. The rules are in hardmode_money.py.

Hooks (each one checks its setting every time, so `bluerabbit477.hard.set <setting> off`
works straight away; each also falls back to EA's own result if anything goes wrong):

selling  - SimInfo.get_item_sell_price_modifier: EA asks it for nearly every way of selling
           (inventory, sell pickers, harvests, payouts, market stands) and for the price shown
           in the inventory. Ours multiplies in the item-kind and market-saturation factors.
           Sales are recorded from _Funds.add (money with reason "object sold", which carries
           the items' tags) and from the stand loot op (DestroyTargetObjectsLootOp).
markups  - BusinessManager.get_value_with_markup (retail, restaurants, small businesses),
           the small-business entry/hourly fees and customer satisfaction, and the stand
           loot ops' price multipliers.
bills    - Bills._get_bill_multiplier: bills scale with household size.
debt     - Bills._shut_off_utility: the unpaid bill becomes debt instead (up to a limit);
           a daily alarm charges interest and takes repayments.
start_funds - on loading a household for the first time, it's cut to the setting.

Cheats:
  bluerabbit477.hard.money.status   - markup table, this household's market and debt
  bluerabbit477.hard.money.reset    - forget this household's sales history and debt
  bluerabbit477.hard.money.bill_to_debt - for testing: turn the unpaid bill into debt now
"""
import alarms
import services
import sims4.commands
from date_and_time import create_time_span
from protocolbuffers import Consts_pb2

import hardmode_log
import hardmode_state
from hardmode_money import (MarketLedger, bill_to_debt, credit_limit, daily_debt_step,
                            household_size_bill_factor, item_kind, markup_curve, markup_satisfaction_factor,
                            markup_scale, sell_multiplier, starting_funds_cut)

_LEDGER_FILE = "hard_mode_market.json"
_DEBT_FILE = "hard_mode_debt.json"   # {household_id: debt}
_FUNDS_FILE = "hard_mode_start_funds.json"  # [household_id, ...] already given the start-funds cut

_ledger = None
_debts = None
_kind_cache = {}       # frozenset(tag values) -> kind
_recording_stand_sale = False


def _get_ledger():
    global _ledger
    if _ledger is None:
        _ledger = MarketLedger(hardmode_state.load_json(_LEDGER_FILE, {}))
    return _ledger


def _get_debts():
    global _debts
    if _debts is None:
        _debts = {str(k): int(v) for k, v in hardmode_state.load_json(_DEBT_FILE, {}).items()}
    return _debts


def _kind_for_tags(tags):
    key = frozenset(tags or ())
    if key not in _kind_cache:
        if len(_kind_cache) > 5000:
            _kind_cache.clear()
        _kind_cache[key] = item_kind(hardmode_state.tag_names(key))
    return _kind_cache[key]


def _tags_of(item_or_tags):
    if item_or_tags is None:
        return ()
    if hasattr(item_or_tags, "get_tags"):
        return item_or_tags.get_tags()
    return item_or_tags


# --- Selling ------------------------------------------------------------------------
_installed = False


def _wrap_sell_modifier():
    """Component methods are copied onto SimInfo when its first BuffComponent is made, so this
    runs at zone load (by then SimInfo has EA's version) rather than at import."""
    from sims.sim_info import SimInfo
    original = SimInfo.get_item_sell_price_modifier
    if getattr(original, "_bluerabbit477", False):
        return

    def get_item_sell_price_modifier(self, item_or_tags, *args, **kwargs):
        value = original(self, item_or_tags, *args, **kwargs)
        try:
            if item_or_tags is None or not hardmode_state.setting("selling"):
                return value
            kind = _kind_for_tags(_tags_of(item_or_tags))
            if kind is None:
                return value
            saturation = _get_ledger().saturation(self.household_id, kind, hardmode_state.sim_today())
            return value * sell_multiplier(kind, saturation)
        except Exception:
            hardmode_log.log_exception("sell price modifier")
            return value

    get_item_sell_price_modifier._bluerabbit477 = True
    SimInfo.get_item_sell_price_modifier = get_item_sell_price_modifier
    hardmode_log.log("sell price hook installed")


def _record_sale(household_id, kind, amount, source):
    if kind is None or amount <= 0:
        return
    ledger = _get_ledger()
    today = hardmode_state.sim_today()
    ledger.record(household_id, kind, amount, today)
    hardmode_state.save_json(_LEDGER_FILE, ledger.to_dict())
    hardmode_log.log("sale ({}): household {} sold {} for {}; {} price now x{:.2f}".format(
        source, household_id, kind, amount, kind, ledger.saturation(household_id, kind, today)))


def _wrap_funds():
    from sims.funds import FamilyFunds
    original = FamilyFunds.add

    # Same parameters as EA's _Funds.add, passed on by keyword.
    def add(self, amount, reason, sim=None, tags=None, count_as_earnings=True):
        try:
            if reason == Consts_pb2.TELEMETRY_OBJECT_SELL and not _recording_stand_sale \
                    and hardmode_state.setting("selling") and tags:
                _record_sale(self._household_id, _kind_for_tags(tags), amount, "sold")
        except Exception:
            hardmode_log.log_exception("recording a sale")
        return original(self, amount, reason, sim=sim, tags=tags, count_as_earnings=count_as_earnings)

    FamilyFunds.add = add


# --- Market stands and other "sell this object" loot ------------------------------------
def _wrap_loot_ops():
    from interactions.utils.loot_ops import DestroyObjectsFromInventoryLootOp, DestroyTargetObjectsLootOp

    for cls in (DestroyTargetObjectsLootOp, DestroyObjectsFromInventoryLootOp):
        _wrap_object_value(cls)

    original_apply = DestroyTargetObjectsLootOp._apply_to_subject_and_target

    def _apply_to_subject_and_target(self, subject, target, resolver):
        global _recording_stand_sale
        award = getattr(self, "award_value", None)
        sale = None
        try:
            if award is not None and award.is_sell_action and subject is not None and not subject.is_sim:
                value = self._get_object_value(subject, resolver)
                sale = (subject, value)
                _log_stand_sale(self, subject, resolver, value)
        except Exception:
            hardmode_log.log_exception("reading a stand sale")
        _recording_stand_sale = True
        try:
            return original_apply(self, subject, target, resolver)
        finally:
            _recording_stand_sale = False
            if sale is not None:
                try:
                    household = self._get_subject_household(subject)
                    if household is not None and hardmode_state.setting("selling"):
                        _record_sale(household.id, _kind_for_tags(_tags_of(sale[0])), sale[1], "stand")
                except Exception:
                    hardmode_log.log_exception("recording a stand sale")

    DestroyTargetObjectsLootOp._apply_to_subject_and_target = _apply_to_subject_and_target


def _wrap_object_value(cls):
    original = cls._get_object_value

    def _get_object_value(self, obj, resolver):
        value = original(self, obj, resolver)
        try:
            award = getattr(self, "award_value", None)
            if award is None or not award.is_sell_action or not hardmode_state.setting("markups"):
                return value
            price_multiplier = award.multiplier * award.tested_multipliers.get_multiplier(resolver)
            if price_multiplier > 1:
                return round(value * markup_scale(price_multiplier))
        except Exception:
            hardmode_log.log_exception("stand markup")
        return value

    cls._get_object_value = _get_object_value


def _log_stand_sale(op, obj, resolver, final_value):
    award = op.award_value
    try:
        tested = award.tested_multipliers.get_multiplier(resolver)
    except Exception:
        tested = "?"
    try:
        sell_mod = op._get_sell_price_modifier(obj, resolver)
    except Exception:
        sell_mod = "?"
    hardmode_log.log("stand sale: {} value={} award_multiplier={} tested_multipliers={} sell_modifier={} -> paid {} "
                     "(kind {}, tags {})".format(
                         getattr(getattr(obj, "definition", None), "name", obj), getattr(obj, "current_value", "?"),
                         award.multiplier, tested, sell_mod, final_value, _kind_for_tags(_tags_of(obj)),
                         hardmode_state.tag_names(_tags_of(obj))[:12]))


# --- Shops, stalls, restaurants --------------------------------------------------------
def _wrap_business():
    from business.business_manager import BusinessManager
    original = BusinessManager.get_value_with_markup

    def get_value_with_markup(self, value):
        result = original(self, value)
        try:
            if value and hardmode_state.setting("markups"):
                multiplier = result / value
                if multiplier > 1:
                    return int(result * markup_scale(multiplier))
        except Exception:
            hardmode_log.log_exception("business markup")
        return result

    BusinessManager.get_value_with_markup = get_value_with_markup

    try:
        from small_business.small_business_income_data import SmallBusinessIncomeData
    except ImportError:
        return  # no Business & Hobbies
    for name in ("get_hourly_fee", "get_entry_fee"):
        _wrap_fee(SmallBusinessIncomeData, name)

    original_retail = SmallBusinessIncomeData.compute_retail_markup_fee

    def compute_retail_markup_fee(self, value):
        result = original_retail(self, value)
        try:
            if hardmode_state.setting("markups"):
                return int(value * markup_curve(self.get_markup_multiplier()) - value)
        except Exception:
            hardmode_log.log_exception("small business retail markup")
        return result

    SmallBusinessIncomeData.compute_retail_markup_fee = compute_retail_markup_fee

    original_satisfaction = SmallBusinessIncomeData.get_satisfaction_rate_for_markup

    def get_satisfaction_rate_for_markup(self, markup):
        result = original_satisfaction(self, markup)
        try:
            if hardmode_state.setting("markups"):
                return result * markup_satisfaction_factor(markup)
        except Exception:
            hardmode_log.log_exception("small business satisfaction")
        return result

    SmallBusinessIncomeData.get_satisfaction_rate_for_markup = get_satisfaction_rate_for_markup


def _wrap_fee(cls, name):
    original = getattr(cls, name)

    def fee(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        try:
            if result and hardmode_state.setting("markups"):
                return int(result * markup_scale(self.get_markup_multiplier()))
        except Exception:
            hardmode_log.log_exception("small business " + name)
        return result

    fee.__name__ = name
    setattr(cls, name, fee)


# --- Bills and debt --------------------------------------------------------------------
def _wrap_bills():
    from sims.bills import Bills
    from sims.household_utilities.utility_types import Utilities
    original_multiplier = Bills._get_bill_multiplier

    def _get_bill_multiplier(self):
        multipliers, descriptions = original_multiplier(self)
        try:
            if hardmode_state.setting("bills"):
                size = len(list(self._household.sim_info_gen()))
                factor = household_size_bill_factor(size)
                for utility in Utilities:
                    if utility in multipliers:
                        multipliers[utility] *= factor
                hardmode_log.log("bills for household {}: {} people -> utilities x{:.2f}".format(
                    self._household.id, size, factor))
        except Exception:
            hardmode_log.log_exception("bill multiplier")
        return multipliers, descriptions

    Bills._get_bill_multiplier = _get_bill_multiplier

    original_shut_off = Bills._shut_off_utility

    def _shut_off_utility(self, utility):
        try:
            if hardmode_state.setting("debt") and _bill_into_debt(self):
                return
        except Exception:
            hardmode_log.log_exception("turning a bill into debt")
        return original_shut_off(self, utility)

    Bills._shut_off_utility = _shut_off_utility


def _bill_into_debt(bills):
    """Returns True if the unpaid bill was turned into debt (so nothing gets shut off)."""
    household = bills._household
    owed = bills.current_payment_owed
    if household is None or not owed or owed <= 0:
        return False
    debts = _get_debts()
    debt = debts.get(str(household.id), 0)
    limit = credit_limit(household.get_home_lot_value() or 0)
    new_debt, accepted = bill_to_debt(debt, owed, limit)
    hardmode_log.log("unpaid bill of {} for household {}: debt {} -> {} (limit {}), accepted={}".format(
        owed, household.id, debt, new_debt, limit, accepted))
    if not accepted:
        hardmode_state.notify("Credit refused",
                              "The bank won't lend the {} household any more (debt §{}, limit §{}). "
                              "Unpaid bills now mean the utilities get shut off.".format(household.name, debt, limit))
        return False
    debts[str(household.id)] = new_debt
    hardmode_state.save_json(_DEBT_FILE, debts)
    bills.pay_bill(sound=False, clear_bill=True)
    hardmode_state.notify("Bill moved to debt",
                          "The {} household couldn't pay a bill of §{}. It's been added to their debt with a late fee: "
                          "they now owe §{}, which is repaid bit by bit each day, with interest.".format(
                              household.name, owed, new_debt))
    return True


def add_debt(household, amount, reason):
    """Adds a cost the household couldn't pay to its debt (no credit limit check: this is
    for things already done, like childcare)."""
    debts = _get_debts()
    debts[str(household.id)] = debts.get(str(household.id), 0) + int(amount)
    hardmode_state.save_json(_DEBT_FILE, debts)
    hardmode_log.log("{}: {} added to household {}'s debt (now {})".format(
        reason, amount, household.id, debts[str(household.id)]))


_debt_alarm = None


def _start_debt_alarm(zone):
    global _debt_alarm
    if _debt_alarm is not None:
        alarms.cancel_alarm(_debt_alarm)
    _debt_alarm = alarms.add_alarm(zone, create_time_span(days=1), lambda _: _debt_day(), repeating=True)


def _debt_day():
    try:
        if not hardmode_state.setting("debt"):
            return
        household = services.active_household()
        if household is None:
            return
        debts = _get_debts()
        debt = debts.get(str(household.id), 0)
        if debt <= 0:
            return
        new_debt, payment = daily_debt_step(debt, household.funds.money)
        if payment:
            household.funds.try_remove(payment, Consts_pb2.TELEMETRY_INTERACTION_COST, None)
        debts[str(household.id)] = new_debt
        hardmode_state.save_json(_DEBT_FILE, debts)
        hardmode_log.log("debt day: household {} debt {} -> {} (paid {})".format(household.id, debt, new_debt, payment))
        if new_debt == 0:
            hardmode_state.notify("Debt paid off", "The {} household has paid off all its debt.".format(household.name))
    except Exception:
        hardmode_log.log_exception("daily debt step")


# --- Starting funds --------------------------------------------------------------------
def _apply_starting_funds():
    household = services.active_household()
    if household is None or not household.is_first_time_playing():
        return
    done = set(str(x) for x in hardmode_state.load_json(_FUNDS_FILE, []))
    if str(household.id) in done:
        return
    target = hardmode_state.setting("start_funds")
    cut = starting_funds_cut(household.funds.money, target)
    done.add(str(household.id))
    hardmode_state.save_json(_FUNDS_FILE, sorted(done))
    hardmode_log.log("new household {} ({}): funds {}, start_funds setting {}, cut {}".format(
        household.name, household.id, household.funds.money, target, cut))
    if cut > 0:
        household.funds.try_remove(cut, Consts_pb2.TELEMETRY_INTERACTION_COST, None)
        hardmode_state.notify("Hard Mode", "The {} household starts with §{} less (Hard Mode starting funds: §{})."
                              .format(household.name, cut, target))


# --- Install -------------------------------------------------------------------------
def _install_once():
    global _installed
    if _installed:
        return
    _installed = True
    for name, fn in (("sell price", _wrap_sell_modifier), ("funds", _wrap_funds), ("loot ops", _wrap_loot_ops),
                     ("business", _wrap_business), ("bills", _wrap_bills)):
        try:
            fn()
        except Exception:
            hardmode_log.log_exception("installing the {} hook".format(name))
    hardmode_log.log("money hooks installed")


def on_zone_loaded(zone):
    hardmode_state.ensure_settings()
    _install_once()
    try:
        _start_debt_alarm(zone)
    except Exception:
        hardmode_log.log_exception("starting the debt alarm")
    if hardmode_state.setting("start_funds") is not None:
        try:
            _apply_starting_funds()
        except Exception:
            hardmode_log.log_exception("starting funds")


# --- Cheats --------------------------------------------------------------------------
@sims4.commands.Command("bluerabbit477.hard.money.status", command_type=sims4.commands.CommandType.Live)
def money_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    lines = ["markup -> what it really earns: " + ", ".join(
        "{:.0%}->{:.0%}".format(m - 1, markup_curve(m) - 1) for m in (1.25, 1.5, 2.0, 2.5, 3.0, 4.0))]
    household = services.active_household()
    if household is not None:
        today = hardmode_state.sim_today()
        ledger = _get_ledger()
        kinds = ledger.data.get(str(household.id), {})
        if kinds:
            lines.append("market (price factor for each kind you've sold this week): " + ", ".join(
                "{} x{:.2f}".format(k, ledger.saturation(household.id, k, today)) for k in sorted(kinds)))
        else:
            lines.append("market: nothing sold this week")
        debt = _get_debts().get(str(household.id), 0)
        lines.append("debt: §{} (credit limit §{})".format(debt, credit_limit(household.get_home_lot_value() or 0)))
    for line in lines:
        output(line)
        hardmode_log.log("money.status " + line)


@sims4.commands.Command("bluerabbit477.hard.money.bill_to_debt", command_type=sims4.commands.CommandType.Live)
def money_bill_to_debt(_connection=None):
    """For testing: does now what happens when utilities would be shut off for an unpaid bill."""
    output = sims4.commands.CheatOutput(_connection)
    household = services.active_household()
    bills = getattr(household, "bills_manager", None) if household is not None else None
    if bills is None or not bills.current_payment_owed:
        output("This household has no unpaid bill right now (wait for one to arrive in the mailbox).")
        return
    try:
        moved = _bill_into_debt(bills)
    except Exception:
        hardmode_log.log_exception("hard.money.bill_to_debt")
        output("Failed - see the log.")
        return
    output("Bill moved to debt." if moved else "Not moved (over the credit limit - see the notification).")


@sims4.commands.Command("bluerabbit477.hard.money.reset", command_type=sims4.commands.CommandType.Live)
def money_reset(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    household = services.active_household()
    if household is None:
        output("No active household.")
        return
    _get_ledger().data.pop(str(household.id), None)
    hardmode_state.save_json(_LEDGER_FILE, _get_ledger().to_dict())
    _get_debts().pop(str(household.id), None)
    hardmode_state.save_json(_DEBT_FILE, _get_debts())
    output("Sales history and debt cleared for this household.")


# --- Zone load -------------------------------------------------------------------------
import zone as _zone_module

_original_on_loading_screen_animation_finished = _zone_module.Zone.on_loading_screen_animation_finished


def _patched_on_loading_screen_animation_finished(self, *args, **kwargs):
    result = _original_on_loading_screen_animation_finished(self, *args, **kwargs)
    try:
        on_zone_loaded(self)
    except Exception:
        hardmode_log.log_exception("money: zone load hook")
    return result


_zone_module.Zone.on_loading_screen_animation_finished = _patched_on_loading_screen_animation_finished

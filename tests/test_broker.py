import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX

ticket = load("trader-broker", "ticket")
check = load("trader-risk", "check")

CFG_PATH = os.path.join(ROOT, "trader-budget", "config.example.json")
ORDERS_PATH = os.path.join(FIX, "trader-risk", "orders-tsla.json")
PLAN_PATH = os.path.join(FIX, "trader-budget", "plan-tsla.json")
NOW = "2026-10-19 10:15"
TODAY = "2026-10-19"
AAPL = {"symbol": "AAPL", "side": "buy", "notional": "1250", "type": "market", "time_in_force": "day"}
BATCH = ["AAPL", "AXP", "GOOGL", "KO", "BAC"]
TSLA_CALL = {"symbol": "TSLA", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
             "order_class": "bracket", "take_profit_limit_price": "370.04", "stop_loss_stop_price": "358.32"}
TSLA_PLAIN = ("BUY 8 TSLA, market, good for today / stop-loss 358.32 / take-profit 370.04 / max loss about "
              "$46.88 if the stop fills at 358.32 (it can fill worse in a fast market)")


def tsla(**over):
    with open(ORDERS_PATH) as fh:
        o = json.load(fh)["orders"][0]
    o.update(over)
    return o


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ticket.main(argv)
    return code, out.getvalue(), err.getvalue()


class ExplicitYes(unittest.TestCase):
    def yes(self, reply, order=AAPL, batch=BATCH):
        return ticket.parse_yes(reply, order, batch)[0]

    def test_plain_yes_counts(self):
        for r in ("yes", "Yes.", "YES", "y", "yes place it", "Yes, buy it", "yes AAPL", "yes $1,250 of AAPL",
                  "yes 1250"):
            self.assertTrue(self.yes(r), r)

    def test_anything_else_does_not(self):
        for r in ("", "sure", "ok", "okay", "go", "do it", "yeah", "yep", "absolutely", "send it",
                  "yes to all", "yes, all of them", "yes to the rest", "yes both",
                  "yes AXP", "yes 1000", "yes but make it 1000", "yes?", "no", "not yes",
                  "yes, wait", "yes if it is under 340"):
            self.assertFalse(self.yes(r), r)

    def test_amount_must_match_this_order(self):
        sell = {"symbol": "KO", "side": "sell", "qty": "3", "type": "market", "time_in_force": "day"}
        self.assertTrue(self.yes("yes sell 3 KO", sell))
        self.assertFalse(self.yes("yes sell 4", sell))

    def test_a_bracket_yes(self):
        o = tsla()
        for r in ("yes", "yes 8 TSLA", "yes 358.32", "yes max loss 46.88", "yes target 370.04"):
            self.assertTrue(self.yes(r, o, ["TSLA"]), r)
        for r in ("yes 9", "yes 10 TSLA", "yes but stop at 357", "yes, stop 358.32", "yes AAPL", "sure"):
            self.assertFalse(self.yes(r, o, ["TSLA", "AAPL"]), r)


class TicketShape(unittest.TestCase):
    def test_tool_input_is_the_alpaca_call(self):
        o = dict(AAPL, why="from a list")
        self.assertEqual(ticket.tool_input(o), AAPL)
        self.assertEqual(ticket.tool_input({"symbol": "KO", "side": "buy", "qty": 3, "type": "limit",
                                            "limit_price": 89.5, "time_in_force": "day"}),
                         {"symbol": "KO", "side": "buy", "qty": "3", "type": "limit", "limit_price": "89.5",
                          "time_in_force": "day"})

    def test_the_bracket_call_leaves_out_why_and_plan(self):
        self.assertEqual(ticket.tool_input(tsla()), TSLA_CALL)
        self.assertEqual(ticket.fingerprint(tsla()), ticket.fingerprint(TSLA_CALL))

    def test_plain_english(self):
        self.assertEqual(ticket.plain(AAPL), "BUY $1,250 of AAPL, market order, good for today")
        self.assertEqual(ticket.plain({"symbol": "KO", "side": "sell", "qty": "1", "type": "limit",
                                       "limit_price": "95", "time_in_force": "gtc"}),
                         "SELL 1 share of KO, limit order at $95, good until canceled")
        self.assertEqual(ticket.plain(tsla()), TSLA_PLAIN)
        lim = tsla(type="limit", limit_price="364.00")
        self.assertEqual(ticket.plain(lim).split(" / ")[0], "BUY 8 TSLA, limit 364.00, good for today")
        self.assertEqual(ticket.max_loss(lim), (45.44, 358.32))
        no_plan = dict(TSLA_CALL)
        self.assertEqual(ticket.max_loss(no_plan), (None, 358.32))


class DesktopConfig(unittest.TestCase):
    def test_example_is_paper_with_placeholder_keys(self):
        with open(os.path.join(ROOT, "trader-broker", "claude_desktop_config.example.json")) as fh:
            server = json.load(fh)["mcpServers"]["alpaca"]
        self.assertEqual((server["command"], server["args"]), ("uvx", ["alpaca-mcp-server"]))
        self.assertEqual(server["env"]["ALPACA_PAPER_TRADE"], "true")
        for k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
            self.assertIn("NEVER_IN_CHAT", server["env"][k])


class Flow(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.orders = os.path.join(self.d, "orders.json")
        shutil.copy(ORDERS_PATH, self.orders)
        self.cfg = os.path.join(self.d, "config.json")
        shutil.copy(CFG_PATH, self.cfg)
        self.risk = os.path.join(self.d, "state", "risk.json")
        self.state = os.path.join(self.d, "state", "broker.json")
        self.pf = os.path.join(self.d, "portfolio.json")
        self.none = os.path.join(self.d, "none")

    def tearDown(self):
        shutil.rmtree(self.d)

    def args(self, *extra, **kw):
        return list(extra) + ["--orders", self.orders, "--config", self.cfg, "--risk", self.risk,
                              "--state", self.state, "--now", kw.get("now", NOW)]

    def run_risk(self, now=NOW):
        with redirect_stdout(io.StringIO()):
            return check.main(["--orders", self.orders, "--config", self.cfg, "--portfolio", self.pf,
                               "--prices", self.none, "--state", self.state, "--now", now, "--out", self.risk])

    def state_doc(self):
        with open(self.state) as fh:
            return json.load(fh)

    def test_nothing_is_ready_before_the_risk_check(self):
        code, text, _ = run(self.args("show"))
        self.assertEqual(code, 1)
        self.assertIn("NOT READY", text)
        self.assertNotIn("Reply \"yes\"", text)
        code, _, err = run(self.args("approve", "--index", "1", "--reply", "yes"))
        self.assertEqual(code, 1)
        self.assertIn("not ready", err)

    def test_the_full_two_yes_flow(self):
        self.assertEqual(self.run_risk(), 0)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 0)
        self.assertIn("ORDER 1 of 1, PAPER account, Alpaca", text)
        for part in TSLA_PLAIN.split(" / "):
            self.assertIn("  " + part + "\n", text)
        self.assertIn("READY: trader-risk PASS", text)
        self.assertIn('"order_class": "bracket"', text)
        self.assertIn('"stop_loss_stop_price": "358.32"', text)
        self.assertNotIn('"plan"', text)
        self.assertNotIn('"why"', text)
        self.assertIn("Allow once", text)

        code, text, _ = run(self.args("approve", "--index", "1", "--reply", "sure"))
        self.assertEqual(code, 1)
        self.assertIn("Not recorded", text)
        self.assertFalse(os.path.exists(self.state))

        code, text, _ = run(self.args("approve", "--index", "1", "--reply", "yes"))
        self.assertEqual(code, 0)
        self.assertIn("place_stock_order", text)
        self.assertEqual(json.loads(text[text.index("{"):text.rindex("}") + 1]), TSLA_CALL)
        code, _, err = run(self.args("approve", "--index", "1", "--reply", "yes"))
        self.assertEqual(code, 1)
        self.assertIn("APPROVED", err)

        code, text, _ = run(self.args("result", "--index", "1", "--status", "placed", "--broker-id", "abc123",
                                      "--filled-qty", "8", "--filled-price", "364.20", "--portfolio", self.pf,
                                      now="2026-10-19 10:16"))
        self.assertEqual(code, 0)
        st = self.state_doc()
        self.assertEqual([r["status"] for r in st["orders"]], ["approved", "placed", "filled"])
        appr, plc = st["orders"][0], st["orders"][1]
        self.assertEqual((appr["reply"], appr["kind"], appr["max_loss"], appr["date"]), ("yes", "entry", 46.88, TODAY))
        self.assertEqual(appr["at"], "2026-10-19T10:15:00-04:00")
        self.assertEqual((plc["broker_order_id"], plc["max_loss"], plc["kind"]), ("abc123", 46.88, "entry"))
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual(pf["cash"], 2086.4)
        self.assertEqual(pf["positions"][0]["shares"], 8)

        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("DONE: placed", text)
        code, text, _ = run(["log", "--state", self.state, "--now", NOW])
        self.assertIn("1 placed today", text)
        self.assertIn("max loss $46.88", text)

        # trader-risk now counts it: a second TSLA buy today is a duplicate, and $46.88 is used
        res = check.check([tsla()], {"budget": 5000}, state=st, now=check.parse_now("2026-10-19 10:30"))
        self.assertIn("already placed today", " ".join(res["results"][0]["reasons"]))
        self.assertEqual((res["today"]["entries_placed"], res["today"]["loss_at_risk"]), (1, 46.88))

    def test_flatten_by_the_close(self):
        self.run_risk()
        run(self.args("approve", "--index", "1", "--reply", "yes"))
        run(self.args("result", "--index", "1", "--status", "placed", "--broker-id", "abc",
                      "--filled-qty", "8", "--filled-price", "364.20", "--portfolio", self.pf))
        late = "2026-10-19 15:55"
        code, text, _ = run(["flatten", "--symbol", "TSLA", "--orders", self.orders, "--portfolio", self.pf,
                             "--plan", PLAN_PATH, "--config", self.cfg, "--now", late])
        self.assertEqual(code, 0)
        self.assertIn("SELL 8 shares of TSLA, market order, good for today (flat by 15:55 New York)", text)
        self.assertIn("replaced 1 earlier proposal", text)
        self.assertIn("cancel_order_by_id", text)
        with open(self.orders) as fh:
            doc = json.load(fh)
        self.assertEqual(ticket.tool_input(doc["orders"][0]),
                         {"symbol": "TSLA", "side": "sell", "qty": "8", "type": "market", "time_in_force": "day"})
        self.assertEqual(self.run_risk(now=late), 0)       # after the 15:30 entry cutoff: an exit still passes
        with open(self.risk) as fh:
            self.assertEqual(json.load(fh)["results"][0]["kind"], "exit")
        code, text, _ = run(self.args("show", now=late))
        self.assertEqual(code, 0)
        self.assertIn("READY", text)
        self.assertEqual(run(self.args("approve", "--index", "1", "--reply", "yes sell 8 TSLA", now=late))[0], 0)
        code, _, _ = run(self.args("result", "--index", "1", "--status", "placed", "--filled-qty", "8",
                                   "--filled-price", "366.10", "--portfolio", self.pf, now="2026-10-19 15:56"))
        self.assertEqual(code, 0)
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual((pf["cash"], pf["positions"]), (5015.2, []))
        self.assertEqual(check.day_trades(self.state_doc(), TODAY), (1, ["2026-10-19 TSLA"]))
        code, _, err = run(["flatten", "--symbol", "TSLA", "--orders", self.orders, "--portfolio", self.pf,
                            "--now", late])
        self.assertEqual(code, 1)
        self.assertIn("nothing to flatten", err)

    def test_flatten_with_the_broker_qty(self):
        code, text, _ = run(["flatten", "--symbol", "tsla", "--qty", "8", "--orders", self.orders,
                             "--portfolio", self.none, "--plan", self.none, "--config", self.cfg, "--now", NOW])
        self.assertEqual(code, 0)
        self.assertNotIn("Check it against get_open_position", text)
        self.assertEqual(run(["flatten", "--symbol", "TSLA", "--qty", "0", "--orders", self.orders])[0], 1)

    def test_an_edited_order_is_not_ready(self):
        self.run_risk()
        with open(self.orders) as fh:
            doc = json.load(fh)
        doc["orders"][0]["qty"] = "9"
        with open(self.orders, "w") as fh:
            json.dump(doc, fh)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertEqual(code, 1)
        self.assertIn("was not in the last risk check", text)

    def test_yesterdays_check_does_not_count(self):
        self.run_risk(now="2026-10-16 10:15")
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("not today", text)

    def test_blocked_orders_are_never_ready(self):
        self.assertEqual(self.run_risk(now="2026-10-19 09:40"), 1)
        code, text, _ = run(self.args("show", "--index", "1", now="2026-10-19 09:40"))
        self.assertIn("BLOCKED by trader-risk: window: no new entries before 09:45", text)
        code, _, _ = run(self.args("approve", "--index", "1", "--reply", "yes", now="2026-10-19 09:40"))
        self.assertEqual(code, 1)

    def test_result_needs_an_approval_and_decline_is_logged(self):
        self.run_risk()
        code, _, err = run(self.args("result", "--index", "1", "--status", "placed"))
        self.assertEqual(code, 1)
        self.assertIn("no yes recorded", err)
        code, text, _ = run(self.args("decline", "--index", "1", "--reply", "no thanks"))
        self.assertEqual(code, 0)
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("DONE: declined", text)

    def test_ibkr_tickets_send_the_final_yes_to_ibkr(self):
        with open(self.cfg) as fh:
            c = json.load(fh)
        c["broker"] = "ibkr"
        with open(self.cfg, "w") as fh:
            json.dump(c, fh)
        self.run_risk()
        code, text, _ = run(self.args("show", "--index", "1"))
        self.assertIn("Interactive Brokers", text)
        self.assertIn("after you approve it there", text)
        self.assertNotIn("place_stock_order", text)

    def test_fill_sell_relieves_the_oldest_lot(self):
        pf = {"cash": 0, "positions": [{"ticker": "KO", "shares": 3, "lots": [
            {"id": "KO-1", "date": "2025-01-02", "shares": 2, "cost": 120.0},
            {"id": "KO-2", "date": "2026-01-02", "shares": 1, "cost": 70.0}]}]}
        with open(self.pf, "w") as fh:
            json.dump(pf, fh)
        code, text, _ = run(["fill", "--symbol", "KO", "--side", "sell", "--qty", "2.5", "--price", "90",
                             "--date", TODAY, "--portfolio", self.pf, "--config", self.cfg, "--state", self.state])
        self.assertEqual(code, 0)
        with open(self.pf) as fh:
            pf = json.load(fh)
        self.assertEqual(pf["cash"], 225.0)
        lots = pf["positions"][0]["lots"]
        self.assertEqual([l["id"] for l in lots], ["KO-2"])
        self.assertEqual(lots[0]["shares"], 0.5)
        self.assertEqual(lots[0]["cost"], 35.0)
        self.assertEqual(self.state_doc()["orders"][-1]["status"], "filled")
        code, _, err = run(["fill", "--symbol", "KO", "--side", "sell", "--qty", "5", "--price", "90",
                            "--portfolio", self.pf, "--config", self.cfg, "--state", self.state])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- the Time Machine note on the ticket

import importlib.util

size = load("trader-budget", "size")
PLAN_MADE = "2026-10-19T14:15:00Z"
TM_MADE = "2026-10-19T14:15:30Z"
TM_POOR = {"p_target": 0.002, "p_stop": 0.138, "r_at_target": 1.0, "avg_R": -0.065}
TM_FINE = {"p_target": 0.20, "p_stop": 0.15, "r_at_target": 1.0, "avg_R": 0.12}


def _read(path):
    with open(path) as fh:
        return fh.read()


def _dump(path, doc):
    with open(path, "w") as fh:
        json.dump(doc, fh)


def _tm_doc(plan, mc=TM_POOR, made=TM_MADE, **over):
    saved = {k: plan.get(k) for k in size.TM_PLAN_KEYS}
    saved.update(over)
    return {"created_by": "trader-timemachine", "created_at": made, "plan": saved, "mc": dict(mc),
            "history": {"triggered": 34, "avg_R": -0.269}}


class TicketTimeMachine(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        j = lambda n: os.path.join(self.d, n)
        self.orders, self.cfg, self.plan_p, self.tm_p = j("orders.json"), j("config.json"), j("plan.json"), j("tm.json")
        self.risk, self.state, self.pf, self.none = j("state/risk.json"), j("state/broker.json"), j("pf.json"), j("none")
        shutil.copy(ORDERS_PATH, self.orders)
        shutil.copy(CFG_PATH, self.cfg)
        with open(PLAN_PATH) as fh:
            self.plan = json.load(fh)
        self.plan["created_at"] = PLAN_MADE
        _dump(self.plan_p, self.plan)
        with redirect_stdout(io.StringIO()):
            check.main(["--orders", self.orders, "--config", self.cfg, "--portfolio", self.pf, "--prices",
                        self.none, "--state", self.state, "--now", NOW, "--out", self.risk])

    def tearDown(self):
        shutil.rmtree(self.d)

    def show(self, *extra):
        return run(["show", "--orders", self.orders, "--config", self.cfg, "--risk", self.risk,
                    "--state", self.state, "--plan", self.plan_p, "--timemachine", self.tm_p,
                    "--now", NOW] + list(extra))

    def test_a_matching_poor_result_warns_on_the_ticket(self):
        _dump(self.tm_p, _tm_doc(self.plan))
        code, text, _ = self.show("--index", "1")
        self.assertEqual(code, 0)
        self.assertIn("  TIME MACHINE WARNING (not a block): the replay of this exact plan leans toward the "
                      "stop: target first 0.2 % vs stop first 13.8 %; simulated average -0.065R; "
                      "historical average -0.269R over 34 past sessions.", text)
        self.assertIn("READY: trader-risk PASS, waiting for your yes", text)
        self.assertIn("Reply \"yes\" to place this one order", text)
        self.assertLess(text.index("READY:"), text.index("TIME MACHINE WARNING"))
        self.assertLess(text.index("TIME MACHINE WARNING"), text.index("Claude will call place_stock_order"))
        self.assertNotIn("unavailable or stale", text)

    def test_a_matching_fair_result_is_only_informational(self):
        _dump(self.tm_p, _tm_doc(self.plan, TM_FINE))
        code, text, _ = self.show("--index", "1")
        self.assertEqual(code, 0)
        self.assertIn("  Time Machine (this exact plan): target first 20.0 % vs stop first 15.0 %", text)
        self.assertNotIn("WARNING", text)

    def test_stale_or_missing_results_say_unavailable_and_never_warn(self):
        stale = {
            "other stop": lambda: _dump(self.tm_p, _tm_doc(self.plan, stop=358.00)),
            "other symbol": lambda: _dump(self.tm_p, _tm_doc(self.plan, symbol="NVDA")),
            "other date": lambda: _dump(self.tm_p, _tm_doc(self.plan, date="2026-10-16")),
            "older than the plan": lambda: _dump(self.tm_p, _tm_doc(self.plan, made="2026-10-19T14:00:00Z")),
            "broken json": lambda: open(self.tm_p, "w").close(),
            "not a dict": lambda: _dump(self.tm_p, [1, 2]),
            "no file": lambda: os.path.exists(self.tm_p) and os.remove(self.tm_p),
        }
        for name, make in stale.items():
            make()
            code, text, _ = self.show("--index", "1")
            self.assertEqual(code, 0, name)
            self.assertIn("  Time Machine result unavailable or stale.", text, name)
            self.assertNotIn("WARNING", text, name)
            self.assertIn("READY: trader-risk PASS", text, name)

    def test_an_order_that_is_not_from_the_current_plan_gets_no_result(self):
        # the plan was redone with a new stop and the Time Machine re-run for it, but the order
        # on the table is still the old bracket: the result is about a different trade
        newer = dict(self.plan, stop=359.00, risk_per_share=5.18)
        _dump(self.plan_p, newer)
        _dump(self.tm_p, _tm_doc(newer))
        code, text, _ = self.show("--index", "1")
        self.assertIn("Time Machine result unavailable or stale.", text)
        self.assertNotIn("WARNING", text)

    def test_the_ticket_and_the_budget_summary_cannot_disagree(self):
        cases = [("poor", lambda: _dump(self.tm_p, _tm_doc(self.plan))),
                 ("fair", lambda: _dump(self.tm_p, _tm_doc(self.plan, TM_FINE))),
                 ("stale", lambda: _dump(self.tm_p, _tm_doc(self.plan, stop=358.00))),
                 ("missing", lambda: os.path.exists(self.tm_p) and os.remove(self.tm_p))]
        for name, make in cases:
            make()
            _, ticket_text, _ = self.show("--index", "1")
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                size.main(["--plan", self.plan_p, "--config", self.cfg, "--portfolio", self.none,
                           "--timemachine", self.tm_p, "--now", NOW])
            budget_text = out.getvalue()
            tm_lines = [l for l in budget_text.splitlines()
                        if l.strip().startswith(("TIME MACHINE", "Time Machine", "trader-risk checks your rules"))]
            self.assertTrue(tm_lines, name)
            for l in tm_lines:
                self.assertIn("  " + l.strip() + "\n", ticket_text, name)

    def test_the_ticket_calls_the_budget_function_and_has_no_rules_of_its_own(self):
        mod = ticket._budget()
        self.assertEqual(os.path.basename(os.path.dirname(mod.__file__)), "trader-budget")
        self.assertEqual(ticket.TM_UNAVAILABLE, size.TM_UNAVAILABLE)
        with open(os.path.join(ROOT, "trader-broker", "ticket.py")) as fh:
            src = fh.read()
        for word in ("TM_POOR_GAP", "p_stop", "p_target", "avg_R", "COIN_FLIP"):
            self.assertNotIn(word, src)

    def test_budget_missing_means_unavailable_not_a_crash(self):
        saved = list(ticket._BUDGET)
        ticket._BUDGET[:] = [None]
        try:
            _dump(self.tm_p, _tm_doc(self.plan))
            code, text, _ = self.show("--index", "1")
            self.assertEqual(code, 0)
            self.assertIn("  Time Machine result unavailable or stale.", text)
            self.assertNotIn("WARNING", text)
        finally:
            ticket._BUDGET[:] = saved

    def test_exit_tickets_carry_no_note(self):
        _dump(self.tm_p, _tm_doc(self.plan))
        sell = {"symbol": "TSLA", "side": "sell", "qty": "8", "type": "market", "time_in_force": "day"}
        for rv in (None, {"kind": "exit"}):
            self.assertIsNone(ticket.time_machine_for(sell, rv, self.plan, _tm_doc(self.plan), TODAY))
        buy = tsla()
        self.assertEqual(ticket.time_machine_for(buy, {"kind": "entry"}, self.plan,
                                                 _tm_doc(self.plan), TODAY)[0], "warning")

    def test_json_carries_the_note_and_nothing_else_changes(self):
        _dump(self.tm_p, _tm_doc(self.plan))
        _, with_text, _ = self.show("--index", "1", "--json")
        os.remove(self.tm_p)
        _, without_text, _ = self.show("--index", "1", "--json")
        a, b = json.loads(with_text), json.loads(without_text)
        self.assertEqual(a["time_machine"]["status"], "warning")
        self.assertIn("TIME MACHINE WARNING (not a block)", a["time_machine"]["message"])
        self.assertEqual(b["time_machine"]["status"], "unavailable")
        a.pop("time_machine"), b.pop("time_machine")
        self.assertEqual(a, b)   # fingerprint, status, tool_input, max loss: all identical

    def test_the_approval_gate_and_order_data_do_not_change(self):
        records = []
        for with_tm in (True, False):
            if with_tm:
                _dump(self.tm_p, _tm_doc(self.plan))
            elif os.path.exists(self.tm_p):
                os.remove(self.tm_p)
            if os.path.exists(self.state):
                os.remove(self.state)
            before = _read(self.orders)
            risk_before = _read(self.risk)
            args = ["--orders", self.orders, "--config", self.cfg, "--risk", self.risk, "--state", self.state,
                    "--now", NOW]
            code, text, _ = run(["approve", "--index", "1", "--reply", "sure"] + args)
            self.assertEqual(code, 1)                      # still not a yes, with or without a warning
            self.assertIn("Not recorded", text)
            code, text, _ = run(["approve", "--index", "1", "--reply", "yes"] + args)
            self.assertEqual(code, 0)                      # a plain yes is still accepted: it is not a gate
            with open(self.state) as fh:
                records.append(json.load(fh)["orders"])
            self.assertEqual(_read(self.orders), before)
            self.assertEqual(_read(self.risk), risk_before)
        self.assertEqual(records[0], records[1])

    def test_the_cloud_copy_says_the_same(self):
        path = os.path.join(ROOT, ".claude", "skills", "trader-broker", "ticket.py")
        spec = importlib.util.spec_from_file_location("trader_cloud_ticket", path)
        cloud = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cloud)
        self.assertIn(os.path.join(".claude", "skills", "trader-budget"), cloud._budget().__file__)
        for doc in (_tm_doc(self.plan), _tm_doc(self.plan, TM_FINE), _tm_doc(self.plan, stop=1.0), None):
            self.assertEqual(cloud.time_machine_for(tsla(), None, self.plan, doc, TODAY),
                             ticket.time_machine_for(tsla(), None, self.plan, doc, TODAY))

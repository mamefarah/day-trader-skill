import json
import os
import re
import unittest

from _load import ROOT

# v2, the day-trading pack: the eleven folders the reel's repo card shows
SKILLS = ["trader-scanner", "trader-news", "trader-entry", "trader-exit", "trader-timemachine",
          "trader-risk", "trader-budget", "trader-broker", "trader-alerts", "trader-analyst",
          "trader-pelosi"]
ABOUT = ("11 Claude skills for day trading: scan thousands of charts, track breaking news, time every "
         "entry and exit, and replay every outcome before you risk a dollar.")
# skills on the way to an order carry the safety block
ORDER_PATH = ["trader-scanner", "trader-entry", "trader-exit", "trader-timemachine", "trader-budget",
              "trader-pelosi", "trader-risk", "trader-broker", "trader-alerts"]
V1_ONLY = ["trader-copycat", "trader-screener", "trader-tax", "trader-rebalance"]


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def every_text_file():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".csv", ".txt", ".xml")) or f == "LICENSE":
                yield os.path.join(base, f)


class Repo(unittest.TestCase):
    def test_eleven_skill_folders_at_the_root(self):
        found = sorted(d for d in os.listdir(ROOT)
                       if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_root_matches_the_reel(self):
        root = sorted(d for d in os.listdir(ROOT) if not d.startswith(".git"))
        # .claude (the persistent cloud copy) and trader/ (the paper-trial config) are the
        # cloud setup's additions on top of the reel's layout
        self.assertEqual(root, sorted([".claude", ".claude-plugin", "LICENSE", "README.md",
                                       "tests", "trader"] + SKILLS))

    def test_frontmatter_name_and_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 200, "%s description is too thin" % s)
            self.assertGreater(len(text.splitlines()), 60, s)

    def test_order_path_skills_carry_the_safety_rule(self):
        for s in ORDER_PATH:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertIn("not financial advice", low, s)
            self.assertIn("yes", low, s)

    def test_plugin_manifest_points_at_the_root_skills(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "day-trader-skill")
        self.assertEqual(plugin["skills"], "./")
        self.assertEqual(plugin["description"], ABOUT)
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(market["name"], "day-trader-skill")
        self.assertEqual(market["plugins"][0]["name"], "day-trader-skill")

    def test_readme_carries_the_reel_copy(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertTrue(readme.startswith("# The Day Trader skill"))
        for line in (ABOUT,
                     "https://github.com/Jakeschincariol/day-trader-skill install skill",
                     "/plugin marketplace add Jakeschincariol/day-trader-skill",
                     "/plugin install day-trader-skill@day-trader-skill",
                     "## Fine print"):
            self.assertIn(line, readme)
        for s in SKILLS:
            self.assertIn("/" + s, readme, s)

    def test_no_em_dashes_and_no_personal_email(self):
        for path in every_text_file():
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            rel = os.path.relpath(path, ROOT)
            if not rel.startswith(os.path.join("tests", "fixtures")):  # fixtures are real data, kept as published
                self.assertNotIn("\u2014", text, rel)
            self.assertNotIn("jakeschincariol" + "@" + "gmail.com", text, rel)  # built, so this file passes too

    def test_no_v1_only_skill_is_left_behind(self):
        for path in every_text_file():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith("tests" + os.sep) or rel == "README.md":
                continue  # the README points v1 users to the v1 commit
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for old in V1_ONLY:
                self.assertNotIn(old, text, rel)

    def test_every_tool_runs_on_python_3_8(self):
        # no 3.9+ only modules or syntax in the tools (the README promises 3.8)
        for s in SKILLS:
            folder = os.path.join(ROOT, s)
            for f in os.listdir(folder):
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(folder, f), encoding="utf-8") as fh:
                    src = fh.read()
                for bad in ("import zoneinfo", "from zoneinfo", ".removeprefix(", ".removesuffix(",
                            "match ", "list[", "dict[", "tuple["):
                    if bad == "match ":
                        self.assertNotRegex(src, r"(?m)^\s+match \w+.*:$", "%s/%s" % (s, f))
                    elif bad.endswith("["):
                        self.assertNotRegex(src, r"(?<![\w.])%s" % re.escape(bad), "%s/%s" % (s, f))
                    else:
                        self.assertNotIn(bad, src, "%s/%s" % (s, f))

    def test_day_trading_limits_ship_in_the_example_config(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        for k in ("max_loss_per_trade_usd", "max_daily_loss_usd", "max_trades_per_day",
                  "min_reward_risk", "require_stop", "no_entries_after", "flat_by"):
            self.assertIn(k, cfg, k)
        self.assertIs(cfg["require_stop"], True)
        self.assertIs(cfg.get("allow_short", False), False)
        self.assertIs(cfg.get("allow_margin", False), False)

    def test_paper_trading_is_the_default(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        self.assertIs(cfg["paper"], True)
        self.assertIs(cfg.get("allow_options", False), False)

    def test_cloud_copy_matches_the_root_skills(self):
        # .claude/skills/ is what a fresh Claude Code cloud session loads as /trader-*.
        # It must stay a byte-for-byte copy of the root folders: edit one, copy to the other.
        cloud = os.path.join(ROOT, ".claude", "skills")
        self.assertEqual(sorted(os.listdir(cloud)), sorted(SKILLS))
        for s in SKILLS:
            def files(base):
                out = {}
                for dirpath, dirs, names in os.walk(base):
                    dirs[:] = [d for d in dirs if d != "__pycache__"]
                    for n in names:
                        full = os.path.join(dirpath, n)
                        with open(full, "rb") as fh:
                            out[os.path.relpath(full, base)] = fh.read()
                return out
            self.assertEqual(files(os.path.join(ROOT, s)), files(os.path.join(cloud, s)), s)

    def test_trial_config_is_a_1000_dollar_paper_account(self):
        with open(os.path.join(ROOT, "trader", "config.json")) as fh:
            cfg = json.load(fh)
        self.assertEqual(cfg["budget"], 1000)
        self.assertIs(cfg["paper"], True)
        self.assertIs(cfg["require_stop"], True)
        for k in ("allow_options", "allow_margin", "allow_short"):
            self.assertIs(cfg[k], False, k)
        # no single trade or day may risk more than a few percent of the account
        self.assertLessEqual(cfg["max_loss_per_trade_usd"], 0.02 * cfg["budget"])
        self.assertLessEqual(cfg["max_daily_loss_usd"], 0.05 * cfg["budget"])
        self.assertLessEqual(cfg["max_order_usd"], cfg["budget"] * cfg["max_position_pct"] / 100.0)
        # no email address (or any personal detail) is committed for the SEC user agent
        self.assertNotIn("sec_user_agent", cfg)

    def test_no_broker_or_order_tool_is_pre_allowed(self):
        # the cloud setup must never pre-approve an order tool
        for name in ("settings.json", "settings.local.json"):
            path = os.path.join(ROOT, ".claude", name)
            if os.path.exists(path):
                with open(path) as fh:
                    text = fh.read()
                self.assertNotIn("place_stock_order", text.split('"ask"')[0] if '"ask"' in text else text)


if __name__ == "__main__":
    unittest.main()

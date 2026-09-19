"""Offline tests: portfolio maths, formatting and rendered markup.

No network, no SDK, no running bar. Run from the plugin folder with:

    python3 -m unittest discover -s tests -v
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio  # noqa: E402
import views  # noqa: E402


def t(key: str) -> str:
    """A translator stand-in that echoes placeholders back."""
    table = {
        "sp.tileTitle": "Portfolio {value}, {change} today, {count} positions",
        "sp.heroCaption": "{count} positions in {currency}",
        "sp.settingsHint": "{base} {provider} {minutes}",
        "sp.noRate": "{currency} {base}",
        "sp.unconvertedNote": "{symbols} {base}",
        "sp.editPosition": "Edit {symbol}",
        "sp.removePosition": "Remove {symbol}",
        "sp.removeWatch": "Remove {symbol}",
        "sp.pick": "Use {symbol}",
        "sp.watchThis": "Watch {symbol}",
        "sp.sparkLabel": "History {count}",
        "sp.symbolSpark": "Prices {symbol}",
    }
    return table.get(key, key.split(".")[-1])


def quote(symbol, price, prev, currency="USD", name=None, points=None):
    return {
        "symbol": symbol,
        "name": name or symbol,
        "price": price,
        "prev": prev,
        "currency": currency,
        "exchange": "",
        "points": points or [],
    }


BASE_DATA = {
    "quotes": {},
    "fx": {"EUR": 1.0},
    "series": {},
    "history": [],
    "lastOk": "10:00",
    "error": "",
    "busy": False,
    "tab": "portfolio",
    "query": "",
    "results": [],
    "searching": False,
    "formError": "",
    "positionError": "",
    "positionOk": "",
    "draft": {"symbol": "", "name": "", "shares": "", "buyPrice": "", "editing": False},
    "tabChosen": True,
}

BASE_CFG = {
    "positions": [],
    "watchlist": [],
    "symbols": [],
    "baseCurrency": "EUR",
    "provider": "yahoo",
    "refreshMinutes": 5,
    "alertPercent": 0,
    "coverLayout": "statSplit",
    "tileRotate": True,
    "hasToken": False,
}


def data(**changes):
    merged = {key: value for key, value in BASE_DATA.items()}
    merged.update(changes)
    return merged


def cfg(**changes):
    merged = {key: value for key, value in BASE_CFG.items()}
    merged.update(changes)
    return merged


class Validation(unittest.TestCase):
    def test_positions_drop_invalid_entries(self):
        raw = [
            {"symbol": "aapl", "shares": 3, "buyPrice": 100},
            {"symbol": "AAPL", "shares": 5},  # duplicate
            {"symbol": "", "shares": 2},
            {"symbol": "MSFT", "shares": 0},
            {"symbol": "MSFT", "shares": "many"},
            {"symbol": "SAP.DE", "shares": 1.5, "buyPrice": -4},
            "not a dict",
        ]
        result = portfolio.normalize_positions(raw)
        self.assertEqual([entry["symbol"] for entry in result], ["AAPL", "SAP.DE"])
        self.assertEqual(result[0]["buyPrice"], 100.0)
        self.assertEqual(result[1]["buyPrice"], 0.0)

    def test_watchlist_accepts_a_comma_string_and_skips_held_symbols(self):
        result = portfolio.normalize_watchlist(" aapl , ^gdaxi ,, aapl ", exclude=["AAPL"])
        self.assertEqual(result, ["^GDAXI"])

    def test_symbol_rejects_markup(self):
        self.assertEqual(portfolio.clean_symbol("<script>"), "")
        self.assertEqual(portfolio.clean_symbol("brk-b"), "BRK-B")
        self.assertEqual(portfolio.clean_symbol("x" * 40), "")

    def test_tracked_symbols_are_unique_and_capped(self):
        positions = [{"symbol": "A", "shares": 1.0, "buyPrice": 0.0}]
        watch = ["A", "B"]
        self.assertEqual(portfolio.tracked_symbols(positions, watch), ["A", "B"])


class Maths(unittest.TestCase):
    def test_row_in_the_base_currency(self):
        quotes = {"SAP.DE": quote("SAP.DE", 110.0, 100.0, "EUR")}
        row = portfolio.position_row(
            {"symbol": "SAP.DE", "shares": 10, "buyPrice": 50.0},
            quotes,
            "EUR",
            {"EUR": 1.0},
        )
        self.assertAlmostEqual(row["value"], 1100.0)
        self.assertAlmostEqual(row["dayAbs"], 100.0)
        self.assertAlmostEqual(row["dayPct"], 10.0)
        self.assertAlmostEqual(row["gainAbs"], 600.0)
        self.assertAlmostEqual(row["gainPct"], 120.0)

    def test_row_converts_a_foreign_currency(self):
        quotes = {"AAPL": quote("AAPL", 200.0, 200.0, "USD")}
        row = portfolio.position_row(
            {"symbol": "AAPL", "shares": 2, "buyPrice": 100.0},
            quotes,
            "EUR",
            {"EUR": 1.0, "USD": 0.5},
        )
        self.assertAlmostEqual(row["value"], 200.0)
        self.assertAlmostEqual(row["gainAbs"], 100.0)

    def test_row_without_a_rate_is_marked_unconverted(self):
        quotes = {"AAPL": quote("AAPL", 200.0, 190.0, "USD")}
        row = portfolio.position_row(
            {"symbol": "AAPL", "shares": 2, "buyPrice": 0.0}, quotes, "EUR", {"EUR": 1.0}
        )
        self.assertTrue(row["hasQuote"])
        self.assertIsNone(row["value"])
        self.assertFalse(row["converted"])

    def test_missing_quote_keeps_the_row(self):
        row = portfolio.position_row(
            {"symbol": "AAPL", "shares": 2, "buyPrice": 0.0}, {}, "EUR", {"EUR": 1.0}
        )
        self.assertFalse(row["hasQuote"])
        self.assertIsNone(row["price"])

    def test_totals_sum_only_valued_rows(self):
        quotes = {
            "A": quote("A", 110.0, 100.0, "EUR"),
            "B": quote("B", 50.0, 50.0, "USD"),
        }
        positions = [
            {"symbol": "A", "shares": 10, "buyPrice": 100.0},
            {"symbol": "B", "shares": 1, "buyPrice": 0.0},
            {"symbol": "C", "shares": 1, "buyPrice": 0.0},
        ]
        rows = [portfolio.position_row(p, quotes, "EUR", {"EUR": 1.0}) for p in positions]
        sums = portfolio.totals(rows)
        self.assertEqual(sums["valued"], 1)
        self.assertAlmostEqual(sums["value"], 1100.0)
        self.assertAlmostEqual(sums["dayAbs"], 100.0)
        self.assertAlmostEqual(sums["dayPct"], 10.0)
        self.assertAlmostEqual(sums["gainAbs"], 100.0)
        self.assertEqual(sums["unpriced"], ["C"])
        self.assertEqual(sums["unconverted"], ["B"])

    def test_totals_of_an_empty_portfolio(self):
        sums = portfolio.totals([])
        self.assertIsNone(sums["value"])
        self.assertIsNone(sums["dayPct"])
        self.assertEqual(sums["valued"], 0)

    def test_gain_ignores_positions_without_a_buy_price(self):
        quotes = {"A": quote("A", 100.0, 100.0, "EUR"), "B": quote("B", 100.0, 100.0, "EUR")}
        rows = [
            portfolio.position_row(
                {"symbol": "A", "shares": 1, "buyPrice": 50.0}, quotes, "EUR", {"EUR": 1.0}
            ),
            portfolio.position_row(
                {"symbol": "B", "shares": 1, "buyPrice": 0.0}, quotes, "EUR", {"EUR": 1.0}
            ),
        ]
        sums = portfolio.totals(rows)
        self.assertAlmostEqual(sums["value"], 200.0)
        self.assertAlmostEqual(sums["gainAbs"], 50.0)
        self.assertAlmostEqual(sums["cost"], 50.0)

    def test_change_needs_a_usable_previous_close(self):
        self.assertEqual(portfolio.quote_change(quote("A", 10.0, None)), (None, None))
        self.assertEqual(portfolio.quote_change(quote("A", 10.0, 0)), (None, None))

    def test_top_mover_is_the_largest_move_either_way(self):
        rows = [
            {"symbol": "A", "dayPct": 1.0},
            {"symbol": "B", "dayPct": -3.0},
            {"symbol": "C", "dayPct": None},
        ]
        self.assertEqual(portfolio.top_mover(rows)["symbol"], "B")
        self.assertIsNone(portfolio.top_mover([{"symbol": "C", "dayPct": None}]))

    def test_zero_previous_value_does_not_divide(self):
        sums = portfolio.totals(
            [
                {
                    "symbol": "A",
                    "hasQuote": True,
                    "value": 0.0,
                    "dayAbs": 0.0,
                    "gainAbs": None,
                }
            ]
        )
        self.assertIsNone(sums["dayPct"])


class Formatting(unittest.TestCase):
    def test_german_and_english_number_style(self):
        self.assertEqual(portfolio.fmt_number(1234.5, "de"), "1.234,50")
        self.assertEqual(portfolio.fmt_number(1234.5, "en"), "1,234.50")

    def test_money_places_the_sign_per_language(self):
        self.assertTrue(portfolio.fmt_money(12.0, "EUR", "de").endswith("\u20ac"))
        self.assertTrue(portfolio.fmt_money(12.0, "USD", "en").startswith("$"))
        self.assertEqual(portfolio.fmt_money(12.0, "ZAR", "en"), "12.00 ZAR")

    def test_percent_is_always_signed(self):
        self.assertTrue(portfolio.fmt_percent(1.5, "en").startswith("+"))
        self.assertTrue(portfolio.fmt_percent(-1.5, "en").startswith("\u2212"))
        self.assertEqual(portfolio.fmt_percent(None), portfolio.NO_DATA)

    def test_compact_money_drops_cents_when_long(self):
        self.assertNotIn(".", portfolio.fmt_money_compact(123456.0, "USD", "en").replace(",", ""))
        self.assertIn(".", portfolio.fmt_money_compact(99.5, "USD", "en"))

    def test_price_uses_more_decimals_below_one(self):
        self.assertIn("0.1234", portfolio.fmt_price(0.1234, "USD", "en"))

    def test_shares_drop_trailing_zeros_for_whole_numbers(self):
        self.assertEqual(portfolio.fmt_shares(3.0, "en"), "3")
        self.assertEqual(portfolio.fmt_shares(1.5, "en"), "1.5000")

    def test_signed_money_uses_the_same_signs_as_percent(self):
        self.assertEqual(portfolio.fmt_signed_money(38.1, "EUR", "en"), "+38.10\u00a0\u20ac")
        self.assertTrue(portfolio.fmt_signed_money(-38.1, "EUR", "en").startswith("\u2212"))
        self.assertEqual(portfolio.fmt_signed_money(None, "EUR"), portfolio.NO_DATA)

    def test_initials_skip_symbol_punctuation(self):
        self.assertEqual(portfolio.initials("^GDAXI"), "GD")
        self.assertEqual(portfolio.initials("SAP.DE"), "SA")
        self.assertEqual(portfolio.initials(""), "?")

    def test_spark_points_need_two_values(self):
        self.assertEqual(portfolio.spark_points([1.0]), "")
        self.assertEqual(portfolio.spark_points([1.0, 2.0]), "1,2")
        self.assertEqual(portfolio.spark_points([1.0, None, 2.0]), "1,2")


class Markup(unittest.TestCase):
    def render_all(self, d, c):
        return (
            views.tile(d, c, t, "en"),
            views.hover(d, c, t, "en"),
            views.flyout(d, c, t, "en"),
        )

    def test_every_surface_renders_when_empty(self):
        for html in self.render_all(data(), cfg()):
            self.assertTrue(html.strip())
            self.assertNotIn("None", html)

    def test_every_cover_layout_renders_a_single_tile_root(self):
        quotes = {"AAPL": quote("AAPL", 200.0, 190.0, "EUR", points=[1.0, 2.0, 3.0])}
        d = data(quotes=quotes, history=[100.0, 110.0])
        for layout in views.LAYOUTS:
            c = cfg(
                coverLayout=layout,
                positions=[{"symbol": "AAPL", "shares": 2.0, "buyPrice": 100.0}],
                symbols=["AAPL"],
            )
            html = views.tile(d, c, t, "en")
            self.assertEqual(html.count('class="sb-tile"'), 1, layout)
            self.assertTrue(html.startswith("<div class=\"sb-tile\""), layout)
            self.assertTrue(html.endswith("</div>"), layout)

    def test_tile_keeps_its_structure_without_data(self):
        html = views.tile(
            data(),
            cfg(positions=[{"symbol": "AAPL", "shares": 1.0, "buyPrice": 0.0}]),
            t,
            "en",
        )
        self.assertIn(portfolio.NO_DATA, html)
        self.assertIn("sb-tile", html)

    def test_tile_rotates_only_with_several_views(self):
        quotes = {"AAPL": quote("AAPL", 2.0, 1.0, "EUR")}
        single = views.tile(data(quotes=quotes), cfg(tileRotate=False, symbols=["AAPL"]), t, "en")
        self.assertNotIn("data-rotator", single)
        many = views.tile(
            data(quotes=quotes),
            cfg(
                positions=[{"symbol": "AAPL", "shares": 1.0, "buyPrice": 0.0}],
                symbols=["AAPL"],
                tileRotate=True,
            ),
            t,
            "en",
        )
        self.assertIn('data-rotator="up"', many)

    def test_flyout_has_exactly_one_root_and_one_width_request(self):
        html = views.flyout(data(), cfg(), t, "en")
        self.assertEqual(html.count("data-sb-flyout-width"), 1)
        self.assertTrue(html.startswith("<section data-sb-flyout-width="))
        self.assertTrue(html.endswith("</section>"))

    def test_flyout_marks_exactly_one_active_tab_and_hides_the_others(self):
        for tab in views.TABS:
            html = views.flyout(data(tab=tab), cfg(), t, "en")
            self.assertEqual(html.count("sb-tab sb-active"), 1, tab)
            self.assertIn(f'data-tab-panel="{tab}">', html)
            self.assertEqual(html.count("data-tab-panel"), len(views.TABS))
            self.assertEqual(html.count("hidden>"), len(views.TABS) - 1, tab)

    def test_position_table_renders_one_row_per_holding(self):
        quotes = {
            "AAPL": quote("AAPL", 200.0, 190.0, "EUR", name="Apple Inc."),
            "SAP.DE": quote("SAP.DE", 100.0, 100.0, "EUR", name="SAP SE"),
        }
        c = cfg(
            positions=[
                {"symbol": "AAPL", "shares": 2.0, "buyPrice": 100.0},
                {"symbol": "SAP.DE", "shares": 1.0, "buyPrice": 0.0},
            ],
            symbols=["AAPL", "SAP.DE"],
        )
        html = views.flyout(data(quotes=quotes, history=[10.0, 20.0]), c, t, "en")
        self.assertEqual(html.count("<tr "), 2)
        self.assertIn("Apple Inc.", html)
        self.assertIn('data-action="remove-position"', html)
        self.assertIn("sb-table__num", html)

    def test_missing_quote_shows_a_badge_not_a_crash(self):
        c = cfg(
            positions=[{"symbol": "AAPL", "shares": 2.0, "buyPrice": 0.0}],
            symbols=["AAPL"],
        )
        html = views.flyout(data(), c, t, "en")
        self.assertIn("sb-badge-warning", html)

    def test_error_state_keeps_the_last_values_and_explains(self):
        quotes = {"AAPL": quote("AAPL", 200.0, 190.0, "EUR")}
        c = cfg(positions=[{"symbol": "AAPL", "shares": 1.0, "buyPrice": 0.0}], symbols=["AAPL"])
        html = views.flyout(data(quotes=quotes, error="HTTP 429"), c, t, "en")
        self.assertIn("HTTP 429", html)
        self.assertIn("sb-tip", html)
        tile_html = views.tile(data(quotes=quotes, error="HTTP 429"), c, t, "en")
        self.assertIn("triangle-alert", tile_html)

    def test_finnhub_without_a_key_warns(self):
        html = views.flyout(data(), cfg(provider="finnhub", hasToken=False), t, "en")
        self.assertIn("sb-alert--warn", html)

    def test_external_text_is_escaped(self):
        nasty = '<img src=x onerror="alert(1)">&'
        quotes = {"AAPL": quote("AAPL", 10.0, 9.0, "EUR", name=nasty)}
        c = cfg(positions=[{"symbol": "AAPL", "shares": 1.0, "buyPrice": 0.0}], symbols=["AAPL"])
        d = data(
            quotes=quotes,
            error=nasty,
            results=[{"symbol": "AAPL", "name": nasty, "kind": "EQUITY", "exchange": nasty}],
            query="x",
            formError=nasty,
            positionError=nasty,
        )
        for tab in views.TABS:
            html = views.flyout(dict(d, tab=tab), c, t, "en")
            # The payload may appear, but only in its escaped form: no raw tag
            # and no attribute boundary the sanitizer could read as markup.
            self.assertNotIn(nasty, html)
            self.assertNotIn("<img", html)
            self.assertIn("&lt;img", html)
            # attribute VALUES may quote hostile text; only bare attribute names count
        self.assertNotRegex(re.sub(r'"[^"]*"', '""', html), r"<[a-z]+[^>]*\son[a-z]+=")

    def test_context_menu_attribute_is_valid_json(self):
        quotes = {"AAPL": quote("AAPL", 10.0, 9.0, "EUR")}
        c = cfg(positions=[{"symbol": "AAPL", "shares": 1.0, "buyPrice": 0.0}], symbols=["AAPL"])
        html = views.flyout(data(quotes=quotes), c, t, "en")
        import html as html_module
        import json

        for raw in re.findall(r"data-context-items='([^']*)'", html):
            entries = json.loads(html_module.unescape(raw))
            self.assertIsInstance(entries, list)
            self.assertTrue(len(entries) <= 12)
            for entry in entries:
                self.assertIn("label", entry)
                self.assertLessEqual(len(entry["label"]), 64)
            self.assertLessEqual(len(raw), 4096)

    def test_icon_only_buttons_carry_a_name(self):
        quotes = {"AAPL": quote("AAPL", 10.0, 9.0, "EUR")}
        c = cfg(watchlist=["AAPL"], symbols=["AAPL"])
        html = views.flyout(data(quotes=quotes, tab="watchlist"), c, t, "en")
        for button in re.findall(r"<button[^>]*sb-btn-icon[^>]*>", html):
            self.assertIn("aria-label=", button)
            self.assertIn("title=", button)

    def test_sparkline_is_omitted_below_two_points(self):
        quotes = {"AAPL": quote("AAPL", 10.0, 9.0, "EUR", points=[10.0])}
        c = cfg(watchlist=["AAPL"], symbols=["AAPL"])
        html = views.flyout(data(quotes=quotes, tab="watchlist"), c, t, "en")
        self.assertNotIn("data-chart=\"sparkline\"", html)

    def test_german_markup_omits_the_tween_hook(self):
        quotes = {"AAPL": quote("AAPL", 10.0, 9.0, "EUR")}
        c = cfg(positions=[{"symbol": "AAPL", "shares": 1.0, "buyPrice": 0.0}], symbols=["AAPL"])
        self.assertNotIn("data-sb-tween", views.tile(data(quotes=quotes), c, t, "de"))
        self.assertIn("data-sb-tween", views.tile(data(quotes=quotes), c, t, "en"))

    def test_popup_markup(self):
        html = views.alert_popup("AAPL", -4.2, 100.0, 95.8, "USD", t, "en")
        self.assertIn("trending-down", html)
        self.assertIn("AAPL", html)

    def test_empty_portfolio_offers_the_button_that_fixes_it(self):
        html = views.flyout(data(tabChosen=True), cfg(), t, "en")
        self.assertIn("sb-empty", html)
        self.assertIn('data-action="select-tab" data-value="manage"', html)
        self.assertIn("sb-btn-primary", html)

    def test_an_untouched_empty_plugin_opens_on_the_add_tab(self):
        html = views.flyout(data(tabChosen=False), cfg(), t, "en")
        self.assertIn('<section data-tab-panel="manage">', html)
        self.assertIn('<section data-tab-panel="portfolio" hidden>', html)

    def test_a_chosen_tab_wins_over_the_empty_default(self):
        html = views.flyout(data(tabChosen=True, tab="watchlist"), cfg(), t, "en")
        self.assertIn('<section data-tab-panel="watchlist">', html)

    def test_once_something_is_tracked_the_holdings_tab_opens(self):
        c = cfg(watchlist=["AAPL"], symbols=["AAPL"])
        html = views.flyout(data(tabChosen=False), c, t, "en")
        self.assertIn('<section data-tab-panel="portfolio">', html)

    def test_the_stepper_advances_once_a_symbol_is_picked(self):
        blank = views.flyout(data(tab="manage", tabChosen=True), cfg(), t, "en")
        self.assertIn("sb-stepper__step is-current", blank)
        self.assertNotIn("is-done", blank)
        picked = views.flyout(
            data(
                tab="manage",
                tabChosen=True,
                draft={"symbol": "AAPL", "name": "Apple Inc.", "shares": "", "buyPrice": "", "editing": False},
            ),
            cfg(),
            t,
            "en",
        )
        self.assertIn("sb-stepper__step is-done", picked)
        self.assertIn("Apple Inc.", picked)
        self.assertEqual(picked.count('aria-current="step"'), 1)

    def test_the_add_card_offers_both_outcomes(self):
        html = views.flyout(data(tab="manage", tabChosen=True), cfg(), t, "en")
        self.assertIn('type="submit" class="sb-btn sb-btn-primary" data-action="add-position"', html)
        # "follow only" must not submit, or the required shares field would block it
        self.assertRegex(html, r'<button type="button"[^>]*data-action="add-watch"')

    def test_quick_picks_only_for_the_provider_whose_symbols_they_are(self):
        yahoo = views.flyout(data(tab="manage", tabChosen=True), cfg(), t, "en")
        self.assertIn('data-action="pick" data-value="^GDAXI"', yahoo)
        finnhub = views.flyout(
            data(tab="manage", tabChosen=True), cfg(provider="finnhub", hasToken=True), t, "en"
        )
        self.assertNotIn("sb-chip", finnhub)

    def test_watchlist_rows_offer_the_route_into_the_portfolio(self):
        quotes = {"AAPL": quote("AAPL", 10.0, 9.0, "EUR")}
        c = cfg(watchlist=["AAPL"], symbols=["AAPL"])
        html = views.flyout(data(quotes=quotes, tab="watchlist", tabChosen=True), c, t, "en")
        self.assertIn('data-action="pick" data-value="AAPL"', html)
        self.assertIn('data-action="remove-watch"', html)

    def test_table_has_six_columns_and_one_row_per_holding(self):
        quotes = {"AAPL": quote("AAPL", 200.0, 190.0, "EUR", name="Apple Inc.")}
        c = cfg(positions=[{"symbol": "AAPL", "shares": 2.0, "buyPrice": 100.0}], symbols=["AAPL"])
        html = views.flyout(data(quotes=quotes, tabChosen=True), c, t, "en")
        self.assertEqual(html.count("<th "), 6)
        self.assertEqual(html.count("<tr "), 1)
        self.assertIn("2 \u00d7 200.00", html)  # shares and price share one cell

    def test_tile_never_repeats_the_label_without_a_sparkline(self):
        quotes = {"AAPL": quote("AAPL", 200.0, 190.0, "EUR")}
        c = cfg(
            positions=[{"symbol": "AAPL", "shares": 1.0, "buyPrice": 0.0}],
            symbols=["AAPL"],
            tileRotate=False,
        )
        html = views.tile(data(quotes=quotes), c, t, "en")
        self.assertEqual(html.count(">portfolio<"), 1)
        self.assertIn("+10.00", html)  # the absolute day move fills the trend slot

    def test_hero_follows_the_day_trend(self):
        c = cfg(positions=[{"symbol": "AAPL", "shares": 1.0, "buyPrice": 0.0}], symbols=["AAPL"])
        up = views.flyout(
            data(quotes={"AAPL": quote("AAPL", 200.0, 190.0, "EUR")}, tabChosen=True), c, t, "en"
        )
        self.assertIn("var(--sb-success)", up)
        down = views.flyout(
            data(quotes={"AAPL": quote("AAPL", 180.0, 190.0, "EUR")}, tabChosen=True), c, t, "en"
        )
        self.assertIn("var(--sb-danger)", down)
        flat = views.flyout(data(tabChosen=True), c, t, "en")
        self.assertNotIn("--sb-accent-gradient", flat)

    def test_kpi_grid_names_the_top_mover(self):
        quotes = {
            "AAPL": quote("AAPL", 200.0, 190.0, "EUR"),
            "SAP.DE": quote("SAP.DE", 90.0, 100.0, "EUR"),
        }
        c = cfg(
            positions=[
                {"symbol": "AAPL", "shares": 2.0, "buyPrice": 100.0},
                {"symbol": "SAP.DE", "shares": 1.0, "buyPrice": 0.0},
            ],
            symbols=["AAPL", "SAP.DE"],
        )
        html = views.flyout(data(quotes=quotes, tabChosen=True), c, t, "en")
        self.assertEqual(html.count('class="sb-kpi"'), 4)
        self.assertIn("topMover \u00b7 SAP.DE", html)

    def test_search_in_progress_shows_placeholders_not_no_results(self):
        d = data(tab="manage", tabChosen=True, query="apple", results=[], searching=True)
        html = views.flyout(d, cfg(), t, "en")
        self.assertIn("sb-skeleton", html)
        self.assertNotIn("noResults", html)
        done = views.flyout(dict(d, searching=False), cfg(), t, "en")
        self.assertNotIn("sb-skeleton", done)
        self.assertIn("noResults", done)

    def test_empty_state_keeps_a_gap_between_text_and_button(self):
        html = views.flyout(data(tabChosen=True), cfg(), t, "en")
        self.assertRegex(
            html, r'sb-stack sb-center"><p class="sb-empty__text">[^<]*</p><button'
        )

    def test_long_names_are_capped_with_the_full_name_as_tooltip(self):
        long_name = "RHEINMETALL CDR (CAD HEDGED)"
        quotes = {"RHM.NE": quote("RHM.NE", 200.0, 190.0, "EUR", name=long_name)}
        c = cfg(positions=[{"symbol": "RHM.NE", "shares": 2.0, "buyPrice": 0.0}], symbols=["RHM.NE"])
        html = views.flyout(data(quotes=quotes, tabChosen=True), c, t, "en")
        self.assertIn(f'title="{long_name}"', html)
        self.assertIn("RHEINMETALL CDR (CA\u2026", html)
        self.assertNotIn(f">{long_name}<", html)

    def test_tab_labels_carry_the_counts(self):
        c = cfg(
            positions=[{"symbol": "AAPL", "shares": 1.0, "buyPrice": 0.0}],
            watchlist=["MSFT"],
            symbols=["AAPL", "MSFT"],
        )
        html = views.flyout(data(tabChosen=True), c, t, "en")
        self.assertIn("(1)", html)


class SanitizerContract(unittest.TestCase):
    """The shell drops unknown tags/attributes silently, so check them here."""

    ALLOWED_TAGS = {
        "a", "b", "br", "button", "caption", "details", "div", "form", "h1", "h2",
        "h3", "i", "input", "label", "li", "ol", "p", "section", "small", "span",
        "strong", "summary", "table", "tbody", "td", "th", "thead", "time", "tr",
        "ul",
    }
    ALLOWED_ATTRS = {
        "alt", "aria-busy", "aria-controls", "aria-current", "aria-describedby",
        "aria-disabled", "aria-expanded", "aria-haspopup", "aria-hidden",
        "aria-label", "aria-labelledby", "aria-live", "aria-modal", "aria-pressed",
        "aria-roledescription", "aria-selected", "class", "colspan", "datetime",
        "dir", "for", "headers", "hidden", "id", "lang", "placeholder", "role",
        "rowspan", "scope", "span", "style", "tabindex", "title", "type",
    }
    INPUT_ATTRS = {
        "checked", "cols", "disabled", "inputmode", "list", "max", "maxlength",
        "min", "minlength", "multiple", "name", "readonly", "required", "rows",
        "selected", "size", "step", "value",
    }

    def all_markup(self):
        quotes = {
            "AAPL": quote("AAPL", 200.0, 190.0, "USD", name="Apple Inc.", points=[1.0, 2.0]),
            "^GDAXI": quote("^GDAXI", 18000.0, 17900.0, "EUR", name="DAX"),
        }
        c = cfg(
            positions=[{"symbol": "AAPL", "shares": 2.0, "buyPrice": 100.0}],
            watchlist=["^GDAXI"],
            symbols=["AAPL", "^GDAXI"],
        )
        d = data(
            quotes=quotes,
            fx={"EUR": 1.0, "USD": 0.9},
            history=[100.0, 120.0],
            results=[{"symbol": "MSFT", "name": "Microsoft", "kind": "EQUITY", "exchange": "NASDAQ"}],
            query="micro",
            positionOk="done",
        )
        pieces = [views.tile(d, c, t, "en"), views.hover(d, c, t, "en")]
        pieces += [views.flyout(dict(d, tab=tab), c, t, "en") for tab in views.TABS]
        pieces.append(views.flyout(dict(d, tab="manage", searching=True), c, t, "en"))
        pieces.append(views.alert_popup("AAPL", 3.0, 1.0, 2.0, "USD", t, "en"))
        return pieces

    def test_only_allowed_tags_and_attributes(self):
        tag_pattern = re.compile(r"<\s*([a-zA-Z0-9]+)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")
        attr_pattern = re.compile(r"([a-zA-Z-]+)\s*=")
        for html in self.all_markup():
            for tag, attrs in tag_pattern.findall(html):
                self.assertIn(tag.lower(), self.ALLOWED_TAGS, f"<{tag}> in {html[:80]}")
                for attr in attr_pattern.findall(attrs):
                    name = attr.lower()
                    if name.startswith("data-"):
                        self.assertRegex(name, r"^data-[a-z0-9-]+$")
                        continue
                    allowed = self.ALLOWED_ATTRS | (
                        self.INPUT_ATTRS if tag.lower() in ("input", "button") else set()
                    )
                    self.assertIn(name, allowed, f"{name} on <{tag}>")

    def test_inline_styles_carry_only_data_values(self):
        for html in self.all_markup():
            for style in re.findall(r'style="([^"]*)"', html):
                self.assertRegex(
                    style.strip(),
                    r"^(max-width: [\d.]+rem|--sb-[a-z-]+: [^;]+(; --sb-[a-z-]+: [^;]+)*)$",
                )

    def test_no_script_or_event_handlers(self):
        for html in self.all_markup():
            self.assertNotIn("<script", html.lower())
            self.assertNotRegex(html, r"\son[a-z]+\s*=")

    def test_every_button_has_an_explicit_type(self):
        for html in self.all_markup():
            for button in re.findall(r"<button[^>]*>", html):
                self.assertIn("type=", button)

    def test_tags_are_balanced(self):
        opening = re.compile(r"<([a-zA-Z0-9]+)(?:\s[^>]*)?>")
        closing = re.compile(r"</([a-zA-Z0-9]+)>")
        void = {"input", "br", "hr", "img"}
        for html in self.all_markup():
            stack = []
            for match in re.finditer(r"</?[a-zA-Z0-9]+(?:\s[^>]*)?>", html):
                token = match.group(0)
                close = closing.fullmatch(token)
                if close:
                    self.assertTrue(stack, f"stray {token}")
                    self.assertEqual(stack.pop(), close.group(1).lower())
                    continue
                name = opening.fullmatch(token).group(1).lower()
                if name not in void:
                    stack.append(name)
            self.assertEqual(stack, [], f"unclosed: {stack}")


class UsedClassesExist(unittest.TestCase):
    """Unknown sb-* classes are design failures, so pin them to the kit."""

    KNOWN = {
        "sb-accent", "sb-active", "sb-alert", "sb-alert--danger", "sb-alert--info",
        "sb-alert--ok", "sb-alert--warn", "sb-alert__icon", "sb-alert__text",
        "sb-alert__title", "sb-avatar", "sb-avatar--sm", "sb-badge", "sb-badge-danger",
        "sb-badge-success",
        "sb-badge-warning", "sb-btn", "sb-btn-ghost", "sb-btn-icon",
        "sb-btn-primary", "sb-card", "sb-card--accent", "sb-card__body", "sb-center",
        "sb-chip", "sb-cluster",
        "sb-collapsible",
        "sb-collapsible__body", "sb-crit", "sb-dim", "sb-empty", "sb-empty__icon",
        "sb-empty__text", "sb-empty__title", "sb-error", "sb-faint", "sb-field",
        "sb-field-stack", "sb-field__hint", "sb-field__label", "sb-header",
        "sb-header-actions", "sb-hero", "sb-icon-badge", "sb-inline", "sb-input",
        "sb-kpi", "sb-kpi-grid", "sb-kpi-label", "sb-kpi-value", "sb-list",
        "sb-meta", "sb-mono", "sb-muted", "sb-ok", "sb-push", "sb-reveal",
        "sb-row", "sb-section", "sb-skeleton", "sb-spark", "sb-spinner", "sb-sr-only",
        "sb-split", "sb-stack", "sb-stat__delta", "sb-stat__delta--down",
        "sb-stat__delta--up", "sb-stepper", "sb-stepper__label", "sb-stepper__marker",
        "sb-stepper__step",
        "sb-tab", "sb-table", "sb-table--hover", "sb-table-wrap", "sb-table__num",
        "sb-table__person",
        "sb-table__sort", "sb-tabs", "sb-tile", "sb-tile-seg", "sb-tile-split",
        "sb-tile-stack", "sb-tip", "sb-title", "sb-warn",
    }

    def test_no_invented_classes(self):
        markup = SanitizerContract().all_markup()
        for html in markup:
            for group in re.findall(r'class="([^"]*)"', html):
                for name in group.split():
                    if name.startswith("sb-"):
                        self.assertIn(name, self.KNOWN, name)


if __name__ == "__main__":
    unittest.main()

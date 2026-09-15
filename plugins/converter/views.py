"""Markup for the converter: semantic HTML on the smabar UI kit.

Every function returns a string the plugin pushes with app.render. Nothing
here touches the SDK, so this module renders in a test without a running bar.
The models are plain dicts the plugin assembles; their keys are named in the
docstrings of currency_panel and units_panel.
"""

from collections.abc import Callable
from html import escape

import units

Translator = Callable[[str], str]
NO_VALUE = "–"
TABS = ("currency", "units")
# The tile's own glyph (Lucide arrow-right-left), rendered in every tile state.
GLYPH = ('<svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" stroke-width="2"'
         ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
         '<path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/></svg>')


def tr(t: Translator, key: str, **values: object) -> str:
    """t() with placeholders: tr(t, "convert.rateLine", src="EUR", ...)."""
    text = t(key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def icon(name: str) -> str:
    return f'<span data-lucide="{name}" aria-hidden="true"></span>'


def button(name: str, label: str, *, value: str | None = None, primary: bool = False,
           symbol: str = "", icon_only: bool = False, submit: bool = False) -> str:
    """A data-action button. Without `value` the click delivers every data-field
    of the surface as a dict. Icon-only buttons carry aria-label AND title: the
    shell turns title into its themed tooltip, so the control has a name."""
    classes = "sb-btn sb-btn-primary" if primary else "sb-btn sb-btn-ghost"
    if icon_only:
        classes += " sb-btn-icon"
    attrs = f' data-value="{escape(value, quote=True)}"' if value is not None else ""
    if icon_only:
        attrs += f' aria-label="{escape(label, quote=True)}" title="{escape(label, quote=True)}"'
    content = (icon(symbol) if symbol else "") + ("" if icon_only else escape(label))
    kind = "submit" if submit else "button"
    return f'<button type="{kind}" class="{classes}" data-action="{escape(name)}"{attrs}>{content}</button>'


def amount_text(amount: float) -> str:
    """The amount as the number input shows it: no float noise, no exponent."""
    return f"{amount:.10f}".rstrip("0").rstrip(".") or "0"


def amount_field(field: str, amount: float, invalid: bool, t: Translator) -> str:
    flag = ' aria-invalid="true"' if invalid else ""
    return (
        f'<div class="sb-field-stack"><label class="sb-field__label" for="{field}">{escape(t("convert.amount"))}</label>'
        f'<input id="{field}" class="sb-input" type="number" inputmode="decimal" step="any" min="0"'
        f' data-field="{field}" value="{amount_text(amount)}"'
        f' placeholder="{escape(t("convert.amountPlaceholder"), quote=True)}" aria-describedby="{field}-error"{flag}>'
        f'<p class="sb-field__error" id="{field}-error">{escape(t("convert.amountInvalid"))}</p></div>'
    )


def select(field: str, label: str, options: list[tuple[str, str]], chosen: str) -> str:
    rows = "".join(
        f'<option value="{escape(value, quote=True)}"{" selected" if value == chosen else ""}>{escape(text)}</option>'
        for value, text in options
    )
    return (
        f'<div class="sb-field-stack"><label class="sb-field__label" for="{field}">{escape(label)}</label>'
        f'<select id="{field}" class="sb-select" data-field="{field}">{rows}</select></div>'
    )


def actions(convert_action: str, swap_action: str, t: Translator) -> str:
    return ('<div class="sb-cluster">'
            + button(convert_action, t("convert.convert"), primary=True, submit=True)
            + button(swap_action, t("convert.swap"), symbol="repeat", icon_only=True)
            + "</div>")


def result(value: float | None, unit: str, line: str, cached: bool, decimals: int, t: Translator) -> str:
    """The big result with its rate line; a missing value keeps the block's shape."""
    shown = units.fmt(value, decimals) if value is not None else NO_VALUE
    marker = f' <span class="sb-faint">· {escape(t("convert.cached"))}</span>' if cached and line else ""
    return (f'<div class="sb-card"><p class="sb-text-xl">{escape(shown)} <span class="sb-muted">{escape(unit)}</span></p>'
            f'<p class="sb-meta">{escape(line or NO_VALUE)}{marker}</p></div>')


def currency_panel(model: dict, decimals: int, active: bool, t: Translator) -> str:
    """model: amount, src, dst, options [(code, label)], rate | None, value | None,
    date, available (a table exists), cached (the last download failed), invalid."""
    alert = "" if model["available"] else (
        f'<div class="sb-alert sb-alert--warn" role="alert"><span class="sb-alert__icon">{icon("wifi-off")}</span>'
        f'<div><p class="sb-alert__title">{escape(t("convert.ratesUnavailable"))}</p>'
        f'<p class="sb-alert__text">{escape(t("convert.ratesUnavailableHint"))}</p></div></div>'
    )
    form = (
        '<form class="sb-stack">'
        + amount_field("cv-amount", model["amount"], model["invalid"], t)
        + select("cv-from", t("convert.from"), model["options"], model["src"])
        + select("cv-to", t("convert.to"), model["options"], model["dst"])
        + actions("convert-currency", "swap-currency", t)
        + "</form>"
    )
    line = ""
    if model["rate"] is not None:
        line = tr(t, "convert.rateLine", src=model["src"], rate=units.fmt(model["rate"], max(decimals, 4)),
                  dst=model["dst"], date=model["date"])
    body = alert + form + result(model["value"], model["dst"], line, model["cached"], decimals, t)
    return f'<div data-tab-panel="currency"{"" if active else " hidden"}>{body}</div>'


def category_chips(current: str, t: Translator) -> str:
    chips = "".join(
        f'<button type="button" class="sb-chip{" is-selected" if name == current else ""}"'
        f' aria-pressed="{str(name == current).lower()}" data-action="category:{name}">'
        f'{escape(t("convert.cat." + name))}</button>'
        for name in units.CATEGORY_ORDER
    )
    return f'<div class="sb-cluster" role="group" aria-label="{escape(t("convert.category"), quote=True)}">{chips}</div>'


def units_panel(model: dict, decimals: int, active: bool, t: Translator) -> str:
    """model: category, amount, src, dst, value, line, invalid."""
    options = [(unit, f"{unit} · {t('convert.unit.' + units.slug(unit))}") for unit in units.units_of(model["category"])]
    form = (
        '<form class="sb-stack">'
        + category_chips(model["category"], t)
        + amount_field("un-amount", model["amount"], model["invalid"], t)
        + select("un-from", t("convert.from"), options, model["src"])
        + select("un-to", t("convert.to"), options, model["dst"])
        + actions("convert-units", "swap-units", t)
        + "</form>"
    )
    body = form + result(model["value"], model["dst"], model["line"], False, decimals, t)
    return f'<div data-tab-panel="units"{"" if active else " hidden"}>{body}</div>'


def flyout(tab: str, currency: dict, unit: dict, decimals: int, t: Translator) -> str:
    header = (
        f'<div class="sb-header"><span class="sb-icon-badge">{icon("repeat")}</span>'
        f'<div><h2 class="sb-title">{escape(t("convert.title"))}</h2><p class="sb-meta">{escape(t("convert.source"))}</p></div>'
        f'<div class="sb-header-actions">{button("refresh", t("convert.refresh"), symbol="refresh-cw", icon_only=True)}</div></div>'
    )
    tabs = "".join(
        f'<button type="button" class="sb-tab{" sb-active" if name == tab else ""}" data-tab="{name}"'
        f' data-action="tab" data-value="{name}">{escape(t("convert.tab." + name))}</button>'
        for name in TABS
    )
    return (header + f'<div data-tabs><div class="sb-tabs">{tabs}</div>'
            + currency_panel(currency, decimals, tab == "currency", t)
            + units_panel(unit, decimals, tab == "units", t) + "</div>")


def summary(last: str, currency: dict, unit: dict, decimals: int) -> str:
    """One line for the hover: the most recent conversion, or nothing."""
    model = {"currency": currency, "units": unit}.get(last)
    if model is None or model["value"] is None:
        return ""
    return f'{amount_text(model["amount"])} {model["src"]} = {units.fmt(model["value"], decimals)} {model["dst"]}'


def hover(text: str, t: Translator) -> str:
    return f'<div class="sb-row">{icon("repeat")}<span>{escape(text or t("convert.hoverEmpty"))}</span></div>'


def tile(pair: tuple[str, str], rate: float | None, change: tuple[float, str] | None, date: str, t: Translator) -> str:
    """Basic cover: the glyph, the favourite pair, its rate and yesterday's
    direction. Every state keeps this shape."""
    label = f"{pair[0]}/{pair[1]}"
    if rate is None:
        return (f'<div class="sb-tile" title="{escape(t("convert.ratesUnavailable"), quote=True)}">{GLYPH}'
                f'<span class="sb-muted">{label}</span><span>{NO_VALUE}</span></div>')
    shown = units.fmt(rate, 4)
    title = tr(t, "convert.tileTitle", pair=label, rate=shown, date=date)
    arrow = ""
    if change is not None and change[0] != 0:
        up = change[0] > 0
        arrow = (f'<small class="{"sb-ok" if up else "sb-crit"}">'
                 f'<span data-lucide="{"arrow-up" if up else "arrow-down"}" aria-hidden="true"></span></small>')
        title += " · " + tr(t, "convert.tileChange", change=f"{change[0]:+.2f}", date=change[1])
    return (f'<div class="sb-tile" title="{escape(title, quote=True)}">{GLYPH}'
            f'<span class="sb-muted">{label}</span><span>{shown}</span>{arrow}</div>')

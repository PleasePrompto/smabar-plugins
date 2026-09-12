"""Every section of the kitshow flyout, as plain HTML strings.

Split out of plugin.py so the runtime logic stays readable: this module has
no smabar_sdk import and no state, it is pure markup.

Ground rules followed throughout (see ui_kit / sanitizeRules.ts):
  * no `style=` for spacing, size or colour — only data values and the
    documented `--sb-*` tokens;
  * no `type=` on <button> (the sanitizer only keeps it on <input>);
  * no aria-pressed / aria-haspopup / datetime / autofocus / inputmode /
    optgroup[label] — they are not on the allow list and would be stripped
    and logged;
  * no [data-action] inside a <form> (a button in a form is a submit
    button, and the submit is routed into the action pipeline as well).
"""

import html
import json
import re

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def esc(text: object) -> str:
    return html.escape(str(text))


def ctx(items: list[dict]) -> str:
    """A data-context-items attribute, JSON-escaped for a double-quoted slot."""
    return f'data-context-items="{html.escape(json.dumps(items), quote=True)}"'


def icon(name: str) -> str:
    return f'<span data-lucide="{name}" aria-hidden="true"></span>'


def label(text: str) -> str:
    return f'<div class="sb-section">{esc(text)}</div>'


# --------------------------------------------------------------------------
# 1 — the bar tile
# --------------------------------------------------------------------------

TILE = f"""
<p class="sb-dim">What a tile shows in the bar: one line, hugging its own
content. Everything else belongs in this flyout.</p>
{label("sb-tile · data-badge")}
<div class="sb-card">
  <div class="sb-cluster">
    <span class="sb-tile">{icon("cloud-sun")}21°</span>
    <span class="sb-tile" data-badge="3">{icon("bell")}Inbox</span>
    <span class="sb-tile" data-badge="">{icon("wifi")}Wi-Fi</span>
  </div>
</div>
{label("sb-tile-stack · two lines")}
<div class="sb-card sb-center">
  <span class="sb-tile"><span class="sb-tile-stack">
    <span class="sb-mono">09:41</span><span>Mon, 23 Aug</span>
  </span></span>
</div>
{label("data-marquee · scrolls only while it overflows")}
<div class="sb-card">
  <span data-marquee style="max-width: 9rem">A status line far too long for
  the tile it has to live in</span>
</div>
{label("data-rotator · several values, one footprint")}
<div class="sb-card sb-center">
  <span data-rotator="up" data-rotator-interval="2500">
    <span class="sb-inline">{icon("bitcoin")}<span class="sb-mono">$109,412</span></span>
    <span class="sb-inline">{icon("cpu")}<span class="sb-mono">38 %</span></span>
    <span class="sb-inline">{icon("thermometer")}<span class="sb-mono">21 °C</span></span>
  </span>
</div>
{label("data-clock · the shell keeps time, not the plugin")}
<div class="sb-card sb-center">
  <div data-clock="Europe/Berlin"></div>
  <div class="sb-mono sb-text-xl"><span data-clock-text="Europe/Berlin"></span></div>
  <div class="sb-dim">Berlin ·
    <span data-clock-text="Europe/Berlin" data-clock-format="weekday"></span> ·
    <span data-clock-text="Europe/Berlin" data-clock-format="offset"></span>
  </div>
</div>
"""

# --------------------------------------------------------------------------
# 2 — type
# --------------------------------------------------------------------------

TYPE = f"""
{label("size steps")}
<div class="sb-card sb-tight">
  <div class="sb-text-hero">sb-text-hero</div>
  <div class="sb-text-xl">sb-text-xl</div>
  <div class="sb-text-l">sb-text-l</div>
  <div class="sb-text-m">sb-text-m</div>
  <div class="sb-text-s">sb-text-s</div>
  <div class="sb-text-xs">sb-text-xs</div>
</div>
{label("emphasis steps")}
<div class="sb-card sb-tight">
  <div>plain body text</div>
  <div class="sb-dim">sb-dim</div>
  <div class="sb-muted">sb-muted</div>
  <div class="sb-faint">sb-faint</div>
  <div class="sb-mono">sb-mono 0123456789</div>
</div>
{label("status colours")}
<div class="sb-cluster">
  <span class="sb-ok">{icon("circle-check")} sb-ok</span>
  <span class="sb-warn">{icon("triangle-alert")} sb-warn</span>
  <span class="sb-crit">{icon("circle-x")} sb-crit</span>
</div>
<p class="sb-error">sb-error — the inline message under a field.</p>
<p class="sb-meta">sb-meta — the quiet “updated 2 minutes ago” line.</p>
{label("sb-display")}
<h2 class="sb-display">Display</h2>
{label("sb-prose")}
<article class="sb-prose">
  <h3>A heading</h3>
  <p>Plain children get styled: <strong>strong</strong>, <em>em</em>,
    <code>inline code</code>, <mark>mark</mark>,
    <abbr title="Cascading Style Sheets">CSS</abbr>, H<sub>2</sub>O,
    x<sup>2</sup>, <s>struck</s>, <u>underlined</u>,
    <var>x</var>, <samp>output</samp> and
    <a href="https://lucide.dev/icons/">a link</a> that opens in the
    system browser.</p>
  <blockquote>A quoted thought.</blockquote>
  <pre><code>app.render("kit", "flyout", html)</code></pre>
</article>
{label("sb-quote")}
<figure class="sb-quote">
  <blockquote class="sb-quote__text">Everything is a plugin.</blockquote>
  <figcaption class="sb-quote__cite">smabar — the motto</figcaption>
</figure>
<figure class="sb-quote sb-quote--center sb-quote--plain">
  <blockquote class="sb-quote__text">…and the plain, centred variant.</blockquote>
  <figcaption class="sb-quote__cite">sb-quote--center sb-quote--plain</figcaption>
</figure>
{label("sb-kbd")}
<div class="sb-cluster">
  <span class="sb-kbd">Ctrl</span><span class="sb-faint">+</span>
  <span class="sb-kbd">K</span>
  <kbd class="sb-kbd">Esc</kbd>
  <kbd class="sb-kbd">Super</kbd>
</div>
{label("headings h1–h6 all survive the sanitizer")}
<div class="sb-card sb-tight">
  <h4>h4 — a sub-heading</h4>
  <h5>h5 — a smaller one</h5>
  <h6>h6 — the smallest</h6>
</div>
"""

# --------------------------------------------------------------------------
# 3 — buttons
# --------------------------------------------------------------------------

BUTTONS = f"""
{label("smabar buttons")}
<div class="sb-cluster">
  <button class="sb-btn">sb-btn</button>
  <button class="sb-btn sb-btn-primary">primary</button>
  <button class="sb-btn sb-btn-ghost">ghost</button>
  <button class="sb-btn sb-btn-danger">danger</button>
  <button class="sb-btn sb-btn-icon" aria-label="Refresh" title="sb-btn-icon">{icon("refresh-cw")}</button>
  <button class="sb-btn" disabled>disabled</button>
</div>
{label("harvested variants")}
<div class="sb-cluster">
  <button class="sb-btn sb-btn--outline">--outline</button>
  <button class="sb-btn sb-btn--soft">--soft</button>
  <button class="sb-btn sb-btn--sm">--sm</button>
  <button class="sb-btn sb-btn--lg">--lg</button>
  <button class="sb-btn sb-btn--primary">--primary</button>
  <button class="sb-btn sb-btn--danger">--danger</button>
  <button class="sb-btn sb-btn--ghost">--ghost</button>
  <button class="sb-btn sb-btn--icon" aria-label="Settings" title="sb-btn--icon">{icon("settings")}</button>
</div>
{label("sb-btn-group")}
<div class="sb-btn-group" role="group" aria-label="Time range">
  <button class="sb-btn is-active">Day</button>
  <button class="sb-btn">Week</button>
  <button class="sb-btn">Month</button>
</div>
{label("sb-chip · sb-close")}
<div class="sb-cluster">
  <button class="sb-chip is-selected">Design</button>
  <button class="sb-chip">Engineering<span class="sb-chip__close" aria-hidden="true">×</span></button>
  <button class="sb-close" aria-label="Close" title="sb-close">{icon("x")}</button>
  <button class="sb-close sb-close--morph" aria-expanded="false" aria-label="Expand"
          title="sb-close--morph — the icon is built from aria-expanded"></button>
</div>
{label("sb-choice-grid · sb-active marks the selection")}
<div class="sb-choice-grid">
  <button class="sb-choice sb-active">{icon("sun")}Light</button>
  <button class="sb-choice">{icon("moon")}Dark</button>
  <button class="sb-choice">{icon("monitor")}Auto</button>
</div>
{label("sb-tabs · switched by the shell, no round trip")}
<div data-tabs>
  <div class="sb-tabs">
    <button class="sb-tab sb-active" data-tab="now">Now</button>
    <button class="sb-tab" data-tab="week">Week</button>
    <button class="sb-tab" data-tab="year">Year</button>
  </div>
  <div class="sb-tabs__panel" data-tab-panel="now"><div class="sb-card">Panel “Now”.</div></div>
  <div class="sb-tabs__panel" data-tab-panel="week"><div class="sb-card">Panel “Week”.</div></div>
  <div class="sb-tabs__panel" data-tab-panel="year"><div class="sb-card">Panel “Year”.</div></div>
</div>
"""

# --------------------------------------------------------------------------
# 4 — forms
# --------------------------------------------------------------------------

FORMS = f"""
<p class="sb-dim">Everything below is a real control: what you type here is
sent to the plugin when you press the button at the end.</p>
{label("sb-field · input + button on one line")}
<div class="sb-field">
  <input class="sb-input" data-field="query" id="kit-query" placeholder="City or country">
  <button class="sb-btn" data-action="echo" title="Sends every field to the plugin">Send</button>
</div>
<form>
  {label("label + hint + error")}
  <div class="sb-field-stack">
    <label class="sb-field__label" for="kit-mail">Email</label>
    <input class="sb-input" id="kit-mail" data-field="mail" type="email"
           placeholder="you@example.com" required>
    <p class="sb-field__hint">sb-field__hint — supporting text under the field.</p>
    <p class="sb-error">sb-error — and this is how a problem reads.</p>
  </div>
  {label("sb-textarea")}
  <textarea class="sb-textarea" data-field="note" rows="2"
            placeholder="sb-textarea — resizable"></textarea>
  {label("sb-select · enhanced by default · native opt-out")}
  <div class="sb-grid" style="--sb-grid-cols:2">
    <div class="sb-field-stack">
      <label class="sb-field__label" for="kit-plan">Enhanced</label>
      <select class="sb-select" id="kit-plan" data-field="plan">
        <option>Free</option><option selected>Pro</option><option>Team</option>
      </select>
    </div>
    <div class="sb-field-stack">
      <label class="sb-field__label" for="kit-native-plan">Native fallback</label>
      <select class="sb-select" id="kit-native-plan" data-field="native-plan" data-sb-native>
        <option>Free</option><option selected>Pro</option><option>Team</option>
      </select>
    </div>
  </div>
  {label("sb-input-group")}
  <div class="sb-input-group">
    <span class="sb-input-group__addon">https://</span>
    <input class="sb-input" data-field="site" aria-label="Website" placeholder="example.com">
  </div>
  {label("sb-combobox · native datalist")}
  <div class="sb-combobox-field">
    <input class="sb-input sb-combobox" data-field="lang" list="kit-langs"
           placeholder="Type or pick…" aria-label="Language">
    <datalist id="kit-langs">
      <option value="Rust"></option><option value="Python"></option>
      <option value="TypeScript"></option>
    </datalist>
  </div>
  {label("sb-check · sb-radio-group · sb-switch · sb-toggle")}
  <label class="sb-check"><input type="checkbox" data-field="updates" checked> sb-check (checkbox)</label>
  <label class="sb-check"><input type="checkbox" disabled> disabled</label>
  <fieldset class="sb-radio-group">
    <legend>sb-radio-group</legend>
    <label class="sb-check"><input type="radio" name="kit-cycle" checked> Monthly</label>
    <label class="sb-check"><input type="radio" name="kit-cycle"> Yearly</label>
  </fieldset>
  <fieldset class="sb-radio-group sb-radio-group--inline">
    <legend>sb-radio-group--inline</legend>
    <label class="sb-check"><input type="radio" name="kit-edge" checked> Top</label>
    <label class="sb-check"><input type="radio" name="kit-edge"> Bottom</label>
  </fieldset>
  <label class="sb-switch"><input type="checkbox" role="switch" data-field="notify" checked> sb-switch</label>
  <div class="sb-row">
    <label for="kit-dark">sb-toggle (smabar's own)</label>
    <input class="sb-toggle sb-push" type="checkbox" id="kit-dark" data-field="dark" checked>
  </div>
  {label("sb-range")}
  <div class="sb-range-wrap" style="--sb-range-pct: 0.4">
    <output class="sb-range-wrap__bubble" aria-hidden="true">40 %</output>
    <input class="sb-range" type="range" min="0" max="100" value="40"
           data-field="level" aria-label="Level">
    <div class="sb-range-wrap__labels" aria-hidden="true"><span>0</span><span>100</span></div>
  </div>
  {label("more input types")}
  <div class="sb-grid" style="--sb-grid-cols:2">
    <input class="sb-input" type="date" data-field="day" aria-label="Date">
    <input class="sb-input" type="time" data-field="hour" aria-label="Time">
    <input class="sb-input" type="number" data-field="count" value="3" min="0" max="9" aria-label="Count">
    <input class="sb-input" type="search" data-field="find" placeholder="search" aria-label="Search">
    <input class="sb-input" type="password" data-field="secret" value="hunter2" aria-label="Password">
    <input class="sb-input" type="color" data-field="tint" value="#a78bfa" aria-label="Colour">
  </div>
</form>
<button class="sb-btn sb-btn-primary" data-action="echo">Send every field to the plugin</button>
<div class="sb-tip">{icon("info")}<span>The button sits <em>outside</em> the
  &lt;form&gt;: the sanitizer strips <code>type</code> from a button, so any
  button inside a form is a submit button.</span></div>
"""

# --------------------------------------------------------------------------
# 5 — data display
# --------------------------------------------------------------------------

DATA = f"""
{label("sb-kpi-grid")}
<div class="sb-kpi-grid">
  <div class="sb-kpi"><span class="sb-kpi-value">38 %</span><span class="sb-kpi-label">CPU</span></div>
  <div class="sb-kpi"><span class="sb-kpi-value">6.4 GB</span><span class="sb-kpi-label">RAM</span></div>
</div>
{label("sb-stat")}
<div class="sb-card">
  <div class="sb-stat">
    <span class="sb-stat__value">2,481</span>
    <span class="sb-stat__label">Active users</span>
    <span class="sb-stat__delta sb-stat__delta--up">↑ 12.4 %</span>
  </div>
  <div class="sb-stat sb-stat--center">
    <span class="sb-stat__value">38</span>
    <span class="sb-stat__label">Plugins</span>
    <span class="sb-stat__delta sb-stat__delta--down">↓ 2</span>
  </div>
</div>
{label("sb-badge — smabar naming")}
<div class="sb-cluster">
  <span class="sb-badge">neutral</span>
  <span class="sb-badge sb-badge-success">+2.4 %</span>
  <span class="sb-badge sb-badge-warning">low</span>
  <span class="sb-badge sb-badge-danger">−1.8 %</span>
  <span class="sb-badge sb-badge-info">new</span>
  <span class="sb-badge sb-badge-accent">pro</span>
</div>
{label("sb-badge — harvested naming")}
<div class="sb-cluster">
  <span class="sb-badge sb-badge--ok">--ok</span>
  <span class="sb-badge sb-badge--warn">--warn</span>
  <span class="sb-badge sb-badge--danger">--danger</span>
  <span class="sb-badge sb-badge--info">--info</span>
  <span class="sb-badge sb-badge--accent">--accent</span>
</div>
{label("sb-avatar")}
<div class="sb-cluster">
  <span class="sb-avatar sb-avatar--sm" role="img" aria-label="Ada Lovelace">AL</span>
  <span class="sb-avatar" role="img" aria-label="Grace Hopper">GH</span>
  <span class="sb-avatar sb-avatar--lg" role="img" aria-label="Alan Turing">AT</span>
  <span class="sb-avatar-group">
    <span class="sb-avatar sb-avatar--sm" role="img" aria-label="Ada Lovelace">AL</span>
    <span class="sb-avatar sb-avatar--sm" role="img" aria-label="Grace Hopper">GH</span>
    <span class="sb-avatar sb-avatar--sm" role="img" aria-label="Alan Turing">AT</span>
  </span>
</div>
{label("sb-indicator")}
<div class="sb-cluster">
  <span class="sb-indicator">
    <button class="sb-btn sb-btn-icon" aria-label="Notifications, 3 unread">{icon("bell")}</button>
    <span class="sb-indicator__count" aria-hidden="true">3</span>
  </span>
  <span class="sb-indicator sb-indicator--ok sb-indicator--ring">
    <span class="sb-avatar" role="img" aria-label="Online">ON</span>
    <span class="sb-indicator__dot" aria-hidden="true"></span>
  </span>
  <span class="sb-indicator sb-indicator--danger sb-indicator--bottom">
    <button class="sb-btn sb-btn-icon" aria-label="Errors">{icon("bug")}</button>
    <span class="sb-indicator__count" aria-hidden="true">12</span>
  </span>
  <span class="sb-indicator sb-indicator--warn">
    <button class="sb-btn sb-btn-icon" aria-label="Warnings">{icon("triangle-alert")}</button>
    <span class="sb-indicator__dot" aria-hidden="true"></span>
  </span>
  <span class="sb-indicator sb-indicator--info">
    <span class="sb-badge">info</span>
    <span class="sb-indicator__dot" aria-hidden="true"></span>
  </span>
</div>
{label("sb-table · --hover --striped --sticky")}
<div class="sb-table-wrap" role="region" aria-label="Latest deployments" tabindex="0">
  <table class="sb-table sb-table--hover sb-table--striped sb-table--sticky">
    <caption class="sb-muted">Latest deployments</caption>
    <colgroup><col><col><col></colgroup>
    <thead><tr>
      <th scope="col">Owner</th><th scope="col">Status</th>
      <th scope="col" class="sb-table__num">Time</th>
    </tr></thead>
    <tbody>
      <tr>
        <td><span class="sb-table__person"><span class="sb-avatar sb-avatar--sm" role="img" aria-label="Ada Lovelace">AL</span>Ada</span></td>
        <td><span class="sb-badge sb-badge--ok">passing</span></td>
        <td class="sb-table__num">2m 14s</td>
      </tr>
      <tr>
        <td><span class="sb-table__person"><span class="sb-avatar sb-avatar--sm" role="img" aria-label="Grace Hopper">GH</span>Grace</span></td>
        <td><span class="sb-badge sb-badge--danger">failed</span></td>
        <td class="sb-table__num">38s</td>
      </tr>
      <tr>
        <td><span class="sb-table__person"><span class="sb-avatar sb-avatar--sm" role="img" aria-label="Alan Turing">AT</span>Alan</span></td>
        <td><span class="sb-badge sb-badge--warn">queued</span></td>
        <td class="sb-table__num">—</td>
      </tr>
    </tbody>
    <tfoot><tr><td colspan="2">Total</td><td class="sb-table__num">2m 52s</td></tr></tfoot>
  </table>
</div>
{label("sb-table--editable · --spotlight")}
<div class="sb-table-wrap">
  <table class="sb-table sb-table--editable sb-table--spotlight">
    <tbody>
      <tr><th scope="row">Name</th><td><input class="sb-table__input" data-field="row-name" value="clock"></td></tr>
      <tr><th scope="row">Interval</th><td><input class="sb-table__input" data-field="row-interval" value="1000"></td></tr>
    </tbody>
  </table>
</div>
"""

# --------------------------------------------------------------------------
# 6 — charts
# --------------------------------------------------------------------------

CHARTS = f"""
{label('data-chart="donut"')}
<div class="sb-cluster">
  <div class="sb-gauge" data-chart="donut" data-value="62" role="img"
       aria-label="Storage used: 62 percent"><span class="sb-mono">62 %</span></div>
  <div class="sb-gauge" data-chart="donut" data-value="7" data-max="10" role="img"
       aria-label="Tasks complete: 7 of 10"><span class="sb-mono">7/10</span></div>
</div>
{label('data-chart="sparkline"')}
<div class="sb-spark" data-chart="sparkline" data-points="3,5,4,8,6,9,7,11,8,12,9"
     role="img" aria-label="Requests over 11 hours, ranging from 3 to 12 thousand"></div>
{label("sb-chart-bars · shared zero axis, grid and unit")}
<div class="sb-chart-bars" role="img"
     aria-label="Deploys per day: Monday 14, Tuesday 9, Wednesday 17, Thursday 12, Friday 20"
     style="--sb-chart-max:20" data-grid data-axis data-unit="deploys">
  <div class="sb-chart-bars__item" style="--sb-chart-value:14">
    <span class="sb-chart-bars__bar"><span class="sb-chart-bars__value">14</span></span>
    <span class="sb-chart-bars__label">Mon</span>
  </div>
  <div class="sb-chart-bars__item" style="--sb-chart-value:9">
    <span class="sb-chart-bars__bar"><span class="sb-chart-bars__value">9</span></span>
    <span class="sb-chart-bars__label">Tue</span>
  </div>
  <div class="sb-chart-bars__item sb-chart-bars__item--accent" style="--sb-chart-value:17">
    <span class="sb-chart-bars__bar"><span class="sb-chart-bars__value">17</span></span>
    <span class="sb-chart-bars__label">Wed</span>
  </div>
  <div class="sb-chart-bars__item" style="--sb-chart-value:12">
    <span class="sb-chart-bars__bar"><span class="sb-chart-bars__value">12</span></span>
    <span class="sb-chart-bars__label">Thu</span>
  </div>
  <div class="sb-chart-bars__item" style="--sb-chart-value:20">
    <span class="sb-chart-bars__bar"><span class="sb-chart-bars__value">20</span></span>
    <span class="sb-chart-bars__label">Fri</span>
  </div>
</div>
{label("sb-chart-donut · labelled series and legend")}
<div class="sb-inline">
  <div class="sb-chart-donut" role="img"
       aria-label="Storage: Documents 38 percent, Media 27 percent, Apps 21 percent, Free 14 percent"
       style="--sb-chart-v1:38;--sb-chart-v2:27;--sb-chart-v3:21">
    <span class="sb-chart-donut__label">
      <span class="sb-chart-donut__value">86 %</span>
      <span class="sb-chart-donut__caption">used</span>
    </span>
  </div>
  <ul class="sb-chart-legend">
    <li class="sb-chart-legend__item">Documents <span class="sb-chart-legend__value">38 %</span></li>
    <li class="sb-chart-legend__item" style="--sb-chart-color:var(--sb-chart-2)">Media <span class="sb-chart-legend__value">27 %</span></li>
    <li class="sb-chart-legend__item" style="--sb-chart-color:var(--sb-chart-3)">Apps <span class="sb-chart-legend__value">21 %</span></li>
  </ul>
</div>
{label("sb-chart-rows · explicit values and units")}
<div class="sb-chart-rows" role="img"
     aria-label="Requests by region: Frankfurt 412 thousand, Virginia 268 thousand, Singapore 193 thousand"
     style="--sb-chart-max:450">
  <span class="sb-chart-rows__label">Frankfurt</span>
  <span class="sb-chart-rows__bar sb-chart-rows__bar--accent" style="--sb-chart-value:412"></span>
  <span class="sb-chart-rows__value">412k</span>
  <span class="sb-chart-rows__label">Virginia</span>
  <span class="sb-chart-rows__bar" style="--sb-chart-value:268"></span>
  <span class="sb-chart-rows__value">268k</span>
  <span class="sb-chart-rows__label">Singapore</span>
  <span class="sb-chart-rows__bar" style="--sb-chart-value:193"></span>
  <span class="sb-chart-rows__value">193k</span>
</div>
{label("chart states · loading and no data")}
<div class="sb-chart-bars is-loading" aria-busy="true" role="status"
     aria-label="Loading chart" style="--sb-chart-max:100">
  <span class="sb-chart-bars__item" style="--sb-chart-value:72">
    <span class="sb-chart-bars__bar sb-skeleton"></span>
    <span class="sb-chart-bars__label">Loading</span>
  </span>
  <span class="sb-chart-bars__item" style="--sb-chart-value:48">
    <span class="sb-chart-bars__bar sb-skeleton"></span>
    <span class="sb-chart-bars__label">Loading</span>
  </span>
</div>
<div class="sb-chart-rows is-empty" role="img" aria-label="No chart data"></div>
<div class="sb-empty">
  <div class="sb-empty__icon" aria-hidden="true">{icon("chart-column")}</div>
  <p class="sb-empty__title">No chart data</p>
  <p class="sb-empty__text">Choose a wider time range to include observations.</p>
</div>
{label("sb-progress · the kit's own track")}
<div class="sb-progress"><span style="width: 38%"></span></div>
<div class="sb-progress"><span style="width: 84%"></span></div>
{label("…and the native element with the same class")}
<progress class="sb-progress" value="65" max="100">65 %</progress>
<p class="sb-muted">No value at all makes it indeterminate:</p>
<progress class="sb-progress"></progress>
{label("&lt;meter&gt; — allowed, but the kit has no class for it")}
<meter value="0.7" min="0" max="1">70 %</meter>
{label("inline &lt;svg&gt; · shapes, gradients and text")}
<svg viewBox="0 0 300 90" role="img" aria-label="An accent wave">
  <defs>
    <linearGradient id="kit-wave" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="var(--sb-accent)"></stop>
      <stop offset="1" stop-color="var(--sb-accent-2)"></stop>
    </linearGradient>
  </defs>
  <path d="M4 70 Q 50 10 100 48 T 200 34 T 296 14" fill="none"
        stroke="url(#kit-wave)" stroke-width="6" stroke-linecap="round"></path>
  <circle cx="296" cy="14" r="8" fill="var(--sb-accent-2)"></circle>
  <text x="4" y="86" fill="var(--sb-text-faint)">polyline · path · circle · text</text>
</svg>
"""

# --------------------------------------------------------------------------
# 7 — surfaces
# --------------------------------------------------------------------------

SURFACES = f"""
{label("sb-hero · painted from the tile's accent")}
<div class="sb-hero">
  <small>Accent gradient</small><h1>sb-hero</h1>
  <span class="sb-badge sb-badge-info">badges adapt inside it</span>
</div>
<div class="sb-hero" style="--sb-accent-gradient:linear-gradient(135deg,#0ea5e9,#22c1a7);--sb-on-accent:#04141a">
  <small>Its own tint</small><h1>18°</h1>
</div>
{label("sb-card · sb-tip")}
<div class="sb-card"><p>sb-card — the inner glass surface.</p></div>
<div class="sb-tip">{icon("info")}<span>sb-tip — the info callout row.</span></div>
<hr class="sb-divider">
{label("harvested card anatomy")}
<article class="sb-card">
  <div class="sb-card__body">
    <div class="sb-card__header">
      <span class="sb-card__icon">{icon("zap")}</span>
      <h3 class="sb-card__title">Fast by default</h3>
    </div>
    <p class="sb-card__text">sb-card__text sits under the icon row.</p>
  </div>
  <div class="sb-card__footer">
    <button class="sb-btn sb-btn--soft sb-btn--sm">Learn more</button>
  </div>
</article>
{label("card variants")}
<div class="sb-card sb-card--soft"><div class="sb-card__body"><h3 class="sb-card__title">--soft</h3><p class="sb-card__text">Dual-light modelling.</p></div></div>
<div class="sb-card sb-card--laser"><div class="sb-card__body"><h3 class="sb-card__title">--laser</h3><p class="sb-card__text">Animated accent ring.</p></div></div>
<div class="sb-card sb-card--glass"><div class="sb-card__body"><h3 class="sb-card__title">--glass</h3></div></div>
<div class="sb-card sb-card--accent"><div class="sb-card__body"><h3 class="sb-card__title">--accent</h3></div></div>
<div class="sb-card sb-card--interactive"><div class="sb-card__body"><h3 class="sb-card__title">--interactive</h3><p class="sb-card__text">Surface shifts on hover.</p></div></div>
<label class="sb-card sb-card--selectable">
  <span class="sb-card__body">
    <span class="sb-card__title">--selectable</span>
    <span class="sb-card__text">A card that is a radio button.</span>
    <input type="radio" name="kit-pick" checked>
  </span>
  <span class="sb-card__checked-cue" aria-hidden="true"></span>
</label>
<div class="sb-card sb-grain"><div class="sb-card__body"><h3 class="sb-card__title">sb-grain</h3><p class="sb-card__text">Film grain over the surface.</p></div></div>
<section class="sb-card sb-mesh"><div class="sb-card__body"><h3 class="sb-card__title">sb-mesh</h3><p class="sb-card__text">Gradient mesh, no images.</p></div></section>
{label("sb-card__media")}
<article class="sb-card">
  <img class="sb-card__media" src="sb-asset:slide-1.svg" alt="A generated gradient">
  <div class="sb-card__body"><h3 class="sb-card__title">sb-card__media</h3>
    <p class="sb-card__text">The image was written into the plugin's data
      directory and addressed with <code>sb-asset:</code>.</p></div>
</article>
{label("sb-scroll · sb-scroll-area")}
<div class="sb-scroll sb-card" style="max-height: 120px">
  <p>sb-scroll gives an area themed thin scrollbars.</p>
  <p>Keep scrolling…</p><p>…still going…</p><p>…and this is the bottom.</p>
</div>
<div class="sb-scroll-area" role="region" aria-label="Changelog" tabindex="0">
  <p>sb-scroll-area caps its own height instead.</p>
  <p>Line two.</p><p>Line three.</p><p>Line four.</p><p>Line five.</p>
  <p>Line six.</p><p>Line seven.</p>
</div>
"""

# --------------------------------------------------------------------------
# 8 — lists
# --------------------------------------------------------------------------

LISTS = f"""
{label("sb-list + sb-row (smabar)")}
<div class="sb-list">
  <div class="sb-row">{icon("cpu")}<span>CPU</span><span class="sb-mono sb-push sb-ok">38 %</span></div>
  <div class="sb-row sb-active">{icon("memory-stick")}<span>RAM</span><span class="sb-mono sb-push sb-warn">78 %</span></div>
  <div class="sb-row">{icon("hard-drive")}<span>Disk</span><span class="sb-mono sb-push sb-crit">96 %</span></div>
</div>
{label("sb-list__item (harvested)")}
<ul class="sb-list sb-list--interactive">
  <li class="sb-list__item">{icon("folder")}Documents<span class="sb-muted sb-push">42</span></li>
  <li class="sb-list__item">{icon("image")}Pictures<span class="sb-muted sb-push">318</span></li>
  <li class="sb-list__item">{icon("music")}Music<span class="sb-muted sb-push">7</span></li>
</ul>
{label("sb-timeline")}
<ol class="sb-timeline">
  <li>
    <time class="sb-timeline__time">23 Aug 2026</time>
    <p class="sb-timeline__title">v1.0 released</p>
    <p class="sb-muted">First stable release.</p>
  </li>
  <li>
    <time class="sb-timeline__time">14 Jul 2026</time>
    <p class="sb-timeline__title">Plugin UI kit</p>
    <p class="sb-muted">264 classes, no JavaScript.</p>
  </li>
</ol>
{label("plain lists")}
<ul><li>ul / li</li><li>survive the sanitizer untouched</li></ul>
<ol><li>ordered</li><li>as well</li></ol>
<dl><dt>dl / dt / dd</dt><dd>A definition list, for key–value prose.</dd></dl>
{label("sb-empty")}
<div class="sb-empty">
  <div class="sb-empty__icon" aria-hidden="true">{icon("package")}</div>
  <p class="sb-empty__title">No messages yet</p>
  <p class="sb-empty__text">When someone writes to you, it shows up here.</p>
</div>
"""

# --------------------------------------------------------------------------
# 9 — feedback
# --------------------------------------------------------------------------

FEEDBACK = f"""
{label("sb-alert")}
<div class="sb-alert sb-alert--ok" role="alert">
  <span class="sb-alert__icon" aria-hidden="true">{icon("circle-check")}</span>
  <div><div class="sb-alert__title">Saved</div>
    <div class="sb-alert__text">Your changes have been stored.</div></div>
</div>
<div class="sb-alert sb-alert--info">
  <span class="sb-alert__icon" aria-hidden="true">{icon("info")}</span>
  <div><div class="sb-alert__title">Heads up</div>
    <div class="sb-alert__text">A new plugin version is waiting.</div></div>
</div>
<div class="sb-alert sb-alert--warn">
  <span class="sb-alert__icon" aria-hidden="true">{icon("triangle-alert")}</span>
  <div><div class="sb-alert__title">Disk almost full</div>
    <div class="sb-alert__text">96 % of / is in use.</div></div>
</div>
<div class="sb-alert sb-alert--danger" role="alert">
  <span class="sb-alert__icon" aria-hidden="true">{icon("circle-x")}</span>
  <div><div class="sb-alert__title">Plugin crashed</div>
    <div class="sb-alert__text">weather exited with code 1.</div></div>
</div>
{label("sb-spinner · sb-skeleton")}
<div class="sb-inline">
  <span class="sb-spinner" role="status" aria-label="Loading"></span>
  <span class="sb-muted">loading…</span>
</div>
<p class="sb-skeleton">This line is invisible and only defines the width</p>
<p class="sb-skeleton">…and a shorter one</p>
{label("sb-toast — smabar sends these as popups")}
<div class="sb-cluster">
  <button class="sb-btn sb-btn--soft" data-action="toast" data-value="ok">ok</button>
  <button class="sb-btn sb-btn--soft" data-action="toast" data-value="info">info</button>
  <button class="sb-btn sb-btn--soft" data-action="toast" data-value="warn">warn</button>
  <button class="sb-btn sb-btn--soft" data-action="toast" data-value="danger">danger</button>
</div>
<p class="sb-meta">Each one is a real <code>target="popup"</code> render.</p>
{label("sb-reveal · sb-active opens it")}
<div class="sb-reveal sb-active">
  <div class="sb-card">This block sits inside an open sb-reveal — add or drop
    sb-active and the flyout grows and shrinks smoothly.</div>
</div>
"""

# --------------------------------------------------------------------------
# 10 — disclosure
# --------------------------------------------------------------------------

DISCLOSURE = f"""
<p class="sb-dim">The sections of this flyout are themselves the accordion:
plain <code>&lt;details&gt;</code>, no JavaScript anywhere.</p>
{label("sb-collapsible")}
<details class="sb-collapsible">
  <summary>Show advanced options</summary>
  <div class="sb-collapsible__body">Hidden until you ask for it — native
    &lt;details&gt;/&lt;summary&gt;.</div>
</details>
{label("sb-accordion, nested")}
<div class="sb-accordion">
  <details class="sb-accordion-item" open>
    <summary>Why can a plugin have no JavaScript?</summary>
    <div class="sb-accordion-item__body">Because the shell would run it in the
      document that holds the Tauri bridge. Inert structure is welcome, code is
      not.</div>
  </details>
  <details class="sb-accordion-item">
    <summary>So how is anything interactive?</summary>
    <div class="sb-accordion-item__body">&lt;details&gt;, &lt;dialog&gt; with
      command invokers, and the popover attribute. All three are in the
      Overlays section.</div>
  </details>
</div>
{label("data-carousel · swipe or wait")}
<div class="sb-media" data-carousel data-carousel-interval="4000"
     aria-label="Kit media carousel">
  <img src="sb-asset:slide-1.svg" alt="Slide one">
  <img src="sb-asset:slide-2.svg" alt="Slide two">
  <img src="sb-asset:slide-3.svg" alt="Slide three">
</div>
{label("figure · figcaption · a data: image URI")}
<figure>
  <img class="sb-media" src="{{DATA_URI}}" alt="An inline data URI image">
  <figcaption class="sb-muted">Written straight into the markup as
    <code>data:image/svg+xml</code>.</figcaption>
</figure>
"""

# --------------------------------------------------------------------------
# 11 — overlays
# --------------------------------------------------------------------------

_CTX_ITEMS = [
    {"action": "ctx", "value": "copy", "label": "Copy this example", "icon": "copy"},
    {"action": "ctx", "value": "share", "label": "Share it", "icon": "share-2"},
    {"separator": True},
    {
        "label": "Sort by",
        "icon": "list",
        "items": [
            {"action": "ctx", "value": "sort:name", "label": "Name", "checked": True},
            {"action": "ctx", "value": "sort:date", "label": "Date", "checked": False},
        ],
    },
    {"action": "ctx", "value": "hide", "label": "Not selectable", "disabled": True},
    {"separator": True},
    {"action": "ctx", "value": "delete", "label": "Delete", "icon": "trash-2", "danger": True},
]

OVERLAYS = f"""
{label("native &lt;dialog&gt; · commandfor + command")}
<div class="sb-cluster">
  <button class="sb-btn sb-btn-primary" commandfor="kit-modal" command="show-modal">Open modal</button>
  <button class="sb-btn sb-btn-danger" commandfor="kit-alert" command="show-modal">Alert dialog</button>
</div>
<dialog class="sb-modal" id="kit-modal" aria-labelledby="kit-modal-title">
  <div class="sb-modal__header">
    <h3 class="sb-modal__title" id="kit-modal-title">A real modal</h3>
    <button class="sb-close" commandfor="kit-modal" command="close" aria-label="Close">{icon("x")}</button>
  </div>
  <div class="sb-modal__body">
    <p>A <code>&lt;button commandfor command="show-modal"&gt;</code> opened
      this <code>&lt;dialog&gt;</code>. No script was involved.</p>
    <div class="sb-tip">{icon("info")}<span>Only the built-in command values
      work: close, request-close, show-modal, show-popover, hide-popover,
      toggle-popover.</span></div>
  </div>
  <div class="sb-modal__footer">
    <button class="sb-btn sb-btn-ghost" commandfor="kit-modal" command="close">Cancel</button>
    <button class="sb-btn sb-btn-primary" commandfor="kit-modal" command="close">Save</button>
  </div>
</dialog>
<dialog class="sb-modal sb-modal--alert sb-modal--sm" id="kit-alert" role="alertdialog"
        aria-labelledby="kit-alert-title" aria-describedby="kit-alert-desc">
  <div class="sb-modal__header">
    <span class="sb-modal__icon" aria-hidden="true">{icon("trash-2")}</span>
    <h3 class="sb-modal__title" id="kit-alert-title">Delete plugin?</h3>
  </div>
  <div class="sb-modal__body"><p id="kit-alert-desc">This cannot be undone.</p></div>
  <div class="sb-modal__footer">
    <button class="sb-btn sb-btn--outline" commandfor="kit-alert" command="close">Cancel</button>
    <button class="sb-btn sb-btn-danger" commandfor="kit-alert" command="close">Delete</button>
  </div>
</dialog>
{label("[popover] · a card, a menu and an upward one")}
<div class="sb-cluster">
  <span class="sb-popover">
    <button class="sb-btn" popovertarget="kit-pop">Shipping</button>
    <div class="sb-popover__card" popover id="kit-pop" role="dialog" aria-label="Shipping details">
      <p class="sb-popover__title">Shipping</p>
      <p class="sb-popover__body">Free worldwide shipping on orders over $50.</p>
    </div>
  </span>
  <span class="sb-popover">
    <button class="sb-btn" popovertarget="kit-pop-top">Upwards</button>
    <div class="sb-popover__card sb-popover__card--top" popover id="kit-pop-top"
         role="dialog" aria-label="Opens above the trigger">
      <p class="sb-popover__title">--top</p>
      <p class="sb-popover__body">The same card, opening above its trigger.</p>
    </div>
  </span>
  <span class="sb-popover">
    <button class="sb-btn sb-btn-icon" popovertarget="kit-menu" aria-label="Options"
            title="A menu, built from a popover">{icon("ellipsis")}</button>
    <div class="sb-popover__card sb-popover__card--right" popover id="kit-menu" role="menu">
      <button class="sb-dropdown__item" role="menuitem" data-action="menu" data-value="edit">
        {icon("pencil")}Edit<span class="sb-dropdown__kbd">Ctrl E</span></button>
      <button class="sb-dropdown__item" role="menuitem" data-action="menu" data-value="duplicate">
        {icon("copy")}Duplicate</button>
      <div class="sb-dropdown__divider" role="separator"></div>
      <button class="sb-dropdown__item sb-dropdown__item--danger" role="menuitem"
              data-action="menu" data-value="delete">{icon("trash-2")}Delete</button>
    </div>
  </span>
</div>
<p class="sb-meta">The menu entries are real actions — picking one sends it to
  the plugin and a popup comes back.</p>
{label("sb-hover-card · pure CSS, opens on hover")}
<p class="sb-dim">Hover <span class="sb-hover-card"><a href="https://lucide.dev/icons/">@lucide</a>
  <span class="sb-hover-card__card"><strong>Lucide</strong><br>
  <span class="sb-muted">The icon set behind data-lucide. The link opens in
  your system browser.</span></span></span> to see the card.</p>
{label("title = a themed tooltip, not the webview's")}
<button class="sb-btn" title="The shell draws this after 400 ms and clamps it to the screen">
  Hover me</button>
{label("data-context-items = a custom right-click menu")}
<div class="sb-card" {ctx(_CTX_ITEMS)}>
  <p>Right-click this card: icons, a check-marked submenu, a disabled entry, a
    separator and a destructive item. Picking one arrives as a normal action.</p>
</div>
"""

# --------------------------------------------------------------------------
# 12 — layout
# --------------------------------------------------------------------------

_ICON_NAMES = (
    "activity", "battery-charging", "bell", "bitcoin", "calendar-days",
    "chart-column", "chart-pie", "cloud-rain", "cpu", "database",
    "download", "droplets", "flame", "folder-open", "gauge", "globe",
    "hard-drive", "heart", "house", "layers", "lock", "mail", "map-pin",
    "moon", "music", "network", "package", "power", "search", "shield",
    "snowflake", "sparkles", "star", "sun", "terminal", "timer",
    "trending-up", "truck", "umbrella", "user", "wallet", "wifi",
    "wind", "wrench",
)

_ICON_GRID = "".join(
    f'<span class="sb-card sb-center" title="{name}">{icon(name)}</span>'
    for name in _ICON_NAMES
)

LAYOUT = f"""
{label("sb-grid · --sb-grid-cols is yours")}
<div class="sb-grid" style="--sb-grid-cols:4">
  <span class="sb-card sb-center">1</span><span class="sb-card sb-center">2</span>
  <span class="sb-card sb-center">3</span><span class="sb-card sb-center">4</span>
</div>
{label("sb-cols-2 / sb-cols-3 / sb-cols-4")}
<div class="sb-cols-2"><div class="sb-card sb-center">A</div><div class="sb-card sb-center">B</div></div>
<div class="sb-cols-3"><div class="sb-card sb-center">A</div><div class="sb-card sb-center">B</div><div class="sb-card sb-center">C</div></div>
<div class="sb-cols-4"><div class="sb-card sb-center">1</div><div class="sb-card sb-center">2</div><div class="sb-card sb-center">3</div><div class="sb-card sb-center">4</div></div>
{label("sb-cluster · wraps, sb-inline · does not")}
<div class="sb-cluster">
  <span class="sb-badge">one</span><span class="sb-badge">two</span>
  <span class="sb-badge">three</span><span class="sb-badge">four</span>
  <span class="sb-badge">five</span><span class="sb-badge">six</span>
</div>
<div class="sb-inline">{icon("cpu")}<span>sb-inline</span><span class="sb-mono sb-push">sb-push →</span></div>
{label("sb-stack · sb-tight · sb-flush")}
<div class="sb-stack"><div class="sb-card">standard rhythm</div><div class="sb-card">between blocks</div></div>
<div class="sb-tight"><div class="sb-card">sb-tight</div><div class="sb-card">is denser</div></div>
<div class="sb-flush"><div class="sb-card">sb-flush</div><div class="sb-card">has no gap at all</div></div>
{label("sb-center")}
<div class="sb-card sb-center">centred text</div>
{label("sb-container--narrow")}
<div class="sb-container sb-container--narrow"><div class="sb-card sb-center">inset and centred</div></div>
{label("sb-ratio (16:9) · sb-media · sb-media-cover")}
<div class="sb-ratio"><img src="sb-asset:slide-2.svg" alt="A 16:9 crop"></div>
<img class="sb-media sb-media-cover" src="sb-asset:slide-3.svg" alt="Cover media">
{label("sb-cq + sb-card-grid")}
<div class="sb-cq">
  <div class="sb-card-grid">
    <div class="sb-card"><div class="sb-card__body">The grid asks its wrapper how wide it is…</div></div>
    <div class="sb-card"><div class="sb-card__body">…and drops to one column here.</div></div>
  </div>
</div>
{label("sb-bento")}
<div class="sb-bento" style="--sb-gap:0.375rem">
  <div class="sb-card sb-bento__item--2x"><div class="sb-card__body">--2x</div></div>
  <div class="sb-card sb-bento__item--wide"><div class="sb-card__body">--wide</div></div>
  <div class="sb-card"><div class="sb-card__body">item</div></div>
  <div class="sb-card"><div class="sb-card__body">item</div></div>
  <div class="sb-card sb-bento__item--tall"><div class="sb-card__body">--tall</div></div>
</div>
{label("sb-icon-badge")}
<div class="sb-cluster">
  <span class="sb-icon-badge">{icon("cloud-sun")}</span>
  <span class="sb-icon-badge" style="--sb-accent:#0ea5e9;--sb-on-accent:#04141a">{icon("droplets")}</span>
  <span class="sb-icon-badge" style="--sb-accent:#f59e0b;--sb-on-accent:#241800">{icon("flame")}</span>
</div>
{label(f"data-lucide · {len(_ICON_NAMES)} of the 120 names")}
<div class="sb-grid" style="--sb-grid-cols:6">{_ICON_GRID}</div>
"""

# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# source annotation
# --------------------------------------------------------------------------

# A block runs from one sb-section caption to the next. Splitting on the
# caption is what lets every demo grow a copy button and a source view
# without touching the 77 blocks by hand — a new block gets both for free.
_CAPTION = re.compile(r'<div class="sb-section">(.*?)</div>', re.S)

# The demo image is inlined as a data URI so the showcase needs no files,
# but a plugin should address its own files instead. The source view says
# so rather than printing 20 KB of base64.
_SOURCE_ASSET = "sb-asset:slide-1.svg"


def _tidy(markup: str) -> str:
    """The block's markup as an author would write it: no blank runs."""
    lines = [line.rstrip() for line in markup.strip().splitlines()]
    return "\n".join(line for line in lines if line.strip())


def annotate(section: str) -> str:
    """Gives every demo block a copy button and a foldable source view.

    The copy button carries the caption as an HTML comment, so what lands on
    the clipboard says WHICH classes the markup below demonstrates.
    """
    parts = _CAPTION.split(section)
    if len(parts) < 3:
        return section
    out = [parts[0]]
    # split() yields [before, caption, body, caption, body, ...]
    for index in range(1, len(parts) - 1, 2):
        caption, body = parts[index], parts[index + 1]
        annotate.counter += 1
        source_id = f"kit-src-{annotate.counter}"
        source = f"<!-- {caption} -->\n" + _tidy(
            body.replace("{DATA_URI}", _SOURCE_ASSET)
        )
        out.append(
            '<div class="sb-section sb-inline">'
            f"<span>{caption}</span>"
            '<button class="sb-btn sb-btn-icon sb-copy sb-push"'
            f' data-sb-copy="#{source_id}"'
            ' title="Copy this markup" aria-label="Copy this markup"></button>'
            "</div>"
        )
        out.append(body)
        out.append(
            '<details class="sb-collapsible">'
            "<summary>Markup</summary>"
            '<figure class="sb-code sb-code--wrap">'
            f'<pre class="sb-code__body"><code id="{source_id}">{esc(source)}</code></pre>'
            "</figure>"
            "</details>"
        )
    out.append(parts[-1] if len(parts) % 2 == 0 else "")
    return "".join(out)


annotate.counter = 0  # type: ignore[attr-defined]


SECTIONS: list[tuple[str, str, str]] = [
    ("monitor", "Bar tile", TILE),
    ("file-text", "Type & text", TYPE),
    ("zap", "Buttons, chips & tabs", BUTTONS),
    ("pencil", "Forms", FORMS),
    ("database", "Data display", DATA),
    ("chart-line", "Charts & meters", CHARTS),
    ("layers", "Surfaces & cards", SURFACES),
    ("list", "Lists & timeline", LISTS),
    ("bell", "Feedback", FEEDBACK),
    ("chevron-down", "Disclosure & media", DISCLOSURE),
    ("layout-grid", "Overlays & menus", OVERLAYS),
    ("box", "Layout & icons", LAYOUT),
]


def header() -> str:
    return (
        '<div class="sb-header">'
        f'<span class="sb-icon-badge">{icon("layout-grid")}</span>'
        '<span class="sb-title">UI Kit</span>'
        '<div class="sb-header-actions">'
        '<button class="sb-btn sb-btn-icon" data-action="toast" data-value="info"'
        ' title="Send a demo popup" aria-label="Send a demo popup">'
        f'{icon("bell")}</button>'
        '<button class="sb-btn sb-btn-icon" data-action="about"'
        ' title="What is this?" aria-label="What is this?">'
        f'{icon("info")}</button>'
        "</div></div>"
    )


def intro(class_count: int) -> str:
    return (
        '<div class="sb-hero">'
        "<small>smabar plugin UI kit</small>"
        f"<h1>{class_count} classes</h1>"
        '<span class="sb-badge sb-badge-accent">no JavaScript</span>'
        "</div>"
        '<p class="sb-dim">Twelve sections, all live markup. Open one — they are'
        " ordinary <code>&lt;details&gt;</code> elements.</p>"
    )


def flyout(data_uri: str, class_count: int, compact: bool) -> str:
    annotate.counter = 0  # type: ignore[attr-defined]
    body = [header(), intro(class_count), '<div class="sb-accordion">']
    for name, title, markup in SECTIONS:
        body.append(
            '<details class="sb-accordion-item">'
            f'<summary><span class="sb-inline">{icon(name)}<span>{esc(title)}</span>'
            "</span></summary>"
            '<div class="sb-accordion-item__body">'
            f"{annotate(markup).replace('{DATA_URI}', data_uri)}"
            "</div></details>"
        )
    body.append("</div>")
    body.append(
        '<p class="sb-meta">Written entirely through the MCP plugin tools — '
        "a Python process that emits HTML strings.</p>"
    )
    inner = "".join(body)
    return f'<div class="sb-tight">{inner}</div>' if compact else inner

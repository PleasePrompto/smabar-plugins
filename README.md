# smabar-plugins

The official plugin and theme repository of [smabar](https://smabar.com). Everything here is
written by the smabar developer, listed in the Community Store and licensed under MIT.
New plugins are released here first.

One folder per plugin under `plugins/`, each with its `smabar.json`, entry script and README.
Themes are single files under `themes/`. Install from Settings › Plugins › Plugin Store or
Settings › Design › Community Themes inside the app.

## Plugins

| Plugin | What it does |
| --- | --- |
| [`plugins/dev-smabar`](plugins/dev-smabar) | smabar Dev Kit: every UI-kit class and convention, live in one flyout. The reference for plugin authors and their agents. |
| [`plugins/ai-usage`](plugins/ai-usage) | AI Usage: Claude Code and Codex quota usage on the bar, read from the local CLIs — no API keys. |
| [`plugins/clipboard-history`](plugins/clipboard-history) | Clipboard History: everything you copied as text, found again in one click. Local, searchable, pinnable. |
| [`plugins/converter`](plugins/converter) | Converter: currency and unit conversion in a flyout, the live rate of a favourite pair on the tile. ECB rates via Frankfurter, no API key. |
| [`plugins/countdowns`](plugins/countdowns) | Countdowns: days until the things you look forward to (or dread): holidays, launches, deadlines, birthdays. |
| [`plugins/docker`](plugins/docker) | Docker: your containers on the bar: what runs, what stopped, ports, start and stop without a terminal. Docker Desktop, Docker Engine and Podman. |
| [`plugins/focus-timer`](plugins/focus-timer) | Focus Timer: Pomodoro on the bar: focus blocks, short and long breaks, a done popup with chime, today's totals and agent commands. |
| [`plugins/keep-awake`](plugins/keep-awake) | Keep Awake: one switch that keeps the screen on and the computer from sleeping, for a presentation, a long download or a build. |
| [`plugins/next-meeting`](plugins/next-meeting) | Next Meeting: your next appointment on the bar, from any calendar with an ICS address (Google, Outlook, iCloud, Nextcloud, Fastmail). No OAuth, no API key. |
| [`plugins/quick-notes`](plugins/quick-notes) | Quick Notes: a scratchpad on the bar: jot a note in two seconds and find it again later. Plain Markdown files you can open in any editor. |
| [`plugins/rss-ticker`](plugins/rss-ticker) | RSS Ticker: headlines from the feeds you choose, rotating on the bar, the full list one click away. |
| [`plugins/uptime`](plugins/uptime) | Uptime: is it up? Your own sites, servers and services, checked from your machine, with a popup the moment one goes down. |

## Themes

| Theme | What it is |
| --- | --- |
| [`themes/smabar-flat.json`](themes/smabar-flat.json) | smabar Flat: the smabar look as a flat top bar, brand yellow on cool near-black, square corners, Open Sans and Roboto Mono. |

## Writing your own

Any public GitHub repository with the same layout can be submitted to the Community Store:
[smabar.com/docs/publish](https://smabar.com/docs/publish/). The Dev Kit shows the kit
classes; `plugin_guide` and `ui_kit` over MCP describe them to an agent.

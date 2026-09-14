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

## Themes

| Theme | What it is |
| --- | --- |
| [`themes/smabar-flat.json`](themes/smabar-flat.json) | smabar Flat: the smabar look as a flat top bar, brand yellow on cool near-black, square corners, Open Sans and Roboto Mono. |

## Writing your own

Any public GitHub repository with the same layout can be submitted to the Community Store:
[smabar.com/docs/publish](https://smabar.com/docs/publish/). The Dev Kit shows the kit
classes; `plugin_guide` and `ui_kit` over MCP describe them to an agent.

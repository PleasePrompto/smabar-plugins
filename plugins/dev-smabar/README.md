# smabar Dev Kit

Every class and convention of the smabar plugin UI kit, live in one flyout. One tile on the bar, one flyout with twelve collapsible sections, no JavaScript.

## What you see

| Section | Contents |
| --- | --- |
| Bar tile | Rotating tile text, badge, hover card |
| Type & text | Headings, meta, mono, muted and faint text |
| Buttons, chips & tabs | Every button flavour, chips, tab strips |
| Forms | Inputs, selects, switches, ranges and how `data-field` values reach the plugin |
| Data display | Key/value rows, stats, badges |
| Charts & meters | Sparkline, bars, gauges, progress |
| Surfaces & cards | Cards, hero blocks, inner surfaces |
| Lists & timeline | Lists, rows, timeline entries |
| Feedback | Toasts in all four flavours, sent as popups |
| Disclosure & media | `<details>`, carousel, images from `sb-asset:` and `data:` URIs |
| Overlays & menus | `<dialog>` with command invokers, `[popover]`, context menus |
| Layout & icons | Grid helpers, spacing, Lucide icons |

The hero prints how many distinct `sb-*` classes the page uses. Every button answers with a popup instead of a re-render, so the section you opened stays open.

## Settings

`density`: `comfortable` (default) or `compact`.

## For plugin authors

Read `plugin.py` and `kit_sections.py` next to the flyout: each section is the markup that produced it. With an agent connected over MCP, `plugin_guide` and `ui_kit` describe the same classes; this plugin is where you look at them.

Python, no dependencies beyond the smabar SDK. MIT, see the repository root.

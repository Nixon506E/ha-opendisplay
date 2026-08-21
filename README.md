# OpenDisplay integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/OpenDisplay/Home_Assistant_Integration?style=for-the-badge)](https://github.com/OpenDisplay/Home_Assistant_Integration/releases)
[![GitHub issues](https://img.shields.io/github/issues/OpenDisplay/Home_Assistant_Integration?style=for-the-badge)](https://github.com/OpenDisplay/Home_Assistant_Integration/issues)
![Discord](https://img.shields.io/discord/1453066942544875593?style=for-the-badge)



Home Assistant Integration for the [OpenDisplay](https://opendisplay.org/) project, enabling control and monitoring of E-Paper displays through Home Assistant.

## Requirements

Link to seeed OpenDisplay Wiki page will be added here...

### Hardware
OpenDisplay-compatible Boards/Displays:
 - See [Compatibility Guide](https://opendisplay.org/firmware/seeed_display_compatibility.html)

### 🎨 Display Controls

#### drawcustom (Recommended)
The most flexible and powerful service for creating custom displays. Supports:
- Text with multiple fonts and styles
- Shapes (rectangles, circles, lines)
- Icons from Material Design Icons
- QR codes
- Images from URLs
- Plots of Home Assistant sensor data
- Progress bars

[View full drawcustom documentation](docs/drawcustom/supported_types.md)


## Installation


### Option 1: HACS Installation (Recommended)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=OpenDisplay&repository=Home_Assistant_Integration)

### Option 2: Manual Installation
1. Download the `opendisplay` folder from the [latest release](https://github.com/OpenDisplay/Home_Assistant_Integration/releases/latest)
2. Copy it to your [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations)
3. Restart Home Assistant

## Configuration

Devices should be automatically discovered after installation.


## Usage Examples

### Basic Text Display
```yaml
- type: "text"
  value: "Hello World!"
  x: 10
  y: 10
  size: 40
  color: "red"
```

### Progress Bar with Icon
```yaml
- type: "progress_bar"
  x_start: 10
  y_start: 10
  x_end: 180
  y_end: 30
  progress: 75
  fill: "red"
  show_percentage: true
- type: "icon"
  value: "mdi:battery-70"
  x: 190
  y: 20
  size: 24
```

### Sensor Display
```yaml
- type: "text"
  value: "Temperature: {{ states('sensor.temperature') }}°C"
  x: 10
  y: 10
  size: 24
  color: "black"
- type: "text"
  value: "Humidity: {{ states('sensor.humidity') }}%"
  x: 10
  y: 40
  size: 24
  color: "black"
```

## Translations

The integration is available in Czech, Dutch, English, French, German, Italian,
Polish, Portuguese (European and Brazilian), and Spanish.

English is written by hand. **Every other language is machine-translated** and
has not been reviewed by a native speaker, so expect the occasional awkward or
plainly wrong phrasing. Corrections are very welcome, and they stick:

- Edit the relevant file in `custom_components/opendisplay/translations/` and
  open a pull request. There is no need to touch anything else.
- **Your wording will not be overwritten.** The translation workflow records a
  fingerprint of what it generated, so it can tell its own output from a human
  edit. Once you have corrected a string it is treated as yours. If the English
  source later changes, the workflow flags the string for review rather than
  replacing your version.

One style note if you are correcting a string: translations deliberately avoid
the familiar/polite distinction (German du/Sie, French tu/vous, and so on) by
using impersonal phrasing, such as infinitives for instructions. Please keep
that style.

Missing a language? Open an issue and we will add it.

<details>
<summary>Maintaining the translations (developer notes)</summary>

`scripts/translate.py` fills in strings that are missing from a language, or
whose English source was reworded since it was last translated. Nothing else is
ever sent to a model. `.github/workflows/translate.yml` runs it when
`translations/en.json` changes on a release branch and opens a pull request.

**Adding a language.** Add its code and name to `LANGUAGES` in
`scripts/translate.py`. The next run fills in the file.

**Providers.** Any OpenAI-compatible chat endpoint works. OpenRouter and GitHub
Models are configured out of the box in `PROVIDERS`, selected by whichever API
key is present:

| Variable | Provider | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | OpenRouter | Preferred. No output-token cap. |
| `MODELS_TOKEN` | GitHub Models | Personal access token with `models:read`. |
| `GITHUB_TOKEN` | GitHub Models | Only works if the repo's org has a Copilot plan. |

`TRANSLATE_PROVIDER` and `TRANSLATE_MODEL` override the choice for one run:

```bash
OPENROUTER_API_KEY=... TRANSLATE_MODEL=google/gemini-2.5-flash-lite \
  python3 scripts/translate.py --languages de --dry-run
```

**Checking output.** `scripts/verify_translations.py` re-checks the files on
disk and fails on placeholder mismatches, empty values, or keys that no longer
exist in `en.json`. It also warns when a translation addresses the reader
directly, which the impersonal style above is meant to avoid.

</details>

## Contributing
- Feature requests and bug reports are welcome! Please open an issue on GitHub
- Pull requests are encouraged
- Join the [Discord server](https://discord.com/invite/tw48NCrRxH) to discuss ideas and get help

# Enable HACS Download Count Tracking

Do this when cutting the 3.0 stable release, not before.

## How it works

HACS reads `assets[0].download_count` from the GitHub release. Without a zip asset,
there is nothing to count. Adding `zip_release` causes HACS to download a zip file
from the release assets instead of individual files from the source tree — GitHub
then tracks how many times that zip has been downloaded.

## Changes required

### 1. `hacs.json`

Add two keys:

```json
{
  "name": "OpenDisplay",
  "render_readme": true,
  "homeassistant": "2026.4.0",
  "zip_release": true,
  "filename": "opendisplay.zip"
}
```

### 2. `.github/workflows/release-zip.yml` (new file)

Create a separate workflow triggered when release-please publishes a release.
This is the pattern used by blitzortung and ha-bambulab.

```yaml
name: Release Zip

on:
  release:
    types: [published]

jobs:
  upload-zip:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - name: Create zip
        run: |
          cd custom_components/opendisplay
          zip opendisplay.zip -r ./

      - name: Upload zip to release
        uses: softprops/action-gh-release@v3
        with:
          files: ${{ github.workspace }}/custom_components/opendisplay/opendisplay.zip
```

## Verify it worked

After the 3.0 release, check:

```
gh api repos/OpenDisplay/Home_Assistant_Integration/releases/latest \
  --jq '{tag: .tag_name, assets: [.assets[] | {name: .name, downloads: .download_count}]}'
```

`assets` should be non-empty. Once a few users install via HACS, the count will appear in the HACS UI.

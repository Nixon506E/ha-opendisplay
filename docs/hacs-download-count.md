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

### 2. Attach the zip from the release-please workflow

Applied in `.github/workflows/release-please.yml`: the zip is built and uploaded in
the same job that cuts the release, gated on the action's `release_created` output.

```yaml
      - uses: googleapis/release-please-action@v4
        id: release
        ...

      - uses: actions/checkout@v4
        if: ${{ steps.release.outputs.release_created }}

      - name: Create zip
        if: ${{ steps.release.outputs.release_created }}
        run: |
          cd custom_components/opendisplay
          zip opendisplay.zip -r ./

      - name: Upload zip to release
        if: ${{ steps.release.outputs.release_created }}
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh release upload "${{ steps.release.outputs.tag_name }}" \
            custom_components/opendisplay/opendisplay.zip --clobber
```

**Do not use a separate workflow triggered by `release: published`.** That was tried for
3.0.0 and never ran: release-please creates the release with `GITHUB_TOKEN`, and GitHub
does not start workflow runs from events raised by that token. The 3.0.0 zip had to be
built and uploaded by hand afterwards. Since `zip_release` makes HACS install from the
asset, a missing zip means installing that release fails outright.

## Verify it worked

After the 3.0 release, check:

```
gh api repos/OpenDisplay/Home_Assistant_Integration/releases/latest \
  --jq '{tag: .tag_name, assets: [.assets[] | {name: .name, downloads: .download_count}]}'
```

`assets` should be non-empty. Once a few users install via HACS, the count will appear in the HACS UI.

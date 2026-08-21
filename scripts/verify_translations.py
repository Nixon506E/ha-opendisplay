#!/usr/bin/env python3
"""Check generated translation files before they reach a pull request.

translate.py validates each string as it comes back from the model. This script
re-checks the files as they now sit on disk, so a bug in the writing/merging
path, a bad hand-edit, or a truncated response is caught by CI rather than by a
user seeing a broken config flow.

Exits non-zero on any problem. Safe to run locally at any time.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS_DIR = REPO_ROOT / "custom_components" / "opendisplay" / "translations"
SOURCE_FILE = TRANSLATIONS_DIR / "en.json"

# Reuse the flattening and placeholder rules rather than reimplementing them,
# so the two scripts can never disagree about what "valid" means.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from translate import PLACEHOLDER_RE, flatten, show  # noqa: E402

# Second-person pronouns that indicate the model addressed the user directly
# instead of using the impersonal phrasing rule 6 asks for. These are warnings,
# not failures: a false alarm should never block a release.
#
# German is matched case-sensitively on purpose. It capitalises the polite
# pronouns (Sie/Ihr/Ihnen) and lowercases the identical-looking third person
# ("sie" = they, "ihre" = their), so folding case turns every "before they
# expire" into a false formality warning. Other languages are case-insensitive.
DIRECT_ADDRESS = {
    "de": (r"\bSie\b|\bIhre?[nmrs]?\b|\bIhnen\b|\bdu\b|\bdir\b|\bdich\b|\bdein\w*\b", 0),
    "nl": (r"\bje\b|\bjouw\b|\bjij\b|\buw\b|\bu\b", re.IGNORECASE),
    "fr": (r"\btu\b|\bton\b|\bta\b|\btes\b|\bvous\b|\bvotre\b|\bvos\b", re.IGNORECASE),
    "es": (r"\btú\b|\btu\b|\busted\b|\bsus?\b|\bvuestro\b", re.IGNORECASE),
    "it": (r"\btu\b|\btuo\b|\blei\b|\bsuo\b|\bvostro\b", re.IGNORECASE),
    "pl": (r"\bty\b|\btwój\b|\btwoje\w*\b|\bpan\b|\bpani\b", re.IGNORECASE),
    "pt": (r"\bvocê\b|\btu\b|\bteu\b|\btua\b|\bseu\b|\bsua\b|\bvosso\b", re.IGNORECASE),
    "pt-BR": (r"\bvocê\b|\bteu\b|\btua\b|\bseu\b|\bsua\b", re.IGNORECASE),
    "cs": (r"\bty\b|\btvůj\b|\btvoje\w*\b|\bvy\b|\bváš\b|\bvaše\w*\b", re.IGNORECASE),
}


def main() -> int:
    source = flatten(json.loads(SOURCE_FILE.read_text(encoding="utf-8")))
    errors: list[str] = []
    warnings: list[str] = []
    checked = 0

    for path in sorted(TRANSLATIONS_DIR.glob("*.json")):
        code = path.stem
        if code == "en":
            continue
        checked += 1

        try:
            data = flatten(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError) as err:
            errors.append(f"{path.name}: not valid translation JSON: {err}")
            continue

        for key in sorted(set(data) - set(source)):
            errors.append(f"{path.name}: key '{show(key)}' does not exist in en.json")

        for key, translation in sorted(data.items()):
            english = source.get(key)
            if english is None:
                continue

            if not translation.strip():
                errors.append(f"{path.name}: '{show(key)}' is empty")
                continue

            expected = sorted(PLACEHOLDER_RE.findall(english))
            actual = sorted(PLACEHOLDER_RE.findall(translation))
            if expected != actual:
                errors.append(
                    f"{path.name}: '{show(key)}' placeholder mismatch: "
                    f"expected {expected}, got {actual}"
                )

            pattern = DIRECT_ADDRESS.get(code)
            if pattern:
                match = re.search(pattern[0], translation, pattern[1])
                if match:
                    warnings.append(
                        f"{path.name}: '{show(key)}' may address the user directly "
                        f"({match.group(0)!r}): {translation}"
                    )

        missing = len(set(source) - set(data))
        extra = len(set(data) - set(source))
        notes = []
        if missing:
            notes.append(f"{missing} missing")
        if extra:
            notes.append(f"{extra} unknown")
        status = ", ".join(notes) if notes else "complete"
        print(f"{path.name}: {len(data & source.keys())}/{len(source)} ({status})")

    if not checked:
        print("No translation files to verify yet.")
        return 0

    if warnings:
        print(f"\n{len(warnings)} formality warning(s):")
        for warning in warnings:
            print(f"  - {warning}")

    if errors:
        print(f"\n{len(errors)} error(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("\nAll translation files valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

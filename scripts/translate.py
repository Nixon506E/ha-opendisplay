#!/usr/bin/env python3
"""Fill in missing Home Assistant translations using GitHub Models.

Source of truth is ``translations/en.json`` -- the fully resolved English file.
``strings.json`` is NOT usable here: it contains ``[%key:...%]`` references that
only Home Assistant's build tooling (script/hassfest) resolves. The runtime
translation loader does no such resolution, so shipped translation files must be
fully resolved.

A key is sent to the model only when it is missing, or when its English source
was reworded since it was last translated. Everything else is left alone, so a
run after adding three new strings costs three strings' worth of tokens rather
than the whole file.

Manual corrections are protected. ``.translation-state.json`` records, per key,
a fingerprint of the English source *and* of the translation this script wrote.
If the translation on disk no longer matches the recorded fingerprint, a human
edited it: the script will never overwrite that key, and instead reports it for
review if the English behind it changed. See ``classify`` for the full policy.

Runs on the stdlib only -- no new entries in requirements.txt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _ssl_context() -> ssl.SSLContext:
    """TLS context that also works on python.org macOS builds.

    Those ship without a CA bundle wired into OpenSSL, so urllib fails with
    CERTIFICATE_VERIFY_FAILED even though curl succeeds. CI runners are fine;
    this keeps local runs working without an extra setup step.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CONTEXT = _ssl_context()

REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS_DIR = REPO_ROOT / "custom_components" / "opendisplay" / "translations"
SOURCE_FILE = TRANSLATIONS_DIR / "en.json"

# Deliberately outside custom_components/: this is CI bookkeeping, not data that
# should ship to every HACS user alongside the integration.
STATE_FILE = REPO_ROOT / ".github" / "translation-state.json"

# When the English source is reworded but the existing translation was edited by
# a human, prefer the human's wording and surface it for review. Flip this to
# True to let fresh machine output win instead.
OVERWRITE_MANUAL_EDITS = False

API_URL = "https://models.github.ai/inference/chat/completions"

# Low rate-limit tier: 150 requests/day vs 50 for high tier. Tagged multilingual.
# Verify against https://models.github.ai/catalog/models before changing.
MODEL = "openai/gpt-4.1-mini"

# GitHub Models caps output at 4000 tokens per request on the Copilot Free/Pro
# tier, well below the model's own 32k ceiling. That cap -- not the model -- is
# why we chunk. ~80 strings lands around 1800 output tokens, leaving margin for
# languages that render longer than English.
CHUNK_SIZE = 80

# 15 requests/minute on the low tier.
MIN_SECONDS_BETWEEN_REQUESTS = 4.5

LANGUAGES = {
    "de": "German",
    "fr": "French",
    "nl": "Dutch",
    "es": "Spanish",
    "it": "Italian",
    "pl": "Polish",
    # Home Assistant treats these as separate locales, and they diverge in
    # everyday UI vocabulary (ecra/tela, utilizador/usuario).
    "pt": "European Portuguese",
    "pt-BR": "Brazilian Portuguese",
    "cs": "Czech",
}

PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")

# Every target language distinguishes a familiar from a polite second person.
# Rule 6 of the prompt asks the model to sidestep the choice with impersonal
# phrasing; this is only the tie-breaker for sentences where that is impossible.
FALLBACK_REGISTER = "informal"

# Terms that must survive translation untouched. Product and protocol names read
# as noise when localised, and HA's own translations leave them in English.
DO_NOT_TRANSLATE = [
    "OpenDisplay",
    "Home Assistant",
    "BLE",
    "Bluetooth",
    "NFC",
    "AP",
    "MAC",
    "OTA",
    "RSSI",
    "LED",
]

SYSTEM_PROMPT = """\
You translate user-interface strings for a Home Assistant integration from \
English into {language}.

You will receive a JSON object mapping opaque dotted keys to English strings. \
Return a JSON object with the EXACT same keys, where each value is the \
{language} translation of the corresponding English string.

Rules:
1. Return only the JSON object. No prose, no markdown fences, no explanation.
2. Keys are identifiers, not content. Copy them verbatim; never translate a key.
3. Placeholders wrapped in curly braces, such as {{name}} or {{number}}, are \
substituted at runtime. Reproduce every placeholder exactly, character for \
character, including its braces. Never translate, rename, reorder into a \
different placeholder, add, or drop one. You may move a placeholder within the \
sentence when the target language's grammar requires it.
4. Leave these terms in English: {do_not_translate}.
5. Use the terminology and phrasing Home Assistant itself uses in {language} \
for common concepts (device, entity, sensor, configuration, service, area).
6. Stay neutral about formality. {language} distinguishes levels of politeness \
when addressing someone directly, and this interface should commit to neither. \
Rephrase so the question does not arise: use the infinitive or a bare noun \
phrase for instructions and labels, and an impersonal or passive construction \
for statements. For example, prefer the {language} equivalent of "Enter \
encryption key" over "Please enter your encryption key", and of "Set up \
{{name}}?" over "Do you want to set up {{name}}?". This is normal, idiomatic \
phrasing for software interfaces, not a stilted workaround.
7. Only if a sentence genuinely cannot be expressed without addressing the \
reader, use the {fallback_register} form, and keep it consistent.
8. These are short UI labels, field descriptions, and error messages. Keep them \
concise and idiomatic. Do not add politeness or filler that is absent from the \
English source. Preserve trailing punctuation as-is.
"""


# Path separator for flattened keys. NOT a dot: Home Assistant select entities
# use their option values as translation keys, and those legitimately contain
# dots, e.g. entity.select.subghzchannel.state."100 - 864.000 Mhz (Europe, etc)".
# A dot separator silently mis-nests those. NUL cannot appear in a JSON key that
# came from a real translation file, so it round-trips safely.
SEP = "\x00"


def flatten(obj: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested translation data into separator-joined paths."""
    flat: dict[str, str] = {}
    for key, value in obj.items():
        if SEP in key:
            raise ValueError(f"Key {key!r} at {prefix or '<root>'} contains NUL")
        path = f"{prefix}{SEP}{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten(value, path))
        else:
            flat[path] = value
    return flat


def unflatten(flat: dict[str, str]) -> dict:
    """Rebuild nested translation data from flattened paths."""
    nested: dict = {}
    for path, value in sorted(flat.items()):
        parts = path.split(SEP)
        cursor = nested
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return nested


def show(path: str) -> str:
    """Human-readable form of a flattened path, for logs and PR summaries."""
    return path.replace(SEP, ".")


def fingerprint(text: str) -> str:
    """Short, stable content hash. Only ever compared, never reversed."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def classify(
    source: dict[str, str],
    existing: dict[str, str],
    state: dict[str, dict[str, str]],
    force: bool,
) -> tuple[dict[str, str], list[str], list[str]]:
    """Decide what to do with every key of one language.

    Returns (to_translate, needs_review, obsolete).

    The state entry for a key records two fingerprints: ``src`` (the English at
    the time we translated) and ``out`` (what we wrote). Comparing ``out``
    against the file on disk is what distinguishes a translation this script
    owns from one a human has since corrected.
    """
    to_translate: dict[str, str] = {}
    needs_review: list[str] = []

    for key, english in source.items():
        if key not in existing:
            to_translate[key] = english
            continue

        if force:
            to_translate[key] = english
            continue

        entry = state.get(key)
        if entry is None:
            # No provenance: hand-authored, or predates the state file. Not ours
            # to touch.
            continue

        human_edited = entry.get("out") != fingerprint(existing[key])
        source_changed = entry.get("src") != fingerprint(english)

        if not source_changed:
            continue

        if human_edited and not OVERWRITE_MANUAL_EDITS:
            needs_review.append(key)
            continue

        to_translate[key] = english

    obsolete = [key for key in existing if key not in source]
    return to_translate, needs_review, obsolete


def write_translation_file(path: Path, flat: dict[str, str]) -> None:
    """Write a translation file matching en.json's formatting."""
    path.write_text(
        json.dumps(unflatten(flat), indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def call_model(token: str, language: str, batch: dict[str, str]) -> dict[str, str]:
    """Translate one batch of strings. Raises on transport or parse failure."""
    body = json.dumps(
        {
            "model": MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT.format(
                        language=language,
                        do_not_translate=", ".join(DO_NOT_TRANSLATE),
                        fallback_register=FALLBACK_REGISTER,
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(batch, indent=2, ensure_ascii=False),
                },
            ],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=180, context=SSL_CONTEXT) as response:
        payload = json.load(response)

    content = payload["choices"][0]["message"]["content"].strip()

    # response_format should make fences impossible, but a stray ```json wrapper
    # would otherwise fail the whole run. Cheap to tolerate.
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]

    return json.loads(content)


def validate(
    source: dict[str, str], translated: dict[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Split a model response into (accepted, rejected-with-reason).

    A translation that loses or mangles a placeholder renders broken in Home
    Assistant, so placeholder equality is enforced rather than trusted.
    """
    accepted: dict[str, str] = {}
    rejected: dict[str, str] = {}

    for key, english in source.items():
        if key not in translated:
            rejected[key] = "missing from model response"
            continue

        value = translated[key]
        if not isinstance(value, str) or not value.strip():
            rejected[key] = "empty or non-string translation"
            continue

        expected = sorted(PLACEHOLDER_RE.findall(english))
        actual = sorted(PLACEHOLDER_RE.findall(value))
        if expected != actual:
            rejected[key] = f"placeholder mismatch: expected {expected}, got {actual}"
            continue

        accepted[key] = value

    return accepted, rejected


def translate_language(
    token: str,
    code: str,
    language: str,
    todo: dict[str, str],
    throttle: list[float],
) -> tuple[dict[str, str], dict[str, str]]:
    """Translate every missing string for one language, chunk by chunk."""
    keys = sorted(todo)
    accepted: dict[str, str] = {}
    rejected: dict[str, str] = {}

    chunks = [keys[i : i + CHUNK_SIZE] for i in range(0, len(keys), CHUNK_SIZE)]

    for index, chunk in enumerate(chunks, start=1):
        batch = {key: todo[key] for key in chunk}
        # The model never sees the real paths: they carry a NUL separator and
        # would waste output tokens round-tripping. Send 1..n and map back.
        numbered = {str(n): todo[key] for n, key in enumerate(chunk)}
        by_number = {str(n): key for n, key in enumerate(chunk)}
        print(f"  [{code}] chunk {index}/{len(chunks)} ({len(batch)} strings)")

        elapsed = time.monotonic() - throttle[0]
        if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
            time.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
        throttle[0] = time.monotonic()

        try:
            response = call_model(token, language, numbered)
        except urllib.error.HTTPError as err:
            if err.code == 429:
                # Daily or per-minute budget exhausted. Keep what we have: a
                # partial-but-valid PR beats a failed run.
                print(f"  [{code}] rate limited, stopping early", file=sys.stderr)
                for key in chunk:
                    rejected[key] = "rate limited"
                return accepted, rejected
            raise

        translated = {
            by_number[n]: value
            for n, value in response.items()
            if n in by_number and isinstance(value, str)
        }
        good, bad = validate(batch, translated)
        accepted.update(good)

        # One retry, isolated, in case a neighbouring string derailed the batch.
        for key, reason in bad.items():
            print(f"  [{code}] retrying {show(key)} ({reason})")
            time.sleep(MIN_SECONDS_BETWEEN_REQUESTS)
            throttle[0] = time.monotonic()
            try:
                retry = call_model(token, language, {"0": todo[key]})
            except urllib.error.HTTPError:
                rejected[key] = reason
                continue
            retried = {key: retry["0"]} if isinstance(retry.get("0"), str) else {}
            good_retry, bad_retry = validate({key: todo[key]}, retried)
            accepted.update(good_retry)
            rejected.update(bad_retry)

    return accepted, rejected


def emit_output(name: str, value: str) -> None:
    """Write a step output for the workflow to consume."""
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        if "\n" in value:
            handle.write(f"{name}<<__EOF__\n{value}\n__EOF__\n")
        else:
            handle.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--languages",
        help=f"Comma-separated subset of: {', '.join(LANGUAGES)}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be translated. Makes no API calls.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-translate every key, including ones a human edited.",
    )
    args = parser.parse_args()

    if args.force:
        print(
            "--force will overwrite manual corrections in the selected "
            "languages.",
            file=sys.stderr,
        )

    source = flatten(json.loads(SOURCE_FILE.read_text(encoding="utf-8")))
    print(f"{SOURCE_FILE.name}: {len(source)} strings")

    if args.languages:
        codes = [code.strip() for code in args.languages.split(",") if code.strip()]
        unknown = [code for code in codes if code not in LANGUAGES]
        if unknown:
            parser.error(f"unknown language(s): {', '.join(unknown)}")
    else:
        codes = list(LANGUAGES)

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token and not args.dry_run:
        print(
            "GITHUB_TOKEN is not set. In Actions, add 'models: read' to the "
            "workflow permissions block. Locally, export a PAT with the "
            "models:read scope.",
            file=sys.stderr,
        )
        return 1

    state: dict[str, dict[str, dict[str, str]]] = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    throttle = [0.0]
    changed = False
    summary: list[str] = []
    review: list[str] = []

    for code in codes:
        language = LANGUAGES[code]
        target = TRANSLATIONS_DIR / f"{code}.json"

        existing: dict[str, str] = {}
        if target.exists():
            existing = flatten(json.loads(target.read_text(encoding="utf-8")))

        lang_state = state.setdefault(code, {})
        todo, needs_review, obsolete = classify(
            source, existing, lang_state, args.force
        )

        for key in needs_review:
            review.append(
                f"- **{code}** `{show(key)}`: English source changed, but the "
                f"translation was edited by hand and was left as-is."
            )

        if not todo and not obsolete:
            flagged = (
                f", {len(needs_review)} flagged for review" if needs_review else ""
            )
            print(f"{code} ({language}): up to date{flagged}")
            continue

        if args.dry_run:
            print(
                f"{code} ({language}): would translate {len(todo)}, "
                f"flag {len(needs_review)} for review, "
                f"drop {len(obsolete)} obsolete"
            )
            continue

        print(f"{code} ({language}): translating {len(todo)} strings")
        accepted, rejected = (
            translate_language(token, code, language, todo, throttle)
            if todo
            else ({}, {})
        )

        merged = {key: value for key, value in existing.items() if key in source}
        merged.update(accepted)

        if not merged:
            continue

        write_translation_file(target, merged)
        changed = True

        # Record provenance only for what we just wrote. Untouched keys keep
        # their existing entry; obsolete keys lose theirs.
        for key, value in accepted.items():
            lang_state[key] = {
                "src": fingerprint(source[key]),
                "out": fingerprint(value),
            }
        for key in obsolete:
            lang_state.pop(key, None)

        line = f"- **{code}** ({language}): {len(accepted)} translated"
        if obsolete:
            line += f", {len(obsolete)} obsolete removed"
        if rejected:
            line += f", {len(rejected)} skipped"
        summary.append(line)
        for key, reason in sorted(rejected.items()):
            summary.append(f"  - skipped `{show(key)}`: {reason}")

    if args.dry_run:
        if review:
            print("\nNeeds review:\n" + "\n".join(review))
        return 0

    if changed:
        STATE_FILE.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    if review:
        summary.append("")
        summary.append("**Needs review** (manual translations left untouched):")
        summary.extend(review)

    emit_output("changed", "true" if changed else "false")
    emit_output(
        "summary",
        "\n".join(summary) if summary else "No translation changes.",
    )

    print("\n" + ("\n".join(summary) if summary else "No changes."))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Generate enhanced DREAM profiles from the Persona Modality text records."""

import argparse
import json
import os
import random
import re
import runpy
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


HERE = Path(__file__).resolve().parent
DREAM = HERE.parent / "1000"
DATA = HERE / "personas.json"
TEXT_MODEL = "gpt-5.6-terra"
IMAGE_MODEL = "gpt-image-2.5-sunburst-2026-09-08"
SIZE = "1024x1024"
SECTIONS = (
    "personal_data", "visual_appearance", "environment",
    "personality_attitudes", "other_details",
)
SOURCE_BLOB = "14ac2a996d6c5650997c2d6bb7dfa5bddf381bfe"
DREAM_COMMIT = "9391ff124fa8b6ae2b7332a735fa82c80c74d322"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def write_json(path, value):
    write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def openai_request(key, endpoint, payload):
    request = Request(
        f"https://api.openai.com/v1/{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=300) as response:
            return json.load(response), response.headers.get("x-request-id")
    except HTTPError as exc:
        detail = ""
        if exc.code not in (401, 403):
            try:
                error = json.load(exc)["error"]
                detail = ": " + str(error.get("message", ""))[:500]
            except (ValueError, KeyError, TypeError):
                pass
        message = f"{endpoint}: HTTP {exc.code}{detail}"
        raise RuntimeError(message.replace(key, "[redacted]")) from None


def tracked_request(key, ledger, persona_id, endpoint, payload):
    if endpoint == "images/generations":
        stage = "image"
    elif "text" in payload:
        stage = "expansion"
    else:
        stage = "portrait_prompt"
    record = {
        "persona_id": persona_id, "stage": stage, "requested_model": payload["model"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if stage == "image":
        record.update(quality=payload["quality"], size=payload["size"])
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as stream:
        try:
            result, request_id = openai_request(key, endpoint, payload)
        except (OSError, RuntimeError, ValueError) as exc:
            record.update(status="request_error", error_type=type(exc).__name__)
            raise
        else:
            record.update(
                status=result.get("status", "returned"),
                response_model=result.get("model"),
                request_id=request_id,
                usage=result.get("usage"),
            )
            return result
        finally:
            stream.write(json.dumps(record) + "\n")


def generate_text(request, prompt, *, structured=False):
    payload = {
        "model": TEXT_MODEL,
        "input": prompt,
        "reasoning": {"effort": "low"},
        "max_output_tokens": 4000 if structured else 1500,
        "store": False,
    }
    if structured:
        payload["text"] = {"format": {"type": "json_object"}}
    result = request("responses", payload)
    if result.get("status") != "completed":
        raise ValueError(f"Text generation status: {result.get('status')}")
    content = [
        part["text"] for item in result["output"] if item["type"] == "message"
        for part in item["content"] if part["type"] == "output_text"
    ]
    if not content:
        raise ValueError("Text generation produced no usable text")
    return "".join(content), result["usage"], result.get("model", TEXT_MODEL)


def make_expansion(entry, fallback, config):
    labels = {
        "VALID_ETHNICITIES": config["ethnicity"],
        "VALID_GENDER": config["gender_identity"],
        "VALID_ORIENTATIONS": config["sexual_orientation"],
    }
    template = (HERE / "expand.txt").read_text(encoding="utf-8")
    template = template.replace("{{", "{").replace("}}", "}")
    for placeholder, options in labels.items():
        template = template.replace("{" + placeholder + "}", "\n".join(f"- {option}" for option in options))
    return template.replace("{FALLBACK_JSON}", json.dumps(fallback, indent=2)).replace(
        "{INPUT_PERSONA_JSON}", json.dumps(entry, ensure_ascii=False, indent=2)
    )


def normalized_words(text):
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    unaccented = "".join(character for character in decomposed if not unicodedata.combining(character))
    words = re.findall(r"\w+", unaccented)
    return " ".join("laboratory" if word == "lab" else word for word in words)


def validate_profile(profile, entry, config):
    if profile["persona_id"] != entry["persona_id"]:
        raise ValueError("Expanded persona ID differs from the source")
    source = re.fullmatch(
        r"An? (\d+)-year-old (female|male|non-binary)\s*(.+?) from (.+)",
        entry["persona"],
    )
    if source is None:
        raise ValueError("Unrecognized persona format")
    age, gender, occupation, location = source.groups()
    attributes = profile["profile_struct"]
    if attributes["age"] != int(age) or attributes["gender_identity"] != gender:
        raise ValueError("Expanded age or gender differs from the source")
    for field in ("ethnicity", "sexual_orientation"):
        allowed = set(config[field])
        if field == "sexual_orientation" and int(age) < 13:
            allowed = {"unspecified"}
        if attributes[field] not in allowed:
            raise ValueError(f"Invalid {field}: {attributes[field]}")
    biography = normalized_words(" ".join(profile["profile_narrative"]["personal_data"]))
    if normalized_words(occupation) not in biography or normalized_words(location) not in biography:
        raise ValueError("Expanded biography must include the source occupation and location")
    for section in SECTIONS:
        details = profile["profile_narrative"][section]
        if not isinstance(details, list) or not all(isinstance(item, str) for item in details) or len(details) < 5:
            raise ValueError(f"Expected at least five entries in {section}")


def prepare(entries):
    source = runpy.run_path(str(DREAM / "prompts_profile_extension.py"))
    config_dir = DREAM / "config"
    config = read_json(config_dir / "demographics_config.json")
    regions = read_json(config_dir / "m49_by_region.json")
    populations = source["load_populations"](str(config_dir / "population_by_country.json"))
    rng = random.Random(config.get("seed", 42))
    random.seed(config.get("seed", 42))
    fallbacks = {
        entry["id"]: source["sample_fallback"](config, regions, populations, rng)
        for entry in entries
    }
    return config, fallbacks


def render(entry, fallback, config, out, request):
    persona_id = entry["id"]
    path = out / str(persona_id)
    metadata_path = path / "metadata.json"
    source = {"persona_id": persona_id, "persona": entry["persona"]}
    settings = {
        "text_model": TEXT_MODEL,
        "source_blob": SOURCE_BLOB, "dream_commit": DREAM_COMMIT,
    }
    if metadata_path.exists():
        metadata = read_json(metadata_path)
        compared_settings = ("text_model", "source_blob", "dream_commit")
        if metadata["source"] != source or any(
            metadata["settings"].get(name) != settings[name] for name in compared_settings
        ):
            raise ValueError("Existing output has different inputs or settings; use a new output directory")
        if "profile" in metadata:
            validate_profile(metadata["profile"], source, config)
            return "enhanced already generated"
    else:
        metadata = {"source": source, "settings": settings, "synthetic_fallback": fallback}

    if "profile" not in metadata:
        pending_path = path / "expansion_response.json"
        if pending_path.exists():
            pending = read_json(pending_path)
        else:
            prompt = make_expansion(source, metadata["synthetic_fallback"], config)
            text, usage, model = generate_text(request, prompt, structured=True)
            pending = {"source": source, "settings": settings, "text": text, "usage": usage, "model": model}
            write_json(pending_path, pending)
        if pending["source"] != source or pending["settings"] != settings:
            raise ValueError("Saved expansion response has different inputs or settings")
        profile = json.loads(pending["text"])
        validate_profile(profile, source, config)
        metadata.update(profile=profile, expansion_usage=pending["usage"], expansion_model=pending["model"])
        write_json(metadata_path, metadata)

    return "enhanced generated"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "out")
    parser.add_argument("--quality", choices=("medium", "high"), help=argparse.SUPPRESS)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", help="Process all 200 personas")
    selection.add_argument("--ids", type=int, nargs="+", help="Process specific persona IDs")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without calling any API")
    args = parser.parse_args()
    entries = read_json(DATA)
    available = {entry["id"]: entry for entry in entries}
    if len(entries) != 200 or sorted(available) != list(range(200)):
        parser.error("Expected 200 unique IDs from 0 through 199")
    ids = list(available) if args.all else (args.ids or list(range(0, 200, 20)))
    if len(ids) != len(set(ids)) or any(value not in available for value in ids):
        parser.error("Use unique persona IDs between 0 and 199")
    config, fallbacks = prepare(entries)
    if args.dry_run:
        for persona_id in ids:
            entry = available[persona_id]
            make_expansion({"persona_id": persona_id, "persona": entry["persona"]}, fallbacks[persona_id], config)
        print(f"Validated {len(ids)} inputs for enhanced profiles.")
        return 0

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        parser.error("Set OPENAI_API_KEY in your environment to enable generation")

    for persona_id in ids:
        def request(endpoint, payload):
            return tracked_request(key, args.output / "usage.jsonl", persona_id, endpoint, payload)

        try:
            result = render(available[persona_id], fallbacks[persona_id], config, args.output, request)
            print(f"{persona_id}: {result}", flush=True)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"Persona {persona_id}, stopped: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    if os.environ.get("PYTHONHASHSEED") != "0":
        # DREAM's fallback sampler uses sets. Stabilize their order across processes.
        os.environ["PYTHONHASHSEED"] = "0"
        raise SystemExit(subprocess.call([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]))
    raise SystemExit(main())

"""LLM-labeler voor slice B: labelt label_sample_1500 met Claude (Haiku).

- Prompt: tagging/llm_prompt_draft.txt (placeholders {vacancy_id}, {title}, {text}).
- Model: standaard claude-haiku-5-5. Sonnet en Opus worden geweigerd (budget).
- Eén call per vacature. Retries met exponentiële backoff bij tijdelijke fouten
  (429, 5xx, netwerk) en bij ongeldige JSON-antwoorden.
- Elke call (ook mislukte) wordt gelogd naar logs/claude_usage.csv (append),
  met input- en output-tokens.
- Voortgang wordt per vacature weggeschreven naar een checkpoint (jsonl).
  Als de run stopt, hervat je met hetzelfde commando: afgeronde vacatures worden overgeslagen.
- Uitvoer: claude_labels_1500.parquet.

API-sleutel: env-var ANTHROPIC_API_KEY, of een regel ANTHROPIC_API_KEY=... in <repo>/.env.
Sla de sleutel nooit op in code, git of chat.

Draaien:
  python run_claude_labeler.py                      # echt (vereist sleutel)
  python run_claude_labeler.py --mock --limit 3 \\
      --out /tmp/x.parquet --usage-csv /tmp/u.csv --checkpoint /tmp/c.jsonl  # test zonder API
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.paths import (  # noqa: E402
    CLAUDE_CHECKPOINT_JSONL,
    CLAUDE_LABELS_PARQUET,
    CLAUDE_USAGE_CSV,
    DATA_WORK,
    LABEL_SAMPLE_PARQUET,
    LOG_DIR,
    PROMPT_TXT,
    REPO_ROOT,
)
from baseline import tag_text  # noqa: E402  (alleen voor de mock-responder)

SCRIPT = "run_claude_labeler"
DEFAULT_MODEL = "claude-haiku-5-5"
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
ALLOWED_TYPES = ("builder", "user", "governor", "none")
MAX_TEXT_CHARS = 6000
# Ruim genoeg dat het model niet midden in het antwoord wordt afgekapt.
# De testrun gaf precies 200 output-tokens bij elke parse-fout: het antwoord was afgekapt.
MAX_OUTPUT_TOKENS = 1024
RAW_PREVIEW_CHARS = 400
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
USAGE_FIELDS = [
    "timestamp", "script", "model", "vacancy_id", "attempt",
    "input_tokens", "output_tokens", "status",
]


class ApiError(Exception):
    """Fout van de API met HTTP-statuscode."""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status


class FatalApiError(Exception):
    """Niet-herstelbare fout (bv. ongeldige sleutel). De run stopt."""


class ParseError(ValueError):
    """Antwoord van het model is geen geldig labelobject."""


@dataclass
class Config:
    model: str
    delay: float
    max_attempts: int
    backoff_base: float
    usage_csv: Path
    checkpoint: Path
    limit: int | None


# --- Hulpfuncties -------------------------------------------------------------
def check_model(model: str) -> None:
    low = model.lower()
    if "haiku" not in low or any(w in low for w in ("sonnet", "opus")):
        raise SystemExit(
            f"Model '{model}' is niet toegestaan. Deze labeler gebruikt alleen Haiku "
            f"(standaard {DEFAULT_MODEL})."
        )


def load_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(
        "Geen ANTHROPIC_API_KEY gevonden (env-var of regel in <repo>/.env)."
    )


def _as_text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value)


def render_prompt(template: str, vacancy_id, title, text) -> str:
    """Vult de drie placeholders in. Andere accolades (bv. het JSON-voorbeeld) blijven staan."""
    values = {
        "vacancy_id": _as_text(vacancy_id),
        "title": _as_text(title),
        "text": _as_text(text)[:MAX_TEXT_CHARS],
    }
    return re.sub(
        r"\{(vacancy_id|title|text)\}", lambda m: values[m.group(1)], template
    )


_FENCE_RE = re.compile(r"```[a-zA-Z]*")


def extract_json(raw: str) -> dict:
    """Haalt het eerste JSON-object uit een modelantwoord.

    Stript Markdown-codeblokken (```json ... ```) en tekst ervoor of erna.
    """
    text = _FENCE_RE.sub("", raw or "")
    decoder = json.JSONDecoder()
    last_exc = None
    # Probeer elke '{' tot er een geldig JSON-object begint (tekst kan eigen accolades bevatten).
    for match in re.finditer(r"\{", text):
        try:
            obj, _end = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError as exc:
            last_exc = exc
            continue
        if isinstance(obj, dict):
            return obj
    if last_exc is None:
        raise ParseError("geen JSON-object in antwoord")
    raise ParseError(f"ongeldige JSON: {last_exc}")


def parse_label(raw: str) -> dict:
    """Haalt het JSON-object uit het antwoord en valideert het."""
    obj = extract_json(raw)

    has_ai = obj.get("has_ai")
    ai_type = obj.get("ai_type")
    conf = obj.get("confidence")
    if not isinstance(has_ai, bool):
        raise ParseError("has_ai is geen bool")
    if ai_type not in ALLOWED_TYPES:
        raise ParseError(f"ai_type onbekend: {ai_type!r}")
    if has_ai != (ai_type != "none"):
        raise ParseError("has_ai en ai_type spreken elkaar tegen")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
        raise ParseError(f"confidence ongeldig: {conf!r}")
    return {"has_ai": has_ai, "ai_type": ai_type, "confidence": float(conf)}


def log_usage(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=USAGE_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


# --- API ----------------------------------------------------------------------
def api_call(prompt: str, model: str, api_key: str, timeout: float = 60.0):
    """Eén Messages-API-call. Geeft (tekst, input_tokens, output_tokens)."""
    body = json.dumps({
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code, exc.read().decode("utf-8", "replace")[:300]) from exc

    text = "".join(
        block.get("text", "") for block in data.get("content", [])
        if block.get("type") == "text"
    )
    usage = data.get("usage", {})
    return text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def mock_call(prompt: str):
    """Nep-model voor tests: labelt met de keyword-basislijn. Kost niets."""
    vid = re.search(r"vacancy_id:\s*(\S+)", prompt).group(1)
    title = re.search(r"title:\s*(.*)", prompt).group(1)
    text = re.search(r"text:\s*(.*)", prompt, re.DOTALL).group(1)
    has_ai, ai_type = tag_text(f"{title} {text}")
    out = json.dumps({
        "vacancy_id": vid,
        "has_ai": has_ai,
        "ai_type": ai_type,
        "confidence": 0.9,
    })
    return out, len(prompt) // 4, len(out) // 4


# --- Labelen ------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def label_one(vacancy_id, title, text, template, call, cfg: Config) -> dict:
    """Labelt één vacature met retries. Geeft een record terug; gooit FatalApiError bij fatale fouten."""
    prompt = render_prompt(template, vacancy_id, title, text)
    last_error = None

    for attempt in range(1, cfg.max_attempts + 1):
        base_row = {
            "timestamp": _now(), "script": SCRIPT, "model": cfg.model,
            "vacancy_id": vacancy_id, "attempt": attempt,
        }
        try:
            raw, tin, tout = call(prompt)
        except ApiError as exc:
            log_usage(cfg.usage_csv, {**base_row, "input_tokens": 0,
                                      "output_tokens": 0, "status": f"api_error_{exc.status}"})
            print(f"    poging {attempt}: API-fout: {exc}", file=sys.stderr)
            if exc.status not in RETRYABLE_STATUS:
                raise FatalApiError(str(exc)) from exc
            last_error = f"api_error_{exc.status}: {exc}"[:RAW_PREVIEW_CHARS]
            time.sleep(cfg.backoff_base ** attempt)
            continue
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            log_usage(cfg.usage_csv, {**base_row, "input_tokens": 0,
                                      "output_tokens": 0, "status": "net_error"})
            print(f"    poging {attempt}: netwerkfout: {type(exc).__name__}: {exc}", file=sys.stderr)
            last_error = f"net_error: {type(exc).__name__}: {exc}"[:RAW_PREVIEW_CHARS]
            time.sleep(cfg.backoff_base ** attempt)
            continue

        try:
            label = parse_label(raw)
        except ParseError as exc:
            log_usage(cfg.usage_csv, {**base_row, "input_tokens": tin,
                                      "output_tokens": tout, "status": "parse_error"})
            preview = (raw or "")[:RAW_PREVIEW_CHARS]
            print(f"    poging {attempt}: parse-fout: {exc}\n"
                  f"    ruw antwoord ({tout} output-tokens): {preview!r}", file=sys.stderr)
            last_error = f"parse_error: {exc} | ruw: {preview}"
            time.sleep(cfg.backoff_base)
            continue

        log_usage(cfg.usage_csv, {**base_row, "input_tokens": tin,
                                  "output_tokens": tout, "status": "ok"})
        return {**label, "parse_ok": True, "attempts": attempt, "error": None}

    return {"has_ai": None, "ai_type": None, "confidence": None,
            "parse_ok": False, "attempts": cfg.max_attempts, "error": last_error}


def load_checkpoint(path: Path) -> dict:
    """Geeft alleen de geslaagde vacatures terug (parse_ok). Mislukte rijen worden opnieuw geprobeerd.

    Bij meerdere regels voor dezelfde vacature wint de laatste.
    """
    done = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            vid = str(rec["vacancy_id"])
            if rec.get("parse_ok"):
                done[vid] = rec
            else:
                done.pop(vid, None)
    return done


def run(df: pd.DataFrame, template: str, call, cfg: Config) -> dict:
    """Labelt alle nog niet gedane vacatures. Schrijft na elke vacature naar het checkpoint."""
    done = load_checkpoint(cfg.checkpoint)
    cfg.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    new_this_run = 0

    with cfg.checkpoint.open("a", encoding="utf-8") as ckpt:
        for row in df.itertuples(index=False):
            vid = str(row.vacancy_id)
            if vid in done:
                continue
            if cfg.limit is not None and new_this_run >= cfg.limit:
                break
            rec = label_one(vid, row.title, row.text, template, call, cfg)
            rec = {"vacancy_id": vid, "model": cfg.model, **rec}
            ckpt.write(json.dumps(rec, ensure_ascii=False) + "\n")
            ckpt.flush()
            done[vid] = rec
            new_this_run += 1
            if rec["parse_ok"]:
                print(f"[{new_this_run}] {vid}: ok {rec['ai_type']} (pogingen: {rec['attempts']})")
            else:
                print(f"[{new_this_run}] {vid}: MISLUKT na {rec['attempts']} pogingen. "
                      f"Laatste fout: {rec['error']}", file=sys.stderr)
            if cfg.delay > 0:
                time.sleep(cfg.delay)
    return done


def write_output(df: pd.DataFrame, done: dict, out_path: Path) -> pd.DataFrame:
    recs = [done[str(v)] for v in df["vacancy_id"].astype(str) if str(v) in done]
    res = pd.DataFrame(recs)
    res["vacancy_id"] = res["vacancy_id"].astype(str)
    res["has_ai"] = res["has_ai"].astype("boolean")
    res["ai_type"] = res["ai_type"].astype("object")
    res["confidence"] = res["confidence"].astype("float64")
    res["source"] = "claude"
    res["parse_ok"] = res["parse_ok"].astype(bool)
    res["attempts"] = res["attempts"].astype(int)
    res = res[["vacancy_id", "has_ai", "ai_type", "confidence", "source",
               "model", "parse_ok", "attempts", "error"]].reset_index(drop=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    res.to_parquet(out_path, index=False)
    return res


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Labelt de labelset met Claude (Haiku).")
    p.add_argument("--input", type=Path, default=LABEL_SAMPLE_PARQUET)
    p.add_argument("--out", type=Path, default=None,
                   help="Standaard: claude_labels_1500.parquet (mock: mock_claude_labels.parquet)")
    p.add_argument("--prompt", type=Path, default=PROMPT_TXT)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--delay", type=float, default=0.3, help="Pauze tussen vacatures (s)")
    p.add_argument("--max-attempts", type=int, default=4)
    p.add_argument("--backoff-base", type=float, default=2.0)
    p.add_argument("--limit", type=int, default=None,
                   help="Maximaal aantal nieuwe vacatures in deze run (voor tests)")
    p.add_argument("--usage-csv", type=Path, default=None)
    p.add_argument("--checkpoint", type=Path, default=None)
    p.add_argument("--mock", action="store_true",
                   help="Geen API-call; labelt met de keyword-basislijn (voor tests)")
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    check_model(args.model)

    # In mock-modus gaan uitvoer en logs naar aparte bestanden, zodat de echte niet vervuild raken.
    if args.mock:
        out = args.out or DATA_WORK / "mock_claude_labels.parquet"
        usage = args.usage_csv or LOG_DIR / "mock_claude_usage.csv"
        checkpoint = args.checkpoint or LOG_DIR / "mock_claude_checkpoint.jsonl"
        call = mock_call
        api_key = None
    else:
        out = args.out or CLAUDE_LABELS_PARQUET
        usage = args.usage_csv or CLAUDE_USAGE_CSV
        checkpoint = args.checkpoint or CLAUDE_CHECKPOINT_JSONL
        api_key = load_api_key()
        call = lambda prompt: api_call(prompt, args.model, api_key)  # noqa: E731

    cfg = Config(
        model="mock" if args.mock else args.model,
        delay=args.delay,
        max_attempts=args.max_attempts,
        backoff_base=args.backoff_base,
        usage_csv=usage,
        checkpoint=checkpoint,
        limit=args.limit,
    )

    df = pd.read_parquet(args.input)
    template = args.prompt.read_text(encoding="utf-8")
    print(f"{len(df)} vacatures, model={cfg.model}, uitvoer={out}")

    try:
        done = run(df, template, call, cfg)
    except FatalApiError as exc:
        print(f"STOP: niet-herstelbare API-fout: {exc}")
        print(f"Voortgang staat in {checkpoint}; hervat met hetzelfde commando.")
        raise SystemExit(1)

    res = write_output(df, done, out)
    print(f"\nGeschreven: {out} ({len(res)} rijen, "
          f"waarvan {int((~res['parse_ok']).sum())} mislukt)")
    print(res["ai_type"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()

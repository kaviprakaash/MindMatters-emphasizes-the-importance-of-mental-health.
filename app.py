from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from models import get_db, init_db
from datetime import datetime
import json
import urllib.request
import urllib.error
import urllib.parse
import traceback
import random
import re
import time
import io
import threading
import uuid
import secrets

import requests
from google_auth_oauthlib.flow import Flow
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change')
# So https:// and host are correct behind Railway / Render / nginx (needed for OAuth redirect URLs).
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

GOOGLE_OAUTH_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '').strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', '').strip()
# Optional: exact callback URL if auto-detected url_for is wrong (local: http://127.0.0.1:5000/auth/google/callback).
OAUTH_REDIRECT_URI = os.environ.get('OAUTH_REDIRECT_URI', '').strip()


def _google_oauth_configured():
    return bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)


def _google_redirect_uri():
    if OAUTH_REDIRECT_URI:
        return OAUTH_REDIRECT_URI.rstrip('/')
    return url_for('auth_google_callback', _external=True)


def _google_flow(redirect_uri):
    return Flow.from_client_config(
        {
            'web': {
                'client_id': GOOGLE_OAUTH_CLIENT_ID,
                'client_secret': GOOGLE_OAUTH_CLIENT_SECRET,
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [redirect_uri],
            }
        },
        scopes=[
            'openid',
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile',
        ],
        redirect_uri=redirect_uri,
    )


def _oauth_pick_username(db, email, google_sub):
    raw = (email or '').split('@')[0]
    base = re.sub(r'[^a-zA-Z0-9_]', '_', raw)[:20].strip('_') or 'user'
    for attempt in range(40):
        candidate = base if attempt == 0 else f'{base[:14]}_{attempt}'
        candidate = candidate[:32]
        if not db.execute('SELECT 1 FROM users WHERE username = ?', (candidate,)).fetchone():
            return candidate
    tail = (google_sub or '')[-6:] or secrets.token_hex(4)
    return f'g_{tail}'[:32]

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '').strip()
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
AI_PROVIDER = os.environ.get('AI_PROVIDER', 'auto').strip().lower()  # auto | openai | ollama
OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'llama3.1:8b')
# Optional: if Ollama sits behind a reverse proxy that requires a bearer token.
OLLAMA_API_KEY = os.environ.get('OLLAMA_API_KEY', '').strip()


def _ollama_http_headers():
    h = {'Content-Type': 'application/json'}
    if OLLAMA_API_KEY:
        h['Authorization'] = f'Bearer {OLLAMA_API_KEY}'
    return h
# Env vars set on common PaaS — used to avoid defaulting to 127.0.0.1 Ollama (nothing listening).
_CLOUD_ENV_MARKERS = (
    'RENDER', 'RAILWAY_ENVIRONMENT', 'RAILWAY_PROJECT_ID', 'FLY_APP_NAME',
    'HEROKU_APP_NAME', 'DYNO', 'K_SERVICE', 'AWS_EXECUTION_ENV',
    'GAE_ENV', 'WEBSITE_INSTANCE_ID', 'VERCEL', 'CODESPACES',
)


def _is_likely_cloud_host():
    return any(os.environ.get(k) for k in _CLOUD_ENV_MARKERS)


def _ollama_url_looks_local():
    try:
        parsed = urllib.parse.urlparse((OLLAMA_BASE_URL or 'http://127.0.0.1:11434').strip() + '/')
        host = (parsed.hostname or '').lower()
        return host in ('127.0.0.1', 'localhost', '::1', '')
    except Exception:
        return True


def _ollama_reachable_in_this_runtime():
    """
    Hosted containers have no local Ollama unless OLLAMA_BASE_URL points elsewhere.
    Set ALLOW_LOCAL_OLLAMA=1 to force trying loopback Ollama (unusual).
    """
    if os.environ.get('ALLOW_LOCAL_OLLAMA', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        return True
    if not _ollama_url_looks_local():
        return True
    if _is_likely_cloud_host():
        return False
    return True


def _ai_not_configured_message():
    return (
        "AI isn’t configured for this deployment. Options: (1) Set OPENAI_API_KEY, or (2) Run Ollama on a "
        "separate server or Docker host and set OLLAMA_BASE_URL to that base URL (https://…), not 127.0.0.1. "
        "Cloud web hosts do not bundle Ollama inside the same small container; use Docker Compose on a VPS "
        "or a tunnel (e.g. ngrok) to a machine with Ollama. Optional: OLLAMA_API_KEY for authenticated proxies."
    )


def _effective_llm_mode():
    """openai | ollama | unconfigured — for AI_PROVIDER / auto without local Ollama on cloud."""
    base = (AI_PROVIDER or 'auto').strip().lower()
    if base not in ('auto', 'openai', 'ollama'):
        base = 'auto'
    if base == 'auto':
        if OPENAI_API_KEY:
            return 'openai'
        if _ollama_reachable_in_this_runtime():
            return 'ollama'
        return 'unconfigured'
    if base == 'openai':
        return 'openai' if OPENAI_API_KEY else 'unconfigured'
    if base == 'ollama':
        return 'ollama' if _ollama_reachable_in_this_runtime() else 'unconfigured'
    return 'unconfigured'

OPENFDA_BASE_URL = "https://api.fda.gov/drug/label.json"
# Optional: https://open.fda.gov/apis/authentication/ — raises rate limits and can reduce failed requests.
OPENFDA_API_KEY = os.environ.get('OPENFDA_API_KEY', '').strip()
MEDICATION_DISCLAIMER = "This information is for educational purposes only and not medical advice."
RXNAV_BASE_URL = "https://rxnav.nlm.nih.gov/REST"
MEDICATION_CACHE_DAYS = int(os.environ.get('MEDICATION_CACHE_DAYS', '30'))
# Increment (or set env) when lookup/cache semantics change so old rows are ignored.
MEDICATION_CACHE_KEY_VERSION = os.environ.get('MEDICATION_CACHE_KEY_VERSION', '3').strip()

def _medication_cache_storage_key(normalized_query):
    v = MEDICATION_CACHE_KEY_VERSION or '1'
    return f"{v}:{normalized_query}"
# Refine FDA/fallback text with LLM for readability (facts must stay grounded in provided text).
# Default off so lookups finish quickly if Ollama/OpenAI is slow or not configured.
MEDICATION_USE_LLM = os.environ.get('MEDICATION_USE_LLM', '0').strip().lower() not in ('0', 'false', 'no', 'off')
MEDICATION_LLM_TIMEOUT_OPENAI = float(os.environ.get('MEDICATION_LLM_TIMEOUT_OPENAI', '35'))
MEDICATION_LLM_TIMEOUT_OLLAMA = float(os.environ.get('MEDICATION_LLM_TIMEOUT_OLLAMA', '35'))
# Leave empty to follow AI_PROVIDER; set to "ollama" or "openai" to force medication refinement provider.
MEDICATION_LLM_PROVIDER = os.environ.get('MEDICATION_LLM_PROVIDER', '').strip().lower()
# Text-only medication summary via Ollama (no OpenFDA / drug_cache).
MEDICATION_OLLAMA_TIMEOUT = float(os.environ.get('MEDICATION_OLLAMA_TIMEOUT', '120'))
ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}

# Whole-campus group lounge (single room id).
CAMPUS_LOUNGE_ROOM_ID = "general"
CAMPUS_CHAT_BODY_MAX = 500
CAMPUS_CHAT_NICK_MAX = 24
CAMPUS_CHAT_POLL_LIMIT = 120
RANDOM_CHAT_BODY_MAX = 500
RANDOM_MATCH_LOCK = threading.Lock()

# Initialize DB
init_db()

# -----------------------------
# 🧠 SYSTEM PROMPT (HUMAN-LIKE)
# -----------------------------
def build_system_prompt():
    return (
        "You are a real human listener, not an AI. "
        "Talk like a close friend who genuinely cares. "
        "Avoid sounding like a therapist or giving textbook advice. "
        "Do not follow fixed patterns. "
        "Sometimes be short, sometimes expressive. "
        "Sometimes ask questions, sometimes just listen. "
        "Be warm, natural, and slightly imperfect."
    )

# -----------------------------
# 🚨 CRISIS DETECTION
# -----------------------------
def detect_crisis(message):
    text = message.lower()
    keywords = [
        "want to die", "kill myself", "suicide",
        "end my life", "better off dead",
        "hurt myself", "self harm"
    ]
    return any(k in text for k in keywords)

def crisis_response():
    return (
        "Hey… I’m really glad you said this out loud. "
        "You don’t have to go through it alone.\n\n"
        "If you feel like you might act on these thoughts, please call your local emergency number immediately.\n"
        "In India, you can call Tele-MANAS: 14416 or 1-800-891-4416.\n\n"
        "Are you safe right now?"
    )

# -----------------------------
# 🤖 OPENAI RESPONSE
# -----------------------------
def generate_ai_response(message, history_turns):
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")

    messages = [{"role": "system", "content": build_system_prompt()}]

    # Add chat memory
    messages.extend(history_turns[-6:])

    messages.append({"role": "user", "content": message})

    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.9,
        "max_tokens": 250
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())

    return data["choices"][0]["message"]["content"].strip()

def generate_ollama_response(message, history_turns):
    """Generate response from local Ollama server (no API key required)."""
    messages = [{"role": "system", "content": build_system_prompt()}]
    messages.extend(history_turns[-6:])
    messages.append({"role": "user", "content": message})

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.85
        }
    }

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers=_ollama_http_headers(),
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        if _ollama_url_looks_local() and (
            _is_likely_cloud_host() or 'Connection refused' in str(e) or 'Errno 111' in str(e)
        ):
            raise RuntimeError(_ai_not_configured_message()) from e
        raise RuntimeError(
            "Could not reach Ollama. Start it with `ollama serve` and pull a model "
            f"like `ollama pull {OLLAMA_MODEL}`. Error: {e}"
        ) from e

    content = data.get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("Ollama returned an empty response.")
    return content

def _llm_single_turn(
    system_prompt,
    user_message,
    max_tokens=400,
    temperature=0.75,
    provider_override=None,
    timeout_openai=None,
    timeout_ollama=None,
    ollama_format_json=False,
):
    """One-shot chat completion (OpenAI or Ollama). provider_override: 'openai' | 'ollama' | None (use AI_PROVIDER)."""
    to_openai = 45 if timeout_openai is None else timeout_openai
    to_ollama = 90 if timeout_ollama is None else timeout_ollama
    ov = provider_override
    if ov in ('openai', 'ollama'):
        if ov == 'openai' and not OPENAI_API_KEY:
            provider = 'unconfigured'
        elif ov == 'ollama' and not _ollama_reachable_in_this_runtime():
            provider = 'unconfigured'
        else:
            provider = ov
    else:
        provider = _effective_llm_mode()

    if provider == 'unconfigured':
        raise RuntimeError(_ai_not_configured_message())

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    if provider == 'openai':
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set")
        payload = {
            "model": OPENAI_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_API_KEY}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=to_openai) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"].strip()

    if provider == 'ollama':
        predict = max(256, min(int(max_tokens), 8192))
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": float(temperature),
                "num_predict": predict,
            },
        }
        if ollama_format_json:
            payload["format"] = "json"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/chat",
            data=body,
            headers=_ollama_http_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=to_ollama) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            detail = raw.strip()[:800]
            try:
                err_obj = json.loads(raw)
                detail = str(err_obj.get("error") or err_obj.get("message") or detail)
            except (json.JSONDecodeError, TypeError):
                pass
            raise RuntimeError(f"Ollama returned HTTP {e.code}: {detail}") from e
        content = data.get("message", {}).get("content", "").strip()
        if not content:
            raise RuntimeError("Ollama returned an empty response.")
        return content

    raise ValueError("Invalid AI provider resolution.")

def _parse_json_object_from_llm(text):
    """Extract first JSON object from model output (strips markdown fences if present)."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(t[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None

MEDICATION_REFINE_SYSTEM = (
    "You are a medical information editor. The user message is a JSON object with drug facts from an official-style "
    "label excerpt (OpenFDA or a small fallback dataset)—not a full prescription.\n"
    "Output ONLY one JSON object (no markdown, no code fences) with keys: use, side_effects, safety_warnings. "
    "Each value is a plain string for a general reader.\n"
    "Rules:\n"
    "- Base every sentence ONLY on the input fields. Do not invent doses, scheduling, interactions, diagnoses, or new risks.\n"
    "- If an input field is empty or says 'Not available', use: 'Not detailed in this excerpt.'\n"
    "- Use clear, calm language. At most 4-6 short sentences per field. No markdown bullets.\n"
    "- Do not tell the user what to do with their medicine; only summarize what the excerpt says.\n"
    "- Keep the same drug name context; do not substitute a different drug."
)

def refine_medication_with_llm(drug_name, data_source, use, side_effects, safety_warnings):
    """
    Rewrite OpenFDA/fallback strings for readability using OpenAI or Ollama.
    Returns dict with keys use, side_effects, safety_warnings or None.
    """
    if not MEDICATION_USE_LLM:
        return None
    prov = MEDICATION_LLM_PROVIDER if MEDICATION_LLM_PROVIDER in ('openai', 'ollama') else None
    payload = json.dumps({
        "drug_name": drug_name,
        "data_source": data_source,
        "use": use,
        "side_effects": side_effects,
        "safety_warnings": safety_warnings,
    }, ensure_ascii=False)
    try:
        raw = _llm_single_turn(
            MEDICATION_REFINE_SYSTEM,
            payload,
            max_tokens=900,
            temperature=0.25,
            provider_override=prov,
            timeout_openai=MEDICATION_LLM_TIMEOUT_OPENAI,
            timeout_ollama=MEDICATION_LLM_TIMEOUT_OLLAMA,
        )
        obj = _parse_json_object_from_llm(raw)
        if not obj:
            return None
        out = {}
        for key in ('use', 'side_effects', 'safety_warnings'):
            val = str(obj.get(key, '')).strip()
            if val:
                out[key] = val
        if len(out) == 3:
            return out
    except Exception as ex:
        print('Medication LLM refine failed:', ex)
    return None

def apply_medication_llm_refine(result):
    """Attach LLM-polished fields to a successful medication result dict."""
    if not result or not result.get('found'):
        return result
    try:
        refined = refine_medication_with_llm(
            result.get('drug_name', ''),
            result.get('source', ''),
            result.get('use', ''),
            result.get('side_effects', ''),
            result.get('safety_warnings', ''),
        )
        if not refined:
            return result
        merged = {**result, **refined}
        merged['refined_by_llm'] = True
        return merged
    except Exception as ex:
        print("Medication refine skipped:", ex)
        return result

OVERthinking_JSON_SYSTEM = (
    "You are a warm, practical mental wellness coach helping someone break overthinking. "
    "Reply with ONLY one JSON object (no markdown, no code fences, no extra text). "
    "Use exactly these keys: worst_case, realistic, action. "
    "Each value is a short plain string (2-4 sentences). "
    "worst_case: acknowledge the scary story their mind might be telling. "
    "realistic: a compassionate, grounded perspective—no toxic positivity. "
    "action: one small concrete step they can take in the next hour."
)

def generate_overthinking_analysis(thought):
    """
    Natural overthinking breakdown via OpenAI or Ollama.
    Returns dict with keys worst_case, realistic, action, or None on failure.
    """
    thought = (thought or "").strip()
    if not thought:
        return None
    try:
        raw = _llm_single_turn(
            OVERthinking_JSON_SYSTEM,
            f"What they're stuck on:\n{thought}",
            max_tokens=500,
            temperature=0.75,
        )
        obj = _parse_json_object_from_llm(raw)
        if not obj:
            return None
        wc = str(obj.get("worst_case", "")).strip()
        rl = str(obj.get("realistic", "")).strip()
        ac = str(obj.get("action", "")).strip()
        if wc and rl and ac:
            return {"worst_case": wc, "realistic": rl, "action": ac}
    except Exception as ex:
        print("Overthinking LLM error:", ex)
    return None

def template_overthinking_analysis(thought):
    """Simple non-LLM fallback (original behavior)."""
    return {
        "worst_case": f"Worst case: {thought}.",
        "realistic": "Most realistic case: it may be difficult, but manageable step by step.",
        "action": "Next helpful step: pick one small action you can do in the next 10 minutes.",
    }

# -----------------------------
# 💊 MEDICATION INFO MODULE
# -----------------------------
def clean_medicine_name(raw_name):
    """Normalize medicine name and remove dosage/units."""
    text = (raw_name or "").strip().lower()
    # Remove strength patterns like 12.5mg, 500 mg, 10ml, 2%
    text = re.sub(r"\b\d+(\.\d+)?\s*(mg|mcg|g|ml|iu|%)\b", " ", text)
    # Remove common release/variant markers (helps RxNorm matching).
    text = re.sub(r"\b(cr|er|xr|sr|dr)\b", " ", text)
    # Remove common dosage form words to improve matching
    text = re.sub(
        r"\b(tablet|tablets|capsule|capsules|syrup|injection|cream|gel|drops)\b",
        " ",
        text
    )
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Keep only plausible medicine-like tokens.
    tokens = [t for t in text.split() if not t.isdigit() and len(t) > 1]
    text = " ".join(tokens).strip()
    return text

MEDICATION_OLLAMA_SYSTEM = (
    "You summarize medications for educational purposes only - not medical advice.\n"
    "The user gives a medicine name (brand or generic; may include dose - ignore dose for your summary).\n"
    "Output exactly ONE JSON object (no markdown, no code fences) with exactly two string keys:\n"
    '- "use": 2-5 short plain-language sentences on typical therapeutic uses / drug class.\n'
    '- "side_effects": 2-5 short sentences on commonly reported side effects (not exhaustive).\n'
    "Rules:\n"
    "- Use only well-established general knowledge. Do not invent doses, schedules, or rare serious risks.\n"
    "- If the name is unclear, not a medication, or you are unsure, set BOTH fields to one sentence asking the user to "
    "verify the name with a pharmacist or clinician.\n"
    "- No bullet characters; no diagnosis or instructions to start/stop medication.\n"
)

def ollama_medication_lookup(raw_name):
    """Return use + side_effects from local Ollama (text input only)."""
    raw = (raw_name or "").strip()
    if not raw:
        return {
            "found": False,
            "message": "Enter a medicine name.",
            "disclaimer": MEDICATION_DISCLAIMER,
        }
    user_line = f'Medication name: "{raw}"'
    try:
        text = _llm_single_turn(
            MEDICATION_OLLAMA_SYSTEM,
            user_line,
            max_tokens=900,
            temperature=0.3,
            provider_override="ollama",
            timeout_ollama=MEDICATION_OLLAMA_TIMEOUT,
            ollama_format_json=True,
        )
    except Exception as ex:
        ex_s = str(ex).lower()
        if _is_likely_cloud_host() or 'connection refused' in ex_s or 'errno 111' in ex_s:
            msg = (
                "This path needs a local Ollama server, which hosted apps don’t have. "
                "Use Get Medication Info on the latest deploy—it uses the FDA database instead. "
                f"If you still see this, redeploy. Technical detail: {ex}"
            )
        else:
            msg = (
                "If `ollama serve` says the address is already in use, Ollama is already running—"
                f"confirm `ollama list` includes `{OLLAMA_MODEL}`. Details: {ex}"
            )
        return {
            "found": False,
            "message": msg,
            "disclaimer": MEDICATION_DISCLAIMER,
        }
    obj = _parse_json_object_from_llm(text)
    if not obj:
        return {
            "found": False,
            "message": "Could not read the model response. Try again with a simpler drug name.",
            "disclaimer": MEDICATION_DISCLAIMER,
        }
    use = str(obj.get("use", "")).strip()
    side_effects = str(obj.get("side_effects", "")).strip()
    if not use and not side_effects:
        return {
            "found": False,
            "message": "No summary was returned. Try again.",
            "disclaimer": MEDICATION_DISCLAIMER,
        }
    return {
        "found": True,
        "drug_name": raw[:200],
        "use": use,
        "side_effects": side_effects,
        "source": "ollama",
        "disclaimer": MEDICATION_DISCLAIMER,
    }

def _first_text(value):
    """Return first string from OpenFDA list/string fields."""
    if isinstance(value, list) and value:
        return str(value[0]).strip()
    if isinstance(value, str):
        return value.strip()
    return ""

def _clean_label_text(text):
    """Clean noisy label text from OpenFDA sections."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(text))
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _summarize_label_text(text, max_chars=360):
    """Return a readable concise summary from long OpenFDA text."""
    cleaned = _clean_label_text(text)
    if not cleaned:
        return ""
    # Take first 2 sentence-like chunks to avoid giant paragraphs.
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    brief = " ".join(parts[:2]).strip() if parts else cleaned
    if len(brief) > max_chars:
        brief = brief[:max_chars].rsplit(" ", 1)[0] + "..."
    return brief

def _openfda_request(search_query, limit=5):
    q = [("search", search_query), ("limit", str(limit))]
    if OPENFDA_API_KEY:
        q.append(("api_key", OPENFDA_API_KEY))
    url = f"{OPENFDA_BASE_URL}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("error") and not payload.get("results"):
            return {"results": []}
        return payload
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        print("OpenFDA HTTPError", e.code, body[:300])
        return {"results": []}
    except urllib.error.URLError as e:
        print("OpenFDA URLError", e)
        return {"results": [], "_req_error": "network"}

def fetch_openfda_drug_data(clean_name):
    """Fetch drug label details from OpenFDA (exact match first, then broader search)."""
    if not clean_name:
        return None

    safe_term = str(clean_name).replace('"', '').strip()
    if not safe_term:
        return None

    # 1) Exact fields — good when name matches FDA strings exactly.
    exact_q = (
        f'(openfda.generic_name.exact:"{safe_term}" '
        f'OR openfda.brand_name.exact:"{safe_term}" '
        f'OR openfda.substance_name.exact:"{safe_term}")'
    )
    try:
        payload = _openfda_request(exact_q, limit=5)
        if payload.get("_req_error"):
            return payload
        if payload and (payload.get("results") or []):
            return payload
    except Exception:
        pass

    # 2) Phrase search — catches "sertraline" vs labels filed as "SERTRALINE HYDROCHLORIDE", etc.
    broad_q = (
        f'(openfda.generic_name:"{safe_term}" '
        f'OR openfda.brand_name:"{safe_term}" '
        f'OR openfda.substance_name:"{safe_term}")'
    )
    try:
        payload = _openfda_request(broad_q, limit=12)
        if payload.get("_req_error"):
            return payload
        return payload
    except Exception as ex:
        print("OpenFDA broad query failed:", ex)
        return {"results": []}

def _openfda_all_name_strings(item):
    """Lowercase drug name strings from openfda block and product rows (for relevance scoring)."""
    names = []
    o = item.get("openfda") if isinstance(item.get("openfda"), dict) else {}
    for key in ("generic_name", "brand_name", "substance_name"):
        val = o.get(key, [])
        if isinstance(val, list):
            names.extend([str(v).lower() for v in val])
        elif isinstance(val, str) and val.strip():
            names.append(val.lower())
    for p in item.get("products") or []:
        if not isinstance(p, dict):
            continue
        for key in ("brand_name", "generic_name"):
            v = p.get(key)
            if isinstance(v, str) and v.strip():
                names.append(v.lower())
        for ing in p.get("active_ingredient") or []:
            if isinstance(ing, dict):
                n = ing.get("name")
                if n:
                    names.append(str(n).lower())
            elif isinstance(ing, str) and ing.strip():
                names.append(ing.lower())
    return names

def _openfda_name_match_strength(item, query_term):
    """Non-zero iff generic/brand/substance metadata overlaps the search term."""
    names = _openfda_all_name_strings(item)
    term = (query_term or "").lower()
    term_tokens = [t for t in term.split() if len(t) > 2]
    exact = 1 if term and any(term == n for n in names) else 0
    contains = 1 if term and any(term in n for n in names) else 0
    token_match = 0
    if term_tokens and names:
        for n in names:
            if any(tok in n for tok in term_tokens):
                token_match = 1
                break
    return (exact * 100) + (contains * 30) + (token_match * 15)

def _score_openfda_result(item, query_term):
    """Score OpenFDA result relevance to the queried drug."""
    has_fields = sum(
        1
        for k in (
            "purpose",
            "indications_and_usage",
            "adverse_reactions",
            "warnings",
            "boxed_warning",
            "warnings_and_cautions",
        )
        if item.get(k)
    )
    return _openfda_name_match_strength(item, query_term) + has_fields

def parse_openfda_response(payload, query_term):
    """Extract readable purpose, warnings, and side effects."""
    results = (payload or {}).get("results", [])
    if not results:
        return None

    matching = [r for r in results if _openfda_name_match_strength(r, query_term) > 0]
    if not matching:
        return None
    best_item = max(matching, key=lambda r: _score_openfda_result(r, query_term))

    item = best_item

    def _best_snippet(*keys):
        for key in keys:
            raw = _first_text(item.get(key))
            if not raw:
                continue
            summarized = _summarize_label_text(raw)
            if summarized:
                return summarized
            cleaned = _clean_label_text(raw)
            if cleaned:
                return cleaned[:500] + ("..." if len(cleaned) > 500 else "")
        return ""

    info = {
        "source": "openfda",
        "use": _best_snippet(
            "purpose",
            "indications_and_usage",
            "information_for_patients",
            "patient_medication_information",
            "clinical_pharmacology",
        ),
        "side_effects": _best_snippet(
            "adverse_reactions",
            "postmarketing_experience",
        ),
        "safety_warnings": _best_snippet(
            "boxed_warning",
            "warnings",
            "warnings_and_cautions",
            "contraindications",
            "precautions",
        ),
    }
    if not any([info["use"], info["side_effects"], info["safety_warnings"]]):
        return None
    return info

_RX_APPROX_STOP = frozenset({
    "drug", "tablet", "tablets", "capsule", "capsules", "oral", "solution", "suspension",
    "extended", "release", "dose", "dosing", "prescription", "medicine", "medication", "generic",
})

def _rxnorm_substantive_tokens(query_clean):
    """Tokens that should appear in an approximate RxNorm hit (avoids 'xyz' -> Xyzal flukes)."""
    return [
        w for w in (query_clean or "").lower().split()
        if len(w) >= 4 and w not in _RX_APPROX_STOP
    ]

def _approx_rxnav_name_plausible(query_clean, candidate_name):
    """Require at least one substantive query token to appear in the candidate display name."""
    need = _rxnorm_substantive_tokens(query_clean)
    if not need:
        return True
    blob = (candidate_name or "").lower()
    return any(t in blob for t in need)

def rxnav_search_rxcui(name):
    """Search RxNav for candidate RxCUIs by (approximate) drug name."""
    if not name:
        return []
    safe_name = str(name).replace('"', '').strip()
    params = urllib.parse.urlencode({"name": safe_name})
    url = f"{RXNAV_BASE_URL}/rxcui.json?{params}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=8) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    ids = (payload or {}).get("idGroup", {}).get("rxnormId", []) or []
    if isinstance(ids, str):
        ids = [ids]
    return ids

def rxnav_approximate_rxcui_candidates(name, max_entries=8):
    """Fuzzy RxNorm lookup when exact name match returns no RxCUI."""
    if not name:
        return []
    params = urllib.parse.urlencode({"term": str(name).strip(), "maxEntries": str(max_entries)})
    url = f"{RXNAV_BASE_URL}/approximateTerm.json?{params}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=8) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    group = (payload or {}).get("approximateGroup") or {}
    cand = group.get("candidate")
    if not cand:
        return []
    if isinstance(cand, dict):
        cand = [cand]
    out = []
    seen = set()
    q = str(name).strip()
    for c in cand:
        rx = c.get("rxcui")
        if not rx:
            continue
        cand_name = (c.get("name") or "").strip()
        need_substantive = _rxnorm_substantive_tokens(q)
        if need_substantive:
            if not cand_name:
                continue
            if not _approx_rxnav_name_plausible(q, cand_name):
                continue
        rid = str(rx)
        if rid in seen:
            continue
        seen.add(rid)
        out.append(rid)
    return out

def rxnav_get_rxcui_properties(rxcui):
    """Get RxNorm concept properties for a given RxCUI."""
    url = f"{RXNAV_BASE_URL}/rxcui/{rxcui}/properties.json"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=8) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    inner = (payload or {}).get("properties")
    if isinstance(inner, dict):
        return inner
    return payload if isinstance(payload, dict) else {}

def rxnorm_preferred_name(name):
    """
    Normalize a user drug name via RxNorm.
    Returns a dict with canonical_name and tty when possible.
    """
    candidates = rxnav_search_rxcui(name)
    if not candidates:
        try:
            candidates = rxnav_approximate_rxcui_candidates(name)
        except Exception:
            candidates = []
    if not candidates:
        return None

    # Prefer ingredient terms first (IN). Then brands (BN). Fall back to first match.
    tty_preference = {"IN": 0, "BN": 1, "SCD": 2, "GP": 3, "BNF": 4}
    best = None
    best_score = 999

    # Limit requests to avoid slowdowns.
    for rxcui in candidates[:4]:
        try:
            props = rxnav_get_rxcui_properties(rxcui)
            tty = props.get("tty", "")
            score = tty_preference.get(tty, 50)
            if score < best_score:
                best_score = score
                best = {
                    "rxcui": rxcui,
                    "canonical_name": props.get("name", "") or "",
                    "tty": tty,
                    "synonym": props.get("synonym", "") or ""
                }
                # If we found an ingredient term, stop early.
                if score == 0:
                    break
        except Exception:
            continue

    if not best:
        return None

    canonical = best.get("canonical_name", "").strip()
    if not canonical:
        return None
    return {**best, "canonical_name": canonical.lower()}

def get_cached_medication_info(normalized_query):
    """Return cached medication data when available and fresh."""
    if not normalized_query:
        return None
    storage_key = _medication_cache_storage_key(normalized_query)
    now_ts = int(time.time())
    ttl_seconds = MEDICATION_CACHE_DAYS * 86400

    db = get_db()
    try:
        row = db.execute(
            'SELECT normalized_query, openfda_query, source, use, side_effects, safety_warnings, fetched_at '
            'FROM drug_cache WHERE normalized_query = ?',
            (storage_key,)
        ).fetchone()
    finally:
        db.close()

    if not row:
        return None
    try:
        fetched_at = int(row["fetched_at"])
    except Exception:
        return None
    if now_ts - fetched_at > ttl_seconds:
        return None

    return {
        "found": True,
        "drug_name": row["openfda_query"] or row["normalized_query"],
        "use": row["use"] or "Not available",
        "side_effects": row["side_effects"] or "Not available",
        "safety_warnings": row["safety_warnings"] or "Not available",
        "source": row["source"] or "cache",
        "disclaimer": MEDICATION_DISCLAIMER
    }

def cache_medication_info(normalized_query, openfda_query, source, result):
    """Store medication lookup result in SQLite cache."""
    if not normalized_query or not result:
        return
    storage_key = _medication_cache_storage_key(normalized_query)
    fetched_at = int(time.time())
    db = get_db()
    try:
        db.execute(
            'INSERT OR REPLACE INTO drug_cache '
            '(normalized_query, openfda_query, source, use, side_effects, safety_warnings, fetched_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (
                storage_key,
                openfda_query,
                source,
                result.get("use"),
                result.get("side_effects"),
                result.get("safety_warnings"),
                fetched_at
            )
        )
        db.commit()
    finally:
        db.close()

def is_allowed_image_file(filename):
    if not filename:
        return False
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_IMAGE_EXTENSIONS

def extract_text_from_prescription_image(file_storage):
    """Extract OCR text from uploaded prescription image."""
    if Image is None or pytesseract is None:
        raise RuntimeError(
            "OCR dependencies are not installed. Install Pillow and pytesseract, and ensure Tesseract OCR is available."
        )
    if not file_storage or not file_storage.filename:
        raise ValueError("No image file uploaded.")
    if not is_allowed_image_file(file_storage.filename):
        raise ValueError("Unsupported image format. Use PNG/JPG/JPEG/WEBP.")

    image_bytes = file_storage.read()
    if not image_bytes:
        raise ValueError("Uploaded image is empty.")

    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    text = pytesseract.image_to_string(img)
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    if not text:
        raise RuntimeError("Could not read text from prescription image.")
    return text

def extract_medicine_candidates_from_text(ocr_text):
    """Extract likely medicine names from OCR text."""
    text = (ocr_text or "").lower()
    lines = [re.sub(r"[^a-z0-9\s\-\./]", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line and len(line) > 2]

    stop_words = {
        "tab", "tablet", "capsule", "caps", "rx", "sig", "take", "daily",
        "morning", "night", "after", "before", "food", "doctor", "patient",
        "prescription", "name", "age", "date"
    }

    candidates = []
    for line in lines:
        # Keep first 3 tokens for lines like "sertraline 50 mg once daily"
        tokens = [t for t in line.split() if t not in stop_words]
        if not tokens:
            continue
        candidate = clean_medicine_name(" ".join(tokens[:3]))
        if candidate and candidate not in stop_words and len(candidate) >= 3:
            candidates.append(candidate)

    # Unique preserve order; cap to avoid too many API calls.
    unique = []
    for c in candidates:
        if c not in unique:
            unique.append(c)
    return unique[:5]

def extract_medicine_candidates_fallback(ocr_text):
    """Extract word-like tokens from raw OCR when line parsing yields nothing."""
    if not (ocr_text or "").strip():
        return []
    stop = {
        "tab", "tablet", "capsule", "caps", "rx", "sig", "take", "daily",
        "morning", "night", "after", "before", "food", "doctor", "patient",
        "prescription", "name", "age", "date", "once", "twice", "with",
        "this", "that", "your", "please", "refills", "authorized", "dispense",
    }
    raw = re.sub(r"[^a-zA-Z\s-]", " ", ocr_text)
    raw = re.sub(r"\s+", " ", raw).strip().lower()
    seen = set()
    out = []
    for w in raw.split():
        w = w.strip("-")
        if len(w) < 4 or w in stop:
            continue
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out[:12]

def load_local_medication_dataset():
    """Load local fallback medication JSON data."""
    dataset_path = os.path.join(app.root_path, "data", "medication_fallback.json")
    try:
        with open(dataset_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def lookup_local_medication(clean_name, dataset):
    """Find best local fallback match by cleaned drug name."""
    if not clean_name or not dataset:
        return None

    if clean_name in dataset:
        match = dataset[clean_name]
    else:
        # Soft match if cleaned name is part of a local key.
        match = None
        for key, value in dataset.items():
            if clean_name in key or key in clean_name:
                match = value
                break

    if not match:
        return None

    return {
        "source": "local",
        "use": match.get("use", ""),
        "side_effects": match.get("side_effects", ""),
        "safety_warnings": match.get("safety_warnings", ""),
    }

def get_medication_information(raw_name):
    """Orchestrate API lookup with safe local fallback."""
    cleaned_input = clean_medicine_name(raw_name)
    if not cleaned_input:
        return {
            "found": False,
            "drug_name": cleaned_input,
            "message": "No medicine name could be read. Check spelling or try the generic name.",
            "disclaimer": MEDICATION_DISCLAIMER
        }

    # 0) Cache-first (using cleaned input without dosage).
    normalized_query = cleaned_input
    cached = get_cached_medication_info(normalized_query)
    if cached:
        return apply_medication_llm_refine(cached)

    # 1) Normalize via RxNorm for better matching.
    canonical_match = None
    try:
        canonical_match = rxnorm_preferred_name(cleaned_input)
    except Exception:
        canonical_match = None

    base_term = (canonical_match.get("canonical_name") if canonical_match else cleaned_input) or cleaned_input
    search_terms = []
    for t in (base_term, cleaned_input):
        tt = (t or "").strip().lower()
        if tt and tt not in search_terms:
            search_terms.append(tt)
    if canonical_match:
        syn_raw = (canonical_match.get("synonym") or "").strip().lower()
        for part in re.split(r"[|;]", syn_raw):
            p = part.strip()
            if p and p not in search_terms:
                search_terms.append(p)
    parts = cleaned_input.split()
    if parts and len(parts[0]) > 2 and parts[0] not in search_terms:
        search_terms.append(parts[0])

    # 2) Try OpenFDA with several normalized spellings (API + RxNorm quirks).
    parsed = None
    matched_term = base_term
    fda_network_error = False
    for term in search_terms:
        try:
            fda_payload = fetch_openfda_drug_data(term)
            if isinstance(fda_payload, dict) and fda_payload.get("_req_error") == "network":
                fda_network_error = True
                break
            if not fda_payload or not fda_payload.get("results"):
                continue
            parsed = parse_openfda_response(fda_payload, term)
            if parsed:
                matched_term = term
                break
        except Exception as ex:
            print("OpenFDA error for term:", term, ex)
            continue

    if parsed:
        result = {
            "found": True,
            "drug_name": matched_term,
            "use": parsed["use"] or "Not available",
            "side_effects": parsed["side_effects"] or "Not available",
            "safety_warnings": parsed["safety_warnings"] or "Not available",
            "source": parsed["source"],
            "disclaimer": MEDICATION_DISCLAIMER
        }
        try:
            cache_medication_info(
                normalized_query,
                matched_term,
                parsed.get("source", "openfda"),
                {
                    "use": result["use"],
                    "side_effects": result["side_effects"],
                    "safety_warnings": result["safety_warnings"]
                }
            )
        except Exception:
            pass
        return apply_medication_llm_refine(result)

    openfda_term = base_term

    # 3) Fallback local dataset (try every search variant)
    local_data = load_local_medication_dataset()
    local_match = None
    for term in search_terms:
        local_match = lookup_local_medication(term, local_data)
        if local_match:
            openfda_term = term
            break
    if not local_match:
        local_match = lookup_local_medication(openfda_term, local_data)
    if local_match:
        result = {
            "found": True,
            "drug_name": openfda_term,
            "use": local_match["use"] or "Not available",
            "side_effects": local_match["side_effects"] or "Not available",
            "safety_warnings": local_match["safety_warnings"] or "Not available",
            "source": local_match["source"],
            "disclaimer": MEDICATION_DISCLAIMER
        }
        # Cache local result too (helps reduce repeated lookups).
        try:
            cache_medication_info(normalized_query, openfda_term, local_match["source"], local_match)
        except Exception:
            pass
        return apply_medication_llm_refine(result)

    if fda_network_error:
        msg = (
            "Could not reach the FDA medication database (network or firewall). "
            "Check your internet connection, or try again later. "
            "You can set OPENFDA_API_KEY for more reliable access—see open.fda.gov."
        )
    else:
        msg = (
            "No matching label was found. Try the generic (INN) name, check spelling, "
            "or add common drugs to data/medication_fallback.json for offline use."
        )
    return {
        "found": False,
        "drug_name": openfda_term,
        "message": msg,
        "disclaimer": MEDICATION_DISCLAIMER
    }

# -----------------------------
# 🔐 AUTH ROUTES
# -----------------------------
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        db = get_db()
        try:
            hashed = generate_password_hash(password)
            db.execute(
                'INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                (username, email, hashed)
            )
            db.commit()
            flash("Registered successfully!", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("User already exists", "error")
        finally:
            db.close()

    return render_template('register.html', google_oauth_enabled=_google_oauth_configured())

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        db = get_db()
        user = db.execute(
            'SELECT * FROM users WHERE username = ?',
            (username,)
        ).fetchone()
        db.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials", "error")

    return render_template('login.html', google_oauth_enabled=_google_oauth_configured())


@app.route('/auth/google')
def auth_google():
    if not _google_oauth_configured():
        flash('Google sign-in is not configured on this server.', 'error')
        return redirect(url_for('login'))
    redirect_uri = _google_redirect_uri()
    flow_state = secrets.token_urlsafe(32)
    session['google_oauth_state'] = flow_state
    try:
        flow = _google_flow(redirect_uri)
        authorization_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='select_account',
            state=flow_state,
        )
    except Exception:
        traceback.print_exc()
        flash('Could not start Google sign-in.', 'error')
        return redirect(url_for('login'))
    return redirect(authorization_url)


@app.route('/auth/google/callback')
def auth_google_callback():
    if not _google_oauth_configured():
        return redirect(url_for('login'))
    if request.args.get('error'):
        flash('Google sign-in was cancelled or denied.', 'error')
        return redirect(url_for('login'))
    stored_state = session.pop('google_oauth_state', None)
    if not stored_state or stored_state != request.args.get('state'):
        flash('Sign-in expired. Please try again.', 'error')
        return redirect(url_for('login'))
    redirect_uri = _google_redirect_uri()
    try:
        flow = _google_flow(redirect_uri)
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
    except Exception:
        traceback.print_exc()
        flash('Could not finish Google sign-in. Try again.', 'error')
        return redirect(url_for('login'))
    try:
        resp = requests.get(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization': f'Bearer {creds.token}'},
            timeout=12,
        )
        if not resp.ok:
            flash('Could not load your Google profile.', 'error')
            return redirect(url_for('login'))
        info = resp.json()
    except Exception:
        traceback.print_exc()
        flash('Could not load your Google profile.', 'error')
        return redirect(url_for('login'))

    google_sub = (info.get('sub') or '').strip()
    email = (info.get('email') or '').strip().lower()
    if not google_sub or not email:
        flash('Your Google account must have an email address to sign in here.', 'error')
        return redirect(url_for('login'))

    db = get_db()
    try:
        user = db.execute(
            'SELECT * FROM users WHERE google_sub = ?', (google_sub,)
        ).fetchone()
        if not user:
            user = db.execute(
                "SELECT * FROM users WHERE lower(email) = ?", (email,)
            ).fetchone()
            if user:
                existing_sub = user['google_sub'] if user['google_sub'] else None
                if existing_sub and existing_sub != google_sub:
                    flash('This email is already used with a different Google account.', 'error')
                    return redirect(url_for('login'))
                db.execute(
                    'UPDATE users SET google_sub = ? WHERE id = ?',
                    (google_sub, user['id']),
                )
                db.commit()
                user = db.execute('SELECT * FROM users WHERE id = ?', (user['id'],)).fetchone()
        if not user:
            username = _oauth_pick_username(db, email, google_sub)
            placeholder_pw = generate_password_hash(secrets.token_hex(32))
            db.execute(
                'INSERT INTO users (username, email, password, google_sub) VALUES (?, ?, ?, ?)',
                (username, email, placeholder_pw, google_sub),
            )
            db.commit()
            user = db.execute(
                'SELECT * FROM users WHERE google_sub = ?', (google_sub,)
            ).fetchone()
        session['user_id'] = user['id']
        session['username'] = user['username']
        flash("You're signed in with Google.", 'success')
        return redirect(url_for('dashboard'))
    except sqlite3.IntegrityError:
        db.rollback()
        flash('Could not create your account (duplicate details). Try signing in with username/password or contact support.', 'error')
        return redirect(url_for('login'))
    finally:
        db.close()


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# -----------------------------
# 📊 DASHBOARD
# -----------------------------
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

# -----------------------------
# 😊 MOOD TRACKER
# -----------------------------
@app.route('/mood_tracker', methods=['GET', 'POST'])
def mood_tracker():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        mood = request.form['mood']
        note = request.form.get('note', '')
        date = datetime.now().strftime('%Y-%m-%d')

        db = get_db()
        existing = db.execute(
            'SELECT id FROM mood_logs WHERE user_id=? AND date=?',
            (session['user_id'], date)
        ).fetchone()

        if existing:
            flash("Already logged today", "error")
        else:
            db.execute(
                'INSERT INTO mood_logs (user_id, mood, note, date) VALUES (?, ?, ?, ?)',
                (session['user_id'], mood, note, date)
            )
            db.commit()
            flash("Mood saved!", "success")

        db.close()
        return redirect(url_for('mood_tracker'))

    return render_template('mood_tracker.html')

# -----------------------------
# 💬 CHAT PAGE
# -----------------------------
@app.route('/chat')
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('chat.html')

@app.route('/medication')
def medication():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('medication.html')

@app.route('/campus-chat')
def campus_chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('campus_chat.html')

def _normalize_peer_nickname(raw):
    n = re.sub(r'\s+', ' ', (raw or '').strip())[:CAMPUS_CHAT_NICK_MAX]
    return n if n else 'Anonymous'

def _random_pair_row_for_user(db, uid):
    return db.execute(
        'SELECT pair_id, user_a_id, user_b_id, nick_a, nick_b FROM random_chat_pairs '
        'WHERE ended_at IS NULL AND (user_a_id = ? OR user_b_id = ?)',
        (uid, uid),
    ).fetchone()

@app.route('/api/random_match/join', methods=['POST'])
def api_random_match_join():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    data = request.get_json(silent=True) or {}
    nick = _normalize_peer_nickname(data.get('nickname'))
    uid = session['user_id']
    try:
        with RANDOM_MATCH_LOCK:
            db = get_db()
            existing = _random_pair_row_for_user(db, uid)
            if existing:
                pid = existing['pair_id']
                partner = (
                    existing['nick_b'] if uid == existing['user_a_id'] else existing['nick_a']
                )
                db.close()
                return jsonify({
                    'status': 'matched',
                    'pair_id': pid,
                    'partner_nickname': partner,
                })
            db.execute('DELETE FROM random_match_queue WHERE user_id = ?', (uid,))
            other = db.execute(
                'SELECT user_id, nickname FROM random_match_queue WHERE user_id != ? '
                'ORDER BY queued_at ASC LIMIT 1',
                (uid,),
            ).fetchone()
            now_ts = int(time.time())
            if other:
                o_uid = other['user_id']
                nick_other = other['nickname'] or 'Anonymous'
                db.execute(
                    'DELETE FROM random_match_queue WHERE user_id IN (?, ?)',
                    (uid, o_uid),
                )
                pid = str(uuid.uuid4())
                db.execute(
                    'INSERT INTO random_chat_pairs '
                    '(pair_id, user_a_id, user_b_id, nick_a, nick_b, created_at, ended_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, NULL)',
                    (pid, uid, o_uid, nick, nick_other, now_ts),
                )
                db.commit()
                db.close()
                return jsonify({
                    'status': 'matched',
                    'pair_id': pid,
                    'partner_nickname': nick_other,
                })
            db.execute(
                'INSERT OR REPLACE INTO random_match_queue (user_id, nickname, queued_at) '
                'VALUES (?, ?, ?)',
                (uid, nick, now_ts),
            )
            db.commit()
            db.close()
        return jsonify({'status': 'waiting'})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/random_match/status', methods=['GET'])
def api_random_match_status():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    uid = session['user_id']
    db = get_db()
    in_queue = db.execute(
        'SELECT 1 FROM random_match_queue WHERE user_id = ?', (uid,)
    ).fetchone()
    row = _random_pair_row_for_user(db, uid)
    db.close()
    if row:
        partner = row['nick_b'] if uid == row['user_a_id'] else row['nick_a']
        return jsonify({
            'status': 'matched',
            'pair_id': row['pair_id'],
            'partner_nickname': partner,
        })
    if in_queue:
        return jsonify({'status': 'waiting'})
    return jsonify({'status': 'idle'})

@app.route('/api/random_match/leave', methods=['POST'])
def api_random_match_leave():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    uid = session['user_id']
    now_ts = int(time.time())
    try:
        with RANDOM_MATCH_LOCK:
            db = get_db()
            db.execute('DELETE FROM random_match_queue WHERE user_id = ?', (uid,))
            db.execute(
                'UPDATE random_chat_pairs SET ended_at = ? '
                'WHERE ended_at IS NULL AND (user_a_id = ? OR user_b_id = ?)',
                (now_ts, uid, uid),
            )
            db.commit()
            db.close()
        return jsonify({'ok': True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/random_match/messages', methods=['GET'])
def api_random_match_messages():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    pair_id = (request.args.get('pair_id') or '').strip()
    if not re.match(r'^[0-9a-f-]{36}$', pair_id, re.I):
        return jsonify({'error': 'Invalid pair'}), 400
    uid = session['user_id']
    db = get_db()
    pr = db.execute(
        'SELECT user_a_id, user_b_id FROM random_chat_pairs '
        'WHERE pair_id = ? AND ended_at IS NULL',
        (pair_id,),
    ).fetchone()
    if not pr or uid not in (pr['user_a_id'], pr['user_b_id']):
        db.close()
        return jsonify({'error': 'Not in this chat'}), 403
    rows = db.execute(
        'SELECT user_id, body, created_at FROM random_chat_messages '
        'WHERE pair_id = ? ORDER BY created_at ASC',
        (pair_id,),
    ).fetchall()
    db.close()
    msgs = [
        {
            'from_self': r['user_id'] == uid,
            'body': r['body'],
            'created_at': r['created_at'],
        }
        for r in rows
    ]
    return jsonify({'pair_id': pair_id, 'messages': msgs})

@app.route('/api/random_match/send', methods=['POST'])
def api_random_match_send():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    data = request.get_json(silent=True) or {}
    pair_id = (data.get('pair_id') or '').strip()
    body = (data.get('body') or '').strip()
    if not re.match(r'^[0-9a-f-]{36}$', pair_id, re.I):
        return jsonify({'error': 'Invalid pair'}), 400
    if len(body) < 1 or len(body) > RANDOM_CHAT_BODY_MAX:
        return jsonify({'error': f'Message must be 1–{RANDOM_CHAT_BODY_MAX} characters.'}), 400
    if detect_crisis(body):
        return jsonify({
            'error': 'crisis',
            'message': (
                'This space is not for immediate crisis support. If you may hurt yourself, '
                'contact local emergency services or a crisis line right away. '
                'In India: Tele-MANAS 14416.'
            ),
        }), 422
    now_ts = time.time()
    last = session.get('random_chat_last_post', 0)
    if now_ts - float(last) < 1.5:
        return jsonify({'error': 'Please wait a moment before sending another message.'}), 429
    session['random_chat_last_post'] = now_ts
    uid = session['user_id']
    db = get_db()
    pr = db.execute(
        'SELECT user_a_id, user_b_id FROM random_chat_pairs '
        'WHERE pair_id = ? AND ended_at IS NULL',
        (pair_id,),
    ).fetchone()
    if not pr or uid not in (pr['user_a_id'], pr['user_b_id']):
        db.close()
        return jsonify({'error': 'Not in this chat'}), 403
    try:
        cur = db.execute(
            'INSERT INTO random_chat_messages (pair_id, user_id, body, created_at) VALUES (?, ?, ?, ?)',
            (pair_id, uid, body, int(now_ts)),
        )
        db.commit()
        db.close()
        return jsonify({'ok': True, 'created_at': int(now_ts)})
    except Exception as e:
        traceback.print_exc()
        db.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/campus_chat/messages', methods=['GET'])
def api_campus_chat_messages():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    room_id = CAMPUS_LOUNGE_ROOM_ID
    db = get_db()
    rows = db.execute(
        'SELECT id, nickname, body, created_at FROM campus_chat_messages '
        'WHERE room_id = ? ORDER BY created_at DESC LIMIT ?',
        (room_id, CAMPUS_CHAT_POLL_LIMIT),
    ).fetchall()
    db.close()
    rows = list(reversed(rows))
    out = [
        {
            'id': row['id'],
            'nickname': row['nickname'],
            'body': row['body'],
            'created_at': row['created_at'],
        }
        for row in rows
    ]
    return jsonify({'room_id': room_id, 'messages': out})

@app.route('/api/campus_chat/post', methods=['POST'])
def api_campus_chat_post():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    try:
        data = request.get_json(silent=True) or {}
        room_id = CAMPUS_LOUNGE_ROOM_ID
        nickname = (data.get('nickname') or '').strip()
        body = (data.get('body') or '').strip()
        nickname = re.sub(r'\s+', ' ', nickname)[:CAMPUS_CHAT_NICK_MAX].strip() or 'Anonymous'
        if len(nickname) < 1:
            nickname = 'Anonymous'
        if len(body) < 1 or len(body) > CAMPUS_CHAT_BODY_MAX:
            return jsonify({'error': f'Message must be 1–{CAMPUS_CHAT_BODY_MAX} characters.'}), 400
        if detect_crisis(body):
            return jsonify({
                'error': 'crisis',
                'message': (
                    'This space is not for immediate crisis support. If you may hurt yourself, '
                    'contact local emergency services or a crisis line right away. '
                    'In India: Tele-MANAS 14416.'
                ),
            }), 422
        now_ts = time.time()
        last = session.get('campus_chat_last_post', 0)
        if now_ts - float(last) < 2.0:
            return jsonify({'error': 'Please wait a moment before sending another message.'}), 429
        session['campus_chat_last_post'] = now_ts

        created_at = int(now_ts)
        db = get_db()
        cur = db.execute(
            'INSERT INTO campus_chat_messages (room_id, nickname, body, user_id, created_at) '
            'VALUES (?, ?, ?, ?, ?)',
            (room_id, nickname, body, session['user_id'], created_at),
        )
        db.commit()
        mid = cur.lastrowid
        db.close()
        return jsonify({
            'ok': True,
            'message': {
                'id': mid,
                'nickname': nickname,
                'body': body,
                'created_at': created_at,
            },
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# -----------------------------
# 💬 CHAT API
# -----------------------------
@app.route('/api/chat', methods=['POST'])
def api_chat():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    try:
        data = request.get_json()
        message = data.get('message', '').strip()

        db = get_db()

        # Fetch history
        history = db.execute(
            'SELECT message, response FROM chat_history WHERE user_id=? ORDER BY timestamp DESC LIMIT 6',
            (session['user_id'],)
        ).fetchall()

        history_turns = []
        for row in reversed(history):
            history_turns.append({"role": "user", "content": row["message"]})
            history_turns.append({"role": "assistant", "content": row["response"]})

        # 🚨 Crisis check
        if detect_crisis(message):
            response = crisis_response()
        else:
            mode = _effective_llm_mode()
            if mode == 'unconfigured':
                response = (
                    f"{_ai_not_configured_message()} "
                    "If you’re in crisis, contact local emergency services or a crisis line right away."
                )
            elif mode == 'openai':
                response = generate_ai_response(message, history_turns)
            elif mode == 'ollama':
                response = generate_ollama_response(message, history_turns)
            else:
                raise ValueError("Invalid AI provider mode.")

        # Save chat
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.execute(
            'INSERT INTO chat_history (user_id, message, response, timestamp) VALUES (?, ?, ?, ?)',
            (session['user_id'], message, response, timestamp)
        )
        db.commit()
        db.close()

        return jsonify({'response': response})

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# -----------------------------
# 📈 MOOD DATA API
# -----------------------------
@app.route('/api/mood_data')
def mood_data():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    db = get_db()
    rows = db.execute(
        'SELECT mood, date FROM mood_logs WHERE user_id=? ORDER BY date',
        (session['user_id'],)
    ).fetchall()
    db.close()

    return jsonify([dict(r) for r in rows])

@app.route('/api/medication_info', methods=['POST'])
def api_medication_info():
    """Medication summary from typed name: OpenFDA + cache + local fallback (hosted-friendly; no local Ollama required)."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    try:
        medicine = ""
        if request.content_type and "multipart/form-data" in request.content_type:
            medicine = (request.form.get('medicine') or '').strip()
        else:
            data = request.get_json(silent=True) or {}
            medicine = (data.get('medicine') or '').strip()

        if not medicine:
            return jsonify({
                "found": False,
                "message": "Enter a medicine name.",
                "disclaimer": MEDICATION_DISCLAIMER,
            }), 200

        info = get_medication_information(medicine)
        if info.get("found"):
            card = {
                "drug_name": info.get("drug_name"),
                "use": info.get("use") or "Not available",
                "side_effects": info.get("side_effects") or "Not available",
            }
            return jsonify({
                "found": True,
                "results": [card],
                "disclaimer": info.get("disclaimer", MEDICATION_DISCLAIMER),
            }), 200
        return jsonify({
            "found": False,
            "message": info.get("message") or "No information found.",
            "disclaimer": info.get("disclaimer", MEDICATION_DISCLAIMER),
        }), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "found": False,
            "message": str(e) or "Request failed.",
            "disclaimer": MEDICATION_DISCLAIMER,
        }), 200

@app.route('/api/suggestions')
def api_suggestions():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    db = get_db()
    latest = db.execute(
        'SELECT mood FROM mood_logs WHERE user_id=? ORDER BY date DESC LIMIT 1',
        (session['user_id'],)
    ).fetchone()
    db.close()

    suggestions_by_mood = {
        'stressed': [
            "Take a 10-minute walk away from screens.",
            "Do 1 minute of slow breathing (inhale 4s, exhale 6s).",
            "Pick only one task for the next 15 minutes."
        ],
        'sad': [
            "Message one trusted person and ask for a quick check-in.",
            "Have water and step outside for 2-5 minutes.",
            "Do one tiny self-care action right now."
        ],
        'happy': [
            "Write down what helped you feel better today.",
            "Share this moment with someone you trust.",
            "Use this energy for one positive habit."
        ]
    }

    default_suggestions = [
        "Log your mood daily to get better suggestions.",
        "Try a short breathing break.",
        "Take a short walk and hydrate."
    ]

    if latest:
        mood = latest['mood']
        return jsonify(suggestions_by_mood.get(mood, default_suggestions))
    return jsonify(default_suggestions)

@app.route('/overthinking', methods=['GET', 'POST'])
def overthinking():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        thought = request.form.get('thought', '').strip()
        if not thought:
            flash('Please enter a thought to continue.', 'error')
            return render_template('overthinking.html')

        analysis = generate_overthinking_analysis(thought)
        if not analysis:
            analysis = template_overthinking_analysis(thought)
        return render_template(
            'overthinking.html',
            thought=thought,
            worst_case=analysis["worst_case"],
            realistic=analysis["realistic"],
            action=analysis["action"],
        )

    return render_template('overthinking.html')

# -----------------------------
# 🚀 RUN
# -----------------------------
if __name__ == '__main__':
    app.run(debug=True)
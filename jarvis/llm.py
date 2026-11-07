"""
Routage des modèles, avec streaming :
  1. Ollama local (Mac)                       — par défaut
  2. Ollama d'une autre machine du réseau      — secours ou prioritaire
  3. Fournisseur cloud compatible OpenAI       — OPTIONNEL, désactivé par défaut
Réessais, bascule automatique, gestion de la « réflexion » (think) des modèles qui la supportent.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable

import requests

import security

Stream = Callable[[str, str], None] | None   # (type: "content" | "thinking", texte)


class LLMError(Exception):
    pass


class ToolParseError(LLMError):
    """Le modèle a produit un appel d'outil mal formé (JSON invalide) : on le lui signale au lieu d'abandonner."""


def _parse_args(a):
    if isinstance(a, str):
        try:
            return json.loads(a) if a.strip() else {}
        except json.JSONDecodeError:
            return {}
    return a or {}


def _perf(backend: str, s: dict | None, n_msgs: int, with_tools: bool):
    """Mesures de vitesse de chaque appel (jetons relus, jetons générés, débit) → logs/perf.jsonl, pour diagnostiquer."""
    if not s:
        return
    try:
        import config
        ns = 1e9
        pe, pd = s.get("prompt_eval_count") or 0, (s.get("prompt_eval_duration") or 0) / ns
        ec, ed = s.get("eval_count") or 0, (s.get("eval_duration") or 0) / ns
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "backend": backend, "msgs": n_msgs, "tools": with_tools,
               "prompt_tokens": pe, "prompt_s": round(pd, 2), "prompt_tps": round(pe / pd, 1) if pd else None,
               "gen_tokens": ec, "gen_s": round(ed, 2), "gen_tps": round(ec / ed, 1) if ed else None,
               "load_s": round((s.get("load_duration") or 0) / ns, 2), "total_s": round((s.get("total_duration") or 0) / ns, 2)}
        p = config.LOG_DIR / "perf.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > 5_000_000:      # rotation simple
            p.replace(p.with_suffix(".old.jsonl"))
        with open(p, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def ram_gb() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3 + 0.5)
    except (ValueError, OSError, AttributeError):
        return 16


def model_ctx(cfg: dict, model: str) -> int:
    """Mémoire de travail adaptée au modèle. gpt-oss a une mémoire de contexte très économe (fenêtre glissante sur la
    moitié des couches) : sur 24 Go on lui donne 32 k jetons sans risque de swap ; les autres gardent le réglage."""
    n = int(cfg.get("num_ctx", 16384))
    if cfg.get("auto_ctx", True) and (model or "").startswith("gpt-oss") and ram_gb() >= 24:
        n = max(n, 32768)
    return n


def think_value(model: str, want):
    """gpt-oss réfléchit toujours : on règle son NIVEAU (« low » = rapide). Les autres modèles : vrai / faux."""
    if (model or "").startswith("gpt-oss"):
        if want in ("low", "medium", "high"):
            return want
        return "high" if want is True else "low"
    if want in ("low", "medium", "high"):
        return False if want in ("low", "medium") else True     # qwen3 : la réflexion coûte ~25 s, réservée à « high »
    return want


class OllamaBackend:
    def __init__(self, host: str, model: str, label: str, think=None, keep_alive="30m"):
        self.host, self.model, self.name = host.rstrip("/"), model, label
        self.think, self.keep_alive = think, keep_alive

    def available(self) -> bool:
        try:
            return requests.get(f"{self.host}/api/tags", timeout=3).ok
        except requests.RequestException:
            return False

    def models(self) -> list[str]:
        r = requests.get(f"{self.host}/api/tags", timeout=5)
        r.raise_for_status()
        return [m.get("model") or m.get("name") for m in r.json().get("models", [])]

    def pull(self, model: str, progress=None):
        with requests.post(f"{self.host}/api/pull", json={"model": model, "stream": True}, stream=True, timeout=None) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line and progress:
                    progress(json.loads(line))

    def chat(self, messages, tools, options, stream: Stream = None, think="auto") -> dict:
        body = {"model": self.model, "messages": messages, "stream": True, "options": options,
                "keep_alive": self.keep_alive}
        if tools:
            body["tools"] = tools
        want = self.think if think == "auto" else (think if self.think is not None else None)
        want = think_value(self.model, want)
        if want is not None:
            body["think"] = want
        try:
            r = requests.post(f"{self.host}/api/chat", json=body, stream=True, timeout=(10, 900))
        except requests.ConnectionError:
            raise
        if r.status_code >= 400:
            txt = r.text[:400]
            if "error parsing tool call" in txt:
                raise ToolParseError(txt[:300])
            if "think" in txt.lower() and self.think is not None:
                self.think = None          # modèle sans réflexion : on réessaie sans
                return self.chat(messages, tools, options, stream, think)
            raise LLMError(f"{self.name} HTTP {r.status_code}: {txt}")
        content, thinking, calls, stats = [], [], [], {}
        for line in r.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if chunk.get("error"):
                if "error parsing tool call" in str(chunk["error"]):
                    raise ToolParseError(str(chunk["error"])[:300])
                raise LLMError(f"{self.name}: {chunk['error']}")
            msg = chunk.get("message") or {}
            if msg.get("thinking"):
                thinking.append(msg["thinking"])
                if stream:
                    stream("thinking", msg["thinking"])
            if msg.get("content"):
                content.append(msg["content"])
                if stream:
                    stream("content", msg["content"])
            for c in msg.get("tool_calls") or []:
                fn = c.get("function", {})
                calls.append({"id": c.get("id") or uuid.uuid4().hex[:8], "name": fn.get("name", ""),
                              "arguments": _parse_args(fn.get("arguments"))})
            if chunk.get("done"):
                stats = {k: chunk.get(k, 0) for k in ("prompt_eval_count", "prompt_eval_duration", "eval_count",
                                                      "eval_duration", "load_duration", "total_duration")}
                break
        return {"content": "".join(content), "thinking": "".join(thinking), "tool_calls": calls, "stats": stats}

    def vision(self, prompt: str, image_path: str) -> str:
        with open(image_path, "rb") as f:
            img = base64.b64encode(f.read()).decode()
        r = requests.post(f"{self.host}/api/chat", timeout=300, json={
            "model": self.model, "stream": False, "keep_alive": "10m",
            "messages": [{"role": "user", "content": prompt, "images": [img]}]})
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        r = requests.post(f"{self.host}/api/embed", json={"model": model, "input": texts, "keep_alive": "10m"},
                          timeout=300)
        if r.status_code >= 400:
            raise LLMError(f"embeddings HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["embeddings"]


# ====================================================================== renfort cloud (facultatif)
PROVIDERS = {
    "gemini": {
        "label": "Google Gemini (recommandé)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_url": "https://aistudio.google.com/apikey",
        "prefer": [r"^gemini-[\d.]+-flash$", r"^gemini-[\d.]+-flash", r"^gemini-[\d.]+-pro$"],
        "avoid": r"lite|image|tts|audio|live|embed|vision|robotics|computer|native|learnlm|gemma|aqa",
        # chaîne de secours : chaque modèle a son propre quota gratuit du jour ; les « lite » en tout dernier recours
        "chain": r"^gemini-[\d.]+-flash|^gemini-flash-latest$",
        "last_resort": ["gemini-flash-latest", "gemini-flash-lite-latest"],
        "note": "Gratuit, sans carte bancaire. En France (Espace économique européen), Google applique à l'usage gratuit "
                "les conditions de son service payant : tes données ne servent pas à entraîner ses modèles.",
    },
    "mistral": {
        "label": "Mistral (français, quota large)",
        "base_url": "https://api.mistral.ai/v1",
        "key_url": "https://console.mistral.ai/api-keys",
        "prefer": [r"^devstral-latest$", r"^devstral", r"^mistral-large-latest$", r"^mistral-medium-latest$"],
        "avoid": r"embed|ocr|moderation|pixtral|voxtral|saba|tiny",
        "note": "Gratuit, sans carte (vérification par SMS), quota très large : idéal en relais. Mais Mistral prévient que "
                "les requêtes du plan gratuit peuvent servir à entraîner ses modèles : évite-le pour du code confidentiel.",
    },
    "openrouter": {
        "label": "OpenRouter (modèles « :free »)",
        "base_url": "https://openrouter.ai/api/v1",
        "key_url": "https://openrouter.ai/keys",
        "prefer": [r"^openai/gpt-oss-120b:free$", r"^qwen/qwen3-coder:free$", r"^deepseek/.*:free$", r":free$"],
        "avoid": r"vision|image|audio",
        "note": "Modèles gratuits limités (environ 50 requêtes par jour). Selon le modèle, le fournisseur peut entraîner sur "
                "tes données : bloque-le dans les réglages de confidentialité d'OpenRouter.",
    },
    "groq": {
        "label": "Groq (très rapide, quota serré)",
        "base_url": "https://api.groq.com/openai/v1",
        "key_url": "https://console.groq.com/keys",
        "prefer": [r"^openai/gpt-oss-120b$", r"gpt-oss", r"llama"],
        "avoid": r"whisper|guard|tts|playai|compound|prompt",
        "note": "Données non utilisées pour l'entraînement, mais le quota gratuit (environ 8 000 jetons par minute) est "
                "souvent trop petit pour les longues instructions de Jarvis.",
    },
    "custom": {"label": "Autre (compatible OpenAI)", "base_url": "", "key_url": "", "prefer": [],
               "avoid": r"embed|tts|audio|image|vision|whisper|moderation|guard|ocr|lite|transcribe|realtime",
               "note": "N'importe quel service compatible OpenAI (adresse et modèle à saisir)."},
}


KEY_FORMATS = {
    "gemini": (r"^AIza[0-9A-Za-z_\-]{30,60}$", "elle commence par « AIza »"),
    "mistral": (r"^[A-Za-z0-9]{24,64}$", "32 lettres et chiffres"),
    "groq": (r"^gsk_[A-Za-z0-9]{20,80}$", "elle commence par « gsk_ »"),
    "openrouter": (r"^sk-or-v1-[A-Za-z0-9]{32,96}$", "elle commence par « sk-or-v1- »"),
    "custom": (r"^[A-Za-z0-9_\-.:]{16,400}$", ""),
}


def looks_like_key(provider: str, text: str) -> bool:
    pat = KEY_FORMATS.get(provider, KEY_FORMATS["custom"])[0]
    return bool(re.fullmatch(pat, (text or "").strip()))


def key_account(provider: str) -> str:
    return f"cloud_key_{provider}"


def cloud_key(provider: str) -> str | None:
    return security.keychain_get(key_account(provider)) or (security.keychain_get("cloud_api_key") if provider == "custom" else None)


def _version_key(mid: str):
    nums = [int(x) for x in re.findall(r"\d+", mid)[:3]]
    stable = 0 if re.search(r"preview|exp|beta", mid) else 1
    return (nums, stable, -len(mid))


def rank_models(provider: str, ids: list[str]) -> list[str]:
    """Modèles candidats, du meilleur au moins bon : préférences du service (plus récent d'abord), alias stables
    « *-latest » juste après, puis le reste. Sert à essayer le suivant si le premier est saturé."""
    p = PROVIDERS.get(provider) or PROVIDERS["custom"]
    clean = [i.split("/", 1)[1] if i.startswith("models/") else i for i in ids]
    avoid = re.compile(p["avoid"], re.I) if p.get("avoid") else None
    pool = [i for i in clean if not (avoid and avoid.search(i))] or clean
    out: list[str] = []
    for pat in p.get("prefer", []):
        hit = sorted((i for i in pool if re.search(pat, i) and i not in out), key=_version_key, reverse=True)
        out += hit
        if hit and pat == p["prefer"][0]:
            out += [i for i in pool if i.endswith("-latest") and re.search(pat.replace("[\\d.]+-", "").replace("$", ""), i)
                    and i not in out]
    out += sorted((i for i in pool if i not in out), key=_version_key, reverse=True)
    return out


def pick_model(provider: str, ids: list[str]) -> str:
    """Le meilleur modèle disponible pour un agent (le plus récent qui correspond aux préférences)."""
    r = rank_models(provider, ids)
    return r[0] if r else ""


def fallback_chain(provider: str, ids: list[str], model: str, first: list[str] | None = None, limit: int = 10) -> list[str]:
    """Modèles à essayer quand le principal est saturé ou a épuisé son quota gratuit du jour.
    Chaque modèle Gemini a son propre quota : plus la chaîne est longue, plus la journée tient."""
    p = PROVIDERS.get(provider) or PROVIDERS["custom"]
    keep = re.compile(p["chain"], re.I) if p.get("chain") else None
    clean = [i.split("/", 1)[1] if i.startswith("models/") else i for i in ids]
    out: list[str] = []
    for m in list(first or []) + [m for m in rank_models(provider, clean) if not keep or keep.search(m)]:
        if m and m != model and m not in out:
            out.append(m)
    tail = [m for m in p.get("last_resort", []) if m != model]
    out = [m for m in out if m not in tail][:max(0, limit - len(tail))]
    return out + tail


# Quotas gratuits « par jour » épuisés (remis à zéro à minuit, heure de Californie, chez Google)
_EXHAUSTED: dict[str, str] = {}


def _quota_day() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - 8 * 3600))


def _quota_file():
    import config
    return config.JARVIS_DIR / "cloud_quota.json"


def _load_exhausted():
    """Partagé entre l'app et les autres processus Jarvis (Siri, banc d'essai), et conservé après un redémarrage."""
    try:
        day = _quota_day()
        for m, d in json.loads(_quota_file().read_text()).items():
            if d == day:
                _EXHAUSTED.setdefault(m, d)
    except (OSError, ValueError, AttributeError):
        pass


def mark_exhausted(model: str):
    day = _quota_day()
    _load_exhausted()
    _EXHAUSTED[model] = day
    try:
        _quota_file().write_text(json.dumps({m: d for m, d in _EXHAUSTED.items() if d == day}))
    except OSError:
        pass


def exhausted_today() -> list[str]:
    _load_exhausted()
    return sorted(m for m, d in _EXHAUSTED.items() if d == _quota_day())


def reset_exhausted():
    _EXHAUSTED.clear()
    try:
        _quota_file().unlink(missing_ok=True)
    except OSError:
        pass


def exhausted(model: str) -> bool:
    if _EXHAUSTED.get(model) != _quota_day():
        _load_exhausted()
    return _EXHAUSTED.get(model) == _quota_day()


# Gemini 3 exige la « thought_signature » de ses propres appels d'outils. Ceux qui viennent d'un autre modèle
# (Jarvis en local, ou un autre Gemini après une bascule) n'en ont pas de valable : Google documente cette valeur
# pour lever la vérification sur ces appels-là.
DUMMY_SIGNATURE = "skip_thought_signature_validator"


def _mistral_id(i: str) -> str:
    """Mistral exige des identifiants d'appel de 9 lettres ou chiffres : on convertit, toujours de la même façon."""
    return i if re.fullmatch(r"[A-Za-z0-9]{9}", i or "") else hashlib.md5((i or "x").encode()).hexdigest()[:9]


def mistral_messages(conv: list[dict]) -> list[dict]:
    """Règles de Mistral : identifiants de 9 caractères, consignes « system » seulement au début,
    et jamais de message utilisateur juste après un résultat d'outil."""
    out: list[dict] = []
    for i, m in enumerate(conv):
        m = dict(m)
        if m["role"] == "system" and any(x["role"] != "system" for x in out):
            m = {"role": "user", "content": f"[Consigne de Jarvis] {m.get('content') or ''}"}
        if m.get("tool_calls"):
            m["tool_calls"] = [{**c, "id": _mistral_id(c.get("id", ""))} for c in m["tool_calls"]]
        if m["role"] == "tool":
            m["tool_call_id"] = _mistral_id(m.get("tool_call_id", ""))
        if m["role"] == "user" and out and out[-1]["role"] == "tool":
            out.append({"role": "assistant", "content": " "})
        out.append(m)
    return out


def sign_tool_calls(calls: list[dict], provider: str, model: str) -> list[dict]:
    """Prépare les extra_content d'un message assistant : on garde les signatures produites par CE modèle,
    sinon (Gemini) on met la signature neutre sur le premier appel, comme Google le fait pour les appels parallèles."""
    out, valid = [], False
    for c in calls:
        c = dict(c)
        ec = c.pop("extra_content", None)
        ec = dict(ec) if isinstance(ec, dict) else {}
        src = ec.pop("_m", None)
        if provider not in ("gemini", "custom") or (provider == "custom" and src and src != model):
            out.append(c)                         # Mistral, Groq… refusent les champs qu'ils ne connaissent pas
            continue
        sig = (ec.get("google") or {}).get("thought_signature") if isinstance(ec.get("google"), dict) else None
        if sig and src and src != model:
            ec.pop("google", None)                # signature d'un autre modèle : refusée par Google
            sig = None
        valid = valid or bool(sig)
        if ec:
            c["extra_content"] = ec
        out.append(c)
    if provider == "gemini" and out and not valid:
        ec = dict(out[0].get("extra_content") or {})
        ec["google"] = {**(ec.get("google") or {}), "thought_signature": DUMMY_SIGNATURE}
        out[0]["extra_content"] = ec
    return out


def cloud_tools(tools: list[dict] | None) -> list[dict] | None:
    """Schémas d'outils acceptés par tous les services (Gemini refuse notamment les objets sans propriétés)."""
    if not tools:
        return tools
    keep = {"type", "description", "properties", "required", "items", "enum"}

    def fix(s):
        if not isinstance(s, dict):
            return {"type": "string"}
        s = {k: v for k, v in s.items() if k in keep}
        typ = s.get("type")
        if isinstance(typ, list):
            typ = s["type"] = next((x for x in typ if x != "null"), "string")
        if typ == "object":
            props = {k: fix(v) for k, v in (s.get("properties") or {}).items()}
            if not props:
                return {"type": "string", "description": (s.get("description", "") + " (objet JSON, en texte)").strip()}
            s["properties"] = props
            s["required"] = [r for r in s.get("required", []) if r in props]
            if not s["required"]:
                s.pop("required")
        elif typ == "array":
            s["items"] = fix(s.get("items") or {"type": "string"})
        return s

    out = []
    for t in tools:
        fn = dict(t.get("function", {}))
        params = fn.get("parameters") or {"type": "object", "properties": {}}
        fixed = fix(params)
        if fixed.get("type") != "object":
            fixed = {"type": "object", "properties": {}}
        fn["parameters"] = fixed
        out.append({"type": "function", "function": fn})
    return out


class OpenAICompatBackend:
    """Renfort en ligne gratuit (Gemini, Mistral, OpenRouter, Groq…). Clé dans le Trousseau. Jamais utilisé sans accord."""

    def __init__(self, base_url: str, model: str, api_key: str, provider: str = "custom"):
        self.base, self.model, self.key, self.provider = base_url.rstrip("/"), model, api_key, provider
        self.name = f"renfort · {model}"
        self.default_max_tokens = 0
        self.fallbacks: list[str] = []
        self.can_stream = False

    def _extra_body(self, think) -> dict:
        return {}

    def _chat_stream(self, body, stream) -> dict:
        raise NotImplementedError

    def available(self) -> bool:
        return bool(self.key and self.model)

    def _headers(self):
        h = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if self.provider == "openrouter":
            h.update({"HTTP-Referer": "https://localhost/jarvis", "X-Title": "Jarvis"})
        return h

    def models(self) -> list[str]:
        r = requests.get(f"{self.base}/models", headers=self._headers(), timeout=20)
        if r.status_code >= 400:
            raise LLMError(f"{self.name} HTTP {r.status_code}: {security.redact(r.text[:300])}")
        data = r.json()
        items = data.get("data") or data.get("models") or []
        return [m.get("id") or m.get("name") for m in items if isinstance(m, dict) and (m.get("id") or m.get("name"))]

    @staticmethod
    def _retry_after(r) -> float | None:
        h = r.headers.get("retry-after")
        if h:
            try:
                return float(h)
            except ValueError:
                pass
        m = re.search(r'retry(?:Delay| in)[^0-9]{0,6}([0-9.]+)\s*s', r.text or "", re.I)
        return float(m.group(1)) if m else None

    def chat(self, messages, tools, options, stream: Stream = None, think="auto") -> dict:
        conv = []
        for m in messages:
            content = m.get("content") or ""
            if m["role"] == "assistant":
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
            m2 = {"role": m["role"], "content": content}
            if m["role"] == "assistant" and m.get("tool_calls"):
                m2["tool_calls"] = [{"id": c.get("id", "x"), "type": "function",
                                     "function": {"name": c["function"]["name"],
                                                  "arguments": json.dumps(c["function"]["arguments"], ensure_ascii=False)},
                                     # Gemini 3 refuse la suite si on ne lui renvoie pas sa « thought_signature »
                                     **({"extra_content": c["extra_content"]} if c.get("extra_content") else {})}
                                    for c in m["tool_calls"]]
                if not content:
                    m2["content"] = None
            if m["role"] == "tool":
                m2["tool_call_id"] = m.get("tool_call_id", "x")
                if m.get("tool_name"):
                    m2["name"] = m["tool_name"]
            conv.append(m2)
        if exhausted(self.model):                 # quota du jour déjà épuisé : on ne le redemande pas à chaque appel
            nxt = next((m for m in self.fallbacks if not exhausted(m)), None)
            if nxt:
                self.model, self.name = nxt, f"renfort · {nxt}"

        if self.provider == "mistral":
            conv = mistral_messages(conv)

        def sign(model):
            return [{**m, "tool_calls": sign_tool_calls(m["tool_calls"], self.provider, model)} if m.get("tool_calls") else m
                    for m in conv]

        body = {"model": self.model, "messages": sign(self.model), "temperature": options.get("temperature", 0.2)}
        if options.get("num_predict"):
            body["max_tokens"] = options["num_predict"]
        elif self.default_max_tokens:
            body["max_tokens"] = self.default_max_tokens
        if tools:
            body["tools"] = cloud_tools(tools)
        body.update(self._extra_body(think))
        if stream and self.can_stream:
            return self._chat_stream(body, stream)
        tried, malformed = [self.model], 0

        def switch() -> bool:
            nxt = next((m for m in self.fallbacks if m not in tried and not exhausted(m)), None)
            if not nxt:
                return False
            tried.append(nxt)
            self.model = body["model"] = nxt
            self.name = f"renfort · {nxt}"
            body["messages"] = sign(nxt)          # les signatures dépendent du modèle qui répond
            return True

        for attempt in range(12):
            t_req = time.time()
            r = requests.post(f"{self.base}/chat/completions", json=body, timeout=300, headers=self._headers())
            if r.status_code == 404 and "model" in r.text.lower():
                mark_exhausted(self.model)            # modèle retiré : inutile de le redemander aujourd'hui
            if r.status_code in (503, 404) and self.fallbacks and switch():   # saturé ou retiré : le suivant
                continue
            if r.status_code == 429:
                wait = self._retry_after(r)
                low = r.text.lower()
                per_day = "PerDay" in r.text or "per day" in low or "month" in low or "daily" in low
                if not per_day and attempt < 3 and (wait is None or wait <= 65):
                    time.sleep(wait + 0.5 if wait is not None else 1.5 * (attempt + 1))   # limite par minute/seconde
                    continue
                if per_day:
                    mark_exhausted(self.model)
                if switch():                          # quota du jour épuisé pour ce modèle : un autre modèle gratuit
                    continue
                raise LLMError(f"{self.name} : quota gratuit atteint ({security.redact(r.text[:200])})")
            if r.status_code >= 500 and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 200 and malformed < 2 and "MALFORMED_FUNCTION_CALL" in r.text[:4000]:
                malformed += 1                    # Gemini rate parfois la forme d'un appel : on redemande
                body["temperature"] = min(1.0, body.get("temperature", 0.2) + 0.3)
                continue
            break
        if r.status_code >= 400:
            raise LLMError(f"{self.name} HTTP {r.status_code}: {security.redact(r.text[:300])}")
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        if "MALFORMED_FUNCTION_CALL" in str(choice.get("finish_reason", "")):
            raise LLMError(f"{self.name} : appel d'outil mal formé côté service")
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        calls = [{"id": c.get("id") or uuid.uuid4().hex[:8], "name": c["function"]["name"],
                  "arguments": _parse_args(c["function"].get("arguments")),
                  # Gemini 3 : signature de pensée, liée au modèle qui l'a produite (_m, jamais envoyé)
                  **({"extra": {**c["extra_content"], "_m": self.model}} if isinstance(c.get("extra_content"), dict) else {})}
                 for c in msg.get("tool_calls") or [] if c.get("function")]
        thinking = msg.get("reasoning") or msg.get("reasoning_content") or ""
        content, thinking, calls = self._post(content, thinking, calls)
        if stream and thinking:
            stream("thinking", thinking)
        if stream and content:
            stream("content", content)
        u = data.get("usage") or {}
        stats = {"prompt_eval_count": u.get("prompt_tokens", 0), "eval_count": u.get("completion_tokens", 0),
                 "total_duration": (time.time() - t_req) * 1e9}
        return {"content": content, "thinking": thinking, "tool_calls": calls, "stats": stats}

    def all_exhausted(self) -> bool:
        """Plus aucun modèle de ce service n'a de quota aujourd'hui : on passe directement au relais."""
        return exhausted(self.model) and all(exhausted(m) for m in self.fallbacks)

    def _post(self, content, thinking, calls):
        return content, thinking, calls


HARMONY_SEG = re.compile(r"(?:<\|start\|>)?(?P<head>[^<]*?(?:<\|channel\|>[^<]*)?(?:<\|constrain\|>[^<]*)?)<\|message\|>"
                         r"(?P<body>.*?)(?=<\|end\|>|<\|call\|>|<\|return\|>|<\|start\|>|$)", re.S)


def parse_harmony(raw: str) -> tuple[str, str, list[dict]]:
    """Sortie brute de gpt-oss (format « harmony ») → (réponse, réflexion, appels d'outils).
    mlx_lm.server ne fait pas cette analyse : on la fait ici."""
    if "<|message|>" not in raw and "<|channel|>" not in raw:
        return raw.strip(), "", []
    content, thinking, calls = [], [], []
    for m in HARMONY_SEG.finditer(raw):
        head, body = m.group("head") or "", (m.group("body") or "").strip()
        to = re.search(r"to=functions\.([A-Za-z0-9_\-]+)", head)
        if to:
            calls.append({"id": uuid.uuid4().hex[:8], "name": to.group(1), "arguments": _parse_args(body)})
        elif "analysis" in head:
            thinking.append(body)
        elif "final" in head or not head.strip() or "commentary" in head:
            content.append(body)
    return "\n".join(c for c in content if c).strip(), "\n".join(thinking).strip(), calls


class MLXBackend(OpenAICompatBackend):
    """Moteur MLX d'Apple (mlx_lm.server, local) : ~30 % plus rapide que llama.cpp sur M5 (mesuré : 40 contre 30
    jetons/s pour gpt-oss-20b). Rien ne quitte le Mac."""

    def __init__(self, base_url: str, model: str, label: str):
        super().__init__(base_url, model, "local", "mlx")
        self.name = label
        self.can_stream = True
        self.default_max_tokens = 16384     # mlx_lm.server s'arrête à 512 jetons par défaut : patchs et fichiers coupés

    def available(self) -> bool:
        try:
            return requests.get(f"{self.base}/models", timeout=2).ok
        except requests.RequestException:
            return False

    def _headers(self):
        return {"Content-Type": "application/json"}

    def all_exhausted(self) -> bool:
        """Plus aucun modèle de ce service n'a de quota aujourd'hui : on passe directement au relais."""
        return exhausted(self.model) and all(exhausted(m) for m in self.fallbacks)

    def _post(self, content, thinking, calls):
        if calls:
            return content, thinking, calls
        c, t, k = parse_harmony(content)
        return c, (thinking + "\n" + t).strip() if t else thinking, k

    think_default = False

    def _extra_body(self, think) -> dict:
        """Niveau de réflexion de gpt-oss choisi à chaque appel (rapide pour agir, plus poussé pour vérifier)."""
        want = self.think_default if think == "auto" else think
        return {"chat_template_kwargs": {"reasoning_effort": think_value("gpt-oss", want)}}

    def _chat_stream(self, body, stream) -> dict:
        """Texte en direct : on lit le flux de mlx_lm.server et on n'affiche que la réponse (et la réflexion à part),
        jamais les balises internes de gpt-oss. Les appels d'outils sont extraits à la fin."""
        body = {**body, "stream": True, "stream_options": {"include_usage": True}}
        t0 = time.time()
        r = requests.post(f"{self.base}/chat/completions", json=body, timeout=300, headers=self._headers(), stream=True)
        if r.status_code >= 400:
            raise LLMError(f"{self.name} HTTP {r.status_code}: {r.text[:300]}")
        raw, sent_c, sent_t, usage, t_first = "", "", "", {}, 0.0
        for line in r.iter_lines(decode_unicode=True):
            if not t_first and line and line.startswith("data: "):
                t_first = time.time()             # premier jeton : la lecture des instructions est finie
            if not line or not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            usage = chunk.get("usage") or usage
            for ch in chunk.get("choices") or []:
                raw += (ch.get("delta") or {}).get("content") or ""
            view = raw
            cut = view.rfind("<|")
            if cut >= 0 and "|>" not in view[cut:]:
                view = view[:cut]                     # balise pas encore complète : on attend
            if "<|message|>" not in view and ("<|" in view or len(view) < 12):
                continue
            c, t, _ = parse_harmony(view)
            if t.startswith(sent_t) and len(t) > len(sent_t):
                stream("thinking", t[len(sent_t):])
                sent_t = t
            if c.startswith(sent_c) and len(c) > len(sent_c):
                stream("content", c[len(sent_c):])
                sent_c = c
        content, thinking, calls = parse_harmony(raw)
        t_end, t_first = time.time(), t_first or time.time()
        ns = 1e9                                   # mêmes mesures qu'Ollama, pour comparer les moteurs dans perf.jsonl
        stats = {"prompt_eval_count": usage.get("prompt_tokens", 0), "eval_count": usage.get("completion_tokens", 0),
                 "prompt_eval_duration": (t_first - t0) * ns, "eval_duration": (t_end - t_first) * ns,
                 "total_duration": (t_end - t0) * ns}
        return {"content": content, "thinking": thinking, "tool_calls": calls, "stats": stats}


def make_cloud(cfg: dict) -> OpenAICompatBackend | None:
    c = cfg.get("cloud") or {}
    if not c.get("enabled") or c.get("mode", "ask") == "off" or not c.get("model"):
        return None
    prov = c.get("provider", "custom")
    base = c.get("base_url") or PROVIDERS.get(prov, {}).get("base_url", "")
    key = cloud_key(prov)
    if not (base and key):
        return None
    b = OpenAICompatBackend(base, c["model"], key, prov)
    b.fallbacks = fallback_chain(prov, c.get("models") or [], c["model"], first=c.get("fallbacks") or [])
    return b


class AppleBackend:
    """Modèle d'Apple (Apple Intelligence) via un raccourci « Utiliser un modèle » que tu crées une fois dans
    Raccourcis. « Cloud » / « Cloud Pro » tournent sur le Private Cloud Compute d'Apple : gratuit (limite par jour),
    sans clé, et Apple ne garde pas les données. Texte seulement (pas d'outils) : Jarvis s'en sert pour rédiger."""
    SHORTCUT = "Jarvis · modèle Apple"

    def __init__(self, name: str = SHORTCUT):
        self.shortcut, self.name, self.model = name, "Apple · Private Cloud", "apple"

    @staticmethod
    def installed(name: str = SHORTCUT) -> bool:
        try:
            out = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=20).stdout
            return name in out.splitlines()
        except (OSError, subprocess.SubprocessError):
            return False

    def chat(self, messages, tools=None, options=None, stream=None, think="auto") -> dict:
        if tools:
            raise LLMError("le modèle d'Apple ne pilote pas d'outils")
        parts = []
        for m in messages:
            c = m.get("content") or ""
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            if c.strip():
                parts.append(("Consignes : " if m["role"] == "system" else "Réponse précédente : " if m["role"] == "assistant"
                              else "") + c.strip())
        prompt = "\n\n".join(parts)[-60000:]
        t0 = time.time()
        with tempfile.TemporaryDirectory(prefix="jarvis-apple-") as d:
            src, dst = Path(d) / "demande.txt", Path(d) / "reponse.txt"
            src.write_text(prompt, encoding="utf-8")
            try:
                r = subprocess.run(["shortcuts", "run", self.shortcut, "--input-path", str(src), "--output-path", str(dst),
                                    "--output-type", "public.plain-text"], capture_output=True, text=True, timeout=180)
            except subprocess.TimeoutExpired:
                raise LLMError("le modèle d'Apple n'a pas répondu à temps")
            text = dst.read_text(encoding="utf-8", errors="replace").strip() if dst.exists() else ""
        if r.returncode != 0 or not text:
            raise LLMError(f"raccourci « {self.shortcut} » : {(r.stderr or r.stdout or 'pas de réponse').strip()[:200]}")
        return {"content": text, "thinking": "", "tool_calls": [],
                "stats": {"eval_count": len(text) // 4, "total_duration": (time.time() - t0) * 1e9}}


def make_relay(cfg: dict) -> OpenAICompatBackend | None:
    """Deuxième service gratuit, utilisé quand le premier a épuisé ses quotas (ou ne répond plus)."""
    c = cfg.get("cloud") or {}
    r = c.get("relay") or {}
    if not (c.get("enabled") and c.get("mode", "ask") != "off" and r.get("enabled") and r.get("model")):
        return None
    prov = r.get("provider", "custom")
    if prov == c.get("provider"):
        return None
    base = r.get("base_url") or PROVIDERS.get(prov, {}).get("base_url", "")
    key = cloud_key(prov)
    if not (base and key):
        return None
    b = OpenAICompatBackend(base, r["model"], key, prov)
    b.name = f"relais · {r['model']}"
    b.fallbacks = fallback_chain(prov, r.get("models") or [], r["model"], first=r.get("fallbacks") or [])
    return b


class Router:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        think = cfg.get("think")
        self.ollama = OllamaBackend(cfg["ollama_host"], cfg["model"], f"Mac · {cfg['model']}", think)
        self.local = self.ollama
        if cfg.get("engine") == "mlx" and (cfg.get("mlx") or {}).get("url"):
            mx = cfg["mlx"]
            self.local = MLXBackend(mx["url"], mx.get("model", "default_model"), f"Mac · MLX · {cfg['model']}")
            self.local.think_default = bool(cfg.get("think"))
        self.remote = None
        if cfg.get("remote_ollama_host"):
            rm = cfg.get("remote_model") or cfg["model"]
            self.remote = OllamaBackend(cfg["remote_ollama_host"], rm, f"réseau · {rm}", think)
        self.cloud = make_cloud(cfg)
        self.relay = make_relay(cfg)
        self.clouds = [b for b in (self.cloud, self.relay) if b]
        if not self.cloud and self.relay:          # renfort principal sans clé : le relais tient le rôle
            self.cloud = self.relay
            self.clouds = [self.relay]
        self.relay_used = False
        ap = cfg.get("apple") or {}
        self.apple = AppleBackend(ap.get("shortcut") or AppleBackend.SHORTCUT) if ap.get("enabled") else None
        self.vision_backend = OllamaBackend(cfg["ollama_host"], cfg["vision_model"], "vision") if cfg.get("vision_model") else None
        self.last_used = ""
        self.cloud_error = ""

    def write(self, messages, max_tokens: int = 1500, think="low", cloud=False) -> dict:
        """Rédaction sans outils (rapport de recherche, résumé) : le renfort si la tâche l'a, sinon le modèle privé
        d'Apple s'il est activé, sinon le modèle du Mac."""
        if self.apple and not cloud:
            try:
                out = self.apple.chat(messages)
                self.last_used = self.apple.name
                _perf(self.apple.name, out.get("stats"), len(messages), False)
                return out
            except LLMError as e:
                self.apple_error = str(e)
        return self.chat(messages, tools=None, cloud=cloud, think=think, options={"temperature": 0.2, "num_predict": max_tokens})

    def chain(self, cloud=False):
        """Le renfort cloud n'est JAMAIS utilisé d'office : seulement quand la tâche l'a obtenu (accord ou mode auto)."""
        order = [self.remote, self.local] if self.cfg.get("prefer_remote") else [self.local, self.remote]
        if self.local is not self.ollama:
            order.append(self.ollama)           # service MLX arrêté ? Ollama prend le relais automatiquement
        order = [b for b in order if b]
        if cloud and self.clouds:
            live = [b for b in self.clouds if not b.all_exhausted()] or self.clouds[-1:]
            order = live + order
        return order

    def chat(self, messages, tools=None, cloud=False, options=None, stream: Stream = None, think="auto") -> dict:
        opts = {"num_ctx": model_ctx(self.cfg, self.cfg.get("model", "")), "temperature": self.cfg["temperature"], **(options or {})}
        errors, cloud_errs = [], []
        self.cloud_error = ""
        for backend in self.chain(cloud):
            for attempt in range(3):
                try:
                    out = backend.chat(messages, tools, opts, stream, think)
                    self.last_used = backend.name
                    if backend in self.clouds:
                        self.cloud_error = ""             # étape faite en ligne (au besoin par le relais)
                        if backend is self.relay and self.relay is not self.clouds[0]:
                            self.relay_used = True
                    elif cloud_errs:                  # tous les services en ligne ont échoué : étape faite en local
                        self.cloud_error = " · ".join(cloud_errs)[:300]
                    _perf(backend.name, out.get("stats"), len(messages), bool(tools))
                    return out
                except ToolParseError:
                    raise                             # c'est au modèle de corriger : l'agent le lui signale
                except requests.ConnectionError as e:
                    errors.append(f"{backend.name}: injoignable ({e.__class__.__name__})")
                    if backend in self.clouds:
                        cloud_errs.append(f"{backend.name} : service injoignable (Internet ?)")
                        self.cloud_error = " · ".join(cloud_errs)[:300]
                    break
                except (requests.RequestException, LLMError, KeyError, ValueError) as e:
                    errors.append(f"{backend.name}: {e}")
                    if backend in self.clouds:
                        cloud_errs.append(str(e)[:200])
                        self.cloud_error = " · ".join(cloud_errs)[:300]
                        break                         # indisponible (quota…) : relais, sinon retour en local
                    if "not found" in str(e).lower():
                        break
                    time.sleep(1.5 * (attempt + 1))
        raise LLMError("Aucun modèle n'a répondu :\n" + "\n".join(errors[-4:]))

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.ollama.embed(texts, self.cfg.get("embed_model", "nomic-embed-text"))

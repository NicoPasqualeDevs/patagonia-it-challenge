from __future__ import annotations

import socket
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from orchestrator.retry import PermanentError

USER_AGENT = "patagonia-it-orchestrator/1.0 (demo; local)"
TIMEOUT_S = 12
ART = timezone(timedelta(hours=-3))

PLACES: dict[str, dict[str, Any]] = {
    "palermo": {
        "lat": -34.588,
        "lon": -58.430,
        "label": "Palermo (Sakura, Honduras 4780)",
    },
    "sakura": {
        "lat": -34.588,
        "lon": -58.430,
        "label": "Palermo (Sakura, Honduras 4780)",
    },
    "belgrano": {
        "lat": -34.562,
        "lon": -58.456,
        "label": "Belgrano (Lima de Barrio, Cabildo 2450)",
    },
    "lima": {
        "lat": -34.562,
        "lon": -58.456,
        "label": "Belgrano (Lima de Barrio, Cabildo 2450)",
    },
    "recoleta": {
        "lat": -34.595,
        "lon": -58.392,
        "label": "Recoleta (Café Andino, Av. Callao 1240)",
    },
    "andino": {
        "lat": -34.595,
        "lon": -58.392,
        "label": "Recoleta (Café Andino, Av. Callao 1240)",
    },
    "caba": {"lat": -34.61, "lon": -58.38, "label": "CABA"},
    "buenos aires": {"lat": -34.61, "lon": -58.38, "label": "CABA"},
}

AGENT_PLACE = {
    "agt_sakura": "palermo",
    "agt_lima": "belgrano",
    "agt_andino": "recoleta",
    "agt_geo": "caba",
    "agt_nutri": "caba",
}

AGENT_ADDRESS = {
    "agt_sakura": "Honduras 4780",
    "agt_lima": "Cabildo 2450",
    "agt_andino": "Callao 1240",
}

WMO = {
    0: "despejado",
    1: "mayormente despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "niebla",
    48: "niebla con rime",
    51: "llovizna débil",
    53: "llovizna",
    55: "llovizna intensa",
    61: "lluvia débil",
    63: "lluvia",
    65: "lluvia intensa",
    80: "chubascos",
    81: "chubascos fuertes",
    95: "tormenta",
    96: "tormenta con granizo",
}

FOOD_TERMS = (
    "edamame",
    "ramen",
    "nigiri",
    "salmón",
    "salmon",
    "tempura",
    "mochi",
    "soja",
    "trigo",
    "ceviche",
    "lomo saltado",
    "ají de gallina",
    "aji de gallina",
    "causa",
    "pisco",
    "medialuna",
    "café",
    "cafe",
)

DOLLAR_HINTS = (
    "dolar",
    "dólar",
    "usd",
    "oficial",
    "en dólares",
    "en dolares",
    "cotización",
    "cotizacion",
)
WEATHER_HINTS = (
    "clima",
    "lluv",
    "frío",
    "frio",
    "calor",
    "temperatura",
    "nublado",
    "despejado",
    "hace frío",
    "hace frio",
    "hace calor",
)
HOLIDAY_HINTS = (
    "feriado",
    "abierto hoy",
    "abre hoy",
    "hoy abren",
    "hoy cierra",
    "hoy cerrado",
    "puente",
)
TIME_HINTS = (
    "qué hora",
    "que hora",
    "hora es",
    "último pedido",
    "ultimo pedido",
    "llego",
    "llego a",
    "alcanzo",
    "ahora mismo",
)
FOOD_HINTS = (
    "kcal",
    "caloría",
    "caloria",
    "proteína",
    "proteina",
    "alérgeno",
    "alergeno",
    "nutri",
    "sodio",
    "celiac",
    "gluten",
    "datos públicos",
    "open food",
)
GEO_HINTS = (
    "dónde queda",
    "donde queda",
    "dirección",
    "direccion",
    "geocod",
    "coordenad",
    "normalizar",
)


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def http_get_json(url: str, *, headers: dict[str, str] | None = None, attempts: int = 3) -> Any:
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, headers=req_headers, method="GET")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                raw = response.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError("la API no devolvió JSON válido") from exc
        except urllib.error.HTTPError as exc:
            last_error = RuntimeError(f"HTTP {exc.code} al consultar {url}")
            if exc.code < 500 or attempt >= attempts:
                raise last_error from exc
        except urllib.error.URLError as exc:
            last_error = RuntimeError(f"no se pudo conectar: {exc.reason}")
            if attempt >= attempts:
                raise last_error from exc
        except (TimeoutError, socket.timeout) as exc:
            last_error = RuntimeError(f"timeout al consultar {url}")
            if attempt >= attempts:
                raise last_error from exc
        time.sleep(0.4 * attempt)
    raise last_error or RuntimeError(f"falló {url}")


def _fail(source: str, error: str) -> dict[str, Any]:
    return {"ok": False, "source": source, "error": error, "data": None}


def _ok(source: str, data: Any, **extra: Any) -> dict[str, Any]:
    payload = {"ok": True, "source": source, "data": data}
    payload.update(extra)
    return payload


def resolve_place(place: str | None, *, agent_id: str | None = None) -> dict[str, Any]:
    key = _norm(place or "")
    if key in PLACES:
        return PLACES[key]
    for name, meta in PLACES.items():
        if name in key:
            return meta
    if agent_id and agent_id in AGENT_PLACE:
        return PLACES[AGENT_PLACE[agent_id]]
    return PLACES["caba"]


def get_weather(place: str = "caba") -> dict[str, Any]:
    meta = resolve_place(place)
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode(
            {
                "latitude": meta["lat"],
                "longitude": meta["lon"],
                "current": "temperature_2m,precipitation,weather_code",
                "timezone": "America/Argentina/Buenos_Aires",
            }
        )
    )
    try:
        body = http_get_json(url)
    except RuntimeError as exc:
        return _fail("open-meteo", str(exc))
    current = body.get("current") if isinstance(body, dict) else None
    if not isinstance(current, dict):
        return _fail("open-meteo", "respuesta sin current")
    code = current.get("weather_code")
    try:
        code_int = int(code)
    except (TypeError, ValueError):
        code_int = -1
    data = {
        "place": meta["label"],
        "latitude": meta["lat"],
        "longitude": meta["lon"],
        "temperature_c": current.get("temperature_2m"),
        "precipitation_mm": current.get("precipitation"),
        "condition": WMO.get(code_int, f"código {code}"),
        "observed_at": current.get("time"),
    }
    return _ok("open-meteo", data)


def get_dollar(casa: str = "all") -> dict[str, Any]:
    kind = _norm(casa) or "all"
    aliases = {"oficial": "oficial", "bolsa": "bolsa", "mep": "bolsa"}
    path = aliases.get(kind)
    url = (
        f"https://dolarapi.com/v1/dolares/{path}"
        if path
        else "https://dolarapi.com/v1/dolares"
    )
    try:
        body = http_get_json(url)
    except RuntimeError as exc:
        return _fail("dolarapi", str(exc))
    rows = body if isinstance(body, list) else [body]
    quotes = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("casa") or row.get("nombre") or "")
        if "blue" in label.lower():
            continue
        quotes.append(
            {
                "casa": label,
                "compra": row.get("compra"),
                "venta": row.get("venta"),
                "fecha": row.get("fechaActualizacion"),
            }
        )
    if not quotes:
        return _fail("dolarapi", "sin cotizaciones")
    return _ok("dolarapi", quotes)


def get_holidays(year: int | str | None = None) -> dict[str, Any]:
    today = datetime.now(ART).date()
    try:
        y = int(year) if year not in (None, "", "current") else today.year
    except (TypeError, ValueError) as exc:
        raise PermanentError("get_holidays requiere un año numérico") from exc
    url = f"https://api.argentinadatos.com/v1/feriados/{y}"
    try:
        body = http_get_json(url)
    except RuntimeError as exc:
        return _fail("argentinadatos", str(exc))
    if not isinstance(body, list):
        return _fail("argentinadatos", "respuesta inesperada")
    today_iso = today.isoformat()
    today_hit = next((row for row in body if isinstance(row, dict) and row.get("fecha") == today_iso), None)
    upcoming = [
        row
        for row in body
        if isinstance(row, dict) and str(row.get("fecha") or "") >= today_iso
    ][:5]
    return _ok(
        "argentinadatos",
        {
            "year": y,
            "today": today_iso,
            "today_is_holiday": bool(today_hit),
            "today_holiday": today_hit,
            "upcoming": upcoming,
        },
    )


def lookup_food(query: str) -> dict[str, Any]:
    term = (query or "").strip()
    if not term:
        raise PermanentError("lookup_food requiere query")
    params = urllib.parse.urlencode(
        {
            "search_terms": term,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": 1,
        }
    )
    url = f"https://world.openfoodfacts.org/cgi/search.pl?{params}"
    try:
        body = http_get_json(url)
    except RuntimeError as exc:
        return _fail("openfoodfacts", str(exc))
    products = body.get("products") if isinstance(body, dict) else None
    product = products[0] if isinstance(products, list) and products else None
    if not isinstance(product, dict):
        return _ok("openfoodfacts", {"query": term, "found": False})
    nutriments = product.get("nutriments") if isinstance(product.get("nutriments"), dict) else {}
    labels = product.get("labels_tags") if isinstance(product.get("labels_tags"), list) else []
    data = {
        "query": term,
        "found": True,
        "product_name": product.get("product_name") or product.get("product_name_en"),
        "brands": product.get("brands"),
        "allergens_tags": product.get("allergens_tags") or [],
        "traces_tags": product.get("traces_tags") or [],
        "labels": labels[:8],
        "nutriscore_grade": product.get("nutriscore_grade"),
        "kcal_100g": nutriments.get("energy-kcal_100g"),
        "proteins_100g": nutriments.get("proteins_100g"),
        "salt_100g": nutriments.get("salt_100g"),
        "fat_100g": nutriments.get("fat_100g"),
        "url": product.get("url"),
    }
    return _ok("openfoodfacts", data)


def geocode_address(address: str) -> dict[str, Any]:
    text = (address or "").strip()
    if not text:
        raise PermanentError("geocode_address requiere address")
    url = "https://servicios.usig.buenosaires.gob.ar/normalizar/?" + urllib.parse.urlencode(
        {"direccion": text, "geocodificar": "true"}
    )
    try:
        body = http_get_json(url)
    except RuntimeError as exc:
        return _fail("usig", str(exc))
    rows = body.get("direccionesNormalizadas") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not rows:
        return _ok("usig", {"address": text, "found": False})
    typed_rows = [row for row in rows if isinstance(row, dict)]
    first = next(
        (
            row
            for row in typed_rows
            if str(row.get("cod_partido") or "").lower() == "caba"
            or "caba" in str(row.get("direccion") or "").lower()
        ),
        typed_rows[0],
    )
    coords = first.get("coordenadas") if isinstance(first.get("coordenadas"), dict) else {}
    data = {
        "address": text,
        "found": True,
        "normalized": first.get("direccion") or first.get("nombre_calle"),
        "street": first.get("nombre_calle"),
        "height": first.get("altura"),
        "barrio": first.get("nombre_localidad") or first.get("barrio"),
        "comuna": first.get("nombre_partido") or first.get("comuna"),
        "lon": coords.get("x"),
        "lat": coords.get("y"),
        "matches": len(typed_rows),
    }
    return _ok("usig", data)


def get_local_time() -> dict[str, Any]:
    url = "https://worldtimeapi.org/api/timezone/America/Argentina/Buenos_Aires"
    try:
        body = http_get_json(url)
        if isinstance(body, dict) and body.get("datetime"):
            return _ok(
                "worldtimeapi",
                {
                    "datetime": body.get("datetime"),
                    "day_of_week": body.get("day_of_week"),
                    "timezone": body.get("timezone"),
                    "utc_offset": body.get("utc_offset"),
                },
            )
    except RuntimeError:
        pass
    now = datetime.now(ART)
    return _ok(
        "utc-3",
        {
            "datetime": now.isoformat(),
            "day_of_week": now.weekday(),
            "timezone": "America/Argentina/Buenos_Aires",
            "utc_offset": "-03:00",
            "fallback": True,
        },
    )


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _food_query_from(message: str) -> str:
    text = _norm(message)
    for term in FOOD_TERMS:
        if term in text:
            return term
    words = re.findall(r"[a-záéíóúñ]{4,}", text)
    return words[0] if words else "edamame"


def _place_from_message(message: str, agent: dict[str, Any]) -> str:
    text = _norm(message)
    for name in ("palermo", "belgrano", "recoleta", "sakura", "lima", "andino"):
        if name in text:
            return name
    return AGENT_PLACE.get(str(agent.get("id") or ""), "caba")


def detect_public_tools(text: str, *, agent_type: str = "") -> list[str]:
    body = _norm(text)
    tools: list[str] = []
    if _contains_any(body, DOLLAR_HINTS):
        tools.append("get_dollar")
    if _contains_any(body, WEATHER_HINTS) or (agent_type == "geo" and "clima" in body):
        tools.append("get_weather")
    if _contains_any(body, HOLIDAY_HINTS):
        tools.append("get_holidays")
    if _contains_any(body, TIME_HINTS):
        tools.append("get_local_time")
    if (
        agent_type == "nutrition" and _contains_any(body, FOOD_HINTS + FOOD_TERMS)
    ) or _contains_any(body, FOOD_HINTS):
        tools.append("lookup_food")
    if _contains_any(body, GEO_HINTS):
        tools.append("geocode_address")
    return tools


def default_public_tool_args(
    tool: str,
    text: str = "",
    *,
    agent_id: str = "",
    agent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = agent if agent is not None else ({"id": agent_id} if agent_id else {})
    if tool == "get_dollar":
        return {"casa": "all"}
    if tool == "get_weather":
        return {"place": _place_from_message(text, payload)}
    if tool == "lookup_food":
        return {"query": _food_query_from(text)}
    if tool == "geocode_address":
        key = str(payload.get("id") or agent_id or "")
        address = AGENT_ADDRESS.get(key) or "Honduras 4780"
        body = _norm(text)
        for known in AGENT_ADDRESS.values():
            if known.split()[0].lower() in body:
                address = known
                break
        return {"address": address}
    return {}


def fetch_live_facts(
    agent: dict[str, Any],
    message: str,
    *,
    skip: set[str] | None = None,
) -> list[dict[str, Any]]:
    skip_tools = skip or set()
    agent_type = str(agent.get("type") or "")
    facts: list[dict[str, Any]] = []
    callers = {
        "get_dollar": lambda: get_dollar("all"),
        "get_weather": lambda: get_weather(_place_from_message(message, agent)),
        "get_holidays": get_holidays,
        "get_local_time": get_local_time,
        "lookup_food": lambda: lookup_food(_food_query_from(message)),
        "geocode_address": lambda: geocode_address(
            default_public_tool_args("geocode_address", message, agent=agent)["address"]
        ),
    }
    for tool in detect_public_tools(message, agent_type=agent_type):
        if tool in skip_tools:
            continue
        facts.append({"tool": tool, **callers[tool]()})
    return facts


PUBLIC_TOOL_LABELS = {
    "get_weather": "clima",
    "get_dollar": "dólar",
    "get_holidays": "feriados",
    "get_local_time": "hora local",
    "lookup_food": "el plato pedido",
    "geocode_address": "la ubicación",
}


def disabled_tool_fact(tool: str) -> dict[str, Any]:
    label = PUBLIC_TOOL_LABELS.get(tool, tool)
    return {
        "ok": False,
        "skipped": True,
        "disabled": True,
        "error": f"{label} no disponible: la tool está desactivada",
        "agent_hint": (
            f"Pedí disculpas porque no podés informar {label}. "
            "No inventes el dato y continuá con el resto de la consulta."
        ),
    }


def format_live_facts(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return ""
    blocks = []
    for item in facts:
        tool = item.get("tool") or item.get("source") or "api"
        if item.get("skipped") or item.get("disabled") or not item.get("ok"):
            hint = item.get("agent_hint") or item.get("error") or "dato no disponible"
            blocks.append(f"### {tool}\n{hint}")
            continue
        data = item.get("data")
        blocks.append(f"### {tool}\n{json.dumps(data, ensure_ascii=False, indent=2)}")
    return "\n\n".join(blocks)

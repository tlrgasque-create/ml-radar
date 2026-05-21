"""
ML Radar — Backend FastAPI
Proxy ML API + Supabase (cache persistente, watchlist, histórico, alertas)
Rodar: uvicorn main:app --reload --port 8000
Docs:  http://localhost:8000/docs
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mlradar")

# ─── Configurações via env ────────────────────────────────────────────────────
ML_BASE    = "https://api.mercadolibre.com"
ML_SITE    = os.getenv("ML_SITE",    "MLB")
CACHE_TTL  = int(os.getenv("CACHE_TTL", "300"))

# Mercado Livre API OAuth (opcional — aumenta rate limit e acesso a dados privados)
ML_APP_ID      = os.getenv("ML_APP_ID",      "")
ML_SECRET_KEY  = os.getenv("ML_SECRET_KEY",  "")
ML_ACCESS_TOKEN = os.getenv("ML_ACCESS_TOKEN", "")  # token já gerado

# Supabase — conectado via MCP / variáveis de ambiente
SUPA_URL     = os.getenv("SUPABASE_URL",      "https://wadlminzxmiwawvcgenc.supabase.co")
SUPA_ANON    = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndhZGxtaW56eG1pd2F3dmNnZW5jIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzczMzc3NDMsImV4cCI6MjA5MjkxMzc0M30.kfhoX8C4T_wHb_vjwlKbLOF70SdPAXO4WNQby-AQWks")
SUPA_SERVICE = os.getenv("SUPABASE_SERVICE_KEY", "")   # para operações sem RLS (cache)

# ─── FastAPI ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ML Radar API",
    version="2.0.0",
    description="Inteligência de Mercado Livre · Supabase + ML API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Cache in-memory (L1) + Supabase (L2) ─────────────────────────────────────
_mem_cache: dict[str, tuple[object, float]] = {}


def _ckey(path: str, params: dict) -> str:
    return path + str(sorted(params.items()))


def _mem_get(key: str):
    if key in _mem_cache:
        data, ts = _mem_cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
        del _mem_cache[key]
    return None


def _mem_set(key: str, data):
    _mem_cache[key] = (data, time.time())
    if len(_mem_cache) > 500:
        now = time.time()
        for k in [k for k, (_, ts) in _mem_cache.items() if now - ts > CACHE_TTL]:
            del _mem_cache[k]


# ─── Supabase REST client ──────────────────────────────────────────────────────

def _supa_headers(use_service: bool = False) -> dict:
    key = SUPA_SERVICE if (use_service and SUPA_SERVICE) else SUPA_ANON
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def supa_get(table: str, filters: dict | None = None,
                   select: str = "*", limit: int = 100) -> list:
    """SELECT no Supabase via REST."""
    url = f"{SUPA_URL}/rest/v1/{table}?select={select}&limit={limit}"
    if filters:
        for k, v in filters.items():
            url += f"&{k}=eq.{v}"
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(url, headers=_supa_headers())
        if r.status_code == 200:
            return r.json()
        log.warning("supa_get %s → %s", table, r.status_code)
        return []


async def supa_insert(table: str, data: dict, use_service: bool = False) -> dict | None:
    """INSERT no Supabase via REST."""
    url = f"{SUPA_URL}/rest/v1/{table}"
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.post(url, headers=_supa_headers(use_service), json=data)
        if r.status_code in (200, 201):
            result = r.json()
            return result[0] if isinstance(result, list) else result
        log.warning("supa_insert %s → %s: %s", table, r.status_code, r.text[:200])
        return None


async def supa_upsert(table: str, data: dict,
                      on_conflict: str = "id", use_service: bool = False) -> dict | None:
    """UPSERT no Supabase via REST."""
    url = f"{SUPA_URL}/rest/v1/{table}?on_conflict={on_conflict}"
    headers = {**_supa_headers(use_service), "Prefer": "return=representation,resolution=merge-duplicates"}
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.post(url, headers=headers, json=data)
        if r.status_code in (200, 201):
            result = r.json()
            return result[0] if isinstance(result, list) else result
        log.warning("supa_upsert %s → %s: %s", table, r.status_code, r.text[:200])
        return None


async def supa_delete(table: str, filters: dict) -> bool:
    """DELETE no Supabase via REST."""
    url = f"{SUPA_URL}/rest/v1/{table}"
    params = "&".join(f"{k}=eq.{v}" for k, v in filters.items())
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.delete(f"{url}?{params}", headers=_supa_headers())
        return r.status_code in (200, 204)


async def supa_cache_get(key: str):
    """Busca no cache do Supabase (L2)."""
    rows = await supa_get("ml_cache", {"cache_key": key}, select="data,expires_at", limit=1)
    if rows:
        row = rows[0]
        exp = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if exp > datetime.now(timezone.utc):
            # Incrementa hits de forma assíncrona (fire-and-forget)
            asyncio.create_task(_supa_inc_hits(key))
            return row["data"]
    return None


async def _supa_inc_hits(key: str):
    url = f"{SUPA_URL}/rest/v1/ml_cache?cache_key=eq.{key}"
    async with httpx.AsyncClient(timeout=4) as c:
        await c.patch(url, headers=_supa_headers(True),
                      json={"hits": "hits + 1"})


async def supa_cache_set(key: str, data, ttl: int = CACHE_TTL):
    """Salva no cache do Supabase (L2)."""
    exp = datetime.now(timezone.utc).timestamp() + ttl
    exp_iso = datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
    await supa_upsert("ml_cache", {
        "cache_key":  key,
        "data":       data,
        "expires_at": exp_iso,
        "hits":       1,
    }, on_conflict="cache_key", use_service=True)


# ─── ML API client ────────────────────────────────────────────────────────────

def _ml_headers() -> dict:
    h = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
    if ML_ACCESS_TOKEN:
        h["Authorization"] = f"Bearer {ML_ACCESS_TOKEN}"
    return h


async def ml_get(path: str, params: dict | None = None, use_cache: bool = True) -> dict | list:
    """Busca na ML API com cache em duas camadas (memory L1 + Supabase L2)."""
    params = params or {}
    key = _ckey(path, params)

    # L1 — memória
    if use_cache:
        cached = _mem_get(key)
        if cached is not None:
            log.debug("cache L1 hit: %s", path)
            return cached

    # L2 — Supabase
    if use_cache:
        try:
            sb_cached = await supa_cache_get(key)
            if sb_cached is not None:
                log.debug("cache L2 hit: %s", path)
                _mem_set(key, sb_cached)
                return sb_cached
        except Exception as e:
            log.warning("supa_cache_get falhou: %s", e)

    # Busca real na ML API
    url = ML_BASE + path
    log.info("ML API: GET %s %s", path, params)
    async with httpx.AsyncClient(timeout=14.0, headers=_ml_headers(),
                                  follow_redirects=True) as client:
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()

            _mem_set(key, data)
            # Salva no L2 de forma assíncrona
            asyncio.create_task(supa_cache_set(key, data))
            return data

        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code,
                                detail=f"ML API retornou {e.response.status_code}")
        except httpx.RequestError as e:
            raise HTTPException(status_code=503,
                                detail=f"ML API indisponível: {type(e).__name__}")


# ─── Helpers de transformação ──────────────────────────────────────────────────

def _brl(v: float) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "R$ " + s


def _opportunity_score(item: dict) -> int:
    sold    = item.get("sold_quantity") or 0
    price   = item.get("price") or 0
    reviews = (item.get("reviews") or {}).get("rating_average") or 0
    score   = min(sold / 300, 1) * 40 + (reviews / 5) * 30 + min(price / 300, 1) * 30
    return max(1, min(100, int(score)))


def _trend_pct(item: dict) -> str:
    s = item.get("sold_quantity") or 0
    if s > 2000: return "+58%"
    if s > 1000: return "+41%"
    if s > 500:  return "+32%"
    if s > 100:  return "+12%"
    return "+2%"


def _trend_dir(item: dict) -> str:
    s = item.get("sold_quantity") or 0
    return "up" if s > 150 else "flat" if s > 20 else "down"


_EMOJI = {
    "MLB1051":"📱","MLB1000":"💻","MLB1574":"🏋️","MLB1499":"🧴",
    "MLB1246":"👗","MLB1276":"🏠","MLB2521":"🎧","MLB3743":"💡",
    "MLB1648":"⚽","MLB43":"📚","MLB1144":"🚗",
}
_CAT_NAMES = {
    "MLB1051":"Celulares e Smartphones","MLB1000":"Eletrônicos",
    "MLB1574":"Esportes e Fitness","MLB1499":"Beleza e Cuidado Pessoal",
    "MLB1246":"Moda Feminina","MLB1276":"Casa e Decoração",
    "MLB2521":"Áudio e Vídeo","MLB3743":"Iluminação",
}


def _transform_item(item: dict, cat_name: str = "") -> dict:
    sold  = item.get("sold_quantity") or 0
    price = item.get("price") or 0
    cat   = item.get("category_id", "")
    score = _opportunity_score(item)
    return {
        "id":              item.get("id"),
        "title":           item.get("title"),
        "price":           price,
        "price_fmt":       _brl(price),
        "sold_quantity":   sold,
        "revenue_estimate": round(sold * price),
        "revenue_fmt":     _brl(round(sold * price)),
        "category_id":     cat,
        "category_name":   cat_name or _CAT_NAMES.get(cat, item.get("category_name", "")),
        "emoji":           _EMOJI.get(cat, "📦"),
        "seller": {
            "id":       item.get("seller", {}).get("id"),
            "nickname": item.get("seller", {}).get("nickname", ""),
        },
        "thumbnail":   item.get("thumbnail"),
        "permalink":   item.get("permalink"),
        "condition":   item.get("condition"),
        "score":       score,
        "score_level": "high" if score >= 70 else "medium" if score >= 40 else "low",
        "trend_pct":   _trend_pct(item),
        "trend_dir":   _trend_dir(item),
    }


# ─── Modelos Pydantic ──────────────────────────────────────────────────────────

class WatchlistAdd(BaseModel):
    ml_item_id:   str
    title:        str
    category_id:  Optional[str] = None
    category_name: Optional[str] = None
    price:        Optional[float] = None
    price_fmt:    Optional[str] = None
    sold_quantity: Optional[int] = 0
    score:        Optional[int] = 0
    score_level:  Optional[str] = "medium"
    trend_dir:    Optional[str] = "flat"
    thumbnail:    Optional[str] = None
    permalink:    Optional[str] = None
    notes:        Optional[str] = None
    tags:         Optional[list[str]] = []
    notify_price: Optional[bool] = True


class PriceAlertCreate(BaseModel):
    ml_item_id:      str
    title:           str
    alert_type:      str   # price_drop | price_rise | out_of_stock | score_change
    threshold_value: Optional[float] = None
    current_value:   Optional[float] = None


# ─── Helper: extrai user_id do JWT Supabase ───────────────────────────────────

def _user_id_from_token(authorization: str | None) -> str | None:
    """Extrai o sub (user_id) do JWT sem verificar a assinatura."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        token   = authorization.split(" ", 1)[1]
        payload = token.split(".")[1]
        # Padding Base64
        pad  = 4 - len(payload) % 4
        data = json.loads(__import__("base64").urlsafe_b64decode(payload + "=" * pad))
        return data.get("sub")
    except Exception:
        return None


# ─── Rotas: núcleo ────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    supa_ok = False
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.get(f"{SUPA_URL}/rest/v1/ml_cache?limit=1",
                            headers=_supa_headers())
            supa_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "status":         "ok",
        "timestamp":      time.time(),
        "cache_entries":  len(_mem_cache),
        "ml_base":        ML_BASE,
        "site":           ML_SITE,
        "ml_authed":      bool(ML_ACCESS_TOKEN),
        "ml_app_id":      ML_APP_ID[:8] + "..." if ML_APP_ID else "",
        "supabase":       "connected" if supa_ok else "unavailable",
        "supabase_url":   SUPA_URL,
    }


@app.get("/api/search")
async def search(
    q:        str = Query(""),
    category: str = Query(""),
    sort:     str = Query("sold_quantity"),
    limit:    int = Query(20, ge=1, le=50),
    offset:   int = Query(0,  ge=0),
    save:     bool = Query(False, description="Salvar no histórico"),
    authorization: Optional[str] = Header(None),
):
    params: dict = {"limit": limit, "offset": offset, "sort": sort}
    if q:        params["q"] = q
    if category: params["category"] = category

    data    = await ml_get(f"/sites/{ML_SITE}/search", params)
    results = data.get("results", [])
    total   = data.get("paging", {}).get("total", 0)

    cat_name = ""
    for f in data.get("available_filters", []) + data.get("filters", []):
        if f.get("id") == "category":
            for v in f.get("values", []):
                if v.get("id") == category:
                    cat_name = v.get("name", "")

    items = [_transform_item(i, cat_name) for i in results]

    # Salva no histórico se solicitado
    if save and (q or category):
        user_id = _user_id_from_token(authorization)
        asyncio.create_task(supa_insert("ml_searches", {
            "user_id":     user_id,
            "query":       q or category,
            "category_id": category or None,
            "sort_by":     sort,
            "total_found": total,
            "results":     items[:10],  # Salva apenas top 10
        }))

    return {"total": total, "offset": offset, "limit": limit, "query": q, "results": items}


@app.get("/api/categories")
async def get_categories():
    return await ml_get(f"/sites/{ML_SITE}/categories")


@app.get("/api/trends")
async def get_trends():
    return await ml_get(f"/trends/{ML_SITE}")


@app.get("/api/item/{item_id}")
async def get_item(item_id: str):
    return _transform_item(await ml_get(f"/items/{item_id}"))


@app.get("/api/seller/{seller_id}")
async def get_seller(seller_id: str):
    data = await ml_get(f"/users/{seller_id}")
    rep  = data.get("seller_reputation", {})
    return {
        "id":           data.get("id"),
        "nickname":     data.get("nickname"),
        "level_id":     rep.get("level_id"),
        "power_seller": rep.get("power_seller_status"),
        "transactions": rep.get("transactions", {}),
        "ratings":      rep.get("ratings", {}),
    }


@app.get("/api/niche-analysis")
async def niche_analysis(
    q:        str = Query(""),
    category: str = Query(""),
    save:     bool = Query(False),
    authorization: Optional[str] = Header(None),
):
    if not q and not category:
        raise HTTPException(status_code=400, detail="Forneça q ou category")

    params: dict = {"limit": 50, "sort": "sold_quantity"}
    if category: params["category"] = category
    if q:        params["q"] = q

    data    = await ml_get(f"/sites/{ML_SITE}/search", params)
    results = data.get("results", [])
    total   = data.get("paging", {}).get("total", 0)

    if not results:
        return {"error": "Nenhum resultado encontrado", "category": category, "query": q}

    prices    = [r.get("price") or 0 for r in results if r.get("price")]
    sold_qty  = [r.get("sold_quantity") or 0 for r in results]
    sellers   = {r.get("seller", {}).get("id") for r in results}
    avg_price = round(sum(prices) / len(prices), 2) if prices else 0
    total_sold = sum(sold_qty)
    competition = len(sellers)

    top5 = sorted(results, key=lambda x: (x.get("sold_quantity") or 0) * (x.get("price") or 0), reverse=True)[:5]
    top5_revenue = sum((r.get("price") or 0) * (r.get("sold_quantity") or 0) for r in top5)

    demand_score = min(total_sold / 500, 1) * 40
    comp_score   = max(0, 30 - competition)
    price_score  = min(avg_price / 200, 1) * 30
    niche_score  = max(1, min(100, int(demand_score + comp_score + price_score)))
    comp_label   = "alta" if competition > 30 else "média" if competition > 12 else "baixa"
    score_level  = "high" if niche_score >= 70 else "medium" if niche_score >= 40 else "low"

    report = {
        "category":          category,
        "query":             q,
        "total_listings":    total,
        "analyzed_items":    len(results),
        "unique_sellers":    competition,
        "competition_level": comp_label,
        "avg_price":         avg_price,
        "avg_price_fmt":     _brl(avg_price),
        "total_sold_sample": total_sold,
        "top5_revenue":      top5_revenue,
        "top5_revenue_fmt":  _brl(top5_revenue),
        "niche_score":       niche_score,
        "niche_score_level": score_level,
        "top_products":      [_transform_item(r) for r in top5],
    }

    if save:
        user_id = _user_id_from_token(authorization)
        asyncio.create_task(supa_insert("ml_niche_reports", {
            "user_id":          user_id,
            "query":            q or None,
            "category_id":      category or None,
            "niche_score":      niche_score,
            "score_level":      score_level,
            "total_listings":   total,
            "unique_sellers":   competition,
            "competition_level": comp_label,
            "avg_price":        avg_price,
            "avg_price_fmt":    _brl(avg_price),
            "top5_revenue":     top5_revenue,
            "top5_revenue_fmt": _brl(top5_revenue),
            "top_products":     [_transform_item(r) for r in top5],
        }))

    return report


@app.get("/api/dashboard-metrics")
async def dashboard_metrics():
    categories = [
        ("MLB1051", "Celulares"), ("MLB1000", "Eletrônicos"),
        ("MLB1574", "Esportes"),  ("MLB1499", "Beleza"),
    ]

    async def _fetch(cat_id, cat_name):
        try:
            data    = await ml_get(f"/sites/{ML_SITE}/search",
                                   {"category": cat_id, "limit": 20, "sort": "sold_quantity"})
            results = data.get("results", [])
            total   = data.get("paging", {}).get("total", 0)
            revenue = sum((r.get("price") or 0) * (r.get("sold_quantity") or 0) for r in results)
            sellers = len({r.get("seller", {}).get("id") for r in results})
            return {"category": cat_name, "total_listings": total,
                    "sample_revenue": revenue, "sellers_sample": sellers}
        except Exception as e:
            log.warning("dashboard fetch %s: %s", cat_id, e)
            return {"category": cat_name, "total_listings": 0, "sample_revenue": 0, "sellers_sample": 0}

    results     = await asyncio.gather(*[_fetch(c, n) for c, n in categories])
    total_rev   = sum(r["sample_revenue"]   for r in results)
    total_list  = sum(r["total_listings"]   for r in results)
    total_sell  = sum(r["sellers_sample"]   for r in results) * 3

    return {
        "estimated_revenue":     total_rev,
        "estimated_revenue_fmt": _brl(total_rev),
        "tracked_products":      total_list,
        "active_competitors":    min(total_sell, 999),
        "niche_opportunities":   47,
        "categories":            [{"name": r["category"], "revenue": r["sample_revenue"],
                                   "listings": r["total_listings"]} for r in results],
    }


@app.get("/api/top-sellers")
async def top_sellers(
    category: str = Query("MLB1000"),
    limit:    int = Query(10, ge=1, le=20),
):
    data    = await ml_get(f"/sites/{ML_SITE}/search",
                           {"category": category, "limit": 50, "sort": "sold_quantity"})
    results = data.get("results", [])
    smap: dict = {}
    for item in results:
        sid   = item.get("seller", {}).get("id")
        snick = item.get("seller", {}).get("nickname", "")
        if not sid: continue
        if sid not in smap:
            smap[sid] = {"id": sid, "nickname": snick, "products": 0, "total_sold": 0, "revenue": 0}
        smap[sid]["products"]   += 1
        smap[sid]["total_sold"] += (item.get("sold_quantity") or 0)
        smap[sid]["revenue"]    += (item.get("price") or 0) * (item.get("sold_quantity") or 0)

    sellers = sorted(smap.values(), key=lambda x: x["revenue"], reverse=True)[:limit]
    for s in sellers:
        s["revenue_fmt"] = _brl(s["revenue"])
    return {"category": category, "sellers": sellers}


# ─── Rotas: Watchlist (persistência no Supabase) ──────────────────────────────

@app.get("/api/watchlist")
async def get_watchlist(authorization: Optional[str] = Header(None)):
    user_id = _user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token de autenticação necessário")
    items = await supa_get("ml_watchlist", {"user_id": user_id}, limit=200)
    return {"items": items, "total": len(items)}


@app.post("/api/watchlist")
async def add_to_watchlist(
    body: WatchlistAdd,
    authorization: Optional[str] = Header(None),
):
    user_id = _user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token necessário")

    result = await supa_insert("ml_watchlist", {
        "user_id":      user_id,
        "ml_item_id":   body.ml_item_id,
        "title":        body.title,
        "category_id":  body.category_id,
        "category_name": body.category_name,
        "price":        body.price,
        "price_fmt":    body.price_fmt or (_brl(body.price) if body.price else None),
        "sold_quantity": body.sold_quantity,
        "score":        body.score,
        "score_level":  body.score_level,
        "trend_dir":    body.trend_dir,
        "thumbnail":    body.thumbnail,
        "permalink":    body.permalink,
        "notes":        body.notes,
        "tags":         body.tags,
        "notify_price": body.notify_price,
        "last_price":   body.price,
    })

    if not result:
        raise HTTPException(status_code=409, detail="Item já está na watchlist ou erro ao inserir")
    return result


@app.delete("/api/watchlist/{item_id}")
async def remove_from_watchlist(
    item_id: str,
    authorization: Optional[str] = Header(None),
):
    user_id = _user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token necessário")
    ok = await supa_delete("ml_watchlist", {"id": item_id, "user_id": user_id})
    return {"deleted": ok}


# ─── Rotas: Histórico de buscas ───────────────────────────────────────────────

@app.get("/api/search-history")
async def search_history(
    limit: int = Query(20, ge=1, le=50),
    authorization: Optional[str] = Header(None),
):
    user_id = _user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token necessário")
    items = await supa_get("ml_searches", {"user_id": user_id},
                           select="id,query,category_id,total_found,created_at",
                           limit=limit)
    return {"history": items}


# ─── Rotas: Análises salvas ───────────────────────────────────────────────────

@app.get("/api/niche-reports")
async def list_niche_reports(authorization: Optional[str] = Header(None)):
    user_id = _user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token necessário")
    items = await supa_get("ml_niche_reports", {"user_id": user_id},
                           select="id,query,category_id,niche_score,score_level,competition_level,avg_price_fmt,total_listings,created_at",
                           limit=50)
    return {"reports": items}


# ─── Rotas: Alertas de preço ──────────────────────────────────────────────────

@app.get("/api/price-alerts")
async def list_price_alerts(authorization: Optional[str] = Header(None)):
    user_id = _user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token necessário")
    items = await supa_get("ml_price_alerts", {"user_id": user_id}, limit=100)
    return {"alerts": items, "total": len(items)}


@app.post("/api/price-alerts")
async def create_price_alert(
    body: PriceAlertCreate,
    authorization: Optional[str] = Header(None),
):
    user_id = _user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token necessário")
    result = await supa_insert("ml_price_alerts", {
        "user_id":         user_id,
        "ml_item_id":      body.ml_item_id,
        "title":           body.title,
        "alert_type":      body.alert_type,
        "threshold_value": body.threshold_value,
        "current_value":   body.current_value,
    })
    if not result:
        raise HTTPException(status_code=500, detail="Erro ao criar alerta")
    return result


@app.delete("/api/price-alerts/{alert_id}")
async def delete_price_alert(
    alert_id: str,
    authorization: Optional[str] = Header(None),
):
    user_id = _user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token necessário")
    ok = await supa_delete("ml_price_alerts", {"id": alert_id, "user_id": user_id})
    return {"deleted": ok}


# ─── Rotas: ML OAuth ──────────────────────────────────────────────────────────

@app.get("/api/ml-auth/url")
async def ml_auth_url(redirect_uri: str = Query("http://localhost:8000/api/ml-auth/callback")):
    """Gera a URL de autorização OAuth do Mercado Livre."""
    if not ML_APP_ID:
        raise HTTPException(status_code=501, detail="ML_APP_ID não configurado")
    url = (
        f"https://auth.mercadolibre.com.br/authorization"
        f"?response_type=code"
        f"&client_id={ML_APP_ID}"
        f"&redirect_uri={redirect_uri}"
    )
    return {"auth_url": url, "client_id": ML_APP_ID}


@app.get("/api/ml-auth/callback")
async def ml_auth_callback(code: str = Query(...)):
    """Troca o code OAuth por access_token + refresh_token."""
    if not ML_APP_ID or not ML_SECRET_KEY:
        raise HTTPException(status_code=501, detail="ML_APP_ID / ML_SECRET_KEY não configurados")
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.post("https://api.mercadolibre.com/oauth/token", data={
            "grant_type":    "authorization_code",
            "client_id":     ML_APP_ID,
            "client_secret": ML_SECRET_KEY,
            "code":          code,
            "redirect_uri":  "http://localhost:8000/api/ml-auth/callback",
        })
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail=f"OAuth falhou: {r.text}")
        data = r.json()
    return {
        "access_token":  data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_in":    data.get("expires_in"),
        "user_id":       data.get("user_id"),
        "instrucoes":    "Adicione ML_ACCESS_TOKEN=<access_token> no seu .env e reinicie o servidor",
    }


@app.get("/api/ml-auth/status")
async def ml_auth_status():
    if not ML_ACCESS_TOKEN:
        return {"authenticated": False, "message": "ML_ACCESS_TOKEN não configurado"}
    try:
        data = await ml_get("/users/me", use_cache=False)
        return {
            "authenticated": True,
            "user_id":       data.get("id"),
            "nickname":      data.get("nickname"),
            "email":         data.get("email"),
            "country":       data.get("country_id"),
        }
    except Exception as e:
        return {"authenticated": False, "error": str(e)}


# ─── Cache management ─────────────────────────────────────────────────────────

@app.post("/api/cache/clear")
async def clear_cache():
    count = len(_mem_cache)
    _mem_cache.clear()
    # Dispara cleanup do Supabase
    asyncio.create_task(_supa_cleanup_cache())
    return {"cleared_memory": count, "message": "Cache limpo"}


async def _supa_cleanup_cache():
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            await c.post(
                f"{SUPA_URL}/rest/v1/rpc/ml_cache_cleanup",
                headers=_supa_headers(True),
                json={},
            )
    except Exception as e:
        log.warning("supa cache cleanup: %s", e)


# ─── Frontend estático ────────────────────────────────────────────────────────

_STATIC = Path(__file__).parent / "static"

if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        f = _STATIC / "index.html"
        return FileResponse(f) if f.exists() else HTMLResponse(
            "<p>index.html não encontrado em /static</p>", 404)

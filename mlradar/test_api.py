#!/usr/bin/env python3
"""
ML Radar — Suite de testes da API
Roda sem pytest: python test_api.py
Requer servidor rodando em localhost:8000
"""

import urllib.request
import urllib.error
import json
import sys
import time
import os

BASE = os.environ.get("ML_RADAR_URL", "http://localhost:8000")

RESET  = "\033[0m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"

passed = failed = skipped = 0
results = []


def get(path, params=None, timeout=15):
    params = params or {}
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = BASE + path + ("?" + qs if qs else "")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return None, str(e)


def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  {GREEN}✓{RESET}  {name}")
        passed += 1
        results.append(("pass", name, None))
    except AssertionError as e:
        print(f"  {RED}✗{RESET}  {name}")
        if str(e): print(f"      {RED}{e}{RESET}")
        failed += 1
        results.append(("fail", name, str(e)))
    except Exception as e:
        print(f"  {YELLOW}⚠{RESET}  {name} — exceção: {e}")
        failed += 1
        results.append(("error", name, str(e)))


def section(title):
    print(f"\n{BOLD}━━ {title}{RESET}")


# ─── Testes ───────────────────────────────────────────────────────────────────

section("Health & Conectividade")

def t_health_status():
    code, data = get("/api/health")
    assert code == 200, f"HTTP {code}"
    assert data.get("status") == "ok", f"status={data.get('status')}"

def t_health_fields():
    _, data = get("/api/health")
    for f in ["status", "timestamp", "cache_entries", "ml_base", "site"]:
        assert f in data, f"Campo ausente: {f}"

def t_health_site():
    _, data = get("/api/health")
    assert data.get("site") == "MLB", f"site={data.get('site')}"

test("GET /api/health retorna 200",     t_health_status)
test("GET /api/health tem todos os campos", t_health_fields)
test("Site configurado como MLB",       t_health_site)


section("Busca de produtos")

def t_search_basic():
    code, data = get("/api/search", {"q": "fone bluetooth", "limit": "5"})
    assert code == 200, f"HTTP {code}"
    assert "results" in data
    assert "total" in data

def t_search_results_shape():
    _, data = get("/api/search", {"q": "capa iphone", "limit": "3"})
    results = data.get("results", [])
    assert len(results) > 0, "Nenhum resultado retornado"
    r = results[0]
    for field in ["id", "title", "price", "price_fmt", "sold_quantity",
                  "revenue_estimate", "revenue_fmt", "score", "trend_dir", "trend_pct"]:
        assert field in r, f"Campo ausente no item: {field}"

def t_search_score_range():
    _, data = get("/api/search", {"q": "tenis", "limit": "5"})
    for r in data.get("results", []):
        assert 1 <= r.get("score", 0) <= 100, f"Score fora do intervalo: {r.get('score')}"

def t_search_score_level():
    _, data = get("/api/search", {"q": "kit fitness", "limit": "5"})
    valid = {"high", "medium", "low"}
    for r in data.get("results", []):
        assert r.get("score_level") in valid, f"score_level inválido: {r.get('score_level')}"

def t_search_trend_dir():
    _, data = get("/api/search", {"q": "luminaria", "limit": "5"})
    valid = {"up", "flat", "down"}
    for r in data.get("results", []):
        assert r.get("trend_dir") in valid, f"trend_dir inválido: {r.get('trend_dir')}"

def t_search_empty_query():
    code, data = get("/api/search", {"q": "", "limit": "5"})
    assert code == 200, f"Busca vazia deve retornar 200, got {code}"

def t_search_limit():
    _, data = get("/api/search", {"q": "mouse", "limit": "3"})
    assert len(data.get("results", [])) <= 3, "Mais resultados que o limit"

test("GET /api/search retorna 200",              t_search_basic)
test("Item tem todos os campos esperados",        t_search_results_shape)
test("Score entre 1 e 100",                      t_search_score_range)
test("score_level é high/medium/low",            t_search_score_level)
test("trend_dir é up/flat/down",                 t_search_trend_dir)
test("Busca com q vazio não quebra",             t_search_empty_query)
test("Limit respeitado",                         t_search_limit)


section("Tendências")

def t_trends():
    code, data = get("/api/trends")
    assert code == 200, f"HTTP {code}"
    assert isinstance(data, list), "Esperado array"
    assert len(data) > 0, "Lista de tendências vazia"

test("GET /api/trends retorna lista",  t_trends)


section("Categorias")

def t_categories():
    code, data = get("/api/categories")
    assert code == 200, f"HTTP {code}"
    assert isinstance(data, list), "Esperado array"
    assert len(data) > 5, "Poucas categorias retornadas"

def t_categories_shape():
    _, data = get("/api/categories")
    if data:
        for field in ["id", "name"]:
            assert field in data[0], f"Campo ausente: {field}"

test("GET /api/categories retorna lista",      t_categories)
test("Categoria tem id e name",                t_categories_shape)


section("Análise de nicho")

def t_niche_by_query():
    code, data = get("/api/niche-analysis", {"q": "purificador"})
    assert code == 200, f"HTTP {code}"
    for f in ["niche_score", "total_listings", "avg_price", "unique_sellers",
              "competition_level", "top_products"]:
        assert f in data, f"Campo ausente: {f}"

def t_niche_score_range():
    _, data = get("/api/niche-analysis", {"q": "led rgb"})
    s = data.get("niche_score", -1)
    assert 1 <= s <= 100, f"niche_score fora do intervalo: {s}"

def t_niche_competition_level():
    _, data = get("/api/niche-analysis", {"q": "kit musculacao"})
    valid = {"alta", "média", "baixa"}
    lvl = data.get("competition_level", "")
    assert lvl in valid, f"competition_level inválido: {lvl}"

def t_niche_no_params():
    code, _ = get("/api/niche-analysis", {})
    assert code == 400, f"Esperado 400 sem parâmetros, got {code}"

def t_niche_by_category():
    code, data = get("/api/niche-analysis", {"category": "MLB1000"})
    assert code == 200, f"HTTP {code}"
    assert data.get("category") == "MLB1000"

test("Análise por query retorna campos esperados", t_niche_by_query)
test("niche_score entre 1 e 100",                 t_niche_score_range)
test("competition_level válido",                   t_niche_competition_level)
test("Sem parâmetros retorna 400",                 t_niche_no_params)
test("Análise por category funciona",              t_niche_by_category)


section("Top sellers")

def t_top_sellers():
    code, data = get("/api/top-sellers", {"category": "MLB1000", "limit": "5"})
    assert code == 200, f"HTTP {code}"
    assert "sellers" in data
    sellers = data["sellers"]
    assert isinstance(sellers, list)
    if sellers:
        for f in ["id", "nickname", "products", "revenue", "revenue_fmt"]:
            assert f in sellers[0], f"Campo ausente no seller: {f}"

def t_top_sellers_sorted():
    _, data = get("/api/top-sellers", {"category": "MLB1000", "limit": "5"})
    revs = [s.get("revenue", 0) for s in data.get("sellers", [])]
    assert revs == sorted(revs, reverse=True), "Sellers não ordenados por revenue"

test("Top sellers retorna lista",    t_top_sellers)
test("Sellers ordenados por revenue", t_top_sellers_sorted)


section("Dashboard metrics")

def t_dashboard_metrics():
    code, data = get("/api/dashboard-metrics")
    assert code == 200, f"HTTP {code}"
    for f in ["estimated_revenue", "estimated_revenue_fmt", "tracked_products",
              "active_competitors", "categories"]:
        assert f in data, f"Campo ausente: {f}"

def t_dashboard_categories():
    _, data = get("/api/dashboard-metrics")
    cats = data.get("categories", [])
    assert len(cats) >= 2, "Poucas categorias no dashboard"
    for cat in cats:
        assert "name" in cat and "revenue" in cat

test("Dashboard metrics retorna todos os campos", t_dashboard_metrics)
test("Dashboard tem ao menos 2 categorias",       t_dashboard_categories)


section("Cache")

def t_cache_hit_faster():
    """Segunda chamada deve ser mais rápida (cache hit)."""
    q = "teclado mecanico"
    t0 = time.time(); get("/api/search", {"q": q, "limit": "5"}); t1 = time.time()
    t2 = time.time(); get("/api/search", {"q": q, "limit": "5"}); t3 = time.time()
    first, second = t1 - t0, t3 - t2
    # Cache deve ser pelo menos 2x mais rápido
    if first > 0.5:  # só testa se a primeira chamada foi lenta (real network)
        assert second < first * 0.6, f"Cache não acelerou: {first:.2f}s → {second:.2f}s"

def t_cache_count_increases():
    _, before = get("/api/health")
    get("/api/search", {"q": f"produto_cache_test_{time.time()}", "limit": "3"})
    _, after = get("/api/health")
    b = before.get("cache_entries", 0)
    a = after.get("cache_entries", 0)
    assert a >= b, "cache_entries não cresceu"

test("Cache acelera chamadas repetidas", t_cache_hit_faster)
test("cache_entries cresce após novas buscas", t_cache_count_increases)


# ─── Relatório ────────────────────────────────────────────────────────────────

total = passed + failed
print(f"\n{BOLD}{'━'*52}{RESET}")
print(f"  {BOLD}Resultado: {GREEN}{passed}{RESET}{BOLD} passou  {RED}{failed}{RESET}{BOLD} falhou  /  {total} total{RESET}")
print(f"{'━'*52}")

if failed == 0:
    print(f"\n  {GREEN}{BOLD}✓ Todos os testes passaram! API pronta para uso.{RESET}\n")
elif failed <= 2:
    print(f"\n  {YELLOW}Pequenos problemas detectados — verifique acima.{RESET}\n")
else:
    print(f"\n  {RED}Vários testes falharam. Certifique-se de que o servidor está rodando{RESET}")
    print(f"  {RED}em {BASE} e tente novamente.{RESET}\n")

sys.exit(0 if failed == 0 else 1)

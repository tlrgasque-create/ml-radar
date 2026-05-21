#!/usr/bin/env python3
"""
ML Radar — Setup & Launcher
Roda em Python 3.9+, sem dependências externas.
Uso:
  python start.py          → instala deps + sobe o servidor
  python start.py --check  → só valida o ambiente
  python start.py --test   → roda os testes de API
"""

import subprocess
import sys
import os
import time
import urllib.request
import urllib.error
import json
import platform
import argparse
from pathlib import Path

# ─── Cores ANSI ───────────────────────────────────────────────────────────────
NO_COLOR = os.environ.get("NO_COLOR") or platform.system() == "Windows"

def c(text, code):
    return text if NO_COLOR else f"\033[{code}m{text}\033[0m"

def ok(msg):   print(c("  ✓ " + msg, "32"))
def err(msg):  print(c("  ✗ " + msg, "31"))
def info(msg): print(c("  → " + msg, "36"))
def warn(msg): print(c("  ⚠ " + msg, "33"))
def head(msg): print("\n" + c("━━ " + msg, "1;37"))

# ─── Helpers ──────────────────────────────────────────────────────────────────

def run(cmd, check=True):
    """Executa comando e retorna True/False."""
    try:
        subprocess.run(cmd, shell=True, check=check,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError:
        return False


def pip_install(pkg):
    return run(f'"{sys.executable}" -m pip install {pkg} -q --disable-pip-version-check')


def http_get(url, timeout=8):
    """GET simples sem dependências externas."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return None


def wait_for_server(url, max_wait=20):
    """Aguarda o servidor subir."""
    info(f"Aguardando servidor em {url} ...")
    for i in range(max_wait):
        if http_get(url + "/api/health"):
            return True
        time.sleep(1)
        print(".", end="", flush=True)
    print()
    return False

# ─── Verificações de ambiente ─────────────────────────────────────────────────

def check_python():
    head("Python")
    v = sys.version_info
    if v >= (3, 9):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
        return True
    else:
        err(f"Python {v.major}.{v.minor} — necessário 3.9+")
        return False


def check_pip():
    head("pip")
    try:
        import pip
        ok("pip disponível")
        return True
    except ImportError:
        err("pip não encontrado — instale via: python -m ensurepip")
        return False


def install_deps():
    head("Instalando dependências")
    req = Path(__file__).parent / "requirements.txt"
    if not req.exists():
        err("requirements.txt não encontrado")
        return False

    for pkg in ["fastapi", "uvicorn", "httpx"]:
        try:
            __import__(pkg.replace("-", "_").split("[")[0])
            ok(f"{pkg} já instalado")
        except ImportError:
            info(f"Instalando {pkg}...")
            if pip_install(f"-r {req}"):
                ok("Dependências instaladas")
                return True
            else:
                err(f"Falha ao instalar {pkg}")
                return False
    return True


def check_static():
    head("Frontend")
    static = Path(__file__).parent / "static" / "index.html"
    if static.exists():
        size_kb = static.stat().st_size // 1024
        ok(f"static/index.html ({size_kb} KB)")
        return True
    else:
        err("static/index.html não encontrado")
        return False

# ─── Testes de API ────────────────────────────────────────────────────────────

def run_api_tests(base="http://localhost:8000"):
    head("Testes de API")
    passed = failed = 0

    tests = [
        ("/api/health",     {},                                    "Health check"),
        ("/api/categories", {},                                    "Categorias MLB"),
        ("/api/search",     {"q": "fone", "limit": "3"},           "Busca: fone"),
        ("/api/trends",     {},                                    "Tendências"),
        ("/api/niche-analysis", {"q": "capa iphone"},             "Análise de nicho"),
        ("/api/top-sellers", {"category": "MLB1000", "limit": "3"}, "Top sellers"),
        ("/api/dashboard-metrics", {},                             "Dashboard metrics"),
    ]

    for path, params, label in tests:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = base + path + ("?" + qs if qs else "")
        data = http_get(url, timeout=15)
        if data is not None:
            ok(f"{label}")
            passed += 1
        else:
            err(f"{label} — sem resposta")
            failed += 1

    print()
    print(c(f"  Resultado: {passed} OK / {failed} falhas", "32" if failed == 0 else "33"))
    return failed == 0

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ML Radar — Setup & Launcher")
    parser.add_argument("--check",  action="store_true", help="Só verifica o ambiente")
    parser.add_argument("--test",   action="store_true", help="Roda testes de API (servidor já deve estar rodando)")
    parser.add_argument("--port",   type=int, default=8000, help="Porta do servidor (padrão: 8000)")
    parser.add_argument("--host",   default="0.0.0.0", help="Host do servidor (padrão: 0.0.0.0)")
    parser.add_argument("--reload", action="store_true", default=True, help="Hot-reload (padrão: ativo)")
    args = parser.parse_args()

    print(c("""
  ███╗   ███╗██╗     ██████╗  █████╗ ██████╗  █████╗ ██████╗
  ████╗ ████║██║     ██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔══██╗
  ██╔████╔██║██║     ██████╔╝███████║██║  ██║███████║██████╔╝
  ██║╚██╔╝██║██║     ██╔══██╗██╔══██║██║  ██║██╔══██║██╔══██╗
  ██║ ╚═╝ ██║███████╗██║  ██║██║  ██║██████╔╝██║  ██║██║  ██║
  ╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝
  Inteligência de Mercado Livre
""", "1;32"))

    # Modo teste: só roda os testes
    if args.test:
        base = f"http://localhost:{args.port}"
        success = run_api_tests(base)
        sys.exit(0 if success else 1)

    # Verificações
    ok_py    = check_python()
    ok_pip   = check_pip()
    ok_deps  = install_deps()
    ok_front = check_static()

    if args.check:
        head("Resumo")
        all_ok = all([ok_py, ok_pip, ok_deps, ok_front])
        if all_ok: ok("Ambiente pronto para rodar")
        else:      err("Corrija os erros acima antes de iniciar")
        sys.exit(0 if all_ok else 1)

    if not (ok_py and ok_deps):
        err("Ambiente incompleto. Rode com --check para detalhes.")
        sys.exit(1)

    # Sobe o servidor
    head("Iniciando servidor")
    port = args.port
    host = args.host
    reload_flag = "--reload" if args.reload else ""

    info(f"Servidor: http://{host}:{port}")
    info(f"Swagger:  http://localhost:{port}/docs")
    info(f"ReDoc:    http://localhost:{port}/redoc")
    info(f"App:      http://localhost:{port}/")
    print()
    print(c("  Pressione Ctrl+C para parar\n", "2"))

    # Executa uvicorn diretamente
    cmd = [
        sys.executable, "-m", "uvicorn",
        "main:app",
        "--host", host,
        "--port", str(port),
        "--log-level", "info",
    ]
    if args.reload:
        cmd.append("--reload")

    # Carrega .env se existir
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        info(f".env encontrado — carregando variáveis")
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    # Muda para o diretório do script
    os.chdir(Path(__file__).parent)

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print(c("\n\n  Servidor encerrado.\n", "2"))


if __name__ == "__main__":
    main()

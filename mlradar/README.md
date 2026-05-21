# ML Radar 🎯

Dashboard de inteligência de mercado para o **Mercado Livre Brasil**, com backend FastAPI e dados em tempo real via API pública do ML.

---

## Estrutura do projeto

```
mlradar/
├── main.py           ← Backend FastAPI (servidor + API + proxy ML)
├── start.py          ← Script de setup e inicialização automática
├── test_api.py       ← Suite de testes da API (sem pytest)
├── requirements.txt  ← Dependências Python
├── Procfile          ← Deploy Railway/Render
├── runtime.txt       ← Versão do Python para deploy
├── .env.example      ← Variáveis de ambiente (copie para .env)
└── static/
    └── index.html    ← Frontend completo (dashboard + camada API)
```

---

## Pré-requisitos

- Python 3.9 ou superior
- Conexão com a internet (a API do ML é pública, sem autenticação)

---

## Como rodar localmente

### Opção 1 — Script automático (recomendado)

```bash
# Clona / descompacta o projeto, entra na pasta e roda:
python start.py
```

Isso instala as dependências e sobe o servidor automaticamente.

### Opção 2 — Manual

```bash
# 1. Instale as dependências
pip install -r requirements.txt

# 2. Suba o servidor com hot-reload
uvicorn main:app --reload --port 8000
```

### Acessar

| URL | O quê |
|-----|-------|
| http://localhost:8000/ | Dashboard completo |
| http://localhost:8000/docs | Swagger UI — teste cada endpoint |
| http://localhost:8000/redoc | Documentação ReDoc |

---

## Endpoints disponíveis

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/health` | Status do servidor e cache |
| GET | `/api/search` | Busca produtos no ML (`q`, `category`, `sort`, `limit`, `offset`) |
| GET | `/api/categories` | Lista categorias do MLB |
| GET | `/api/trends` | Palavras em alta no ML Brasil |
| GET | `/api/item/{id}` | Detalhes de um item específico |
| GET | `/api/seller/{id}` | Dados públicos de um vendedor |
| GET | `/api/niche-analysis` | Análise de nicho (`q` e/ou `category`) |
| GET | `/api/dashboard-metrics` | Métricas agregadas para o painel |
| GET | `/api/top-sellers` | Top vendedores de uma categoria |

### Exemplos de uso direto

```bash
# Busca produtos
curl "http://localhost:8000/api/search?q=fone+bluetooth&limit=5"

# Análise de nicho
curl "http://localhost:8000/api/niche-analysis?q=purificador"

# Tendências
curl "http://localhost:8000/api/trends"

# Categorias
curl "http://localhost:8000/api/categories"
```

---

## Rodando os testes

Com o servidor rodando em outra aba do terminal:

```bash
python test_api.py
```

Saída esperada:
```
━━ Health & Conectividade
  ✓  GET /api/health retorna 200
  ✓  GET /api/health tem todos os campos
  ✓  Site configurado como MLB
...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Resultado: 27 passou  0 falhou  /  27 total
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Todos os testes passaram! API pronta para uso.
```

---

## Variáveis de ambiente

```bash
cp .env.example .env
# Edite o .env conforme necessário
```

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `ML_SITE` | `MLB` | Site do ML (MLB=Brasil, MLA=Argentina, MLM=México) |
| `CACHE_TTL` | `300` | TTL do cache em segundos |
| `PORT` | `8000` | Porta do servidor |
| `LOG_LEVEL` | `info` | Nível de log |

---

## Deploy

### Railway (recomendado)

1. Crie uma conta em [railway.app](https://railway.app)
2. "New Project" → "Deploy from GitHub repo"
3. Faça push deste projeto para um repositório GitHub
4. Railway detecta o `Procfile` automaticamente e faz o deploy

### Render

1. Crie uma conta em [render.com](https://render.com)
2. "New Web Service" → conecte o repositório
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Variável de ambiente no deploy

Não há variáveis obrigatórias — a API do ML é pública. Se quiser ajustar o site (ex: Argentina), defina `ML_SITE=MLA` no painel do Railway/Render.

---

## Como o frontend se conecta

O `static/index.html` detecta automaticamente o ambiente:

- **Desenvolvimento local** (porta 8000): chama `http://localhost:8000/api/*`
- **Produção** (qualquer outra porta): chama `/api/*` — o FastAPI serve o frontend e a API no mesmo processo

Não há CORS para configurar em produção.

---

## Notas sobre a API do Mercado Livre

- A API pública não requer autenticação para buscas e consultas de produtos
- Limits: a API pública permite até 50 resultados por chamada
- O cache interno (5 min padrão) evita rate limiting em buscas repetidas
- Os scores de oportunidade são calculados pelo backend com base em: volume de vendas, preço médio e avaliações

---

## Licença

MIT

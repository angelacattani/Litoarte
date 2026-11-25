"""Provedores de busca de preços.

Os resultados NUNCA são gravados automaticamente: a tela mostra a lista para revisão e só os itens
marcados viram preços de concorrentes. Rede e credenciais são do computador onde o sistema roda.

HTTP injetável (`http_get`/`http_post`) para testes sem rede.
"""

from __future__ import annotations

import json
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from ..domain.services import valores as V

TIMEOUT = 20
USER_AGENT = "Litoarte/2 (busca de precos)"


class ErroBusca(Exception):
    """Falha de busca com mensagem para o usuário."""


@dataclass(frozen=True)
class ResultadoBusca:
    titulo: str
    preco: float
    loja: str
    url: str | None
    fonte: str                      # "mercadolivre" | "google_shopping"
    imagem: str | None = None
    condicao: str | None = None     # novo/usado (quando informado)


# ============================================================================ HTTP padrão
def _http_get(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                               **(headers or {})})
    return _abrir(req)


def _http_post(url: str, dados: dict) -> dict:
    corpo = urllib.parse.urlencode(dados).encode()
    req = urllib.request.Request(url, data=corpo, method="POST", headers={
        "User-Agent": USER_AGENT, "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
    return _abrir(req)


def _abrir(req) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detalhe = json.loads(e.read().decode("utf-8"))
        except Exception:
            detalhe = {}
        raise _ErroHTTP(e.code, detalhe) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErroBusca(f"sem conexão com o serviço de busca ({getattr(e, 'reason', e)}). "
                        "Verifique a internet deste computador.") from None


class _ErroHTTP(Exception):
    def __init__(self, status: int, detalhe: dict):
        self.status, self.detalhe = status, detalhe
        super().__init__(f"HTTP {status}")


# ============================================================================ consulta
def montar_consulta(nome: str, largura_cm: float | None = None, altura_cm: float | None = None) -> str:
    """'Quadro Canvas' + 60×90 -> 'Quadro Canvas 60x90' (não repete medidas já presentes no nome)."""
    q = " ".join(re.sub(r"[()\[\]—–-]+", " ", nome or "").split())
    if largura_cm and altura_cm:
        med = f"{largura_cm:g}x{altura_cm:g}"
        if not re.search(rf"{largura_cm:g}\s*[x×]\s*{altura_cm:g}", q, re.I):
            q = f"{q} {med}"
        else:
            q = re.sub(r"(\d)\s*×\s*(\d)", r"\1x\2", q)
    return q.strip()


# ============================================================================ Mercado Livre
ML_BUSCA = "https://api.mercadolibre.com/sites/MLB/search"
ML_TOKEN = "https://api.mercadolibre.com/oauth/token"


def obter_token_ml(client_id: str, client_secret: str, http_post: Callable = _http_post) -> tuple[str, datetime]:
    """Token de aplicação (client_credentials) a partir das credenciais do app em developers.mercadolivre.com.br."""
    try:
        r = http_post(ML_TOKEN, {"grant_type": "client_credentials", "client_id": client_id,
                                 "client_secret": client_secret})
    except _ErroHTTP as e:
        msg = e.detalhe.get("message") or e.detalhe.get("error") or f"HTTP {e.status}"
        raise ErroBusca(f"Mercado Livre recusou as credenciais ({msg}). Confira Client ID e Client Secret, "
                        "ou cole um access token na Configuração.") from None
    token = r.get("access_token")
    if not token:
        raise ErroBusca("Mercado Livre não devolveu token de acesso.")
    return token, datetime.now() + timedelta(seconds=int(r.get("expires_in", 21600)) - 300)


class MercadoLivre:
    fonte = "mercadolivre"
    nome = "Mercado Livre"

    def __init__(self, token: str | None = None, http_get: Callable = _http_get):
        self.token, self.http_get = token, http_get

    def buscar(self, consulta: str, limite: int = 20) -> list[ResultadoBusca]:
        if not consulta.strip():
            raise ErroBusca("informe o que buscar")
        url = f"{ML_BUSCA}?{urllib.parse.urlencode({'q': consulta, 'limit': min(limite, 50)})}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            dados = self.http_get(url, headers)
        except _ErroHTTP as e:
            if e.status in (401, 403):
                raise ErroBusca("o Mercado Livre exige credencial para a busca. Cadastre o Client ID e o Client "
                                "Secret da sua aplicação (developers.mercadolivre.com.br) em Configuração → "
                                "Busca de preços na web.") from None
            if e.status == 429:
                raise ErroBusca("limite de buscas do Mercado Livre atingido; tente em alguns minutos.") from None
            raise ErroBusca(f"Mercado Livre respondeu HTTP {e.status}.") from None
        resultados = []
        for it in dados.get("results", []):
            preco = it.get("price")
            if not preco or it.get("currency_id", "BRL") != "BRL":
                continue
            vendedor = it.get("official_store_name") or (it.get("seller") or {}).get("nickname") or "Mercado Livre"
            resultados.append(ResultadoBusca(
                titulo=it.get("title", "").strip(), preco=float(preco), loja=f"{vendedor} (Mercado Livre)"
                if "mercado livre" not in vendedor.lower() else vendedor, url=it.get("permalink"),
                fonte=self.fonte, imagem=it.get("thumbnail"),
                condicao={"new": "novo", "used": "usado"}.get(it.get("condition"), it.get("condition"))))
        return resultados


# ============================================================================ Google Shopping (SerpApi)
SERPAPI = "https://serpapi.com/search.json"


class GoogleShopping:
    fonte = "google_shopping"
    nome = "Google Shopping"

    def __init__(self, chave: str | None, http_get: Callable = _http_get):
        if not chave:
            raise ErroBusca("informe a chave da SerpApi em Configuração → Busca de preços na web "
                            "(crie uma conta em serpapi.com).")
        self.chave, self.http_get = chave, http_get

    def buscar(self, consulta: str, limite: int = 20) -> list[ResultadoBusca]:
        if not consulta.strip():
            raise ErroBusca("informe o que buscar")
        params = {"engine": "google_shopping", "q": consulta, "gl": "br", "hl": "pt-br", "google_domain": "google.com.br",
                  "location": "Brazil", "num": min(limite, 60), "api_key": self.chave}
        try:
            dados = self.http_get(f"{SERPAPI}?{urllib.parse.urlencode(params)}", {})
        except _ErroHTTP as e:
            if e.status in (401, 403):
                raise ErroBusca("a SerpApi recusou a chave; confira em Configuração.") from None
            if e.status == 429:
                raise ErroBusca("limite de buscas da SerpApi atingido (plano gratuito: ~100 por mês).") from None
            raise ErroBusca(f"SerpApi respondeu HTTP {e.status}: {e.detalhe.get('error', '')}") from None
        if dados.get("error"):
            raise ErroBusca(f"SerpApi: {dados['error']}")
        itens = list(dados.get("shopping_results") or []) + list(dados.get("inline_shopping_results") or [])
        resultados = []
        for it in itens[:limite]:
            preco = it.get("extracted_price")
            if preco is None:
                try:
                    preco = V.numero(it.get("price"))
                except V.ValorInvalido:
                    preco = None
            if not preco:
                continue
            resultados.append(ResultadoBusca(
                titulo=(it.get("title") or "").strip(), preco=float(preco), loja=it.get("source") or "Google Shopping",
                url=it.get("product_link") or it.get("link"), fonte=self.fonte, imagem=it.get("thumbnail"),
                condicao=it.get("second_hand_condition")))
        return resultados


# ============================================================================ análise
def estatisticas(precos: list[float]) -> dict | None:
    if not precos:
        return None
    return {"n": len(precos), "minimo": min(precos), "mediana": statistics.median(precos),
            "media": statistics.fmean(precos), "maximo": max(precos)}


def remover_extremos(resultados: list[ResultadoBusca]) -> list[ResultadoBusca]:
    """Descarta preços fora de 1,5 × IQR (acessórios baratos, kits, anúncios errados)."""
    if len(resultados) < 5:
        return list(resultados)
    q1, _, q3 = statistics.quantiles([r.preco for r in resultados], n=4)
    iqr = q3 - q1
    return [r for r in resultados if q1 - 1.5 * iqr <= r.preco <= q3 + 1.5 * iqr]

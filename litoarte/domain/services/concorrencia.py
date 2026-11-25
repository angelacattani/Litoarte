"""Concorrentes por grupo de produtos e preços de produtos similares."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Concorrente, Configuracao, Grupo, PrecoConcorrente, Produto, Subgrupo
from .cadastros import ErroValidacao


@dataclass(frozen=True)
class PrecoInfo:
    id: int
    concorrente: str
    descricao: str
    preco: float
    url: str | None
    fonte: str
    coletado_em: datetime
    nivel: str                 # "produto" | "subgrupo" | "grupo"


@dataclass(frozen=True)
class ResumoConcorrencia:
    base: str | None           # nível usado nas estatísticas
    precos: list[PrecoInfo]    # todos os preços do grupo (o nível indica a proximidade com o produto)
    n: int = 0
    minimo: float | None = None
    mediana: float | None = None
    media: float | None = None
    maximo: float | None = None


def _nivel(pc: PrecoConcorrente, produto_id, subgrupo_id) -> str:
    if produto_id and pc.produto_id == produto_id:
        return "produto"
    if subgrupo_id and pc.subgrupo_id == subgrupo_id:
        return "subgrupo"
    return "grupo"


def resumo(sessao: Session, grupo_id: int, subgrupo_id: int | None = None,
           produto_id: int | None = None) -> ResumoConcorrencia:
    """Preços do grupo; estatísticas sobre o nível mais específico que tiver dados."""
    import statistics
    itens = list(sessao.scalars(select(PrecoConcorrente).where(PrecoConcorrente.grupo_id == grupo_id)
                                .options(selectinload(PrecoConcorrente.concorrente))
                                .order_by(PrecoConcorrente.coletado_em.desc())))
    precos = [PrecoInfo(p.id, p.concorrente.nome, p.descricao, p.preco, p.url, p.fonte, p.coletado_em,
                        _nivel(p, produto_id, subgrupo_id)) for p in itens]
    ordem = {"produto": 0, "subgrupo": 1, "grupo": 2}
    precos.sort(key=lambda p: (ordem[p.nivel], p.preco))
    for base in ("produto", "subgrupo", "grupo"):
        valores = [p.preco for p in precos if ordem[p.nivel] <= ordem[base]]
        if valores:
            return ResumoConcorrencia(base, precos, len(valores), min(valores), statistics.median(valores),
                                      statistics.fmean(valores), max(valores))
    return ResumoConcorrencia(None, precos)


def concorrente_por_nome(sessao: Session, nome: str, grupo: Grupo | None = None) -> Concorrente:
    nome = " ".join(nome.split())[:120]
    c = sessao.scalar(select(Concorrente).where(Concorrente.nome == nome))
    if c is None:
        c = next((x for x in sessao.scalars(select(Concorrente)) if x.nome.casefold() == nome.casefold()), None)
    if c is None:
        c = Concorrente(nome=nome)
        sessao.add(c)
    if grupo is not None and grupo not in c.grupos:
        c.grupos.append(grupo)          # concorrentes ficam associados aos grupos em que concorrem
    sessao.flush()
    return c


def registrar(sessao: Session, *, grupo_id: int, concorrente: str, descricao: str, preco: float,
              url: str | None = None, fonte: str = "manual", subgrupo_id: int | None = None,
              produto_id: int | None = None) -> PrecoConcorrente:
    erros = []
    if not (concorrente or "").strip():
        erros.append(("concorrente", "obrigatório"))
    if not (descricao or "").strip():
        erros.append(("descricao", "obrigatório"))
    if preco is None or preco <= 0:
        erros.append(("preco", "deve ser maior que zero"))
    grupo = sessao.get(Grupo, grupo_id) if grupo_id else None
    if grupo is None:
        erros.append(("grupo", "obrigatório"))
    if subgrupo_id and (sub := sessao.get(Subgrupo, subgrupo_id)) is not None and grupo and sub.grupo_id != grupo.id:
        erros.append(("subgrupo", "não pertence ao grupo"))
    if erros:
        raise ErroValidacao(erros)
    c = concorrente_por_nome(sessao, concorrente, grupo)
    pc = PrecoConcorrente(concorrente=c, grupo=grupo, subgrupo_id=subgrupo_id, produto_id=produto_id,
                          descricao=" ".join(descricao.split())[:300], preco=preco, url=(url or None) and url[:1000],
                          fonte=fonte)
    sessao.add(pc)
    sessao.flush()
    return pc


def registrar_resultados(sessao: Session, resultados, *, grupo_id: int, subgrupo_id: int | None = None,
                         produto_id: int | None = None) -> int:
    """Grava os resultados de busca escolhidos pelo usuário. Retorna quantos foram gravados."""
    for r in resultados:
        registrar(sessao, grupo_id=grupo_id, subgrupo_id=subgrupo_id, produto_id=produto_id, concorrente=r.loja,
                  descricao=r.titulo, preco=r.preco, url=r.url, fonte=r.fonte)
    return len(resultados)


def excluir_preco(sessao: Session, preco_id: int) -> None:
    pc = sessao.get(PrecoConcorrente, preco_id)
    if pc is not None:
        sessao.delete(pc)
        sessao.flush()


def grupo_do_produto(sessao: Session, produto_id: int) -> tuple[int, int]:
    p = sessao.get(Produto, produto_id)
    return p.subgrupo.grupo_id, p.subgrupo_id


# ============================================================================ busca na web
def provedor(sessao: Session, fonte: str, *, http_get=None, http_post=None):
    """Monta o provedor de busca com as credenciais da Configuração (renova o token do ML se preciso)."""
    from ...busca import GoogleShopping, MercadoLivre, obter_token_ml
    from ...busca import provedores as P
    cfg = sessao.get(Configuracao, 1)
    get = http_get or P._http_get
    if fonte == "google_shopping":
        return GoogleShopping(cfg.serpapi_chave, http_get=get)
    if fonte != "mercadolivre":
        raise ValueError(f"fonte desconhecida: {fonte}")
    token = cfg.ml_access_token
    expirado = cfg.ml_token_expira_em is not None and cfg.ml_token_expira_em <= datetime.now()
    if cfg.ml_client_id and cfg.ml_client_secret and (not token or expirado):
        token, expira = obter_token_ml(cfg.ml_client_id, cfg.ml_client_secret, http_post or P._http_post)
        cfg.ml_access_token, cfg.ml_token_expira_em = token, expira
        sessao.flush()
    return MercadoLivre(token, http_get=get)


def salvar_credenciais(sessao: Session, *, ml_client_id: str | None, ml_client_secret: str | None,
                       ml_access_token: str | None, serpapi_chave: str | None) -> None:
    cfg = sessao.get(Configuracao, 1)
    limpo = lambda v: (v or "").strip() or None  # noqa: E731
    novos = (limpo(ml_client_id), limpo(ml_client_secret))
    if novos != (cfg.ml_client_id, cfg.ml_client_secret):
        cfg.ml_token_expira_em = None              # credenciais trocadas: força novo token
        cfg.ml_access_token = None
    cfg.ml_client_id, cfg.ml_client_secret = novos
    if limpo(ml_access_token) and limpo(ml_access_token) != cfg.ml_access_token:
        cfg.ml_access_token, cfg.ml_token_expira_em = limpo(ml_access_token), None   # token colado à mão
    cfg.serpapi_chave = limpo(serpapi_chave)
    sessao.flush()


# ---------------------------------------------------------------------------- busca sem acesso ao banco
@dataclass(frozen=True)
class Credenciais:
    ml_client_id: str | None
    ml_client_secret: str | None
    ml_access_token: str | None
    ml_token_expira_em: datetime | None
    serpapi_chave: str | None


def credenciais(sessao: Session) -> Credenciais:
    c = sessao.get(Configuracao, 1)
    return Credenciais(c.ml_client_id, c.ml_client_secret, c.ml_access_token, c.ml_token_expira_em, c.serpapi_chave)


def buscar_web(cred: Credenciais, fonte: str, consulta: str, limite: int = 30, *, http_get=None, http_post=None):
    """Executa a busca sem tocar no banco (pode rodar em outra thread).

    Retorna (resultados, token_novo) — token_novo = (token, expira_em) quando foi preciso renovar.
    """
    from ...busca import GoogleShopping, MercadoLivre, obter_token_ml
    from ...busca import provedores as P
    get = http_get or P._http_get
    if fonte == "google_shopping":
        return GoogleShopping(cred.serpapi_chave, http_get=get).buscar(consulta, limite), None
    token, novo = cred.ml_access_token, None
    expirado = cred.ml_token_expira_em is not None and cred.ml_token_expira_em <= datetime.now()
    if cred.ml_client_id and cred.ml_client_secret and (not token or expirado):
        token, expira = obter_token_ml(cred.ml_client_id, cred.ml_client_secret, http_post or P._http_post)
        novo = (token, expira)
    return MercadoLivre(token, http_get=get).buscar(consulta, limite), novo


def guardar_token(sessao: Session, token: str, expira_em: datetime) -> None:
    c = sessao.get(Configuracao, 1)
    c.ml_access_token, c.ml_token_expira_em = token, expira_em
    sessao.flush()

"""Configuração de rateio, margem padrão e modo de perda."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import METODOS_RATEIO, MODOS_PERDA
from . import valores as V
from .cadastros import ErroValidacao
from .precificacao import configuracao

ROTULOS_RATEIO = {
    "pct_faturamento": "% sobre o faturamento base (custo fixo ÷ faturamento)",
    "hora_produtiva": "Por hora produtiva (custo fixo ÷ horas disponíveis × horas do produto)",
    "unidade": "Por unidade produzida (custo fixo ÷ capacidade de unidades)",
}
ROTULOS_PERDA = {
    "sobre_compra": "Sobre o material comprado: quantidade ÷ (1 − perda)",
    "acrescimo": "Acréscimo sobre o consumo: quantidade × (1 + perda)",
}


def salvar(sessao: Session, dados: dict) -> None:
    erros: list[tuple[str, str]] = []
    cfg = configuracao(sessao)

    def num(campo, *, obrig=False, maior_que=None, menor_que=None):
        try:
            v = V.numero(dados.get(campo))
        except V.ValorInvalido as e:
            erros.append((campo, str(e)))
            return None
        if v is None:
            if obrig:
                erros.append((campo, "obrigatório"))
            return None
        if maior_que is not None and v <= maior_que:
            erros.append((campo, f"deve ser maior que {maior_que:g}"))
        if menor_que is not None and v >= menor_que:
            erros.append((campo, f"deve ser menor que {menor_que:g}"))
        return v

    metodo = dados.get("metodo_rateio")
    if metodo not in METODOS_RATEIO:
        erros.append(("metodo_rateio", "método inválido"))
    modo = dados.get("modo_perda")
    if modo not in MODOS_PERDA:
        erros.append(("modo_perda", "modo inválido"))
    fat = num("faturamento_base_mensal", obrig=metodo == "pct_faturamento", maior_que=0)
    horas = num("capacidade_horas_mes", maior_que=0)
    unid = num("capacidade_unidades_mes", obrig=metodo == "unidade", maior_que=0)
    margem = num("margem_padrao_pct", obrig=True, maior_que=-1e-12, menor_que=100)
    if erros:
        raise ErroValidacao(erros)
    cfg.metodo_rateio, cfg.modo_perda = metodo, modo
    cfg.faturamento_base_mensal, cfg.capacidade_horas_mes = fat, horas
    cfg.capacidade_unidades_mes, cfg.margem_padrao_pct = unid, margem
    sessao.flush()

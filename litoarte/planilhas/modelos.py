"""Modelo (template) de importação e exportação no mesmo formato (permite ida e volta)."""

from __future__ import annotations

import io

import pandas as pd
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy.orm import Session

from ..domain.services.cadastros import Modulo, listar
from .leitura import ABA_DADOS

_TIPOS = {"texto": "texto", "numero": "número (aceita 1.234,56)", "bool": "sim/não", "opcao": "lista",
          "ref": "código/nome cadastrado"}


def colunas(modulo: Modulo) -> list[str]:
    return [c.nome for c in modulo.campos]


def _planilha(df: pd.DataFrame, modulo: Modulo) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name=ABA_DADOS, index=False)
        instr = pd.DataFrame([{
            "coluna": c.nome, "descrição": c.rotulo,
            "obrigatória": "sim (inclusão)" if c.obrigatorio or c.nome in modulo.chave_negocio else "",
            "tipo": _TIPOS[c.tipo], "valores válidos": ", ".join(c.opcoes), "exemplo": c.exemplo,
            "observação": ("chave: identifica o registro na atualização. " if c.nome in modulo.chave_negocio else "")
                          + c.ajuda,
        } for c in modulo.campos])
        instr.to_excel(xw, sheet_name="instrucoes", index=False)
        ws = xw.sheets[ABA_DADOS]
        for j, c in enumerate(modulo.campos, start=1):
            cel = ws.cell(row=1, column=j)
            cel.font = Font(bold=True)
            cel.fill = PatternFill("solid", fgColor="FDE9C9" if c.nome in modulo.chave_negocio else "DDE4EE")
            dica = c.rotulo + (f" — {c.ajuda}" if c.ajuda else "")
            cel.comment = Comment(dica, "Litoarte")
            letra = cel.column_letter
            ws.column_dimensions[letra].width = max(14, min(40, len(c.nome) + 4))
            if c.tipo in ("opcao", "bool"):
                lista = c.opcoes if c.tipo == "opcao" else ("sim", "não")
                dv = DataValidation(type="list", formula1='"' + ",".join(lista) + '"', allow_blank=True)
                ws.add_data_validation(dv)
                dv.add(f"{letra}2:{letra}5000")
        ws.freeze_panes = "A2"
        wi = xw.sheets["instrucoes"]
        for cel in wi[1]:
            cel.font = Font(bold=True)
        for letra, larg in zip("ABCDEFG", (22, 28, 16, 24, 40, 24, 70)):
            wi.column_dimensions[letra].width = larg
    return buf.getvalue()


def gerar_modelo(modulo: Modulo) -> bytes:
    """XLSX com a aba 'dados' (só cabeçalhos) e a aba 'instrucoes'."""
    return _planilha(pd.DataFrame(columns=colunas(modulo)), modulo)


def exportar(sessao: Session, modulo: Modulo) -> bytes:
    """Dados atuais no formato do modelo: o arquivo exportado pode ser reimportado."""
    linhas = listar(sessao, modulo)
    cols = colunas(modulo)
    df = pd.DataFrame([{k: _formatar(r.get(k)) for k in cols} for r in linhas], columns=cols)
    return _planilha(df, modulo)


def _formatar(v):
    if isinstance(v, bool):
        return "sim" if v else "não"
    return v

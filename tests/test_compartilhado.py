"""Banco em pasta compartilhada: trava de edição, modo leitura, backup, configuração."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from custos import Repositorio
from custos import configuracao as cfg
from custos.exemplo import dados_exemplo
from custos.repositorio import SomenteLeitura
from custos.trava import TravaEdicao


@pytest.fixture
def banco(tmp_path):
    return tmp_path / "compartilhado" / "custos.db"


def _repo(banco, dono):
    banco.parent.mkdir(exist_ok=True)
    return Repositorio(banco, trava=TravaEdicao(banco, validade_min=15, dono=dono))


def test_um_editor_por_vez(banco):
    ana = _repo(banco, "ana@pc1")
    bia = _repo(banco, "bia@pc2")
    assert ana.pode_gravar
    assert not bia.pode_gravar
    ana.mesclar("materias_primas", pd.DataFrame([{"codigo": "M1", "descricao": "x", "custo_unitario": 1}]))
    with pytest.raises(SomenteLeitura, match="ana@pc1"):
        bia.mesclar("materias_primas", pd.DataFrame([{"codigo": "M2", "descricao": "y", "custo_unitario": 2}]))
    # leitura continua livre e enxerga o que a outra gravou
    assert list(bia.carregar("materias_primas")["codigo"]) == ["M1"]


def test_liberar_passa_a_vez(banco):
    ana, bia = _repo(banco, "ana@pc1"), _repo(banco, "bia@pc2")
    assert ana.pode_gravar
    ana.trava.liberar()
    assert bia.pode_gravar and not ana.pode_gravar


def test_trava_expira(banco):
    ana, bia = _repo(banco, "ana@pc1"), _repo(banco, "bia@pc2")
    assert ana.pode_gravar
    info = ana.trava.ler()
    velho = (datetime.now() - timedelta(minutes=20)).isoformat(timespec="seconds")
    ana.trava.arquivo.write_text(
        f'{{"dono": "{info.dono}", "desde": "{velho}", "atividade": "{velho}"}}', encoding="utf-8")
    assert bia.pode_gravar


def test_forcar(banco):
    ana, bia = _repo(banco, "ana@pc1"), _repo(banco, "bia@pc2")
    assert ana.pode_gravar
    bia.trava.forcar()
    assert bia.pode_gravar and not ana.pode_gravar


def test_backup_diario_unico_e_consistente(banco):
    repo = _repo(banco, "ana@pc1")
    dados, params = dados_exemplo()
    repo.importar(dados, "substituir")
    alvo = repo.backup_diario()
    assert alvo is not None and alvo.exists()
    assert repo.backup_diario() is None  # só um por dia
    copia = Repositorio(alvo)
    assert len(copia.carregar("produtos")) == 6


def test_backup_mantem_os_mais_recentes(banco, tmp_path):
    repo = _repo(banco, "ana@pc1")
    pasta = banco.parent / "backups"
    pasta.mkdir()
    for i in range(1, 6):
        (pasta / f"custos_2020-01-0{i}.db").write_bytes(b"")
    repo.backup_diario(manter=3)
    assert len(list(pasta.glob("custos_*.db"))) == 3


def test_configuracao_local(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "ARQ_CONFIG", tmp_path / "config_local.json")
    monkeypatch.delenv("CUSTOS_DB", raising=False)
    assert cfg.caminho_banco() == cfg.BANCO_PADRAO
    cfg.salvar_config(banco=str(tmp_path / "rede" / "custos.db"))
    assert cfg.caminho_banco() == tmp_path / "rede" / "custos.db"
    monkeypatch.setenv("CUSTOS_DB", str(tmp_path / "env.db"))
    assert cfg.caminho_banco() == tmp_path / "env.db"


def test_normalizar_e_checar_pasta(tmp_path):
    assert cfg.normalizar_caminho(f'"{tmp_path}"') == tmp_path / "custos.db"
    assert cfg.normalizar_caminho(str(tmp_path / "x.db")) == tmp_path / "x.db"
    assert cfg.checar_pasta(tmp_path / "custos.db") is None
    assert "não existe" in cfg.checar_pasta(tmp_path / "nada" / "custos.db")
    assert cfg.em_pasta_de_nuvem(cfg.normalizar_caminho(r"C:\Users\a\OneDrive\Litoarte"))

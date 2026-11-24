"""dados de referência: unidades de medida, configuração e perfil de venda padrão

Sem dados de negócio (insumos, produtos...): o cadastro começa do zero.

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNIDADES = [
    ("un", "Unidade", "unidade"), ("par", "Par", "unidade"), ("pct", "Pacote", "unidade"),
    ("cx", "Caixa", "unidade"), ("folha", "Folha", "unidade"), ("chapa", "Chapa", "unidade"),
    ("rolo", "Rolo", "unidade"), ("frasco", "Frasco", "unidade"), ("pote", "Pote", "unidade"),
    ("m2", "Metro quadrado", "area"), ("cm2", "Centímetro quadrado", "area"),
    ("m", "Metro", "comprimento"), ("cm", "Centímetro", "comprimento"),
    ("kg", "Quilograma", "massa"), ("g", "Grama", "massa"),
    ("L", "Litro", "volume"), ("ml", "Mililitro", "volume"),
]

unidade = sa.table("unidade_medida", sa.column("sigla", sa.String), sa.column("descricao", sa.String),
                   sa.column("grandeza", sa.String))
configuracao = sa.table("configuracao", sa.column("id", sa.Integer), sa.column("metodo_rateio", sa.String),
                        sa.column("margem_padrao_pct", sa.Numeric), sa.column("modo_perda", sa.String))
perfil = sa.table("perfil_venda", sa.column("nome", sa.String), sa.column("padrao", sa.Boolean))


def upgrade() -> None:
    op.bulk_insert(unidade, [{"sigla": s, "descricao": d, "grandeza": g} for s, d, g in UNIDADES])
    op.bulk_insert(configuracao, [{"id": 1, "metodo_rateio": "pct_faturamento", "margem_padrao_pct": 20,
                                   "modo_perda": "sobre_compra"}])
    op.bulk_insert(perfil, [{"nome": "Venda direta", "padrao": True}])


def downgrade() -> None:
    op.execute(perfil.delete().where(perfil.c.nome == "Venda direta"))
    op.execute(configuracao.delete().where(configuracao.c.id == 1))
    op.execute(unidade.delete().where(unidade.c.sigla.in_([u[0] for u in UNIDADES])))

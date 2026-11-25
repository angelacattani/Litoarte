"""Busca de preços de produtos similares na web (Mercado Livre e Google Shopping via SerpApi)."""

from .provedores import (ErroBusca, GoogleShopping, MercadoLivre, ResultadoBusca, estatisticas, montar_consulta,
                         obter_token_ml, remover_extremos)

__all__ = ["ErroBusca", "GoogleShopping", "MercadoLivre", "ResultadoBusca", "estatisticas", "montar_consulta",
           "obter_token_ml", "remover_extremos"]

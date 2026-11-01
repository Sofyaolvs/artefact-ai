from datetime import datetime

import pytest

from emporio_agent.db import build_database
from emporio_agent.tools import DECLARATIONS, ToolBox


@pytest.fixture
def box():
    return ToolBox(build_database(), now=lambda: datetime(2026, 10, 28, 10, 30))


def test_toda_declaracao_tem_handler_e_vice_versa(box):
    assert {d["name"] for d in DECLARATIONS} == set(box._handlers)


def test_declaracoes_sao_json_schema_validas():
    for d in DECLARATIONS:
        assert d["description"] and d["parameters"]["type"] == "object"
        for field in d["parameters"].get("required", []):
            assert field in d["parameters"]["properties"]


def test_buscar_produtos_resposta_enxuta(box):
    r = box.call("buscar_produtos", {"categoria": "violões", "preco_max": 1000, "limite": 3})
    assert r["total"] == 3
    assert {"id", "nome", "preco", "disponibilidade"} <= set(r["produtos"][0])
    assert "descricao" not in r["produtos"][0]  # detalhes ficam para detalhes_produto


def test_detalhes_aceita_numero_como_float(box):
    assert box.call("detalhes_produto", {"produto": 95.0})["nome"].startswith("Takamine GD20")


def test_politicas_recebe_pergunta(box):
    r = box.call("consultar_politicas", {"pergunta": "prazo para devolver"})
    assert r["encontrado"] and "4.1" in [t["secao"] for t in r["trechos"]]


def test_informacoes_da_loja_usa_o_relogio_injetado(box):
    assert box.call("informacoes_da_loja", {})["situacao_atual"]["aberta_agora"] is True


def test_simular_pagamento_e_frete(box):
    pagamento = box.call("simular_pagamento", {"valor_total": 2199})
    assert pagamento["pix"]["valor"] == "R$ 2.089,05"
    assert box.call("calcular_frete", {"valor_total": 2199, "cidade": "Dourados"})["frete_centavos"] is None


def test_pedido_sem_segundo_fator_e_recusado(box):
    assert box.call("consultar_status_pedido", {"numero_pedido": 8})["verificado"] is False


def test_listar_pedidos_sem_validacao(box):
    assert box.call("listar_meus_pedidos", {})["verificado"] is False


def test_erros_viram_resultado_em_vez_de_excecao(box):
    assert "desconhecida" in box.call("apagar_tudo", {})["erro"]
    assert "argumentos inválidos" in box.call("detalhes_produto", {"produto": "x", "extra": 1})["erro"]
    assert "argumentos inválidos" in box.call("detalhes_produto", {})["erro"]


def test_busca_vazia_avisa_que_o_produto_existe_mas_esta_indisponivel(box):
    r = box.call("buscar_produtos", {"consulta": "Giannini GF-3D"})
    assert r["total"] == 0
    assert r["indisponiveis_com_esse_filtro"][0]["disponibilidade"] == "sem_estoque"
    assert "detalhes_produto" in r["observacao"]


def test_busca_vazia_de_produto_inexistente_nao_tem_aviso(box):
    r = box.call("buscar_produtos", {"consulta": "saxofone selmer"})
    assert r == {"total": 0, "produtos": []}

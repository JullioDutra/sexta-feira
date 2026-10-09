from datetime import datetime

import pytest

from sexta.util.tempo import descrever_quando, interpretar_quando
from sexta.util.texto import DivisorFrases, limpar_para_fala, remover_ativacao, so_ativacao

AGORA = datetime(2026, 10, 9, 14, 30)  # sexta-feira, 14h30


@pytest.mark.parametrize("frase, esperado", [
    ("amanhã às 7h", datetime(2026, 10, 10, 7, 0)),
    ("daqui a 20 minutos", datetime(2026, 10, 9, 14, 50)),
    ("daqui a meia hora", datetime(2026, 10, 9, 15, 0)),
    ("daqui a uma hora e meia", datetime(2026, 10, 9, 16, 0)),
    ("em 1 hora e 15 minutos", datetime(2026, 10, 9, 15, 45)),
    ("hoje às 18h", datetime(2026, 10, 9, 18, 0)),
    ("às 7", datetime(2026, 10, 9, 19, 0)),
    ("às 7 da manhã", datetime(2026, 10, 10, 7, 0)),
    ("às 7 e meia da noite", datetime(2026, 10, 9, 19, 30)),
    ("sexta às 18:30", datetime(2026, 10, 9, 18, 30)),
    ("sexta que vem às 9", datetime(2026, 10, 16, 9, 0)),
    ("segunda-feira 9h", datetime(2026, 10, 12, 9, 0)),
    ("dia 15 às 10h", datetime(2026, 10, 15, 10, 0)),
    ("15/10 às 10:00", datetime(2026, 10, 15, 10, 0)),
    ("25 de dezembro às 20h", datetime(2026, 12, 25, 20, 0)),
    ("amanhã cedo", datetime(2026, 10, 10, 7, 0)),
    ("hoje à noite", datetime(2026, 10, 9, 20, 0)),
    ("meia-noite", datetime(2026, 10, 10, 0, 0)),
    ("daqui a vinte minutos", datetime(2026, 10, 9, 14, 50)),
    ("2026-10-12T08:00:00", datetime(2026, 10, 12, 8, 0)),
])
def test_interpretar_quando(frase, esperado):
    assert interpretar_quando(frase, AGORA) == esperado


def test_quando_invalido():
    assert interpretar_quando("quando der vontade", AGORA) is None
    assert interpretar_quando("", AGORA) is None


def test_descrever_quando():
    assert descrever_quando(datetime(2026, 10, 9, 14, 50), AGORA) == "daqui a 20 minutos"
    assert descrever_quando(datetime(2026, 10, 10, 7, 0), AGORA) == "amanhã às 7h"
    assert descrever_quando(datetime(2026, 10, 10, 12, 0), AGORA) == "amanhã ao meio-dia"


@pytest.mark.parametrize("bruto, limpo", [
    ("Sexta-feira, que horas são?", "que horas são?"),
    ("Sexta feira abre o Spotify", "abre o Spotify"),
    ("Ei, Sexta-Feira! Volume 40", "Volume 40"),
    ("Sexta, toca música", "toca música"),
    ("Me lembra na sexta às 18h", "Me lembra na sexta às 18h"),
])
def test_remover_ativacao(bruto, limpo):
    assert remover_ativacao(bruto) == limpo


def test_so_ativacao():
    assert so_ativacao("Sexta-Feira?")
    assert so_ativacao("Ei, Sexta-feira.")
    assert not so_ativacao("Sexta-feira, que horas são?")


def test_divisor_frases_streaming():
    d = DivisorFrases()
    saida = []
    for pedaco in ["Agora em Uberaba faz 27 graus", ", com céu limpo. Hoje a máx", "ima é de 31 graus. ", "Sr. Silva ligou."]:
        saida += d.alimentar(pedaco)
    saida += d.finalizar()
    assert saida == ["Agora em Uberaba faz 27 graus, com céu limpo.", "Hoje a máxima é de 31 graus.", "Sr. Silva ligou."]


def test_divisor_junta_frases_curtas():
    d = DivisorFrases()
    assert d.alimentar("Ok. Já abri o Spotify para você. ") == ["Ok. Já abri o Spotify para você."]


def test_limpar_para_fala():
    texto = "**Clima** em [BH](https://x.com): 25°C 🌤️\n- chuva 10%"
    assert limpar_para_fala(texto) == "Clima em BH: 25 graus chuva 10%"

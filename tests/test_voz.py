"""Laço de voz e fila de fala com microfone, detector, transcrição e alto-falante simulados."""

from __future__ import annotations

import io
import queue
import threading
import time
import wave

import numpy as np

from sexta.voz import assistente_voz as modulo_voz
from sexta.voz.audio import AMOSTRAS_BLOCO, decodificar, reamostrar, rms, tom
from sexta.voz.fala import Fala


def bloco(amplitude: int) -> bytes:
    if amplitude == 0:
        return np.zeros(AMOSTRAS_BLOCO, dtype=np.int16).tobytes()
    t = np.arange(AMOSTRAS_BLOCO) / 16000
    return (np.sin(2 * np.pi * 220 * t) * amplitude).astype(np.int16).tobytes()


class MicrofoneFalso:
    def __init__(self, roteiro: list[bytes]):
        self.fila: queue.Queue[bytes] = queue.Queue()
        for b in roteiro:
            self.fila.put(b)

    def iniciar(self):
        pass

    def ler(self, timeout=0.5):
        try:
            return self.fila.get(timeout=0.01)
        except queue.Empty:
            time.sleep(0.01)
            return bloco(0)

    def esvaziar(self):
        pass

    def parar(self):
        pass


class DetectorFalso:
    """Dispara a ativação no primeiro bloco com som forte."""

    def __init__(self):
        self.disparos = 0

    def processar(self, b: bytes) -> bool:
        if rms(b) > 5000 and self.disparos == 0:
            self.disparos += 1
            return True
        return False

    def reiniciar(self):
        pass


def test_comando_de_voz_completo(app, monkeypatch):
    # silêncio, "Sexta-Feira" (som forte), comando (som médio) e silêncio
    roteiro = [bloco(0)] * 10 + [bloco(9000)] * 3 + [bloco(3000)] * 30 + [bloco(0)] * 60
    voz = modulo_voz.AssistenteVoz(app)
    voz.mic = MicrofoneFalso(roteiro)
    monkeypatch.setattr(modulo_voz, "criar_detector", lambda cfg: DetectorFalso())
    transcricoes = iter(["Sexta-feira, que horas são?"])
    monkeypatch.setattr(app.transcritor, "transcrever", lambda audio: next(transcricoes, ""))
    pedidos = []
    monkeypatch.setattr(app.agente, "processar", lambda texto, canal="voz", **k: pedidos.append((texto, canal)) or {"texto": "ok"})
    app.prefs.atualizar({"modo_continuacao": False})
    app.voz = voz
    voz.iniciar()
    for _ in range(300):
        if pedidos:
            break
        time.sleep(0.01)
    voz.parar()
    assert pedidos == [("que horas são?", "voz")]
    assert app.estado.atual in ("pensando", "inativa")


def test_so_o_nome_pergunta_pois_nao(app, monkeypatch):
    roteiro = [bloco(9000)] * 3 + [bloco(3000)] * 15 + [bloco(0)] * 40 + [bloco(3000)] * 20 + [bloco(0)] * 60
    voz = modulo_voz.AssistenteVoz(app)
    voz.mic = MicrofoneFalso(roteiro)
    monkeypatch.setattr(modulo_voz, "criar_detector", lambda cfg: DetectorFalso())
    transcricoes = iter(["Sexta-Feira?", "abre o Spotify"])
    monkeypatch.setattr(app.transcritor, "transcrever", lambda audio: next(transcricoes, ""))
    pedidos = []
    monkeypatch.setattr(app.agente, "processar", lambda texto, canal="voz", **k: pedidos.append(texto) or {"texto": "ok"})
    app.prefs.atualizar({"modo_continuacao": False})
    voz.iniciar()
    for _ in range(400):
        if pedidos:
            break
        time.sleep(0.01)
    voz.parar()
    assert "Pois não?" in app.fala.falas
    assert pedidos == ["abre o Spotify"]


def test_voz_respeita_bloqueio_facial(app, monkeypatch):
    roteiro = [bloco(9000)] * 3 + [bloco(3000)] * 20 + [bloco(0)] * 60
    voz = modulo_voz.AssistenteVoz(app)
    voz.mic = MicrofoneFalso(roteiro)
    monkeypatch.setattr(modulo_voz, "criar_detector", lambda cfg: DetectorFalso())
    monkeypatch.setattr(app.transcritor, "transcrever", lambda audio: "desliga o computador")
    monkeypatch.setattr(app.rosto, "cadastrado", lambda: True)
    from sexta.visao.rosto import Resultado

    monkeypatch.setattr(app.rosto, "verificar", lambda **k: Resultado(False, "desconhecido", 0.1))
    pedidos = []
    monkeypatch.setattr(app.agente, "processar", lambda texto, **k: pedidos.append(texto))
    app.sessao.bloquear("teste")
    voz.iniciar()
    time.sleep(1.5)
    voz.parar()
    assert pedidos == []  # não obedeceu
    assert app.sessao.bloqueada


class ReprodutorFalso:
    def __init__(self):
        self.tocados = []
        self._parar = threading.Event()

    def tocar(self, audio, taxa):
        self._parar.clear()
        self.tocados.append(len(audio) / taxa)
        fim = time.time() + 0.05
        while time.time() < fim:
            if self._parar.is_set():
                return False
            time.sleep(0.005)
        return True

    def parar(self):
        self._parar.set()


def test_fila_de_fala(app, monkeypatch):
    fala = Fala(app)
    fala.reprodutor = ReprodutorFalso()
    sintetizados = []

    def sintetizar(texto):
        sintetizados.append(texto)
        return tom([(440, 0.1)]), 24000

    monkeypatch.setattr(fala, "_sintetizar", sintetizar)
    estados = []
    app.barramento.ouvir(lambda e: e["tipo"] == "estado" and estados.append(e["estado"]))
    fala.falar("**Olá**, chefe! 🌞")
    fala.falar("Tudo pronto.")
    assert fala.aguardar(5)
    assert sintetizados == ["Olá, chefe!", "Tudo pronto."]
    assert len(fala.reprodutor.tocados) == 2
    assert estados[:1] == ["falando"] and estados[-1] == "inativa"
    # parar limpa a fila
    for i in range(5):
        fala.falar(f"Frase número {i}.")
    fala.parar()
    assert fala.aguardar(5)
    assert len(sintetizados) < 2 + 5
    fala.encerrar()


def test_decodificar_wav_e_reamostrar():
    sinal = (np.sin(np.linspace(0, 2 * np.pi * 440, 24000)) * 0.5).astype(np.float32)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes((sinal * 32767).astype("<i2").tobytes())
    audio, taxa = decodificar(buffer.getvalue(), 16000)
    assert taxa == 16000 and abs(len(audio) - 16000) < 400
    assert 0.3 < float(np.max(np.abs(audio))) < 0.6
    assert len(reamostrar(sinal, 24000, 48000)) == 48000


def test_interromper_enquanto_ela_fala(app, monkeypatch):
    """Dizer "Sexta-Feira" no meio da resposta faz ela parar e ouvir o novo pedido."""
    # 1º pedido; depois, enquanto ela "fala", um novo "Sexta-Feira" + pedido
    roteiro = ([bloco(9000)] * 3 + [bloco(3000)] * 20 + [bloco(0)] * 40 +   # comando 1
               [bloco(0)] * 30 + [bloco(9500)] * 3 + [bloco(3000)] * 20 + [bloco(0)] * 60)  # interrupção + comando 2
    voz = modulo_voz.AssistenteVoz(app)
    voz.mic = MicrofoneFalso(roteiro)

    class DetectorDuplo(DetectorFalso):
        def processar(self, b):
            if rms(b) > 5000:
                self.disparos += 1
                return self.disparos in (1, 4)  # 1º bloco forte de cada "Sexta-Feira"
            return False

    monkeypatch.setattr(modulo_voz, "criar_detector", lambda cfg: DetectorDuplo())
    transcricoes = iter(["Sexta-feira, me conta uma história longa", "Sexta-feira, para e me diz as horas"])
    monkeypatch.setattr(app.transcritor, "transcrever", lambda audio: next(transcricoes, ""))
    falando = threading.Event()
    paradas = []
    monkeypatch.setattr(app.fala, "falando_ou_na_fila", falando.is_set)
    monkeypatch.setattr(app.fala, "parar", lambda: (paradas.append(1), falando.clear()))
    pedidos = []

    def processar(texto, canal="voz", **k):
        pedidos.append(texto)
        if len(pedidos) == 1:
            falando.set()  # resposta longa sendo falada
        return {"texto": "ok"}

    monkeypatch.setattr(app.agente, "processar", processar)
    app.prefs.atualizar({"modo_continuacao": False})
    voz.iniciar()
    for _ in range(400):
        if len(pedidos) >= 2:
            break
        time.sleep(0.01)
    voz.parar()
    assert pedidos == ["me conta uma história longa", "para e me diz as horas"]
    assert paradas  # a fala foi interrompida


def test_efeito_traje_mantem_tamanho_e_volume():
    import numpy as np

    from sexta.voz.efeitos import para_wav, traje

    taxa = 24000
    t = np.arange(taxa * 2) / taxa
    audio = (0.6 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    saida = traje(audio, taxa)
    assert saida.dtype == np.float32 and len(saida) == len(audio)
    assert 0.5 < float(np.abs(saida).max()) <= 0.95
    assert not np.allclose(saida, audio)
    assert para_wav(saida, taxa)[:4] == b"RIFF"


def test_perfil_de_voz_sexta(app):
    from sexta.voz.fala import Fala

    fala = Fala(app)
    try:
        app.prefs.atualizar({"voz": "sexta"})
        assert fala.voz == "pt-BR-ThalitaMultilingualNeural" and fala._prosodia() == ("+4%", "-3Hz")
        app.prefs.atualizar({"voz": "pt-BR-AntonioNeural"})
        assert fala.voz == "pt-BR-AntonioNeural" and fala._prosodia() == (app.cfg.voz_velocidade, app.cfg.voz_tom)
    finally:
        fala.encerrar()


def test_preferencia_antiga_migra_para_voz_sexta(tmp_path):
    import json

    from sexta.config import Preferencias

    arquivo = tmp_path / "prefs.json"
    arquivo.write_text(json.dumps({"voz": "", "nome": "Jullio"}), encoding="utf-8")
    assert Preferencias(arquivo).get("voz") == "sexta"
    arquivo.write_text(json.dumps({"voz": "pt-BR-AntonioNeural"}), encoding="utf-8")
    assert Preferencias(arquivo).get("voz") == "pt-BR-AntonioNeural"

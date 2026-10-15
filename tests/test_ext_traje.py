"""Traje: inicialização, diagnóstico do PC, alertas proativos e modo jogo/overlay (sem Windows nem rede)."""

from __future__ import annotations

import io
import json
from datetime import date, datetime

import httpx
import pytest

from sexta.cerebro.ferramentas import Contexto
from sexta.extensoes import traje
from sexta.extensoes import traje_jogo as jogo
from sexta.extensoes import traje_sensores as sensores
from sexta.habilidades.clima import ServicoClima, minutos_ate_chuva


class SensoresFalsos:
    """Leituras fixas no lugar do PC."""

    def __init__(self, cpu=60.0, gpu=55.0, espaco=None) -> None:
        self.cpu, self.gpu_temp = cpu, gpu
        self._espaco = espaco if espaco is not None else [
            {"unidade": "C:", "pct": 50, "livre_gb": 200, "total_gb": 400, "sistema": True}]
        self._nvidia = None

    def temperaturas(self, idade=5.0):
        return {"cpu": self.cpu, "gpu": None, "fonte": "LibreHardwareMonitor", "erro": ""}

    def gpu(self, idade=2.0):
        return {"nome": "RTX", "temp": self.gpu_temp, "uso": 40.0, "vram_usada": 2000.0, "vram_total": 8000.0,
                "fonte": "nvidia-smi", "erro": ""}

    def uso(self):
        return {"cpu": 12.0, "ram": 40, "ram_usada": 6.4, "ram_total": 16.0}

    def espaco(self):
        return self._espaco

    def latencia(self, idade=3.0):
        return 18

    def ultimo(self, chave):
        return None

    def aquecer(self):
        pass

    def coletar(self, timeout=8.0):
        return {"temperaturas": self.temperaturas(), "gpu": self.gpu(), "uso": self.uso(), "espaco": self.espaco(),
                "saude_discos": {"discos": [{"nome": "Samsung SSD", "tipo": "SSD", "saude": "saudável", "ok": True}], "erro": ""},
                "rede": {"ping_ms": 18, "ssid": "Casa", "erro": ""},
                "atualizacoes": {"windows": 0, "winget": 2, "verificado": "2026-10-15T10:00:00", "verificando": False, "erro": ""},
                "bateria": {"presente": False, "erro": ""}}


@pytest.fixture
def eventos(app):
    lista: list[dict] = []
    app.barramento.ouvir(lista.append)
    return lista


@pytest.fixture
def falsos(app):
    s = SensoresFalsos()
    app.traje.sensores = s
    app.traje.jogo.sensores = s
    return s


# -- interpretação dos sensores -------------------------------------------------------------------
def test_temperaturas_do_librehardwaremonitor():
    saida = json.dumps({"fonte": "LibreHardwareMonitor", "acpi": [], "sensores": [
        {"Name": "Core #1", "Identifier": "/intelcpu/0/temperature/0", "Value": 70},
        {"Name": "CPU Package", "Identifier": "/intelcpu/0/temperature/8", "Value": 74.6},
        {"Name": "GPU Core", "Identifier": "/gpu-nvidia/0/temperature/0", "Value": 61},
        {"Name": "Temperature", "Identifier": "/nvme/0/temperature/0", "Value": 40}]})
    r = sensores.interpretar_temperaturas(saida)
    assert r == {"cpu": 75.0, "gpu": 61.0, "fonte": "LibreHardwareMonitor", "erro": ""}


def test_temperaturas_sem_lhm_usa_acpi_ou_explica():
    r = sensores.interpretar_temperaturas(json.dumps({"fonte": "", "sensores": [], "acpi": [3232]}))
    assert r["cpu"] == 50.0 and r["fonte"].startswith("ACPI")
    vazio = sensores.interpretar_temperaturas(json.dumps({"fonte": "", "sensores": [], "acpi": []}))
    assert vazio["cpu"] is None and "LibreHardwareMonitor" in vazio["erro"]


def test_nvidia_smi_discos_ssid_winget_bateria():
    g = sensores.interpretar_nvidia_smi("67, 98, 7012, 8192, NVIDIA GeForce RTX 3070\n")
    assert g["temp"] == 67 and g["uso"] == 98 and g["vram_total"] == 8192 and g["nome"].endswith("3070")
    assert sensores.interpretar_nvidia_smi("[N/A], 3, 100, 4096, GPU")["temp"] is None
    discos = sensores.interpretar_discos(json.dumps([
        {"FriendlyName": "Samsung SSD 980", "MediaType": 4, "HealthStatus": "Healthy", "Size": 1000204886016},
        {"FriendlyName": "WD Blue", "MediaType": "HDD", "HealthStatus": "Warning", "Size": 2000398934016}]))
    assert [d["ok"] for d in discos] == [True, False] and discos[0]["tipo"] == "SSD" and discos[1]["saude"] == "atenção"
    netsh = "    Nome                   : Wi-Fi\n    BSSID                  : aa:bb\n    SSID                   : Casa 5G\n"
    assert sensores.interpretar_ssid(netsh) == "Casa 5G"
    winget = ("Nome      ID           Versão Disponível Origem\n" + "-" * 50 + "\n"
              "Git       Git.Git      2.40   2.41       winget\nNode      OpenJS.Node  20     22         winget\n"
              "2 atualizações disponíveis.\n")
    assert sensores.interpretar_winget(winget) == 2
    xml = ('<BatteryReport xmlns="http://schemas.microsoft.com/battery/2012"><Batteries><Battery><Id>DELL</Id>'
           "<DesignCapacity>56000</DesignCapacity><FullChargeCapacity>42000</FullChargeCapacity></Battery></Batteries>"
           "</BatteryReport>")
    assert sensores.interpretar_bateria(xml)["saude_pct"] == 75
    assert sensores.interpretar_bateria("<BatteryReport><Batteries/></BatteryReport>") is None


def test_coleta_paralela_com_tempo_limite(tmp_path):
    s = sensores.Sensores(tmp_path, rodar=lambda c, t: "", powershell=lambda s, t: "", ping=lambda: 20, no_windows=False)
    r = s.coletar(timeout=3)
    assert r["temperaturas"]["erro"] == "só no Windows" and r["rede"]["ping_ms"] == 20
    assert isinstance(r["espaco"], list) and r["espaco"]


def test_atualizacoes_lentas_rodam_em_segundo_plano(tmp_path):
    import threading

    liberar = threading.Event()

    def powershell(script, timeout):
        if "Microsoft.Update" in script:
            liberar.wait(5)
            return "3"
        return ""

    s = sensores.Sensores(tmp_path, rodar=lambda c, t: "", powershell=powershell, ping=lambda: 20, no_windows=True)
    primeiro = s.atualizacoes()
    assert primeiro["verificando"] and primeiro["windows"] is None
    liberar.set()
    for _ in range(50):
        if not s.verificando("atualizacoes"):
            break
        threading.Event().wait(0.05)
    assert s.atualizacoes()["windows"] == 3


# -- clima ----------------------------------------------------------------------------------------
def test_chuva_de_curto_prazo():
    def responder(pedido: httpx.Request) -> httpx.Response:
        assert pedido.url.params["minutely_15"] == "precipitation"
        return httpx.Response(200, json={"utc_offset_seconds": -10800, "current": {"time": "2026-10-15T14:00", "precipitation": 0},
                                         "minutely_15": {"time": ["2026-10-15T14:00", "2026-10-15T14:15", "2026-10-15T14:30",
                                                                  "2026-10-15T14:45", "2026-10-15T15:00"],
                                                         "precipitation": [0, 0, 0, 0.6, 1.2]}})

    clima = ServicoClima(httpx.Client(transport=httpx.MockTransport(responder)))
    dados = clima.precipitacao_curta(-23.5, -46.6)
    assert clima.precipitacao_curta(-23.5, -46.6) is dados  # cache
    assert minutos_ate_chuva(dados, agora=datetime(2026, 10, 15, 14, 0)) == 30
    assert minutos_ate_chuva(dados, agora=datetime(2026, 10, 15, 13, 0)) is None  # fora da janela de 60 min
    chovendo = {**dados, "agora": {"mm": 0.5}}
    assert minutos_ate_chuva(chovendo, agora=datetime(2026, 10, 15, 14, 0)) is None


# -- alertas --------------------------------------------------------------------------------------
def test_alerta_sustentado_dispara_uma_vez_e_rearma():
    a = traje.AlertaSustentado()
    assert not a.atualizar(96, 95, 0)
    assert not a.atualizar(97, 95, 299)
    assert a.atualizar(96, 95, 300)
    assert not a.atualizar(99, 95, 900)  # já avisou
    assert not a.atualizar(92, 95, 1000)  # abaixo do limite, mas não de (limite - 5)
    assert not a.atualizar(80, 95, 1010)
    assert not a.atualizar(80, 95, 1100)
    assert not a.atualizar(80, 95, 1130) and not a.disparado  # 2 min abaixo: rearmou
    assert not a.atualizar(96, 95, 1200) and a.atualizar(96, 95, 1500)


def test_alerta_de_cpu_fala_e_notifica(app, falsos, eventos):
    falsos.cpu = 96
    app.traje.checar_temperaturas(agora=0)
    app.traje.checar_temperaturas(agora=301)
    assert "Chefe, a CPU está a 96 graus há 5 minutos." in app.fala.falas
    assert any(e["tipo"] == "notificacao" and "CPU" in e["texto"] for e in eventos)
    app.traje.checar_temperaturas(agora=400)
    assert len([f for f in app.fala.falas if "CPU" in f]) == 1


def test_alertas_respeitam_preferencias(app, falsos):
    app.prefs.atualizar({"alertas_proativos": False})
    falsos.cpu = 99
    app.traje.checar_temperaturas(agora=0)
    app.traje.checar_temperaturas(agora=400)
    assert not app.fala.falas


def test_chuva_avisa_uma_vez_por_evento_e_espera_o_foco(app, monkeypatch):
    app.prefs.atualizar({"cidade_lat": -23.5, "cidade_lon": -46.6}, interno=True)
    previsao = {"dados": {"agora": {"mm": 0}, "passos": [{"hora": "x", "mm": 1.0}], "offset": 0}}
    monkeypatch.setattr(app.clima, "precipitacao_curta", lambda lat, lon: previsao["dados"])
    monkeypatch.setattr("sexta.habilidades.clima.minutos_ate_chuva", lambda dados, *a, **k: 40 if dados["passos"][0]["mm"] else None)
    segurados = []
    monkeypatch.setattr(app.foco, "segurar", lambda acao: segurados.append(acao) or True)
    app.traje.checar_chuva()
    app.traje.checar_chuva()
    assert len(segurados) == 1 and not app.fala.falas  # modo foco: espera
    segurados[0]()
    assert app.fala.falas == ["Chefe, vai chover em uns 40 minutos."]
    previsao["dados"] = {"agora": {"mm": 0}, "passos": [{"hora": "x", "mm": 0}], "offset": 0}
    app.traje.checar_chuva()
    assert not app.traje.chuva_avisada  # passou: o próximo evento avisa de novo


def test_disco_cheio_uma_vez_por_dia(app, falsos):
    falsos._espaco = [{"unidade": "C:", "pct": 95, "livre_gb": 12, "total_gb": 240, "sistema": True}]
    app.traje.checar_disco(hoje=date(2026, 10, 15))
    app.traje.checar_disco(hoje=date(2026, 10, 15))
    assert app.fala.falas == ["Chefe, o disco C está com só 5% livre, 12 gigas."]
    app.traje.checar_disco(hoje=date(2026, 10, 16))
    assert len(app.fala.falas) == 2


# -- relatório ------------------------------------------------------------------------------------
REVISAO = {"tipo": "pc", "risco": "medio", "quando": "2026-10-10T09:00:00", "itens": [
    {"id": "defender-tempo-real", "titulo": "Proteção em tempo real do Defender ligada", "risco": "ok"},
    {"id": "firewall", "titulo": "Firewall desligado", "risco": "alto"}]}


def test_resumo_de_seguranca():
    r = traje.resumo_seguranca([{"tipo": "arquivo"}, REVISAO])
    assert r["defender"] == "ligado" and r["firewall"] == "desligado" and r["nivel"] == "falha"
    assert r["ultima_revisao"] == "2026-10-10T09:00:00"
    assert traje.resumo_seguranca([])["defender"] == "não verificado"


def test_relatorio_e_resumo_falado(app, falsos, monkeypatch):
    r = app.traje.relatorio()
    assert r["nivel"] == "ok" and r["seguranca"]["defender"] == "não verificado"
    assert traje.resumo_falado(r) == "Traje em ordem: CPU a 60 graus, GPU a 55 graus, disco C com 50% livre e ping de 18 milissegundos."
    monkeypatch.setattr(app.seguranca, "historico", lambda: [REVISAO])
    falsos.cpu = 91
    r = app.traje.relatorio()
    assert r["nivel"] == "falha"
    assert traje.resumo_falado(r).startswith("Traje operacional, com 2 pontos de atenção: firewall desligado e CPU a 91 graus")


def test_relatorio_sem_extensao_de_seguranca(app, falsos, monkeypatch):
    monkeypatch.delattr(app, "seguranca")
    assert app.traje.relatorio()["seguranca"] is None


def test_ferramenta_e_atalhos_do_relatorio(app, falsos):
    from sexta.cerebro.atalhos import tentar

    for frase in ("status do traje", "relatório do traje", "diagnóstico do traje", "como está o traje?"):
        resposta = tentar(frase, app.contexto("texto"))
        assert resposta is not None and resposta.startswith("Traje em ordem"), frase
    assert any(h["tipo"] == "traje" for h in app.hologramas.lista())


# -- inicialização --------------------------------------------------------------------------------
def test_sequencia_de_inicializacao(app, eventos, monkeypatch):
    monkeypatch.setattr(traje, "INTERVALO_INICIALIZACAO_S", 0)
    monkeypatch.setattr(app.agente.ollama, "verificar", lambda: (True, "Ollama ok (teste)"))
    app.transcritor._modelo = object()
    app.voz.mic_ok = True
    app.camera.erro = "Não consegui abrir a câmera 0."
    resumo = app.traje.inicializacao.executar("E hoje é sexta-feira: sextou!", esperar_hud=0)
    passos = [e for e in eventos if e["tipo"] == "inicializacao"]
    assert [e["fase"] for e in passos] == ["checando"] * 10 + ["fim"]
    assert [e["indice"] for e in passos[:10]] == list(range(1, 11)) and passos[0]["total"] == 10
    assert passos[0]["modulo"] == "Cérebro (Ollama)" and passos[0]["ok"]
    assert len(passos[-2]["itens"]) == 10
    assert resumo["falhas"] == ["Câmera"]
    falado = app.fala.tudo()
    assert falado.startswith("Sexta-Feira online. Câmera indisponível.") and falado.endswith("sextou!")
    assert app.fala.sons == 1


def test_inicializacao_tudo_ok(app, monkeypatch):
    monkeypatch.setattr(traje, "INTERVALO_INICIALIZACAO_S", 0)
    monkeypatch.setattr(app.agente.ollama, "verificar", lambda: (True, "ok"))
    monkeypatch.setattr("importlib.util.find_spec", lambda nome: object())
    app.voz.mic_ok = True
    app.transcritor._modelo = object()
    app.camera.erro = None
    app.traje.inicializacao.executar(esperar_hud=0)
    assert app.fala.tudo().startswith("Sexta-Feira online. Todos os sistemas operacionais.")


def test_app_delega_a_saudacao(app, monkeypatch):
    chamadas = []
    monkeypatch.setattr(app.traje, "sequencia_inicial", lambda complemento="": chamadas.append(complemento))
    app.com_voz = True
    app.prefs.atualizar({"saudacao_ao_iniciar": True, "sequencia_inicial": True})
    for nome in ("voz", "lembretes", "rotinas", "vigia", "jornal", "agenda", "aprendizado", "arquivos"):
        monkeypatch.setattr(getattr(app, nome), "iniciar", lambda *a, **k: None)
    monkeypatch.setattr("sexta.extensoes.iniciar", lambda app: None)
    monkeypatch.setattr(app.agente.ollama, "verificar", lambda: (False, "x"))
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(app, "_carregar_whisper", lambda: None)
    app._inicializar_servicos()
    assert chamadas == [""] and not app.fala.falas
    app.prefs.atualizar({"sequencia_inicial": False})
    app._inicializar_servicos()
    assert app.fala.falas and app.fala.falas[-1].startswith("Sexta-Feira online.")


# -- jogos ----------------------------------------------------------------------------------------
def test_reconhece_jogos_e_ignora_launchers():
    assert jogo.eh_jogo("EldenRing.exe", r"C:\Program Files (x86)\Steam\steamapps\common\ELDEN RING\Game\eldenring.exe")
    assert jogo.eh_jogo("VALORANT-Win64-Shipping.exe", r"C:\Riot Games\VALORANT\live\VALORANT-Win64-Shipping.exe")
    assert jogo.eh_jogo("Forza.exe", r"D:\XboxGames\Forza Horizon 5\Content\ForzaHorizon5.exe")
    assert not jogo.eh_jogo("RiotClientServices.exe", r"C:\Riot Games\Riot Client\RiotClientServices.exe")
    assert not jogo.eh_jogo("steam.exe", r"C:\Program Files (x86)\Steam\steam.exe")
    assert not jogo.eh_jogo("chrome.exe", r"C:\Program Files\Google\Chrome\chrome.exe")
    assert jogo.eh_jogo("javaw", r"C:\Java\javaw.exe", ["javaw.exe"])
    assert jogo.nome_amigavel("FortniteClient-Win64-Shipping.exe") == "Fortnite Client"
    assert jogo.nome_amigavel("EldenRing.exe") == "Elden Ring"


class JanelaFalsa:
    def __init__(self) -> None:
        self.abertas: list[tuple[str, str | None]] = []
        self.fechadas = 0

    def abrir(self, url, exe):
        self.abertas.append((url, exe))
        return True, ""

    def fechar(self):
        self.fechadas += 1

    def manter_no_topo(self, *a):
        pass


def test_modo_jogo_automatico_e_overlay(app, falsos, monkeypatch):
    executados = []
    monkeypatch.setattr(app.registro, "executar",
                        lambda nome, args, ctx, **_: executados.append((nome, args, ctx.confiavel)) or {"ok": True, "resumo": "ok"})
    processos = [{"pid": 10, "nome": "explorer.exe", "exe": r"C:\Windows\explorer.exe", "memoria": 1}]
    gerente = app.traje.jogo
    gerente.listar = lambda: processos
    gerente.janela = janela = JanelaFalsa()
    gerente.verificar()
    assert gerente.jogo is None and not executados
    processos.append({"pid": 42, "nome": "EldenRing.exe", "exe": r"C:\Steam\steamapps\common\ELDEN RING\eldenring.exe", "memoria": 9})
    gerente.verificar()
    assert gerente.jogo["titulo"] == "Elden Ring"
    assert ("configuracao", {"item": "plano_energia", "valor": "desempenho maximo"}, True) in executados
    assert ("configuracao", {"item": "nao_perturbe", "valor": "ligar"}, True) in executados
    assert janela.abertas and janela.abertas[0][0].startswith(f"http://127.0.0.1:{app.cfg.porta}/overlay#t=")
    assert "Modo jogo: Elden Ring" in app.fala.tudo()
    metricas = gerente.metricas()
    assert metricas["jogo"] == "Elden Ring" and metricas["fps"] is None and "PresentMon" in metricas["fps_dica"]
    processos.pop()
    gerente.verificar()
    assert gerente.jogo is None and not gerente.overlay_aberto and janela.fechadas
    assert ("configuracao", {"item": "plano_energia", "valor": "equilibrado"}, True) in executados
    assert ("configuracao", {"item": "nao_perturbe", "valor": "desligar"}, True) in executados


def test_modo_jogo_desligado_nao_mexe_no_sistema(app, falsos, monkeypatch):
    executados = []
    monkeypatch.setattr(app.registro, "executar", lambda nome, args, ctx, **_: executados.append(nome) or {"ok": True, "resumo": ""})
    app.prefs.atualizar({"modo_jogo_auto": False, "overlay_jogo": False})
    gerente = app.traje.jogo
    gerente.janela = JanelaFalsa()
    gerente.listar = lambda: [{"pid": 7, "nome": "game.exe", "exe": r"C:\Epic Games\Game\game.exe"}]
    gerente.verificar()
    assert gerente.jogo is not None and not executados and not gerente.janela.abertas


def test_atalhos_de_overlay_e_modo_jogo(app, falsos):
    from sexta.cerebro.atalhos import tentar

    app.traje.jogo.janela = JanelaFalsa()
    ctx = app.contexto("texto")

    def plano_atalho(frase, ctx):
        return lambda: tentar(frase, ctx)
    assert plano_atalho("desliga o overlay", ctx)().startswith("Overlay desligado")
    assert app.prefs.get("overlay_jogo") is False
    assert plano_atalho("liga o overlay", ctx)().startswith("Overlay ligado")
    assert app.prefs.get("overlay_jogo") is True
    app.traje.jogo.fechar_overlay()
    assert plano_atalho("desliga o modo jogo automático", ctx)() == "Modo jogo automático desligado."
    assert app.prefs.get("modo_jogo_auto") is False
    assert plano_atalho("liga o modo jogo automatico", ctx)().startswith("Modo jogo automático ligado")


def test_overlay_fora_do_windows_explica(app):
    ok, erro = jogo.JanelaOverlay(app.cfg.dados).abrir("http://x/overlay", None)
    assert not ok and "Windows" in erro


# -- FPS ------------------------------------------------------------------------------------------
def test_contador_de_fps():
    c = jogo.ContadorFps()
    for _ in range(200):
        c.adicionar(16.6667, agora=10.0)
    assert c.fps(agora=10.5) == pytest.approx(60, abs=0.5)
    assert c.fps(agora=13.0) is None  # o jogo parou de desenhar


def test_presentmon_le_csv_das_duas_versoes(tmp_path):
    leitor = jogo.LeitorPresentMon(tmp_path / "PresentMon.exe")
    csv1 = io.StringIO("Application,ProcessID,SwapChainAddress,Runtime,SyncInterval,PresentFlags,Dropped,TimeInSeconds,"
                       "msBetweenPresents\n" + "".join(f"game.exe,42,0x1,DXGI,0,0,0,{i / 100},10.0\n" for i in range(120)))
    assert leitor.ler(csv1)
    assert leitor.fps() == pytest.approx(100, abs=1)
    leitor2 = jogo.LeitorPresentMon(tmp_path / "PresentMon.exe")
    csv2 = [b"Application,ProcessID,FrameTime,CPUBusy\n"] + [b"game.exe,42,8.0,3.1\n"] * 200
    assert leitor2.ler(csv2) and leitor2.fps() == pytest.approx(125, abs=1)
    assert not jogo.LeitorPresentMon(tmp_path / "x").ler(["erro: opção desconhecida\n"])


def test_presentmon_pela_pasta_de_ferramentas(tmp_path, monkeypatch):
    monkeypatch.delenv("PRESENTMON", raising=False)
    assert jogo.caminho_presentmon(tmp_path) is None
    (tmp_path / "ferramentas").mkdir()
    (tmp_path / "ferramentas" / "PresentMon-2.3.0-x64.exe").write_bytes(b"MZ")
    assert jogo.caminho_presentmon(tmp_path).name == "PresentMon-2.3.0-x64.exe"


def test_posicao_do_overlay():
    assert jogo.posicao_overlay((1920, 0, 3840, 1080), 300) == (3524, 16)


def test_declaracoes():
    from sexta import eventos

    traje_mod = traje
    assert "traje.overlay" in traje_mod.EVENTOS_ALTA_FREQUENCIA
    assert "traje.overlay" in eventos.TIPOS_ALTA_FREQUENCIA
    assert traje_mod.PREFERENCIAS["alerta_cpu_temp"] == 95
    assert Contexto  # import usado pelos dublês

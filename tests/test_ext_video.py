"""Extensão de vídeos: tempos, linhas de comando do ffmpeg, fila com progresso, legendas, HyperFrames,
atalhos e rotas — tudo com dublês (nenhum ffmpeg, Node ou Whisper de verdade)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sexta.cerebro.ferramentas import Contexto
from sexta.extensoes import video as mod
from sexta.util.texto import normalizar


# ---------------------------------------------------------------- tempos

@pytest.mark.parametrize("texto,segundos", [
    ("1:15", 75), ("0:30", 30), ("1:02:03", 3723), ("30 segundos", 30), ("30s", 30), ("minuto 2", 120),
    ("1 minuto e 15", 75), ("1 minuto e 15 segundos", 75), ("1min15", 75), ("2 minutos", 120), ("1,5 minuto", 90),
    ("um minuto e meio", 90), ("meio minuto", 30), ("trinta e cinco segundos", 35), ("90", 90), ("no 0:45", 45),
    ("2h", 7200),
])
def test_interpretar_tempo(texto, segundos):
    assert mod.interpretar_tempo(texto) == pytest.approx(segundos)


@pytest.mark.parametrize("texto", ["banana", "", "o video da praia"])
def test_interpretar_tempo_recusa_o_que_nao_e_tempo(texto):
    assert mod.interpretar_tempo(texto) is None


def test_numero_sem_unidade_usa_a_padrao():
    assert mod.interpretar_tempo("3", "minuto") == 180


@pytest.mark.parametrize("texto,inicio,fim,do_fim", [
    ("do 0:30 ao 1:15", 30, 75, None),
    ("do minuto 2 ao 3", 120, 180, None),
    ("do minuto 2 ao minuto 3", 120, 180, None),
    ("de 10 a 20 segundos", 10, 20, None),
    ("entre 5 e 10 segundos", 5, 10, None),
    ("do 1 minuto e 15 ao 2 minutos", 75, 120, None),
    ("os primeiros 30 segundos", 0, 30, None),
    ("últimos 10 segundos", None, None, 10),
    ("a partir do 1:00", 60, None, None),
    ("do 2:00 até o fim", 120, None, None),
    ("até o 0:45", 0, 45, None),
])
def test_interpretar_intervalo(texto, inicio, fim, do_fim):
    i = mod.interpretar_intervalo(texto)
    assert (i.inicio, i.fim, i.do_fim) == (inicio, fim, do_fim)


def test_intervalo_resolvido_pela_duracao():
    assert mod.Intervalo(do_fim=10).resolver(60) == (50, 60)
    assert mod.Intervalo(30, None).resolver(60) == (30, 60)
    assert mod.Intervalo(30, 61).resolver(60) == (30, 60)  # passou um pouco do fim: vai até o fim
    with pytest.raises(mod.ErroVideo, match="começa depois do fim"):
        mod.Intervalo(70, 80).resolver(60)
    with pytest.raises(mod.ErroVideo, match="depois do começo"):
        mod.Intervalo(30, 20).resolver(60)


def test_separar_nome_do_trecho():
    assert mod.separar_trecho("do casamento do 0:30 ao 1:15") == ("do casamento", "do 0:30 ao 1:15")
    assert mod.separar_trecho("viagem") == ("viagem", None)


def test_formatar_tempo():
    assert mod.formatar_tempo(75) == "1:15"
    assert mod.formatar_tempo(3723) == "1:02:03"


# ---------------------------------------------------------------- ffmpeg

E, S = Path("/v/entrada.mp4"), Path("/v/saida.mp4")


def test_comando_de_corte_nunca_sobrescreve_e_manda_progresso():
    cmd = mod.cmd_cortar("ffmpeg", E, S, 30, 75, "media")
    assert cmd[:2] == ["ffmpeg", "-hide_banner"]
    assert "-n" in cmd and "-y" not in cmd
    assert cmd[cmd.index("-progress") + 1] == "pipe:1"
    assert cmd[cmd.index("-ss") + 1] == "30" and cmd[cmd.index("-t") + 1] == "45"
    assert cmd.index("-ss") < cmd.index("-i")  # busca rápida e precisa (antes da entrada)
    assert cmd[cmd.index("-crf") + 1] == "23" and cmd[-1] == str(S)


def test_comando_de_corte_sem_audio():
    cmd = mod.cmd_cortar("ffmpeg", E, S, 0, 1.5, "alta", audio=False)
    assert "-an" in cmd and "aac" not in cmd and cmd[cmd.index("-t") + 1] == "1.5"


def test_juntar_normaliza_tamanho_e_preenche_silencio():
    a = (Path("/v/a.mp4"), mod.InfoVideo(10, 1920, 1080, tem_audio=True))
    b = (Path("/v/b.mp4"), mod.InfoVideo(4, 640, 480, tem_audio=False))
    cmd = mod.cmd_juntar("ffmpeg", [a, b], S, "media")
    assert cmd.count("-i") == 3 and "anullsrc=r=48000:cl=stereo" in cmd
    filtro = cmd[cmd.index("-filter_complex") + 1]
    assert "scale=1920:1080:force_original_aspect_ratio=decrease" in filtro
    assert "[2:a]aresample" in filtro  # o silêncio entra no lugar do áudio de b
    assert filtro.endswith("concat=n=2:v=1:a=1[v][a]")
    sem_audio = mod.cmd_juntar("ffmpeg", [(a[0], mod.InfoVideo(1, 1280, 720)), b], S, "media")
    assert "anullsrc=r=48000:cl=stereo" not in sem_audio and "-an" in sem_audio


def test_extrair_audio_por_formato():
    assert "libmp3lame" in mod.cmd_extrair_audio("ffmpeg", E, Path("/v/a.mp3"))
    assert "pcm_s16le" in mod.cmd_extrair_audio("ffmpeg", E, Path("/v/a.wav"))
    assert "-vn" in mod.cmd_extrair_audio("ffmpeg", E, Path("/v/a.m4a"))


@pytest.mark.parametrize("fator,cadeia", [(2, "atempo=2"), (4, "atempo=2,atempo=2"), (0.5, "atempo=0.5"),
                                          (0.25, "atempo=0.5,atempo=0.5"), (1.5, "atempo=1.5")])
def test_cadeia_atempo(fator, cadeia):
    assert mod.cadeia_atempo(fator) == cadeia


def test_velocidade():
    cmd = mod.cmd_velocidade("ffmpeg", E, S, 2, True, "media")
    assert cmd[cmd.index("-filter_complex") + 1] == "[0:v]setpts=PTS/2[v];[0:a]atempo=2[a]"
    assert "-an" in mod.cmd_velocidade("ffmpeg", E, S, 0.5, False, "media")


def test_bitrate_para_caber_no_tamanho():
    video, altura = mod.bitrate_alvo(16, 60)
    assert 1700 < video < 2000 and altura == 720
    assert mod.bitrate_alvo(100, 30)[1] is None
    with pytest.raises(mod.ErroVideo, match="longo demais"):
        mod.bitrate_alvo(10, 3600)


def test_comprimir_reduz_a_resolucao():
    cmd = mod.cmd_comprimir("ffmpeg", E, S, 10, mod.InfoVideo(120, 1920, 1080, tem_audio=True))
    assert cmd[cmd.index("-vf") + 1] == "scale=-2:480"
    taxa = int(cmd[cmd.index("-b:v") + 1].rstrip("k"))
    assert taxa * 120 + 96 * 120 <= 10 * 8 * 1024  # cabe nos 10 MB


def test_converter_por_formato():
    assert "libvpx-vp9" in mod.cmd_converter("ffmpeg", E, Path("/v/s.webm"), "media", True)
    assert "mpeg4" in mod.cmd_converter("ffmpeg", E, Path("/v/s.avi"), "media", True)
    mkv = mod.cmd_converter("ffmpeg", E, Path("/v/s.mkv"), "media", False)
    assert "libx264" in mkv and "-an" in mkv and "+faststart" not in mkv


def test_gif_com_paleta():
    cmd = mod.cmd_gif("ffmpeg", E, Path("/v/s.gif"), 5, 10)
    assert "palettegen" in cmd[cmd.index("-filter_complex") + 1] and cmd[cmd.index("-t") + 1] == "5"


def test_sem_audio_copia_o_video():
    cmd = mod.cmd_sem_audio("ffmpeg", E, S)
    assert cmd[cmd.index("-c") + 1] == "copy" and "-an" in cmd


def test_vertical_corte_e_fundo():
    corte = mod.cmd_vertical("ffmpeg", E, S, "corte", "media", True)
    assert "crop=w='min(iw,ih*9/16)'" in corte[corte.index("-filter_complex") + 1]
    fundo = mod.cmd_vertical("ffmpeg", E, S, "fundo", "media", False, 10, 25)
    assert "boxblur" in fundo[fundo.index("-filter_complex") + 1] and "-an" in fundo
    assert fundo[fundo.index("-t") + 1] == "15"


def test_queimar_legenda_usa_nome_relativo():
    cmd = mod.cmd_queimar_legenda("ffmpeg", E, "legenda_1.srt", S, "media", True)
    assert cmd[cmd.index("-vf") + 1].startswith("subtitles=legenda_1.srt:")
    with pytest.raises(ValueError):
        mod.cmd_queimar_legenda("ffmpeg", E, r"C:\x\a.srt", S, "media", True)


def test_ler_sonda():
    info = mod.ler_sonda({"format": {"duration": "12.5", "size": "2048"}, "streams": [
        {"codec_type": "video", "width": 1280, "height": 720, "avg_frame_rate": "30000/1001"},
        {"codec_type": "audio"}]})
    assert (info.duracao, info.largura, info.altura, info.tem_audio) == (12.5, 1280, 720, True)
    assert info.fps == pytest.approx(29.97, 0.01)
    capa = mod.ler_sonda({"format": {"duration": "3"}, "streams": [
        {"codec_type": "audio"}, {"codec_type": "video", "disposition": {"attached_pic": 1}}]})
    assert not capa.tem_video and capa.tem_audio


def test_ler_progresso():
    assert mod.ler_progresso("out_time_us=5000000", 10) == 0.5
    assert mod.ler_progresso("out_time_ms=2500000", 10) == 0.25
    assert mod.ler_progresso("out_time=00:00:07.500000", 10) == 0.75
    assert mod.ler_progresso("progress=end", 10) == 1.0
    assert mod.ler_progresso("out_time_us=N/A", 10) is None
    assert mod.ler_progresso("frame=12", 10) is None
    assert mod.ler_progresso("out_time_us=99000000", 10) == 1.0


# ---------------------------------------------------------------- legendas

def test_blocos_e_srt():
    longo = "palavra " * 30
    blocos = mod.blocos_legenda([(0.0, 6.0, longo), (7.0, 8.0, "Oi."), (9, 9, "vazio")])
    assert len(blocos) == 4 and blocos[-1] == (7.0, 8.0, "Oi.")
    assert blocos[2][1] == pytest.approx(6.0)
    for _, _, texto in blocos:
        assert all(len(linha) <= 42 for linha in texto.split("\n")) and texto.count("\n") <= 1
    srt = mod.gerar_srt([(1.5, 3.25, "Olá"), (3661.0, 3662.0, "fim")])
    assert srt == "1\n00:00:01,500 --> 00:00:03,250\nOlá\n\n2\n01:01:01,000 --> 01:01:02,000\nfim\n"


# ---------------------------------------------------------------- HyperFrames

HTML = '<!doctype html><html><body><div id="root" data-composition-id="main"></div></body></html>'


def test_extrair_html():
    assert mod.extrair_html(f"Aqui está:\n```html\n{HTML}\n```\nPronto.") == HTML + "\n"
    assert mod.extrair_html(f"texto {HTML} mais") == HTML + "\n"
    with pytest.raises(mod.ErroVideo):
        mod.extrair_html("não sei fazer isso")


def test_ler_lint_e_problemas():
    saida = "npm aviso\n" + json.dumps({"ok": False, "errorCount": 1, "warningCount": 1, "findings": [
        {"code": "gsap_animates_clip_element", "severity": "error", "message": "não anime clip", "selector": "#c1",
         "fixHint": "anime o filho"},
        {"code": "x", "severity": "warning", "message": "aviso"}, {"code": "y", "severity": "info", "message": "i"}]})
    ok, problemas = mod.ler_lint(saida)
    assert not ok and [p["code"] for p in problemas] == ["gsap_animates_clip_element", "x"]
    texto = mod.descrever_problemas(problemas)
    assert "(em #c1)" in texto and "dica: anime o filho" in texto
    assert mod.ler_lint(json.dumps({"ok": True, "errorCount": 0, "findings": [
        {"code": "w", "severity": "warning", "message": "só aviso"}]}))[0]
    with pytest.raises(mod.ErroVideo):
        mod.ler_lint("command not found")


def test_progresso_do_render():
    assert mod.ler_progresso_render('@hf-progress {"code":"capture","pct":42}') == 0.42
    assert mod.ler_progresso_render("Rendering...") is None


def test_prompt_traz_as_regras_do_hyperframes():
    texto = mod.SISTEMA_HYPERFRAMES.format(largura=1920, altura=1080, duracao="15", titulo_px=110)
    for regra in ("data-composition-id", "data-duration=\"15\"", "paused: true", 'window.__timelines["main"]',
                  "class=\"clip\"", "gsap_animates_clip_element", "Math.random", "width=1920, height=1080"):
        assert regra in texto


# ---------------------------------------------------------------- fila com dublês

class Processos:
    """Dublê de ``rodar_processo``: anota a linha de comando, manda progresso e cria a saída."""

    def __init__(self, gerente, lint: list[dict] | None = None, codigo: int = 0) -> None:
        self.comandos: list[list[str]] = []
        self.cwds: list = []
        self.lint = list(lint or [])
        self.codigo = codigo
        gerente.rodar_processo = self

    def __call__(self, trabalho, cmd, *, cwd=None, ao_linha=None, env=None):
        self.comandos.append(cmd)
        self.cwds.append(cwd)
        if cmd[1:4] == ["--yes", "hyperframes", "lint"]:
            return 0, json.dumps(self.lint.pop(0) if self.lint else {"ok": True, "errorCount": 0, "findings": []}), ""
        if "render" in cmd:
            for pct in (10, 60, 100):
                ao_linha(f'@hf-progress {{"pct": {pct}}}\n')
            saida = Path(cmd[cmd.index("--output") + 1])
        else:
            for linha in ("out_time_us=1000000", "progress=continue", "progress=end"):
                ao_linha and ao_linha(linha + "\n")
            saida = Path(cmd[-1])
        if self.codigo == 0:
            saida.write_bytes(b"dados")
        return self.codigo, "", "Erro de verdade" if self.codigo else ""


@pytest.fixture
def videos(app, tmp_path, monkeypatch):
    pasta = tmp_path / "MeusVideos"
    pasta.mkdir()
    app.prefs.atualizar({"videos_pasta": str(pasta)})
    gerente = app.videos
    gerente.programa = lambda nome: nome
    infos = {}
    gerente.sondar = lambda caminho: infos.get(caminho.name, mod.InfoVideo(60, 1920, 1080, tem_audio=True, tamanho=50 << 20))
    gerente.infos = infos
    eventos = []
    monkeypatch.setattr(app.barramento, "publicar", lambda tipo, para=None, **d: eventos.append((tipo, d)))
    gerente.eventos = eventos
    return pasta


def novo(pasta: Path, nome: str, mtime: float | None = None) -> Path:
    caminho = pasta / nome
    caminho.write_bytes(b"video")
    if mtime:
        import os

        os.utime(caminho, (mtime, mtime))
    return caminho


def rodar_ultimo(app):
    trabalho = app.videos._trabalhos[-1]
    app.videos.executar(trabalho)
    return trabalho


def test_cortar_gera_arquivo_novo_e_avisa(app, videos):
    original = novo(videos, "Viagem Praia.mp4")
    processos = Processos(app.videos)
    r = app.registro.executar("video_editar", {"acao": "cortar", "video": "viagem", "trecho": "do 0:30 ao 1:15"},
                              Contexto(app))
    assert r["ok"] and "do 0:30 ao 1:00" in r["resumo"]  # o vídeo tem 60 s: o fim vira o fim do vídeo
    trabalho = rodar_ultimo(app)
    assert trabalho.estado == "ok" and trabalho.progresso == 1.0
    cmd = processos.comandos[0]
    assert cmd[cmd.index("-i") + 1] == str(original)
    saida = Path(cmd[-1])
    assert saida == videos / "Sexta-Feira" / "Viagem Praia (cortado).mp4" and saida.is_file()
    assert original.read_bytes() == b"video"
    gerados = app.videos.gerados()
    assert gerados[-1]["nome"] == saida.name and gerados[-1]["tipo"] == "video"
    assert any("Pronto" in f for f in app.fala.falas)
    assert any(t == "video.trabalhos" for t, _ in app.videos.eventos)
    assert any(t == "aviso" and d["nivel"] == "sucesso" for t, d in app.videos.eventos)


def test_segundo_corte_nao_sobrescreve(app, videos):
    novo(videos, "a.mp4")
    Processos(app.videos)
    for _ in range(2):
        app.registro.executar("video_editar", {"acao": "cortar", "video": "a", "inicio": "0", "fim": "10"}, Contexto(app))
        rodar_ultimo(app)
    nomes = sorted(p.name for p in (videos / "Sexta-Feira").iterdir())
    assert nomes == ["a (cortado 2).mp4", "a (cortado).mp4"]


def test_o_ultimo_video(app, videos):
    novo(videos, "velho.mp4", time.time() - 1000)
    novo(videos, "novo.mkv")
    (videos / "nota.txt").write_text("x")
    processos = Processos(app.videos)
    app.registro.executar("video_editar", {"acao": "sem_audio", "video": "o último vídeo"}, Contexto(app))
    rodar_ultimo(app)
    assert processos.comandos[0][processos.comandos[0].index("-i") + 1].endswith("novo.mkv")
    assert processos.comandos[0][-1].endswith("novo (sem áudio).mkv")


def test_video_que_nao_existe(app, videos):
    r = app.registro.executar("video_editar", {"acao": "gif", "video": "aniversario"}, Contexto(app))
    assert not r["ok"] and "aniversario" in r["resumo"]


def test_sem_ffmpeg_explica_como_instalar(app, videos, monkeypatch):
    monkeypatch.setattr(mod, "localizar", lambda nome: None)
    del app.videos.programa  # volta ao método de verdade
    r = app.registro.executar("video_editar", {"acao": "gif", "video": "x"}, Contexto(app))
    assert not r["ok"] and "winget install Gyan.FFmpeg" in r["resumo"]


def test_falha_do_ffmpeg_vira_aviso_e_apaga_a_saida_parcial(app, videos):
    novo(videos, "a.mp4")
    Processos(app.videos, codigo=1)
    app.registro.executar("video_editar", {"acao": "converter", "video": "a", "formato": "webm"}, Contexto(app))
    trabalho = rodar_ultimo(app)
    assert trabalho.estado == "erro" and "Erro de verdade" in trabalho.erro
    assert not (videos / "Sexta-Feira" / "a.webm").exists()
    assert any("Não consegui" in f for f in app.fala.falas)


def test_juntar_e_comprimir(app, videos):
    novo(videos, "parte1.mp4")
    novo(videos, "parte2.mp4")
    processos = Processos(app.videos)
    r = app.registro.executar("video_editar", {"acao": "juntar", "videos": ["parte1", "parte2"]}, Contexto(app))
    assert r["ok"] and "2 vídeos" in r["resumo"]
    rodar_ultimo(app)
    assert "concat=n=2" in processos.comandos[-1][processos.comandos[-1].index("-filter_complex") + 1]
    r = app.registro.executar("video_editar", {"acao": "comprimir", "video": "parte1", "destino": "discord"},
                              Contexto(app))
    assert "Discord (10 MB)" in r["resumo"]
    app.videos.infos["pequeno.mp4"] = mod.InfoVideo(10, 640, 360, tem_audio=True, tamanho=1 << 20)
    novo(videos, "pequeno.mp4")
    r = app.registro.executar("video_editar", {"acao": "comprimir", "video": "pequeno"}, Contexto(app))
    assert r["ok"] and "já tem" in r["resumo"]


def test_juntar_precisa_de_dois(app, videos):
    r = app.registro.executar("video_editar", {"acao": "juntar", "videos": ["um"]}, Contexto(app))
    assert not r["ok"]


def test_velocidade_fora_do_limite(app, videos):
    novo(videos, "a.mp4")
    r = app.registro.executar("video_editar", {"acao": "velocidade", "video": "a", "fator": 10}, Contexto(app))
    assert not r["ok"] and "4x" in r["resumo"]


def test_cancelar_trabalho_na_fila(app, videos):
    novo(videos, "a.mp4")
    Processos(app.videos)
    app.registro.executar("video_editar", {"acao": "gif", "video": "a"}, Contexto(app))
    r = app.registro.executar("video_trabalhos", {"acao": "cancelar"}, Contexto(app))
    assert r["ok"] and app.videos._trabalhos[-1].estado == "cancelado"
    assert app.registro.executar("video_trabalhos", {"acao": "status"}, Contexto(app))["resumo"].startswith("Nenhum")


def test_cancelar_no_meio_apaga_a_saida(app, videos):
    novo(videos, "a.mp4")
    app.registro.executar("video_editar", {"acao": "gif", "video": "a"}, Contexto(app))
    trabalho = app.videos._trabalhos[-1]

    def processo(t, cmd, **_):
        Path(cmd[-1]).write_bytes(b"pela metade")
        app.videos.cancelar(t.id)
        app.videos._checar_cancelado(t)

    app.videos.rodar_processo = processo
    app.videos.executar(trabalho)
    assert trabalho.estado == "cancelado" and not list((videos / "Sexta-Feira").iterdir())


def test_status_mostra_o_progresso(app, videos):
    novo(videos, "a.mp4")
    app.registro.executar("video_editar", {"acao": "gif", "video": "a"}, Contexto(app))
    trabalho = app.videos._trabalhos[-1]
    trabalho.estado = "rodando"
    app.videos.etapa(trabalho, "Processando", 0, 1)
    app.videos.progresso(trabalho, 0.42)
    assert "42%" in mod.descrever_trabalhos(app)


def test_legendas_com_whisper_falso(app, videos):
    novo(videos, "aula.mp4")
    processos = Processos(app.videos)
    app.videos.transcrever = lambda t, wav, idioma, dur: [(0.0, 2.0, "Bom dia, turma."), (2.5, 4.0, "Hoje é vídeo.")]
    r = app.registro.executar("video_legendas", {"video": "aula", "queimar": True}, Contexto(app))
    assert r["ok"] and "Whisper" in r["resumo"]
    trabalho = rodar_ultimo(app)
    assert trabalho.estado == "ok"
    srt = videos / "Sexta-Feira" / "aula.srt"
    assert srt.read_text(encoding="utf-8").startswith("1\n00:00:00,000 --> 00:00:02,000\nBom dia, turma.")
    wav_cmd, queimar_cmd = processos.comandos
    assert wav_cmd[-1].endswith(f"audio_{trabalho.id}.wav") and "16000" in wav_cmd
    assert queimar_cmd[queimar_cmd.index("-vf") + 1].startswith(f"subtitles=legenda_{trabalho.id}.srt")
    assert processos.cwds[1] == app.videos.pasta / "tmp"
    assert not list((app.videos.pasta / "tmp").iterdir())  # temporários apagados
    assert [g["tipo"] for g in app.videos.gerados()] == ["legenda", "video"]


def test_legendas_sem_fala(app, videos):
    novo(videos, "mudo.mp4")
    Processos(app.videos)
    app.videos.transcrever = lambda *a: []
    app.registro.executar("video_legendas", {"video": "mudo"}, Contexto(app))
    assert rodar_ultimo(app).erro == "Não ouvi fala nenhuma no vídeo."


class CerebroFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.pedidos = []

    def completar(self, sistema, texto, rapido=True):
        self.pedidos.append((sistema, texto, rapido))
        return self.respostas.pop(0)


def test_criar_com_hyperframes_corrige_o_lint(app, videos):
    erro = {"ok": False, "errorCount": 1, "findings": [{"code": "gsap_css_transform_conflict", "severity": "error",
                                                        "message": "conflito"}]}
    processos = Processos(app.videos, lint=[erro])
    cerebro = CerebroFalso([f"```html\n{HTML}\n```", f"```html\n{HTML.replace('main', 'main' + chr(34) + ' x=' + chr(34))}\n```"])
    app.agente = cerebro
    r = app.registro.executar("video_criar", {"briefing": "um vídeo vertical de 12 segundos anunciando meu canal"},
                              Contexto(app))
    assert r["ok"] and "12 segundos em 9:16" in r["resumo"]
    trabalho = rodar_ultimo(app)
    assert trabalho.estado == "ok", trabalho.erro
    sistema, pedido, rapido = cerebro.pedidos[0]
    assert 'data-width="1080" data-height="1920" data-duration="12"' in sistema and not rapido
    assert "gsap_css_transform_conflict" in cerebro.pedidos[1][1]
    lint1, lint2, render = processos.comandos
    assert lint1[:5] == ["npx", "--yes", "hyperframes", "lint", "--json"]
    assert render[:4] == ["npx", "--yes", "hyperframes", "render"]
    assert render[render.index("--quality") + 1] == "looks"
    projeto = Path(r["projeto"])
    assert projeto.parent == app.videos.pasta and (projeto / "index.html").read_text().count('x="') == 1
    assert Path(render[render.index("--output") + 1]).parent == videos / "Sexta-Feira"


def test_criar_desiste_depois_de_duas_correcoes(app, videos):
    erro = {"ok": False, "errorCount": 1, "findings": [{"code": "ruim", "severity": "error", "message": "x"}]}
    processos = Processos(app.videos, lint=[erro, erro, erro])
    app.agente = CerebroFalso([HTML] * 3)
    app.registro.executar("video_criar", {"briefing": "intro animada com o texto Sexta"}, Contexto(app))
    trabalho = rodar_ultimo(app)
    assert trabalho.estado == "erro" and "ruim" in trabalho.erro
    assert len(processos.comandos) == 3 and not any("render" in c for c in processos.comandos)


def test_criar_sem_node(app, videos, monkeypatch):
    monkeypatch.setattr(mod, "localizar", lambda nome: None if nome == "npx" else nome)
    del app.videos.programa
    r = app.registro.executar("video_criar", {"briefing": "intro"}, Contexto(app))
    assert not r["ok"] and "Node.js 22" in r["resumo"]


# ---------------------------------------------------------------- atalhos

def _atalho(app, frase):
    rodar = lambda nome, args, padrao=None: (nome, args)  # noqa: E731
    t = normalizar(frase).removeprefix("sexta feira ")  # como em cerebro/atalhos.tentar
    return mod.atalho(t, Contexto(app), rodar, frase)


@pytest.mark.parametrize("frase,nome,args", [
    ("corta o vídeo viagem do 0:30 ao 1:15", "video_editar",
     {"acao": "cortar", "video": "viagem", "trecho": "do 0:30 ao 1:15"}),
    ("corta o vídeo do casamento do minuto 2 ao 3", "video_editar",
     {"acao": "cortar", "video": "casamento", "trecho": "do minuto 2 ao 3"}),
    ("corta o último vídeo dos primeiros 30 segundos", "video_editar",
     {"acao": "cortar", "video": "o último vídeo", "trecho": "dos primeiros 30 segundos"}),
    ("extrai o áudio do vídeo show", "video_editar", {"acao": "extrair_audio", "video": "show", "formato": "mp3"}),
    ("tira o áudio do vídeo show", "video_editar", {"acao": "sem_audio", "video": "show"}),
    ("comprime o vídeo show para o WhatsApp", "video_editar", {"acao": "comprimir", "video": "show", "destino": "whatsapp"}),
    ("comprime o vídeo show pra 8 MB", "video_editar", {"acao": "comprimir", "video": "show", "destino": "8mb"}),
    ("converte o vídeo show para webm", "video_editar", {"acao": "converter", "video": "show", "formato": "webm"}),
    ("faz um gif do vídeo gato do 0:05 ao 0:10", "video_editar",
     {"acao": "gif", "video": "gato", "trecho": "do 0:05 ao 0:10"}),
    ("acelera o vídeo corrida em 3x", "video_editar", {"acao": "velocidade", "video": "corrida", "fator": 3.0}),
    ("desacelera o vídeo corrida", "video_editar", {"acao": "velocidade", "video": "corrida", "fator": 2.0 ** -1}),
    ("deixa o vídeo gol em câmera lenta", "video_editar", {"acao": "velocidade", "video": "gol", "fator": 0.5}),
    ("coloca legendas no vídeo aula", "video_legendas", {"video": "aula", "queimar": True}),
    ("gera legenda do vídeo aula em inglês", "video_legendas", {"video": "aula", "queimar": False, "idioma": "en"}),
    ("faz um corte vertical do vídeo live", "video_editar", {"acao": "vertical", "video": "live", "modo": "corte"}),
    ("faz um corte vertical do vídeo live do 1:00 ao 1:30 com fundo desfocado", "video_editar",
     {"acao": "vertical", "video": "live", "modo": "fundo", "trecho": "do 1:00 ao 1:30"}),
    ("junta os vídeos praia, piscina e show", "video_editar",
     {"acao": "juntar", "videos": ["praia", "piscina", "show"]}),
    ("Sexta-feira, cria um vídeo de 15 segundos anunciando meu canal", "video_criar",
     {"briefing": "cria um vídeo de 15 segundos anunciando meu canal"}),
    ("faz uma intro animada com o texto Oficina do João", "video_criar",
     {"briefing": "faz uma intro animada com o texto Oficina do João"}),
    ("mostra os vídeos", "video_trabalhos", {"acao": "mostrar"}),
    ("como está o vídeo", "video_trabalhos", {"acao": "status"}),
    ("cancela a renderização", "video_trabalhos", {"acao": "cancelar"}),
])
def test_atalhos(app, frase, nome, args):
    assert _atalho(app, frase) == (nome, args)


@pytest.mark.parametrize("frase", [
    "para o vídeo", "pausa o vídeo", "abre o vídeo da viagem", "corta o vídeo viagem", "faz um vídeo do meu jogo",
    "corta a cebola", "junta os vídeos praia",
])
def test_frases_que_nao_sao_atalhos_de_video(app, frase):
    assert _atalho(app, frase) is None


def test_atalho_chega_pelo_agente(app, monkeypatch):
    from sexta.cerebro.agente import Agente

    from test_agente import OllamaFalso, cliente

    chamadas = []
    monkeypatch.setattr(app.registro, "executar",
                        lambda nome, a, ctx, **_: chamadas.append((nome, a)) or {"ok": True, "resumo": "ok"})
    app.agente = Agente(app, cliente(OllamaFalso([])))
    assert app.agente.processar("corta o vídeo viagem do 0:30 ao 1:15")["caminho"] == "atalho"
    assert chamadas[0][0] == "video_editar"


# ---------------------------------------------------------------- HUD

@pytest.fixture
def api(app):
    from sexta.servidor import criar_api

    with TestClient(criar_api(app), base_url="http://127.0.0.1:8765") as c:
        c.headers["Authorization"] = f"Bearer {app.acesso.token_pc}"
        yield c


def test_rota_serve_so_arquivos_gerados(app, videos, api, tmp_path):
    gerado = videos / "clip.mp4"
    gerado.write_bytes(b"0123456789")
    item = app.videos.registrar_gerado(gerado, "cortar")
    assert api.get(f"/api/videos/arquivo/{item['id']}", headers={"Authorization": ""}).status_code == 401
    r = api.get(f"/api/videos/arquivo/{item['id']}")
    assert r.status_code == 200 and r.content == b"0123456789" and r.headers["content-type"] == "video/mp4"
    parcial = api.get(f"/api/videos/arquivo/{item['id']}", headers={"Range": "bytes=2-4"})
    assert parcial.status_code == 206 and parcial.content == b"234"  # o <video> pede por partes
    token = app.acesso.token_pc
    assert api.get(f"/api/videos/arquivo/{item['id']}?token={token}", headers={"Authorization": ""}).status_code == 200
    assert api.get("/api/videos/arquivo/999").status_code == 404
    assert api.get("/api/videos/arquivo/..%2F..%2Fsegredo").status_code in (404, 422)
    estado = api.get("/api/videos/estado").json()
    assert estado["gerados"][0]["nome"] == "clip.mp4" and estado["gerados"][0]["existe"]


def test_gerados_persistem(app, videos):
    arquivo = videos / "x.gif"
    arquivo.write_bytes(b"g")
    app.videos.registrar_gerado(arquivo, "gif")
    outro = mod.GerenteVideos(app, app.videos.pasta)
    assert outro.gerados()[0]["tipo"] == "gif"


def test_holograma_e_diagnostico(app, videos, monkeypatch):
    app.hologramas.mostrar("videos", mod.dados_holograma(app, "videos"))
    assert app.hologramas.aberto("videos")
    monkeypatch.setattr(mod, "localizar", lambda nome: None)
    itens = {i["nome"]: i for i in mod.diagnostico(app, forcar=True)}
    assert not itens["Vídeos: ffmpeg"]["ok"] and "winget" in itens["Vídeos: ffmpeg"]["dica"]
    assert not itens["Vídeos: Node.js (HyperFrames)"]["ok"]
    assert itens["Vídeos: pasta"]["ok"]


def test_diagnostico_node_antigo(app, videos, monkeypatch):
    monkeypatch.setattr(mod, "localizar", lambda nome: nome)
    monkeypatch.setattr(mod, "versao_node", lambda node: (20, "v20.1.0"))
    itens = {i["nome"]: i for i in mod.diagnostico(app, forcar=True)}
    assert not itens["Vídeos: Node.js (HyperFrames)"]["ok"] and itens["Vídeos: ffmpeg"]["ok"]


def test_pasta_padrao_e_env(app, monkeypatch, tmp_path):
    app.prefs.atualizar({"videos_pasta": ""})
    monkeypatch.setenv("VIDEOS_PASTA", str(tmp_path / "env"))
    assert mod.pasta_videos(app) == tmp_path / "env"
    monkeypatch.delenv("VIDEOS_PASTA")
    assert mod.pasta_videos(app).name in ("Videos", "Vídeos")

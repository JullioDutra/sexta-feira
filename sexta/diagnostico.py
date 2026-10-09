"""Checagem rápida do que está funcionando (usada pelo HUD e por ``python -m sexta diagnostico``)."""

from __future__ import annotations

from .visao.maos import MODELO_MAOS
from .visao.rosto import MODELO_DETECTOR, MODELO_MARCOS, MODELO_RECONHECEDOR


def verificar_tudo(app) -> list[dict]:
    cfg = app.cfg
    itens: list[dict] = []

    def item(nome: str, ok: bool, detalhe: str = "", dica: str = "") -> None:
        itens.append({"nome": nome, "ok": ok, "detalhe": detalhe, "dica": dica})

    ok, mensagem = app.agente.ollama.verificar()
    item("Cérebro (Ollama)", ok, mensagem, "" if ok else f"Instale o Ollama e rode: ollama pull {cfg.ollama_modelo}")

    vosk = (cfg.modelos / "vosk-model-small-pt-0.3").exists()
    item("Ativação por voz (Vosk)", vosk or cfg.ativacao_motor != "vosk", "modelo presente" if vosk else "modelo ausente",
         "" if vosk else "python -m sexta baixar")
    if app.voz.mic_ok:
        item("Microfone", True, "capturando")
    else:
        try:
            import sounddevice as sd

            nome = sd.query_devices(kind="input")["name"]
            item("Microfone", True, f"padrão do Windows: {nome}")
        except Exception as erro:  # noqa: BLE001
            item("Microfone", False, f"sem microfone ({erro})", "Confira o microfone padrão do Windows ou MICROFONE no .env")
    if app.transcritor._modelo is not None:
        item("Transcrição (Whisper)", True, f"{cfg.whisper_modelo} em {app.transcritor.dispositivo}")
    else:
        pasta = cfg.modelos / "whisper"
        baixado = pasta.exists() and any(cfg.whisper_modelo in p.name for p in pasta.iterdir())
        item("Transcrição (Whisper)", baixado, f"modelo {cfg.whisper_modelo} " + ("baixado" if baixado else "ainda não baixado"),
             "" if baixado else "python -m sexta baixar")

    rosto = all((cfg.modelos / m).exists() for m in (MODELO_DETECTOR, MODELO_RECONHECEDOR))
    detalhe, dica = ("cadastrado" if app.rosto.cadastrado() else "sem cadastro"), ""
    if rosto:
        try:
            app.rosto._carregar()
        except Exception as erro:  # noqa: BLE001
            rosto, detalhe = False, f"modelos não abrem: {erro}"
            dica = "Apague os .onnx em dados/modelos e rode: iniciar.bat baixar"
    else:
        dica = "python -m sexta baixar"
    item("Reconhecimento facial", rosto, detalhe, dica)
    item("Teste de piscada", (cfg.modelos / MODELO_MARCOS).exists(), MODELO_MARCOS)
    item("Gestos com as mãos", (cfg.modelos / MODELO_MAOS).exists(), MODELO_MAOS)
    item("Câmera", app.camera.erro is None, app.camera.erro or "ok (liga quando precisa)")
    return itens
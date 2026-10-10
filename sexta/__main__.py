"""Linha de comando da Sexta-Feira.

    python -m sexta                 inicia a assistente
    python -m sexta baixar          baixa os modelos (rosto, mãos, voz, Whisper)
    python -m sexta diagnostico     mostra o que está funcionando
    python -m sexta pin             define ou remove o PIN
    python -m sexta dispositivos    lista/remove celulares pareados
    python -m sexta microfones      lista microfones e alto-falantes
    python -m sexta testar-voz      fala uma frase de teste
    python -m sexta testar-ativacao mostra quando ela ouve "Sexta-Feira"
    python -m sexta abrir           abre o HUD de uma Sexta-Feira já em execução
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
import time

from .config import Config
from .logs import configurar_logs


def main(argv: list[str] | None = None) -> int:
    from .habilidades.windows import ativar_dpi

    ativar_dpi()
    parser = argparse.ArgumentParser(prog="sexta", description="Sexta-Feira — assistente pessoal")
    sub = parser.add_subparsers(dest="comando")
    sub.add_parser("iniciar", help="inicia a assistente (padrão)")
    baixar = sub.add_parser("baixar", help="baixa os modelos")
    baixar.add_argument("--sem-whisper", action="store_true", help="não baixa o Whisper agora")
    sub.add_parser("diagnostico", help="verifica componentes")
    sub.add_parser("pin", help="define/remove o PIN")
    disp = sub.add_parser("dispositivos", help="lista ou remove celulares pareados")
    disp.add_argument("remover", nargs="?", help="id do dispositivo a remover")
    sub.add_parser("microfones", help="lista dispositivos de áudio")
    voz = sub.add_parser("testar-voz", help="fala uma frase")
    voz.add_argument("texto", nargs="*", default=["Olá, chefe. Sexta-Feira online e operacional."])
    sub.add_parser("testar-ativacao", help="testa a palavra de ativação por 30 segundos")
    sub.add_parser("abrir", help="abre o HUD")
    args = parser.parse_args(argv)
    comando = args.comando or "iniciar"

    cfg = Config.carregar()
    configurar_logs(cfg.logs, cfg.log_nivel)

    if comando == "baixar":
        from .baixar_modelos import baixar_tudo

        ok = baixar_tudo(cfg.modelos, None if args.sem_whisper else cfg.whisper_modelo)
        print("\nTudo pronto!" if ok else "\nAlguns modelos falharam (veja acima).")
        return 0 if ok else 1

    if comando == "microfones":
        from .voz.audio import listar_dispositivos

        for d in listar_dispositivos():
            tipos = ("entrada " if d["entradas"] else "") + ("saída" if d["saidas"] else "")
            print(f"{d['indice']:3d}  {d['nome']}  [{tipos.strip()}]")
        print("\nUse o número ou parte do nome em MICROFONE= / ALTO_FALANTE= no arquivo .env")
        return 0

    if comando == "pin":
        from .seguranca import Acesso, ErroAcesso

        acesso = Acesso(cfg.dados / "acesso.json")
        novo = getpass.getpass("Novo PIN (4 a 8 números; vazio remove): ").strip()
        try:
            acesso.definir_pin(novo or None)
        except ErroAcesso as erro:
            print(erro)
            return 1
        print("PIN definido." if novo else "PIN removido.")
        return 0

    if comando == "dispositivos":
        from .seguranca import Acesso

        acesso = Acesso(cfg.dados / "acesso.json")
        if args.remover:
            print("Removido." if acesso.remover_dispositivo(args.remover) else "Não encontrado.")
        for d in acesso.listar_dispositivos():
            visto = time.strftime("%d/%m %H:%M", time.localtime(d.get("visto", 0)))
            print(f"{d['id']}  {d['nome']}  (visto {visto})")
        return 0

    if comando == "abrir":
        from .seguranca import Acesso
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{cfg.porta}/#t={Acesso(cfg.dados / 'acesso.json').token_pc}")
        return 0

    from .app import SextaFeira

    if comando == "testar-voz":
        app = SextaFeira(cfg, com_voz=False)
        app.fala.falar_e_esperar(" ".join(args.texto))
        app.fala.encerrar()
        return 0

    if comando == "testar-ativacao":
        from .voz.ativacao import criar_detector
        from .voz.audio import Microfone

        detector = criar_detector(cfg)
        if detector is None:
            print("Ativação por voz desligada no .env (ATIVACAO_MOTOR).")
            return 1
        mic = Microfone(cfg.microfone)
        mic.iniciar()
        print("Fale \"Sexta-Feira\"... (30 segundos)")
        fim = time.time() + 30
        while time.time() < fim:
            bloco = mic.ler(0.5)
            if bloco and detector.processar(bloco):
                print(f"  ✓ ouvi você às {time.strftime('%H:%M:%S')}")
        mic.parar()
        return 0

    app = SextaFeira(cfg)
    if comando == "diagnostico":
        from .diagnostico import verificar_tudo

        for item in verificar_tudo(app):
            marca = "ok" if item["ok"] else "!!"
            print(f"[{marca}] {item['nome']}: {item['detalhe']}" + (f"\n      → {item['dica']}" if item["dica"] else ""))
        return 0

    logging.getLogger("sexta").info("Iniciando a Sexta-Feira %s (cérebro: %s)", app.versao, cfg.modelo_principal)
    app.executar()
    return 0


if __name__ == "__main__":
    sys.exit(main())

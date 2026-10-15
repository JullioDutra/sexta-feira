"""Extensão "aprendizado": o holograma da memória, os comandos sobre o que ela aprendeu e se acertou.

O núcleo da memória e do aprendizado fica em ``sexta/cerebro/memoria.py`` e ``sexta/aprendizado.py``;
aqui ficam a tela, as rotas e os atalhos de voz.
"""

from __future__ import annotations

import asyncio
import re

HOLOGRAMAS = {"memoria": "Memória e aprendizado"}

_APRENDEU = re.compile(r"^(o que )?(voce )?(aprendeu|tem aprendido)( hoje| de novo| ultimamente)?$|"
                       r"^o que voce aprendeu( hoje| de novo| ultimamente| comigo)?$")
_SABE = re.compile(r"^o que voce sabe (sobre|de) mim$|^(mostra|abre|mostre|abra) (a |sua |a sua )?memoria$|"
                   r"^(o que (tem|esta) na|como esta a) (sua )?memoria$")
_DEU_CERTO = re.compile(r"^(e )?(deu certo|funcionou|conseguiu|voce conseguiu|deu tudo certo|foi certo|"
                        r"fez certo|ficou certo)$")
_CONSOLIDAR = re.compile(r"^(consolida|organiza|revisa) (a |sua |a sua )?memoria( agora)?$")


def dados(app) -> dict:
    from ..habilidades import _dados_memoria

    return _dados_memoria(app)


def dados_holograma(app, tipo: str) -> dict | None:
    return dados(app) if tipo == "memoria" else None


def atalho(t, ctx, rodar, original):
    app = ctx.app
    if _APRENDEU.match(t):
        return lambda: app.aprendizado.resumo_do_dia()
    if _SABE.match(t):
        def mostrar() -> str:
            app.hologramas.mostrar("memoria", dados(app))
            e = app.memoria.estatisticas()
            return (f"Sei {e['fatos']} coisas sobre você, tenho {e['licoes']} lições e {e['conhecimentos']} "
                    f"conhecimentos guardados. Está tudo na tela.")
        return mostrar
    if _DEU_CERTO.match(t):
        def conferir() -> str:
            texto, _ = app.aprendizado.o_que_fez(3)
            return texto
        return conferir
    if _CONSOLIDAR.match(t):
        def consolidar() -> str:
            novos = app.aprendizado.consolidar()
            if not novos:
                return "Memória revisada. Nada de novo para guardar."
            return f"Memória revisada: {novos.get('fato', 0)} fatos e {novos.get('licao', 0)} lições novas."
        return consolidar
    return None


def rotas(api, app, autenticado, so_pc) -> None:
    from fastapi import Depends, HTTPException, Request

    @api.get("/api/memoria")
    def memoria(_=Depends(autenticado)):
        return {**dados(app), "episodios": app.memoria.episodios(limite=30)}

    @api.post("/api/memoria")
    async def adicionar(request: Request, _=Depends(autenticado)):
        corpo = await request.json()
        tipo = str(corpo.get("tipo") or "fato")
        texto = str(corpo.get("texto") or "").strip()
        if tipo not in ("fato", "licao", "conhecimento") or not texto:
            raise HTTPException(400, "Diga o tipo e o texto.")
        app.memoria.aprender(tipo, texto, origem="usuario")
        return dados(app)

    @api.delete("/api/memoria/{item_id}")
    def remover(item_id: int, _=Depends(autenticado)):
        if app.memoria.remover(item_id) is None:
            raise HTTPException(404, "Esse item não existe mais.")
        if app.hologramas.aberto("memoria"):
            app.hologramas.atualizar_tipo("memoria", dados(app))
        return dados(app)

    @api.post("/api/memoria/consolidar")
    async def consolidar(_=Depends(so_pc)):
        novos = await asyncio.to_thread(app.aprendizado.consolidar)
        return {"novos": novos, **dados(app)}


def diagnostico(app) -> list[dict]:
    e = app.memoria.estatisticas()
    taxa = f", {round(100 * e['acertos'] / e['episodios'])}% de acertos" if e["episodios"] else ""
    return [{"nome": "Memória", "ok": True,
             "detalhe": f"{e['fatos']} fatos, {e['licoes']} lições, {e['conhecimentos']} conhecimentos, "
                        f"{e['episodios']} pedidos registrados{taxa}" + ("" if app.memoria.fts else " (busca simples: SQLite sem FTS5)"),
             "dica": ""}]

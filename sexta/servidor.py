"""Servidor web: API + WebSocket + HUD.

- ``http://127.0.0.1:PORTA``      → HUD do próprio PC (só aceita conexões locais).
- ``https://IP-DO-PC:PORTA_CELULAR`` → celular na mesma rede (HTTPS para liberar o microfone).

Toda chamada precisa de token (ver ``seguranca.py``) e o cabeçalho Host é
conferido, o que bloqueia ataques de "DNS rebinding" vindos de sites maliciosos.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import signal
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .certificado import garantir_certificado
from .seguranca import Cliente, ErroAcesso
from .util.rede import ips_locais, nome_do_computador

log = logging.getLogger(__name__)

PRINT_VALIDO = re.compile(r"^print_[\w\-]+\.png$")


class VerificadorHosts:
    """Decide se um nome de host é deste PC (local, rede de casa ou Tailscale)."""

    def __init__(self, extras: list[str]) -> None:
        self.extras = {e.lower() for e in extras if e}
        self._permitidos: set[str] = set()
        self._atualizado = 0.0

    def permitidos(self) -> set[str]:
        if time.monotonic() - self._atualizado > 60:
            nome = nome_do_computador().lower()
            self._permitidos = {"127.0.0.1", "localhost", "[::1]", nome, f"{nome}.local", *ips_locais(), *self.extras}
            self._atualizado = time.monotonic()
        return self._permitidos

    def host_ok(self, host: str) -> bool:
        host = host.lower().strip()
        if host.startswith("["):
            host = host.split("]")[0] + "]"
        else:
            host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        return host in self.permitidos() or host.endswith(".ts.net")


class HostsPermitidos:
    """Middleware ASGI: só aceita Host local/LAN/Tailscale (contra DNS rebinding)."""

    def __init__(self, asgi_app, verificador: VerificadorHosts | list[str]) -> None:
        self.app = asgi_app
        self.verificador = verificador if isinstance(verificador, VerificadorHosts) else VerificadorHosts(verificador)

    def host_ok(self, host: str) -> bool:
        return self.verificador.host_ok(host)

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            cabecalhos = dict(scope.get("headers") or [])
            host = cabecalhos.get(b"host", b"").decode("latin-1")
            if not self.host_ok(host):
                if scope["type"] == "http":
                    await Response("Host não permitido", status_code=400)(scope, receive, send)
                else:
                    await send({"type": "websocket.close", "code": 4403})
                return
        await self.app(scope, receive, send)


def criar_api(app, verificador: VerificadorHosts | None = None) -> Any:
    api = FastAPI(title="Sexta-Feira", version=app.versao, docs_url=None, redoc_url=None, openapi_url=None)
    verificador = verificador or VerificadorHosts(app.cfg.hosts_extras)
    audios: dict[str, tuple[bytes, str, float]] = {}
    tentativas_pareamento: dict[str, list[float]] = {}

    # -------------------------------------------------------------- autenticação
    def token_da_requisicao(request: Request) -> str | None:
        cabecalho = request.headers.get("authorization", "")
        if cabecalho.lower().startswith("bearer "):
            return cabecalho[7:].strip()
        return request.query_params.get("token")

    def autenticado(request: Request) -> Cliente:
        cliente = app.acesso.autenticar(token_da_requisicao(request))
        if cliente is None:
            raise HTTPException(401, "Token inválido ou ausente. Abra o HUD pelo atalho da Sexta-Feira ou pareie o celular.")
        return cliente

    def so_pc(cliente: Cliente = Depends(autenticado)) -> Cliente:
        if cliente.tipo != "pc":
            raise HTTPException(403, "Essa ação só pode ser feita no HUD do computador.")
        return cliente

    def foto(cliente: Cliente) -> dict[str, Any]:
        rotinas = [r.para_dict() for r in app.rotinas.listar()]
        return {
            "tipo": "ola",
            "versao": app.versao,
            "cliente": {"tipo": cliente.tipo, "nome": cliente.nome},
            "status": app.estado.status(),
            "bloqueio": app.sessao.estado(),
            "preferencias": app.prefs.tudo(),
            "hologramas": app.hologramas.lista(),
            "lembretes": app.lembretes.listar(),
            "rotinas": rotinas,
            "rosto": app.rosto.info(),
            "maos_disponivel": app.maos.disponivel(),
            "pin": app.acesso.tem_pin(),
            "modelo": app.cfg.ollama_modelo,
            "alarme": app.lembretes.alarme_ativo(),
        }

    # -------------------------------------------------------------- básicos
    @api.get("/api/saude")
    def saude():
        return {"ok": True, "nome": "Sexta-Feira", "versao": app.versao}

    @api.get("/api/estado")
    def estado(cliente: Cliente = Depends(autenticado)):
        return foto(cliente)

    @api.patch("/api/preferencias")
    async def preferencias(request: Request, _: Cliente = Depends(so_pc)):
        valores = await request.json()
        if not isinstance(valores, dict):
            raise HTTPException(400, "JSON inválido")
        cidade = valores.pop("cidade", None)
        cidade = str(cidade).strip() if cidade is not None else ""
        if cidade and cidade not in (app.prefs.get("cidade"), app.prefs.get("cidade_rotulo")):
            from .habilidades.clima import ErroClima

            try:
                local = await asyncio.to_thread(app.clima.localizar, cidade)
            except ErroClima as erro:
                raise HTTPException(400, str(erro)) from erro
            app.definir_cidade(local)
        app.prefs.atualizar(valores)
        app.barramento.publicar("preferencias", preferencias=app.prefs.tudo())
        if "bloqueio_facial" in valores:
            app.sessao.publicar()
        return app.prefs.tudo()

    # -------------------------------------------------------------- conversa
    @api.post("/api/conversa")
    async def conversa(request: Request, cliente: Cliente = Depends(autenticado)):
        corpo = await request.json()
        texto = str(corpo.get("texto", "")).strip()[:2000]
        if not texto:
            raise HTTPException(400, "Mensagem vazia")
        if cliente.tipo == "pc" and app.sessao.bloqueada:
            raise HTTPException(423, "A Sexta-Feira está bloqueada. Olhe para a câmera ou use o PIN.")
        canal = "celular" if cliente.tipo == "celular" else "texto"
        falar_no_pc = bool(corpo.get("falar_no_pc", cliente.tipo == "pc"))
        resposta = await asyncio.to_thread(app.agente.processar, texto, canal, cliente, falar_no_pc)
        return await _com_audio(resposta, bool(corpo.get("audio")))

    async def _com_audio(resposta: dict, quer_audio: bool) -> dict:
        saida = {"texto": resposta["texto"], "id": resposta["id"],
                 "ferramentas": [r["ferramenta"] for r in resposta["resultados"]]}
        if quer_audio and resposta["texto"]:
            gerado = await asyncio.to_thread(app.fala.gerar_audio, resposta["texto"])
            if gerado:
                agora = time.time()
                for chave in [k for k, v in audios.items() if agora - v[2] > 600]:
                    audios.pop(chave, None)
                id_audio = uuid.uuid4().hex
                audios[id_audio] = (gerado[0], gerado[1], agora)
                saida["audio"] = f"/api/audio/{id_audio}"
        return saida

    @api.post("/api/voz")
    async def voz(audio: UploadFile = File(...), resposta_em_audio: bool = True,
                  cliente: Cliente = Depends(autenticado)):
        from .voz.audio import decodificar
        from .util.texto import remover_ativacao

        dados = await audio.read()
        if len(dados) > 20 * 1024 * 1024:
            raise HTTPException(413, "Áudio grande demais")
        try:
            amostras, _ = await asyncio.to_thread(decodificar, dados, 16000)
        except Exception as erro:  # noqa: BLE001
            raise HTTPException(400, f"Não consegui ler o áudio: {erro}") from erro
        texto = await asyncio.to_thread(app.transcritor.transcrever, amostras)
        texto = remover_ativacao(texto)
        if not texto:
            return {"transcricao": "", "texto": "Não entendi. Pode repetir?", "id": 0}
        canal = "celular" if cliente.tipo == "celular" else "texto"
        resposta = await asyncio.to_thread(app.agente.processar, texto, canal, cliente, cliente.tipo == "pc")
        saida = await _com_audio(resposta, resposta_em_audio and cliente.tipo == "celular")
        saida["transcricao"] = texto
        return saida

    @api.get("/api/audio/{id_audio}")
    def audio_gerado(id_audio: str, _: Cliente = Depends(autenticado)):
        item = audios.get(id_audio)
        if not item:
            raise HTTPException(404, "Áudio expirado")
        return Response(item[0], media_type=item[1], headers={"Cache-Control": "no-store"})

    @api.post("/api/ouvir")
    def ouvir(_: Cliente = Depends(so_pc)):
        if app.sessao.bloqueada and not app.sessao.protecao_ativa():
            app.sessao.desbloquear("sem_protecao")
        app.voz.ativar()
        return {"ok": True}

    @api.post("/api/parar")
    def parar(_: Cliente = Depends(autenticado)):
        app.lembretes.parar_alarme()
        app.agente.cancelar()
        app.fala.parar()
        return {"ok": True}

    @api.post("/api/microfone")
    async def microfone(request: Request, _: Cliente = Depends(autenticado)):
        ligado = bool((await request.json()).get("ligado", True))
        app.estado.definir_microfone(ligado)
        return {"ligado": ligado}

    # -------------------------------------------------------------- câmera e rosto
    @api.get("/api/camera.mjpg")
    async def camera(request: Request, _: Cliente = Depends(autenticado)):
        from .visao.previa import quadro_jpeg

        nome = f"previa-{uuid.uuid4().hex[:6]}"

        async def gerar():
            app.camera.adquirir(nome)
            seq = 0
            try:
                while not await request.is_disconnected():
                    quadro, seq = await asyncio.to_thread(app.camera.esperar_quadro, seq, 2.0)
                    if quadro is None:
                        if app.camera.erro:
                            break
                        continue
                    jpg = await asyncio.to_thread(quadro_jpeg, app, quadro)
                    yield b"--quadro\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
                    await asyncio.sleep(0.06)
            finally:
                app.camera.liberar(nome)

        return StreamingResponse(gerar(), media_type="multipart/x-mixed-replace; boundary=quadro",
                                 headers={"Cache-Control": "no-store"})

    @api.post("/api/rosto/cadastrar")
    def rosto_cadastrar(_: Cliente = Depends(so_pc)):
        if not app.rosto.modelos_presentes():
            raise HTTPException(409, "Modelos de rosto ausentes. Rode: python -m sexta baixar")

        def progresso(info: dict) -> None:
            app.barramento.publicar("cadastro", **info)
            if info.get("fase") == "concluido":
                app.sessao.desbloquear("cadastro")
                app.fala.falar("Rosto cadastrado. A partir de agora eu reconheço você.")

        threading.Thread(target=app.rosto.cadastrar, args=(progresso,), daemon=True).start()
        return {"ok": True}

    @api.post("/api/rosto/cancelar")
    def rosto_cancelar(_: Cliente = Depends(autenticado)):
        app.rosto.cancelar_evento.set()
        return {"ok": True}

    @api.delete("/api/rosto")
    def rosto_apagar(_: Cliente = Depends(so_pc)):
        app.rosto.apagar()
        app.sessao.desbloquear("cadastro_apagado")
        return app.rosto.info()

    @api.post("/api/desbloquear")
    async def desbloquear(request: Request, cliente: Cliente = Depends(autenticado)):
        corpo = await request.json()
        if corpo.get("metodo") == "pin":
            try:
                ok = await asyncio.to_thread(app.desbloquear_por_pin, str(corpo.get("pin", "")))
            except ErroAcesso as erro:
                raise HTTPException(429, str(erro)) from erro
            if not ok:
                raise HTTPException(403, "PIN incorreto" if app.acesso.tem_pin() else "Nenhum PIN definido")
            return app.sessao.estado()
        if cliente.tipo != "pc":
            raise HTTPException(403, "Pelo celular, desbloqueie com o PIN.")
        threading.Thread(target=app.desbloquear_por_rosto, daemon=True).start()
        return {"ok": True}

    @api.post("/api/bloquear")
    def bloquear(_: Cliente = Depends(autenticado)):
        app.sessao.bloquear("pedido")
        return app.sessao.estado()

    @api.post("/api/pin")
    async def definir_pin(request: Request, _: Cliente = Depends(so_pc)):
        corpo = await request.json()
        if app.acesso.tem_pin():
            try:
                if not app.acesso.verificar_pin(str(corpo.get("pin_atual", ""))):
                    raise HTTPException(403, "PIN atual incorreto")
            except ErroAcesso as erro:
                raise HTTPException(429, str(erro)) from erro
        try:
            app.acesso.definir_pin(corpo.get("pin") or None)
        except ErroAcesso as erro:
            raise HTTPException(400, str(erro)) from erro
        app.barramento.publicar("acesso", pin=app.acesso.tem_pin())
        return {"pin": app.acesso.tem_pin()}

    # -------------------------------------------------------------- pareamento do celular
    @api.post("/api/pareamento")
    def pareamento(_: Cliente = Depends(so_pc)):
        import segno

        info = app.acesso.iniciar_pareamento()
        enderecos = []
        if app.cfg.endereco_externo:
            enderecos.append({"rotulo": "De qualquer lugar (Tailscale)", "url": f"{app.cfg.endereco_externo}/m?pareamento={info['codigo']}"})
        if app.cfg.liberar_rede:
            for ip in ips_locais():
                enderecos.append({"rotulo": f"Wi-Fi de casa ({ip})", "url": f"https://{ip}:{app.cfg.porta_https}/m?pareamento={info['codigo']}"})
        for e in enderecos:
            e["qr"] = segno.make(e["url"], error="m").svg_inline(scale=5, dark="#ffb547", light=None, border=2)
        return {"codigo": info["codigo"], "expira_em": info["expira_em"], "enderecos": enderecos}

    @api.post("/api/pareamento/concluir")
    async def concluir_pareamento(request: Request):
        ip = request.client.host if request.client else "?"
        agora = time.time()
        historico = [t for t in tentativas_pareamento.get(ip, []) if agora - t < 60]
        if len(historico) >= 10:
            raise HTTPException(429, "Muitas tentativas. Espere um minuto.")
        tentativas_pareamento[ip] = historico + [agora]
        corpo = await request.json()
        try:
            token, cliente = app.acesso.concluir_pareamento(str(corpo.get("codigo", "")), str(corpo.get("nome", "Celular")))
        except ErroAcesso as erro:
            raise HTTPException(403, str(erro)) from erro
        app.barramento.publicar("pareado", nome=cliente.nome, para="pc")
        app.fala.falar(f"Celular {cliente.nome} pareado.")
        return {"token": token, "nome": cliente.nome}

    @api.get("/api/dispositivos")
    def dispositivos(_: Cliente = Depends(so_pc)):
        return app.acesso.listar_dispositivos()

    @api.delete("/api/dispositivos/{id_}")
    def remover_dispositivo(id_: str, _: Cliente = Depends(so_pc)):
        if not app.acesso.remover_dispositivo(id_):
            raise HTTPException(404, "Dispositivo não encontrado")
        return app.acesso.listar_dispositivos()

    # -------------------------------------------------------------- hologramas, lembretes, rotinas
    @api.post("/api/hologramas")
    async def abrir_holograma(request: Request, cliente: Cliente = Depends(autenticado)):
        tipo = str((await request.json()).get("tipo", ""))
        ctx = app.contexto("texto", cliente)
        resultado = await asyncio.to_thread(app.registro.executar, "holograma", {"acao": "mostrar", "tipo": tipo}, ctx)
        if not resultado.get("ok"):
            raise HTTPException(400, resultado.get("resumo"))
        return resultado

    @api.delete("/api/hologramas/{id_}")
    def fechar_holograma(id_: str, _: Cliente = Depends(autenticado)):
        app.hologramas.fechar(id_=id_)
        return {"ok": True}

    @api.delete("/api/hologramas")
    def fechar_hologramas(_: Cliente = Depends(autenticado)):
        return {"fechados": app.hologramas.fechar_todos()}

    @api.post("/api/maos")
    async def maos(request: Request, _: Cliente = Depends(so_pc)):
        ligar = bool((await request.json()).get("ligar"))
        app.maos_para_hud(ligar)
        return {"ligado": app.maos.ligado()}

    @api.get("/api/lembretes")
    def lembretes(_: Cliente = Depends(autenticado)):
        return app.lembretes.listar()

    @api.delete("/api/lembretes/{id_}")
    def cancelar_lembrete(id_: int, _: Cliente = Depends(autenticado)):
        app.lembretes.cancelar(id_)
        return app.lembretes.listar()

    @api.get("/api/rotinas")
    def rotinas(_: Cliente = Depends(autenticado)):
        return [r.para_dict() for r in app.rotinas.listar()]

    @api.post("/api/rotinas/{nome}/executar")
    async def executar_rotina(nome: str, cliente: Cliente = Depends(autenticado)):
        ctx = app.contexto("texto", cliente)
        resultado = await asyncio.to_thread(app.registro.executar, "rotina", {"acao": "executar", "nome": nome}, ctx)
        if not resultado.get("ok"):
            raise HTTPException(404, resultado.get("resumo"))
        return resultado

    # -------------------------------------------------------------- protocolos (editor visual)
    @api.get("/api/protocolos")
    def protocolos(_: Cliente = Depends(autenticado)):
        from .habilidades.rotinas import CATALOGO

        return {"protocolos": [r.para_editor() for r in app.rotinas.listar()], "catalogo": CATALOGO,
                "layouts": app.layouts.nomes()}

    @api.put("/api/protocolos")
    async def salvar_protocolo(request: Request, _: Cliente = Depends(so_pc)):
        dados = await request.json()
        try:
            rotina = await asyncio.to_thread(app.rotinas.salvar_do_editor, dados, dados.get("nome_antigo") or None)
        except ValueError as erro:
            raise HTTPException(400, str(erro)) from None
        app.atividades.anotar({"ferramenta": "editor_protocolos", "argumentos": {"nome": rotina.nome}, "nivel": 1,
                               "situacao": "ok", "resumo": f"Protocolo {rotina.nome} salvo no editor.", "canal": "texto"})
        return rotina.para_editor()

    @api.post("/api/protocolos/{nome}/ativo")
    async def ativar_protocolo(nome: str, request: Request, _: Cliente = Depends(so_pc)):
        ativo = bool((await request.json()).get("ativo"))
        if not await asyncio.to_thread(app.rotinas.definir_ativo, nome, ativo):
            raise HTTPException(404, "Protocolo não encontrado.")
        return {"ok": True}

    @api.delete("/api/protocolos/{nome}")
    async def apagar_protocolo(nome: str, _: Cliente = Depends(so_pc)):
        if not await asyncio.to_thread(app.rotinas.apagar, nome):
            raise HTTPException(400, "Só dá para apagar protocolos criados por voz ou no editor. "
                                     "Os outros ficam em config/rotinas.yaml.")
        return {"ok": True}

    @api.post("/api/pendente")
    async def responder_pendente(request: Request, cliente: Cliente = Depends(autenticado)):
        """Botões Aprovar/Cancelar dos hologramas (mesmo efeito de dizer "sim" ou "não")."""
        aprovar = bool((await request.json()).get("aprovar"))
        if app.registro.pendente() is None:
            raise HTTPException(404, "Não há nada esperando confirmação.")
        if not aprovar:
            pendente = app.registro.cancelar_pendente()
            if pendente and pendente.nome == "criar_protocolo":
                app.hologramas.fechar(tipo="protocolo")
            return {"texto": "Cancelado."}
        ctx = app.contexto("texto" if cliente.tipo == "pc" else "celular", cliente)
        resultado = await asyncio.to_thread(app.registro.confirmar, ctx, app.verificar_para_acao)
        app.barramento.publicar("aviso", nivel="sucesso" if resultado.get("ok") else "erro", texto=resultado["resumo"])
        return {"texto": resultado["resumo"], "ok": resultado.get("ok")}

    @api.post("/api/rotinas/recarregar")
    def recarregar_rotinas(_: Cliente = Depends(so_pc)):
        app.rotinas.recarregar()
        app.apps.recarregar()
        app.layouts.recarregar()
        app.terminal.recarregar()
        return [r.para_dict() for r in app.rotinas.listar()]

    @api.get("/api/prints/{nome}")
    def prints(nome: str, _: Cliente = Depends(autenticado)):
        if not PRINT_VALIDO.match(nome):
            raise HTTPException(400, "Nome inválido")
        arquivo = app.pasta_prints() / nome
        if not arquivo.is_file():
            raise HTTPException(404, "Print não encontrado")
        return FileResponse(arquivo, media_type="image/png")

    @api.get("/api/diagnostico")
    async def diagnostico(_: Cliente = Depends(so_pc)):
        from .diagnostico import verificar_tudo

        return await asyncio.to_thread(verificar_tudo, app)

    # -------------------------------------------------------------- WebSocket
    @api.websocket("/ws")
    async def ws(websocket: WebSocket):
        cliente = app.acesso.autenticar(websocket.query_params.get("token"))
        origem = websocket.headers.get("origin")
        # a página precisa ter sido aberta a partir deste PC (bloqueia sites de terceiros)
        if cliente is None or (origem and not verificador.host_ok(urlparse(origem).netloc)):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        if app.barramento._loop is None:  # quando rodando fora de servir() (ex.: testes)
            app.barramento.anexar_loop(asyncio.get_running_loop())
        await websocket.send_json(foto(cliente))
        registrado = app.barramento.novo_cliente(cliente.tipo, cliente.nome, websocket.send_json)
        envio = asyncio.create_task(registrado.loop_envio())
        try:
            while True:
                mensagem = await websocket.receive_json()
                tipo = mensagem.get("tipo")
                if tipo == "maos" and cliente.tipo == "pc":
                    registrado.quer_maos = bool(mensagem.get("ligar"))
                    if registrado.quer_maos:
                        await asyncio.to_thread(app.maos.ligar)
                    elif not app.barramento.alguem_quer_maos():
                        app.maos.desligar()
                elif tipo == "ouvir" and cliente.tipo == "pc":
                    app.voz.ativar()
                elif tipo == "parar":
                    app.lembretes.parar_alarme()
                    app.agente.cancelar()
                elif tipo == "ping":
                    await websocket.send_json({"tipo": "pong", "t": mensagem.get("t")})
        except (WebSocketDisconnect, RuntimeError):
            pass
        except Exception:  # noqa: BLE001
            log.exception("Erro no WebSocket")
        finally:
            app.barramento.remover_cliente(registrado)
            envio.cancel()
            if registrado.quer_maos and not app.barramento.alguem_quer_maos():
                app.maos.desligar()

    # -------------------------------------------------------------- HUD (arquivos estáticos)
    dist: Path = app.cfg.hud_dist
    if (dist / "assets").is_dir():
        api.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @api.get("/{caminho:path}", include_in_schema=False)
    def hud(caminho: str):
        if caminho.startswith("api/"):
            raise HTTPException(404)
        arquivo = (dist / caminho).resolve()
        if caminho and arquivo.is_file() and dist.resolve() in arquivo.parents:
            return FileResponse(arquivo)
        indice = dist / "index.html"
        if indice.exists():
            return FileResponse(indice, headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<h1>HUD não compilado</h1><p>Rode <code>npm install</code> e <code>npm run build</code> na pasta hud.</p>")

    @api.exception_handler(HTTPException)
    async def erro_http(_request: Request, erro: HTTPException):
        return JSONResponse({"erro": erro.detail}, status_code=erro.status_code)

    return api


class _ServidorSemSinais:
    """Envolve um uvicorn.Server sem instalar tratadores de sinal (tratamos nós mesmos)."""

    def __init__(self, config) -> None:
        import uvicorn

        class Servidor(uvicorn.Server):
            @contextlib.contextmanager
            def capture_signals(self):  # noqa: D401
                yield

        self.servidor = Servidor(config)

    @property
    def should_exit(self) -> bool:
        return self.servidor.should_exit

    @should_exit.setter
    def should_exit(self, valor: bool) -> None:
        self.servidor.should_exit = valor

    async def serve(self) -> None:
        await self.servidor.serve()


def porta_ocupada(porta: int) -> bool:
    """Verdadeiro se já existe algum programa escutando nesta porta."""
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=0.5):
            return True
    except OSError:
        return False


def outra_sexta_aberta(porta: int) -> bool:
    try:
        import httpx

        return httpx.get(f"http://127.0.0.1:{porta}/api/saude", timeout=1.5).json().get("nome") == "Sexta-Feira"
    except Exception:  # noqa: BLE001
        return False


async def servir(app) -> None:
    import uvicorn

    cfg = app.cfg
    app.barramento.anexar_loop(asyncio.get_running_loop())
    verificador = VerificadorHosts(cfg.hosts_extras + ([urlparse(cfg.endereco_externo).hostname or ""]
                                                       if cfg.endereco_externo else []))
    api = HostsPermitidos(criar_api(app, verificador), verificador)

    comum = {"log_level": "warning", "proxy_headers": False, "server_header": False, "ws_ping_interval": 20,
             "timeout_graceful_shutdown": 3}
    servidores = [_ServidorSemSinais(uvicorn.Config(api, host="127.0.0.1", port=cfg.porta, **comum))]
    if cfg.liberar_rede:
        ips = ips_locais()
        nome = nome_do_computador()
        cert, chave = garantir_certificado(cfg.dados / "certificados", ips, [nome, f"{nome}.local"])
        if not porta_ocupada(cfg.porta_https):
            servidores.append(_ServidorSemSinais(uvicorn.Config(
                api, host="0.0.0.0", port=cfg.porta_https, ssl_certfile=str(cert), ssl_keyfile=str(chave), **comum)))
            for ip in ips:
                log.info("Celular (mesma rede): https://%s:%s/m", ip, cfg.porta_https)
        else:
            log.warning("Porta %s ocupada: acesso pelo celular desligado", cfg.porta_https)
    log.info("HUD: %s", app.endereco_hud)
    app.servidores = servidores

    def sair(*_args) -> None:
        for s in servidores:
            if s.should_exit:
                s.servidor.force_exit = True
            s.should_exit = True

    with contextlib.suppress(ValueError):  # só funciona na thread principal
        signal.signal(signal.SIGINT, sair)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, sair)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, sair)  # Ctrl+Break / fechar a janela no Windows
    await asyncio.gather(*(s.serve() for s in servidores))

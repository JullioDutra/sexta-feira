"""Cliente MCP genérico: servidores MCP (stdio) viram ferramentas dos agentes.

Os servidores ficam em ``config/mcp.yaml``. Cada um só é iniciado quando um agente precisa dele
(preguiçoso) e fica de pé até a Sexta-Feira fechar. As ferramentas aparecem para os agentes com o
prefixo do servidor: ``rea__analyze_binary``, ``chrome-devtools__navigate_page``.

O pacote ``mcp`` é assíncrono; aqui tudo roda num loop asyncio próprio, numa thread separada, e a
interface para o resto da Sexta-Feira é síncrona (com tempo-limite em cada chamada).
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

LIVRE, CONFIRMAR = 1, 2  # mesmos valores de cerebro.ferramentas
INICIAR_S = 90.0         # npx pode baixar o pacote na primeira vez
CHAMADA_S = 120.0
MAX_RESULTADO = 12_000   # caracteres de cada resultado que voltam para o modelo
SEPARADOR = "__"

MODELO_YAML = """\
# Servidores MCP que os agentes da Sexta-Feira podem usar (https://modelcontextprotocol.io).
# Cada servidor vira um conjunto de ferramentas com o prefixo do nome: rea__..., chrome-devtools__...
# Eles só são iniciados quando um agente precisa e são encerrados quando a Sexta-Feira fecha.
#
# Campos de cada servidor:
#   comando:     programa a rodar (no Windows, "npx" é chamado por "cmd.exe /d /c npx ..." sozinho)
#   args:        argumentos
#   habilitado:  auto (liga se o comando existir neste PC), true ou false
#   nivel:       livre ou confirmar — segurança padrão das ferramentas deste servidor
#   livres:      ferramentas que rodam sem perguntar mesmo com nivel: confirmar (aceita * no nome)
#   confirmar:   ferramentas que sempre pedem a sua aprovação (aceita * no nome)
#   timeout:     segundos por chamada (padrão 120)
#   env:         variáveis de ambiente extras
#
# Ferramentas que o próprio servidor marca como só-leitura rodam direto; as marcadas como destrutivas
# sempre pedem aprovação. Para adicionar outro servidor, copie um bloco abaixo.

servidores:
  # REA — engenharia reversa (binários, Electron/JS, .NET, APK, sites). https://github.com/morluto/rea
  # Requer Node.js 20+. A primeira execução baixa o pacote. Ghidra/JDK são opcionais (veja o README do REA).
  rea:
    comando: npx
    args: ["-y", "rea-agents@latest", "mcp"]
    habilitado: auto
    nivel: confirmar
    timeout: 600

  # Chrome DevTools MCP — controla um Chrome de verdade (navegar, clicar, ler a página, rede, desempenho).
  # https://github.com/ChromeDevTools/chrome-devtools-mcp  (requer Node.js 20+ e o Google Chrome)
  chrome-devtools:
    comando: npx
    args: ["-y", "chrome-devtools-mcp@latest", "--isolated"]
    habilitado: auto
    nivel: livre
    confirmar: ["evaluate_script", "upload_file"]
"""


class ErroMCP(Exception):
    """Problema com mensagem pronta para o usuário."""


@dataclass
class FerramentaMCP:
    servidor: str
    nome: str               # nome original no servidor
    descricao: str
    esquema: dict[str, Any]
    nivel: int = LIVRE

    @property
    def nome_completo(self) -> str:
        return f"{self.servidor}{SEPARADOR}{self.nome}"


def _casa(nome: str, padroes: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(nome, p) for p in padroes)


def _lista(valor) -> list[str]:
    if isinstance(valor, str):
        return [valor]
    return [str(v) for v in valor or [] if v]


@dataclass
class ConfigServidor:
    nome: str
    comando: str
    args: list[str] = field(default_factory=list)
    habilitado: str | bool = "auto"
    nivel: str = "confirmar"
    livres: list[str] = field(default_factory=list)
    confirmar: list[str] = field(default_factory=list)
    timeout: float = CHAMADA_S
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    @classmethod
    def de_dict(cls, nome: str, dados: dict) -> "ConfigServidor":
        if not isinstance(dados, dict) or not dados.get("comando"):
            raise ValueError(f"servidor MCP {nome} sem comando")
        try:
            timeout = float(dados.get("timeout") or CHAMADA_S)
        except (TypeError, ValueError):
            timeout = CHAMADA_S
        env = dados.get("env") if isinstance(dados.get("env"), dict) else {}
        return cls(nome=str(nome), comando=str(dados["comando"]), args=_lista(dados.get("args")),
                   habilitado=dados.get("habilitado", "auto"), nivel=str(dados.get("nivel") or "confirmar").lower(),
                   livres=_lista(dados.get("livres")), confirmar=_lista(dados.get("confirmar")),
                   timeout=max(5.0, timeout), env={str(k): str(v) for k, v in env.items()},
                   cwd=str(dados["cwd"]) if dados.get("cwd") else None)

    def comando_existe(self) -> bool:
        return shutil.which(self.comando) is not None

    def ativo(self) -> bool:
        if isinstance(self.habilitado, bool):
            return self.habilitado and self.comando_existe()
        if str(self.habilitado).lower() in ("false", "nao", "não", "0", "off"):
            return False
        return self.comando_existe()

    def linha_de_comando(self) -> tuple[str, list[str]]:
        """No Windows, ``npx``/``npm`` são scripts .cmd: precisam do cmd.exe para rodar como servidor stdio."""
        if os.name == "nt" and Path(self.comando).stem.lower() in ("npx", "npm", "pnpm", "yarn", "bunx"):
            return "cmd.exe", ["/d", "/c", self.comando, *self.args]
        return self.comando, list(self.args)

    def nivel_de(self, nome: str, anotacoes: Any = None) -> int:
        if _casa(nome, self.confirmar):
            return CONFIRMAR
        if anotacoes is not None and getattr(anotacoes, "destructive_hint", None) is True \
                and not getattr(anotacoes, "read_only_hint", None):
            return CONFIRMAR
        if _casa(nome, self.livres):
            return LIVRE
        if anotacoes is not None and getattr(anotacoes, "read_only_hint", None) is True:
            return LIVRE
        return CONFIRMAR if self.nivel.startswith("confirm") else LIVRE


def _conectar_stdio(cfg: ConfigServidor, arquivo_log: Path | None):
    """Abre o servidor por stdio e devolve a sessão MCP inicializada (gerenciador de contexto assíncrono)."""

    @contextlib.asynccontextmanager
    async def conectar():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        comando, args = cfg.linha_de_comando()
        parametros = StdioServerParameters(command=comando, args=args, env=cfg.env or None, cwd=cfg.cwd)
        erros = open(arquivo_log, "a", encoding="utf-8") if arquivo_log else open(os.devnull, "w")  # noqa: SIM115
        try:
            async with stdio_client(parametros, errlog=erros) as (leitura, escrita):
                async with ClientSession(leitura, escrita) as sessao:
                    await sessao.initialize()
                    yield sessao
        finally:
            erros.close()

    return conectar


def _texto_do_resultado(resultado: Any) -> tuple[bool, str]:
    partes: list[str] = []
    for bloco in getattr(resultado, "content", None) or []:
        tipo = getattr(bloco, "type", "")
        if tipo == "text":
            partes.append(getattr(bloco, "text", ""))
        elif tipo == "image":
            partes.append("[imagem]")
        elif tipo == "resource":
            recurso = getattr(bloco, "resource", None)
            partes.append(getattr(recurso, "text", None) or f"[recurso {getattr(recurso, 'uri', '')}]")
        else:
            partes.append(f"[{tipo or 'conteúdo'}]")
    estruturado = getattr(resultado, "structured_content", None)
    if not any(p.strip() for p in partes) and estruturado is not None:
        partes.append(json.dumps(estruturado, ensure_ascii=False, default=str))
    texto = "\n".join(p for p in partes if p).strip()
    if len(texto) > MAX_RESULTADO:
        texto = texto[:MAX_RESULTADO] + f"\n[… cortado: {len(texto) - MAX_RESULTADO} caracteres a mais]"
    return not bool(getattr(resultado, "is_error", False)), texto or "(sem conteúdo)"


class ServidorMCP:
    """Um servidor MCP: abre na primeira necessidade, guarda a lista de ferramentas e atende chamadas."""

    def __init__(self, cfg: ConfigServidor, cliente: "ClienteMCP", conectar: Callable | None = None) -> None:
        self.cfg = cfg
        self.nome = cfg.nome
        self._cliente = cliente
        self._conectar = conectar
        self._sessao: Any = None
        self._tarefa: Any = None
        self._parar: asyncio.Event | None = None
        self._lock = threading.Lock()
        self.ferramentas: list[FerramentaMCP] = []
        self.erro = ""
        self.iniciado_em = 0.0

    @property
    def rodando(self) -> bool:
        return self._sessao is not None

    def estado(self) -> dict:
        return {"nome": self.nome, "comando": " ".join([self.cfg.comando, *self.cfg.args]),
                "habilitado": self.cfg.ativo(), "comando_existe": self.cfg.comando_existe(),
                "rodando": self.rodando, "ferramentas": len(self.ferramentas), "erro": self.erro}

    def garantir(self) -> None:
        """Inicia o servidor (se ainda não está de pé) e carrega as ferramentas."""
        with self._lock:
            if self._sessao is not None:
                return
            if not self.cfg.ativo():
                if not self.cfg.comando_existe():
                    raise ErroMCP(f"O servidor MCP {self.nome} precisa do comando {self.cfg.comando}, que não está "
                                  "instalado. Instale o Node.js (nodejs.org) e tente de novo.")
                raise ErroMCP(f"O servidor MCP {self.nome} está desligado em config/mcp.yaml.")
            conectar = self._conectar or _conectar_stdio(self.cfg, self._cliente.arquivo_log(self.nome))
            pronto: asyncio.Future = self._cliente.loop_futuro()
            futuro = self._cliente.agendar(self._manter(conectar, pronto))
            try:
                self._cliente.esperar(pronto, INICIAR_S)
            except Exception as erro:  # noqa: BLE001
                futuro.cancel()
                self.erro = _mensagem_erro(erro)
                log.warning("Servidor MCP %s não iniciou: %s", self.nome, self.erro)
                raise ErroMCP(f"O servidor MCP {self.nome} não iniciou: {self.erro}") from None
            self._tarefa = futuro
            try:
                resultado = self._cliente.rodar(self._sessao.list_tools(), self.cfg.timeout)
            except Exception as erro:  # noqa: BLE001
                self.erro = _mensagem_erro(erro)
                self._parar_agora()
                raise ErroMCP(f"O servidor MCP {self.nome} não listou as ferramentas: {self.erro}") from None
            self.ferramentas = [
                FerramentaMCP(self.nome, t.name, (t.description or "").strip()[:1000],
                              getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)
                              or {"type": "object", "properties": {}},
                              self.cfg.nivel_de(t.name, getattr(t, "annotations", None)))
                for t in getattr(resultado, "tools", []) or []
            ]
            self.erro = ""
            self.iniciado_em = time.time()
            log.info("Servidor MCP %s pronto com %d ferramentas", self.nome, len(self.ferramentas))

    async def _manter(self, conectar, pronto: asyncio.Future) -> None:
        self._parar = asyncio.Event()
        try:
            async with conectar() as sessao:
                self._sessao = sessao
                if not pronto.done():
                    pronto.set_result(True)
                await self._parar.wait()
        except BaseException as erro:  # noqa: BLE001 - inclusive cancelamento: a sessão acabou
            if not pronto.done():
                pronto.set_exception(erro if isinstance(erro, Exception) else ErroMCP("cancelado"))
            elif not isinstance(erro, asyncio.CancelledError):
                self.erro = _mensagem_erro(erro)
                log.warning("Servidor MCP %s caiu: %s", self.nome, self.erro)
            if isinstance(erro, asyncio.CancelledError):
                raise
        finally:
            self._sessao = None

    def chamar(self, nome: str, argumentos: dict, timeout: float | None = None) -> dict:
        self.garantir()
        sessao = self._sessao
        if sessao is None:
            raise ErroMCP(f"O servidor MCP {self.nome} não está rodando.")
        limite = min(timeout or self.cfg.timeout, self.cfg.timeout)
        try:
            resultado = self._cliente.rodar(sessao.call_tool(nome, argumentos or {}), limite)
        except TimeoutError:
            return {"ok": False, "resumo": f"{self.nome}{SEPARADOR}{nome} passou de {round(limite)} s sem responder."}
        except Exception as erro:  # noqa: BLE001 - erro do servidor vira resultado para o modelo
            return {"ok": False, "resumo": f"Erro em {self.nome}{SEPARADOR}{nome}: {_mensagem_erro(erro)}"}
        ok, texto = _texto_do_resultado(resultado)
        return {"ok": ok, "resumo": texto}

    def _parar_agora(self) -> None:
        parar, tarefa = self._parar, self._tarefa
        if parar is not None:
            self._cliente.chamar_no_loop(parar.set)
        if tarefa is not None:
            try:
                tarefa.result(timeout=5)
            except Exception:  # noqa: BLE001 - encerrando de qualquer jeito
                tarefa.cancel()
        self._sessao = None
        self._tarefa = None

    def encerrar(self) -> None:
        with self._lock:
            self._parar_agora()


def _mensagem_erro(erro: BaseException) -> str:
    if isinstance(erro, BaseExceptionGroup):  # noqa: F821 - anyio junta os erros das tarefas
        return "; ".join(_mensagem_erro(e) for e in erro.exceptions)
    if isinstance(erro, TimeoutError):
        return "não respondeu a tempo"
    return str(erro) or erro.__class__.__name__


class ClienteMCP:
    """Todos os servidores de ``config/mcp.yaml`` e o loop asyncio que os atende."""

    def __init__(self, arquivo: Path | None, pasta_logs: Path | None = None,
                 conectores: dict[str, Callable] | None = None) -> None:
        self.arquivo = arquivo
        self.pasta_logs = pasta_logs
        self._conectores = conectores or {}  # testes: nome do servidor -> conector falso
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.servidores: dict[str, ServidorMCP] = {}
        self.erro_config = ""
        self.recarregar()

    # -- configuração -----------------------------------------------------------------------
    def recarregar(self) -> None:
        import yaml

        configs: dict[str, ConfigServidor] = {}
        self.erro_config = ""
        if self.arquivo is not None:
            try:
                if not self.arquivo.exists():
                    self.arquivo.parent.mkdir(parents=True, exist_ok=True)
                    self.arquivo.write_text(MODELO_YAML, encoding="utf-8")
                dados = yaml.safe_load(self.arquivo.read_text(encoding="utf-8")) or {}
                for nome, bloco in (dados.get("servidores") or {}).items():
                    try:
                        configs[str(nome)] = ConfigServidor.de_dict(nome, bloco)
                    except ValueError as erro:
                        log.warning("config/mcp.yaml: %s", erro)
            except (OSError, yaml.YAMLError, AttributeError) as erro:
                self.erro_config = f"config/mcp.yaml inválido: {erro}"
                log.warning("%s", self.erro_config)
        antigos = self.servidores
        self.servidores = {}
        for nome, cfg in configs.items():
            atual = antigos.pop(nome, None)
            if atual is not None and atual.cfg == cfg:
                self.servidores[nome] = atual
            else:
                if atual is not None:
                    atual.encerrar()
                self.servidores[nome] = ServidorMCP(cfg, self, self._conectores.get(nome))
        for sobra in antigos.values():
            sobra.encerrar()

    def arquivo_log(self, nome: str) -> Path | None:
        if self.pasta_logs is None:
            return None
        try:
            self.pasta_logs.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        return self.pasta_logs / f"mcp-{nome}.log"

    # -- loop asyncio -----------------------------------------------------------------------
    def _garantir_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or self._loop.is_closed():
                loop = asyncio.new_event_loop()
                self._thread = threading.Thread(target=loop.run_forever, name="mcp", daemon=True)
                self._thread.start()
                self._loop = loop
            return self._loop

    def loop_futuro(self) -> asyncio.Future:
        loop = self._garantir_loop()
        return asyncio.run_coroutine_threadsafe(_novo_futuro(), loop).result(5)

    def agendar(self, corrotina):
        return asyncio.run_coroutine_threadsafe(corrotina, self._garantir_loop())

    def esperar(self, futuro: asyncio.Future, timeout: float) -> Any:
        async def aguardar():
            return await asyncio.wait_for(asyncio.shield(futuro), timeout)
        return self.agendar(aguardar()).result(timeout + 5)

    def rodar(self, corrotina, timeout: float) -> Any:
        async def com_limite():
            return await asyncio.wait_for(corrotina, timeout)
        return self.agendar(com_limite()).result(timeout + 5)

    def chamar_no_loop(self, funcao) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(funcao)

    # -- uso pelos agentes ------------------------------------------------------------------
    def servidores_de(self, padroes: list[str]) -> list[str]:
        """Servidores cujas ferramentas os padrões pedem (``rea__*`` -> rea)."""
        nomes = []
        for nome in self.servidores:
            if any(p.split(SEPARADOR, 1)[0] == nome or fnmatch.fnmatchcase(f"{nome}{SEPARADOR}x", p)
                   for p in padroes if SEPARADOR in p):
                nomes.append(nome)
        return nomes

    def ferramentas(self, padroes: list[str], avisar: Callable[[str], None] | None = None) -> list[FerramentaMCP]:
        """Inicia (se preciso) os servidores dos padrões e devolve as ferramentas que casam."""
        saida: list[FerramentaMCP] = []
        for nome in self.servidores_de(padroes):
            servidor = self.servidores[nome]
            try:
                servidor.garantir()
            except ErroMCP as erro:
                if avisar:
                    avisar(str(erro))
                continue
            saida += [f for f in servidor.ferramentas if _casa(f.nome_completo, padroes)]
        return saida

    def chamar(self, nome_completo: str, argumentos: dict, timeout: float | None = None) -> dict:
        servidor_nome, _, nome = nome_completo.partition(SEPARADOR)
        servidor = self.servidores.get(servidor_nome)
        if servidor is None or not nome:
            return {"ok": False, "resumo": f"Ferramenta MCP {nome_completo} não existe."}
        try:
            return servidor.chamar(nome, argumentos, timeout)
        except ErroMCP as erro:
            return {"ok": False, "resumo": str(erro)}

    def estado(self) -> list[dict]:
        return [s.estado() for s in self.servidores.values()]

    def encerrar(self) -> None:
        for servidor in list(self.servidores.values()):
            try:
                servidor.encerrar()
            except Exception:  # noqa: BLE001
                log.exception("Erro encerrando o servidor MCP %s", servidor.nome)
        with self._lock:
            loop, self._loop = self._loop, None
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=3)
            if not loop.is_running():
                loop.close()


async def _novo_futuro() -> asyncio.Future:
    return asyncio.get_running_loop().create_future()

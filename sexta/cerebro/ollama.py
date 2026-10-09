"""Cliente mínimo da API nativa do Ollama (``/api/chat``) com streaming e ferramentas."""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

import httpx

log = logging.getLogger(__name__)


class ErroOllama(Exception):
    pass


class ClienteOllama:
    def __init__(self, url: str, modelo: str, *, pensar: bool = False, contexto: int = 8192,
                 temperatura: float = 0.6, manter_carregado: str = "30m", timeout: float = 180.0,
                 transporte: httpx.BaseTransport | None = None) -> None:
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.pensar = pensar
        self.contexto = contexto
        self.temperatura = temperatura
        self.manter_carregado = manter_carregado
        self._enviar_think = True  # desliga sozinho se o modelo não aceitar o parâmetro
        self._http = httpx.Client(
            base_url=self.url,
            timeout=httpx.Timeout(connect=5.0, read=timeout, write=30.0, pool=5.0),
            transport=transporte,
        )

    # ------------------------------------------------------------------
    def modelos_instalados(self) -> list[str]:
        r = self._http.get("/api/tags")
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", [])]

    def verificar(self) -> tuple[bool, str]:
        """(ok, mensagem) — usado no diagnóstico e na inicialização."""
        try:
            modelos = self.modelos_instalados()
        except httpx.HTTPError:
            return False, (f"Não consegui falar com o Ollama em {self.url}. "
                           "Ele está instalado e aberto? (ícone da lhama na bandeja do Windows)")
        alvo = self.modelo if ":" in self.modelo else f"{self.modelo}:latest"
        if alvo not in modelos and self.modelo not in modelos:
            return False, f"O modelo {self.modelo} não está baixado. Rode no terminal: ollama pull {self.modelo}"
        return True, f"Ollama ok ({self.modelo})"

    def aquecer(self) -> None:
        """Carrega o modelo na memória (mensagens vazias só carregam)."""
        try:
            self._http.post("/api/chat", json={"model": self.modelo, "messages": [],
                                               "keep_alive": self.manter_carregado}, timeout=120)
        except httpx.HTTPError as erro:
            log.warning("Não foi possível pré-carregar o modelo: %s", erro)

    # ------------------------------------------------------------------
    def conversar(self, mensagens: list[dict[str, Any]], ferramentas: list[dict] | None = None,
                  cancelado=lambda: False) -> Iterator[dict[str, Any]]:
        """Gera eventos: ``{"tipo": "texto"|"pensamento"|"ferramentas"|"fim", ...}``."""
        payload: dict[str, Any] = {
            "model": self.modelo,
            "messages": mensagens,
            "stream": True,
            "keep_alive": self.manter_carregado,
            "options": {"temperature": self.temperatura, "num_ctx": self.contexto},
        }
        if ferramentas:
            payload["tools"] = ferramentas
        if self._enviar_think:
            payload["think"] = self.pensar

        for tentativa in range(2):
            try:
                yield from self._stream(payload, cancelado)
                return
            except _ThinkNaoSuportado:
                if tentativa == 0:
                    log.info("Modelo %s não aceita o parâmetro 'think'; seguindo sem ele", self.modelo)
                    self._enviar_think = False
                    payload.pop("think", None)
                    continue
                raise ErroOllama("O modelo recusou a requisição.") from None

    def _stream(self, payload: dict[str, Any], cancelado) -> Iterator[dict[str, Any]]:
        texto: list[str] = []
        chamadas: list[dict[str, Any]] = []
        try:
            with self._http.stream("POST", "/api/chat", json=payload) as resposta:
                if resposta.status_code != 200:
                    corpo = resposta.read().decode("utf-8", "replace")
                    self._erro_http(resposta.status_code, corpo)
                for linha in resposta.iter_lines():
                    if cancelado():
                        log.info("Resposta cancelada")
                        break
                    if not linha.strip():
                        continue
                    try:
                        pedaco = json.loads(linha)
                    except json.JSONDecodeError:
                        continue
                    if "error" in pedaco:
                        self._erro_http(500, json.dumps(pedaco))
                    msg = pedaco.get("message") or {}
                    if msg.get("thinking"):
                        yield {"tipo": "pensamento", "texto": msg["thinking"]}
                    if msg.get("content"):
                        texto.append(msg["content"])
                        yield {"tipo": "texto", "texto": msg["content"]}
                    for chamada in msg.get("tool_calls") or []:
                        chamadas.append(_normalizar_chamada(chamada))
                    if pedaco.get("done"):
                        break
        except httpx.ConnectError as erro:
            raise ErroOllama(f"Não consegui falar com o Ollama em {self.url}. Ele está aberto?") from erro
        except httpx.TimeoutException as erro:
            raise ErroOllama("O Ollama demorou demais para responder.") from erro
        if chamadas:
            yield {"tipo": "ferramentas", "chamadas": chamadas}
        yield {"tipo": "fim", "texto": "".join(texto), "chamadas": chamadas}

    def _erro_http(self, status: int, corpo: str) -> None:
        try:
            mensagem = json.loads(corpo).get("error", corpo)
        except json.JSONDecodeError:
            mensagem = corpo
        texto = str(mensagem)
        if "think" in texto.lower() and self._enviar_think:
            raise _ThinkNaoSuportado()
        if "not found" in texto.lower() and "model" in texto.lower():
            raise ErroOllama(f"O modelo {self.modelo} não está baixado. Rode: ollama pull {self.modelo}")
        if "does not support tools" in texto.lower():
            raise ErroOllama(f"O modelo {self.modelo} não suporta ferramentas. Use um modelo com 'tools' no site do Ollama.")
        raise ErroOllama(f"Erro do Ollama ({status}): {texto[:300]}")

    def fechar(self) -> None:
        self._http.close()


class _ThinkNaoSuportado(Exception):
    pass


def _normalizar_chamada(chamada: dict[str, Any]) -> dict[str, Any]:
    funcao = chamada.get("function") or {}
    argumentos = funcao.get("arguments") or {}
    if isinstance(argumentos, str):
        try:
            argumentos = json.loads(argumentos) if argumentos.strip() else {}
        except json.JSONDecodeError:
            argumentos = {}
    return {"nome": funcao.get("name", ""), "argumentos": argumentos if isinstance(argumentos, dict) else {}}

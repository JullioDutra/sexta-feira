"""Cérebro na nuvem: Claude (Anthropic), com streaming, ferramentas, cache de prompt e visão.

Mesma interface do ``ClienteOllama``: ``conversar`` gera eventos ``texto``/``ferramentas``/``fim``,
e o agente usa ``mensagem_assistente`` / ``mensagens_resultados`` para montar a volta das ferramentas
no formato que cada cérebro entende.

Velocidade:
- o prompt de sistema e as ferramentas ficam em cache por 1 hora (só a parte nova da conversa é lida);
- na voz o esforço de raciocínio é baixo (respostas curtas e rápidas); no texto, médio;
- comandos curtos podem ir para o modelo rápido (Haiku) quando os "dois cérebros" estão ligados.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from .ollama import ErroOllama

log = logging.getLogger(__name__)

MODELO_PADRAO = "claude-opus-5-5"
MODELO_RAPIDO_PADRAO = "claude-haiku-5-5"
# Modelos com fallback no servidor quando um filtro de segurança recusa o pedido
COM_FALLBACK = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
BETA_FALLBACK = "server-side-fallback-2026-07-01"


class ClienteClaude:
    def __init__(self, modelo: str = MODELO_PADRAO, *, chave: str = "", esforco_voz: str = "low",
                 esforco_texto: str = "medium", cliente=None) -> None:
        self.modelo = modelo or MODELO_PADRAO
        self.esforco_voz = esforco_voz
        self.esforco_texto = esforco_texto
        self.pensar = False
        self.url = "https://api.anthropic.com"
        if cliente is not None:
            self._cliente = cliente
        else:
            import anthropic

            # sem chave explícita, o SDK lê ANTHROPIC_API_KEY (ou o login do `ant`)
            self._cliente = anthropic.Anthropic(api_key=chave or None, max_retries=2,
                                                timeout=anthropic.Timeout(60.0, connect=5.0))

    # ------------------------------------------------------------------
    def verificar(self) -> tuple[bool, str]:
        import anthropic

        try:
            self._cliente.models.retrieve(self.modelo)
        except anthropic.AuthenticationError:
            return False, "A chave da API do Claude é inválida. Confira ANTHROPIC_API_KEY no arquivo .env."
        except anthropic.NotFoundError:
            return False, f"O modelo {self.modelo} não existe ou não está liberado na sua conta."
        except anthropic.APIConnectionError:
            return False, "Sem conexão com a API do Claude. Confira a internet."
        except anthropic.APIStatusError as erro:
            return False, f"API do Claude respondeu com erro {erro.status_code}."
        except Exception as erro:  # noqa: BLE001 - ex.: nenhuma credencial configurada
            return False, f"Claude indisponível: {erro}"
        return True, f"Claude ok ({self.modelo})"

    def aquecer(self, mensagens: list[dict[str, Any]] | None = None, ferramentas: list[dict] | None = None,
                modelo: str | None = None) -> None:
        """Grava o prompt de sistema + ferramentas no cache (``max_tokens=0`` não gera resposta)."""
        if not mensagens:
            return
        sistema, conversa = self._separar(mensagens)
        try:
            self._cliente.messages.create(model=modelo or self.modelo, max_tokens=0, system=sistema,
                                          tools=self._ferramentas(ferramentas), messages=conversa)
        except Exception as erro:  # noqa: BLE001 - aquecer é só otimização
            log.info("Não foi possível pré-aquecer o cache do Claude: %s", erro)

    # ------------------------------------------------------------------
    @staticmethod
    def _separar(mensagens: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
        """Tira o prompt de sistema (vai no campo ``system``, com cache de 1 hora)."""
        sistema = [{"type": "text", "text": m["content"]} for m in mensagens if m.get("role") == "system"]
        if sistema:
            sistema[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
        conversa = [m for m in mensagens if m.get("role") != "system"]
        return sistema, conversa

    @staticmethod
    def _ferramentas(ferramentas: list[dict] | None) -> list[dict]:
        saida = []
        for f in ferramentas or []:
            funcao = f.get("function", f)
            saida.append({"name": funcao["name"], "description": funcao.get("description", ""),
                          "input_schema": funcao.get("parameters") or {"type": "object", "properties": {}},
                          "eager_input_streaming": True})
        return saida

    def _parametros(self, mensagens, ferramentas, modelo: str | None, max_tokens: int | None, voz: bool) -> dict:
        sistema, conversa = self._separar(mensagens)
        modelo = modelo or self.modelo
        params: dict[str, Any] = {
            "model": modelo,
            "max_tokens": 8000 if voz else 16000,
            "system": sistema,
            "messages": conversa,
            "output_config": {"effort": self.esforco_voz if voz else self.esforco_texto},
            "cache_control": {"type": "ephemeral"},  # a conversa também entra no cache
        }
        if ferramentas:
            params["tools"] = self._ferramentas(ferramentas)
        if modelo in COM_FALLBACK:
            params["betas"] = [BETA_FALLBACK]
            params["fallbacks"] = "default"
        return params

    def conversar(self, mensagens: list[dict[str, Any]], ferramentas: list[dict] | None = None,
                  cancelado=lambda: False, *, modelo: str | None = None, max_tokens: int | None = None
                  ) -> Iterator[dict[str, Any]]:
        import anthropic

        voz = max_tokens is not None  # o agente só limita tokens no canal de voz
        params = self._parametros(mensagens, ferramentas, modelo, max_tokens, voz)
        for tentativa in range(3):
            houve_texto = False
            try:
                with self._cliente.beta.messages.stream(**params) as stream:
                    for evento in stream:
                        if cancelado():
                            log.info("Resposta cancelada")
                            yield {"tipo": "fim", "texto": "", "chamadas": [], "bruto": []}
                            return
                        if evento.type == "text":
                            houve_texto = True
                            yield {"tipo": "texto", "texto": evento.text}
                    final = stream.get_final_message()
                break
            except ValueError:
                # JSON de ferramenta que o SDK não conseguiu ler: refaz a rodada (poucas vezes)
                if tentativa == 2 or houve_texto:
                    raise ErroOllama("O Claude mandou uma chamada de ferramenta inválida.") from None
                continue
            except anthropic.AuthenticationError as erro:
                raise ErroOllama("A chave da API do Claude é inválida. Confira ANTHROPIC_API_KEY no .env.") from erro
            except anthropic.RateLimitError as erro:
                raise ErroOllama("Limite de uso da API do Claude atingido. Tente de novo em instantes.") from erro
            except anthropic.APIConnectionError as erro:
                raise ErroOllama("Sem conexão com o Claude. Confira a internet.") from erro
            except anthropic.APIStatusError as erro:
                raise ErroOllama(f"Erro da API do Claude ({erro.status_code}): {erro.message}") from erro

        if final.stop_reason == "refusal":
            yield {"tipo": "texto", "texto": " Não posso ajudar com isso."}
            yield {"tipo": "fim", "texto": "", "chamadas": [], "bruto": []}
            return
        usos = [b for b in final.content if b.type == "tool_use"]
        chamadas = []
        if usos and final.stop_reason != "max_tokens":  # entrada truncada não roda
            for b in usos:
                argumentos = b.input if isinstance(b.input, dict) else {}
                chamadas.append({"nome": b.name, "argumentos": argumentos, "id": b.id})
        uso = final.usage
        log.info("Claude %s: entrada %s (cache lido %s, gravado %s), saída %s", final.model, uso.input_tokens,
                 getattr(uso, "cache_read_input_tokens", 0), getattr(uso, "cache_creation_input_tokens", 0),
                 uso.output_tokens)
        if chamadas:
            yield {"tipo": "ferramentas", "chamadas": chamadas}
        yield {"tipo": "fim", "texto": "", "chamadas": chamadas, "bruto": _para_reenvio(final.content)}

    # -- formato da volta das ferramentas ----------------------------------------------
    @staticmethod
    def mensagem_assistente(texto: str, chamadas: list[dict], bruto: Any) -> dict[str, Any]:
        return {"role": "assistant", "content": bruto}

    @staticmethod
    def mensagens_resultados(chamadas: list[dict], conteudos: list[dict]) -> list[dict[str, Any]]:
        blocos = []
        for chamada, conteudo in zip(chamadas, conteudos):
            bloco = {"type": "tool_result", "tool_use_id": chamada["id"],
                     "content": json.dumps(conteudo, ensure_ascii=False, default=str)}
            if conteudo.get("ok") is False and not conteudo.get("pendente"):
                bloco["is_error"] = True
            blocos.append(bloco)
        return [{"role": "user", "content": blocos}]  # todos os resultados numa mensagem só

    # -- visão ---------------------------------------------------------------------------
    def visao(self, pergunta: str, imagens_b64: list[str], sistema: str = "", modelo: str | None = None) -> str:
        import anthropic

        conteudo: list[dict[str, Any]] = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img}}
            for img in imagens_b64
        ]
        conteudo.append({"type": "text", "text": pergunta})
        params: dict[str, Any] = {"model": modelo or self.modelo, "max_tokens": 8000,
                                  "messages": [{"role": "user", "content": conteudo}],
                                  "output_config": {"effort": "low"}}
        if sistema:
            params["system"] = sistema
        if params["model"] in COM_FALLBACK:
            params["betas"] = [BETA_FALLBACK]
            params["fallbacks"] = "default"
        try:
            resposta = self._cliente.beta.messages.create(**params)
        except anthropic.APIConnectionError as erro:
            raise ErroOllama("Sem conexão com o Claude. Confira a internet.") from erro
        except anthropic.APIStatusError as erro:
            raise ErroOllama(f"Erro da API do Claude ({erro.status_code}): {erro.message}") from erro
        if resposta.stop_reason == "refusal":
            return "Não posso analisar essa imagem."
        return "".join(b.text for b in resposta.content if b.type == "text").strip()

    def fechar(self) -> None:
        self._cliente.close()


def _para_reenvio(conteudo: list) -> list:
    """Conteúdo do assistente para mandar de volta. Depois de um fallback no meio da resposta,
    blocos internos anteriores ao último marcador de fallback não podem ser reenviados."""
    indices = [i for i, b in enumerate(conteudo) if b.type == "fallback"]
    if not indices:
        return list(conteudo)
    corte = indices[-1]
    internos = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}
    return [b for i, b in enumerate(conteudo) if i > corte or (b.type not in internos and b.type != "fallback")]

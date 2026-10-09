"""Configuração da Sexta-Feira.

Dois níveis:
- ``.env`` (arquivo na raiz do projeto): infraestrutura — Ollama, portas, voz,
  câmera, microfone. Lido uma vez na inicialização.
- ``dados/preferencias.json``: preferências do usuário editáveis pelo HUD
  (nome, cidade, bloqueio facial...). Ver :class:`Preferencias`.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # python-dotenv é opcional nos testes
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

RAIZ = Path(__file__).resolve().parent.parent
WINDOWS = sys.platform == "win32"


def _env_str(nome: str, padrao: str = "") -> str:
    valor = os.environ.get(nome)
    return padrao if valor is None or valor.strip() == "" else valor.strip()


def _env_int(nome: str, padrao: int) -> int:
    try:
        return int(_env_str(nome, str(padrao)))
    except ValueError:
        return padrao


def _env_float(nome: str, padrao: float) -> float:
    try:
        return float(_env_str(nome, str(padrao)).replace(",", "."))
    except ValueError:
        return padrao


def _env_bool(nome: str, padrao: bool) -> bool:
    valor = _env_str(nome, "sim" if padrao else "nao").lower()
    return valor in {"1", "true", "sim", "s", "yes", "y", "on", "ligado"}


def _env_lista(nome: str, padrao: list[str] | None = None) -> list[str]:
    valor = _env_str(nome, "")
    if not valor:
        return list(padrao or [])
    return [item.strip() for item in valor.split(",") if item.strip()]


@dataclass
class Config:
    """Configuração de infraestrutura (lida do .env)."""

    raiz: Path = RAIZ
    dados: Path = RAIZ / "dados"

    # Cérebro: "claude" (nuvem, mais rápido e inteligente), "ollama" (local) ou "auto"
    # (Claude se houver ANTHROPIC_API_KEY, senão Ollama)
    cerebro: str = "auto"
    claude_modelo: str = "claude-opus-5-5"
    claude_modelo_rapido: str = "claude-haiku-5-5"  # vazio = um cérebro só
    claude_esforco_voz: str = "low"
    claude_esforco_texto: str = "medium"

    # Cérebro local (Ollama)
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_modelo: str = "qwen3.5:9b"
    ollama_modelo_rapido: str = ""   # opcional: modelo menor só para comandos curtos ("dois cérebros")
    ollama_modelo_visao: str = ""    # modelo com visão para "analisa a tela" (padrão: o principal)
    ollama_pensar: bool = False
    ollama_contexto: int = 8192
    ollama_temperatura: float = 0.5
    ollama_manter_carregado: str = "4h"  # quanto tempo o modelo fica na memória sem uso (evita recarregar)
    ollama_max_tokens_voz: int = 400

    # Notificações no celular (opcional, app ntfy)
    ntfy_topico: str = ""
    ntfy_servidor: str = "https://ntfy.sh"

    # Arquivos
    pastas_arquivos: list[str] = field(default_factory=list)  # pastas extras para a busca de arquivos

    # Servidor
    porta: int = 8765
    porta_https: int = 8766
    liberar_rede: bool = True
    hosts_extras: list[str] = field(default_factory=list)
    endereco_externo: str = ""  # ex.: https://meu-pc.tail1234.ts.net (Tailscale)
    abrir_hud: bool = True
    navegador: str = "edge"

    # Voz
    ativacao_motor: str = "vosk"
    ativacao_frases: list[str] = field(default_factory=lambda: ["sexta feira"])
    porcupine_chave: str = ""
    porcupine_arquivo: str = ""
    porcupine_modelo: str = ""
    whisper_modelo: str = "small"
    whisper_dispositivo: str = "auto"
    voz_motor: str = "edge"  # "edge" (neural, online) ou "windows" (offline, vozes do Windows)
    voz: str = "pt-BR-FranciscaNeural"
    voz_velocidade: str = "+8%"
    voz_tom: str = "+0Hz"
    microfone: str = ""
    alto_falante: str = ""
    fim_de_fala_ms: int = 850
    interromper_com_ativacao: bool = True

    # Câmera
    camera_indice: int = 0
    camera_largura: int = 640
    camera_altura: int = 480
    camera_backend: str = "dshow" if WINDOWS else "auto"

    log_nivel: str = "INFO"

    def usa_claude(self) -> bool:
        if self.cerebro == "claude":
            return True
        if self.cerebro == "ollama":
            return False
        return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())

    @property
    def modelo_principal(self) -> str:
        return self.claude_modelo if self.usa_claude() else self.ollama_modelo

    @property
    def modelos(self) -> Path:
        return self.dados / "modelos"

    @property
    def logs(self) -> Path:
        return self.dados / "logs"

    @property
    def pasta_config(self) -> Path:
        return self.raiz / "config"

    @property
    def hud_dist(self) -> Path:
        return self.raiz / "hud" / "dist"

    @classmethod
    def carregar(cls, arquivo_env: Path | None = None) -> "Config":
        arquivo_env = arquivo_env or (RAIZ / ".env")
        if load_dotenv and arquivo_env.exists():
            load_dotenv(arquivo_env, override=False, encoding="utf-8")
        cfg = cls(
            cerebro=_env_str("CEREBRO", cls.cerebro).lower(),
            claude_modelo=_env_str("CLAUDE_MODELO", cls.claude_modelo),
            claude_modelo_rapido=os.environ.get("CLAUDE_MODELO_RAPIDO", cls.claude_modelo_rapido).strip(),
            claude_esforco_voz=_env_str("CLAUDE_ESFORCO_VOZ", cls.claude_esforco_voz).lower(),
            claude_esforco_texto=_env_str("CLAUDE_ESFORCO_TEXTO", cls.claude_esforco_texto).lower(),
            ollama_url=_env_str("OLLAMA_URL", cls.ollama_url).rstrip("/"),
            ollama_modelo=_env_str("OLLAMA_MODELO", cls.ollama_modelo),
            ollama_modelo_rapido=_env_str("OLLAMA_MODELO_RAPIDO"),
            ollama_modelo_visao=_env_str("OLLAMA_MODELO_VISAO"),
            ollama_pensar=_env_bool("OLLAMA_PENSAR", cls.ollama_pensar),
            ollama_contexto=_env_int("OLLAMA_CONTEXTO", cls.ollama_contexto),
            ollama_temperatura=_env_float("OLLAMA_TEMPERATURA", cls.ollama_temperatura),
            ollama_manter_carregado=_env_str("OLLAMA_MANTER_CARREGADO", cls.ollama_manter_carregado),
            ollama_max_tokens_voz=_env_int("OLLAMA_MAX_TOKENS_VOZ", cls.ollama_max_tokens_voz),
            pastas_arquivos=_env_lista("PASTAS_ARQUIVOS"),
            ntfy_topico=_env_str("NTFY_TOPICO"),
            ntfy_servidor=_env_str("NTFY_SERVIDOR", cls.ntfy_servidor),
            porta=_env_int("PORTA", cls.porta),
            porta_https=_env_int("PORTA_CELULAR", cls.porta_https),
            liberar_rede=_env_bool("LIBERAR_CELULAR", cls.liberar_rede),
            hosts_extras=_env_lista("HOSTS_EXTRAS"),
            endereco_externo=_env_str("ENDERECO_EXTERNO").rstrip("/"),
            abrir_hud=_env_bool("ABRIR_HUD", cls.abrir_hud),
            navegador=_env_str("NAVEGADOR", cls.navegador).lower(),
            ativacao_motor=_env_str("ATIVACAO_MOTOR", cls.ativacao_motor).lower(),
            ativacao_frases=_env_lista("ATIVACAO_FRASES", ["sexta feira"]),
            porcupine_chave=_env_str("PORCUPINE_CHAVE"),
            porcupine_arquivo=_env_str("PORCUPINE_ARQUIVO"),
            porcupine_modelo=_env_str("PORCUPINE_MODELO"),
            whisper_modelo=_env_str("WHISPER_MODELO", cls.whisper_modelo),
            whisper_dispositivo=_env_str("WHISPER_DISPOSITIVO", cls.whisper_dispositivo).lower(),
            voz_motor=_env_str("VOZ_MOTOR", cls.voz_motor).lower(),
            voz=_env_str("VOZ", cls.voz),
            voz_velocidade=_env_str("VOZ_VELOCIDADE", cls.voz_velocidade),
            voz_tom=_env_str("VOZ_TOM", cls.voz_tom),
            microfone=_env_str("MICROFONE"),
            alto_falante=_env_str("ALTO_FALANTE"),
            fim_de_fala_ms=_env_int("FIM_DE_FALA_MS", cls.fim_de_fala_ms),
            interromper_com_ativacao=_env_bool("INTERROMPER_COM_ATIVACAO", cls.interromper_com_ativacao),
            camera_indice=_env_int("CAMERA_INDICE", cls.camera_indice),
            camera_largura=_env_int("CAMERA_LARGURA", cls.camera_largura),
            camera_altura=_env_int("CAMERA_ALTURA", cls.camera_altura),
            camera_backend=_env_str("CAMERA_BACKEND", "dshow" if WINDOWS else "auto").lower(),
            log_nivel=_env_str("LOG_NIVEL", cls.log_nivel).upper(),
        )
        pasta_dados = _env_str("PASTA_DADOS")
        if pasta_dados:
            cfg.dados = Path(pasta_dados).expanduser().resolve()
        cfg.garantir_pastas()
        return cfg

    def garantir_pastas(self) -> None:
        for pasta in (self.dados, self.modelos, self.logs, self.dados / "rosto",
                      self.dados / "audio", self.dados / "prints", self.dados / "certificados"):
            pasta.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Preferências (editáveis pelo HUD)
# ---------------------------------------------------------------------------

PREFERENCIAS_PADRAO: dict[str, Any] = {
    "nome": "",                # como a Sexta chama o usuário em saudações
    "tratamento": "chefe",     # forma de tratamento nas respostas
    "cidade": "",              # cidade padrão para o clima
    "cidade_lat": None,
    "cidade_lon": None,
    "cidade_fuso": None,
    "cidade_rotulo": "",
    "bloqueio_facial": True,   # a Sexta só obedece depois de reconhecer o rosto
    "exigir_piscada": True,    # teste de vivacidade (não aceita foto)
    "limiar_rosto": 0.42,      # similaridade mínima (cosseno SFace)
    "sessao_minutos": 30,      # por quanto tempo a verificação facial vale
    "modo_continuacao": True,  # depois de responder, escuta mais alguns segundos sem precisar do nome
    "continuacao_segundos": 6,
    "tema": "sexta",           # "sexta" (âmbar) ou "jarvis" (ciano)
    "maos_sensibilidade": 1.0,
    "voz": "sexta",            # "sexta" (perfil da assistente do traje), uma voz do edge-tts, ou "" (a do .env)
    "voz_efeito": True,        # efeito "IA do traje" na voz
    "onboarding_concluido": False,
    "saudacao_ao_iniciar": True,
    "atalhos_rapidos": True,   # comandos simples sem passar pela IA (mais rápido)
    "presenca_camera": False,  # protocolo "quando eu voltar ao PC": também procura seu rosto na câmera
}

# Preferências que o HUD pode alterar diretamente
PREFERENCIAS_EDITAVEIS = set(PREFERENCIAS_PADRAO) - {"cidade_lat", "cidade_lon", "cidade_fuso", "cidade_rotulo"}


class Preferencias:
    """Preferências persistidas em JSON, seguras para uso entre threads."""

    def __init__(self, arquivo: Path):
        self.arquivo = arquivo
        self._lock = threading.RLock()
        self._dados: dict[str, Any] = dict(PREFERENCIAS_PADRAO)
        self._ouvintes: list = []
        if arquivo.exists():
            try:
                salvos = json.loads(arquivo.read_text(encoding="utf-8"))
                if isinstance(salvos, dict):
                    if "voz_efeito" not in salvos and not salvos.get("voz"):
                        salvos["voz"] = "sexta"  # quem usava a voz padrão passa para o perfil novo
                    self._dados.update(salvos)
            except (OSError, json.JSONDecodeError):
                pass

    def get(self, chave: str, padrao: Any = None) -> Any:
        with self._lock:
            return self._dados.get(chave, PREFERENCIAS_PADRAO.get(chave, padrao))

    def __getitem__(self, chave: str) -> Any:
        return self.get(chave)

    def tudo(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._dados)

    def atualizar(self, valores: dict[str, Any], *, interno: bool = False) -> dict[str, Any]:
        """Atualiza e salva. Se ``interno`` for falso, só aceita chaves editáveis."""
        with self._lock:
            mudou = {}
            for chave, valor in valores.items():
                if not interno and chave not in PREFERENCIAS_EDITAVEIS:
                    continue
                if chave in PREFERENCIAS_PADRAO and self._dados.get(chave) != valor:
                    self._dados[chave] = valor
                    mudou[chave] = valor
            if mudou:
                self._salvar()
            ouvintes = list(self._ouvintes)
        for ouvinte in ouvintes:
            try:
                ouvinte(mudou)
            except Exception:  # noqa: BLE001 - um ouvinte com erro não pode travar os outros
                pass
        return mudou

    def ao_mudar(self, funcao) -> None:
        with self._lock:
            self._ouvintes.append(funcao)

    def _salvar(self) -> None:
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._dados, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.arquivo)

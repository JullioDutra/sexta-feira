"""Agenda do Google ou do Outlook (opcional), lida pelo endereço iCal secreto — sem login, só leitura.

- Google Agenda: Configurações da agenda → "Endereço secreto no formato iCal".
- Outlook: Configurações → Calendário → Calendários compartilhados → Publicar → link ICS.

Coloque os endereços em ``AGENDA_ICS`` no .env (separados por vírgula). A Sexta-Feira usa os
compromissos no "planeja meu dia", no briefing e avisa minutos antes de cada um.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta

import httpx

from ..util.tempo import formatar_hora

log = logging.getLogger(__name__)

CACHE_S = 600


class Agenda:
    def __init__(self, app, urls: list[str], http: httpx.Client | None = None) -> None:
        self.app = app
        self.urls = [u.strip() for u in urls if u.strip()]
        self.http = http or httpx.Client(timeout=15.0, follow_redirects=True)
        self._cache: tuple[float, list[bytes]] | None = None
        self._avisados: set[str] = set()
        self._lock = threading.Lock()
        self._rodando = False

    def configurada(self) -> bool:
        return bool(self.urls)

    def _calendarios(self) -> list[bytes]:
        with self._lock:
            if self._cache and time.time() - self._cache[0] < CACHE_S:
                return self._cache[1]
        dados = []
        for url in self.urls:
            try:
                r = self.http.get(url.replace("webcal://", "https://"))
                r.raise_for_status()
                dados.append(r.content)
            except httpx.HTTPError as erro:
                log.warning("Agenda indisponível (%s): %s", url[:40], erro)
        with self._lock:
            self._cache = (time.time(), dados)
        return dados

    def eventos(self, inicio: datetime, fim: datetime) -> list[dict]:
        """Compromissos (inclusive os que se repetem) entre ``inicio`` e ``fim``, em horário local."""
        if not self.urls:
            return []
        import icalendar
        import recurring_ical_events

        saida = []
        for bruto in self._calendarios():
            try:
                cal = icalendar.Calendar.from_ical(bruto)
                ocorrencias = recurring_ical_events.of(cal).between(inicio, fim)
            except Exception as erro:  # noqa: BLE001 - um calendário com defeito não derruba os outros
                log.warning("Não consegui ler um calendário: %s", erro)
                continue
            for ev in ocorrencias:
                if str(ev.get("STATUS", "")).upper() == "CANCELLED" or str(ev.get("TRANSP", "")).upper() == "TRANSPARENT":
                    continue
                comeco = ev.get("DTSTART").dt
                termino = ev.get("DTEND").dt if ev.get("DTEND") else None
                dia_inteiro = not isinstance(comeco, datetime)
                comeco = _local(comeco)
                termino = _local(termino) if termino else comeco + timedelta(hours=1)
                saida.append({"titulo": str(ev.get("SUMMARY", "Compromisso")), "inicio": comeco, "fim": termino,
                              "dia_inteiro": dia_inteiro, "local": str(ev.get("LOCATION", "") or ""),
                              "id": f"{ev.get('UID', '')}@{comeco.isoformat()}"})
        return sorted(saida, key=lambda e: e["inicio"])

    def do_dia(self, dia: date | None = None) -> list[dict]:
        dia = dia or date.today()
        inicio = datetime.combine(dia, datetime.min.time())
        return self.eventos(inicio, inicio + timedelta(days=1))

    @staticmethod
    def descrever(ev: dict) -> str:
        return ev["titulo"] if ev["dia_inteiro"] else f"{ev['titulo']} às {formatar_hora(ev['inicio'])}"

    # -- avisos antes dos compromissos --------------------------------------------------------
    def iniciar(self) -> None:
        if not self.urls:
            return
        self._rodando = True
        threading.Thread(target=self._laco, name="agenda", daemon=True).start()

    def parar(self) -> None:
        self._rodando = False

    def _laco(self) -> None:
        while self._rodando:
            try:
                self.verificar_avisos(datetime.now())
            except Exception:  # noqa: BLE001
                log.exception("Erro verificando a agenda")
            time.sleep(60)

    def verificar_avisos(self, agora: datetime) -> list[dict]:
        minutos = int(self.app.prefs.get("aviso_reuniao_min") or 10)
        proximos = [e for e in self.eventos(agora, agora + timedelta(minutes=minutos + 1))
                    if not e["dia_inteiro"] and e["inicio"] >= agora and e["id"] not in self._avisados]
        for ev in proximos:
            self._avisados.add(ev["id"])
            faltam = max(1, round((ev["inicio"] - agora).total_seconds() / 60))
            tratamento = self.app.prefs.get("tratamento") or "chefe"
            texto = f"{tratamento.capitalize()}, {ev['titulo']} começa em {faltam} minuto{'s' if faltam > 1 else ''}."
            self.app.fala.falar(texto)
            self.app.barramento.publicar("aviso", nivel="lembrete", texto=texto)
            from .notificacoes import notificar

            notificar(self.app, texto, titulo="Agenda")
        return proximos


def _local(valor) -> datetime:
    if isinstance(valor, datetime):
        return valor.astimezone().replace(tzinfo=None) if valor.tzinfo else valor
    return datetime.combine(valor, datetime.min.time())

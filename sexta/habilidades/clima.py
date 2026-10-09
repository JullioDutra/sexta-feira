"""Clima pelo Open-Meteo (gratuito, sem chave de API)."""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime

import httpx

from ..util.texto import normalizar

log = logging.getLogger(__name__)

GEOCODIFICACAO = "https://geocoding-api.open-meteo.com/v1/search"
PREVISAO = "https://api.open-meteo.com/v1/forecast"

UFS = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins",
}
SIGLA_POR_ESTADO = {normalizar(v): k for k, v in UFS.items()}

# Códigos WMO -> (descrição, ícone)
CODIGOS = {
    0: ("céu limpo", "limpo"), 1: ("predominantemente limpo", "limpo"), 2: ("parcialmente nublado", "parcial"),
    3: ("nublado", "nublado"), 45: ("neblina", "neblina"), 48: ("neblina com geada", "neblina"),
    51: ("garoa fraca", "garoa"), 53: ("garoa", "garoa"), 55: ("garoa forte", "garoa"),
    56: ("garoa congelante", "garoa"), 57: ("garoa congelante forte", "garoa"),
    61: ("chuva fraca", "chuva"), 63: ("chuva moderada", "chuva"), 65: ("chuva forte", "chuva_forte"),
    66: ("chuva congelante", "chuva"), 67: ("chuva congelante forte", "chuva_forte"),
    71: ("neve fraca", "neve"), 73: ("neve", "neve"), 75: ("neve forte", "neve"), 77: ("grãos de neve", "neve"),
    80: ("pancadas de chuva", "chuva"), 81: ("pancadas de chuva moderadas", "chuva"),
    82: ("pancadas de chuva fortes", "chuva_forte"), 85: ("pancadas de neve", "neve"),
    86: ("pancadas de neve fortes", "neve"), 95: ("trovoadas", "tempestade"),
    96: ("trovoadas com granizo", "tempestade"), 99: ("trovoadas fortes com granizo", "tempestade"),
}
DIAS_CURTOS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def descrever(codigo: int | None) -> tuple[str, str]:
    return CODIGOS.get(int(codigo or 0), ("condição desconhecida", "nublado"))


class ErroClima(Exception):
    pass


class ServicoClima:
    def __init__(self, http: httpx.Client | None = None) -> None:
        self.http = http or httpx.Client(timeout=10.0, headers={"User-Agent": "Sexta-Feira/1.0"})
        self._cache_local: dict[str, dict] = {}
        self._cache_previsao: dict[tuple, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def localizar(self, consulta: str) -> dict:
        consulta = consulta.strip()
        chave = normalizar(consulta)
        if chave in self._cache_local:
            return self._cache_local[chave]
        nome, estado = consulta, ""
        m = re.match(r"^(.*?)(?:\s*[,\-/]\s*|\s+)([A-Za-z]{2})$", consulta)
        if m and m.group(2).upper() in UFS:
            nome, estado = m.group(1), m.group(2).upper()
        elif "," in consulta:
            nome, estado = (p.strip() for p in consulta.split(",", 1))
        try:
            r = self.http.get(GEOCODIFICACAO, params={"name": nome.strip(), "count": 10, "language": "pt", "format": "json"})
            r.raise_for_status()
        except httpx.HTTPError as erro:
            raise ErroClima("Não consegui acessar o serviço de clima agora.") from erro
        resultados = r.json().get("results") or []
        if not resultados:
            raise ErroClima(f"Não encontrei a cidade {consulta}.")
        if estado:
            alvo = normalizar(UFS.get(estado.upper(), estado))
            filtrados = [x for x in resultados if alvo in normalizar(x.get("admin1", "")) or
                         normalizar(x.get("country", "")) == alvo]
            resultados = filtrados or resultados
        resultados.sort(key=lambda x: (x.get("country_code") != "BR", -(x.get("population") or 0)))
        melhor = resultados[0]
        sigla = SIGLA_POR_ESTADO.get(normalizar(melhor.get("admin1", "")), "")
        rotulo = melhor["name"] + (f" - {sigla}" if sigla else (f", {melhor.get('country', '')}" if melhor.get("country_code") != "BR" else ""))
        local = {"nome": melhor["name"], "lat": melhor["latitude"], "lon": melhor["longitude"],
                 "fuso": melhor.get("timezone"), "rotulo": rotulo, "estado": melhor.get("admin1", ""),
                 "pais": melhor.get("country", "")}
        self._cache_local[chave] = local
        return local

    def previsao(self, lat: float, lon: float) -> dict:
        chave = (round(lat, 3), round(lon, 3))
        with self._lock:
            em_cache = self._cache_previsao.get(chave)
            if em_cache and time.time() - em_cache[0] < 600:
                return em_cache[1]
        params = {
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 7, "forecast_hours": 24,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m",
            "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset,uv_index_max",
        }
        try:
            r = self.http.get(PREVISAO, params=params)
            r.raise_for_status()
        except httpx.HTTPError as erro:
            raise ErroClima("Não consegui acessar o serviço de clima agora.") from erro
        dados = r.json()
        with self._lock:
            self._cache_previsao[chave] = (time.time(), dados)
        return dados

    # ------------------------------------------------------------------
    def obter(self, local: dict) -> dict:
        """Dados prontos para o holograma."""
        bruto = self.previsao(local["lat"], local["lon"])
        atual = bruto.get("current", {})
        desc, icone = descrever(atual.get("weather_code"))
        diario = bruto.get("daily", {})
        dias = []
        for i, data in enumerate(diario.get("time", [])):
            d = datetime.fromisoformat(data)
            ddesc, dicone = descrever(diario["weather_code"][i])
            dias.append({
                "data": data,
                "dia": "hoje" if i == 0 else "amanhã" if i == 1 else DIAS_CURTOS[d.weekday()],
                "max": round(diario["temperature_2m_max"][i]),
                "min": round(diario["temperature_2m_min"][i]),
                "chuva": (diario.get("precipitation_probability_max") or [None] * 7)[i],
                "descricao": ddesc,
                "icone": dicone,
            })
        horario = bruto.get("hourly", {})
        horas = []
        for i, quando in enumerate(horario.get("time", [])[:24:2]):
            idx = i * 2
            hdesc, hicone = descrever(horario["weather_code"][idx])
            horas.append({
                "hora": f"{datetime.fromisoformat(quando).hour}h",
                "temp": round(horario["temperature_2m"][idx]),
                "chuva": (horario.get("precipitation_probability") or [None] * 24)[idx],
                "icone": hicone,
                "dia": bool((horario.get("is_day") or [1] * 24)[idx]),
            })
        nascer = (diario.get("sunrise") or [""])[0][-5:]
        por = (diario.get("sunset") or [""])[0][-5:]
        return {
            "local": local["rotulo"],
            "lat": local["lat"],
            "lon": local["lon"],
            "atual": {
                "temp": round(atual.get("temperature_2m", 0)),
                "sensacao": round(atual.get("apparent_temperature", 0)),
                "umidade": atual.get("relative_humidity_2m"),
                "vento": round(atual.get("wind_speed_10m", 0)),
                "descricao": desc,
                "icone": icone,
                "dia": bool(atual.get("is_day", 1)),
            },
            "dias": dias,
            "horas": horas,
            "nascer_sol": nascer,
            "por_sol": por,
            "uv": (diario.get("uv_index_max") or [None])[0],
        }

    @staticmethod
    def resumo(dados: dict, dias: int = 1) -> str:
        atual = dados["atual"]
        cidade = dados["local"].split(" - ")[0].split(",")[0]
        partes = [f"Agora em {cidade} faz {atual['temp']} graus, com {atual['descricao']}."]
        if abs(atual["sensacao"] - atual["temp"]) >= 3:
            partes.append(f"A sensação térmica é de {atual['sensacao']}.")
        if dados["dias"]:
            hoje = dados["dias"][0]
            texto = f"Hoje a máxima é de {hoje['max']} e a mínima de {hoje['min']}"
            if hoje.get("chuva") is not None:
                texto += f", com {hoje['chuva']}% de chance de chuva"
            partes.append(texto + ".")
            if (hoje.get("chuva") or 0) >= 60:
                partes.append("Melhor levar o guarda-chuva.")
        for dia in dados["dias"][1:max(1, min(dias, 7))]:
            nome = "Amanhã" if dia["dia"] == "amanhã" else {"seg": "Segunda", "ter": "Terça", "qua": "Quarta", "qui": "Quinta",
                                                             "sex": "Sexta", "sáb": "Sábado", "dom": "Domingo"}.get(dia["dia"], dia["dia"])
            chuva = f", chuva {dia['chuva']}%" if dia.get("chuva") is not None else ""
            partes.append(f"{nome}: {dia['descricao']}, de {dia['min']} a {dia['max']} graus{chuva}.")
        return " ".join(partes)

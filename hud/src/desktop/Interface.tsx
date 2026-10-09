// Peças fixas do HUD: tempo, status, legendas, doca e barra de comando.
import { useEffect, useRef, useState } from "react";
import { api, comToken } from "../lib/api";
import { conexao } from "../lib/socket";
import { useHud } from "../lib/store";
import type { TipoHolograma } from "../lib/tipos";
import { GlifoTipo, Icone } from "../holograms/Glifos";
import { dataPorExtenso, useAgora } from "../holograms/Relogio";

export function Cabecalho() {
  const agora = useAgora(1000);
  const lembretes = useHud((s) => s.lembretes);
  const nome = useHud((s) => s.prefs?.nome);
  const proximo = lembretes.find((l) => new Date(l.quando).getTime() > agora.getTime());
  const sextou = agora.getDay() === 5 && agora.getHours() >= 16;
  return (
    <div className="absolute left-10 top-8 select-none">
      <p className="numeral text-[112px] leading-[0.82] font-[200] text-gelo brilho" aria-label="Hora atual">
        {String(agora.getHours()).padStart(2, "0")}
        <span className="text-[var(--luz)] pulsando">:</span>
        {String(agora.getMinutes()).padStart(2, "0")}
      </p>
      <p className="mt-3 text-[17px] text-gelo/80 first-letter:uppercase">{dataPorExtenso(agora)}</p>
      {sextou && <p className="mt-1 text-[15px] text-[var(--luz)]">Sextou{nome ? `, ${nome}` : ""}.</p>}
      {proximo && (
        <p className="mt-4 max-w-[340px] text-sm text-aco leading-snug">
          Próximo lembrete: <span className="text-gelo/85">{proximo.texto}</span>, {proximo.descricao}
        </p>
      )}
    </div>
  );
}

function Indicador({ ativo, rotulo, children, aoClicar, alerta }: { ativo: boolean; rotulo: string; children: React.ReactNode; aoClicar?: () => void; alerta?: boolean }) {
  const cor = alerta ? "text-coral" : ativo ? "text-[var(--luz)]" : "text-aco";
  const conteudo = (
    <>
      <span className={cor}>{children}</span>
      <span className={ativo ? "text-gelo/85" : "text-aco"}>{rotulo}</span>
    </>
  );
  return aoClicar ? (
    <button type="button" onClick={aoClicar} className="flex items-center gap-1.5 hover:text-gelo">
      {conteudo}
    </button>
  ) : (
    <span className="flex items-center gap-1.5">{conteudo}</span>
  );
}

export function Status() {
  const conectado = useHud((s) => s.conectado);
  const microfone = useHud((s) => s.microfone);
  const camera = useHud((s) => s.camera);
  const maos = useHud((s) => s.maosLigadas);
  const maosDisponivel = useHud((s) => s.maosDisponivel);
  const modelo = useHud((s) => s.modelo);
  const bloqueio = useHud((s) => s.bloqueio);
  const avisos = useHud((s) => s.avisosSistema);
  const avisar = useHud((s) => s.acoes.avisar);

  const alternarMicrofone = () => api("/api/microfone", { method: "POST", json: { ligado: !microfone } }).catch((e) => avisar(e.message, "erro"));
  const alternarMaos = () => {
    if (!maosDisponivel) return avisar("O modelo das mãos não está instalado. Rode: python -m sexta baixar", "erro");
    conexao.definirMaos(!maos);
    api("/api/maos", { method: "POST", json: { ligar: !maos } }).catch((e) => avisar(e.message, "erro"));
  };

  return (
    <div className="absolute right-10 top-9 flex flex-col items-end gap-3 text-[13px] select-none pointer-events-auto">
      <div className="flex items-center gap-5">
        <Indicador ativo={microfone} rotulo={microfone ? "Microfone" : "Microfone desligado"} aoClicar={alternarMicrofone} alerta={!microfone}>
          {microfone ? <Icone.Microfone tamanho={16} /> : <Icone.MicrofoneDesligado tamanho={16} />}
        </Indicador>
        <Indicador ativo={maos} rotulo={maos ? "Gestos ligados" : "Gestos"} aoClicar={alternarMaos}>
          <Icone.Mao tamanho={16} />
        </Indicador>
        <Indicador ativo={camera} rotulo={camera ? "Câmera ligada" : "Câmera"}>
          <Icone.Camera tamanho={16} />
        </Indicador>
        <Indicador ativo={!bloqueio.bloqueada} rotulo={bloqueio.protecao ? (bloqueio.bloqueada ? "Bloqueada" : "Protegida") : "Sem proteção"}>
          {bloqueio.bloqueada ? <Icone.Cadeado tamanho={16} /> : <Icone.CadeadoAberto tamanho={16} />}
        </Indicador>
      </div>
      <p className="text-xs text-aco">
        {conectado ? nomeCerebro(modelo) : "Reconectando à Sexta-Feira…"}
      </p>
      {Object.entries(avisos).map(([chave, texto]) => (
        <p key={chave} className="max-w-[420px] text-right text-xs text-coral leading-snug">
          {texto}
        </p>
      ))}
    </div>
  );
}

const PALAVRA_ESTADO: Record<string, string> = {
  iniciando: "Iniciando",
  ouvindo: "Ouvindo",
  pensando: "Pensando",
  falando: "Falando",
  verificando: "Confirmando que é você",
};

export function Legendas() {
  const estado = useHud((s) => s.estado);
  const conversa = useHud((s) => s.conversa);
  const ouvido = useHud((s) => s.ouvido);
  const ferramenta = useHud((s) => s.ferramentaAtual);
  const rotina = useHud((s) => s.rotinaAtiva);
  const [visivel, setVisivel] = useState(true);
  const ultimaResposta = [...conversa].reverse().find((l) => l.papel === "assistente");
  const ultimaPergunta = [...conversa].reverse().find((l) => l.papel === "usuario");
  const atualizado = Math.max(ultimaResposta?.ts ?? 0, ultimaPergunta?.ts ?? 0);

  useEffect(() => {
    setVisivel(true);
    if (estado !== "inativa") return;
    const t = window.setTimeout(() => setVisivel(false), 12000);
    return () => window.clearTimeout(t);
  }, [atualizado, estado, ultimaResposta?.texto]);

  const palavra = PALAVRA_ESTADO[estado];
  const pergunta = estado === "ouvindo" || estado === "pensando" ? ouvido || ultimaPergunta?.texto : ultimaPergunta?.texto;
  return (
    <div className="absolute inset-x-0 top-[66%] flex flex-col items-center px-8 text-center pointer-events-none select-none">
      <p className="numeral text-[22px] tracking-[0.06em] font-[300] text-[var(--luz)] h-7 brilho" aria-live="polite">
        {palavra ?? ""}
      </p>
      {(ferramenta || rotina) && (
        <p className="mt-1 text-xs text-aco surgir">
          {rotina ? `Rotina ${rotina.nome}: passo ${rotina.passo} de ${rotina.total}` : `${ferramenta}…`}
        </p>
      )}
      <div className={`mt-4 max-w-[760px] legivel transition-opacity duration-700 ${visivel ? "opacity-100" : "opacity-0"}`}>
        {pergunta && <p className="text-base text-aco leading-snug">{pergunta}</p>}
        {ultimaResposta?.texto && (
          <p className="mt-2 text-[22px] leading-snug text-gelo" aria-live="polite">
            {ultimaResposta.texto}
          </p>
        )}
      </div>
      {estado === "inativa" && !visivel && <p className="text-sm text-aco/70">Diga "Sexta-Feira" ou pressione a barra de espaço.</p>}
    </div>
  );
}

/** "claude-opus-5-5" -> "Cérebro: Claude Opus 5.5"; modelos do Ollama aparecem como estão. */
function nomeCerebro(modelo: string): string {
  if (!modelo.startsWith("claude-")) return `Cérebro local: ${modelo}`;
  const partes = modelo.slice(7).split("-");
  const nome = partes.filter((p) => !/^\d+$/.test(p)).map((p) => p[0].toUpperCase() + p.slice(1));
  const versao = partes.filter((p) => /^\d+$/.test(p)).join(".");
  return `Cérebro: Claude ${nome.join(" ")} ${versao}`.trim();
}

const DOCA: { tipo: TipoHolograma; rotulo: string }[] = [
  { tipo: "clima", rotulo: "Clima" },
  { tipo: "jornal", rotulo: "Jornal" },
  { tipo: "tarefas", rotulo: "Tarefas" },
  { tipo: "lembretes", rotulo: "Lembretes" },
  { tipo: "rotinas", rotulo: "Protocolos" },
  { tipo: "sistema", rotulo: "Sistema" },
  { tipo: "relogio", rotulo: "Relógio" },
  { tipo: "globo", rotulo: "Globo" },
  { tipo: "camera", rotulo: "Câmera" },
  { tipo: "atividades", rotulo: "Atividades" },
];

export function Doca({ abrirAjustes }: { abrirAjustes: () => void }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const abertos = useHud((s) => s.hologramas);
  return (
    <nav aria-label="Hologramas" className="absolute left-5 top-1/2 -translate-y-1/2 flex flex-col gap-1 pointer-events-auto">
      {DOCA.map(({ tipo, rotulo }) => {
        const aberto = abertos.some((h) => h.tipo === tipo);
        return (
          <button
            key={tipo}
            type="button"
            title={rotulo}
            aria-label={`Mostrar ${rotulo}`}
            aria-pressed={aberto}
            onClick={() => {
              const existente = abertos.find((h) => h.tipo === tipo);
              if (existente) api(`/api/hologramas/${existente.id}`, { method: "DELETE" }).catch(() => {});
              else api("/api/hologramas", { method: "POST", json: { tipo } }).catch((e) => avisar(e.message, "erro"));
            }}
            className={`group relative grid place-items-center size-11 rounded-full transition-colors ${
              aberto ? "text-[var(--luz)] bg-[rgb(var(--luz-rgb)/0.1)]" : "text-aco hover:text-gelo"
            }`}
          >
            <GlifoTipo tipo={tipo} tamanho={20} />
            <span className="absolute left-14 whitespace-nowrap text-xs text-gelo/90 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity pointer-events-none">
              {rotulo}
            </span>
          </button>
        );
      })}
      <span className="my-2 mx-auto h-px w-6 bg-aco/30" />
      <button
        type="button"
        title="Ajustes"
        aria-label="Abrir ajustes"
        onClick={abrirAjustes}
        className="group relative grid place-items-center size-11 rounded-full text-aco hover:text-gelo"
      >
        <Icone.Ajustes tamanho={20} />
        <span className="absolute left-14 whitespace-nowrap text-xs text-gelo/90 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
          Ajustes
        </span>
      </button>
    </nav>
  );
}

export function BarraComando() {
  const estado = useHud((s) => s.estado);
  const bloqueada = useHud((s) => s.bloqueio.bloqueada);
  const avisar = useHud((s) => s.acoes.avisar);
  const [texto, setTexto] = useState("");
  const [aberta, setAberta] = useState(false);
  const campo = useRef<HTMLInputElement>(null);
  const ocupada = estado === "pensando" || estado === "falando" || estado === "ouvindo";

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      const digitando = (e.target as HTMLElement)?.closest?.("input, textarea, select");
      if (digitando) return;
      if (e.key === "/") {
        e.preventDefault();
        setAberta(true);
        window.setTimeout(() => campo.current?.focus(), 0);
      } else if (e.code === "Space" && !bloqueada) {
        e.preventDefault();
        api("/api/ouvir", { method: "POST" }).catch((erro) => avisar(erro.message, "erro"));
      } else if (e.key === "Escape") {
        api("/api/parar", { method: "POST" }).catch(() => {});
      }
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [avisar, bloqueada]);

  const enviar = async () => {
    const mensagem = texto.trim();
    if (!mensagem) return;
    setTexto("");
    try {
      await api("/api/conversa", { method: "POST", json: { texto: mensagem } });
    } catch (e: any) {
      avisar(e.message, "erro");
    }
  };

  return (
    <div className="absolute bottom-7 left-1/2 -translate-x-1/2 flex items-center gap-3 pointer-events-auto">
      {aberta ? (
        <form
          className="holo-corpo flex items-center gap-2 w-[min(640px,70vw)] px-4 py-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            enviar();
          }}
        >
          <label htmlFor="comando" className="sr-only">
            Comando para a Sexta-Feira
          </label>
          <input
            id="comando"
            ref={campo}
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setAberta(false);
                (e.target as HTMLInputElement).blur();
              }
            }}
            placeholder="Escreva um pedido, por exemplo: como está o tempo amanhã?"
            autoComplete="off"
            className="flex-1 bg-transparent text-[15px] text-gelo placeholder:text-aco/80 outline-none"
          />
          <button type="submit" aria-label="Enviar" className="p-1.5 text-[var(--luz)] hover:text-gelo">
            <Icone.Enviar tamanho={18} />
          </button>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => {
            setAberta(true);
            window.setTimeout(() => campo.current?.focus(), 0);
          }}
          className="flex items-center gap-2 px-3 py-2 text-sm text-aco hover:text-gelo"
        >
          <Icone.Teclado tamanho={18} /> Escrever
        </button>
      )}
      <button
        type="button"
        aria-label={ocupada ? "Parar" : "Falar com a Sexta-Feira"}
        title={ocupada ? "Parar (Esc)" : "Falar (barra de espaço)"}
        disabled={bloqueada}
        onClick={() =>
          api(ocupada ? "/api/parar" : "/api/ouvir", { method: "POST" }).catch((e) => avisar(e.message, "erro"))
        }
        className="grid place-items-center size-12 rounded-full border border-[var(--luz)]/60 text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)] disabled:opacity-40"
      >
        {ocupada ? <Icone.Parar tamanho={18} /> : <Icone.Microfone tamanho={20} />}
      </button>
    </div>
  );
}

export function Espelho() {
  const maos = useHud((s) => s.maosLigadas);
  const erroCamera = useHud((s) => s.avisosSistema.camera);
  const [mostrar, setMostrar] = useState(true);
  if (!maos) return null;
  return (
    <div className="absolute right-8 bottom-8 w-[220px] select-none pointer-events-auto">
      {mostrar ? (
        <figure className="holo-corpo p-1.5">
          {erroCamera ? (
            <p className="aspect-[4/3] grid place-items-center p-3 text-center text-xs text-coral">{erroCamera}</p>
          ) : (
            <img src={comToken("/api/camera.mjpg")} alt="Sua imagem na câmera, para posicionar as mãos" className="w-full aspect-[4/3] object-cover opacity-80" />
          )}
          <figcaption className="flex items-center justify-between px-1 pt-1.5 text-[11px] text-aco">
            Pinça pega, mão aberta amplia
            <button type="button" className="text-aco hover:text-gelo" onClick={() => setMostrar(false)}>
              Ocultar
            </button>
          </figcaption>
        </figure>
      ) : (
        <button type="button" onClick={() => setMostrar(true)} className="ml-auto block text-xs text-aco hover:text-gelo">
          Mostrar câmera
        </button>
      )}
    </div>
  );
}

export function Avisos() {
  const avisos = useHud((s) => s.avisos);
  const dispensar = useHud((s) => s.acoes.dispensarAviso);
  const alarme = useHud((s) => s.alarme);
  return (
    <>
      <div className="absolute top-6 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 z-[3000]" role="status">
        {avisos.map((a) => (
          <button
            key={a.id}
            type="button"
            onClick={() => dispensar(a.id)}
            className={`holo-corpo surgir max-w-[560px] px-5 py-3 text-left text-[15px] ${
              a.nivel === "erro" ? "text-coral" : a.nivel === "sucesso" ? "text-menta" : "text-gelo"
            }`}
          >
            {a.nivel === "lembrete" && <span className="block text-xs text-[var(--luz)] mb-0.5">Lembrete</span>}
            {a.texto}
          </button>
        ))}
      </div>
      {alarme && (
        <div className="absolute inset-0 z-[4000] grid place-items-center bg-tinta-funda/70 backdrop-blur-sm" role="alertdialog" aria-label="Alarme">
          <div className="text-center">
            <Icone.Alarme tamanho={64} className="mx-auto text-[var(--luz)] pulsando" />
            <p className="mt-4 numeral text-6xl font-[250] text-gelo brilho">{alarme.texto}</p>
            <button
              type="button"
              autoFocus
              onClick={() => api("/api/parar", { method: "POST" }).catch(() => {})}
              className="mt-8 px-8 py-3 rounded-full border border-[var(--luz)] text-[var(--luz)] text-lg hover:bg-[rgb(var(--luz-rgb)/0.12)]"
            >
              Parar alarme
            </button>
          </div>
        </div>
      )}
    </>
  );
}

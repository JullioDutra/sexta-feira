// Telas que cobrem o HUD: bloqueio, primeira configuração, ajustes e falta de acesso.
import { useEffect, useState } from "react";
import { api, comToken } from "../lib/api";
import { useHud } from "../lib/store";
import { Icone } from "../holograms/Glifos";

const FASES_VERIFICACAO: Record<string, string> = {
  inicio: "Olhe para a câmera",
  procurando: "Procurando seu rosto",
  analisando: "Analisando",
  reconhecido: "Reconhecido",
  pisque: "Pisque para confirmar",
  desconhecido: "Não reconheci este rosto",
  ok: "Identidade confirmada",
};

const MOTIVOS: Record<string, string> = {
  windows: "O Windows foi bloqueado",
  inicio: "A Sexta-Feira acabou de iniciar",
  pedido: "Modo privado",
  teste: "Bloqueada",
};

const MOTIVOS_FALHA: Record<string, string> = {
  sem_rosto: "Não vi nenhum rosto. Fique de frente para a câmera, com luz no rosto.",
  desconhecido: "O rosto não confere com o cadastro.",
  sem_piscada: "Reconheci você, mas faltou a piscada.",
  erro: "A câmera não respondeu. Ela está sendo usada por outro programa?",
  cancelado: "Verificação cancelada.",
};

function CampoPin({ aoConfirmar, rotulo = "PIN" }: { aoConfirmar: (pin: string) => Promise<void>; rotulo?: string }) {
  const [pin, setPin] = useState("");
  const [erro, setErro] = useState("");
  return (
    <form
      className="flex flex-col items-center gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        setErro("");
        try {
          await aoConfirmar(pin);
          setPin("");
        } catch (falha: any) {
          setErro(falha.message);
        }
      }}
    >
      <label className="text-xs text-aco" htmlFor="pin">
        {rotulo}
      </label>
      <input
        id="pin"
        inputMode="numeric"
        autoComplete="off"
        type="password"
        maxLength={8}
        value={pin}
        onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
        className="w-40 bg-transparent border-b border-aco/60 text-center numeral text-3xl tracking-[0.4em] text-gelo outline-none focus:border-[var(--luz)]"
      />
      {erro && <p className="text-xs text-coral">{erro}</p>}
      <button type="submit" className="mt-1 text-sm text-[var(--luz)] hover:text-gelo">
        Desbloquear
      </button>
    </form>
  );
}

export function TelaBloqueio() {
  const bloqueio = useHud((s) => s.bloqueio);
  const verificacao = useHud((s) => s.verificacao);
  const temPin = useHud((s) => s.pin);
  const nome = useHud((s) => s.prefs?.nome);
  const [usarPin, setUsarPin] = useState(false);
  if (!bloqueio.bloqueada) return null;

  const emAndamento = verificacao && !["falhou", "ok"].includes(verificacao.fase);
  const fase = verificacao?.fase ?? "";
  const ok = fase === "ok";
  const falhou = fase === "falhou";
  const texto = falhou ? MOTIVOS_FALHA[verificacao?.motivo ?? ""] ?? "Não consegui confirmar." : FASES_VERIFICACAO[fase] ?? MOTIVOS[bloqueio.motivo] ?? "Bloqueada";
  const corAnel = ok ? "var(--color-menta)" : falhou || fase === "desconhecido" ? "var(--color-coral)" : "var(--luz)";

  return (
    <div className="absolute inset-0 z-[3500] flex flex-col items-center justify-center bg-tinta-funda/80 backdrop-blur-md" role="dialog" aria-label="Sexta-Feira bloqueada">
      <div className="relative size-[300px]">
        <div className="absolute inset-0 rounded-full border border-aco/40" />
        <div
          className={`absolute -inset-3 rounded-full border-2 border-transparent ${emAndamento ? "girando" : ""}`}
          style={{ borderTopColor: corAnel, borderRightColor: emAndamento ? corAnel : "transparent", filter: `drop-shadow(0 0 8px ${corAnel})` }}
        />
        {emAndamento ? (
          <img src={comToken("/api/camera.mjpg")} alt="Câmera" className="absolute inset-3 size-[calc(100%-24px)] rounded-full object-cover opacity-90" />
        ) : (
          <div className="absolute inset-3 rounded-full grid place-items-center">
            {ok ? <Icone.CadeadoAberto tamanho={72} className="text-menta" /> : <Icone.Cadeado tamanho={72} className="text-coral/90" />}
          </div>
        )}
      </div>
      <p className="mt-8 numeral text-[34px] font-[300] text-gelo" aria-live="assertive">
        {ok && nome ? `Bem-vindo, ${nome}` : texto}
      </p>
      {fase === "pisque" && <p className="mt-1 text-sm text-aco">Uma piscada natural basta.</p>}
      {!emAndamento && !ok && (
        <div className="mt-8 flex flex-col items-center gap-6">
          <button
            type="button"
            onClick={() => api("/api/desbloquear", { method: "POST", json: { metodo: "rosto" } }).catch(() => {})}
            className="px-6 py-2.5 rounded-full border border-[var(--luz)] text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)]"
          >
            Verificar meu rosto
          </button>
          {temPin &&
            (usarPin ? (
              <CampoPin aoConfirmar={async (pin) => void (await api("/api/desbloquear", { method: "POST", json: { metodo: "pin", pin } }))} />
            ) : (
              <button type="button" onClick={() => setUsarPin(true)} className="text-sm text-aco hover:text-gelo">
                Usar PIN
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------- cadastro do rosto

export function CadastroRosto({ aoTerminar }: { aoTerminar: () => void }) {
  const cadastro = useHud((s) => s.cadastro);
  const rosto = useHud((s) => s.rosto);
  const avisar = useHud((s) => s.acoes.avisar);
  const [iniciado, setIniciado] = useState(false);

  useEffect(() => {
    if (cadastro?.fase === "concluido") {
      useHud.setState({ rosto: { ...(rosto ?? { modelos: true, piscada_disponivel: true }), cadastrado: true } });
      const t = window.setTimeout(aoTerminar, 1500);
      return () => window.clearTimeout(t);
    }
  }, [cadastro?.fase]); // eslint-disable-line react-hooks/exhaustive-deps

  const iniciar = async () => {
    useHud.setState({ cadastro: null });
    try {
      await api("/api/rosto/cadastrar", { method: "POST" });
      setIniciado(true);
    } catch (e: any) {
      avisar(e.message, "erro");
    }
  };

  if (!rosto?.modelos)
    return (
      <p className="text-sm text-coral leading-relaxed">
        Os modelos de reconhecimento facial não estão instalados. Feche a Sexta-Feira, rode <code>python -m sexta baixar</code> e abra de novo.
      </p>
    );

  const progresso = cadastro?.progresso ?? 0;
  const c = 2 * Math.PI * 128;
  return (
    <div className="flex flex-col items-center">
      <div className="relative size-[272px]">
        {iniciado ? (
          <img src={comToken("/api/camera.mjpg")} alt="Câmera" className="absolute inset-4 size-[240px] rounded-full object-cover" />
        ) : (
          <div className="absolute inset-4 rounded-full border border-aco/40 grid place-items-center text-aco">
            <Icone.Camera tamanho={56} />
          </div>
        )}
        <svg className="absolute inset-0" viewBox="0 0 272 272" aria-hidden="true">
          <circle cx="136" cy="136" r="128" fill="none" stroke="rgb(95 124 147 / 0.3)" strokeWidth="3" />
          <circle
            cx="136"
            cy="136"
            r="128"
            fill="none"
            stroke="var(--luz)"
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray={`${progresso * c} ${c}`}
            transform="rotate(-90 136 136)"
            style={{ transition: "stroke-dasharray .3s", filter: "drop-shadow(0 0 6px rgb(var(--luz-rgb)/.8))" }}
          />
        </svg>
      </div>
      <p className="mt-5 text-lg text-gelo min-h-7" aria-live="polite">
        {!iniciado
          ? "Fique de frente para a câmera, com o rosto bem iluminado."
          : cadastro?.fase === "concluido"
            ? "Pronto. Agora eu reconheço você."
            : cadastro?.fase === "erro"
              ? cadastro.mensagem
              : cadastro?.fase === "tempo_esgotado"
                ? "Demorou demais. Vamos tentar de novo?"
                : cadastro?.instrucao ?? "Preparando a câmera…"}
      </p>
      {iniciado && cadastro?.etapas && cadastro.fase === "cadastro" && (
        <p className="text-xs text-aco mt-1">
          Etapa {cadastro.etapa} de {cadastro.etapas}. Só vetores numéricos são salvos, nenhuma foto.
        </p>
      )}
      {(!iniciado || cadastro?.fase === "tempo_esgotado" || cadastro?.fase === "erro") && (
        <button type="button" onClick={iniciar} className="mt-6 px-6 py-2.5 rounded-full border border-[var(--luz)] text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)]">
          {rosto?.cadastrado ? "Cadastrar de novo" : "Começar cadastro"}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------- pareamento

interface Pareamento {
  codigo: string;
  enderecos: { rotulo: string; url: string; qr: string }[];
}

export function ParearCelular() {
  const [dados, setDados] = useState<Pareamento | null>(null);
  const [erro, setErro] = useState("");
  const [escolhido, setEscolhido] = useState(0);
  useEffect(() => {
    api<Pareamento>("/api/pareamento", { method: "POST" })
      .then(setDados)
      .catch((e) => setErro(e.message));
  }, []);
  if (erro) return <p className="text-sm text-coral">{erro}</p>;
  if (!dados) return <p className="text-sm text-aco">Gerando o código…</p>;
  if (!dados.enderecos.length)
    return <p className="text-sm text-aco">O acesso pelo celular está desligado (LIBERAR_CELULAR no arquivo .env).</p>;
  const atual = dados.enderecos[Math.min(escolhido, dados.enderecos.length - 1)];
  return (
    <div className="flex gap-6 items-start">
      <div className="shrink-0 p-2 bg-tinta-funda" dangerouslySetInnerHTML={{ __html: atual.qr }} aria-label="QR code para parear o celular" />
      <div className="text-sm leading-relaxed text-gelo/90 space-y-2">
        <p>Aponte a câmera do celular para o código. O celular precisa estar no mesmo Wi-Fi.</p>
        <p className="text-aco">
          Na primeira vez o navegador avisa que a conexão "não é particular": toque em Avançado e depois em Continuar. É o certificado do seu próprio PC.
        </p>
        <p>
          Ou digite no celular o código <span className="numeral text-2xl text-[var(--luz)] tracking-[0.2em]">{dados.codigo}</span>
        </p>
        {dados.enderecos.length > 1 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {dados.enderecos.map((e, i) => (
              <button
                key={e.url}
                type="button"
                onClick={() => setEscolhido(i)}
                className={`text-xs px-2.5 py-1 rounded-full border ${i === escolhido ? "border-[var(--luz)] text-[var(--luz)]" : "border-aco/40 text-aco"}`}
              >
                {e.rotulo}
              </button>
            ))}
          </div>
        )}
        <p className="text-xs text-aco break-all">{atual.url.split("?")[0]}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- primeira configuração

const PASSOS = ["Você", "Cidade", "Rosto", "Celular", "Pronto"];

function Painel({ titulo, children, largura = 640 }: { titulo: string; children: React.ReactNode; largura?: number }) {
  return (
    <section className="holo-corpo surgir px-8 py-7" style={{ width: largura }} aria-label={titulo}>
      <h2 className="numeral text-[34px] font-[300] text-gelo leading-tight">{titulo}</h2>
      <div className="mt-5">{children}</div>
    </section>
  );
}

function Campo(props: React.InputHTMLAttributes<HTMLInputElement> & { rotulo: string }) {
  const { rotulo, id, ...resto } = props;
  return (
    <label className="block" htmlFor={id}>
      <span className="text-xs text-aco">{rotulo}</span>
      <input
        id={id}
        {...resto}
        className="mt-1 block w-full bg-transparent border-b border-aco/50 py-1.5 text-lg text-gelo outline-none focus:border-[var(--luz)] placeholder:text-aco/60"
      />
    </label>
  );
}

export function PrimeiraConfiguracao() {
  const prefs = useHud((s) => s.prefs);
  const avisar = useHud((s) => s.acoes.avisar);
  const [passo, setPasso] = useState(0);
  const [nome, setNome] = useState(prefs?.nome ?? "");
  const [tratamento, setTratamento] = useState(prefs?.tratamento ?? "chefe");
  const [cidade, setCidade] = useState(prefs?.cidade ?? "");
  const [salvando, setSalvando] = useState(false);
  if (!prefs || prefs.onboarding_concluido) return null;

  const salvar = async (valores: Record<string, unknown>) => {
    setSalvando(true);
    try {
      await api("/api/preferencias", { method: "PATCH", json: valores });
      return true;
    } catch (e: any) {
      avisar(e.message, "erro");
      return false;
    } finally {
      setSalvando(false);
    }
  };
  const avancar = () => setPasso((p) => Math.min(PASSOS.length - 1, p + 1));

  return (
    <div className="absolute inset-0 z-[3200] flex flex-col items-center justify-center bg-tinta-funda/75 backdrop-blur-md">
      <ol className="mb-6 flex gap-6 text-sm" aria-label="Etapas">
        {PASSOS.map((p, i) => (
          <li key={p} className={i === passo ? "text-[var(--luz)]" : i < passo ? "text-gelo/70" : "text-aco/60"} aria-current={i === passo ? "step" : undefined}>
            {p}
          </li>
        ))}
      </ol>
      {passo === 0 && (
        <Painel titulo="Olá. Eu sou a Sexta-Feira.">
          <form
            className="space-y-5"
            onSubmit={async (e) => {
              e.preventDefault();
              if (await salvar({ nome: nome.trim(), tratamento: tratamento.trim() || "chefe" })) avancar();
            }}
          >
            <Campo id="nome" rotulo="Como você se chama?" value={nome} onChange={(e) => setNome(e.target.value)} placeholder="Seu nome" autoFocus />
            <Campo
              id="tratamento"
              rotulo='Como prefere ser chamado nas respostas? (ex.: "chefe", "senhor", seu apelido)'
              value={tratamento}
              onChange={(e) => setTratamento(e.target.value)}
            />
            <Rodape salvando={salvando} textoAvancar="Continuar" />
          </form>
        </Painel>
      )}
      {passo === 1 && (
        <Painel titulo="Onde você está?">
          <form
            className="space-y-5"
            onSubmit={async (e) => {
              e.preventDefault();
              if (!cidade.trim() || (await salvar({ cidade: cidade.trim() }))) avancar();
            }}
          >
            <p className="text-sm text-aco">Uso a cidade para o clima e para marcar você no globo. Fica só no seu computador.</p>
            <Campo id="cidade" rotulo="Cidade (pode incluir o estado)" value={cidade} onChange={(e) => setCidade(e.target.value)} placeholder="Ex.: Belo Horizonte, MG" autoFocus />
            <Rodape salvando={salvando} textoAvancar="Continuar" aoPular={avancar} />
          </form>
        </Painel>
      )}
      {passo === 2 && (
        <Painel titulo="Deixe eu conhecer seu rosto" largura={560}>
          <p className="text-sm text-aco mb-5 leading-relaxed">
            Com o rosto cadastrado, eu só obedeço a você: quando o Windows é bloqueado ou quando você pede modo privado, eu confiro seu rosto
            (com uma piscada, para não aceitar foto) antes de voltar a responder.
          </p>
          <CadastroRosto aoTerminar={avancar} />
          <div className="mt-6 flex justify-end">
            <button type="button" onClick={avancar} className="text-sm text-aco hover:text-gelo">
              Fazer depois
            </button>
          </div>
        </Painel>
      )}
      {passo === 3 && (
        <Painel titulo="Me leve no bolso" largura={700}>
          <ParearCelular />
          <div className="mt-6 flex justify-end">
            <button type="button" onClick={avancar} className="px-5 py-2 rounded-full border border-[var(--luz)] text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)]">
              Continuar
            </button>
          </div>
        </Painel>
      )}
      {passo === 4 && (
        <Painel titulo="Tudo pronto">
          <p className="text-[15px] text-gelo/90 leading-relaxed">Experimente dizer:</p>
          <ul className="mt-3 space-y-1.5 text-[17px] text-gelo">
            <li>"Sexta-Feira, como está o tempo?"</li>
            <li>"Sexta-Feira, me lembra de beber água daqui a 30 minutos."</li>
            <li>"Sexta-Feira, modo trabalho."</li>
            <li>"Sexta-Feira, liga os gestos" e faça uma pinça para pegar um holograma.</li>
          </ul>
          <p className="mt-4 text-sm text-aco">Sem microfone por perto? Aperte a barra de espaço para falar ou "/" para escrever.</p>
          <div className="mt-6 flex justify-end">
            <button
              type="button"
              autoFocus
              onClick={() => salvar({ onboarding_concluido: true })}
              className="px-6 py-2.5 rounded-full border border-[var(--luz)] text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)]"
            >
              Começar
            </button>
          </div>
        </Painel>
      )}
    </div>
  );
}

function Rodape({ salvando, textoAvancar, aoPular }: { salvando: boolean; textoAvancar: string; aoPular?: () => void }) {
  return (
    <div className="flex items-center justify-end gap-5 pt-2">
      {aoPular && (
        <button type="button" onClick={aoPular} className="text-sm text-aco hover:text-gelo">
          Pular
        </button>
      )}
      <button type="submit" disabled={salvando} className="px-5 py-2 rounded-full border border-[var(--luz)] text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)] disabled:opacity-50">
        {salvando ? "Salvando…" : textoAvancar}
      </button>
    </div>
  );
}

export function SemAcesso() {
  return (
    <div className="absolute inset-0 grid place-items-center p-8">
      <section className="holo-corpo max-w-[560px] px-8 py-7">
        <h1 className="numeral text-[34px] font-[300] text-gelo">Falta a chave de acesso</h1>
        <p className="mt-4 text-[15px] text-gelo/85 leading-relaxed">
          Por segurança, o HUD só abre com a chave que a própria Sexta-Feira coloca no endereço. Abra pelo atalho <b>iniciar.bat</b> ou
          rode <code className="text-[var(--luz)]">python -m sexta abrir</code>.
        </p>
      </section>
    </div>
  );
}
